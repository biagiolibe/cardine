"""Configured single-template bootstrap using the shared intent/effect protocol."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

from cardine.lifecycle import receipts
from cardine.lifecycle.file_operation import operation
from cardine.release.version import read_version, require_release_version
from cardine.shared.atomic import file_digest
from cardine.shared.constants import PROTOCOL_VERSION
from cardine.shared.errors import CardineError
from cardine.shared.layout import names
from cardine.shared.project import parse_project_declaration, project_validation_commands
from cardine.tasks.state import STATUSES
from cardine.tasks.status_render import input_digest, render_queue, render_plan_region, splice_region
from cardine.templates.files import latest_migration_to, managed_files
from cardine.templates.manifest import manifest_bytes
from cardine.templates.migrations import migration_ids
from cardine.templates.roots import single_template_root


def _json(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


@dataclass(frozen=True)
class InitPlan:
    root: Path
    outputs: dict[str, bytes]
    directories: tuple[Path, ...]
    binding: dict
    receipt: Path


def _safe(root: Path, target: Path) -> None:
    # Check the caller's spelling before resolving: resolving would hide links.
    for candidate in reversed(target.parents):
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_dir()):
            raise CardineError(f"expected a directory without symlinks: {candidate}")
    if target.is_symlink():
        raise CardineError(f"refusing a symlink: {target}")


def _inspect(plan: InitPlan) -> tuple[dict | None, bool]:
    if plan.binding != _binding(plan.root, plan.outputs):
        raise CardineError("init plan changed after preview; rerun --check")
    intent = receipts._load_intent(plan.receipt) if plan.receipt.exists() else None
    if intent is not None and intent.get("owner") != plan.binding:
        raise CardineError("init inputs or template changed; rerun the original init command")
    files = intent.get("files", {}) if intent else {}
    for relative, output in plan.outputs.items():
        target = plan.root / relative
        _safe(plan.root, target)
        current = file_digest(target)
        record = files.get(relative)
        if record is not None:
            if (record.get("target") != str(target) or record.get("before") is not None
                    or record.get("after") != receipts.digest(output)):
                raise CardineError(f"invalid init ownership for {relative}")
            if current not in (None, record["after"]) or (intent.get("result") and current is None):
                raise CardineError(f"owned init output changed: {relative}")
        elif current is not None:
            raise CardineError(f"init conflicts with existing path: {relative}; use adoption for an existing workflow")
    # An existing task store cannot be represented by the empty initial views.
    task_store = plan.root / names().tasks_path
    _safe(plan.root, task_store / "probe")
    if task_store.exists() and any(task_store.iterdir()):
        raise CardineError("init requires an empty task state store")
    for directory in plan.directories:
        _safe(plan.root, directory / "probe")
    done = bool(intent and intent.get("result"))
    return intent, done


def _binding(root: Path, outputs: dict[str, bytes]) -> dict:
    return {"kind": "init", "anchor": str(root), "digest": receipts.digest(_json({
        key: receipts.digest(value) for key, value in sorted(outputs.items())}))}


def plan_init(project: Path, framework: Path, *, name: str, slug: str, preset: str,
              language: str, task_identity: str, validation: dict) -> InitPlan:
    """Build all bytes without creating a directory, receipt, or generated view."""
    receipts.boundary("before_init_plan")
    root = Path(project).absolute()
    if ".." in root.parts:
        raise CardineError("init project path must not contain '..'")
    for label, value in (("name", name), ("language", language)):
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\n\r\x00"):
            raise CardineError(f"init {label} must be a nonempty single line")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise CardineError("init slug must contain lowercase words separated by hyphens")
    config = parse_project_declaration({
        "version": 1, "project": {"name": name, "slug": slug}, "preset": preset,
        "taskIdentity": {"mode": task_identity}, "validation": validation, "ci": "none",
    })
    require_release_version(framework)
    version = read_version(framework)
    baseline = latest_migration_to(framework, version)
    template = single_template_root(framework)
    outputs = {}
    for source in sorted(template.rglob("*")):
        if source.is_symlink():
            raise CardineError(f"template contains a symlink: {source}")
        if source.is_file():
            relative = source.relative_to(template).as_posix()
            text = source.read_text(encoding="utf-8").replace("[Project Name]", name)
            if relative == "LANGUAGE_POLICY.md":
                text = text.replace("[Conversation language]", language)
            outputs[relative] = text.encode()
    outputs["docs/ARCHITECTURE_DECISIONS.md"] = b"# Architecture Decision Log\n\nNo decisions recorded.\n"
    declaration = names().project_declaration_path.as_posix()
    outputs[declaration] = _json(config)
    # Keep the legacy candidate declaration explicit too, without inventing commands.
    outputs[names().candidate_validation_path.as_posix()] = _json({
        "version": 1, "state": "declared", "outcomes": {
            outcome: list(project_validation_commands(config, outcome))
            for outcome in ("REUSE", "BOUNDED", "FULL")},
    })
    outputs[names().task_identity_path.as_posix()] = _json({"version": 1, "mode": task_identity})
    files = managed_files(framework, "single")
    for item in files:
        outputs[(names().baselines_path / baseline / item.target).as_posix()] = item.source.read_bytes()
    outputs[names().manifest_path.as_posix()] = manifest_bytes({
        "frameworkVersion": version, "protocolVersion": PROTOCOL_VERSION, "workflowMode": "single",
        "workflowBaselineVersion": baseline,
        "managedFiles": {item.target.as_posix(): receipts.digest(item.source.read_bytes()) for item in files},
        "appliedMigrations": migration_ids(framework, "0.0.0", baseline),
    }, framework)
    model = {"preset": preset, "totals": dict.fromkeys((*STATUSES, "total"), 0), "tasks": []}
    digest = input_digest(root, {root / declaration: outputs[declaration]}, set())
    outputs["tasks/QUEUE.md"] = render_queue(model, digest).encode()
    outputs["PROJECT_PLAN.md"] = splice_region(outputs["PROJECT_PLAN.md"], render_plan_region(model, digest))
    directories = {root, root / "tasks/done", root / names().tasks_path}
    for relative in outputs:
        directories.update((root / relative).parents)
    directories = {path for path in directories if path == root or root in path.parents}
    # Missing ancestors are effects too; existing ancestors are never chmodded.
    parent = root.parent
    while not parent.exists():
        directories.add(parent)
        parent = parent.parent
    plan = InitPlan(root, outputs, tuple(sorted(directories, key=lambda p: (len(p.parts), str(p)))),
                    _binding(root, outputs), receipts.host_path("init", root))
    _inspect(plan)
    receipts.boundary("after_init_plan")
    return plan


def apply_init(plan: InitPlan) -> bool:
    """Apply the pinned plan, resuming only its identical, recorded outputs."""
    with operation(plan.receipt, plan.binding, root=plan.root) as active:
        old, done = _inspect(plan)
        if done:
            return False
        # Declare every expected file before the first project write.
        for relative, output in plan.outputs.items():
            active.declare(relative, plan.root / relative, output)
            if active.files[relative]["before"] is not None:
                raise CardineError(f"init path appeared after planning: {relative}")
        owned_dirs = old.get("paths", {}) if old else {}
        for directory in plan.directories:
            label = str(directory)
            if not directory.exists() or label in owned_dirs:
                active.directory(label, directory, 0o755)
        for relative, output in plan.outputs.items():
            active.run(relative, output)
        receipts.boundary("before_init_result")
    receipts.boundary("after_init_result")
    return True


def init_cli(arguments, framework: Path) -> int:
    try:
        validation = json.loads(arguments.validation.read_text(encoding="utf-8"))
        plan = plan_init(arguments.project, framework, name=arguments.name, slug=arguments.slug,
                         preset=arguments.preset, language=arguments.language,
                         task_identity=arguments.task_identity, validation=validation)
        print(f"init plan: {plan.root}; digest {plan.binding['digest']}")
        print("choices: " + json.dumps(json.loads(plan.outputs[names().project_declaration_path.as_posix()]), sort_keys=True))
        print(f"conversation language: {arguments.language}")
        for relative in plan.outputs:
            print(f"project output: {relative}")
        for directory in plan.directories:
            print(f"project directory: {directory}")
        if arguments.apply:
            print("result: initialized" if apply_init(plan) else "result: no-op")
            print("Machine setup is separate: preview with `cardine setup --check`.")
        return 0
    except (CardineError, OSError, ValueError, UnicodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
