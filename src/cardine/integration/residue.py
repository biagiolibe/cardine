"""Engine-owned landing residue: what a kill inside the ``landing_state`` write leaves.

``integrate abort`` restores the tree but preserves the untracked operation
intent and its staged pair. This module recognises exactly those bytes and
clears them as a receipt-backed effect. Any other dirt, or any residue whose
bytes, authority or source differ, stays foreign and keeps ``PRIMARY_DIRTY``.
Recognition is a same-user fact about this checkout, not proof of authorship.
"""

from __future__ import annotations

from pathlib import Path

from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.shared.git import canonical_git_common_dir, git_output, invalidate_facts
from cardine.tasks.state_core import state_path


def landing_residue(root: Path, task_id: str) -> dict[str, object] | None:
    """Read-only: the exact owned residue of an interrupted landing write, or None."""
    root = Path(root).resolve()
    if not receipts.pending_operation(root, task_id):
        return None
    intent_path = receipts._intent_path(root, task_id)
    try:
        intent = receipts._load_intent(intent_path)
        state = intent['state']
        last = state['run']['receipts'][-1]
        name = state_path(root, task_id).relative_to(root).as_posix()
        if (intent['task_id'] != task_id or intent['authority'] != receipts.require_authority(root)
                or set(intent['files']) != {name} or last['kind'] != 'landing_state'
                or state['status'] != 'done' or last['source'] != git_output(root, 'rev-parse', 'HEAD')):
            return None
        staged = {}
        for item in intent['files'].values():
            path = receipts.safe_path(root, item['staged'])
            if path.is_symlink() or (path.exists() and receipts.digest(path.read_bytes()) != item['digest']):
                return None
            staged[item['staged']] = item['digest']
    except (CardineError, KeyError, IndexError, TypeError):
        return None
    owned = {intent_path.relative_to(root).as_posix(), *staged}
    for line in git_output(root, 'status', '--porcelain', '--untracked-files=all').splitlines():
        if not line.startswith('?? ') or line[3:] not in owned:
            return None
    return {'intent': intent_path.relative_to(root).as_posix(), 'staged': staged,
            'intent_digest': receipts.digest(intent_path.read_bytes()), 'paths': owned}


def recover_landing_residue(root: Path, task_id: str) -> bool:
    """Clear the owned residue under a durable operation record; replay-safe after a kill."""
    root = Path(root).resolve()
    operation = receipts.safe_path(canonical_git_common_dir(root), f'cardine-operations/{task_id}.residue.json')
    saved = receipts._load_intent(operation) if operation.exists() else None
    if saved is not None and saved['result'] == 'verified':
        saved = None
    residue = landing_residue(root, task_id)
    head = git_output(root, 'rev-parse', 'HEAD')
    authority = receipts.require_authority(root)
    if saved is None:
        if residue is None:
            return False
        saved = dict(task_id=task_id, head=head, authority=authority, intent=residue['intent'],
                     intent_digest=residue['intent_digest'], staged=residue['staged'], result='pending')
        receipts.boundary('before_residue_intent')
        operation.parent.mkdir(parents=True, exist_ok=True)
        receipts._save_intent(operation, saved)
        receipts.boundary('after_residue_intent')
    elif saved['task_id'] != task_id or saved['head'] != head or saved['authority'] != authority:
        raise CardineError('foreign landing residue operation; it was preserved')
    for name, expected in [*saved['staged'].items(), (saved['intent'], saved['intent_digest'])]:
        path = receipts.safe_path(root, name)
        if not path.exists():
            continue
        if path.is_symlink() or receipts.digest(path.read_bytes()) != expected:
            raise CardineError(f'foreign or changed landing residue preserved: {name}')
        receipts.boundary('before_residue_unlink')
        path.unlink()
        receipts._sync_directory(path.parent)
        invalidate_facts()
        receipts.boundary('after_residue_unlink')
    receipts.boundary('before_residue_result')
    receipts._save_intent(operation, dict(saved, result='verified'))
    receipts.boundary('after_residue_result')
    return True
