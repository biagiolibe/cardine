"""Plan and apply managed project upgrades."""

from __future__ import annotations

from cardine.shared.layout import names

from pathlib import Path

from cardine.lifecycle import receipts
from cardine.lifecycle.file_operation import Operation, operation
from cardine.release.version import read_version, require_release_version
from cardine.shared.constants import PROTOCOL_VERSION, STRICT_DIGEST_PROFILES
from cardine.shared.errors import CardineError
from cardine.shared.hashing import sha256
from cardine.shared.models import ManagedFile, PlanItem
from cardine.templates.adoption import _capability_declaration
from cardine.templates.catalog import load_capability_catalog, manifest_workflow_mode
from cardine.templates.files import latest_migration_to, managed_files, manifest_baseline_version
from cardine.templates.manifest import manifest_bytes
from cardine.templates.markers import append_only_new_markers, deduplicate_identical_template_markers, reflowed_marker_normalization, remove_retired_markers
from cardine.templates.merge import merge_clean, plan_from_baseline, prune_stale_baselines
from cardine.templates.migration_audit import removals_for_managed_file
from cardine.templates.migrations import migration_ids, pending_restructured_markers, restructured_text
from cardine.templates.router import audit_entry_router, entry_router_outputs, project_uses_entry_router
from cardine.templates.upgrade_support import plan_has_blockers, prepare_upgrade_targets, print_plan

def plan_upgrade(
    project_root: Path, framework_root: Path, stop_before_retirement: bool = False
) -> tuple[dict[str, object], list[PlanItem]]:
    manifest, target_override, managed_override = prepare_upgrade_targets(
        project_root, framework_root, stop_before_retirement
    )
    installed_version = manifest_baseline_version(manifest)
    return plan_from_baseline(
        project_root,
        framework_root,
        manifest_workflow_mode(manifest),
        installed_version,
        project_root / names().baselines_path / installed_version,
        list(manifest.get("appliedMigrations", [])),
        target_version_override=target_override,
        managed_files_override=managed_override,
        installed_framework_version=str(manifest.get("frameworkVersion", "")),
        capability_profiles=manifest.get("capabilityProfiles"),
    )


def complete_profile_surfaces(
    project_root: Path,
    framework_root: Path,
    manifest: dict[str, object],
    plan: list[PlanItem],
) -> None:
    """Rebuild each declaration the plan marked as lacking catalog surfaces, in the
    manner of `bootstrap_capability_profile`. Host-activation and verification
    snapshots are kept; only the surface list and installation evidence change."""
    affected = [item.profile_surface for item in plan if item.profile_surface is not None]
    if not affected:
        return
    catalog = load_capability_catalog(framework_root)
    profiles = manifest["capabilityProfiles"]
    managed = dict(manifest["managedFiles"])
    for profile_id, capability_id in affected:
        profile = catalog.profile(profile_id)
        capability = catalog.capability(capability_id)
        assert profile is not None and capability is not None
        declaration = profiles[profile_id]["capabilities"][capability_id]
        rebuilt = _capability_declaration(
            project_root,
            capability,
            dict(profile.capabilities)[capability_id],
            managed,
            profile_id in STRICT_DIGEST_PROFILES,
        )
        for field in ("hostActivation", "verification"):
            if field == "hostActivation":
                rebuilt[field] = {**rebuilt[field], **declaration[field]}
            else:
                rebuilt[field] = declaration[field]
        profiles[profile_id]["capabilities"][capability_id] = rebuilt
    manifest["managedFiles"] = dict(sorted(managed.items()))


WRITING_ACTIONS = frozenset((
    "replace", "add", "adopt-replace", "restructure", "merge", "merge-deduplicate-markers",
    "deduplicate-markers", "append-markers", "append-retire-markers", "normalize-markers",
    "retire-markers",
))


