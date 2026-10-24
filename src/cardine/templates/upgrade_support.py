from __future__ import annotations

from cardine.shared.layout import names

from cardine.release.version import read_version
from cardine.shared.constants import STRICT_DIGEST_PROFILES
from cardine.shared.hashing import sha256
from cardine.shared.models import ManagedFile
from cardine.shared.models import PlanItem
from cardine.stops.render import format_stop
from cardine.templates.audit import _digest_exempt
from cardine.templates.catalog import load_capability_catalog
from cardine.templates.catalog import manifest_workflow_mode
from cardine.templates.catalog import parse_capability_profiles
from cardine.templates.files import capped_managed_files
from cardine.templates.files import latest_migration_to
from cardine.templates.files import manifest_baseline_version
from cardine.templates.manifest import load_manifest
from cardine.templates.migrations import capped_target_version
from cardine.templates.migrations import migration_ids
from pathlib import Path
import json
import shlex
import tempfile


def recorded_managed_digests(project_root: Path) -> dict[str, object]:
    try:
        recorded = json.loads((project_root / names().manifest_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    digests = recorded.get("managedFiles") if isinstance(recorded, dict) else None
    return dict(digests) if isinstance(digests, dict) else {}



def profile_surface_plan(
    project_root: Path, framework_root: Path, manifest: dict[str, object]
) -> list[PlanItem]:
    """One row per profile capability whose declared surface is a strict subset
    of the target catalog surface. A managed copy that drifted from its recorded
    digest is a conflict here, so apply stops before it writes anything."""
    catalog = load_capability_catalog(framework_root)
    gaps: list[tuple[str, str, tuple[str, ...]]] = []
    parse_capability_profiles(manifest, catalog, gaps)
    recorded = recorded_managed_digests(project_root)
    items: list[PlanItem] = []
    for profile_id, capability_id, missing in gaps:
        capability = catalog.capability(capability_id)
        assert capability is not None
        label = f"{profile_id}/{capability_id}"
        drifted = [
            surface.path
            for surface in capability.managed_surfaces
            if surface.forms[0] == "managed-copy"
            and (project_root / surface.path).is_file()
            and recorded.get(surface.path) not in (None, sha256(project_root / surface.path))
            and not (
                profile_id not in STRICT_DIGEST_PROFILES
                and _digest_exempt(surface.path, project_root / surface.path)
            )
        ]
        target = ManagedFile(framework_root / missing[0], Path(missing[0]))
        if drifted:
            items.append(
                PlanItem(
                    target,
                    "conflict",
                    f"{label}: managed copy {', '.join(drifted)} differs from the digest recorded at "
                    "install; restore the released text before upgrading",
                    profile_surface=(profile_id, capability_id),
                )
            )
        else:
            items.append(
                PlanItem(
                    target,
                    "profile-surface",
                    f"{label}: add {', '.join(missing)}",
                    profile_surface=(profile_id, capability_id),
                )
            )
    return items



def prepare_upgrade_targets(
    project_root: Path, framework_root: Path, stop_before_retirement: bool
) -> tuple[dict[str, object], str | None, list[ManagedFile] | None]:
    """The manifest, plus an effective target-version cap and matching
    managed-files substitution when `--stop-before-retirement` is set and it
    actually narrows the upgrade. Both are `None` when the flag is unset, or
    the pending migrations contain no retirement-stage move (a full,
    unmodified upgrade)."""
    manifest = load_manifest(project_root, framework_root, defer_surface_gaps=True)
    if not stop_before_retirement:
        return manifest, None, None
    installed_version = manifest_baseline_version(manifest)
    full_target = read_version(framework_root)
    capped_target = capped_target_version(framework_root, installed_version, full_target)
    if capped_target == full_target:
        return manifest, None, None
    applied = {str(migration) for migration in manifest.get("appliedMigrations", [])}
    full_pending = set(migration_ids(framework_root, installed_version, full_target)) - applied
    capped_pending = set(migration_ids(framework_root, installed_version, capped_target)) - applied
    excluded = full_pending - capped_pending
    scratch_dir = Path(tempfile.mkdtemp(prefix="cardine-capped-"))
    baseline_root = project_root / names().baselines_path / installed_version
    managed_override = capped_managed_files(
        framework_root, manifest_workflow_mode(manifest), baseline_root, excluded, scratch_dir
    )
    return manifest, capped_target, managed_override



def print_plan(
    project_root: Path,
    manifest: dict[str, object],
    framework_root: Path,
    plan: list[PlanItem],
    target_version_override: str | None = None,
) -> None:
    target_version = target_version_override or read_version(framework_root)
    installed_baseline_version = manifest_baseline_version(manifest)
    target_baseline_version = latest_migration_to(framework_root, target_version)
    print(
        f"Cardine {installed_baseline_version} -> {target_baseline_version} "
        f"({manifest_workflow_mode(manifest)})"
    )
    framework_delta = f"Framework: {manifest['frameworkVersion']} -> {target_version}"
    if (
        str(manifest["frameworkVersion"]) != target_version
        and installed_baseline_version == target_baseline_version
    ):
        framework_delta += " (CLI-only; no baseline change)"
    print(framework_delta)
    applied = {str(item) for item in manifest.get("appliedMigrations", [])}
    pending = [
        migration
        for migration in migration_ids(
            framework_root, installed_baseline_version, target_baseline_version
        )
        if migration not in applied
    ]
    for migration in pending:
        print(f"MIGRATION {migration}")
    for item in plan:
        if item.action == "profile-surface":
            print(f"PROFILE-SURFACE {item.detail}")
            continue
        print(f"{item.action.upper():8} {item.file.target} — {item.detail}")
        for problem in item.problems:
            print(f"MISSING-ROUTER {problem}")
    pending = missing_generated_outputs(project_root, plan)
    if pending:
        print(format_stop(
            "UPGRADE_OUTPUT_PENDING", "missing generated output: " + ", ".join(pending),
            resume=shlex.join(("cardine", "--framework-root", str(framework_root.resolve()),
                               "upgrade", "--check", "--project", str(project_root.resolve()))),
        ))
    conflicts = sum(item.action == "conflict" for item in plan)
    edited_copies = sum(item.action == "edited-copy" for item in plan)
    router_blockers = sum(bool(item.problems) for item in plan)
    if edited_copies:
        print(f"WARNING: {edited_copies} edited managed copy/copies will fail the digest audit after upgrade.")
    if conflicts:
        print(format_stop("UPGRADE_BLOCKED", f"{conflicts} conflict(s); no files were changed"))
    if router_blockers:
        print(format_stop("UPGRADE_BLOCKED", f"{router_blockers} router requirement(s); no files were changed"))



def plan_has_blockers(plan: list[PlanItem], owner_reconciled: bool = False) -> bool:
    """Whether apply/check must stop before writing any project file."""
    return any(item.problems or (item.action == "conflict" and not owner_reconciled) for item in plan)



def _unused_adoption_backup(path: Path, kind: str = "pre-adoption") -> Path:
    """Choose a deterministic adjacent backup path without reusing an existing name."""
    first = path.with_name(path.name + f".cardine-{kind}.bak")
    if not first.exists():
        return first
    suffix = 1
    while True:
        candidate = first.with_name(first.name + f".{suffix}")
        if not candidate.exists():
            return candidate
        suffix += 1



def missing_generated_outputs(project_root: Path, plan: list[PlanItem]) -> tuple[str, ...]:
    """Identify absent generated outputs without treating project edits as ours.

    A normal upgrade already regenerates these outputs. This diagnostic neither
    writes them nor bypasses apply consent; invalid sources retain their error.
    """
    from cardine.templates.router import entry_router_outputs
    candidates = [item for item in plan if item.action == "router"]
    if not candidates or plan_has_blockers(plan):
        return ()
    outputs = entry_router_outputs(project_root)
    return tuple(str(item.file.target) for item in candidates
                 if item.file.target in outputs
                 and not (project_root / item.file.target).exists()
                 and not (project_root / item.file.target).is_symlink())
