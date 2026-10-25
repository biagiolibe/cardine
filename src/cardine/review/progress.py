"""Read-only review facts from receipt-covered decisions and issued requests."""
from cardine.lifecycle import receipts
from cardine.lifecycle.control import source_digest
from cardine.shared.git import _run_git, git_output
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state_core import state_path


def review_progress(root, task_id, state):
    contract = receipts.digest(receipts.encoded(state['contract']))
    source = source_digest(root, task_id)
    head = git_output(root, 'rev-parse', 'HEAD')
    decision = state.get('run', {}).get('reviewDecision')
    approved = False
    if decision and state.get('review', {}).get('verdict') == 'APPROVE':
        bound = decision['binding']
        identity = resolve_task_identity(root, task_id, 'existing')
        allowed = {p.relative_to(root).as_posix() for p in
                   (identity.task_path, identity.handoff_path, identity.review_path, state_path(root, task_id))}
        from cardine.shared.layout import names
        allowed.add(names().execution_evidence_path(task_id).as_posix())
        reviewed = state['review']['reviewed_commit']
        changed = set(git_output(root, 'log', '--format=', '--name-only', f'{reviewed}..{head}').splitlines()) - {''}
        approved = (bound.get('contract') == contract and bound.get('source_digest') == source
                    and bound.get('source') == reviewed and bound.get('verdict') == 'APPROVE'
                    and not _run_git(root, 'merge-base', '--is-ancestor', reviewed, head).returncode
                    and not changed - allowed)
    pending = any(record['request']['role'] == 'reviewer'
                  and record['request']['contract'] == contract
                  and record['request']['source'] == head
                  and record['request']['source_digest'] == source
                  and not (decision and decision['binding'].get('request_id') == key)
                  for key, record in state.get('run', {}).get('hostLaunches', {}).items())
    return approved, pending


def prepare_review(root, task_id, *, context=None):
    """Enter review only after real current delivery, validation and dependencies."""
    from copy import deepcopy
    from datetime import datetime, timezone
    from cardine.lifecycle.control import operation_state, require_review_budget
    from cardine.tasks.validation import verified_validation, host_observations_complete
    from cardine.tasks.preflight import check_dependencies
    from cardine.tasks.state_core import validate_task_state
    from cardine.templates.mode import detect_mode
    from cardine.shared.errors import CardineError
    with receipts.task_lock(root, task_id):
        state, pending = operation_state(root, task_id)
        binding = dict(task_id=task_id, contract=receipts.digest(receipts.encoded(state['contract'])),
                       source=git_output(root, 'rev-parse', 'HEAD'))
        kind = 'review-submit:' + receipts.digest(receipts.encoded(binding))
        if pending:
            return receipts.replay_operation(root, task_id, kind=kind)
        require_review_budget(root, task_id, state)
        if state['status'] == 'in_review':
            return state
        check_dependencies(root, task_id, '')
        progress = verified_validation(root, task_id, state)
        if (state['status'] != 'in_progress' or state['contract']['options']['review'] != 'required'
                or progress is None or progress['phase'] != 'passed'
                or not host_observations_complete(state['contract'], progress)):
            raise CardineError('review submission requires current measured passing validation')
        from cardine.lifecycle.execution import _execution_location, _execution_owned_paths
        from cardine.lifecycle.scope import enforce_scope
        inspection = _execution_location(root, task_id, context=context)
        if set(inspection['errors']) - {'dirty-worktree'} or inspection['integration_active']:
            raise CardineError('review submission requires the canonical task worktree')
        enforce_scope(root, state, str(inspection['base_commit']),
                      owned=_execution_owned_paths(root, task_id, context=context))
        updated = deepcopy(state)
        updated['status'] = 'in_review'
        updated['transitions'].append({'from': 'in_progress', 'to': 'in_review', 'commit': binding['source'],
            'at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')})
        if updated.get('review'):
            updated['review'] = dict(updated['review'], verdict=None, reviewed_commit=None, approved_by=None)
        validate_task_state(updated, task_id, detect_mode(root))
        return receipts.write_operation(root, task_id, updated, previous=state, kind=kind)