def planned_output(
    project_root: Path,
    framework_root: Path,
    item: PlanItem,
    baseline_root: Path,
    pending_migrations: list[str],
) -> bytes:
    """The exact bytes one plan action writes, computed without writing anything."""
    local = project_root / item.file.target
    action = item.action
    if action in ("replace", "add"):
        return item.file.source.read_bytes()
    if action == "adopt-replace":
        if item.backup is None:
            raise CardineError(f"adoption backup is missing for {item.file.target}")
        return item.file.source.read_bytes()
    if action == "restructure":
        if item.backup is None:
            raise CardineError(f"restructure backup is missing for {item.file.target}")
        return restructured_text(
            local.read_text(encoding="utf-8"),
            (baseline_root / item.file.target).read_text(encoding="utf-8"),
            item.file.source.read_text(encoding="utf-8"),
            pending_restructured_markers(framework_root, pending_migrations, item.file.target),
        ).encode("utf-8")
    if action == "merge":
        return merge_clean(local, baseline_root / item.file.target, item.file.source)[1]
    source = item.file.source.read_text(encoding="utf-8")
    base = baseline_root / item.file.target
    if action in ("merge-deduplicate-markers", "deduplicate-markers"):
        text = (
            merge_clean(local, base, item.file.source)[1].decode("utf-8")
            if action == "merge-deduplicate-markers"
            else local.read_text(encoding="utf-8")
        )
        normalized = deduplicate_identical_template_markers(text, source)
        label = "marker deduplication"
    elif action == "normalize-markers":
        normalized = reflowed_marker_normalization(local.read_text(encoding="utf-8"), source)
        label = "marker normalization"
    elif action in ("append-markers", "append-retire-markers"):
        normalized = append_only_new_markers(
            local.read_text(encoding="utf-8"), base.read_text(encoding="utf-8"), source
        )
        label = "marker-aware insertion"
        if action == "append-retire-markers":
            removals = removals_for_managed_file(framework_root, pending_migrations, item.file.target)
            pairs = [(capability, version) for capability, version, _superseded_by in removals]
            retired = remove_retired_markers(normalized or "", base.read_text(encoding="utf-8"), pairs)
            normalized = None if normalized is None else retired
            label = "marker-aware relocation"
    else:
        removals = removals_for_managed_file(framework_root, pending_migrations, item.file.target)
        pairs = [(capability, version) for capability, version, _superseded_by in removals]
        local_text = local.read_text(encoding="utf-8")
        normalized = remove_retired_markers(local_text, base.read_text(encoding="utf-8"), pairs)
        if normalized == local_text:
            normalized = None
        label = "marker retirement"
    if normalized is None:
        raise CardineError(f"{label} is no longer safe for {item.file.target}; rerun upgrade --check")
    return normalized.encode("utf-8")


def upgrade_binding(
    project_root: Path, framework_root: Path, owner_reconciled: bool, stop_before_retirement: bool
) -> dict[str, object]:
    return dict(
        kind="upgrade",
        root=str(project_root),
        framework=read_version(framework_root),
        owner_reconciled=bool(owner_reconciled),
        stop_before_retirement=bool(stop_before_retirement),
    )


def remaining_plan(operation: Operation, plan: list[PlanItem]) -> list[PlanItem]:
    """Drop items whose recorded output is already in place; their re-plan would be stale."""
    return [item for item in plan
            if not (f"upgrade:{item.file.target}" in operation.files
                    and operation.state(f"upgrade:{item.file.target}") == "after")]


def stale_baselines(project_root: Path, keep_version: str) -> list[Path]:
    root = project_root / names().baselines_path
    return [entry for entry in root.iterdir() if entry.is_dir() and entry.name != keep_version] \
        if root.is_dir() else []


def prune_baselines(operation: Operation, project_root: Path, target_baseline_version: str) -> None:
    operation.effect(
        "prune-baselines",
        lambda: prune_stale_baselines(project_root, target_baseline_version),
        lambda: not stale_baselines(project_root, target_baseline_version),
    )


def apply_plan(
    project_root: Path,
    framework_root: Path,
    manifest: dict[str, object],
    plan: list[PlanItem],
    baseline_root: Path,
    owner_reconciled: bool = False,
    target_version_override: str | None = None,
    managed_files_override: list[ManagedFile] | None = None,
    stop_before_retirement: bool | None = None,
) -> None:
    project_root = project_root.resolve()
    capped = target_version_override is not None if stop_before_retirement is None else stop_before_retirement
    binding = upgrade_binding(project_root, framework_root, owner_reconciled, capped)
    with operation(receipts.operation_path(project_root, "upgrade"), binding, root=project_root) as active:
        _apply_plan(active, project_root, framework_root, manifest, plan, baseline_root,
                    owner_reconciled, target_version_override, managed_files_override)


