"""Durable CLI operation receipts, within the declared same-user host boundary.

These hashes detect uncovered edits; they are not signatures or authorship proof.
Host permissions are unavailable here until the host adapters install them. The
intent is a transaction recovery record, never the best-effort event journal.
Progress lives only in the task state's ``run`` object.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from cardine.shared.errors import CardineError
from cardine.shared.layout import names


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def digest(content):
    return hashlib.sha256(content).hexdigest()


def state_digest(state):
    """Exclude the enclosing run ledger to avoid a self-referential digest."""
    return digest(encoded({key: value for key, value in state.items() if key != 'run'}))


def safe_path(root, relative):
    root = Path(root).resolve()
    path = Path(relative)
    if (path.is_absolute() or not path.parts or '..' in path.parts
            or '\\' in relative or str(path) != relative):
        raise CardineError(f'unsafe receipt path: {relative}')
    target = root
    for part in path.parts:
        target /= part
        if target.is_symlink():
            raise CardineError(f'receipt path contains a symlink: {target}')
    return target


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable(path, content):
    """Replace bytes and fsync both data and directory, without following links."""
    from cardine.tasks.state_core import write_state_bytes
    write_state_bytes(path, content)


def guard_path(root, task_id):
    """Locate the task's writer guard without creating it."""
    root = Path(root).resolve()
    from cardine.tasks.state_core import state_path
    state_path(root, task_id)  # Validate the ID before constructing lock paths.
    common = _git(root, 'rev-parse', '--git-common-dir')
    if common:
        common = (root / common).resolve()
        return safe_path(common, f'cardine-operations/{task_id}.guard')
    return safe_path(root, f'{names().tasks_path}/.{task_id}.guard')


@contextmanager
def task_lock(root, task_id):
    path = guard_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CardineError(f'live foreign operation for {task_id}; writer in progress') from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def operation_live(root, task_id):
    """Read-only probe: True while another process holds this task's writer guard."""
    path = guard_path(root, task_id)
    try:
        with path.open('rb') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except FileNotFoundError:
        return False
    return False


def _git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def observed_authority(root):
    """Measure the executing checkout, not an environment-selected runtime label."""
    root = Path(root).resolve()
    runtime = Path(__file__).resolve().parents[3]
    files = sorted({p for pattern in ('src/cardine/**/*.py', 'schemas/*.json',
                    'capabilities/*.json', 'migrations/**/*', 'templates/**/*', 'scripts/*.py')
                    for p in runtime.glob(pattern) if p.is_file()
                    and '__pycache__' not in p.parts and p.suffix != '.pyc'})
    runtime_digest = digest(encoded({str(p.relative_to(runtime)): digest(p.read_bytes()) for p in files}))
    common = _git(root, 'rev-parse', '--git-common-dir')
    from cardine.shared.git import primary_project_root
    primary = str(primary_project_root(root))
    common = str((root / common).resolve()) if common else None
    policy = safe_path(root, str(names().project_declaration_path))
    from cardine.worktree.storage import resolve_worktree_root
    return dict(project=primary, common=common, root=str(root),
                worktree_root=str(resolve_worktree_root().path), runtime=runtime_digest,
                policy=digest(policy.read_bytes()),
                accepted_main=_git(Path(primary), 'rev-parse', '--verify', 'refs/heads/main'))


def authorize_project(root, *, accepted, new=False):
    """Adapter for a separately authorized developer channel; never task JSON.

    The caller must explicitly accept observed main/runtime/policy identities.
    A clone or changed policy cannot copy authority from portable task state.
    This function does not install host configuration or claim role enforcement.
    """
    root = Path(root).resolve()
    observed = observed_authority(root)
    comparable = dict(accepted)
    if accepted.get('accepted_main') != observed['accepted_main']:
        # A portable receipt may pin an earlier accepted main. Developer
        # acceptance is explicit and Git must prove it belongs to this history.
        base = accepted.get('accepted_main')
        result = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor',
                                 str(base), str(observed['accepted_main'])], capture_output=True)
        if not base or result.returncode:
            raise CardineError('accepted main is not an ancestor of observed main')
        comparable['accepted_main'] = observed['accepted_main']
    if comparable != observed:
        raise CardineError('developer reauthorization must accept the observed project/runtime/policy')
    if new and observed['accepted_main']:
        # Task-branch policy cannot authorize its own first receipt when main
        # already defines policy. Initial untracked project setup remains allowed.
        policy = subprocess.run(['git', '-C', str(root), 'show',
                                 f'{observed["accepted_main"]}:{names().project_declaration_path}'],
                                capture_output=True)
        if policy.returncode == 0 and digest(policy.stdout) != observed['policy']:
            raise CardineError('developer reauthorization required: policy differs from accepted main')
    path = safe_path(root, f'{names().project_directory}/receipt-authority.json')
    if new and path.exists():
        return require_authority(root)
    _durable(path, encoded(accepted))
    return accepted


