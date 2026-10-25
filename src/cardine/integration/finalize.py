"""Finalize once, reconciling the exact tree and parents after a lost response."""
from pathlib import Path
import base64

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


def finalization_aborted(locations, intent=None):
    """Pure reconciliation: only a verified abort of this exact candidate counts."""
    from cardine.lifecycle.control import operation_state
    path = operation_path(locations, 'finalize')
    if intent is None:
        if not path.exists():
            return False
        intent = receipts._load_intent(path)
    if intent['result'] is not None:
        return False
    state, pending = operation_state(locations.worktree, locations.task_id)
    if pending:
        return False
    command = state.get('run', {}).get('ownedAbort')
    result = state.get('run', {}).get('ownedAbortResult')
    if not command or not result:
        return False
    aborted = command['binding']
    binding = intent['binding']
    return (intent['task_id'] == locations.task_id and binding['project'] == str(locations.primary)
            and binding['worker'] == str(locations.worktree)
            and binding['authority'] == receipts.require_authority(locations.worktree)
            and aborted['lease_digest'] == binding['lease']
            and aborted['staged_digest'] == binding['staged']
            and result == dict(operation=receipts.digest(receipts.encoded(command)), result='verified'))


@scoped_command
def finalize_candidate(task_id, project):
    locations = locations_for(task_id, project)
    root, task_id = locations.primary, locations.task_id
    identity = resolve_task_identity(root, task_id, 'existing')
    _, lease, staged = _lifecycle_paths(root, identity)
    path = operation_path(locations, 'finalize')
    with receipts.task_lock(locations.worktree, task_id):
        intent = receipts._load_intent(path) if path.exists() else None
        if intent and finalization_aborted(locations, intent):
            intent = None
        if intent is None:
            progress = verified_candidate(locations)
            if not progress or progress['phase'] != 'passed':
                raise stop_error('EVIDENCE_MISMATCH', 'no current measured candidate validation', task_id=task_id, project=root)
            from cardine.tasks.state import state_path
            name = state_path(locations.worktree, task_id).relative_to(locations.worktree).as_posix()
            original = _run_git(locations.worktree, 'show', f'HEAD:{name}', text=False)
            if original.returncode:
                raise CardineError('missing committed worker state before finalize')
            intent = dict(task_id=task_id, binding=progress['binding'],
                          attempt=progress['attemptId'], result=None,
                          workerState=dict(path=name, before=receipts.digest(original.stdout),
                              content=base64.b64encode(original.stdout).decode(),
                              measured=receipts.digest(receipts.safe_path(locations.worktree, name).read_bytes())))
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
        if intent['result'] is not None and head != intent['result']['merge_commit']:
            landed = intent['result']['merge_commit']
            output = intent['workerState']
            if (lease.exists() or staged.exists() or _merge_head_path(root).exists()
                    or git_output(root, 'status', '--porcelain')
                    or _run_git(root, 'merge-base', '--is-ancestor', landed, head).returncode
                    or git_output(root, 'show', '-s', '--format=%T', landed) != binding['tree']
                    or git_output(root, 'show', '-s', '--format=%P', landed).split() != [binding['main'], binding['source']]
                    or receipts.digest(receipts.safe_path(locations.worktree, output['path']).read_bytes()) != output['before']):
                raise CardineError('advanced main does not prove the completed owned landing')
            # A later task's landing does not invalidate this immutable result.
            # The old operation has no remaining outputs to write or remove.
            return intent['result']
        if head == binding['main']:
            if intent['result'] is not None:
                raise CardineError('landed main was moved backwards')
            progress = verified_candidate(locations)
            if not progress or progress['binding'] != binding or progress['attemptId'] != intent['attempt']:
                raise stop_error('EVIDENCE_MISMATCH', 'candidate validation changed before commit', task_id=task_id, project=root)
            receipts.boundary('before_finalize_commit')
            invalidate_facts()  # Recheck after an interruption/external-effect seam.
            current = verified_candidate(locations)
            if not current or current['binding'] != binding or current['attemptId'] != intent['attempt']:
                raise CardineError('candidate changed immediately before commit')
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
        # The measured result survives in the common operation receipt. Restore
        # exactly its CLI-owned worker state before handing off clean delivery;
        # this is not permission to discard any source or foreign metadata.
        output = intent['workerState']
        target = receipts.safe_path(locations.worktree, output['path'])
        current = receipts.digest(target.read_bytes())
        dirty = set(filter(None, (git_output(locations.worktree, 'diff', 'HEAD', '--name-only', '-z') + '\0' +
            git_output(locations.worktree, 'ls-files', '--others', '--exclude-standard', '-z')).split('\0')))
        if current not in (output['before'], output['measured']) or dirty - {output['path']}:
            raise CardineError('foreign worker output preserved during finalize')
        if current != output['before']:
            receipts.boundary('before_finalize_worker_restore')
            if receipts.digest(target.read_bytes()) != output['measured']:
                raise CardineError('foreign worker state changed before restore')
            receipts._durable(target, base64.b64decode(output['content'], validate=True))
            receipts.boundary('after_finalize_worker_restore')
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
