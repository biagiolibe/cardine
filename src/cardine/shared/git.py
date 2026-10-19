"""Shared git bindings extracted from the legacy CLI."""

from __future__ import annotations

from cardine.shared.layout import PRODUCT_NAMES

import contextlib
import contextvars
import subprocess
from collections.abc import Iterator
from pathlib import Path

from cardine.shared.errors import MeridianError


def git_output(project_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise MeridianError(completed.stderr.strip() or f"git {' '.join(arguments)} failed")
    return completed.stdout.strip()


def canonical_git_common_dir(project_root: Path) -> Path:
    common = Path(git_output(project_root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = project_root / common
    return common.resolve()


def _run_git(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


_SHARED_WORKTREES: contextvars.ContextVar[dict[Path, list[dict[str, str]]] | None] = (
    contextvars.ContextVar(PRODUCT_NAMES.shared_worktrees_context, default=None))


def parse_worktree_records(output: str) -> list[dict[str, str]]:
    """Parse `git worktree list --porcelain` output into one mapping per worktree."""
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines() + [""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return records


@contextlib.contextmanager
def shared_worktree_records(records: list[dict[str, str]]) -> Iterator[None]:
    """Answer worktree-list reads from `records` for a read-only scope.

    Any registered worktree path is answered without running Git; other paths
    (for example a subdirectory) still run Git once and are remembered. Use
    only for scopes that change no worktree registration.
    """
    known = {Path(item["worktree"]).resolve(): records for item in records if "worktree" in item}
    token = _SHARED_WORKTREES.set(known)
    try:
        yield
    finally:
        _SHARED_WORKTREES.reset(token)


def _git_worktrees(project_root: Path) -> list[dict[str, str]]:
    shared = _SHARED_WORKTREES.get()
    if shared is None:
        return parse_worktree_records(git_output(project_root, "worktree", "list", "--porcelain"))
    key = project_root.resolve()
    if key not in shared:
        shared[key] = parse_worktree_records(
            git_output(project_root, "worktree", "list", "--porcelain"))
    return shared[key]


def canonical_project_root(path: Path) -> Path:
    """Return the first registered worktree, which is Meridian's primary checkout."""
    candidate = path.expanduser().resolve()
    records = _git_worktrees(candidate)
    if not records or "worktree" not in records[0]:
        raise MeridianError(f"cannot identify the primary checkout from {candidate}")
    return Path(records[0]["worktree"]).resolve()


def primary_project_root(project_root: Path) -> Path:
    """Use the canonical checkout when Git knows this project has worktrees.

    Lightweight fixtures and pre-Git setup still use their supplied directory.
    """
    try:
        return canonical_project_root(project_root)
    except MeridianError:
        return project_root.expanduser().resolve()


TASK_BRANCH_OPEN_STATUSES = ("QUEUED", "IN_PROGRESS", "CHANGES_REQUESTED", "READY_FOR_REVIEW")


def current_branch(project_root: Path) -> str | None:
    """Return the checked-out branch name, or None outside Git or on a detached HEAD."""
    try:
        return git_output(project_root, "symbolic-ref", "--short", "-q", "HEAD") or None
    except MeridianError:
        return None
