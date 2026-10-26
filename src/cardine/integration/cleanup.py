"""Verified delivery and receipt-bound cleanup within the same-user trust boundary.

Remote facts are read from origin, never inferred from tracking refs. Destructive
steps retain exact input identities across retries and never force removal.
"""
from pathlib import Path
import subprocess
import shlex
import uuid

from cardine.integration.candidate import operation_path
from cardine.integration.ci import remote_tip, remote_transport as _origin, _git_environment, _refused, PUSH_SECONDS
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.git import (_run_git, git_output, _git_worktrees, scoped_command,
                                canonical_git_common_dir, invalidate_facts)
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.storage import (_lifecycle_paths, _merge_head_path, _branch_commit,
                                     _verified_lifecycle_project, _effective_worktree_root)
from cardine.worktree.paths import _task_worktree_path_for_identity
from cardine.lifecycle.model import RunLocations


def _fail(locations, detail, code='CLEANUP_BLOCKED'):
    resume = shlex.join(['cardine', 'worktree', 'cleanup', locations.task_id, '--project',
                         str(locations.primary), '--worktree-root', str(locations.root), '--format', 'json'])
    if code == 'PUSH_PENDING':
        resume = 'git push origin main'
    raise stop_error(code, detail, task_id=locations.task_id, project=locations.primary, resume=resume)


def _ancestor(root, old, new):
    return _run_git(root, 'merge-base', '--is-ancestor', old, new).returncode == 0


def _push(locations, sha):
    root = locations.primary
    try:
        done = _run_git(root, 'push', 'origin', f'{sha}:refs/heads/main',
                        timeout=PUSH_SECONDS, env=_git_environment())
    except subprocess.TimeoutExpired:
        done = None
    # Even an accepted push with a lost response is observed before retry.
    tip = remote_tip(root, 'refs/heads/main', locations)
    if tip == sha:
        return
    advanced = tip is not None and not _ancestor(root, tip, sha)
    _fail(locations, 'main push not observed' + (': ' + done.stderr.strip() if done else ': timed out'),
          'PUSH_REJECTED' if advanced or (done and _refused(done.stderr)) else 'GIT_OPERATION_FAILED')


def _landed(locations, intent):
    root, binding = locations.primary, intent['binding']
    if (binding['task'] != locations.task_id or binding['project'] != str(root)
            or binding['worker'] != str(locations.worktree)
            or binding['common'] != str(locations.common_dir)
            or binding['authority'] != receipts.require_authority(root)
            or binding['origin'] != _origin(root)
            or git_output(root, 'branch', '--show-current') != 'main'
            or git_output(root, 'status', '--porcelain')
            or not _ancestor(root, binding['main'], 'HEAD')
            or not _ancestor(root, binding['taskTip'], binding['main'])):
        _fail(locations, 'foreign cleanup owner or changed landing inputs')
    final = operation_path(locations, 'finalize')
    if binding['finalDigest'] is not None and (not final.exists() or receipts.digest(final.read_bytes()) != binding['finalDigest']):
        _fail(locations, 'landing receipt changed')
    _inactive(locations)


def _inactive(locations):
    root = locations.primary
    identity = resolve_task_identity(root, locations.task_id, 'existing')
    _, lease, staged = _lifecycle_paths(root, identity)
    if lease.exists() or staged.exists() or _merge_head_path(root).exists():
        from cardine.stops.causes import lease_stop_code
        code = ('LEASE_INTERRUPTED' if lease.exists() and not staged.exists()
                and lease_stop_code(root, identity, lease) == 'LEASE_INTERRUPTED' else 'CLEANUP_BLOCKED')
        raise stop_error(code, 'cleanup is blocked while an integration lease or staged merge is active',
                         task_id=locations.task_id, project=root)


