"""Read-only model of a Meridian project, for its conversion to Cardine.

The reader opens only the paths the installation declares: the manifest, the
workflow lock, the project declaration, the identity, candidate-validation, and
flow-target files, the queue, and the ADR log. It never writes and never reads
task records.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

from cardine.legacy.meridian_installation import (
    MERIDIAN_INSTALLATION_NAMES,
    detect_meridian_mode,
    is_meridian_installation,
    read_manifest,
)
from cardine.legacy.meridian_locations import resolve_meridian_locations
from cardine.legacy.queue_rows import _queue_task_rows
from cardine.shared.authority import ADR_HEADING_ID, ADR_LIKE_HEADING, adr_entries
from cardine.shared.errors import CardineError
from cardine.shared.layout import use
from cardine.shared.models import ProjectLocations
from cardine.shared.project import read_project_declaration
from cardine.shared.text import HEADING_LINE
from cardine.tasks.identity import read_installation_identity_policy

# Checkbox tokens (Lean) and status words (Governed) mapped to a conversion class.
_OPEN = {"[ ]", "QUEUED"}
_IN_PROGRESS = {"[/]", "IN_PROGRESS", "READY_FOR_REVIEW", "CHANGES_REQUESTED", "ACCEPTED"}
_CLOSED = {"[x]", "[X]", "DONE"}
_OTHER = {"[-]": "cancelled", "[?]": "proposed"}


@dataclass(frozen=True)
class LegacyQueueRow:
    task_id: str
    state: str  # open, in_progress, closed, cancelled, proposed, or unknown
    status: str  # the status cell as written
    line: int
    review: str  # the Review cell as written; empty when the queue has none


@dataclass(frozen=True)
class LegacyAdrEntry:
    adr_id: str
    title: str
    status: str | None


@dataclass(frozen=True)
class LegacyProject:
    root: Path
    mode: str | None  # lean-delivery, governed-sdd, or None when undetectable
    locations: ProjectLocations
    queue_present: bool
    rows: tuple[LegacyQueueRow, ...]
    duplicate_ids: tuple[str, ...]
    adr_log_present: bool
    adr_entries: tuple[LegacyAdrEntry, ...]
    adr_unnumbered: tuple[str, ...]  # ADR-like headings without an `ADR-<n>` id
    identity_mode: str
    declaration: dict[str, object] | None
    candidate_validation: dict[str, object] | None
    flow_targets: dict[str, object] | None
    diagnostics: tuple[str, ...]

    @property
    def open_rows(self) -> tuple[LegacyQueueRow, ...]:
        return tuple(row for row in self.rows if row.state == "open")

    @property
    def in_progress_rows(self) -> tuple[LegacyQueueRow, ...]:
        return tuple(row for row in self.rows if row.state == "in_progress")

    @property
    def closed_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(row.task_id for row in self.rows if row.state == "closed"))


def _state(status: str) -> str:
    if status in _OPEN:
        return "open"
    if status in _IN_PROGRESS:
        return "in_progress"
    if status in _CLOSED:
        return "closed"
    return _OTHER.get(status, "unknown")


def _inside(root: Path, relative: Path) -> Path:
    """Resolve a declared path and refuse one that leaves the project."""
    path = (root / relative).resolve()
    if root not in (path, *path.parents):
        raise CardineError(f"declared path leaves the project: {relative}")
    return path


def _read_json_object(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CardineError(f"invalid Meridian declaration: {path}") from error
    if not isinstance(value, dict):
        raise CardineError(f"invalid Meridian declaration: {path}")
    return value


def _read_adr_log(text: str) -> tuple[tuple[LegacyAdrEntry, ...], tuple[str, ...], list[str]]:
    entries, warnings = adr_entries(text)
    unnumbered = tuple(
        title for title in (match.group(2).strip() for match in HEADING_LINE.finditer(text))
        if ADR_LIKE_HEADING.match(title) and ADR_HEADING_ID.match(title) is None
    )
    found = tuple(LegacyAdrEntry(str(entry["id"]), str(entry["title"]), entry["status"]) for entry in entries)
    return found, unnumbered, [warning for warning in warnings if "duplicate ADR-" in warning]


def read_legacy_project(project: Path) -> LegacyProject:
    """Return the read model of the Meridian project at `project`."""
    root = project.expanduser().resolve()
    if not is_meridian_installation(root):
        raise CardineError(f"not a Meridian project: {root}")
    diagnostics: list[str] = []
    read_manifest(root)  # fails on an unreadable manifest before anything else is trusted
    try:
        mode: str | None = detect_meridian_mode(root)
    except CardineError as error:
        mode = None
        diagnostics.append(str(error))
    with use(MERIDIAN_INSTALLATION_NAMES):
        locations = resolve_meridian_locations(root)
        declaration = read_project_declaration(root)
        identity_mode = read_installation_identity_policy(root).mode
    names = MERIDIAN_INSTALLATION_NAMES
    candidate = _read_json_object(_inside(root, names.candidate_validation_path))
    flow_targets = _read_json_object(_inside(root, names.flow_targets_path))

    queue = _inside(root, locations.queue)
    rows: tuple[LegacyQueueRow, ...] = ()
    if queue.is_file():
        rows = tuple(
            LegacyQueueRow(str(row["id"]), _state(str(row["status"])), str(row["status"]),
                           int(row["line"]), str(row["review"]))  # type: ignore[call-overload]
            for row in _queue_task_rows(queue.read_text(encoding="utf-8"))
        )
    else:
        diagnostics.append(f"no queue at {locations.queue}")
    for row in rows:
        if row.state == "unknown":
            diagnostics.append(f"{locations.queue}:{row.line}: unrecognized status {row.status!r} for {row.task_id}")
    counts = Counter(row.task_id for row in rows)
    duplicates = tuple(task_id for task_id, count in counts.items() if count > 1)
    diagnostics.extend(f"duplicate queue id {task_id}" for task_id in duplicates)

    adr_log = _inside(root, locations.adr_log)
    entries: tuple[LegacyAdrEntry, ...] = ()
    unnumbered: tuple[str, ...] = ()
    if adr_log.is_file():
        entries, unnumbered, warnings = _read_adr_log(adr_log.read_text(encoding="utf-8"))
        diagnostics.extend(warnings)
    return LegacyProject(
        root=root, mode=mode, locations=locations, queue_present=queue.is_file(), rows=rows,
        duplicate_ids=duplicates, adr_log_present=adr_log.is_file(), adr_entries=entries,
        adr_unnumbered=unnumbered, identity_mode=identity_mode, declaration=declaration,
        candidate_validation=candidate, flow_targets=flow_targets, diagnostics=tuple(diagnostics),
    )
