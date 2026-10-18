"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.release.version import version_key
from cardine.shared.errors import MeridianError
from cardine.shared.models import CapabilityMove
from cardine.templates.markers import extract_marked_block
from cardine.templates.markers import marker_blocks
from pathlib import Path
from pathlib import PurePosixPath
import json
import re


def migration_ids(framework_root: Path, installed_version: str, target_version: str) -> list[str]:
    result = []
    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if version_key(str(data["to"])) > version_key(installed_version) and version_key(
            str(data["to"])
        ) <= version_key(target_version):
            result.append(str(data["id"]))
    return result


def first_retirement_migration(framework_root: Path, migration_ids_to_check: list[str]) -> str | None:
    """The first migration, in order, among `migration_ids_to_check` whose
    record declares any `stage: "retirement"` capability move, or `None` if
    none of them do."""
    for path in migration_record_paths(framework_root, migration_ids_to_check):
        data = json.loads(path.read_text(encoding="utf-8"))
        if any(str(move.get("stage")) == "retirement" for move in data.get("capabilityMoves", [])):
            return str(data["id"])
    return None


def capped_target_version(framework_root: Path, installed_version: str, target_version: str) -> str:
    """The effective target version for a `--stop-before-retirement` upgrade:
    the `from` version of the first pending migration that declares a
    retirement-stage capability move, or `target_version` unchanged if none
    of the pending migrations retire anything."""
    pending = migration_ids(framework_root, installed_version, target_version)
    retirement_id = first_retirement_migration(framework_root, pending)
    if retirement_id is None:
        return target_version
    for path in migration_record_paths(framework_root, [retirement_id]):
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data["from"])
    raise MeridianError(f"migration record is missing: {retirement_id}")


def migration_record_paths(framework_root: Path, migration_ids_to_find: list[str]) -> list[Path]:
    records = []
    wanted = set(migration_ids_to_find)
    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data["id"]) in wanted:
            records.append(path)
    if len(records) != len(wanted):
        raise MeridianError("a requested migration record is missing from the framework source")
    return records


def validate_adopt_existing_paths(data: dict[str, object]) -> list[str]:
    """Validate an optional, narrowly scoped newly-managed-file adoption declaration."""
    declared = data.get("adoptExistingPaths", [])
    if not isinstance(declared, list):
        return ["adoptExistingPaths must be a list"]
    managed = data.get("managedPaths", [])
    managed_paths = (
        {value for value in managed if isinstance(value, str)}
        if isinstance(managed, list)
        else set()
    )
    errors = []
    seen = set()
    for value in declared:
        if not isinstance(value, str) or not value:
            errors.append("adoptExistingPaths entries must be non-empty strings")
            continue
        normalized = PurePosixPath(value)
        if (
            normalized.is_absolute()
            or not normalized.parts
            or normalized.as_posix() != value
            or "\\" in value
            or ".." in normalized.parts
        ):
            errors.append(f"adoptExistingPaths entry is not a normalized relative path: {value!r}")
        if value in seen:
            errors.append(f"adoptExistingPaths entry is duplicated: {value!r}")
        seen.add(value)
        if value not in managed_paths:
            errors.append(f"adoptExistingPaths entry is not listed in managedPaths: {value!r}")
    return errors


def adopt_existing_paths(framework_root: Path, pending_migrations: list[str]) -> set[Path]:
    """Return files that pending migrations explicitly permit adopting without a baseline."""
    result = set()
    for path in migration_record_paths(framework_root, pending_migrations):
        data = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_adopt_existing_paths(data)
        if errors:
            raise MeridianError(f"invalid adoption declaration in {path.name}: {'; '.join(errors)}")
        result.update(Path(value) for value in data.get("adoptExistingPaths", []))
    return result


