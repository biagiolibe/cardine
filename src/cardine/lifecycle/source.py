"""Task source identity and owned records shared by lifecycle operations."""
import hashlib
import json
import os
from pathlib import Path
from cardine.shared.git import git_output
from cardine.shared.layout import names
from cardine.tasks.identity import resolve_task_identity, resolve_project_locations
from cardine.tasks.state_core import state_path


def _execution_owned_paths(project_root: Path, task_id: str, *, context=None) -> set[str]:
    if context is not None and context.record_path is not None:
        return {context.record_path.as_posix(), context.handoff_path.as_posix(),
                state_path(project_root, task_id).relative_to(project_root).as_posix(),
                names().execution_evidence_path(task_id).as_posix(),
                (resolve_project_locations(project_root).review_root / f'{task_id}.md').as_posix()}
    identity = resolve_task_identity(project_root, task_id, "existing")
    return {path.relative_to(project_root).as_posix() for path in
            (identity.task_path, identity.handoff_path, identity.review_path, state_path(project_root, task_id))} | {names().execution_evidence_path(identity.canonical_id).as_posix()}


def commit_own_records(root, task_id, *, context=None):
    """Commit the records Cardine itself left uncommitted in the task worktree.

    A validation command may require a committed tree; a clean-clone run refuses
    a dirty one. The engine's own state, evidence and handoff must not fail it.
    Any change outside those paths is left for the commands to judge.
    """
    changed = set(git_output(root, 'diff', 'HEAD', '--name-only', '-z').split('\0'))
    changed.update(git_output(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0'))
    changed.discard('')
    owned = _execution_owned_paths(root, task_id, context=context)
    if not changed or changed - owned:
        return False
    paths = sorted(changed)
    git_output(root, 'add', '--', *paths)
    git_output(root, 'commit', '-q', '-m', f'Record {task_id} task state', '--', *paths)
    return True


def execution_source_digest(project_root: Path, task_id: str, *, operation_paths=(), context=None) -> str:
    """Bind validation to source contents and modes, including unstaged files.

    Only the task's delivery-owned paths are excluded. Queue, plan, and other
    tasks remain part of the fingerprint. No index or Git object is written.
    """
    owned = _execution_owned_paths(project_root, task_id, context=context) | set(operation_paths)
    paths = set(git_output(project_root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0"))
    entries = []
    for relative in sorted(paths - owned - {""}):
        path = project_root / relative
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            entries.append((relative, bool(path.stat().st_mode & 0o111), hashlib.sha256(path.read_bytes()).hexdigest()))
        elif path.is_dir():
            # Gitlinks carry a commit identity; dirty nested trees cannot be delivered.
            entries.append((relative, "gitlink", git_output(path, "rev-parse", "HEAD"),
                            git_output(path, "status", "--porcelain")))
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


