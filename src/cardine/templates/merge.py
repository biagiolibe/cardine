from __future__ import annotations

from cardine.release.version import read_version
from cardine.release.version import require_release_version
from cardine.release.version import version_key
from cardine.shared.constants import BASELINES_PATH
from cardine.shared.constants import ENTRY_ROUTER_PATH
from cardine.shared.constants import PROTOCOL_VERSION
from cardine.shared.errors import MeridianError
from cardine.shared.hashing import sha256
from cardine.shared.models import ManagedFile
from cardine.shared.models import PlanItem
from cardine.templates.audit import declared_managed_copy_paths
from cardine.templates.audit import is_markerless_managed_copy_digest_audited
from cardine.templates.files import latest_migration_to
from cardine.templates.files import managed_files
from cardine.templates.manifest import write_manifest
from cardine.templates.marker_history import declared_capability_moves
from cardine.templates.marker_history import pending_migration_establishes_move_source
from cardine.templates.markers import CLAUDE_AGENTS_POINTER_MARKER
from cardine.templates.markers import agents_pointer_can_follow_upgrade
from cardine.templates.markers import agents_pointer_satisfies_claude
from cardine.templates.markers import append_only_new_markers
from cardine.templates.markers import capability_ids_in_template
from cardine.templates.markers import deduplicate_identical_template_markers
from cardine.templates.markers import exact_marker_matches
from cardine.templates.markers import extract_marker_block
from cardine.templates.markers import is_agents_pointer
from cardine.templates.markers import marker_blocks
from cardine.templates.markers import marker_pairs
from cardine.templates.markers import reflowed_marker_normalization
from cardine.templates.markers import remove_retired_markers
from cardine.templates.migration_audit import removals_for_managed_file
from cardine.templates.migrations import adopt_existing_paths
from cardine.templates.migrations import capability_requirements
from cardine.templates.migrations import migration_ids
from cardine.templates.migrations import pending_restructured_markers
from cardine.templates.migrations import pending_wrapped_capabilities
from cardine.templates.migrations import project_sections
from cardine.templates.migrations import restructured_marker_edits
from cardine.templates.router import entry_router_trigger_requirements
from cardine.templates.router import project_uses_entry_router
from cardine.templates.upgrade_support import _unused_adoption_backup
from cardine.templates.upgrade_support import profile_surface_plan
from pathlib import Path
import shutil
import subprocess
import tempfile


def copy_baseline(
    project_root: Path,
    framework_root: Path,
    mode: str,
    version: str,
    managed_files_override: list[ManagedFile] | None = None,
) -> None:
    destination_root = project_root / BASELINES_PATH / version
    for item in managed_files_override or managed_files(framework_root, mode):
        destination = destination_root / item.target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.source, destination)



def prune_stale_baselines(project_root: Path, keep_version: str) -> None:
    """Remove every baseline snapshot except the one the manifest now points at.

    Only the baseline matching `manifest.workflowBaselineVersion` is ever read again
    (see `plan_upgrade`); older snapshots are dead weight the moment an
    upgrade or adoption completes.
    """
    baselines_root = project_root / BASELINES_PATH
    if not baselines_root.is_dir():
        return
    for entry in baselines_root.iterdir():
        if entry.is_dir() and entry.name != keep_version:
            shutil.rmtree(entry)



def lock_project(
    project_root: Path,
    framework_root: Path,
    mode: str,
) -> None:
    require_release_version(framework_root)
    version = read_version(framework_root)
    baseline_version = latest_migration_to(framework_root, version)
    files = managed_files(framework_root, mode)
    missing = [str(item.target) for item in files if not (project_root / item.target).is_file()]
    if missing:
        raise MeridianError("project is missing managed files: " + ", ".join(missing))

    copy_baseline(project_root, framework_root, mode, baseline_version)
    manifest = {
        "frameworkVersion": version,
        "protocolVersion": PROTOCOL_VERSION,
        "workflowMode": mode,
        "managedFiles": {str(item.target): sha256(item.source) for item in files},
        "appliedMigrations": migration_ids(framework_root, "0.0.0", baseline_version),
    }
    manifest["workflowBaselineVersion"] = baseline_version
    write_manifest(project_root, manifest, framework_root)
    print(f"Locked {project_root} to Meridian {version} ({mode}).")



