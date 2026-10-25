"""Receipt-backed abort of one exact owned candidate, with retained recovery intent."""
from copy import deepcopy
from pathlib import Path

from cardine.lifecycle import receipts
from cardine.lifecycle.control import authorize, operation_state, source_digest, verify_control_inputs
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git, git_output, scoped_command, invalidate_facts
from cardine.shared.jsonio import _read_json_object
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.storage import _lifecycle_paths, _merge_head_path


def _file(path):
    if path.is_symlink():
        raise CardineError('foreign symlink in abort operation')
    return path.read_bytes() if path.exists() else None


def _snapshot(root):
    return receipts.digest(receipts.encoded(dict(
        diff=git_output(root, 'diff', '--binary', 'HEAD'),
        index=git_output(root, 'diff', '--cached', '--binary', 'HEAD'),
        status=git_output(root, 'status', '--porcelain', '--untracked-files=all'))))


def _owned_landing_dirt(root, task_id):
    """Recognize exact CLI landing bytes; preserve its untracked recovery residue.

    Staging owns the pending landing transaction. Abort does not replay or erase
    it: RE5 owns that reconciliation. No arbitrary primary edits are covered.
    """
    from cardine.tasks.state_core import state_path
    from cardine.tasks.state import read_task_state
    from cardine.stops.render import stop_error
    path = state_path(root, task_id)
    name = path.relative_to(root).as_posix()
    if git_output(root, 'diff', '--name-only').splitlines() != [name]:
        return False
    if receipts.pending_operation(root, task_id):
        intent = receipts._load_intent(receipts._intent_path(root, task_id))
        state = intent['state']
        if (intent['task_id'] != task_id or intent['authority'] != receipts.require_authority(root)
                or set(intent['files']) != {name}):
            return False
        item = intent['files'][name]
        if receipts.digest(path.read_bytes()) not in (item['before'], item['digest'],
                receipts.digest(receipts.encoded(intent['pending_state']))):
            return False
    else:
        state = read_task_state(root, task_id, 'single', stop_factory=stop_error)
    receipts.verify_receipts(root, state, artifacts=False)
    last = state['run']['receipts'][-1]
    return (last['kind'] == 'landing_state' and state['status'] == 'done'
            and last['source'] == git_output(root, 'rev-parse', 'HEAD'))


