"""Validated paired publication with an exclusive writer and explicit recovery.

The journal is also the reader barrier. Hard links publish staged bytes without
replacing an existing path; the journal survives an interrupted rollback.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from cardine.shared.errors import CardineError
from cardine.shared.layout import names
from cardine.tasks.contract import resolve_task_contract
from cardine.tasks.identity import resolve_project_locations, resolve_task_identity, _authority_matches
from cardine.tasks.state import TaskStateInvalid, state_path, validate_task_state
from cardine.tasks.status import _dependencies


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


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _recover(root: Path, journal: Path, task_id: str):
    try:
        entry = json.loads(journal.read_text(encoding='utf-8'))
        if entry['id'] != task_id:
            raise ValueError(f"interrupted task is {entry['id']}, not {task_id}")
        identity = resolve_task_identity(root, task_id, 'new', check_queue_links=False)
        paths = [identity.task_path, state_path(root, identity.canonical_id)]
        expected = [str(path.relative_to(root)) for path in paths]
        if entry['paths'] != expected or len(entry['digests']) != 2:
            raise ValueError('journal paths do not match the task identity')
        present = []
        for path, digest in zip(paths, entry['digests']):
            _safe_path(root, path)
            if path.exists():
                if _digest(path.read_bytes()) != digest:
                    raise ValueError(f'recovery refuses changed file {path}')
                present.append(path)
        # Staged bytes can survive a killed writer; remove only exact owned files.
        staged = entry.get('staged', [])
        if len(staged) != 2:
            raise ValueError('journal must name both staged files')
        for name, destination, digest in zip(staged, paths, entry['digests']):
            path = _safe_path(root, root / name)
            if path.parent != destination.parent or not path.name.startswith('.task-new-'):
                raise ValueError(f'unsafe staged path {path}')
            if path.exists() and _digest(path.read_bytes()) != digest:
                raise ValueError(f'recovery refuses changed staged file {path}')
        for name in staged:
            (root / name).unlink(missing_ok=True)
        if len(present) == 2:
            validate_task_state(json.loads(paths[1].read_text()), identity.canonical_id, 'single')
            journal.unlink()
            return {'id': identity.canonical_id, 'record': expected[0], 'state': expected[1],
                    'recovered': True}
        for path in present:
            path.unlink()
        journal.unlink()
    except (KeyError, TypeError, ValueError) as error:
        raise CardineError(f'cannot recover task pair from {journal}: {error}') from error
    return None


def create_task(project_root: Path, task_id: str, text: str, *, recover: bool = False) -> dict:
    """Create one complete record and its frozen queued state, or publish neither.

    --recover accepts only the exact journaled bytes. A complete interrupted
    pair is retained; a partial pair is removed before retrying validation.
    """
    root = Path(project_root).resolve()
    with _creation_lock(root) as journal:
        locations = resolve_project_locations(root)
        for directory in locations.task_roots:
            _safe_path(root, root / directory)
        if journal.exists():
            if not recover:
                raise CardineError(f'interrupted task pair: {journal.read_text()}; '
                                   f'run cardine task new {task_id} --recover with the same record')
            result = _recover(root, journal, task_id)
            if result is not None:
                return result
        identity = resolve_task_identity(root, task_id, 'new', check_queue_links=False)
        canonical = identity.canonical_id
        record = _safe_path(root, identity.task_path)
        state_file = _safe_path(root, state_path(root, canonical))
        states = {path.stem: None for path in state_file.parent.glob('*.json')}
        if (record.exists() or _authority_matches(states, canonical)
                or any(item.casefold() == canonical.casefold() for item in states)):
            raise CardineError(f'task ID already exists: {canonical}')
        # Resolve once from the identity and the complete proposed record.
        contract = resolve_task_contract(root, canonical, text=text, identity=identity)
        try:
            _dependencies(text)
            state = {'version': 1, 'task_id': canonical, 'workflow': 'single',
                     'status': 'queued', 'transitions': [], 'contract': contract}
            validate_task_state(state, canonical, 'single')
        except (ValueError, TaskStateInvalid) as error:
            raise CardineError(str(error)) from error
        contents = [text.encode('utf-8'), (json.dumps(state, indent=2, sort_keys=True) + '\n').encode()]
        paths = [record, state_file]
        entry = {'id': task_id, 'paths': [str(path.relative_to(root)) for path in paths],
                 'digests': [_digest(content) for content in contents]}
        # Every temporary file is on the same filesystem as its destination.
        with ExitStack() as cleanup, tempfile.TemporaryDirectory(prefix='task-creation-', dir=journal.parent) as staging:
            staged = []
            for path, content in zip(paths, contents):
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.task-new-', delete=False) as handle:
                    staged.append(Path(handle.name))
                    cleanup.callback(Path(handle.name).unlink, missing_ok=True)
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            published = []
            try:
                entry['staged'] = [str(path.relative_to(root)) for path in staged]
                manifest = Path(staging) / 'journal.json'
                manifest.write_text(json.dumps(entry), encoding='utf-8')
                os.link(manifest, journal)
                try:
                    for source, destination in zip(staged, paths):
                        os.link(source, destination)
                        published.append(destination)
                except BaseException:
                    for destination in reversed(published):
                        destination.unlink()
                    raise
                finally:
                    if len(published) == 2 or not any(path.exists() for path in published):
                        journal.unlink()
            finally:
                for path in staged:
                    path.unlink(missing_ok=True)
        return {'id': canonical, 'record': entry['paths'][0], 'state': entry['paths'][1],
                'recovered': False}