def _remote(locations, intent):
    _landed(locations, intent)
    binding = intent['binding']
    if binding['origin'] is None:
        return
    tip = remote_tip(locations.primary, 'refs/heads/main', locations)
    # A later pushed main is safe only when its object is locally known and
    # proves containment. An unknown advance is retained, never guessed safe.
    if tip is None or not _ancestor(locations.primary, binding['main'], tip):
        behind = tip is not None and _ancestor(locations.primary, tip, binding['main'])
        _fail(locations, 'local main is not proven pushed to origin/main: remote does not contain the exact landed tip',
              'PUSH_PENDING' if behind else 'CLEANUP_BLOCKED')


def _file_identity(path):
    if path.is_symlink():
        raise CardineError('foreign cleanup symlink')
    if not path.exists():
        return None
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_ctime_ns]


def _local(locations, intent):
    _remote(locations, intent)
    root, worker, binding = locations.primary, locations.worktree, intent['binding']
    branch = _branch_commit(root, binding['branch'])
    if branch is not None:
        if branch != binding['taskTip'] or intent.get('effects', {}).get('cleanup_branch') == 'done':
            _fail(locations, 'reused or changed task branch preserved')
        log = locations.common_dir / 'logs/refs/heads' / binding['branch']
        if _file_identity(log) != binding['branchLog'] or (log.exists() and receipts.digest(log.read_bytes()) != binding['branchLogDigest']):
            _fail(locations, 'reused task branch reflog preserved')
    records = [r for r in _git_worktrees(root) if Path(r['worktree']).resolve() == worker]
    if records:
        record = records[0]
        if (record.get('branch') != 'refs/heads/' + binding['branch'] or record.get('HEAD') != binding['taskTip']
                or (worker.exists() and _file_identity(worker / '.git') != binding['registration'])
                or ((worker / '.git').exists() and receipts.digest((worker / '.git').read_bytes()) != binding['registrationDigest'])
                or (worker.exists() and git_output(worker, 'status', '--porcelain'))):
            _fail(locations, 'foreign or dirty task worktree preserved')
    elif worker.exists():
        if intent.get('placeholder') is not None and _file_identity(worker) != intent['placeholder']:
            _fail(locations, 'reused placeholder path preserved')
        if worker.is_symlink() or not worker.is_dir() or any(worker.iterdir()):
            _fail(locations, 'reused worktree path preserved')
    state = Path(binding['lifecycle'])
    receipts.safe_path(state.parent, state.name)
    if state.exists() and receipts.digest(state.read_bytes()) != binding['lifecycleDigest']:
        _fail(locations, 'foreign lifecycle registration preserved')


def _command(locations, *args):
    done = _run_git(locations.primary, *args)
    if done.returncode:
        if args[:2] == ('branch', '-d'):
            from cardine.stops.causes import cleanup_branch_stop_code
            code = cleanup_branch_stop_code(locations.primary, args[2], _branch_commit(locations.primary, args[2]), locations.common_dir)
            _fail(locations, done.stderr.strip() or 'branch deletion refused', code)
        detail = done.stderr.strip() or 'cleanup Git effect refused'
        if args[:2] == ('worktree', 'remove'):
            partial = 'registered-directory-present' if locations.worktree.exists() else 'registered-directory-missing'
            detail = partial + ": worktree removal failed; cleanup needs write access to the primary checkout's .git directory; " + detail
        _fail(locations, detail)


def _owned_remote(locations, state):
    ci = state.get('run', {}).get('ci')
    if not ci:
        return None
    receipts.verify_receipts(locations.worktree, state)
    from cardine.integration.ci import ci_binding, ci_policy
    if (ci['binding'] != ci_binding(locations, state, ci_policy(state['contract']))
            or ci['binding']['origin'] != _origin(locations.primary)):
        _fail(locations, 'changed CI push ownership')
    if not ci['push']['owned']:
        return None  # Observing a pre-existing matching ref never grants deletion.
    return dict(ref=ci['push']['ref'], sha=ci['push']['sha'])


