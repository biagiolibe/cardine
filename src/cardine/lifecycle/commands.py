from __future__ import annotations

from cardine.lifecycle.execution import _delivery_later_commits
from cardine.lifecycle.execution import _execution_location
from cardine.lifecycle.execution import _execution_owned_paths
from cardine.lifecycle.execution import _execution_state
from cardine.lifecycle.execution import _execution_worktree
from cardine.lifecycle.execution import delivery_readiness
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.git import canonical_project_root
from cardine.shared.git import git_output
from cardine.shared.text import read_task_field
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.preflight import execution_preflight
from cardine.tasks.state import read_task_state
from cardine.tasks.state import state_path
from cardine.tasks.transitions import transition_task_state
from cardine.templates.mode import detect_mode
from pathlib import Path


def execution_start(project_root: Path, task_id: str, *, resume: bool = False) -> dict[str, object]:
    """Record the first legal start only after worktree and contract preflight."""
    inspection = _execution_location(project_root, task_id)
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    workflow = detect_mode(project_root)
    record = identity.task_path.read_text(encoding="utf-8")
    state = read_task_state(project_root, task_id, workflow,
                            spike=(read_task_field(record, "Class") or "").lower() == "spike",
                            review_required=None,
                            stop_factory=stop_error) if state_path(project_root, task_id).exists() else None
    _execution_worktree(project_root, task_id, resume=resume,
                        repeated_start=bool(state and state["status"] == "in_progress"), inspection=inspection)
    status = state["status"] if state else "queued"
    if identity.task_path.parent.name == "done":
        if not resume or status != "in_progress":
            raise stop_error("TASK_STATUS_REJECTED", "archived task requires closure recovery", task_id=task_id, project=project_root)
        dirty = bool(git_output(project_root, "status", "--porcelain"))
        return {"task_id": task_id, "workflow": workflow, "status": status, "started": False,
                "state": state, "commit": git_output(project_root, "rev-parse", "HEAD"),
                "next_action": "commit-closure-records" if dirty else "worktree-advance"}
    eligible = ("queued", "in_progress")
    if status not in eligible:
        raise stop_error("TASK_STATUS_REJECTED", f"execution start allows {eligible}; found {status}", task_id=task_id, project=canonical_project_root(project_root))
    if status == "queued":
        if (project_root / "docs/EXECUTION_EVIDENCE_PROFILE.md").is_file():
            from cardine.tasks.contract import resolve_task_contract
            options = resolve_task_contract(project_root, task_id, text=record)["options"]
            execution_preflight(project_root, task_id, options=options)
        state = transition_task_state(project_root, task_id, "in_progress")

    return {"task_id": task_id, "workflow": workflow, "status": state["status"] if state else status,
            "started": True, "state": state,
            "commit": git_output(project_root, "rev-parse", "HEAD")}



def execution_deliver(project_root: Path, task_id: str) -> dict[str, object]:
    result = delivery_readiness(project_root, task_id, allow_handoff_correction=True)
    task_id = str(result["task_id"])
    if result["status"] == "in_review":
        identity = resolve_task_identity(project_root, task_id, "existing")
        later = _delivery_later_commits(
            project_root, task_id, _execution_state(project_root, task_id), str(result["commit"]),
            _execution_owned_paths(project_root, task_id), identity.handoff_path.relative_to(project_root).as_posix())
        if later:
            completed = _run_git(project_root, "commit", "--allow-empty", "-m", f"Deliver {task_id} for review")
            if completed.returncode:
                raise stop_error("EVIDENCE_INCOMPLETE", f"re-delivery commit failed: {completed.stderr.strip()}",
                                 task_id=task_id, project=canonical_project_root(project_root))
        return delivery_readiness(project_root, task_id)
    try:
        transition_task_state(project_root, task_id, "in_review")
    except (OSError, CardineError) as error:
        actual = _execution_state(project_root, task_id)["status"]
        raise stop_error("EVIDENCE_INCOMPLETE", f"delivery transition failed: {error}; actual state {actual}; inspect git status and repair command-owned state/projection before retrying delivery",
                         task_id=task_id, project=canonical_project_root(project_root)) from error
    identity = resolve_task_identity(project_root, task_id, "existing")
    paths = [state_path(project_root, task_id).relative_to(project_root).as_posix(),
             identity.task_path.relative_to(project_root).as_posix()]
    for args in (("add", "--", *paths), ("commit", "-m", f"Deliver {task_id} for review", "--", *paths)):
        completed = _run_git(project_root, *args)
        if completed.returncode:
            raise stop_error("EVIDENCE_INCOMPLETE", f"delivery {args[0]} failed: {completed.stderr.strip()}; actual state in_review, pending delivery; inspect git status, commit only state/projection, then rerun execution deliver", task_id=task_id, project=canonical_project_root(project_root))
    return delivery_readiness(project_root, task_id)

