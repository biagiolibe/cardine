from __future__ import annotations

from cardine.shared.errors import CardineError
from cardine.shared.errors import CardineStop
from pathlib import Path
from cardine.tasks.state import TaskStateInvalid
from cardine.lifecycle.execution import _execution_worktree
from cardine.shared.git import _run_git
from cardine.shared.jsonio import _write_json_atomic
from datetime import datetime
from cardine.lifecycle.execution import delivery_readiness
from cardine.templates.mode import detect_mode
from cardine.shared.git import git_output
from cardine.tasks.state import machine
import re
from cardine.shared.text import read_task_field
from cardine.tasks.state import read_task_state
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import state_path
from cardine.stops.render import stop_error
from datetime import timezone
from cardine.tasks.state import validate_task_state


def transition_task_state(project_root: Path, task_id: str, status: str) -> dict[str, object]:
    """Apply one validated machine transition and update the record projection."""
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    workflow = detect_mode(project_root)
    record = identity.task_path.read_text(encoding="utf-8")
    spike = read_task_field(record, "Class") == "SPIKE"
    review_required = read_task_field(record, "Review") != "NOT_REQUIRED"
    try:
        path = state_path(project_root, task_id)
        try:
            state = read_task_state(project_root, task_id, workflow, spike=spike, review_required=review_required, stop_factory=stop_error)
        except CardineStop as error:
            if error.code != "TASK_STATE_MISSING":
                raise
            state = {"version": 1, "task_id": task_id, "workflow": workflow,
                     "status": "QUEUED", "transitions": []}
        allowed = machine(workflow, spike, review_required)[state["status"]]
        if status not in allowed:
            raise TaskStateInvalid(f"transition from {state['status']}: allowed {list(allowed)}; found {status!r}")
        state["transitions"].append({
            "from": state["status"], "to": status,
            "commit": git_output(project_root, "rev-parse", "HEAD"),
            "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        state["status"] = status
        validate_task_state(state, task_id, workflow, spike=spike, review_required=review_required)
    except TaskStateInvalid as error:
        raise stop_error("TASK_STATE_INVALID", str(error), task_id=task_id, project=project_root) from error
    if status == "READY_FOR_REVIEW":
        delivery_readiness(project_root, task_id)
    projection = re.sub(r"^Status:[^\n]*", f"Status: {status}", record, flags=re.MULTILINE)
    _write_json_atomic(path, state)
    if projection != record:
        identity.task_path.write_text(projection, encoding="utf-8")
    return state


def close_task(project_root: Path, task_id: str) -> dict[str, object]:
    """Close a validated Lean task, staging its state and exact record archive."""
    project_root = project_root.resolve()
    _execution_worktree(project_root, task_id, command=("task", "close"))
    if detect_mode(project_root) != "lean-delivery":
        raise stop_error("TASK_STATUS_REJECTED", "task close is Lean-only; use meridian task transition for Governed SDD",
                         task_id=task_id, project=project_root)
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    record_path = identity.task_path
    if record_path.parent.name == "done":
        raise stop_error("TASK_STATUS_REJECTED", "record is already archived; use meridian worktree advance",
                         task_id=task_id, project=project_root)
    archive = record_path.parent / "done" / record_path.name
    if archive.exists():
        raise stop_error("TASK_STATUS_REJECTED", "exact archive path already exists; inspect the task record before retrying task close",
                         task_id=task_id, project=project_root)
    handoff = identity.handoff_path.relative_to(project_root).as_posix()
    if not identity.handoff_path.is_file() or _run_git(project_root, "cat-file", "-e", f"HEAD:{handoff}").returncode:
        raise stop_error("HANDOFF_REPORT_MISSING", "task close requires a committed handoff; commit it before meridian task close",
                         task_id=task_id, project=project_root)
    path = state_path(project_root, task_id)
    if path.exists():
        state = read_task_state(project_root, task_id, "lean-delivery", stop_factory=stop_error)
        if state["status"] == "DONE":
            raise stop_error("TASK_STATUS_REJECTED", "task is already DONE; use meridian worktree advance",
                             task_id=task_id, project=project_root)
    # The transition validates everything before writing and is the single state writer.
    state = transition_task_state(project_root, task_id, "DONE")
    archive.parent.mkdir(parents=True, exist_ok=True)
    record_path.rename(archive)
    staged = _run_git(project_root, "add", "--", record_path.relative_to(project_root).as_posix(),
                      archive.relative_to(project_root).as_posix(), path.relative_to(project_root).as_posix())
    if staged.returncode:
        raise CardineError(f"could not stage closure records: {staged.stderr.strip()}")
    return {"task_id": task_id, "state": state, "archive": archive.relative_to(project_root).as_posix(),
            "staged": True, "committed": False}
