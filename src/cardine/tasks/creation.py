"""Receipt-covered paired publication with exclusive writers and exact replay."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
from pathlib import Path

from cardine.shared.errors import CardineError
from cardine.shared.layout import names
from cardine.tasks.contract import resolve_task_contract
from cardine.tasks.identity import resolve_project_locations, resolve_task_identity, task_identity_context, _authority_matches
from cardine.tasks.state import TaskStateInvalid, state_path, validate_task_state


def _safe_path(root: Path, path: Path) -> Path:
    if not path.is_relative_to(root) or path == root:
        raise CardineError(f'creation path escapes project: {path}')
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            raise CardineError(f'creation path contains a symlink: {current}')
    return path


@contextmanager
def _creation_lock(root: Path):
    directory = _safe_path(root, root / names().project_directory)
    directory.mkdir(parents=True, exist_ok=True)
    guard = _safe_path(root, directory / 'task-creation.guard')
    with guard.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CardineError('task creation is in progress; retry task new') from error
        try:
            yield _safe_path(root, directory / 'task-creation.lock')
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def create_task(project_root: Path, task_id: str, text: str, *, recover: bool = False) -> dict:
    """Publish a receipt-covered record/state pair; identical interrupted calls replay.

    ``recover`` remains a compatibility spelling. Durable intent, rather than the
    best-effort journal, owns the exact staged pair and never removes foreign work.
    """
    from cardine.lifecycle.receipts import (authorize_project, observed_authority,
        pending_operation, replay_operation, require_authority, task_lock, write_operation)
    root = Path(project_root).resolve()
    with _creation_lock(root) as journal:
        if journal.exists():
            raise CardineError('legacy creation journal is not receipt authority; resolve it explicitly')
        locations = resolve_project_locations(root)
        for directory in locations.task_roots:
            _safe_path(root, root / directory)
        context = task_identity_context(root)
        identity = resolve_task_identity(root, task_id, 'new', check_queue_links=False, context=context)
        canonical = identity.canonical_id
        record = _safe_path(root, identity.task_path)
        state_file = _safe_path(root, state_path(root, canonical))
        with task_lock(root, canonical):
            if pending_operation(root, canonical):
                # Do not replay a different proposal under an interrupted task ID.
                from cardine.lifecycle.receipts import _intent_path, _load_intent
                import base64
                intent = _load_intent(_intent_path(root, canonical))
                name = str(record.relative_to(root))
                proposal = intent['files'].get(name, {}).get('content')
                if proposal is None or base64.b64decode(proposal) != text.encode('utf-8'):
                    raise CardineError('changed creation input; replay requires the identical record')
                replay_operation(root, canonical, kind='creation')
                return {'id': canonical, 'record': name,
                        'state': str(state_file.relative_to(root)), 'recovered': True}
            states = {path.stem: None for path in state_file.parent.glob('*.json')}
            if (record.exists() or _authority_matches(context.authorities, canonical)
                    or _authority_matches(states, canonical)
                    or any(item.casefold() == canonical.casefold() for item in states)):
                raise CardineError(f'task ID already exists: {canonical}')
            contract = resolve_task_contract(root, canonical, text=text, identity=identity)
            try:
                validate_dependencies(root, canonical, contract)
                state = {'version': 1, 'task_id': canonical, 'workflow': 'single',
                         'status': 'queued', 'transitions': [], 'contract': contract}
                validate_task_state(state, canonical, 'single')
            except (ValueError, TaskStateInvalid) as error:
                raise CardineError(str(error)) from error
            authority = root / names().project_directory / 'receipt-authority.json'
            if not authority.exists():
                # Only a new empty project may pin its policy on creation. Existing
                # portable/legacy states require explicit developer acceptance.
                if states:
                    raise CardineError('developer reauthorization required for existing task states')
                authorize_project(root, accepted=observed_authority(root), new=True)
            require_authority(root)
            write_operation(root, canonical, state, kind='creation',
                            files={str(record.relative_to(root)): text.encode('utf-8')})
            return {'id': canonical, 'record': str(record.relative_to(root)),
                    'state': str(state_file.relative_to(root)), 'recovered': False}


def validate_dependencies(root, task_id, contract):
    """Creation and explicit updates reject unknown, unregistered dependencies."""
    from cardine.tasks.state import read_task_state
    for dependency in contract["dependencies"]:
        if dependency == task_id:
            raise CardineError(f"task cannot depend on itself: {task_id}")
        try:
            identity = resolve_task_identity(root, dependency, "existing", allow_archived_queue_links=True)
            if identity.canonical_id != dependency:
                raise CardineError(f"use canonical dependency ID {identity.canonical_id}")
            read_task_state(root, dependency, 'single',
                            stop_factory=lambda code, detail, **kwargs: CardineError(detail))
        except CardineError as error:
            raise CardineError(f"unknown or invalid dependency {dependency}: {error}") from error