def require_authority(root):
    observed = observed_authority(root)
    primary = Path(observed['project']).resolve()
    path = safe_path(primary, f'{names().project_directory}/receipt-authority.json')
    try:
        accepted = json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise CardineError('developer reauthorization required: missing receipt authority') from error
    # A linked task checkout uses the primary's authorization only after Git
    # proves membership; its own policy/runtime still have to match.
    if root != primary:
        from cardine.shared.git import canonical_git_common_dir
        if observed['common'] != str(canonical_git_common_dir(primary)):
            raise CardineError('foreign project/common-directory authority')
        observed['root'] = str(primary)
    # Advancing main is ordinary delivery; it cannot replace the accepted base.
    if (not isinstance(accepted, dict) or set(accepted) != set(observed)
            or any(accepted.get(key) != observed[key] for key in observed if key != 'accepted_main')):
        raise CardineError('developer reauthorization required: project/runtime/policy changed')
    base, main = accepted['accepted_main'], observed['accepted_main']
    if base != main:
        if base is None and main:
            # Explicit acceptance of an unborn project pins policy bytes. Its
            # first main history must retain that policy; no task JSON grants it.
            policy = subprocess.run(['git', '-C', str(primary), 'show',
                                     f'{main}:{names().project_declaration_path}'], capture_output=True)
            if policy.returncode or digest(policy.stdout) != accepted['policy']:
                raise CardineError('developer reauthorization required: initial main policy changed')
        else:
            result = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor',
                                     str(base), str(main)], capture_output=True)
            if not base or not main or result.returncode:
                raise CardineError('developer reauthorization required: accepted main history changed')
    return accepted


def _receipt_hash(receipt):
    return digest(encoded({k: v for k, v in receipt.items() if k != 'digest'}))


def verify_receipts(root, state, *, artifacts=True, portable=False, artifact_ref=None, artifact_names=None):
    """Verify chaining and current coverage against independently accepted policy.

    Portable verification still requires explicit local authorization. It relaxes
    original root identity only, never runtime/policy or artifact coverage.
    """
    root = Path(root).resolve()
    from cardine.tasks.state_core import validate_task_state
    validate_task_state(state, state['task_id'], 'single')
    accepted = require_authority(root)
    receipts = state.get('run', {}).get('receipts', [])
    if not receipts or state.get('run', {}).get('pending') is not None:
        raise CardineError('missing completed operation receipt')
    previous = None
    ids = set()
    coverage = {}
    bridge = max((index for index, receipt in enumerate(receipts)
                  if receipt['kind'] == 'reauthorization'), default=-1)
    for index, receipt in enumerate(receipts):
        if (receipt['task_id'] != state['task_id'] or receipt['predecessor'] != previous
                or receipt['operation_id'] in ids or receipt['digest'] != _receipt_hash(receipt)):
            raise CardineError('invalid operation receipt chain')
        authority = receipt['authority']
        keys = ('runtime', 'policy', 'accepted_main') if portable or index < bridge else tuple(accepted)
        if any(authority.get(key) != accepted.get(key) for key in keys):
            raise CardineError('receipt authority differs from accepted policy; reauthorization required')
        if receipt['result'] != 'verified':
            raise CardineError('unknown operation result')
        ids.add(receipt['operation_id'])
        previous = receipt['digest']
        coverage.update(receipt['outputs'])
    latest = receipts[-1]
    if latest['contract_digest'] != digest(encoded(state.get('contract'))):
        raise CardineError('changed contract is not covered by an operation receipt')
    state_name = f'{names().tasks_path}/{state["task_id"]}.json'
    if coverage.get(state_name) != state_digest(state):
        raise CardineError('changed state is not covered by an operation receipt')
    if artifacts:
        for name, expected in coverage.items():
            if name == state_name or (artifact_names is not None and name not in artifact_names):
                continue
            path = safe_path(root, name)
            if artifact_ref is None:
                content = path.read_bytes() if path.is_file() else None
            else:
                shown = subprocess.run(['git', '-C', str(root), 'show', f'{artifact_ref}:{name}'],
                                       capture_output=True)
                content = shown.stdout if shown.returncode == 0 else None
            if content is None or digest(content) != expected:
                raise CardineError(f'changed or missing receipt artifact: {name}')
    return latest