def migration_capability_entries(data: dict[str, object]) -> list[tuple[str, int]]:
    """A migration record's declared (capability, capabilityVersion) pairs.

    Most migrations declare at most one, via the singular `capability` /
    `capabilityVersion` fields. A migration introducing several independent,
    pre-existing capabilities at once (a marker-retrofit pass over one file's
    several sections, for example) may instead declare a `capabilities` list
    of `{"capability": ..., "capabilityVersion": ...}` objects, so it doesn't
    need one near-duplicate migration record per capability.
    """
    entries = []
    capability = data.get("capability")
    if capability:
        entries.append((str(capability), int(data["capabilityVersion"])))
    for entry in data.get("capabilities", []):
        entries.append((str(entry["capability"]), int(entry["capabilityVersion"])))
    return entries


def migration_capability_removals(data: dict[str, object]) -> list[tuple[str, int, str | None]]:
    """A migration record's declared (capability, capabilityVersion, supersededBy)
    retirements — the mirror of `migration_capability_entries` for task 007's
    retirement path. `supersededBy` is an optional pointer, named in reports
    only, to the capability that now covers the same rule; nothing writes it
    into a managed file (see tasks/007-capability-retirement-path.md — a slot
    left behind inside a merge target is exactly the tension task 014 flagged
    as out of scope)."""
    return [
        (str(entry["capability"]), int(entry["capabilityVersion"]), entry.get("supersededBy"))
        for entry in data.get("removes", [])
    ]


def migration_restructures(data: dict[str, object]) -> list[tuple[Path, list[tuple[str, int]]]]:
    """A migration record's declared `restructures`: for each managed path, the
    inline marker versions the template no longer carries because a standalone
    block replaced them. Unlike `removes`, the scope is one path, so a capability
    that another file still carries stays required."""
    result = []
    for entry in data.get("restructures", []):
        markers = [
            (str(item["capability"]), int(item["capabilityVersion"]))
            for item in entry.get("retiredMarkers", [])
        ]
        result.append((Path(str(entry["path"])), markers))
    return result


def pending_restructured_markers(
    framework_root: Path, migration_ids_to_find: list[str], target: Path
) -> list[tuple[str, int]]:
    """Retired inline marker versions a pending upgrade restructures in one file."""
    wanted = set(migration_ids_to_find)
    result: list[tuple[str, int]] = []
    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data["id"]) not in wanted:
            continue
        for restructured_path, markers in migration_restructures(data):
            if restructured_path == target:
                result.extend(markers)
    return result


def pending_wrapped_capabilities(
    framework_root: Path, migration_ids_to_find: list[str], target: Path
) -> list[tuple[str, int]]:
    """Capability blocks a pending upgrade newly wraps around text the file
    already carried unmarked. A local copy that edited that text cannot take the
    block as an additive insertion without duplicating the text."""
    wanted = set(migration_ids_to_find)
    result: list[tuple[str, int]] = []
    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data["id"]) not in wanted:
            continue
        for entry in data.get("wraps", []):
            if Path(str(entry["path"])) == target:
                result.append((str(entry["capability"]), int(entry["capabilityVersion"])))
    return result


def drop_restructured_marker_blocks(
    text: str, retired_markers: list[tuple[str, int]]
) -> str:
    """Remove complete retired marker blocks from a carried project section.

    Restructuring replaces the managed part of a file, but appends project-owned
    level-2 sections verbatim. Retired inline blocks in those sections must not
    hitch a ride into the new file. The removal intentionally accepts modified
    blocks too: the restructure plan reports those edits and preserves the
    complete pre-restructure file in its backup.
    """
    result = text
    for capability, version in retired_markers:
        while (block := extract_marked_block(result, capability, version)) is not None:
            start = result.index(block)
            end = start + len(block)
            before, after = result[:start], result[end:]
            # Keep normalization bounded to the deletion point so unrelated
            # project-owned blank-line runs remain byte-for-byte.
            boundary = re.sub(r"\n{3,}", "\n\n", before[-4:] + after[:4])
            result = before[:-4] + boundary + after[4:]
    return result


