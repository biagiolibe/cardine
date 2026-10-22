"""Validate authoritative states and report disposable generated-view drift."""
from __future__ import annotations

from pathlib import Path
from cardine.shared.layout import names
from cardine.shared.errors import CardineError
from cardine.shared.models import AuditResult
from cardine.stops.render import stop_error
from cardine.tasks.state import read_task_state
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
    if paths and all(row.status == "PASS" for row in results):
        try:
            drift = stale_views(project_root)
            detail = ", ".join(path.relative_to(project_root).as_posix() for path in drift)
        except (CardineError, OSError, UnicodeError) as error:
            detail = str(error)
        if detail:
            results.append(AuditResult("ADVISORY", "generated-status",
                f"stale generated output: {detail}; regenerate with cardine status --write"))
    return results
