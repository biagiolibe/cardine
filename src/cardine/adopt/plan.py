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
from cardine.shared.atomic import file_digest
from cardine.shared.layout import names
from cardine.shared.project_defaults import resolve_choices
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
    # Case A: digest of each existing file an output was fitted around, at planning.
    existing: dict[str, str] = field(default_factory=dict)
    choices: dict = field(default_factory=dict)

    def bytes(self):
        value = {"case": self.case, "operations": [
            {"path": path, "digest": hashlib.sha256(data).hexdigest()}
            for path, data in sorted(self.outputs.items())],
            "diagnostics": self.diagnostics, "missing": self.missing,
            "refusals": self.refusals, "dropped_dependencies": self.dropped_dependencies,
            "dropped_validation": self.dropped_validation, "choices": self.choices}
        if self.existing:
            value["existing"] = self.existing
        return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def keep_project_files(root: Path, outputs: dict[str, bytes]) -> tuple[dict[str, bytes], dict[str, str], list[str]]:
    """Fit the initial outputs around the files a project without a workflow already has.

    A managed file keeps the project's text after the template. Any other existing
    file stays as it is. Cardine state, the generated queue, and JSON files cannot
    merge and are conflicts.
    """
    manifest = json.loads(outputs[names().manifest_path.as_posix()])
    managed = set(manifest.get("managedFiles", {}))
    result, existing, conflicts = {}, {}, []
    for name, content in outputs.items():
        path = root / name
        if not path.exists() and not path.is_symlink():
            result[name] = content
            continue
        if path.is_file() and not path.is_symlink():
            existing[name] = file_digest(path)
        if (name.startswith(names().project_directory + "/") or name == "tasks/QUEUE.md"
              or name.endswith(".json") or path.is_symlink() or not path.is_file()):
            conflicts.append(name)
        elif name in managed:
            old = path.read_text(encoding="utf-8")
            result[name] = content if not old.strip() else content.rstrip() + b"\n\n" + old.encode()
    return result, {name: digest for name, digest in existing.items() if name in result}, sorted(conflicts)


def plan_adopt(project: Path, framework: Path, *, name=None, slug=None, preset=None,
               language=None, task_identity=None, validation=None, test=None, ci="none"):
    """Describe a conversion without writing either project or host state."""
    receipts.boundary("before_adopt_plan")
    root = Path(project).resolve()
    legacy_case = is_meridian_installation(root)
    legacy = read_legacy_project(root) if legacy_case else None
    installed = {}
    if legacy:
        declaration = legacy.declaration or {}
        project_info = declaration.get("project", {})
        installed = {"name": project_info.get("name"), "slug": project_info.get("slug"),
                     "preset": ("governed" if legacy.mode == "governed-sdd" else "lean") if legacy.mode else None,
                     "task_identity": legacy.identity_mode, "validation": declaration.get("validation")}
        policy = root / "LANGUAGE_POLICY.md"
        if policy.is_file():
            import re
            match = re.search(r"\*\*Conversation language:\*\*\s*`([^`]+)`", policy.read_text(encoding="utf-8"))
            if match:
                installed["language"] = match.group(1)
    choices = resolve_choices(root, name=name, slug=slug, preset=preset, language=language,
                              task_identity=task_identity, validation=validation, test=test, installation=installed)
    name, slug, preset, language, task_identity, validation = (choices[key]["value"] for key in
        ("name", "slug", "preset", "language", "task_identity", "validation"))
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
            return AdoptPlan("A", {}, (), tuple(missing), tuple(refusals), {}, choices=choices)
        init = plan_init(root, framework, name=name, slug=slug, preset=preset,
                         language=language, task_identity=task_identity, validation=validation,
                         refuse_existing=False)
        outputs, existing, conflicts = keep_project_files(root, init.outputs)
        if conflicts:
            refusals.append("ADOPT_RECORD")
        return AdoptPlan("A", outputs, tuple(f"existing path conflicts with adoption: {name}"
                                             for name in conflicts), (), tuple(refusals), {},
                         existing=existing, choices=choices)
    diagnostics = list(legacy.diagnostics)
    if legacy.in_progress_rows:
        refusals.append("ADOPT_IN_PROGRESS")
    outputs = {}
    dropped = {}
    dropped_validation = {}
    if name is not None and slug is not None:
        config = map_config(legacy, name=name, slug=slug, validation=validation, ci=ci)
        config["preset"] = preset
        config["taskIdentity"]["mode"] = task_identity
        outputs[".cardine/project.json"] = (json.dumps(config, indent=2, sort_keys=True) + "\n").encode()
    outputs[".cardine/task-identity.json"] = (json.dumps({"version": 1, "mode": task_identity}, indent=2, sort_keys=True) + "\n").encode()
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
    return AdoptPlan("B", outputs, tuple(diagnostics), tuple(missing), tuple(refusals), dropped, dropped_validation, choices=choices)
