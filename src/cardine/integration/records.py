"""Commit only exact receipt-covered closure bytes before candidate preparation."""
from cardine.lifecycle import receipts
from cardine.lifecycle.control import operation_state, source_digest
from cardine.integration.candidate import operation_path
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git, git_output, scoped_command
from cardine.shared.layout import names
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import state_path


def _dirty(root):
    return set(filter(None, (git_output(root, 'diff', 'HEAD', '--name-only', '-z') + '\0' +
        git_output(root, 'ls-files', '--others', '--exclude-standard', '-z')).split('\0')))


def _git(root, *args):
    result = _run_git(root, *args)
    if result.returncode:
        raise CardineError('closure records ' + result.stderr.strip())


@scoped_command
def commit_closure_records(locations):
    """Replay the intended commit once, never include an agent's uncovered edits."""
    root, task_id = locations.worktree, locations.task_id
    path = operation_path(locations, 'closure')
    with receipts.task_lock(root, task_id):
        state, pending = operation_state(root, task_id)
        if pending:
            raise CardineError('foreign pending operation before closure commit')
        authority = receipts.require_authority(root)
        head = git_output(root, 'rev-parse', 'HEAD')
        saved = receipts._load_intent(path) if path.exists() else None
        if saved and saved['result'] is not None and (saved['result'] != head or _dirty(root)):
            saved = None  # A later repair produces another closure operation.
        if saved is None:
            dirty = _dirty(root)
            if not dirty:
                return None
            identity = resolve_task_identity(root, task_id, 'existing')
            own_state = state_path(root, task_id).relative_to(root).as_posix()
            allowed = {own_state, names().execution_evidence_path(task_id).as_posix(),
                       identity.handoff_path.relative_to(root).as_posix(),
                       identity.review_path.relative_to(root).as_posix()}
            coverage = {}
            for receipt in state['run']['receipts']:
                coverage.update(receipt['outputs'])
            if dirty - allowed:
                raise CardineError('foreign changes before closure records commit')
            files = {}
            for name in sorted(dirty):
                content = receipts.safe_path(root, name).read_bytes()
                expected = receipts.state_digest(state) if name == own_state else receipts.digest(content)
                if coverage.get(name) != expected:
                    raise CardineError('uncovered closure output: ' + name)
                files[name] = receipts.digest(content)
            saved = dict(task_id=task_id, root=str(root), authority=authority, source=head,
                         contract=receipts.digest(receipts.encoded(state['contract'])),
                         sourceDigest=source_digest(root, task_id), files=files, result=None)
            receipts.boundary('before_closure_intent')
            receipts._save_intent(path, saved)
            receipts.boundary('after_closure_intent')
        if (saved['task_id'] != task_id or saved['root'] != str(root) or saved['authority'] != authority
                or saved['contract'] != receipts.digest(receipts.encoded(state['contract']))
                or saved['sourceDigest'] != source_digest(root, task_id)):
            raise CardineError('closure commit inputs or owner changed')
        if _dirty(root) - set(saved['files']):
            raise CardineError('foreign dirt during closure recovery')
        for name, expected in saved['files'].items():
            if receipts.digest(receipts.safe_path(root, name).read_bytes()) != expected:
                raise CardineError('closure output changed before commit')
        if head == saved['source']:
            receipts.boundary('before_closure_add')
            _git(root, 'add', '--', *saved['files'])
            receipts.boundary('after_closure_add')
            receipts.boundary('before_closure_commit')
            _git(root, 'commit', '-m', f'Record {task_id} measured closure', '--', *saved['files'])
            receipts.boundary('after_closure_commit')
            head = git_output(root, 'rev-parse', 'HEAD')
        if (git_output(root, 'rev-parse', 'HEAD^') != saved['source'] or _dirty(root)
                or set(git_output(root, 'diff', '--name-only', '-z', saved['source'], head).split('\0')) - {''}
                != set(saved['files']) or saved['result'] not in (None, head)):
            raise CardineError('closure result is not the intended commit')
        if saved['result'] == head:
            return head
        receipts.boundary('before_closure_result')
        receipts._save_intent(path, dict(saved, result=head))
        receipts.boundary('after_closure_result')
        return head
