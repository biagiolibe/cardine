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
from cardine.tasks.state import validate_task_state, review_is_required


def transition_task_state(project_root: Path, task_id: str, status: str, *, cancellation_authority: str = "", reason: str = "") -> dict[str, object]:
    """Apply one validated machine transition and update the record projection."""
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    workflow = detect_mode(project_root)
    record = identity.task_path.read_text(encoding="utf-8")
    spike = (read_task_field(record, "Class") or "").lower() == "spike"
    review_required = None
    try:
        path = state_path(project_root, task_id)
        try:
            state = read_task_state(project_root, task_id, workflow, spike=spike, review_required=review_required, stop_factory=stop_error)
        except CardineStop as error:
            if error.code != "TASK_STATE_MISSING":
                raise
            state = {"version": 1, "task_id": task_id, "workflow": workflow,
                     "status": "queued", "transitions": []}
        review_required = review_is_required(state)
        if "contract" not in state:
            from cardine.tasks.contract import resolve_task_contract
            state["contract"] = resolve_task_contract(project_root, task_id, text=record)
            review_required = review_is_required(state)
        if state["status"] == "in_review" and status == "in_progress":
            raise TaskStateInvalid("return from review requires cardine review verdict")
        if status == "done":
            raise TaskStateInvalid("done requires verified landing through integration")
        if status == "cancelled" and (not cancellation_authority.strip() or not reason.strip()):
            raise TaskStateInvalid("cancellation requires explicit authority and reason")
        if status == "in_progress" and state["status"] == "queued":
            from cardine.tasks.preflight import check_dependencies
            check_dependencies(project_root, task_id, record)
        allowed = machine(workflow, spike, review_required)[state["status"]]
        if status not in allowed:
            raise TaskStateInvalid(f"transition from {state['status']}: allowed {list(allowed)}; found {status!r}")
        state["transitions"].append({
            "from": state["status"], "to": status,
            "commit": git_output(project_root, "rev-parse", "HEAD"),
            "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        if status == "cancelled":
            state["transitions"][-1].update(authority=cancellation_authority, reason=reason)
        if status == "in_review" and state.get("review"):
            state["review"] = dict(state["review"], verdict=None, reviewed_commit=None, approved_by=None)
        state["status"] = status
        validate_task_state(state, task_id, workflow, spike=spike, review_required=review_required)
    except TaskStateInvalid as error:
        raise stop_error("TASK_STATE_INVALID", str(error), task_id=task_id, project=project_root) from error
    if status == "in_review":
        delivery_readiness(project_root, task_id)
    projection = re.sub(r"^Status:[^\n]*", f"Status: {status}", record, flags=re.MULTILINE)
    _write_json_atomic(path, state)
    if projection != record:
        identity.task_path.write_text(projection, encoding="utf-8")
    return state


def close_task(project_root: Path, task_id: str) -> dict[str, object]:
    """Stage the exact record archive, leaving status in_progress until landing."""
    project_root = project_root.resolve()
    _execution_worktree(project_root, task_id, command=("task", "close"))
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    record_path = identity.task_path
    if record_path.parent.name == "done":
        raise stop_error("TASK_STATUS_REJECTED", "record is already archived; use cardine worktree advance",
                         task_id=task_id, project=project_root)
    archive = record_path.parent / "done" / record_path.name
    if archive.exists():
        raise stop_error("TASK_STATUS_REJECTED", "exact archive path already exists; inspect the task record before retrying task close",
                         task_id=task_id, project=project_root)
    handoff = identity.handoff_path.relative_to(project_root).as_posix()
    if not identity.handoff_path.is_file() or _run_git(project_root, "cat-file", "-e", f"HEAD:{handoff}").returncode:
        raise stop_error("HANDOFF_REPORT_MISSING", "task close requires a committed handoff; commit it before cardine task close",
                         task_id=task_id, project=project_root)
    path = state_path(project_root, task_id)
    state = read_task_state(project_root, task_id, detect_mode(project_root), stop_factory=stop_error)
    if state["status"] != "in_progress":
        raise stop_error("TASK_STATUS_REJECTED", "closure requires in_progress; done is written by landing",
                         task_id=task_id, project=project_root)
    archive.parent.mkdir(parents=True, exist_ok=True)
    record_path.rename(archive)
    staged = _run_git(project_root, "add", "--", record_path.relative_to(project_root).as_posix(),
                      archive.relative_to(project_root).as_posix(), path.relative_to(project_root).as_posix())
    if staged.returncode:
        raise CardineError(f"could not stage closure records: {staged.stderr.strip()}")
    return {"task_id": task_id, "state": state, "archive": archive.relative_to(project_root).as_posix(),
            "staged": True, "committed": False}


def record_spike_outcome(project_root: Path, task_id: str, outcome: str) -> dict[str, object]:
    """Record a spike result without treating the result as a lifecycle state."""
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    state = read_task_state(project_root, task_id, detect_mode(project_root), stop_factory=stop_error)
    if (state.get("contract", {}).get("class") != "spike" or state["status"] != "in_progress"
            or outcome not in ("ANSWERED", "INCONCLUSIVE")):
        raise stop_error("TASK_STATUS_REJECTED", "outcome requires an in_progress spike and ANSWERED or INCONCLUSIVE",
                         task_id=task_id, project=project_root)
    # Changing a research result invalidates any previous approval of that result.
    if state.get("outcome") != outcome and state.get("review"):
        state["review"] = dict(state["review"], verdict=None, reviewed_commit=None, approved_by=None)
    state["outcome"] = outcome
    validate_task_state(state, task_id, detect_mode(project_root))
    _write_json_atomic(state_path(project_root, task_id), state)
    return state
