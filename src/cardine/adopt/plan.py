"""Read-only adoption planning and guardrails."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path

from cardine.adopt.config import map_config, validate_flow_targets
from cardine.adopt.records import translate_record
from cardine.legacy.conversion_reader import read_legacy_project
from cardine.legacy.meridian_installation import is_meridian_installation
from cardine.lifecycle import receipts
from cardine.shared.git import _run_git, canonical_git_common_dir, git_output, parse_worktree_records
from cardine.templates.init import plan_init


@dataclass(frozen=True)
class AdoptPlan:
    case: str
    outputs: dict[str, bytes]
    diagnostics: tuple[str, ...]
    missing: tuple[str, ...]
    refusals: tuple[str, ...]
    dropped_dependencies: dict[str, tuple[str, ...]]

    dropped_validation: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def bytes(self):
        value = {"case": self.case, "operations": [
            {"path": path, "digest": hashlib.sha256(data).hexdigest()}
            for path, data in sorted(self.outputs.items())],
            "diagnostics": self.diagnostics, "missing": self.missing,
            "refusals": self.refusals, "dropped_dependencies": self.dropped_dependencies,
            "dropped_validation": self.dropped_validation}
        return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def plan_adopt(project: Path, framework: Path, *, name=None, slug=None, preset=None,
               language=None, task_identity=None, validation=None, ci="none"):
    """Describe a conversion without writing either project or host state."""
    receipts.boundary("before_adopt_plan")
    root = Path(project).resolve()
    legacy_case = is_meridian_installation(root)
    refusals = []
    git_probe = _run_git(root, "rev-parse", "--show-toplevel") if root.is_dir() else None
    if git_probe is not None and git_probe.returncode == 0:
        if git_output(root, "status", "--porcelain", "--untracked-files=all"):
            refusals.append("ADOPT_DIRTY")
        records = parse_worktree_records(git_output(root, "worktree", "list", "--porcelain"))
        if any(item.get("branch", "").startswith("refs/heads/task-") for item in records):
            refusals.append("ADOPT_WORKTREE")
        common = canonical_git_common_dir(root)
        if any((common / lease_name).exists() for lease_name in ("meridian-integration.lock", "meridian-integration.json")):
            refusals.append("ADOPT_LEASE")
    missing = [key for key, value in (("name", name), ("slug", slug),
               ("language", language), ("validation", validation)) if value is None]
    if not legacy_case:
        missing += [key for key, value in (("preset", preset), ("task_identity", task_identity)) if value is None]
        if missing:
            return AdoptPlan("A", {}, (), tuple(missing), tuple(refusals), {})
        init = plan_init(root, framework, name=name, slug=slug, preset=preset,
                         language=language, task_identity=task_identity, validation=validation)
        return AdoptPlan("A", init.outputs, (), (), tuple(refusals), {})
    legacy = read_legacy_project(root)
    diagnostics = list(legacy.diagnostics)
    if legacy.in_progress_rows:
        refusals.append("ADOPT_IN_PROGRESS")
    outputs = {}
    dropped = {}
    dropped_validation = {}
    if name is not None and slug is not None:
        config = map_config(legacy, name=name, slug=slug, validation=validation, ci=ci)
        outputs[".cardine/project.json"] = (json.dumps(config, indent=2, sort_keys=True) + "\n").encode()
    outputs[".cardine/task-identity.json"] = (json.dumps({"version": 1, "mode": legacy.identity_mode}, indent=2, sort_keys=True) + "\n").encode()
    if legacy.flow_targets is not None:
        try:
            targets = validate_flow_targets(legacy.flow_targets)
            outputs[".cardine/flow-targets.json"] = (json.dumps(targets, indent=2, sort_keys=True) + "\n").encode()
        except ValueError as error:
            diagnostics.append(str(error))
    if legacy.mode == "governed-sdd":
        diagnostics.append("governed tasks require review; review recording is not yet available")
    open_ids = {row.task_id for row in legacy.open_rows}
    for task_id in sorted(open_ids):
        matches = []
        for task_root in legacy.locations.task_roots:
            for path in (root / task_root).rglob("*.md"):
                if path.name == task_id + ".md" or path.name.startswith(task_id + "-"):
                    if not {"done", "handoffs", "reviews"}.intersection(path.relative_to(root).parts):
                        matches.append(path)
        if len(matches) != 1:
            diagnostics.append(f"{task_id}: expected one task record, found {len(matches)}")
            continue
        profile_path = root / "docs/EXECUTION_EVIDENCE_PROFILE.md"
        result = translate_record(matches[0].read_text(encoding="utf-8"), open_ids=open_ids,
                                  closed_ids=set(legacy.closed_ids),
                                  profile=profile_path.read_bytes() if profile_path.is_file() else None)
        diagnostics.extend(f"{task_id}: {message}" for message in result.diagnostics)
        if result.text is not None:
            outputs[matches[0].relative_to(root).as_posix()] = result.text.encode()
        if result.dropped_dependencies:
            dropped[task_id] = result.dropped_dependencies
        if result.dropped_validation:
            dropped_validation[task_id] = result.dropped_validation
    if any(not item.startswith("governed tasks require review") for item in diagnostics):
        refusals.append("ADOPT_RECORD")
    return AdoptPlan("B", outputs, tuple(diagnostics), tuple(missing), tuple(refusals), dropped, dropped_validation)