@scoped_command
def abort_owned(task_id, project, *, adapter=None):
    from cardine.lifecycle.context import resolve_run_locations
    locations = resolve_run_locations(task_id, project)
    root = locations.primary
    if git_output(root, 'branch', '--show-current') != 'main':
        raise CardineError('abort requires the primary checkout on main')
    identity = resolve_task_identity(root, locations.task_id, 'existing', check_queue_links=False)
    task_id = identity.canonical_id
    worker = locations.worktree
    _, lease_path, staged_path = _lifecycle_paths(root, identity)
    operation_path = receipts.safe_path(locations.common_dir, f'cardine-operations/{task_id}.abort.json')
    with receipts.task_lock(worker, task_id):
        state, pending = operation_state(worker, task_id)
        saved = receipts._load_intent(operation_path) if operation_path.exists() else None
        lease_bytes, staged_bytes = _file(lease_path), _file(staged_path)
        if saved and saved['result'] == 'verified' and lease_bytes is not None:
            # A newly staged candidate is a new bounded operation.
            if receipts.digest(lease_bytes) != saved['binding']['lease_digest'] or (
                    staged_bytes is not None and receipts.digest(staged_bytes) != saved['binding']['staged_digest']):
                saved = None
        if saved is None:
            if lease_bytes is None:
                raise CardineError('abort requires an issued owned integration lease')
            lease = _read_json_object(lease_path, 'integration lease')
            staged = _read_json_object(staged_path, 'staged integration') if staged_bytes else None
            if (lease.get('task_id') != task_id or lease.get('project') != str(root)
                    or lease.get('branch') != identity.branch_name
                    or staged is not None and staged.get('task_id') != task_id):
                raise CardineError('foreign integration ownership')
            if lease.get('main_commit', git_output(root, 'rev-parse', 'HEAD')) != git_output(root, 'rev-parse', 'HEAD'):
                raise CardineError('foreign lease main identity')
            merge = _file(_merge_head_path(root))
            task_head = git_output(worker, 'rev-parse', 'HEAD')
            if merge:
                if (merge.decode().strip() != task_head or staged is not None and (
                        staged.get('task_commit') != task_head
                        or staged.get('branch') != identity.branch_name
                        or staged.get('project') != str(root))):
                    raise CardineError('foreign or unverified merge target')
                if (git_output(root, 'diff', '--binary') and not _owned_landing_dirt(root, task_id)
                        or staged is not None and git_output(root, 'diff', '--cached', '--name-only', staged['candidate_tree'], '--')):
                    raise CardineError('foreign candidate changes must be preserved before abort')
            binding = dict(task_id=task_id, project=str(root), root=str(worker),
                contract=receipts.digest(receipts.encoded(state['contract'])),
                source=task_head, source_digest=source_digest(worker, task_id, pending),
                lease_digest=receipts.digest(lease_bytes),
                staged_digest=receipts.digest(staged_bytes) if staged_bytes else None,
                main=git_output(root, 'rev-parse', 'HEAD'), merge=merge.decode() if merge else None,
                snapshot=_snapshot(root), authority=receipts.require_authority(worker))
        else:
            binding = saved['binding']
        principal = authorize(adapter, 'abort', binding)
        verify_control_inputs(worker, task_id, state, pending, binding)
        command = dict(binding=binding, principal=principal)
        operation_id = receipts.digest(receipts.encoded(command))
        kind = 'abort:' + operation_id
        result_kind = 'abort-result:' + operation_id
        if saved and saved['principal'] != principal:
            raise CardineError('foreign abort owner')
        if (binding['task_id'] != task_id or binding['project'] != str(root)
                or binding['root'] != str(worker) or binding['authority'] != receipts.require_authority(worker)
                or binding['contract'] != receipts.digest(receipts.encoded(state['contract']))
                or binding['source'] != git_output(worker, 'rev-parse', 'HEAD')
                or binding['source_digest'] != source_digest(worker, task_id, pending)
                or binding['main'] != git_output(root, 'rev-parse', 'HEAD')):
            raise CardineError('abort inputs changed')
        for path, expected in [(lease_path, binding['lease_digest']), (staged_path, binding['staged_digest'])]:
            content = _file(path)
            if content is not None and receipts.digest(content) != expected:
                raise CardineError('foreign lease or staged state; abort preserved it')
        merge = _file(_merge_head_path(root))
        if merge and (merge.decode() != binding['merge'] or _snapshot(root) != binding['snapshot']):
            raise CardineError('candidate changed before abort')
        if saved is None:
            saved = dict(command, result='pending')
            receipts.boundary('before_abort_intent')
            receipts._save_intent(operation_path, saved)
            receipts.boundary('after_abort_intent')
        if pending:
            pending_kind = pending['state']['run']['receipts'][-1]['kind']
            if pending_kind not in (kind, result_kind):
                raise CardineError('foreign abort pending operation')
            state = receipts.replay_operation(worker, task_id, kind=pending_kind)
        if state.get('run', {}).get('ownedAbort') != command:
            updated = deepcopy(state)
            updated.setdefault('run', {})['ownedAbort'] = command
            state = receipts.write_operation(worker, task_id, updated, previous=state, kind=kind)
        if merge:
            receipts.boundary('before_abort_merge')
            result = _run_git(root, 'merge', '--abort')
            if result.returncode:
                raise CardineError(result.stderr.strip() or 'cannot abort owned merge')
            receipts.boundary('after_abort_merge')
        for path, expected, label in [(staged_path, binding['staged_digest'], 'state'),
                                      (lease_path, binding['lease_digest'], 'lease')]:
            content = _file(path)
            if content is not None:
                if receipts.digest(content) != expected:
                    raise CardineError('foreign abort output')
                receipts.boundary('before_abort_' + label + '_unlink')
                if _file(path) != content:
                    raise CardineError('foreign output changed immediately before abort unlink')
                path.unlink()
                receipts._sync_directory(path.parent)
                invalidate_facts()
                receipts.boundary('after_abort_' + label + '_unlink')
        result = dict(operation=operation_id, result='verified')
        if saved['result'] != 'verified' or state.get('run', {}).get('ownedAbortResult') != result:
            receipts.boundary('before_abort_result')
            if state.get('run', {}).get('ownedAbortResult') != result:
                updated = deepcopy(state)
                updated['run']['ownedAbortResult'] = result
                state = receipts.write_operation(worker, task_id, updated, previous=state, kind=result_kind)
            receipts._save_intent(operation_path, dict(saved, result='verified'))
            receipts.boundary('after_abort_result')
        return dict(version=1, task_id=task_id, status='aborted', next_action='inspect')