def _new_intent(locations, *, delivery):
    root, worker = locations.primary, locations.worktree
    identity = resolve_task_identity(root, locations.task_id, 'existing')
    lifecycle, _, _ = _lifecycle_paths(root, identity)
    if git_output(root, 'status', '--porcelain'):
        _fail(locations, 'primary checkout must be clean')
    _inactive(locations)
    from cardine.worktree.checkout import inspect_task_worktree
    inspected, ready = inspect_task_worktree(locations.task_id, locations.root, root,
                                             require_effective_worktree=False)
    recoverable = {'missing-worktree', 'unregistered-worktree'}
    if not ready and (delivery or set(inspected['errors']) - recoverable):
        _fail(locations, 'cleanup preflight failed: ' + ', '.join(inspected['errors']))
    if not ready and worker.exists() and (worker.is_symlink() or not worker.is_dir() or any(worker.iterdir())):
        _fail(locations, 'reused worktree path preserved')
    tip = _branch_commit(root, identity.branch_name)
    if tip is None:
        from cardine.tasks.state import read_task_state, state_path
        relative = state_path(root, locations.task_id).relative_to(root).as_posix()
        try:
            tracked = git_output(root, 'show', 'main:' + relative)
            state = read_task_state(root, locations.task_id, 'single', text=tracked, stop_factory=stop_error, require_contract=True)
            if state['status'] != 'done':
                raise CardineError('nonterminal tracked task state')
        except CardineError as error:
            _fail(locations, 'branch already deleted; tracked task state on main must be done: ' + str(error))
        tip = git_output(root, 'rev-parse', 'main')
    if not _ancestor(root, tip, 'main'):
        _fail(locations, 'task commit is not integrated into main')
    remote = None
    if delivery:
        finalized = receipts._load_intent(operation_path(locations, 'finalize'))['result']
        if not finalized:
            _fail(locations, 'landing has not completed')
        main = finalized['merge_commit']
        from cardine.lifecycle.control import operation_state
        state, pending = operation_state(worker, locations.task_id)
        if pending:
            _fail(locations, 'pending task operation before delivery')
        remote = _owned_remote(locations, state)
    else:
        main = git_output(root, 'rev-parse', 'main')
    log = locations.common_dir / 'logs/refs/heads' / identity.branch_name
    recovered = ('registered-directory-missing' if 'missing-worktree' in inspected['errors'] else
                 'unregistered-worktree' if 'unregistered-worktree' in inspected['errors'] else None)
    if _branch_commit(root, identity.branch_name) is None:
        recovered = 'branch-already-deleted'
    return dict(version=1, operation_id=uuid.uuid4().hex, kind='cleanup',
                predecessor=receipts.digest(operation_path(locations, 'finalize').read_bytes()) if delivery else
                            receipts.digest(lifecycle.read_bytes()),
                recovered_from=recovered, binding=dict(task=locations.task_id, project=str(root), worker=str(worker),
        common=str(locations.common_dir), authority=receipts.require_authority(root),
        origin=_origin(root), branch=identity.branch_name, taskTip=tip, main=main,
        registration=_file_identity(worker / '.git'),
        registrationDigest=receipts.digest((worker / '.git').read_bytes()) if (worker / '.git').exists() else None, branchLog=_file_identity(log),
        branchLogDigest=receipts.digest(log.read_bytes()) if log.exists() else None,
        finalDigest=receipts.digest(operation_path(locations, 'finalize').read_bytes()) if delivery else None,
        lifecycle=str(lifecycle), lifecycleDigest=receipts.digest(lifecycle.read_bytes()), remote=remote), effects={})


def _delete_remote(locations, intent):
    remote = intent['binding']['remote']
    if remote is None:
        return
    root = locations.primary
    def verify():
        _remote(locations, intent)
        tip = remote_tip(root, remote['ref'], locations)
        if tip is not None and (tip != remote['sha'] or not _ancestor(root, tip, intent['binding']['main'])):
            _fail(locations, 'remote task branch advanced or is unrelated; preserved', 'PUSH_REJECTED')
    def complete():
        return remote_tip(root, remote['ref'], locations) is None
    def apply():
        try:
            result = _run_git(root, 'push', f'--force-with-lease={remote["ref"]}:{remote["sha"]}',
                'origin', ':' + remote['ref'], timeout=PUSH_SECONDS, env=_git_environment())
        except subprocess.TimeoutExpired:
            result = None
        if not complete():
            _fail(locations, 'remote compare-delete refused; branch preserved',
                  'PUSH_REJECTED' if result is not None else 'GIT_OPERATION_FAILED')
    receipts.external_effect(operation_path(locations, 'cleanup'), intent, 'cleanup_remote', verify, apply, complete)


