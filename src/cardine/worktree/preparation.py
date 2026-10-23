"""Receipt-bound preparation recovery; Git facts never manufacture task status.

The store is operation evidence, not a second lifecycle database. Its hashes
have the same same-user limit as the portable operation receipts.
"""
from contextlib import contextmanager
import fcntl
from pathlib import Path
import uuid

from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.git import _git_worktrees, _run_git, canonical_git_common_dir
from cardine.shared.layout import names
from cardine.tasks.state import read_task_state
from cardine.stops.render import stop_error
from cardine.worktree.storage import _branch_commit, _lifecycle_paths


def _path(project, identity):
    state, _, _ = _lifecycle_paths(project, identity)
    common = canonical_git_common_dir(project)
    return receipts.safe_path(common, state.with_suffix('.preparation').relative_to(common).as_posix())


def _binding(project, root, identity, path):
    return dict(task_id=identity.canonical_id, project=str(project),
                common=str(canonical_git_common_dir(project)), root=str(root),
                worktree=str(path), branch=identity.branch_name)


def verify_preparation(project, root, identity, path, lifecycle):
    """Check covered registration bytes and root identity before using them."""
    operation = receipts._load_intent(_path(project, identity))
    if (operation['binding'] != _binding(project, root, identity, path)
            or operation['authority'] != receipts.require_authority(project)
            or operation.get('result') != 'verified'
            or operation.get('output') != receipts.digest(receipts.encoded(lifecycle))
            or operation.get('output') != receipts.digest(_lifecycle_paths(project, identity)[0].read_bytes())):
        raise CardineError(f'lifecycle state mismatch: uncovered or changed worktree preparation receipt at '
                           f'{_lifecycle_paths(project, identity)[0]}; expected branch {identity.branch_name}, '
                           f'found branch {lifecycle.get("branch")}')
    return operation


@contextmanager
def preparation_lock(project, identity):
    path = _path(project, identity).with_suffix('.guard')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise CardineError('foreign preparation lock symlink')
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CardineError('live foreign preparation operation') from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def prepare_owned_pair(project, root, identity, path, base, *, resume):
    """Write intent before branch creation and resume only the exact owned pair."""
    state = read_task_state(project, identity.canonical_id, 'single',
                            stop_factory=stop_error, require_contract=True)
    authority = receipts.require_authority(project)
    operation_path = _path(project, identity)
    binding = _binding(project, root, identity, path)
    lifecycle, _, _ = _lifecycle_paths(project, identity)
    if operation_path.is_symlink():
        raise CardineError('foreign preparation receipt symlink')
    if operation_path.exists():
        operation = receipts._load_intent(operation_path)
        if operation['binding'] != binding or operation['authority'] != authority:
            raise CardineError('preparation input or owner changed')
        if operation.get('result') == 'verified':
            import json
            if not lifecycle.is_file():
                raise CardineError('missing covered lifecycle registration')
            verify_preparation(project, root, identity, path, json.loads(lifecycle.read_bytes()))
            return operation
        if operation['input'] != receipts.digest(receipts.encoded(state)):
            raise CardineError('preparation task input changed')
        if operation['base'] != base:
            raise CardineError('preparation source changed')
    else:
        if resume:
            raise CardineError('nothing to resume: missing owned preparation receipt')
        branch = _branch_commit(project, identity.branch_name)
        records = _git_worktrees(project)
        if branch is not None or path.exists() or lifecycle.exists() or any(
                Path(item['worktree']).resolve() == path for item in records):
            raise CardineError('foreign branch or worktree path collision; no preparation receipt')
        operation = dict(version=1, operation_id=uuid.uuid4().hex, kind='preparation',
                         predecessor=state['run']['receipts'][-1]['digest'],
                         contract_digest=receipts.digest(receipts.encoded(state['contract'])),
                         source=base, tree=receipts._git(project, 'rev-parse', f'{base}^{{tree}}'), binding=binding,
                         authority=authority, base=base, input=receipts.digest(receipts.encoded(state)),
                         result='pending', lifecycle=None)
        receipts.boundary('before_preparation_intent')
        receipts._save_intent(operation_path, operation)
        receipts.boundary('after_preparation_intent')
    branch = _branch_commit(project, identity.branch_name)
    registered = next((item for item in _git_worktrees(project)
                       if Path(item['worktree']).resolve() == path), None)
    if branch is not None and branch != base:
        raise CardineError('foreign branch changed during preparation')
    if registered is not None and (registered.get('branch') != f'refs/heads/{identity.branch_name}'
                                   or registered.get('HEAD') != base):
        raise CardineError('foreign worktree registration during preparation')
    if registered is None and path.exists():
        raise CardineError('foreign worktree path collision during preparation')
    if branch is None:
        receipts.boundary('before_branch_create')
        result = _run_git(project, 'branch', identity.branch_name, base)
        if result.returncode:
            raise CardineError(result.stderr.strip())
        receipts.boundary('after_branch_create')
    if registered is None:
        receipts.boundary('before_worktree_registration')
        path.parent.mkdir(parents=True, exist_ok=True)
        result = _run_git(project, 'worktree', 'add', str(path), identity.branch_name)
        if result.returncode:
            raise CardineError(result.stderr.strip())
        receipts.boundary('after_worktree_registration')
    return operation


def publish_preparation(project, identity, operation, lifecycle):
    """Persist exact lifecycle output before publishing; replay keeps timestamps."""
    path = _path(project, identity)
    state_path, _, _ = _lifecycle_paths(project, identity)
    if operation.get('result') == 'verified':
        return
    if operation['lifecycle'] is None:
        operation['lifecycle'] = lifecycle
        receipts._save_intent(path, operation)
    elif operation['lifecycle'] != lifecycle:
        raise CardineError('preparation lifecycle input changed')
    if state_path.exists() and state_path.read_bytes() != receipts.encoded(lifecycle):
        raise CardineError('foreign lifecycle registration retained')
    receipts.boundary('before_lifecycle_json')
    receipts._durable(state_path, receipts.encoded(lifecycle))
    receipts.boundary('after_lifecycle_json')
    operation.update(result='verified', output=receipts.digest(receipts.encoded(lifecycle)))
    receipts._save_intent(path, operation)


def repair_preparation(project, identity, before, after):
    """Cover a proven Git fast-forward repair; retain exact inputs for replay."""
    path = _path(project, identity)
    operation = receipts._load_intent(path)
    if operation['authority'] != receipts.require_authority(project):
        raise CardineError('preparation repair authority changed')
    if operation.get('result') == 'verified':
        if operation['output'] != receipts.digest(receipts.encoded(before)):
            raise CardineError('uncovered preparation repair input')
        operation = dict(operation, predecessor=receipts.digest(receipts.encoded(operation)),
                         operation_id=uuid.uuid4().hex, result='pending',
                         repair_before=before, lifecycle=after)
        receipts._save_intent(path, operation)
    elif operation.get('repair_before') != before or operation['lifecycle'] != after:
        raise CardineError('preparation repair input changed')
    state_path, _, _ = _lifecycle_paths(project, identity)
    if state_path.read_bytes() not in (receipts.encoded(before), receipts.encoded(after)):
        raise CardineError('foreign lifecycle repair bytes')
    receipts._durable(state_path, receipts.encoded(after))
    operation.update(result='verified', output=receipts.digest(receipts.encoded(after)))
    receipts._save_intent(path, operation)
