"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.constants import CAPABILITY_MARKER
from cardine.templates.files import managed_files
from cardine.templates.marker_history import declared_capability_moves
from cardine.templates.markers import exact_marker_matches
from cardine.templates.markers import marker_blocks
from cardine.templates.migrations import capability_requirements
from cardine.templates.migrations import pending_capability_removals
from pathlib import Path
import json
import re


def validate_capability_moves(framework_root: Path, mode: str) -> list[str]:
    """Validate move declarations against the exact current release templates."""
    managed = {item.target: item.source for item in managed_files(framework_root, mode)}
    requirements = capability_requirements(framework_root)
    errors = []
    seen_sources: set[tuple[Path, str, int]] = set()
    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        moves = data.get("capabilityMoves", [])
        if not moves:
            continue
        if not isinstance(moves, list):
            errors.append(f"{path.name}: capabilityMoves must be an array")
            continue
        for index, raw in enumerate(moves):
            label = f"{path.name}: capabilityMoves[{index}]"
            if not isinstance(raw, dict) or set(raw) != {"stage", "source", "target"}:
                errors.append(f"{label} must contain exactly stage, source, and target")
                continue
            if raw["stage"] not in ("additive", "retirement"):
                errors.append(f"{label} has an unsupported stage")
                continue
            locations = []
            for side in ("source", "target"):
                value = raw[side]
                required = {"path", "capability", "capabilityVersion", "markerSha256"}
                if not isinstance(value, dict) or set(value) != required:
                    errors.append(f"{label}.{side} has an invalid shape")
                    break
                try:
                    location = (
                        Path(str(value["path"])),
                        str(value["capability"]),
                        int(value["capabilityVersion"]),
                        str(value["markerSha256"]),
                    )
                except (TypeError, ValueError):
                    errors.append(f"{label}.{side} has invalid scalar values")
                    break
                if not re.fullmatch(r"[0-9a-f]{64}", location[3]):
                    errors.append(f"{label}.{side}.markerSha256 is not a SHA-256 digest")
                    break
                if location[0] not in managed:
                    errors.append(f"{label}.{side}.path is not a managed path")
                    break
                template_text = managed[location[0]].read_text(encoding="utf-8")
                superseding_version = max(
                    (
                        int(version)
                        for capability, version in CAPABILITY_MARKER.findall(template_text)
                        if capability == location[1] and int(version) > location[2]
                    ),
                    default=None,
                )
                superseded_target = (
                    side == "target"
                    and superseding_version is not None
                    and requirements.get(location[1], (0, ""))[0] == superseding_version
                    and len(marker_blocks(template_text, location[1], superseding_version)) == 1
                )
                if not (side == "source" and not marker_blocks(template_text, location[1], location[2])) and not (raw["stage"] == "retirement" and side == "source") and not exact_marker_matches(template_text, location[1], location[2], location[3]) and not superseded_target:
                    errors.append(f"{label}.{side} does not name one exact marker in the release template")
                    break
                locations.append(location)
            if len(locations) != 2:
                continue
            source, target = locations
            if source[:3] == target[:3]:
                errors.append(f"{label} has an identical source and target location")
            if source[:3] in seen_sources and raw["stage"] != "retirement":
                errors.append(f"{label} duplicates a declared source marker")
            seen_sources.add(source[:3])
            if source[0] not in {Path(item) for item in data.get("managedPaths", [])} or target[0] not in {
                Path(item) for item in data.get("managedPaths", [])
            }:
                errors.append(f"{label} source and target must both be listed in managedPaths")
    return errors


def removals_for_managed_file(
    framework_root: Path, migration_ids_to_find: list[str], target: Path
) -> list[tuple[str, int, str | None]]:
    """(capability, version, supersededBy) triples a pending upgrade should
    retire from this one managed file — `pending_capability_removals`
    filtered to the entries whose migration declares this file among its
    `managedPaths`."""
    result = [
        (capability, version, superseded_by)
        for capability, version, superseded_by, managed_paths in pending_capability_removals(
            framework_root, migration_ids_to_find
        )
        if str(target) in managed_paths
    ]
    for move in declared_capability_moves(framework_root, migration_ids_to_find):
        if move.stage == "retirement" and move.source_path == target:
            result.append((move.source_capability, move.source_version, None))
    return result
