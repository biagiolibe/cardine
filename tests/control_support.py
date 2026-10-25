"""Explicit disposable host permissions for pre-existing lifecycle fixtures."""
from copy import deepcopy
import json
from cardine.hosts.launch import ProfileAdapter
from cardine.lifecycle import receipts
from cardine.shared.git import git_output
from cardine.tasks.state_core import state_path


class ControlHost:
    def profile(self, role):
        from cardine.hosts.launch import RoleProfile
        return RoleProfile('fixture-' + role, role, True)

    def authorize(self, credential, action):
        return (credential == 'developer' and action == 'developer'
                or credential == 'reviewer' and action == 'verdict'
                or credential == 'coordinator' and action == 'abort')

    def authorize_operation(self, credential, action, binding, session):
        expected = 'reviewer' if session else 'coordinator' if action == 'abort' else 'developer'
        if credential != expected:
            return None
        if session:
            return {key: session[key] for key in ('host', 'profile', 'session_id', 'role')}
        return dict(host='fixture', profile=expected, session_id=expected + '-channel', role=expected)


def adapter(role='developer'):
    return ProfileAdapter('fixture', ControlHost(), role)


def issue_fixture_review(root, task_id):
    """Issue fixture provenance explicitly, then exercise the real guarded writer.

    Run-engine tests use launch_work instead; legacy isolated verdict fixtures
    intentionally have neither a canonical worktree nor a delivery operation.
    """
    from cardine.lifecycle.control import operation_state, source_digest
    state, pending = operation_state(root, task_id)
    key = 'fixture-review-' + git_output(root, 'rev-parse', 'HEAD')
    if key in state.get('run', {}).get('hostLaunches', {}):
        return key
    request = dict(task_id=task_id, root=str(root), attempt=key,
        contract=receipts.digest(receipts.encoded(state['contract'])),
        source=git_output(root, 'rev-parse', 'HEAD'), source_digest=source_digest(root, task_id),
        role='reviewer', host='fixture', profile='fixture-reviewer', request_id=key,
        work=dict(role='reviewer', worktree=str(root), contract_digest=receipts.digest(receipts.encoded(state['contract'])),
            expected_surface=[], acceptance_references=[], validation_references=[], delivery_receipt_requirements=[]),
        authority=receipts.require_authority(root))
    session = dict(request_id=key, role='reviewer', host='fixture', profile='fixture-reviewer', session_id=key)
    updated = deepcopy(state)
    updated.setdefault('run', {}).setdefault('hostLaunches', {})[key] = dict(request=request,
         session=session, response=dict(session=session, result='completed'))
    with receipts.task_lock(root, task_id):
        receipts.write_operation(root, task_id, updated, previous=state, kind='fixture-issued-review')
    return key


def issued_verdict(root, task_id, verdict, **kwargs):
    from cardine.review.verdict import record_review_verdict
    from cardine.lifecycle.control import operation_state
    from cardine.tasks.identity import resolve_task_identity
    from cardine.shared.git import current_branch
    identity = resolve_task_identity(root, task_id, 'existing')
    if current_branch(root) != identity.branch_name:
        return record_review_verdict(root, task_id, verdict, **kwargs)
    state, pending = operation_state(root, task_id)
    if not state['contract']['options']['review'] == 'required':
        return record_review_verdict(root, task_id, verdict, **kwargs)
    owner = kwargs.get('owner', False)
    key = 'fixture-review-' + git_output(root, 'rev-parse', 'HEAD')
    if not owner and key not in state.get('run', {}).get('hostLaunches', {}) and state['status'] == 'in_review':
        from cardine.stops.render import stop_error
        if git_output(root, 'status', '--porcelain', '--untracked-files=all'):
            raise stop_error('TASK_STATE_INVALID', 'worktree: unexpected uncommitted changes', task_id=task_id, project=root)
        if verdict == 'APPROVE':
            submitted = state['transitions'][-1]['commit']
            allowed = {p.relative_to(root).as_posix() for p in
                       (identity.task_path, identity.handoff_path, identity.review_path, state_path(root, task_id))}
            changed = set(git_output(root, 'log', '--format=', '--name-only', f'{submitted}..HEAD').splitlines()) - {''}
            if changed - allowed:
                raise stop_error('REVIEW_NOT_APPROVED', 'cause: stale; implementation changed after submission', task_id=task_id, project=root)
        key = issue_fixture_review(root, task_id)
    return record_review_verdict(root, task_id, verdict, adapter=adapter('developer' if owner else 'reviewer'),
                                 request_id=None if owner else key, **kwargs)


def bind_fixture_approval(root, task_id):
    """Explicit fixture decision for integration tests that construct histories."""
    from cardine.lifecycle.control import source_digest
    state = json.loads(state_path(root, task_id).read_bytes())
    if not state.get('run') or not state.get('review', {}).get('required') or state.get('review', {}).get('verdict') != 'APPROVE':
        return state
    updated = deepcopy(state)
    command = dict(principal=dict(host='fixture', profile='fixture-reviewer', role='reviewer', session_id='fixture'),
        binding=dict(task_id=task_id, root=str(root.resolve()), source=state['review']['reviewed_commit'],
            source_digest=source_digest(root, task_id), contract=receipts.digest(receipts.encoded(state['contract'])),
            verdict='APPROVE', body='', owner=False, request_id='fixture'))
    updated['run']['reviewDecision'] = command
    with receipts.task_lock(root, task_id):
        return receipts.write_operation(root, task_id, updated, previous=state,
            kind='review_verdict:' + receipts.digest(receipts.encoded(command)))
