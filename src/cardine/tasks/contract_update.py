"""Explicit, validated revision of a frozen contract; never a lifecycle transition."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from cardine.shared.errors import CardineError
from cardine.shared.jsonio import _write_json_atomic
from cardine.tasks.contract import contract_hash, resolve_task_contract
from cardine.tasks.creation import _creation_lock, _safe_path, validate_dependencies
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import TaskStateInvalid, read_task_state, state_path, validate_task_state


def update_task_contract(project_root: Path, task_id: str) -> dict:
    """Revalidate the record and atomically publish snapshot plus revision history.

    The creation guard serializes explicit contract writers. No record, lifecycle
    status, review verdict or transition is written. Old sparse state is accepted
    here solely to support an explicit upgrade, never an implicit prose fallback.
    """
    root = Path(project_root).resolve()
    identity = resolve_task_identity(root, task_id, 'existing', allow_archived_queue_links=True)
    task_id = identity.canonical_id
    from cardine.lifecycle.receipts import task_lock
    with task_lock(root, task_id), _creation_lock(root) as journal:
        if journal.exists():
            raise CardineError('interrupted task creation; use cardine task new --recover first')
        from cardine.lifecycle.receipts import pending_operation, replay_operation
        if pending_operation(root, task_id):
            recovered = replay_operation(root, task_id, kind='contract_revision')
            return {'id': task_id, 'updated': True, 'state': str(state_path(root, task_id).relative_to(root)),
                    'revision': len(recovered.get('contract_history', []))}
        path = _safe_path(root, state_path(root, task_id))
        record = _safe_path(root, identity.task_path)
        state = read_task_state(root, task_id, 'single',
                                stop_factory=lambda code, detail, **kw: CardineError(detail))
        if 'run' in state:
            from cardine.lifecycle.receipts import verify_receipts
            # The record is the explicit proposal; the previous state must still
            # match its receipt. Output coverage is replaced by this revision.
            verify_receipts(root, state, artifacts=False)
        from copy import deepcopy
        previous_state = deepcopy(state)
        previous = state.get('contract')
        record_path = record.relative_to(root).as_posix()
        if previous and previous.get('recordPath', record_path) != record_path:
            raise CardineError('the frozen recordPath cannot be moved by contract update')
        text = record.read_text(encoding='utf-8')
        contract = resolve_task_contract(root, task_id, text=text, identity=identity)
        validate_dependencies(root, task_id, contract)
        if contract == previous:
            return {'id': task_id, 'updated': False, 'state': str(path.relative_to(root))}
        state['contract'] = contract
        state.setdefault('contract_history', []).append({
            'at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'before': contract_hash(previous), 'after': contract_hash(contract),
            'changedFields': sorted(key for key in set(previous or {}) | set(contract)
                                    if (previous or {}).get(key) != contract.get(key)),
        })
        try:
            validate_task_state(state, task_id, 'single')
        except TaskStateInvalid as error:
            raise CardineError(str(error)) from error
        # Refuse a concurrent editor rather than accepting a different record.
        if record.read_text(encoding='utf-8') != text:
            raise CardineError('task record changed during contract update; retry')
        if 'run' in state:
            from cardine.lifecycle.receipts import write_operation
            write_operation(root, task_id, state, kind='contract_revision', previous=previous_state,
                            files={record_path: text.encode('utf-8')})
        else:
            # The legacy explicit-upgrade adapter is retired by the RE1c reader
            # migration; it does not confer receipt authority on imported state.
            _write_json_atomic(path, state)
        return {'id': task_id, 'updated': True, 'state': str(path.relative_to(root)),
                'revision': len(state['contract_history'])}
