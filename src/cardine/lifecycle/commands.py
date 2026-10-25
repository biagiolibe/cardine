from __future__ import annotations

from cardine.lifecycle.execution import _execution_location
from cardine.lifecycle.execution import _execution_state
from cardine.lifecycle.execution import _execution_worktree
from cardine.lifecycle.execution import delivery_readiness
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git
from cardine.shared.git import canonical_project_root
from cardine.shared.git import git_output
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
    from cardine.lifecycle.receipts import pending_operation, _intent_path, _load_intent
    if pending_operation(project_root, task_id):
        # Reconcile only this start's exact owned transaction, never arbitrary dirt.
        intent_path = _intent_path(project_root, task_id)
        intent = _load_intent(intent_path)
        owned = {intent_path.relative_to(project_root).as_posix()}
        for name, item in intent['files'].items():
            owned.update((name, item['staged']))
        owned.add(intent_path.with_name(f'.{task_id}.guard').relative_to(project_root).as_posix())
        changed = set(git_output(project_root, 'diff', 'HEAD', '--name-only').splitlines())
        changed.update(git_output(project_root, 'ls-files', '--others', '--exclude-standard').splitlines())
        if (set(inspection['errors']) - {'dirty-worktree'} or inspection['integration_active']
                or changed - owned):
            raise stop_error('WRONG_WORKTREE', 'start recovery has foreign changes or identity mismatch',
                             task_id=task_id, project=canonical_project_root(project_root))
        transition_task_state(project_root, task_id, 'in_progress')
    state = read_task_state(project_root, task_id, workflow,
                            stop_factory=stop_error, require_contract=True)
    contract = state["contract"]
    _execution_worktree(project_root, task_id, resume=resume,
                        repeated_start=bool(state and state["status"] == "in_progress"), inspection=inspection)
    status = state["status"]
    eligible = ("queued", "in_progress")
    if status not in eligible:
        raise stop_error("TASK_STATUS_REJECTED", f"execution start allows {eligible}; found {status}", task_id=task_id, project=canonical_project_root(project_root))
    if status == "queued":
        if (project_root / "docs/EXECUTION_EVIDENCE_PROFILE.md").is_file():
            options = contract["options"]
            execution_preflight(project_root, task_id, options=options)
        state = transition_task_state(project_root, task_id, "in_progress")

    return {"task_id": task_id, "workflow": workflow, "status": state["status"] if state else status,
            "started": True, "state": state,
            "commit": git_output(project_root, "rev-parse", "HEAD")}



def execution_deliver(project_root: Path, task_id: str, *, implementation_only: bool | None = None) -> dict[str, object]:
    """Frozen surfaces use pre-validation delivery; retain the legacy review adapter.

    The run engine always selects implementation delivery, including the
    missing-surface guardrail. Interactive legacy snapshots keep their existing
    review path until RE4 replaces role dispatch.
    """
    if implementation_only is None:
        _execution_location(project_root, task_id, command=('execution', 'deliver'))
        from cardine.lifecycle.delivery import _operation_path
        implementation_only = (_operation_path(project_root, task_id).exists()
                               or bool(_execution_state(project_root, task_id)['contract'].get('expectedCodeSurface')))
    if implementation_only:
        from cardine.lifecycle.delivery import deliver_implementation
        return deliver_implementation(project_root, task_id)
    result = delivery_readiness(project_root, task_id)
    task_id = str(result["task_id"])
    if result["status"] == "in_review":
        return result
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

