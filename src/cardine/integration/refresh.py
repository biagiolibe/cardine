"""Bring a task branch up to date with ``main`` before CI validates the tree that will land.

With ``ciBeforeLanding``, a ``FULL`` integration decision means ``main`` advanced
on paths the task also changed. Cardine then merges ``main`` into the task branch,
so CI and the candidate both see the combined tree and the candidate becomes
``REUSE``. The merge is never a rebase and never rewrites the branch.
"""

from __future__ import annotations

from pathlib import Path

from cardine.integration.decision import IntegrationValidationOutcome
from cardine.integration.evidence import measured_task_validation
from cardine.integration.merge import IntegrationDecisionInputs, integration_decision_inputs
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git, git_output
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.storage import _lifecycle_paths, _merge_head_path


def refresh_inputs(locations, state: dict) -> IntegrationDecisionInputs | None:
    """The decision inputs when a refresh is due, otherwise ``None``.

    Any error falls through to the ordinary path, which reports it as before.
    """
    options = state['contract']['options']
    if not options.get('ciBeforeLanding') or options.get('landingMode') != 'direct':
        return None
    worktree, task_id = locations.worktree, locations.task_id
    try:
        measured = measured_task_validation(worktree, task_id)
        if measured is None:
            return None
        identity = resolve_task_identity(locations.primary, task_id, 'existing')
        head = git_output(worktree, 'rev-parse', 'HEAD')
        inputs = integration_decision_inputs(locations.primary, identity, head, state, measured)
    except CardineError:
        return None
    return inputs if inputs.decision.outcome == IntegrationValidationOutcome.FULL else None


def interacting_paths(inputs: IntegrationDecisionInputs) -> tuple[str, ...]:
    from cardine.integration.decision import _paths_interact
    return tuple(sorted({task for task in inputs.task_paths for main in inputs.main_paths
                         if _paths_interact(task, main)}))


def merge_main(locations, main: str) -> None:
    """Merge ``main`` into the task branch; on a conflict, abort and stop."""
    worktree, task_id, primary = locations.worktree, locations.task_id, locations.primary
    if _run_git(worktree, 'merge-base', '--is-ancestor', main, 'HEAD').returncode == 0:
        return  # An earlier run merged it and stopped before the base update.
    before = git_output(worktree, 'rev-parse', 'HEAD')
    merged = _run_git(worktree, 'merge', '--no-ff', '-m', f'Merge main into task-{task_id}', main)
    if merged.returncode == 0:
        return
    conflict = bool(git_output(worktree, 'ls-files', '--unmerged'))
    if _merge_head_path(worktree).exists():
        aborted = _run_git(worktree, 'merge', '--abort')
        if aborted.returncode:
            raise CardineError('could not abort the refresh merge: ' + aborted.stderr.strip())
    if git_output(worktree, 'rev-parse', 'HEAD') != before or _merge_head_path(worktree).exists():
        raise CardineError('the refresh left the task branch changed; inspect the task worktree')
    if not conflict:
        raise CardineError('transient Git failure while merging main: ' + merged.stderr.strip())
    raise stop_error(
        'INTEGRATION_CONFLICT',
        f'merging main ({main[:12]}) into task-{task_id} conflicts. In the task worktree {worktree}, '
        f'run `git merge main`, resolve the conflict and commit, then run `cardine run {task_id}` again',
        task_id=task_id, project=primary,
        resume=f'cardine run {task_id} --project {primary}')


def record_base(locations, main: str) -> None:
    """Make ``main`` the task's recorded base through the owned preparation receipt."""
    from cardine.worktree.preparation import repair_preparation
    from cardine.shared.jsonio import _read_json_object
    identity = resolve_task_identity(locations.primary, locations.task_id, 'existing')
    path, _lease, _staged = _lifecycle_paths(locations.primary, identity)
    state = _read_json_object(path, 'worktree lifecycle state')
    if state.get('base_commit') != main:
        repair_preparation(locations.primary, identity, dict(state), dict(state, base_commit=main))
    rebase_delivery(locations, main)


