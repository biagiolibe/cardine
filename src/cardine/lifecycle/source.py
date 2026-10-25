"""Read-only task source identity, shared by execution and evidence consumers."""
import hashlib
import json
import os
from pathlib import Path
from cardine.shared.git import git_output
from cardine.shared.layout import names
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state_core import state_path


def _execution_owned_paths(project_root: Path, task_id: str, *, context=None) -> set[str]:
    if context is not None and context.record_path is not None:
        return {context.record_path.as_posix(), context.handoff_path.as_posix(),
                state_path(project_root, task_id).relative_to(project_root).as_posix(),
                names().execution_evidence_path(task_id).as_posix()}
    identity = resolve_task_identity(project_root, task_id, "existing")
    return {path.relative_to(project_root).as_posix() for path in
            (identity.task_path, identity.handoff_path, state_path(project_root, task_id))} | {names().execution_evidence_path(identity.canonical_id).as_posix()}


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