def restructured_marker_edits(
    local_text: str, base_text: str, retired_markers: list[tuple[str, int]]
) -> list[tuple[str, int]]:
    """Retired markers whose local complete block differs from the baseline."""
    return [
        (capability, version)
        for capability, version in retired_markers
        if any(
            block != extract_marked_block(base_text, capability, version)
            for block in marker_blocks(local_text, capability, version)
        )
    ]


def project_sections(
    local_text: str,
    base_text: str,
    template_text: str,
    retired_markers: list[tuple[str, int]] | None = None,
) -> list[str]:
    """Level-2 sections of `local_text` whose heading neither the installed
    baseline nor the target template carries: the project's own sections,
    returned verbatim and in order. Headings inside code fences are ignored."""
    def split(text: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, list[str]]] = []
        fenced = False
        for line in text.splitlines(keepends=True):
            if line.lstrip().startswith("```"):
                fenced = not fenced
            if not fenced and re.match(r"#{1,2}\s", line):
                sections.append((line.strip() if line.startswith("## ") else "", [line]))
            elif sections:
                sections[-1][1].append(line)
        return [(heading, "".join(lines)) for heading, lines in sections]

    known = {heading for text in (base_text, template_text) for heading, _body in split(text)}
    return [
        (
            drop_restructured_marker_blocks(body, retired_markers or [])
            if retired_markers
            else body
        ).rstrip("\n") + "\n"
        for heading, body in split(local_text)
        if heading and heading not in known
    ]


def restructured_text(
    local_text: str,
    base_text: str,
    template_text: str,
    retired_markers: list[tuple[str, int]] | None = None,
) -> str:
    """The target template followed by the project's own level-2 sections."""
    carried = project_sections(local_text, base_text, template_text, retired_markers)
    if not carried:
        return template_text
    return template_text.rstrip("\n") + "\n\n" + "\n".join(carried)


def migration_capability_moves(data: dict[str, object]) -> list[CapabilityMove]:
    """Parse the exact-source/exact-target moves declared by one migration."""
    result = []
    for entry in data.get("capabilityMoves", []):
        source = entry["source"]
        target = entry["target"]
        result.append(
            CapabilityMove(
                stage=str(entry["stage"]),
                source_path=Path(str(source["path"])),
                source_capability=str(source["capability"]),
                source_version=int(source["capabilityVersion"]),
                source_sha256=str(source["markerSha256"]),
                target_path=Path(str(target["path"])),
                target_capability=str(target["capability"]),
                target_version=int(target["capabilityVersion"]),
                target_sha256=str(target["markerSha256"]),
                migration=str(data["id"]),
            )
        )
    return result


def capability_requirements(framework_root: Path) -> dict[str, tuple[int, str]]:
    """Compatibility entry point for catalog-backed marker requirements."""
    from cardine.templates.catalog import marker_requirements

    return marker_requirements(framework_root)


def retired_capability_ids(framework_root: Path) -> set[str]:
    """Return historically retired marker IDs from the current catalog."""
    from cardine.templates.catalog import load_marker_catalog

    return {
        capability for capability, item in load_marker_catalog(framework_root).items()
        if item["retired"]
    }


def pending_capability_removals(
    framework_root: Path, migration_ids_to_find: list[str]
) -> list[tuple[str, int, str | None, list[str]]]:
    """(capability, version, supersededBy, managedPaths) for every retirement
    declared by the specific migrations about to be applied in one upgrade
    run (not every removal in framework history — that scope belongs to
    `retired_capability_ids`). `managedPaths` scopes which files an upgrade
    should attempt to remove the marker from, the same field migration
    records already use for the additive case.
    """
    result: list[tuple[str, int, str | None, list[str]]] = []
    wanted = set(migration_ids_to_find)
    for path in sorted((framework_root / "migrations").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data["id"]) not in wanted:
            continue
        managed_paths = [str(p) for p in data.get("managedPaths", [])]
        for capability, version, superseded_by in migration_capability_removals(data):
            result.append((capability, version, superseded_by, managed_paths))
    return result
