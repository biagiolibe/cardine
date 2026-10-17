"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from pathlib import Path

from cardine.integration.projections import _queue_task_rows
from cardine.shared.errors import MeridianError
from cardine.shared.models import AuditResult
from cardine.shared.text import read_task_field
from cardine.stops.render import stop_error
from cardine.tasks.identity import _task_authorities
from cardine.tasks.identity import resolve_project_locations
from cardine.tasks.state import read_task_state


def audit_task_state_projections(project_root: Path, workflow: str) -> list[AuditResult]:
    """Explicit full check: enumerate state files and report prose drift without repairs."""
    project_root = project_root.resolve()
    directory = project_root / ".meridian/tasks"
    paths = sorted(directory.glob("*.json"))
    if not paths:
        return []
    locations = resolve_project_locations(project_root)
    authorities = _task_authorities(project_root, locations)
    projections: dict[str, list[tuple[str, str]]] = {}
    queue = project_root / locations.queue
    for path in (queue, queue.with_name("QUEUE_ARCHIVE.md")):
        if not path.is_file():
            continue
        for found in _queue_task_rows(path.read_text(encoding="utf-8")):
            value = str(found["status"])
            if workflow == "lean-delivery":
                value = {"[ ]": "QUEUED", "[/]": "IN_PROGRESS", "[x]": "DONE"}.get(value, value)
            projections.setdefault(str(found["id"]), []).append((path.relative_to(project_root).as_posix(), value))
    results = []
    for path in paths:
        task_id = path.stem
        relative = path.relative_to(project_root).as_posix()
        authority = authorities.get(task_id)
        records = authority.task_paths if authority else ()
        record = records[0] if len(records) == 1 else None
        try:
            record_text = record.read_text(encoding="utf-8") if record else ""
            state = read_task_state(
                project_root, task_id, workflow, review_required=None,
                spike=read_task_field(record_text, "Class") == "SPIKE", stop_factory=stop_error,
            )
        except (MeridianError, OSError, UnicodeError) as error:
            results.append(AuditResult("FAIL", "task-state", f"{relative}: {error}"))
            continue
        expected = state["status"]
        drift = []
        queue_values = projections.get(task_id, [(locations.queue, "missing")])
        for label, value in queue_values:
            if value != expected:
                drift.append(f"{label} queue Status: state={expected}, projection={value}")
        value = read_task_field(record_text, "Status")
        value = value.strip("`") if value else "missing"
        label = record.relative_to(project_root).as_posix() if record else "task record (missing or ambiguous)"
        if value != expected:
            drift.append(f"{label} record Status: state={expected}, projection={value}")
        results.append(AuditResult(
            "ADVISORY" if drift else "PASS", "task-state",
            f"{relative}: " + ("; ".join(drift) if drift else f"queue Status and record Status match {expected}"),
        ))
    return results
