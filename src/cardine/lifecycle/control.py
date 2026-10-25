"""Host-authorized Stable controls; hashes describe bindings, not authorship.

The injected host must authorize the exact operation or issued session. No
adapter is installed here and neither CLI flags nor environment role labels
create developer authority. Work item 9 owns real host installation.
"""
from copy import deepcopy
from pathlib import Path

from cardine.lifecycle import receipts
from cardine.lifecycle.source import execution_source_digest
from cardine.shared.errors import CardineError
from cardine.shared.git import git_output, scoped_command
from cardine.stops.render import stop_error
from cardine.tasks.state import read_task_state
from cardine.templates.mode import detect_mode


def host_adapter():
    """Integration point for an effectively enforced host channel, unavailable by default."""
    return None


def authorize(adapter, action, binding, *, session=None):
    adapter = adapter or host_adapter()
    if adapter is None:
        raise stop_error('COMMAND_REFUSED', 'host role boundary unavailable: authorized channel required')
    adapter.require('verdict' if session else 'developer' if action != 'abort' else 'abort')
    method = getattr(adapter.transport, 'authorize_operation', None)
    from cardine.shared.git import invalidate_facts
    try:
        principal = method(adapter.credential, action, deepcopy(binding), deepcopy(session)) if method else None
        if session:
            profile_reader = getattr(adapter.transport, 'profile', lambda role: None)
            reviewer, implementer = profile_reader('reviewer'), profile_reader('implementer')
            if (not reviewer or not implementer or not reviewer.enforced or not implementer.enforced
                    or reviewer.role != 'reviewer' or implementer.role != 'implementer'
                    or reviewer.identity != session['profile'] or reviewer.identity == implementer.identity):
                raise CardineError('host reviewer profile boundary unavailable or changed')
    finally:
        invalidate_facts()
    if (not isinstance(principal, dict) or set(principal) != {'host', 'profile', 'session_id', 'role'}
            or principal['host'] != adapter.host or not all(isinstance(v, str) and v for v in principal.values())
            or principal['role'] != ('reviewer' if session else 'coordinator' if action == 'abort' else 'developer')):
        raise CardineError('host denied bound operation ' + action)
    if session and any(principal[k] != session[k] for k in ('host', 'profile', 'session_id', 'role')):
        raise CardineError('host denied foreign review session')
    return principal


def operation_state(root, task_id):
    """Inspect an intact pending intent without blessing it; replay checks ownership."""
    if receipts.pending_operation(root, task_id):
        intent = receipts._load_intent(receipts._intent_path(root, task_id))
        if intent['task_id'] != task_id or intent['authority'] != receipts.require_authority(root):
            raise CardineError('foreign control operation')
        return intent['state'], intent
    return read_task_state(root, task_id, detect_mode(root), stop_factory=stop_error, require_contract=True), None


def source_digest(root, task_id, pending=None):
    ignored = []
    if pending:
        ignored = [receipts._intent_path(root, task_id).relative_to(root).as_posix(),
                   *[item['staged'] for item in pending['files'].values()]]
    return execution_source_digest(root, task_id, operation_paths=ignored)


def verify_control_inputs(root, task_id, state, pending, binding):
    """Host callbacks are external observations; never accept changed inputs."""
    from cardine.tasks.state_core import state_path
    import json
    if (git_output(root, 'rev-parse', 'HEAD') != binding['source']
            or source_digest(root, task_id, pending) != binding['source_digest']
            or not pending and json.loads(state_path(root, task_id).read_bytes()) != state):
        raise CardineError('control inputs changed during host authorization')


def review_exhausted(state):
    history = state.get('review_history', [])
    return len(history) >= 2 and all(r['verdict'] == 'CHANGES_REQUESTED' for r in history[-2:])


def require_review_budget(root, task_id, state):
    if review_exhausted(state):
        raise stop_error('REVIEW_LOOP_EXHAUSTED', 'two consecutive changes-requested rounds require a new budget decision',
                         task_id=task_id, project=root)


@scoped_command
def cancel_task(task_id, supplied_project=None, *, reason, adapter=None):
    from cardine.lifecycle.context import resolve_run_locations
    locations = resolve_run_locations(task_id, supplied_project)
    root = locations.worktree
    from cardine.tasks.state_core import state_path
    if not state_path(root, locations.task_id).is_file():
        from cardine.tasks.identity import resolve_task_identity
        from cardine.worktree.storage import _branch_commit
        identity = resolve_task_identity(locations.primary, locations.task_id, 'existing')
        if _branch_commit(locations.primary, identity.branch_name) is not None:
            raise CardineError('cancellation requires the existing canonical task worktree')
        root = locations.primary
    return cancel_transition(root, locations.task_id, reason=reason, adapter=adapter)


@scoped_command
def cancel_transition(root, task_id, *, reason='', adapter=None, cancellation_authority=''):
    """Keep the branch and task artifacts; cancellation never reopens a task."""
    from cardine.tasks.state_core import machine, validate_task_state
    from datetime import datetime, timezone
    root = Path(root).resolve()
    if not reason.strip():
        raise CardineError('cancellation requires a reason')
    with receipts.task_lock(root, task_id):
        state, pending = operation_state(root, task_id)
        saved = state.get('run', {}).get('cancellation')
        binding = dict(task_id=task_id, root=str(root), contract=receipts.digest(receipts.encoded(state['contract'])),
                       source=git_output(root, 'rev-parse', 'HEAD'), source_digest=source_digest(root, task_id, pending),
                       reason=reason, authority_label=cancellation_authority)
        principal = authorize(adapter, 'cancel', binding)
        verify_control_inputs(root, task_id, state, pending, binding)
        command = dict(binding=binding, principal=principal)
        kind = 'cancel:' + receipts.digest(receipts.encoded(command))
        if saved and saved != command:
            raise CardineError('cancellation has changed inputs or foreign owner; restart requires a new task')
        if pending:
            return receipts.replay_operation(root, task_id, kind=kind)
        if state['status'] == 'cancelled' and saved == command:
            return state
        if 'cancelled' not in machine(review_required=True)[state['status']]:
            raise CardineError('terminal task cannot be cancelled')
        from cardine.tasks.preflight import check_dependencies
        check_dependencies(root, task_id, '')
        updated = deepcopy(state)
        updated['status'] = 'cancelled'
        updated['transitions'].append({})
        updated['transitions'][-1] = {'from': state['status'], 'to': 'cancelled', 'commit': binding['source'],
            'at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'authority': principal['session_id'], 'reason': reason}
        updated.setdefault('run', {})['cancellation'] = command
        validate_task_state(updated, task_id, detect_mode(root))
        receipts.boundary('before_cancel_transition')
        result = receipts.write_operation(root, task_id, updated, previous=state, kind=kind)
        receipts.boundary('after_cancel_transition')
        return result
