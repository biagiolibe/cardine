"""Finalize once, reconciling the exact tree and parents after a lost response."""
from pathlib import Path

from cardine.integration.candidate import locations_for, operation_path, verified_candidate
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git, git_output, scoped_command, invalidate_facts
from cardine.shared.jsonio import _read_json_object
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.storage import _lifecycle_paths, _merge_head_path
from cardine.stops.render import stop_error


def _bytes(path):
    receipts.safe_path(path.parent, path.name)
    return path.read_bytes() if path.exists() else None


def _check_files(intent, lease, staged):
    for path, expected in ((lease, intent['binding']['lease']), (staged, intent['binding']['staged'])):
        content = _bytes(path)
        if content is not None and receipts.digest(content) != expected:
            raise CardineError('foreign integration output preserved during finalize')


@scoped_command
def finalize_candidate(task_id, project):
    locations = locations_for(task_id, project)
    root, task_id = locations.primary, locations.task_id
    identity = resolve_task_identity(root, task_id, 'existing')
    _, lease, staged = _lifecycle_paths(root, identity)
    path = operation_path(locations, 'finalize')
    with receipts.task_lock(locations.worktree, task_id):
        intent = receipts._load_intent(path) if path.exists() else None
        if intent is None:
            progress = verified_candidate(locations)
            if not progress or progress['phase'] != 'passed':
                raise stop_error('EVIDENCE_MISMATCH', 'no current measured candidate validation', task_id=task_id, project=root)
            intent = dict(task_id=task_id, binding=progress['binding'],
                          attempt=progress['attemptId'], result=None)
            receipts.boundary('before_finalize_intent')
            receipts._save_intent(path, intent)
            receipts.boundary('after_finalize_intent')
        binding = intent['binding']
        if (intent['task_id'] != task_id or binding['project'] != str(root)
                or binding['worker'] != str(locations.worktree)
                or binding['authority'] != receipts.require_authority(locations.worktree)
                or binding['primaryAuthority'] != receipts.require_authority(root)
                or git_output(root, 'branch', '--show-current') != 'main'):
            raise CardineError('foreign finalize operation or changed authority')
        from cardine.lifecycle.control import operation_state, source_digest
        state, pending = operation_state(locations.worktree, task_id)
        if (pending or binding['contract'] != receipts.digest(receipts.encoded(state['contract']))
                or binding['source'] != git_output(locations.worktree, 'rev-parse', 'HEAD')
                or binding['sourceDigest'] != source_digest(locations.worktree, task_id)):
            raise CardineError('finalize task inputs changed')
        _check_files(intent, lease, staged)
        head = git_output(root, 'rev-parse', 'HEAD')
        if head == binding['main']:
            if intent['result'] is not None:
                raise CardineError('landed main was moved backwards')
            progress = verified_candidate(locations)
            if not progress or progress['binding'] != binding or progress['attemptId'] != intent['attempt']:
                raise stop_error('EVIDENCE_MISMATCH', 'candidate validation changed before commit', task_id=task_id, project=root)
            receipts.boundary('before_finalize_commit')
            committed = _run_git(root, 'commit', '-m', f'Integrate {task_id}')
            if committed.returncode:
                raise CardineError(committed.stderr.strip() or 'integration commit failed; intent retained')
            receipts.boundary('after_finalize_commit')
            head = git_output(root, 'rev-parse', 'HEAD')
        # A commit with these exact parents and tree is the intended effect.
        # An unrelated advance is never mistaken for a successful lost response.
        if (git_output(root, 'show', '-s', '--format=%T', head) != binding['tree']
                or git_output(root, 'show', '-s', '--format=%P', head).split() != [binding['main'], binding['source']]
                or _merge_head_path(root).exists()
                or git_output(root, 'status', '--porcelain')):
            raise CardineError('main does not match the intended landed commit')
        if intent['result'] is not None and intent['result']['merge_commit'] != head:
            raise CardineError('landed commit changed')
        result = dict(version=1, task_id=task_id, merge_commit=head,
                      candidate_tree=binding['tree'], decision=_read_json_object(staged, 'staged integration')['decision']
                      if staged.exists() else intent['result']['decision'], next_action='push-or-cleanup')
        if intent['result'] is None:
            receipts.boundary('before_finalize_result')
            intent = dict(intent, result=result)
            receipts._save_intent(path, intent)
            receipts.boundary('after_finalize_result')
        for target, label in ((staged, 'json'), (lease, 'lease')):
            _check_files(intent, lease, staged)
            if target.exists():
                receipts.boundary('before_finalize_' + label + '_unlink')
                _check_files(intent, lease, staged)
                target.unlink()
                receipts._sync_directory(target.parent)
                invalidate_facts()
                receipts.boundary('after_finalize_' + label + '_unlink')
        return intent['result']