def merge_clean(local: Path, base: Path, incoming: Path) -> tuple[bool, bytes]:
    with tempfile.TemporaryDirectory(prefix="meridian-merge-") as directory:
        output = Path(directory) / "merged"
        process = subprocess.run(
            ["git", "merge-file", "-p", str(local), str(base), str(incoming)],
            check=False,
            capture_output=True,
        )
        # git merge-file returns the number of conflicts (not merely 1) for a
        # successful merge operation with conflict markers. Only 128+ signals
        # a command failure.
        if process.returncode >= 128:
            detail = process.stderr.decode("utf-8", errors="replace").strip()
            raise MeridianError(detail or "git merge-file failed")
        output.write_bytes(process.stdout)
        return process.returncode == 0, output.read_bytes()



def apply_additive_move_checks(
    plan: list[PlanItem],
    project_root: Path,
    framework_root: Path,
    mode: str,
    baseline_root: Path,
    pending_migrations: list[str],
) -> list[PlanItem]:
    """Turn unsafe pending additive moves into deterministic upgrade conflicts.

    A normal three-way merge only reasons about whole files. A capability move
    instead proves the protected block itself: the old marker must be identical
    to the installed baseline, while unrelated project-owned text in that file
    remains eligible for preservation. A pre-created destination may be
    retained only if it is the exact released marker block.
    """
    by_target = {item.file.target: index for index, item in enumerate(plan)}
    derived_entry_points = {
        item.file.target for item in plan if item.action == "router"
    }

    def conflict(target: Path, detail: str) -> None:
        index = by_target[target]
        plan[index] = PlanItem(plan[index].file, "conflict", detail)

    for move in declared_capability_moves(framework_root, pending_migrations):
        if move.stage not in ("additive", "retirement"):
            continue
        if move.source_path in derived_entry_points or move.target_path in derived_entry_points:
            continue
        source_base = baseline_root / move.source_path
        source_local = project_root / move.source_path
        if not source_base.is_file() or not source_local.is_file():
            conflict(move.source_path, f"capability move {move.migration} source baseline or local file is missing")
            continue
        base_text = source_base.read_text(encoding="utf-8")
        local_text = source_local.read_text(encoding="utf-8")
        if move.source_path == Path("CLAUDE.md") and is_agents_pointer(local_text):
            # A declared pointer deliberately owns no duplicated Claude marker;
            # the matching AGENTS move supplies the source proof instead.
            continue
        source_in_intermediate_state = False
        if not exact_marker_matches(base_text, move.source_capability, move.source_version, move.source_sha256):
            source_in_intermediate_state = (
                not marker_blocks(base_text, move.source_capability, move.source_version)
                and not marker_blocks(local_text, move.source_capability, move.source_version)
                and pending_migration_establishes_move_source(
                    framework_root, pending_migrations, move
                )
            )
            if not source_in_intermediate_state:
                conflict(move.source_path, f"capability move {move.migration} source does not match the installed baseline")
                continue
        if not source_in_intermediate_state and not exact_marker_matches(
            local_text, move.source_capability, move.source_version, move.source_sha256
        ):
            conflict(move.source_path, f"capability move {move.migration} source marker was locally modified or duplicated")
            continue
        target_local = project_root / move.target_path
        if target_local.is_file():
            target_text = target_local.read_text(encoding="utf-8")
            if not exact_marker_matches(
                target_text, move.target_capability, move.target_version, move.target_sha256
            ):
                conflict(move.target_path, f"capability move {move.migration} target marker is not exact")
                continue
            current = plan[by_target[move.target_path]]
            if move.stage == "additive" and current.action == "conflict" and not (baseline_root / move.target_path).is_file():
                plan[by_target[move.target_path]] = PlanItem(
                    current.file,
                    "keep",
                    f"pre-created target marker for capability move {move.migration} is exact",
                )
        elif move.stage == "retirement":
            planned_target = plan[by_target[move.target_path]]
            incoming_target = planned_target.file.source.read_text(encoding="utf-8")
            if planned_target.action != "add" or not exact_marker_matches(
                incoming_target, move.target_capability, move.target_version, move.target_sha256
            ):
                conflict(move.target_path, f"capability move {move.migration} target file is missing")
        if move.stage == "retirement":
            current = plan[by_target[move.source_path]]
            if current.action == "append-markers":
                plan[by_target[move.source_path]] = PlanItem(
                    current.file,
                    "append-retire-markers",
                    "update required marker versions, then retire declared duplicate marker blocks "
                    "without touching other local text",
                )
    return plan



