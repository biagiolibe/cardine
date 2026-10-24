"""Receipt-owned implementation delivery before validation or review acceptance.

The local operation record detects uncovered edits; it is not authorship proof.
No declaration in a handoff or agent-supplied verdict completes acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path

from cardine.lifecycle import receipts
from cardine.lifecycle.execution import (_execution_location, _execution_owned_paths,
                                          _execution_state, execution_source_digest)
from cardine.lifecycle.scope import enforce_scope
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git, git_output
from cardine.tasks.state import state_path


def _operation_path(root, task_id):
    common = Path(git_output(root, 'rev-parse', '--git-common-dir'))
    if not common.is_absolute():
        common = root / common
    return receipts.safe_path(common.resolve(), f'cardine-operations/{task_id}.delivery')


def _git(root, *args):
    result = _run_git(root, *args)
    if result.returncode:
        raise CardineError(f'delivery {args[0]} failed: {result.stderr.strip()}')


def verify_delivery(root, state, base):
    """Derive progress from covered state, actual source and a committed result."""
    receipts.verify_receipts(root, state)
    delivery = state.get('run', {}).get('delivery')
    if not delivery:
        return None
    if (delivery['base'] != base
            or delivery['contractDigest'] != receipts.digest(receipts.encoded(state['contract']))
            or delivery['sourceDigest'] != execution_source_digest(root, state['task_id'])):
        return None  # Genuine, stale delivery requires new work/validation.
    source = delivery['source']
    head = git_output(root, 'rev-parse', 'HEAD')
    if (_run_git(root, 'merge-base', '--is-ancestor', source, head).returncode
            or git_output(root, 'rev-parse', source + '^{tree}') != delivery['sourceTree']):
        raise CardineError('delivery source identity changed')
    name = state_path(root, state['task_id']).relative_to(root).as_posix()
    candidates = git_output(root, 'rev-list', '--reverse', f'{source}..{head}').splitlines()
    for commit in candidates:
        shown = _run_git(root, 'show', f'{commit}:{name}')
        if shown.returncode:
            continue
        recorded = json.loads(shown.stdout)
        if recorded.get('run', {}).get('delivery') != delivery:
            continue
        if (git_output(root, 'rev-parse', commit + '^') != source
                or git_output(root, 'diff', '--name-only', source, commit) != name):
            raise CardineError('delivery commit does not match the exact intended effect')
        receipts.verify_receipts(root, recorded, portable=True)
        proof = [r for r in recorded['run']['receipts'] if r['kind'] == 'implementation-delivery'
                 and r['source'] == source]
        if not proof:
            raise CardineError('delivery lacks its operation receipt')
        enforce_scope(root, state, base, owned=_execution_owned_paths(root, state['task_id']))
        return dict(task_id=state['task_id'], commit=commit, source=source,
                    status=state['status'], clean=not bool(git_output(root, 'status', '--porcelain')))
    raise CardineError('implementation delivery is not committed')


def deliver_implementation(root, task_id):
    """One writer, durable intent, exact state-only commit, replay at every effect."""
    root = Path(root).resolve()
    inspection = _execution_location(root, task_id, command=('execution', 'deliver'))
    if set(inspection['errors']) - {'dirty-worktree'} or inspection['integration_active']:
        raise CardineError('delivery worktree identity mismatch')
    base = str(inspection['base_commit'])
    with receipts.task_lock(root, task_id):
        operation = _operation_path(root, task_id)
        name = state_path(root, task_id).relative_to(root).as_posix()
        if operation.exists():
            intent = receipts._load_intent(operation)
            if (intent['task_id'] != task_id or intent['authority'] != receipts.require_authority(root)
                    or intent['root'] != str(root) or intent['base'] != base):
                raise CardineError('delivery operation owner or authority changed')
            if intent['result'] == 'verified':
                state = _execution_state(root, task_id)
                current = verify_delivery(root, state, base)
                if current is not None:
                    if current['commit'] != intent['commit']:
                        raise CardineError('delivery result commit identity changed')
                    if not current['clean']:
                        raise CardineError('delivery has foreign uncommitted changes')
                    return current
                # An ordinary new implementation can start another delivery;
                # no stale receipt is promoted to validation or acceptance.
                intent = None
        else:
            intent = None
        if intent is None:
            state = _execution_state(root, task_id)
            if state['status'] != 'in_progress':
                raise CardineError('implementation delivery requires in_progress')
            owned = _execution_owned_paths(root, task_id)
            paths = enforce_scope(root, state, base, owned=owned)
            if not paths:
                raise CardineError('delivery needs a real implementation change')
            if git_output(root, 'status', '--porcelain'):
                raise CardineError('implementation must be committed before delivery')
            existing = verify_delivery(root, state, base)
            if existing:
                return existing
            source = git_output(root, 'rev-parse', 'HEAD')
            delivery = dict(source=source, sourceTree=git_output(root, 'rev-parse', 'HEAD^{tree}'),
                            sourceDigest=execution_source_digest(root, task_id), base=base,
                            contractDigest=receipts.digest(receipts.encoded(state['contract'])))
            intent = dict(task_id=task_id, root=str(root), base=base,
                          authority=receipts.require_authority(root), delivery=delivery,
                          before=receipts.digest(state_path(root, task_id).read_bytes()), result='pending')
            operation.parent.mkdir(parents=True, exist_ok=True)
            receipts.boundary('before_delivery_intent')
            receipts._save_intent(operation, intent)
            receipts.boundary('after_delivery_intent')
        delivery = intent['delivery']
        source = delivery['source']
        operation_paths = set()
        if receipts.pending_operation(root, task_id):
            pending_path = receipts._intent_path(root, task_id)
            pending = receipts._load_intent(pending_path)
            if (pending['task_id'] != task_id or set(pending['files']) != {name}
                    or pending['state']['run']['receipts'][-1]['kind'] != 'implementation-delivery'
                    or pending['state'].get('run', {}).get('delivery') != delivery):
                raise CardineError('pending delivery belongs to another operation')
            operation_paths = {pending_path.relative_to(root).as_posix(), pending['files'][name]['staged']}
        # The source digest excludes CLI-owned state but includes all foreign dirt.
        if execution_source_digest(root, task_id, operation_paths=operation_paths) != delivery['sourceDigest']:
            raise CardineError('delivery input source changed')
        if receipts.pending_operation(root, task_id):
            state = receipts.replay_operation(root, task_id, kind='implementation-delivery')
        else:
            state = _execution_state(root, task_id)
            if state.get('run', {}).get('delivery') != delivery:
                if (git_output(root, 'rev-parse', 'HEAD') != source
                        or receipts.digest(state_path(root, task_id).read_bytes()) != intent['before']):
                    raise CardineError('delivery input state changed')
                updated = deepcopy(state)
                updated.setdefault('run', {})['delivery'] = delivery
                receipts.boundary('before_delivery_state')
                state = receipts.write_operation(root, task_id, updated, previous=state,
                                                 kind='implementation-delivery')
                receipts.boundary('after_delivery_state')
        if state.get('run', {}).get('delivery') != delivery:
            raise CardineError('delivery state belongs to another operation')
        # No foreign staged path is included by add/commit. Refuse any foreign
        # lifecycle dirt even when it is excluded from the source fingerprint.
        changed = set(git_output(root, 'diff', 'HEAD', '--name-only', '-z').split('\0')) - {''}
        changed.update(git_output(root, 'diff', '--cached', '--name-only', '-z').split('\0'))
        changed.discard('')
        untracked = set(git_output(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')) - {''}
        if (changed | untracked) - {name}:
            raise CardineError('delivery recovery has foreign changes')
        head = git_output(root, 'rev-parse', 'HEAD')
        if head == source:
            receipts.boundary('before_delivery_add')
            _git(root, 'add', '--', name)
            receipts.boundary('after_delivery_add')
            receipts.boundary('before_delivery_commit')
            _git(root, 'commit', '-m', f'Deliver {task_id} implementation', '--', name)
            receipts.boundary('after_delivery_commit')
        elif (git_output(root, 'rev-parse', 'HEAD^') != source or changed
              or git_output(root, 'diff', '--name-only', source, 'HEAD') != name):
            raise CardineError('delivery replay found a foreign commit')
        result = verify_delivery(root, state, base)
        if result is None:
            raise CardineError('delivery result changed')
        receipts.boundary('before_delivery_receipt')
        receipts._save_intent(operation, dict(intent, result='verified', commit=result['commit']))
        receipts.boundary('after_delivery_receipt')
        return result
