"""Verdicts bound to issued host sessions; Markdown is an optional projection."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from cardine.lifecycle import receipts
from cardine.lifecycle.control import (authorize, operation_state, source_digest,
                                       require_review_budget, verify_control_inputs)
from cardine.shared.errors import CardineError
from cardine.shared.git import git_output, current_branch, scoped_command
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import validate_task_state, review_is_required
from cardine.templates.mode import detect_mode


@scoped_command
def record_review_verdict(project_root: Path, task_id: str, verdict: str, *, owner: bool = False,
                          body: str = '', adapter=None, request_id=None) -> dict:
    """Authorize before replay, preserving the first verdict/time across interruption."""
    root = Path(project_root).resolve()
    identity = resolve_task_identity(root, task_id, 'existing')
    task_id = identity.canonical_id
    if current_branch(root) != identity.branch_name:
        raise stop_error('TASK_STATE_INVALID', 'review requires the task branch', task_id=task_id, project=root)
    if verdict not in ('APPROVE', 'CHANGES_REQUESTED', 'BLOCKED'):
        raise CardineError('invalid verdict')
    with receipts.task_lock(root, task_id):
        state, pending = operation_state(root, task_id)
        if not review_is_required(state):
            raise stop_error('TASK_STATE_INVALID', 'review requires a required-review task', task_id=task_id, project=root)
        if not pending and (not state.get('run', {}).get('reviewDecision')
                or state.get('review', {}).get('verdict') is None):
            _clean_review_outputs(root, task_id, identity, initial=True)
        head = git_output(root, 'rev-parse', 'HEAD')
        binding = dict(task_id=task_id, root=str(root), source=head,
                       source_digest=source_digest(root, task_id, pending),
                       contract=receipts.digest(receipts.encoded(state['contract'])),
                       verdict=verdict, body=body, owner=owner, request_id=request_id)
        saved = state.get('run', {}).get('reviewDecision')
        if state['status'] != 'in_review' and (not saved or saved['binding']['source'] != head):
            raise stop_error('TASK_STATE_INVALID', 'review status: allowed in_review', task_id=task_id, project=root)
        session = None
        if not owner:
            record = state.get('run', {}).get('hostLaunches', {}).get(request_id)
            if not record or not record['session'] or not record['response']:
                raise stop_error('REVIEW_NOT_APPROVED', 'cause: missing; no completed issued independent review',
                                 task_id=task_id, project=root)
            request, session = record['request'], record['session']
            if (request['role'] != 'reviewer' or session['role'] != 'reviewer'
                    or request['task_id'] != task_id or request['root'] != str(root)
                    or request['contract'] != binding['contract']
                    or request['source'] != head or request['source_digest'] != binding['source_digest']
                    or record['response']['session'] != session):
                raise stop_error('REVIEW_NOT_APPROVED', 'cause: stale; issued review inputs changed',
                                 task_id=task_id, project=root)
            for other in state['run']['hostLaunches'].values():
                if other['request']['role'] == 'implementer' and (
                        other['response'] is None or other['request']['profile'] == session['profile']
                        or other['session'] and other['session']['session_id'] == session['session_id']):
                    raise CardineError('review is not independent of the implementer')
        principal = authorize(adapter, 'owner-verdict' if owner else 'verdict', binding, session=session)
        verify_control_inputs(root, task_id, state, pending, binding)
        command = dict(binding=binding, principal=principal)
        kind = 'review_verdict:' + receipts.digest(receipts.encoded(command))
        saved = state.get('run', {}).get('reviewDecision')
        if pending:
            if saved != command:
                raise CardineError('review has changed inputs or foreign owner')
            return receipts.replay_operation(root, task_id, kind=kind)
        if saved == command:
            if state.get('review', {}).get('verdict') != verdict:
                raise CardineError('issued review session has already been consumed')
            # A changed projection must not be overwritten by an ordinary retry.
            receipts.verify_receipts(root, state, artifact_names={identity.review_path.relative_to(root).as_posix()})
            _clean_review_outputs(root, task_id, identity)
            return state
        if not owner and any(item['binding'].get('request_id') == request_id
                for item in state.get('run', {}).get('reviewDecisions', [])):
            raise CardineError('issued review session has already recorded a different verdict')
        if state['status'] != 'in_review':
            raise stop_error('TASK_STATE_INVALID', 'review status: allowed in_review', task_id=task_id, project=root)
        require_review_budget(root, task_id, state)
        if git_output(root, 'status', '--porcelain', '--untracked-files=all'):
            # Issued session receipts may be the only uncommitted CLI output.
            _clean_review_outputs(root, task_id, identity, initial=True)
        if verdict == 'APPROVE':
            submitted = state['transitions'][-1]['commit']
            from cardine.shared.git import _run_git
            allowed = {p.relative_to(root).as_posix() for p in
                       (identity.task_path, identity.handoff_path, identity.review_path)}
            from cardine.tasks.state import state_path
            allowed.add(state_path(root, task_id).relative_to(root).as_posix())
            changed = set(git_output(root, 'log', '--format=', '--name-only', f'{submitted}..{head}').splitlines()) - {''}
            if _run_git(root, 'merge-base', '--is-ancestor', submitted, head).returncode or changed - allowed:
                raise stop_error('REVIEW_NOT_APPROVED', 'cause: stale; implementation changed after submission',
                                 task_id=task_id, project=root)
        from cardine.tasks.preflight import check_dependencies
        check_dependencies(root, task_id, '')
        at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        updated = _review_verdict_projection(state, verdict, head, 'owner' if owner else 'reviewer', at)
        updated.setdefault('run', {})['reviewDecision'] = command
        updated['run'].setdefault('reviewDecisions', []).append(command)
        updated['run']['reviewRecordedAt'] = at
        if verdict == 'CHANGES_REQUESTED':
            # A new delivery and measured validation are required for remediation.
            updated['run'].pop('delivery', None)
            updated['run'].pop('validation', None)
        validate_task_state(updated, task_id, detect_mode(root))
        review_text = identity.review_path.read_text(encoding='utf-8') if identity.review_path.exists() else ''
        projection = _review_attempt_text(review_text, updated['review']['attempt'], verdict, body)
        return receipts.write_operation(root, task_id, updated, kind=kind, previous=state, state_first=True,
            files={identity.review_path.relative_to(root).as_posix(): projection.encode()})


def _clean_review_outputs(root, task_id, identity, initial=False):
    from cardine.tasks.state import state_path
    from cardine.shared.git import _run_git
    state, _ = operation_state(root, task_id)
    state_name = state_path(root, task_id).relative_to(root).as_posix()
    from cardine.shared.layout import names
    allowed = {state_name, identity.handoff_path.relative_to(root).as_posix(),
               names().execution_evidence_path(task_id).as_posix()}
    if not initial:
        allowed.add(identity.review_path.relative_to(root).as_posix())
    covered = {}
    for receipt in state['run']['receipts']:
        covered.update(receipt['outputs'])
    for line in _run_git(root, 'status', '--porcelain', '--untracked-files=all').stdout.splitlines():
        name = line[3:]
        path = receipts.safe_path(root, name)
        if (name not in allowed or line[:2] not in (' M', '??')
                or name != state_name and (not path.is_file() or receipts.digest(path.read_bytes()) != covered.get(name))):
            raise stop_error('TASK_STATE_INVALID', 'worktree: unexpected uncommitted changes', task_id=task_id, project=root)


def _review_verdict_projection(state, verdict, head, approved_by, at):
    state = deepcopy(state)
    attempt = state.get('review', {}).get('attempt', 0) + 1
    state['review'] = dict(required=True, verdict=verdict, attempt=attempt,
                           reviewed_commit=head, approved_by=approved_by, source='local')
    state.setdefault('review_history', []).append(dict(state['review']))
    if verdict != 'BLOCKED':
        state['transitions'].append({'from': state['status'], 'to': 'in_progress', 'commit': head, 'at': at})
        state['status'] = 'in_progress'
    return state


def _review_attempt_text(text, attempt, verdict, body):
    prefix = text.rstrip() + '\n\n' if text.strip() else ''
    return prefix + f'## Attempt {attempt} — {verdict}\n' + ('\n' + body.rstrip() + '\n' if body else '')
