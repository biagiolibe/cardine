"""Validate authoritative states and report disposable generated-view drift."""
from __future__ import annotations

from pathlib import Path
from cardine.shared.layout import names
from cardine.shared.errors import CardineError
from cardine.shared.models import AuditResult
from cardine.stops.render import stop_error
from cardine.tasks.state import read_task_state
from cardine.tasks.contract import frozen_human_fields, resolve_human_fields
from cardine.tasks.status_render import stale_views


def audit_task_state_projections(project_root: Path, workflow: str) -> list[AuditResult]:
    """Read validated state only; generated output never repairs or gates state."""
    project_root = project_root.resolve()
    paths = sorted((project_root / names().tasks_path).glob("*.json"))
    results = []
    for path in paths:
        relative = path.relative_to(project_root).as_posix()
        try:
            state = read_task_state(project_root, path.stem, workflow, stop_factory=stop_error)
        except (CardineError, OSError, UnicodeError) as error:
            results.append(AuditResult("FAIL", "task-state", f"{relative}: {error}"))
            continue
        results.append(AuditResult("PASS", "task-state", f"{relative}: validated status={state['status']}"))
        try:
            human = frozen_human_fields(state)
            record = project_root / human["recordPath"]
            # This comparison is diagnostic only. It never repairs or gates state.
            from types import SimpleNamespace
            current = resolve_human_fields(project_root, SimpleNamespace(
                canonical_id=state["task_id"], task_path=record),
                record.read_text(encoding="utf-8"), state["contract"]["class"])
            changed = [key for key in human if human[key] != current[key]]
            if changed:
                results.append(AuditResult("ADVISORY", "task-contract",
                    f"{relative}: contract drift in {', '.join(changed)}; "
                    f"run cardine task contract update {state['task_id']}"))
        except (CardineError, OSError, UnicodeError, ValueError) as error:
            results.append(AuditResult("ADVISORY", "task-contract",
                f"{relative}: {error}; run cardine task contract update {state['task_id']}"))
    if paths and all(row.status != "FAIL" for row in results):
        try:
            drift = stale_views(project_root)
            detail = ", ".join(path.relative_to(project_root).as_posix() for path in drift)
        except (CardineError, OSError, UnicodeError) as error:
            detail = str(error)
        if detail:
            results.append(AuditResult("ADVISORY", "generated-status",
                f"stale generated output: {detail}; regenerate with cardine status --write"))
    return results