def boundary(name):
    """No-op injection seam: tests kill processes before/after each effect."""


def _intent_path(root, task_id):
    return safe_path(root, f'{names().tasks_path}/.{task_id}.intent.json')


def pending_operation(root, task_id):
    return _intent_path(root, task_id).exists()


def _load_intent(path):
    try:
        value = json.loads(path.read_bytes())
        checksum = value.pop('digest')
        if checksum != digest(encoded(value)):
            raise ValueError('changed intent bytes')
        return value
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CardineError(f'invalid operation intent: {error}') from error


def interrupted_transition(root, task_id):
    """Read-only: the target status when an intact intent is a plain, replayable transition.

    Only the exact command `task transition <id> <status>` is recognised, by
    recomputing its operation kind. Other writers (creation, revisions, landing)
    return None because no single command that replays them can be derived. The
    digest detects uncovered edits of the file; it does not prove authorship.
    """
    try:
        intent = _load_intent(_intent_path(root, task_id))
        status = intent['state']['status']
        kind = intent['state']['run']['receipts'][-1]['kind']
        plain = dict(target=status, cancellation_authority='', reason='')  # the CLI's default options
        if intent['task_id'] == task_id and kind == 'transition:' + digest(encoded(plain)):
            return status
    except (CardineError, KeyError, IndexError, TypeError):
        pass
    return None


def _save_intent(path, value):
    _durable(path, encoded(dict(value, digest=digest(encoded(value)))))


def _finish(root, task_id, intent_path, intent):
    from cardine.tasks.state_core import state_path, validate_task_state
    if intent['task_id'] != task_id or intent['authority'] != require_authority(root):
        raise CardineError('intent identity or accepted policy changed')
    state = intent['state']
    validate_task_state(state, task_id, 'single')
    verify_receipts(root, state, artifacts=False)
    if state['run']['receipts'][-1]['source'] != _git(root, 'rev-parse', 'HEAD'):
        raise CardineError('operation source changed before replay')
    outputs = intent['files']
    state_name = str(state_path(root, task_id).relative_to(root))
    # Preflight every destination and every staged file before any recovery write.
    for name, item in outputs.items():
        path = safe_path(root, name)
        staged = safe_path(root, item['staged'])
        if staged.exists() and digest(staged.read_bytes()) != item['digest']:
            raise CardineError(f'changed staged bytes: {name}')
        current = digest(path.read_bytes()) if path.exists() else None
        allowed = [item['before'], item['digest']]
        if name == state_name:
            allowed += [digest(encoded(intent['pending_state']))]
        if current not in allowed:
            raise CardineError(f'recovery refuses changed file: {name}')
        if intent['staged'] and not staged.exists() and current != item['digest']:
            raise CardineError(f'missing staged bytes: {name}')
    if not intent['staged']:
        boundary('before_staged_pair')
        for name, item in outputs.items():
            _durable(safe_path(root, item['staged']), base64.b64decode(item['content'], validate=True))
        intent['staged'] = True
        _save_intent(intent_path, intent)
        boundary('after_staged_pair')
    # Creation publishes only absent paths; revisions replace only matched inputs.
    for name, item in outputs.items():
        if name == state_name:
            continue
        path = safe_path(root, name)
        if path.exists() and digest(path.read_bytes()) == item['digest']:
            continue
        source = safe_path(root, item['staged'])
        path.parent.mkdir(parents=True, exist_ok=True)
        if item['before'] is None:
            os.link(source, path)
            _sync_directory(path.parent)
        else:
            _durable(path, source.read_bytes())
    path = state_path(root, task_id)
    # Replacing state and recording the verified result are separate boundaries.
    final_bytes = encoded(state)
    if not path.exists() or path.read_bytes() != final_bytes:
        boundary('before_state_replace')
        current = digest(path.read_bytes()) if path.exists() else None
        allowed = [outputs[state_name]['before'], digest(encoded(intent['pending_state'])), digest(final_bytes)]
        if current not in allowed:
            raise CardineError('state changed immediately before replacement')
        _durable(path, encoded(intent['pending_state']))
        boundary('after_state_replace')
        boundary('before_result_receipt')
        if path.read_bytes() != encoded(intent['pending_state']):
            raise CardineError('state changed before result receipt')
        if state['run']['receipts'][-1]['source'] != _git(root, 'rev-parse', 'HEAD'):
            raise CardineError('operation source changed before result receipt')
        verify_receipts(root, state, artifact_names=outputs)
        _durable(path, final_bytes)
        boundary('after_result_receipt')
    verify_receipts(root, state, artifact_names=outputs)
    for item in outputs.values():
        safe_path(root, item['staged']).unlink(missing_ok=True)
    intent_path.unlink()
    _sync_directory(intent_path.parent)
    return state


