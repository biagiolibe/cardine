"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.models import CapabilityMove
from cardine.templates.files import managed_files
from cardine.templates.markers import LEGACY_CAPABILITY_EVIDENCE
from cardine.templates.markers import find_capability_marker_version
from cardine.templates.migrations import capability_requirements
from cardine.templates.migrations import migration_capability_entries
from cardine.templates.migrations import migration_capability_moves
from cardine.templates.migrations import migration_capability_removals
from cardine.templates.migrations import migration_record_paths
from pathlib import Path
import json


def declared_capability_moves(
    framework_root: Path, migration_ids_to_find: list[str] | None = None
) -> list[CapabilityMove]:
    """All, or only pending, declared capability moves in migration order."""
    wanted = set(migration_ids_to_find) if migration_ids_to_find is not None else None
    result = []
    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if wanted is None or str(data["id"]) in wanted:
            result.extend(migration_capability_moves(data))
    return result


def pending_migration_establishes_move_source(
    framework_root: Path, pending_migrations: list[str], move: CapabilityMove
) -> bool:
    """Whether an earlier pending migration declares this move's source marker.

    A long-lag consumer can legitimately predate a marker that an intermediate
    migration adds and a later migration immediately relocates.  The final
    template no longer contains that transient source marker, so its presence
    cannot be inferred from the three-way merge inputs alone.  Trust this
    narrow transition only when the migration ledger explicitly establishes
    the exact capability/version on the same managed source path before the
    move that consumes it.
    """
    try:
        move_index = pending_migrations.index(move.migration)
    except ValueError:
        return False
    for path in migration_record_paths(framework_root, pending_migrations[:move_index]):
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(move.source_path) not in {str(item) for item in data.get("managedPaths", [])}:
            continue
        if (move.source_capability, move.source_version) in migration_capability_entries(data):
            return True
    return False


def capability_presence_map(
    project_root: Path, mode: str, framework_root: Path
) -> dict[str, tuple[bool, str]]:
    """capability id -> (present, evidence), by behavior rather than exact wording.

    A capability is present when the project carries a
    `<!-- MERIDIAN:BEGIN capability=<id> vN --> ... <!-- MERIDIAN:END -->`
    marker for it at or above the version the framework currently requires,
    found anywhere among the project's managed governed-SDD files. When no
    marker is found, a capability with a pre-marker legacy check
    (`LEGACY_CAPABILITY_EVIDENCE`) still counts as present at v1 — never
    higher, since that check cannot distinguish v1 from any later version.
    Pure phrase matching is the fallback only for projects adopted before
    markers existed.
    """
    if mode != "governed-sdd":
        return {}

    combined_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (project_root / item.target for item in managed_files(framework_root, mode))
        if path.is_file()
    )

    presence: dict[str, tuple[bool, str]] = {}
    for capability_id, (required_version, _migration_id) in capability_requirements(framework_root).items():
        found_version = find_capability_marker_version(combined_text, capability_id)
        if found_version is not None:
            if found_version < required_version:
                presence[capability_id] = (
                    False,
                    f"marker present at v{found_version}, but v{required_version} is required",
                )
            else:
                presence[capability_id] = (
                    True,
                    f"marker present at v{found_version} (>= required v{required_version})",
                )
        else:
            legacy_check = LEGACY_CAPABILITY_EVIDENCE.get(capability_id)
            legacy_present = legacy_check is not None and legacy_check(project_root, combined_text)
            if legacy_present and required_version <= 1:
                presence[capability_id] = (True, "no marker found; legacy pre-marker evidence confirms v1")
            elif legacy_present:
                presence[capability_id] = (
                    False,
                    "no marker found; legacy pre-marker evidence only confirms v1, but "
                    f"v{required_version} is required",
                )
            else:
                presence[capability_id] = (
                    False,
                    f"no MERIDIAN:BEGIN capability={capability_id} marker found",
                )
    return presence


def retired_capability_versions(framework_root: Path) -> set[tuple[str, int]]:
    """Every exact (capability, version) pair retired by the marker catalog or
    declared `removes` by a migration, regardless of which files its
    `managedPaths` named. Used by
    `audit_capability_markers` to tell "stale, upgrade hasn't run yet" apart
    from "retired, and this marker should already be gone" — the latter
    reported `FAIL` rather than `SKIP`, since `cardine upgrade`'s own
    retirement path only ever touches the specific files a migration lists,
    so a marker in a file that migration's `managedPaths` omitted would
    otherwise sit as an invisible `SKIP` forever.
    """
    from cardine.templates.catalog import load_marker_catalog

    pairs: set[tuple[str, int]] = {
        (capability, int(item["requiredVersion"]))
        for capability, item in load_marker_catalog(framework_root).items()
        if item["retired"]
    }
    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for capability, version, _superseded_by in migration_capability_removals(data):
            pairs.add((capability, version))
    return pairs