def plan_from_baseline(
    project_root: Path,
    framework_root: Path,
    mode: str,
    installed_version: str,
    baseline_root: Path,
    applied_migrations: list[object],
    target_version_override: str | None = None,
    managed_files_override: list[ManagedFile] | None = None,
    installed_framework_version: str | None = None,
    capability_profiles: object | None = None,
) -> tuple[dict[str, object], list[PlanItem]]:
    target_framework_version = target_version_override or read_version(framework_root)
    target_baseline_version = latest_migration_to(framework_root, target_framework_version)
    if version_key(target_baseline_version) < version_key(installed_version):
        raise MeridianError("framework source is older than the project lockfile")
    if not baseline_root.is_dir():
        raise MeridianError(f"baseline snapshot is missing: {baseline_root}")

    manifest: dict[str, object] = {
        "frameworkVersion": installed_framework_version or installed_version,
        "workflowBaselineVersion": installed_version,
        "workflowMode": mode,
        "appliedMigrations": applied_migrations,
    }
    if capability_profiles is not None:
        manifest["capabilityProfiles"] = capability_profiles
        manifest["protocolVersion"] = PROTOCOL_VERSION

    requirements = capability_requirements(framework_root)
    applied = {str(migration) for migration in applied_migrations}
    pending_migrations = [
        migration
        for migration in migration_ids(framework_root, installed_version, target_baseline_version)
        if migration not in applied
    ]
    adoptable_paths = adopt_existing_paths(framework_root, pending_migrations)

    planned_files = managed_files_override or managed_files(framework_root, mode)
    declared_copy_paths = declared_managed_copy_paths(manifest, framework_root)
    router_project = project_uses_entry_router(project_root)
    router_problems = entry_router_trigger_requirements(
        project_root, framework_root, pending_migrations, planned_files
    )
    router_problem_owner = Path("AGENTS.md")

    plan = []
    for item in planned_files:
        if router_project and item.target in {Path("AGENTS.md"), Path("CLAUDE.md")}:
            plan.append(
                PlanItem(
                    item,
                    "router",
                    f"generated from {ENTRY_ROUTER_PATH}; template merge is disabled",
                    router_problems if item.target == router_problem_owner else (),
                )
            )
            continue
        local = project_root / item.target
        base = baseline_root / item.target
        if not base.is_file():
            if local.exists():
                if item.target not in adoptable_paths or not local.is_file():
                    plan.append(PlanItem(item, "conflict", "managed baseline is missing"))
                elif sha256(local) == sha256(item.source):
                    plan.append(
                        PlanItem(
                            item,
                            "adopt",
                            "existing file matches target; record the managed baseline",
                        )
                    )
                else:
                    backup = _unused_adoption_backup(local).relative_to(project_root)
                    plan.append(
                        PlanItem(
                            item,
                            "adopt-replace",
                            f"replace existing file after preserving it as {backup}",
                            backup=backup,
                        )
                    )
            else:
                plan.append(PlanItem(item, "add", "new managed file"))
            continue
        if not local.is_file():
            plan.append(PlanItem(item, "conflict", "local managed file is missing"))
            continue
        if (
            sha256(local) != sha256(base)
            and is_markerless_managed_copy_digest_audited(
                project_root, str(item.target), declared_copy_paths
            )
        ):
            plan.append(
                PlanItem(
                    item,
                    "edited-copy",
                    "local edits will remain outside the released digest and make `meridian audit` fail; "
                    "restore the released text and keep project content in the project's own files",
                )
            )
        if sha256(item.source) == sha256(base):
            local_text = local.read_text(encoding="utf-8")
            if (
                item.target == Path("CLAUDE.md")
                and CLAUDE_AGENTS_POINTER_MARKER not in local_text
                and "036-explicit-claude-agents-pointer" in pending_migrations
                and agents_pointer_satisfies_claude(
                    project_root, framework_root, mode, item.source.read_text(encoding="utf-8"), local_text
                )
            ):
                plan.append(
                    PlanItem(
                        item,
                        "pointer-upgrade",
                        "add the explicit Claude-to-AGENTS pointer marker without changing project-owned pointer text",
                    )
                )
                continue
            normalized = deduplicate_identical_template_markers(
                local_text, item.source.read_text(encoding="utf-8")
            )
            if normalized is not None:
                plan.append(
                    PlanItem(
                        item,
                        "deduplicate-markers",
                        "template unchanged, but local file contains duplicate identical protected marker(s)",
                    )
                )
            else:
                plan.append(PlanItem(item, "keep", "template unchanged"))
        elif sha256(local) == sha256(base):
            plan.append(PlanItem(item, "replace", "local file matches installed baseline"))
        elif sha256(local) == sha256(item.source):
            plan.append(PlanItem(item, "keep", "local file already matches target"))
        else:
            clean, merged = merge_clean(local, base, item.source)
            if clean:
                merged_text = merged.decode("utf-8")
                if deduplicate_identical_template_markers(
                    merged_text, item.source.read_text(encoding="utf-8")
                ) is not None:
                    plan.append(
                        PlanItem(
                            item,
                            "merge-deduplicate-markers",
                            "three-way merge duplicated an identical new protected marker; retain one canonical copy",
                        )
                    )
                else:
                    plan.append(PlanItem(item, "merge", "three-way merge"))
                continue
            local_text = local.read_text(encoding="utf-8")
            base_text = base.read_text(encoding="utf-8")
            template_text = item.source.read_text(encoding="utf-8")
            if item.target == Path("CLAUDE.md") and agents_pointer_can_follow_upgrade(
                project_root, framework_root, mode, baseline_root, template_text, local_text
            ):
                legacy_pointer = CLAUDE_AGENTS_POINTER_MARKER not in local_text
                action = (
                    "pointer-upgrade"
                    if legacy_pointer and "036-explicit-claude-agents-pointer" in pending_migrations
                    else "pointer-verified"
                )
                plan.append(
                    PlanItem(
                        item,
                        action,
                        "project declares CLAUDE.md as an AGENTS.md pointer; shared markers are current or "
                        "will be updated safely in AGENTS.md",
                    )
                )
                continue
            wrapped = [
                f"{capability} v{version}"
                for capability, version in pending_wrapped_capabilities(
                    framework_root, pending_migrations, item.target
                )
                if extract_marker_block(local_text, capability, version) is None
            ]
            if wrapped:
                plan.append(
                    PlanItem(
                        item,
                        "conflict",
                        f"three-way merge conflicted inside text the new {', '.join(wrapped)} block wraps; "
                        "reconcile the edit by hand or move project text outside the block",
                    )
                )
                continue
            restructured = [
                f"{capability} v{version}"
                for capability, version in pending_restructured_markers(
                    framework_root, pending_migrations, item.target
                )
                if extract_marker_block(local_text, capability, version) is not None
            ]
            if restructured:
                backup = _unused_adoption_backup(local, "pre-restructure").relative_to(project_root)
                carried = len(project_sections(local_text, base_text, template_text))
                edited = restructured_marker_edits(
                    local_text,
                    base_text,
                    pending_restructured_markers(framework_root, pending_migrations, item.target),
                )
                edited_detail = (
                    "; edited retired marker content "
                    f"({', '.join(f'{capability} v{version}' for capability, version in edited)}) "
                    "will be removed from carried project sections; the original remains in the backup"
                    if edited
                    else ""
                )
                plan.append(
                    PlanItem(
                        item,
                        "restructure",
                        f"three-way merge conflicted around retired inline marker(s) ({', '.join(restructured)}); "
                        f"replace with the standalone template block after preserving the current file as {backup}"
                        + (f" and carrying over {carried} project section(s)" if carried else "")
                        + edited_detail
                        + "; re-apply any project prose from the backup after the managed block",
                        backup=backup,
                    )
                )
                continue
            capability_ids = capability_ids_in_template(item.source)
            marker_append = append_only_new_markers(local_text, base_text, template_text)
            if marker_append is not None:
                local_by_name = dict(marker_pairs(local_text))
                added = [
                    capability
                    for capability, version in marker_pairs(template_text)
                    if capability not in local_by_name
                ]
                superseded = [
                    f"{capability} v{local_by_name[capability]}->v{version}"
                    for capability, version in marker_pairs(template_text)
                    if capability in local_by_name and version > local_by_name[capability]
                ]
                detail = "three-way merge conflicted, but existing protected markers are intact; "
                parts = []
                if added:
                    parts.append(f"add new marker block(s) ({', '.join(added)})")
                if superseded:
                    parts.append(f"replace superseded block(s) in place ({', '.join(superseded)})")
                detail += " and ".join(parts) + " without touching other local text"
                pending_removals = removals_for_managed_file(framework_root, pending_migrations, item.target)
                if pending_removals:
                    retired_append = remove_retired_markers(
                        marker_append,
                        base_text,
                        [(capability, version) for capability, version, _superseded_by in pending_removals],
                    )
                    if retired_append is None:
                        plan.append(
                            PlanItem(
                                item,
                                "conflict",
                                "a retired capability block was edited locally; reconcile it by hand "
                                "before this upgrade can remove it",
                            )
                        )
                        continue
                    if retired_append != marker_append:
                        plan.append(
                            PlanItem(
                                item,
                                "append-retire-markers",
                                detail + "; then retire the declared capability block(s) "
                                "that still match the installed baseline",
                            )
                        )
                        continue
                plan.append(
                    PlanItem(
                        item,
                        "append-markers",
                        detail,
                    )
                )
                continue
            normalized_markers = reflowed_marker_normalization(local_text, template_text)
            if normalized_markers is not None:
                plan.append(
                    PlanItem(
                        item,
                        "normalize-markers",
                        "three-way merge conflicted, but protected marker content differs only by prose line wrapping; normalize to the current canonical block",
                    )
                )
                continue
            removals = removals_for_managed_file(framework_root, pending_migrations, item.target)
            retirement_conflict = False
            if removals:
                removal_pairs = [(capability, version) for capability, version, _superseded_by in removals]
                retired = remove_retired_markers(local_text, base_text, removal_pairs)
                if retired is not None and retired != local_text:
                    labels = [
                        f"{capability} -> {superseded_by}" if superseded_by else capability
                        for capability, _version, superseded_by in removals
                    ]
                    plan.append(
                        PlanItem(
                            item,
                            "retire-markers",
                            "three-way merge conflicted, but the retired capability block(s) "
                            f"({', '.join(labels)}) still matched the installed baseline and were "
                            "removed in place",
                        )
                    )
                    continue
                # A locally modified block awaiting retirement must never be
                # silently downgraded to VERIFIED below: `capability_ids`
                # comes from the *current* template, which by definition no
                # longer carries a capability this migration just retired, so
                # that check alone is blind to this exact conflict.
                retirement_conflict = retired is None
            satisfied_here = (
                not retirement_conflict
                and capability_ids
                and all(
                    extract_marker_block(local_text, capability_id, requirements[capability_id][0])
                    is not None
                    and extract_marker_block(local_text, capability_id, requirements[capability_id][0])
                    == extract_marker_block(template_text, capability_id, requirements[capability_id][0])
                    for capability_id in capability_ids
                )
            )
            if satisfied_here:
                plan.append(
                    PlanItem(
                        item,
                        "verified",
                        "three-way merge conflicted, but this file's own capability marker(s) "
                        f"({', '.join(sorted(capability_ids))}) already satisfy the required version — "
                        "left untouched",
                    )
                )
            else:
                plan.append(PlanItem(item, "conflict", "three-way merge"))
    if mode == "governed-sdd":
        plan = apply_additive_move_checks(
            plan,
            project_root,
            framework_root,
            mode,
            baseline_root,
            pending_migrations,
        )
    if capability_profiles is not None:
        plan.extend(profile_surface_plan(project_root, framework_root, manifest))
    return manifest, plan