def rebase_delivery(locations, main: str) -> None:
    """Carry the finished delivery record to the new base.

    The delivery it records is stale against the new base, so ``verify_delivery``
    returns nothing and the merged head is delivered and validated as new work.
    A delivery still in flight is left untouched.
    """
    from cardine.lifecycle import receipts
    from cardine.lifecycle.delivery import _operation_path
    operation = _operation_path(locations.worktree, locations.task_id)
    if not operation.exists():
        return
    intent = receipts._load_intent(operation)
    if intent.get('result') == 'verified' and intent.get('base') != main:
        receipts._save_intent(operation, dict(intent, base=main))


def refresh_to(locations, main: str) -> dict:
    """Merge ``main`` into the task branch and record it as the base."""
    merge_main(locations, main)
    record_base(locations, main)
    return dict(main=main, head=git_output(locations.worktree, 'rev-parse', 'HEAD'))


def refresh_from_main(locations, inputs: IntegrationDecisionInputs) -> dict:
    """Refresh for a ``FULL`` decision, naming the task paths that interacted with main."""
    return dict(refresh_to(locations, inputs.current_main), paths=interacting_paths(inputs))


def dirty(locations) -> bool:
    """Whether the task worktree has any uncommitted or untracked change."""
    return bool(git_output(locations.worktree, 'status', '--porcelain'))


def _policy_digest(blob: bytes) -> str:
    from cardine.lifecycle import receipts
    return receipts.digest(blob)


def policy_predates_main(locations) -> str | None:
    """Return ``main``'s commit when the task branch only lacks the accepted policy.

    All of these must hold: the task worktree's policy differs from the accepted
    one, the policy of current ``main`` is the accepted one, and the task did not
    change the policy file since its recorded base. A policy the task wrote is
    never accepted by this path (decision 14).
    """
    from cardine.lifecycle import receipts
    from cardine.shared.layout import names
    from cardine.tasks.identity import resolve_task_identity
    primary, worktree = locations.primary, locations.worktree
    relative = names().project_declaration_path.as_posix()
    try:
        accepted = _accepted_policy(primary)
        branch = (worktree / relative).read_bytes()
        if accepted is None or _policy_digest(branch) == accepted:
            return None
        main = _run_git(primary, 'show', f'main:{relative}')
        main_bytes = _run_git(primary, 'show', f'main:{relative}', text=False)
        if main.returncode or _policy_digest(main_bytes.stdout) != accepted:
            return None
        identity = resolve_task_identity(primary, locations.task_id, 'existing')
        state = _read_lifecycle_state(primary, identity)
        base = _run_git(primary, 'show', f"{state['base_commit']}:{relative}", text=False)
        if base.returncode or base.stdout != branch:
            return None
        return git_output(primary, 'rev-parse', 'main')
    except (CardineError, OSError, KeyError, ValueError):
        return None


def _read_lifecycle_state(primary, identity) -> dict:
    from cardine.shared.jsonio import _read_json_object
    return _read_json_object(_lifecycle_paths(primary, identity)[0], 'worktree lifecycle state')


def _accepted_policy(primary) -> str | None:
    import json
    from cardine.lifecycle import receipts
    path = receipts._local_authority_path(primary)
    accepted = json.loads(path.read_bytes()) if path.exists() else None
    return accepted.get('policy') if isinstance(accepted, dict) else None


def policy_refresh_blocked(locations) -> bool:
    """True while an operation, a lease or a staged candidate owns the task."""
    from cardine.integration.candidate import operation_path
    from cardine.lifecycle import receipts
    identity = resolve_task_identity(locations.primary, locations.task_id, 'existing')
    _state, lease, staged = _lifecycle_paths(locations.primary, identity)
    return (lease.exists() or staged.exists() or operation_path(locations, 'cleanup').exists()
            or operation_path(locations, 'finalize').exists()
            or bool(receipts.pending_operation(locations.worktree, locations.task_id)))
