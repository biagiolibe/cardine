from __future__ import annotations

from cardine.shared.errors import CardineError
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
from cardine.tasks.state import read_task_state
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import state_path
from cardine.stops.render import stop_error
from datetime import timezone
from cardine.tasks.state import validate_task_state, review_is_required


def transition_task_state(project_root: Path, task_id: str, status: str, *, cancellation_authority: str = "", reason: str = "") -> dict[str, object]:
    """Apply one validated machine transition without changing the task record."""
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    workflow = detect_mode(project_root)
    review_required = None
    try:
        path = state_path(project_root, task_id)
        state = read_task_state(project_root, task_id, workflow, stop_factory=stop_error, require_contract=True)
        spike = state["contract"]["class"] == "spike"
        review_required = review_is_required(state)
        if state["status"] == "in_review" and status == "in_progress":
            raise TaskStateInvalid("return from review requires cardine review verdict")
        if status == "done":
            raise TaskStateInvalid("done requires verified landing through integration")
        if status == "cancelled" and (not cancellation_authority.strip() or not reason.strip()):
            raise TaskStateInvalid("cancellation requires explicit authority and reason")
        if status == "in_progress" and state["status"] == "queued":
            from cardine.tasks.preflight import check_dependencies
            check_dependencies(project_root, task_id, "")
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
    _write_json_atomic(path, state)
    return state


def close_task(project_root: Path, task_id: str) -> dict[str, object]:
    """Verify closure from committed records; the record stays at its path and landing writes done."""
    project_root = project_root.resolve()
    _execution_worktree(project_root, task_id, command=("task", "close"))
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    for label, path in (("task record", identity.task_path), ("handoff", identity.handoff_path)):
        relative = path.relative_to(project_root).as_posix()
        if not path.is_file() or _run_git(project_root, "cat-file", "-e", f"HEAD:{relative}").returncode:
            code = "HANDOFF_REPORT_MISSING" if label == "handoff" else "TASK_STATUS_REJECTED"
            raise stop_error(code, f"task close requires a committed {label}; commit it before cardine task close",
                             task_id=task_id, project=project_root)
    state = read_task_state(project_root, task_id, detect_mode(project_root), stop_factory=stop_error, require_contract=True)
    if state["status"] != "in_progress":
        raise stop_error("TASK_STATUS_REJECTED", "closure requires in_progress; done is written by landing",
                         task_id=task_id, project=project_root)
    return {"task_id": task_id, "state": state, "record": identity.task_path.relative_to(project_root).as_posix(),
            "verified": True, "staged": False, "committed": False}


def record_spike_outcome(project_root: Path, task_id: str, outcome: str) -> dict[str, object]:
    """Record a spike result without treating the result as a lifecycle state."""
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    state = read_task_state(project_root, task_id, detect_mode(project_root), stop_factory=stop_error, require_contract=True)
    contract = state["contract"]
    if (contract["class"] != "spike" or state["status"] != "in_progress"
            or outcome not in ("ANSWERED", "INCONCLUSIVE")):
        raise stop_error("TASK_STATUS_REJECTED", "outcome requires an in_progress spike and ANSWERED or INCONCLUSIVE",
                         task_id=task_id, project=project_root)
    if outcome == "ANSWERED":
        from cardine.shared.git import current_branch
        from cardine.tasks.contract_fields import frozen_human_fields
        deliverables = frozen_human_fields(state)["deliverables"]
        if current_branch(project_root) != identity.branch_name:
            raise stop_error("TASK_STATUS_REJECTED", "ANSWERED requires the task branch",
                             task_id=task_id, project=project_root)
        base = git_output(project_root, "merge-base", "main", "HEAD")
        changed = set(git_output(project_root, "diff", "--name-only", base, "HEAD").splitlines())
        missing = sorted(set(deliverables) - changed)
        if missing:
            raise stop_error("TASK_STATUS_REJECTED", "ANSWERED requires changed frozen deliverables: "
                             + ", ".join(missing), task_id=task_id, project=project_root)
    # Changing a research result invalidates any previous approval of that result.
    if state.get("outcome") != outcome and state.get("review"):
        state["review"] = dict(state["review"], verdict=None, reviewed_commit=None, approved_by=None)
    state["outcome"] = outcome
    validate_task_state(state, task_id, detect_mode(project_root))
    _write_json_atomic(state_path(project_root, task_id), state)
    return state