def replay_operation(root, task_id, *, kind):
    """Caller holds task_lock; never guesses success from an event journal."""
    root = Path(root).resolve()
    path = _intent_path(root, task_id)
    intent = _load_intent(path)
    if intent['state']['run']['receipts'][-1]['kind'] != kind:
        raise CardineError('pending operation belongs to a different command')
    return _finish(root, task_id, path, intent)


def reauthorize_task(root, task_id):
    """Developer-channel adapter: bind verified portable history to this clone.

    Local policy must already have been explicitly accepted. No missing receipt,
    changed artifact or changed policy is imported, and no host role is claimed.
    """
    from cardine.tasks.state_core import state_path
    root = Path(root).resolve()
    with task_lock(root, task_id):
        if pending_operation(root, task_id):
            return replay_operation(root, task_id, kind='reauthorization')
        state = json.loads(state_path(root, task_id).read_bytes())
        verify_receipts(root, state, portable=True)
        if state['run']['receipts'][-1]['authority'] == require_authority(root):
            return state
        return write_operation(root, task_id, state, kind='reauthorization', previous=state)


def write_operation(root, task_id, state, *, kind, files=None, previous=None):
    """Caller holds task_lock. Persist intent, stage exact bytes, publish result."""
    from cardine.tasks.state_core import state_path
    root = Path(root).resolve()
    intent_path = _intent_path(root, task_id)
    if intent_path.exists():
        raise CardineError('pending operation must be replayed before another write')
    authority = require_authority(root)
    path = state_path(root, task_id)
    if previous is not None:
        verify_receipts(root, previous, artifacts=False, portable=kind == 'reauthorization')
        if not path.exists() or json.loads(path.read_bytes()) != previous:
            raise CardineError('operation input state changed')
    elif path.exists():
        raise CardineError('receipt-less state cannot bootstrap operation authority')
    state = deepcopy(state)
    receipts = deepcopy((previous or {}).get('run', {}).get('receipts', []))
    files = dict(files or {})
    state_name = str(state_path(root, task_id).relative_to(root))
    outputs = {name: digest(content) for name, content in files.items()}
    outputs[state_name] = state_digest(state)
    inputs = {}
    for name in [*files, state_name]:
        path = safe_path(root, name)
        inputs[name] = digest(path.read_bytes()) if path.exists() else None
    operation_id = uuid.uuid4().hex
    receipt = dict(version=1, task_id=task_id, operation_id=operation_id, kind=kind,
                   predecessor=receipts[-1]['digest'] if receipts else None,
                   contract_digest=digest(encoded(state.get('contract'))), authority=authority,
                   source=_git(root, 'rev-parse', 'HEAD'), tree=_git(root, 'rev-parse', 'HEAD^{tree}'),
                   inputs=inputs, outputs=outputs, result='verified')
    receipt['digest'] = _receipt_hash(receipt)
    state['run'] = dict(state.get('run', {}), receipts=[*receipts, receipt], pending=None)
    pending = deepcopy(state)
    pending['run'].update(receipts=receipts, pending=operation_id)
    files[state_name] = encoded(state)
    staged = {}
    for index, (name, content) in enumerate(files.items()):
        path = safe_path(root, name)
        staged_name = str(path.with_name(f'.{path.name}.{operation_id}.{index}.stage').relative_to(root))
        staged[name] = dict(content=base64.b64encode(content).decode(), digest=digest(content),
                            before=inputs[name], staged=staged_name)
    intent = dict(task_id=task_id, authority=authority, state=state, pending_state=pending,
                  files=staged, staged=False)
    boundary('before_intent')
    _save_intent(intent_path, intent)
    boundary('after_intent')
    return _finish(root, task_id, intent_path, intent)
