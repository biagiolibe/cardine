"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.git import _run_git

from cardine.shared.errors import CardineError
from cardine.shared.git import canonical_git_common_dir
from cardine.shared.git import git_output
from cardine.shared.models import RepositoryIdentity
from cardine.shared.models import ResolvedTaskIdentity
from cardine.tasks.identity import _safe_component
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.storage import _effective_worktree_root
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import os
import re
import unicodedata


def _normalized_local_repository_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not normalized:
        raise CardineError("local repository name cannot be normalized safely")
    return normalized


def repository_identity(project_root: Path, remote_url: str | None = None) -> RepositoryIdentity:
    """Derive a repository-qualified namespace without machine-specific state."""
    if remote_url is None:
        completed = _run_git(str(project_root), 'config', '--get', 'remote.origin.url', text=True)
        remote_url = completed.stdout.strip() if completed.returncode == 0 else ""
    if remote_url:
        candidate = remote_url.strip()
        if "://" not in candidate and re.match(r"^[^/@:]+@[^/:]+:.+$", candidate):
            user_host, remote_path = candidate.split(":", 1)
            host = user_host.rsplit("@", 1)[-1]
            parts = [part for part in remote_path.strip("/").split("/") if part]
        else:
            parsed = urlparse(candidate)
            host = parsed.hostname or ""
            parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2 and host:
            repository = parts[-1][:-4] if parts[-1].endswith(".git") else parts[-1]
            owner_parts = [_safe_component(part, "remote owner") for part in parts[:-1]]
            if any("--" in part for part in owner_parts):
                raise CardineError("remote owner contains an ambiguous namespace separator")
            owner = "--".join(owner_parts)
            return RepositoryIdentity(
                _safe_component(host, "remote host"),
                owner,
                _safe_component(repository, "repository name"),
            )

    common = canonical_git_common_dir(project_root)
    try:
        repository_name = git_output(project_root, "rev-parse", "--show-toplevel").split("/")[-1]
    except CardineError:
        repository_name = project_root.resolve().name
    repository = _normalized_local_repository_name(repository_name)
    digest = hashlib.sha256(os.fsencode(common)).hexdigest()[:12]
    return RepositoryIdentity("local", "repositories", f"{repository}-{digest}")


def _task_worktree_path_for_identity(
    project_root: Path,
    worktree_root: Path,
    identity: ResolvedTaskIdentity,
) -> Path:
    root = worktree_root.expanduser().resolve()
    if root == Path(root.anchor) or root == Path.home().resolve():
        raise CardineError("worktree root must be a dedicated directory, not the filesystem root or home")
    repository = repository_identity(project_root)
    result = (
        root
        / repository.remote_host
        / repository.owner
        / repository.repository
        / identity.branch_name
    )
    if root not in result.parents:
        raise CardineError("derived worktree path escapes the configured root")
    resolved_result = result.resolve()
    if root not in resolved_result.parents:
        raise CardineError("derived worktree path escapes the configured root through a symlink")
    return result


def handoff_worktree_value(worktree_root: Path, path: Path) -> str:
    """Machine-independent handoff value: the path relative to the worktree root."""
    return path.relative_to(worktree_root.expanduser().resolve()).as_posix()


def task_worktree_path(project_root: Path, worktree_root: Path | None, task_id: str) -> Path:
    """Compatibility derivation for callers that may be planning a new task."""
    return _task_worktree_path_for_identity(
        project_root,
        _effective_worktree_root(worktree_root),
        resolve_task_identity(project_root, task_id, "new"),
    )


def validate_worktree_collision(project_root: Path, path: Path, task_id: str) -> None:
    """Reject an existing path unless it is the exact expected linked worktree."""
    if not path.exists():
        return
    expected_common = canonical_git_common_dir(project_root)
    try:
        actual_common = canonical_git_common_dir(path)
        branch = git_output(path, "branch", "--show-current")
    except CardineError as error:
        raise CardineError(f"worktree path collision at {path}: {error}") from error
    try:
        expected_branch = resolve_task_identity(project_root, task_id, "existing").branch_name
    except CardineError:
        expected_branch = resolve_task_identity(project_root, task_id, "new").branch_name
    if actual_common != expected_common or branch != expected_branch:
        raise CardineError(
            f"worktree path collision at {path}: expected {expected_common} on {expected_branch}, "
            f"found {actual_common} on {branch or 'detached HEAD'}"
        )