def _apply_plan(
    operation: Operation,
    project_root: Path,
    framework_root: Path,
    manifest: dict[str, object],
    plan: list[PlanItem],
    baseline_root: Path,
    owner_reconciled: bool,
    target_version_override: str | None,
    managed_files_override: list[ManagedFile] | None,
) -> None:
    plan = remaining_plan(operation, plan)
    print_plan(project_root, manifest, framework_root, plan, target_version_override=target_version_override)
    if plan_has_blockers(plan, owner_reconciled=owner_reconciled):
        raise CardineError("upgrade has blocking plan items")

    installed_version = manifest_baseline_version(manifest)
    target_version = target_version_override or read_version(framework_root)
    target_baseline_version = latest_migration_to(framework_root, target_version)
    inputs = dict(installed=installed_version, target=target_version, baseline=target_baseline_version)
    if operation.resumed and operation.intent.get("inputs") != inputs:
        raise CardineError("unfinished upgrade was planned for different versions; rerun its original command")
    operation.intent["inputs"] = inputs
    if operation.resumed:
        print(f"Resuming unfinished upgrade operation {operation.intent['operation_id']}.")
    if owner_reconciled:
        print(
            "Owner-reconciled upgrade: skipped automatic file changes for every managed "
            "file, trusting that local content was already brought to the target version "
            "by hand outside the three-way merge."
        )
    else:
        applied = {str(migration) for migration in manifest.get("appliedMigrations", [])}
        pending_migrations = [
            migration
            for migration in migration_ids(framework_root, installed_version, target_baseline_version)
            if migration not in applied
        ]
        # Compute every output before the first write, so an unsafe action stops the upgrade untouched.
        outputs: dict[str, bytes] = {}
        for item in plan:
            if item.action in WRITING_ACTIONS:
                outputs[f"upgrade:{item.file.target}"] = planned_output(
                    project_root, framework_root, item, baseline_root, pending_migrations
                )
        for item in plan:
            if f"upgrade:{item.file.target}" in outputs:
                operation.guard(project_root / item.file.target)
        for item in plan:
            name = f"upgrade:{item.file.target}"
            if name in outputs:
                backup = project_root / item.backup if item.backup is not None else None
                operation.declare(name, project_root / item.file.target, outputs[name],
                                  backup=backup if item.action in ("adopt-replace", "restructure") else None)
        for name in [name for name in operation.files if name.startswith("upgrade:")]:
            operation.run(name, outputs.get(name))

    if project_uses_entry_router(project_root):
        for target, output in entry_router_outputs(project_root).items():
            operation.replace(f"router:{target}", project_root / target, output.encode("utf-8"))
        router_failures = [
            detail for status, detail in audit_entry_router(project_root) if status == "FAIL"
        ]
        if router_failures:
            raise CardineError(
                "entry-router audit failed after regeneration: " + "; ".join(router_failures)
            )

    changes_baseline = target_baseline_version != installed_version
    if changes_baseline:
        for item in managed_files_override or managed_files(framework_root, manifest_workflow_mode(manifest)):
            operation.replace(
                f"baseline:{item.target}",
                project_root / names().baselines_path / target_baseline_version / item.target,
                item.source.read_bytes(),
            )

    def build_manifest() -> bytes:
        manifest["frameworkVersion"] = target_version
        manifest["workflowBaselineVersion"] = target_baseline_version
        manifest["protocolVersion"] = PROTOCOL_VERSION
        manifest["managedFiles"] = {}
        for item in managed_files_override or managed_files(framework_root, manifest_workflow_mode(manifest)):
            digest_source = item.source
            if project_uses_entry_router(project_root) and item.target in {
                Path("AGENTS.md"),
                Path("CLAUDE.md"),
            }:
                digest_source = project_root / item.target
            manifest["managedFiles"][str(item.target)] = sha256(digest_source)
        prior = {str(item) for item in manifest.get("appliedMigrations", [])}
        prior.update(migration_ids(framework_root, installed_version, target_baseline_version))
        manifest["appliedMigrations"] = sorted(prior)
        complete_profile_surfaces(project_root, framework_root, manifest, plan)
        return manifest_bytes(manifest, framework_root)

    built: list[bytes] = []

    def manifest_output() -> bytes:
        if not built:
            built.append(build_manifest())
        return built[0]

    # The manifest names the new baseline, so it is written before the old one is pruned.
    operation.replace("manifest", project_root / names().manifest_path, manifest_output)
    if changes_baseline:
        prune_baselines(operation, project_root, target_baseline_version)
    print("Upgrade applied. Review the diff, run project checks, then commit it.")


def apply_upgrade(
    project_root: Path,
    framework_root: Path,
    owner_reconciled: bool = False,
    stop_before_retirement: bool = False,
) -> None:
    require_release_version(framework_root)
    project_root = project_root.resolve()
    binding = upgrade_binding(project_root, framework_root, owner_reconciled, stop_before_retirement)
    with operation(receipts.operation_path(project_root, "upgrade"), binding, root=project_root) as active:
        if active.resumed and "manifest" in active.files and active.state("manifest") == "after":
            # The manifest is the last file effect; only pruning the old baseline can remain.
            prune_baselines(active, project_root, active.intent["inputs"]["baseline"])
            print("Upgrade applied. Review the diff, run project checks, then commit it.")
            return
        manifest, target_override, managed_override = prepare_upgrade_targets(
            project_root, framework_root, stop_before_retirement
        )
        installed_version = manifest_baseline_version(manifest)
        manifest, plan = plan_from_baseline(
            project_root,
            framework_root,
            manifest_workflow_mode(manifest),
            installed_version,
            project_root / names().baselines_path / installed_version,
            list(manifest.get("appliedMigrations", [])),
            target_version_override=target_override,
            managed_files_override=managed_override,
            installed_framework_version=str(manifest.get("frameworkVersion", "")),
            capability_profiles=manifest.get("capabilityProfiles"),
        )
        _apply_plan(
            active,
            project_root,
            framework_root,
            manifest,
            plan,
            project_root / names().baselines_path / manifest_baseline_version(manifest),
            owner_reconciled,
            target_override,
            managed_override,
        )