@scoped_command
def finish_delivery(locations, *, delivery=True):
    """Push, compare-delete and cleanup; replay the same owned effects after kills."""
    root, worker, task_id = locations.primary, locations.worktree, locations.task_id
    path = operation_path(locations, 'cleanup')
    if delivery and not path.exists():
        from cardine.integration.finalize import finalize_candidate
        finalize_candidate(task_id, root)
    _inactive(locations)  # Classify an idle owned lease before taking our own writer guard.
    with receipts.task_lock(root, task_id):
        intent = receipts._load_intent(path) if path.exists() else None
        if intent is None:
            intent = _new_intent(locations, delivery=delivery)
            _landed(locations, intent)
            receipts._save_intent(path, intent)
        _landed(locations, intent)
        if intent.get('recovered_from') is None and not worker.exists() and any(
                Path(r['worktree']).resolve() == worker for r in _git_worktrees(root)):
            intent['recovered_from'] = 'registered-directory-missing'
            receipts._save_intent(path, intent)
        already = intent.get('effects', {}).get('cleanup_lifecycle') == 'done'
        if delivery and intent['binding']['origin'] is None:
            _fail(locations, 'main delivery requires origin', 'PUSH_REJECTED')
        if delivery:
            receipts.external_effect(path, intent, 'cleanup_push', lambda: _landed(locations, intent),
                lambda: _push(locations, intent['binding']['main']),
                lambda: _pushed(locations, intent))
        _remote(locations, intent)
        _delete_remote(locations, intent)
        def registered():
            return any(Path(r['worktree']).resolve() == worker for r in _git_worktrees(root))
        def effect(name, apply, complete):
            receipts.external_effect(path, intent, name, lambda: _local(locations, intent), apply, complete)
        effect('cleanup_worktree', lambda: _command(locations, 'worktree', 'remove', str(worker)), lambda: not registered())
        effect('cleanup_placeholder', lambda: worker.mkdir(parents=True, exist_ok=True), lambda: worker.is_dir())
        if 'placeholder' not in intent:
            intent['placeholder'] = _file_identity(worker)
            receipts._save_intent(path, intent)
        branch = intent['binding']['branch']
        effect('cleanup_branch', lambda: _command(locations, 'branch', '-d', branch),
               lambda: _branch_commit(root, branch) is None)
        lifecycle = Path(intent['binding']['lifecycle'])
        def unlink():
            lifecycle.unlink()
            receipts._sync_directory(lifecycle.parent)
            invalidate_facts()
        effect('cleanup_lifecycle', unlink, lambda: not lifecycle.exists())
        result = dict(version=1, task_id=task_id, status='cleaned', merge_commit=intent['binding']['main'])
        if already:
            result['already_cleaned'] = True
        if intent.get('recovered_from'):
            result['recovered_from'] = intent['recovered_from']
        return result


def _pushed(locations, intent):
    tip = remote_tip(locations.primary, 'refs/heads/main', locations)
    return tip is not None and _ancestor(locations.primary, intent['binding']['main'], tip)


def cleanup_worktree(task_id, worktree_root, supplied_project):
    root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != root:
        raise CardineError('worktree cleanup must run from the canonical primary checkout')
    identity = resolve_task_identity(root, task_id, 'existing')
    base = _effective_worktree_root(worktree_root)
    worker = _task_worktree_path_for_identity(root, base, identity)
    locations = RunLocations(identity.canonical_id, root, canonical_git_common_dir(root), base, worker)
    return finish_delivery(locations, delivery=False)
