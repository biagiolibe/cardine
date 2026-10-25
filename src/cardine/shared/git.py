"""Shared git bindings extracted from the legacy CLI."""

from __future__ import annotations

from cardine.shared.layout import PRODUCT_NAMES

import contextlib
import contextvars
import subprocess
from copy import deepcopy
from functools import wraps
from collections.abc import Iterator
from pathlib import Path

from cardine.shared.errors import CardineError


# Only observations are reusable. Unknown commands are effects, including failed
# effects: invalidation happens before dispatch and is never rolled back.
_READ_COMMANDS = {"rev-parse", "show", "rev-list", "merge-base", "diff", "ls-files",
                  "status", "check-ref-format", "for-each-ref", "log", "cat-file"}
_FACTS = contextvars.ContextVar("cardine_command_facts", default=None)


def invalidate_facts():
    """End the read-only pass before a Git or filesystem effect."""
    facts = _FACTS.get()
    if facts is not None:
        facts.clear()
    shared = _SHARED_WORKTREES.get()
    if shared is not None:
        shared.clear()


@contextlib.contextmanager
def command_scope():
    """One in-memory observation scope, shared by nested compatibility adapters."""
    if _FACTS.get() is not None:
        yield
        return
    token = _FACTS.set({})
    try:
        yield
    finally:
        _FACTS.reset(token)


def scoped_command(function):
    @wraps(function)
    def call(*args, **kwargs):
        with command_scope():
            return function(*args, **kwargs)
    return call


def scoped_observation(function):
    """Reuse resolution inputs, never a verification verdict, within one pass.

    Copy results so callers cannot mutate the facts consumed by another reader.
    Unhashable arguments (explicit snapshot adapters) keep their existing path.
    """
    @wraps(function)
    def call(*args, **kwargs):
        facts = _FACTS.get()
        if facts is None:
            return function(*args, **kwargs)
        from cardine.shared.layout import names
        from cardine.shared.snapshot_adapters import locations_adapter, state_adapter
        key = (function, names(), locations_adapter.get(), state_adapter.get(),
               args, tuple(sorted(kwargs.items())))
        try:
            hash(key)
        except TypeError:
            return function(*args, **kwargs)
        if key not in facts:
            facts[key] = function(*args, **kwargs)
        return deepcopy(facts[key])
    return call


def _read_only(arguments):
    if not arguments:
        return False
    if arguments[0] == "--no-optional-locks":
        arguments = arguments[1:]
    command, *options = arguments
    return (command in _READ_COMMANDS
            or command == "worktree" and options == ["list", "--porcelain"]
            or command == "config" and options[:1] == ["--get"]
            or command == "branch" and options in (["--show-current"], ["--list"]))


def _run_git(project_root: Path | None, *arguments: str, text=True,
             timeout=None, env=None) -> subprocess.CompletedProcess:
    """The sole product Git subprocess gateway (legacy installation excluded)."""
    readonly = _read_only(arguments)
    if not readonly:
        invalidate_facts()
    facts = _FACTS.get() if readonly else None
    root = Path(project_root).resolve() if project_root is not None else None
    key = ("git", root, arguments, text, timeout,
           tuple(sorted(env.items())) if env is not None else None)
    if facts is not None and key in facts:
        return deepcopy(facts[key])
    command = ["git", *(["-C", str(root)] if root is not None else []), *arguments]
    result = subprocess.run(command, text=text, capture_output=True, check=False,
                            timeout=timeout, env=env)
    if facts is not None:
        facts[key] = result
        if result.returncode == 0 and arguments == ("worktree", "list", "--porcelain"):
            listing = result.stdout if text else result.stdout.decode()
            for record in parse_worktree_records(listing):
                if "worktree" in record:
                    alias = (key[0], Path(record["worktree"]).resolve(), *key[2:])
                    facts[alias] = result
    return deepcopy(result)


def git_output(project_root: Path, *arguments: str) -> str:
    completed = _run_git(project_root, *arguments)
    if completed.returncode != 0:
        raise CardineError(completed.stderr.strip() or f"git {' '.join(arguments)} failed")
    return completed.stdout.strip()


@scoped_observation
def canonical_git_common_dir(project_root: Path) -> Path:
    common = Path(git_output(project_root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = project_root / common
    return common.resolve()


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
    """Return the first registered worktree, which is Cardine's primary checkout."""
    candidate = path.expanduser().resolve()
    records = _git_worktrees(candidate)
    if not records or "worktree" not in records[0]:
        raise CardineError(f"cannot identify the primary checkout from {candidate}")
    return Path(records[0]["worktree"]).resolve()


def primary_project_root(project_root: Path) -> Path:
    """Use the canonical checkout when Git knows this project has worktrees.

    Lightweight fixtures and pre-Git setup still use their supplied directory.
    """
    try:
        return canonical_project_root(project_root)
    except CardineError:
        return project_root.expanduser().resolve()


TASK_BRANCH_OPEN_STATUSES = ("queued", "in_progress", "in_review")


def current_branch(project_root: Path) -> str | None:
    """Return the checked-out branch name, or None outside Git or on a detached HEAD."""
    try:
        return git_output(project_root, "symbolic-ref", "--short", "-q", "HEAD") or None
    except CardineError:
        return None
