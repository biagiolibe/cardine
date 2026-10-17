#!/usr/bin/env python3
"""Local terminal dashboard for a Meridian project."""

from __future__ import annotations

import argparse
import contextlib
import curses
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import tomllib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.dont_write_bytecode = True
from meridian import (
    EXECUTION_EVIDENCE_PATH, INTEGRATION_LEASE_NAME, INTEGRATION_STATE_NAME, TASK_IDENTITY_PATH,
    WORKTREE_STATE_DIRECTORY, MeridianError, MeridianStop, ResolvedTaskIdentity,
    canonical_git_common_dir, detect_mode, parse_worktree_records, read_task_field,
    shared_worktree_records, stop_error, delivery_readiness,
    closure_status, lifecycle_started_at, resolve_project_locations, resolve_task_identity,
)
from task_state import read_task_state, state_path
from console_workflow import (
    ID_PATTERN, PROFILES, BranchFacts, ConsoleError, QueueRow, Profile, effective_state,
    handoff_status, has_link, heading_title, is_task_record_path, latest_review_verdict,
    link_target, parse_queue, record_matches, record_review, record_status,
)


UUID_PATTERN = (r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
ITERM_SESSION_ID_PATTERN = re.compile(r"w\d+t\d+p\d+:(" + UUID_PATTERN + r")")


@dataclass(frozen=True)
class FrameworkIdentity:
    version: str
    root: Path

    @property
    def label(self) -> str:
        version = "version unknown" if self.version == "unknown" else f"v{self.version}"
        return f"{version} | {self.root_label}"

    @property
    def root_label(self) -> str:
        try:
            relative = self.root.relative_to(Path.home().resolve())
            return "~" if relative == Path(".") else "~/" + str(relative)
        except ValueError:
            return str(self.root)


@dataclass(frozen=True)
class AgentDefaults:
    model: str = "unknown"
    effort: str = "unknown"

    @property
    def label(self) -> str:
        return f"configured default: model {self.model}; effort {self.effort}"


def _framework_identity(script_path: Path | None = None) -> FrameworkIdentity:
    """Read this running framework's identity once; identity lookup must not block the console."""
    root = (script_path or Path(__file__)).resolve().parent.parent
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        version = "unknown"
    return FrameworkIdentity(version or "unknown", root)


def _agent_defaults(home: Path | None = None) -> dict[str, AgentDefaults]:
    """Return only supported local default fields, never failing a launch on config problems."""
    home = home or Path.home()
    unknown = AgentDefaults()
    try:
        codex_data = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
        codex = AgentDefaults(
            codex_data.get("model") if isinstance(codex_data.get("model"), str) else "unknown",
            codex_data.get("model_reasoning_effort")
            if isinstance(codex_data.get("model_reasoning_effort"), str) else "unknown",
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        codex = unknown
    try:
        claude_data = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        claude = AgentDefaults(
            claude_data.get("model") if isinstance(claude_data, dict)
            and isinstance(claude_data.get("model"), str) else "unknown",
            claude_data.get("effort") if isinstance(claude_data, dict)
            and isinstance(claude_data.get("effort"), str) else "unknown",
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        claude = unknown
    return {"claude": claude, "codex": codex}


def _set_terminal_title(project: Path) -> None:
    """Best-effort terminal title that intentionally contains no project path."""
    try:
        sys.stdout.write(f"\033]0;Meridian console — {project.name}\007")
        sys.stdout.flush()
    except OSError:
        pass


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    status: str
    phase: tuple[str, ...]
    dependencies: tuple[str, ...]
    path: Path | None
    objective: tuple[str, ...]
    criteria: tuple[str, ...]
    worktree: str | None = None
    readiness: str = ""
    updated_at: int | None = None
    lifecycle: str = "todo"
    source: str = "main"
    mismatch: str | None = None
    changes_requested: bool = False
    active_writer: bool = False
    registered_worktree: bool = False
    record_problem: str | None = None
    review: str | None = None
    dependency_states: tuple[tuple[str, str], ...] = ()
    workflow: str = "lean-delivery"
    closure_stop_reason: str | None = None
    closure_resume: str | None = None
    cleanup_pending: bool = False
    started_at: str | None = None
    progress_phase: str = "unavailable"
    remaining_gates: tuple[str, ...] = ()
    legacy: bool = True
    review_verdict: str | None = None
    state_error: str | None = None
    delivery_pending: str | None = None

    @property
    def is_resume(self) -> bool:
        """Whether Proceed with would resume ordinary implementation work."""
        return (self.lifecycle == "in_progress"
                and not (self.workflow == "governed-sdd" and self.changes_requested))

    @property
    def resume_confirmations(self) -> int:
        """Explicit warnings required before Resume reaches agent selection."""
        return (1 + int(self.active_writer)) if self.is_resume else 0

    @property
    def launch_command(self) -> str | None:
        if self.state_error or self.record_problem or self.delivery_pending or self.readiness == "MISMATCH":
            return None
        if self.is_resume:
            if self.active_writer:
                return (f"Proceed with {self.task_id} (Resume: run "
                        f"meridian worktree prepare {self.task_id} --resume --format json)")
            return f"Proceed with {self.task_id}"
        if self.active_writer:
            return None
        if self.lifecycle == "todo" and self.readiness == "READY":
            return f"Proceed with {self.task_id}"
        if self.lifecycle == "ready_for_review":
            if self.workflow == "lean-delivery":
                return f"Review {self.task_id}"
            if self.workflow == "governed-sdd" and self.review == "REQUIRED":
                return f"Review {self.task_id}"
        if (self.workflow == "governed-sdd" and self.lifecycle == "in_progress"
                and self.changes_requested):
            return f"Address review {self.task_id}"
        return None

    @property
    def shows_progress(self) -> bool:
        """Whether elapsed time and lifecycle progress apply to this task."""
        return self.lifecycle in ("in_progress", "closing") or (
            self.workflow == "governed-sdd" and self.lifecycle == "ready_for_review"
            and self.worktree is not None
        )

    @property
    def markers(self) -> tuple[str, ...]:
        return (
            *(("changes requested",) if self.changes_requested else ()),
            *(("active writer",) if self.active_writer else ()),
            *(("registered worktree",) if self.registered_worktree else ()),
        )

    @property
    def next_action(self) -> str:
        if self.state_error:
            return self.state_error
        if self.is_resume and self.launch_command:
            return f"If assigned: {self.launch_command}"
        if self.closure_stop_reason:
            return f"{self.closure_stop_reason}: {self.closure_resume or 'no resume command'}"
        if self.closure_resume:
            return self.closure_resume
        if self.readiness == "CLOSING":
            return "Closure state unavailable: rerun meridian worktree closure-status"
        if self.record_problem and self.readiness != "MISMATCH":
            return f"Resolve the task record: {self.record_problem}"
        if self.readiness == "READY":
            return f"If assigned: {self.launch_command}"
        if self.readiness == "MISMATCH":
            return f"Resolve the state disagreement: {self.mismatch}"
        if self.readiness == "READY FOR REVIEW":
            if self.launch_command:
                return f"If assigned: {self.launch_command}"
            if self.active_writer:
                return "Review unavailable: active writer"
            if self.review == "NOT REQUIRED":
                return "Review unavailable: Review: NOT REQUIRED"
            if self.review is None:
                return "Review unavailable: review policy not declared"
            return "Awaiting review of the task branch"
        if self.readiness == "DONE ON BRANCH":
            return "Awaiting integration of the task branch"
        if self.readiness == "IN PROGRESS":
            return "Continue the assigned task in its worktree"
        if self.readiness.startswith("BLOCKED"):
            return "Wait for the listed dependencies to complete"
        return "Resolve the missing dependency record"


@dataclass(frozen=True)
class LaunchRequest:
    """A confirmed, safe-to-quote invocation for an iTerm2 split pane."""

    agent: str
    directive: str
    directory: Path
    task_id: str
    session_uuid: str

    @property
    def shell_command(self) -> str:
        return "cd " + shlex.quote(str(self.directory)) + " && exec " + shlex.join(
            (self.agent, self.directive)
        )


def _launch_request(task: Task, project: Path, agent: str) -> tuple[LaunchRequest | None, str | None]:
    """Revalidate a selected task and console session before offering a launch."""
    if agent not in ("claude", "codex"):
        return None, "Choose Claude Code or Codex"
    if not ID_PATTERN.fullmatch(task.task_id):
        return None, "Refusing launch: task ID no longer matches the workflow rules"
    directive = task.launch_command
    if not directive:
        return None, "This task is not eligible to launch; use [copy] if a directive is shown"
    directory, error = _primary_checkout(project)
    if error:
        return None, error
    session_id = os.environ.get("ITERM_SESSION_ID", "")
    match = ITERM_SESSION_ID_PATTERN.fullmatch(session_id)
    if not match:
        return None, "iTerm2 console session is missing or invalid; [copy] remains available"
    return LaunchRequest(agent, directive, directory, task.task_id, match.group(1)), None


def _apple_script(command: str, session_uuid: str) -> str:
    """Return the sole split-pane payload, with AppleScript quoting."""
    quoted = command.replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join((
        'tell application "iTerm2"',
        "activate",
        "set targetSession to missing value",
        "repeat with aWindow in windows",
        "    repeat with aTab in tabs of aWindow",
        "        repeat with aSession in sessions of aTab",
        f'            if unique id of aSession is "{session_uuid}" then set targetSession to aSession',
        "        end repeat",
        "    end repeat",
        "end repeat",
        "if targetSession is missing value then error \"MERIDIAN_SESSION_NOT_FOUND\"",
        "tell targetSession",
        "set newSession to split horizontally with default profile",
        f'tell newSession to write text "{quoted}"',
        "end tell",
        "end tell",
    ))


def _start_launch(request: LaunchRequest) -> tuple[bool, str]:
    """Open an iTerm2 split pane after UI confirmation."""
    if sys.platform != "darwin":
        return False, "Agent launch requires macOS and iTerm2; [copy] remains available"
    if shutil.which(request.agent) is None:
        return False, f"{request.agent} is not available on PATH; [copy] remains available"
    if shutil.which("osascript") is None:
        return False, "macOS osascript is unavailable; [copy] remains available"
    if not ID_PATTERN.fullmatch(request.task_id):
        return False, "Refusing launch: task ID no longer matches the workflow rules; [copy] remains available"
    if not re.fullmatch(UUID_PATTERN, request.session_uuid):
        return False, "iTerm2 console session is missing or invalid; [copy] remains available"
    try:
        result = subprocess.run(
            ("osascript", "-e", _apple_script(request.shell_command, request.session_uuid)),
            capture_output=True, text=True, check=False, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False, "iTerm2 launch timed out; [copy] remains available"
    except OSError as error:
        return False, f"iTerm2 launch failed: {error}; [copy] remains available"
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        if "MERIDIAN_SESSION_NOT_FOUND" in detail:
            return False, "iTerm2 console session was not found; [copy] remains available"
        return False, (f"iTerm2 is unavailable or rejected launch: {detail}; [copy] remains available"
                       if detail else "iTerm2 launch failed; [copy] remains available")
    return True, f"Started {request.agent} in a new iTerm2 split pane"


def _launch_selected(state: "ConsoleState", task: Task, agent: str,
                     dirty_confirmed: bool = False) -> tuple[bool, str]:
    """Reread only the selected task, require an unchanged directive, and launch it.

    Blocking: run it off the UI thread through `ConsoleState.start_launch`.
    """
    expected_directive = task.launch_command
    expected_resume = task.is_resume
    try:
        current = load_task(state.project, task.task_id, IdentityCache())
    except ConsoleError as error:
        return False, f"Launch revalidation failed: {error}"
    if current is None or current.launch_command != expected_directive or current.is_resume != expected_resume:
        return False, "Task state changed; review the refreshed task before launching"
    if current.is_resume and current.active_writer and not dirty_confirmed:
        return False, "Task worktree became dirty; confirm Resume again before launching"
    request, error = _launch_request(current, state.project, agent)
    if error:
        return False, error
    assert request is not None
    return _start_launch(request)


@dataclass(frozen=True)
class Snapshot:
    project: Path
    queue: Path
    branch: str
    git_summary: str
    git_changes: int
    tasks: tuple[Task, ...]
    done_count: int


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConsoleError(f"Cannot read {path}: {error}") from error


class RecordResolver:
    """Find task records for queue rows with absent or missing file targets.

    The task roots are walked at most once per snapshot, and only when a row
    needs the search, so resolution adds no per-task subprocess work.
    """

    def __init__(self, project: Path, locations) -> None:
        self.project = project
        self.roots = tuple(root.as_posix() for root in locations.task_roots)
        self.excluded = (locations.handoff_root.as_posix(), locations.review_root.as_posix())
        self._paths: list[str] | None = None

    def _scan(self) -> list[str]:
        if self._paths is None:
            found: set[str] = set()
            for root in self.roots:
                for directory, names, files in os.walk(self.project / root):
                    relative = Path(directory).relative_to(self.project).as_posix()
                    names[:] = [
                        name for name in names
                        if is_task_record_path(f"{relative}/{name}/x", self.excluded)
                    ]
                    found.update(
                        f"{relative}/{name}" for name in files
                        if name.endswith(".md") and not os.path.islink(os.path.join(directory, name))
                    )
            self._paths = sorted(found)
        return self._paths

    def find(self, task_id: str) -> tuple[Path | None, str | None]:
        """Return the record path, or the per-task problem that prevents one."""
        matches = record_matches(task_id, self._scan(), self.excluded)
        if not matches:
            return None, "task record not found"
        if len(matches) > 1:
            return None, "ambiguous task record: " + ", ".join(matches)
        path = (self.project / matches[0]).resolve()
        if not path.is_relative_to(self.project) or not path.is_file():
            return None, f"task record is unavailable within the project: {matches[0]}"
        return path, None

    def find_by_name(self, basename: str) -> tuple[Path | None, str | None]:
        """Resolve an exact linked filename using the cached task-root scan."""
        matches = [relative for relative in self._scan()
                   if Path(relative).name == basename
                   and is_task_record_path(relative, self.excluded)]
        if not matches:
            return None, "task record not found"
        if len(matches) > 1:
            return None, "ambiguous task record: " + ", ".join(matches)
        path = (self.project / matches[0]).resolve()
        if not path.is_relative_to(self.project) or not path.is_file():
            return None, f"task record is unavailable within the project: {matches[0]}"
        return path, None

    def find_on_ref(self, ref: str, task_id: str) -> str | None:
        """Apply the same rules to a task branch tree; None unless exactly one match."""
        listing = _git_optional(self.project, "ls-tree", "-r", "--name-only", ref, "--", *self.roots)
        matches = record_matches(task_id, (listing or "").splitlines(), self.excluded)
        return matches[0] if len(matches) == 1 else None


def _task_path(project: Path, queue: Path, row: QueueRow,
               resolver: RecordResolver) -> tuple[Path | None, str | None]:
    """Resolve a queue link, searching task roots when its record has moved."""
    if not has_link(row.link):
        return resolver.find(row.task_id)
    target = link_target(queue.relative_to(project).as_posix(), row.link)
    if target is None:
        raise ConsoleError(f"Task {row.task_id} has no unambiguous file link")
    path = (project / target).resolve()
    if path.is_relative_to(project) and not path.exists():
        relative = path.relative_to(project).as_posix()
        in_task_root = any(relative.startswith(root.rstrip("/") + "/")
                           for root in resolver.roots)
        if in_task_root and is_task_record_path(relative, resolver.excluded):
            archived, problem = resolver.find_by_name(Path(target).name)
            if archived is not None and problem is None:
                try:
                    text = _read_text(archived)
                except ConsoleError:
                    text = ""
                heading = text.splitlines()[0] if text else ""
                if re.match(rf"^#\s+(?:Task\s+)?`?{re.escape(row.task_id)}`?(?:\s|$)",
                            heading):
                    return archived, None
    if not path.is_relative_to(project) or not path.is_file():
        raise ConsoleError(f"Task {row.task_id} file is unavailable within the project: {path}")
    return path, None


def _section(text: str, *names: str) -> tuple[str, ...]:
    """Return the first named level-two section, tolerating decorative emoji."""
    inside = False
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            heading = re.sub(r"^[^\w]+", "", line[3:]).strip().casefold()
            inside = heading in {name.casefold() for name in names}
        elif inside and line.strip():
            lines.append(line.strip())
    return tuple(lines)


def _git_result(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ("git", "-C", str(project), *args),
            capture_output=True, text=True, check=False, timeout=5,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ConsoleError(f"Git {' '.join(args)} failed: {error}") from error


def _git(project: Path, *args: str) -> str:
    result = _git_result(project, *args)
    if result.returncode:
        raise ConsoleError(f"Git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _git_optional(project: Path, *args: str) -> str | None:
    """Return Git output, or None when the object or ref does not exist."""
    result = _git_result(project, *args)
    return None if result.returncode else result.stdout


def _primary_checkout(project: Path) -> tuple[Path | None, str | None]:
    """Resolve Git's first registered worktree, which is the primary checkout."""
    result = _git_result(project, "worktree", "list", "--porcelain")
    if result.returncode:
        return None, "Cannot resolve the primary checkout"
    primary = next((line.removeprefix("worktree ") for line in result.stdout.splitlines()
                    if line.startswith("worktree ")), None)
    directory = Path(primary).resolve() if primary else None
    if directory is None or not directory.is_dir():
        return None, "Primary checkout is unavailable"
    return directory, None


def _worktrees(records: list[dict[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    """Return the registered branch-to-path map and each worktree's HEAD by path."""
    branches: dict[str, str] = {}
    heads: dict[str, str] = {}
    for record in records:
        path = record.get("worktree")
        if not path:
            continue
        heads[path] = record.get("HEAD", "")
        if record.get("branch", "").startswith("refs/heads/"):
            branches[record["branch"].removeprefix("refs/heads/")] = path
    return branches, heads


def _stat_identity(path: Path) -> tuple[int, int] | None:
    """Return a file's size and modification time, or None when it is unreadable."""
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_size, status.st_mtime_ns


class DeliveryCache:
    """Remember each task's delivery gate outcome until one of its inputs changes.

    `delivery_readiness` is a pure function of the task worktree contents and
    HEAD, the handoff and state files, the execution evidence, the lifecycle
    registration files, and whether `main` moved (a stale-base proof). The key
    holds all of them, so an unchanged review-ready task is not rechecked and
    any change discards its entry. Failures are cached too: the console shows
    their text. A dirty worktree is never cached; the gate rejects it cheaply.
    """

    def __init__(self) -> None:
        self._items: dict[str, tuple[tuple, str | None]] = {}

    def pending(self, project: Path, worktree: Path, head: str, task_id: str,
                identity: ResolvedTaskIdentity, main_commit: str | None,
                common_dir: Path | None) -> str | None:
        """Return the delivery failure text, or None when delivery is ready."""
        key = None
        status = _git_result(worktree, "status", "--porcelain")
        if not status.returncode and not status.stdout and head and common_dir is not None:
            lifecycle = common_dir / WORKTREE_STATE_DIRECTORY / f"{identity.artifact_stem}.json"
            try:
                handoff = worktree / _relative(project, identity.handoff_path)
            except ConsoleError:
                handoff = None
            if handoff is not None:
                key = (head, main_commit,
                       *(_stat_identity(path) for path in (
                           handoff, state_path(worktree, task_id), worktree / EXECUTION_EVIDENCE_PATH,
                           lifecycle, common_dir / INTEGRATION_LEASE_NAME,
                           common_dir / INTEGRATION_STATE_NAME)))
        if key is not None:
            cached = self._items.get(str(worktree))
            if cached is not None and cached[0] == key:
                return cached[1]
        try:
            delivery_readiness(worktree, task_id, verify_worktree=False)
            outcome = None
        except (MeridianError, OSError, ValueError) as error:
            outcome = str(error)
        if key is None:
            self._items.pop(str(worktree), None)
        else:
            self._items[str(worktree)] = (key, outcome)
        return outcome


def _committed_update(project: Path, relative: str, ref: str = "HEAD") -> int | None:
    """Return the last committed change to a task record, when Git knows it."""
    try:
        value = _git(project, "log", "-1", "--format=%ct", ref, "--", relative).strip()
        return int(value) if value else None
    except (ConsoleError, ValueError):
        return None


def _select_profile(project: Path) -> Profile:
    try:
        mode = detect_mode(project)
    except MeridianError as error:
        raise ConsoleError(str(error).partition("; pass --mode")[0]) from error
    return PROFILES[mode]


def _relative(project: Path, path: Path) -> str:
    try:
        return path.relative_to(project).as_posix()
    except ValueError as error:
        raise ConsoleError(f"Task record is outside the project: {path}") from error


class IdentityCache:
    """Resolve each task identity once per console process.

    Entries are valid only for the bytes of the identity declaration they were
    resolved under; any change to that file discards them. Failures are never
    cached, so a corrected project recovers on the next refresh.
    """

    def __init__(self) -> None:
        self._declaration: bytes | None = None
        self._loaded = False
        self._items: dict[str, ResolvedTaskIdentity] = {}

    def resolve(self, project: Path, task_id: str) -> ResolvedTaskIdentity:
        try:
            declaration = (project / TASK_IDENTITY_PATH).read_bytes()
        except OSError:
            declaration = None
        if not self._loaded or declaration != self._declaration:
            self._items.clear()
            self._declaration, self._loaded = declaration, True
        identity = self._items.get(task_id)
        if identity is None:
            identity = self._items[task_id] = resolve_task_identity(project, task_id, "existing")
        return identity


def _read_console_state(project: Path, profile: Profile, task_id: str,
                        record_loader: Callable[[], str | None], *, text: str | None = None
                        ) -> tuple[dict | None, str | None]:
    """Read only the addressed task; missing state alone enables legacy prose."""
    # Class is metadata for choosing the SPIKE machine, never a status projection.
    try:
        record = record_loader() if text is not None or state_path(project, task_id).exists() else ""
        state = read_task_state(
            project, task_id, profile.name, review_required=None,
            spike=read_task_field(record or "", "Class") == "SPIKE",
            text=text, stop_factory=stop_error,
        )
        return state, None
    except MeridianStop as error:
        if error.code == "TASK_STATE_MISSING":
            return None, None
        return None, str(error)
    except ConsoleError as error:
        return None, str(stop_error("TASK_STATE_INVALID", f"state metadata: {error}",
                                    task_id=task_id, project=project))


def _branch_facts(project: Path, profile: Profile, task_id: str, queue: str,
                  worktrees: dict[str, str], identities: IdentityCache | None = None,
                  resolver: RecordResolver | None = None, main_record: str | None = None,
                  archived_link: bool = False, main_state: dict | None = None
                  ) -> tuple[BranchFacts | None, str | None, str | None, str | None]:
    """Read one task branch and its worktree state without modifying either.

    Returns the branch facts, the branch task record text and path, and the
    registered worktree path (known even when the branch ref is unreadable).
    """
    try:
        if archived_link:
            # _task_path already verified the uniquely moved record and its heading.
            identity = resolve_task_identity(project, task_id, "existing", check_queue_links=False)
        else:
            identity = (identities or IdentityCache()).resolve(project, task_id)
    except MeridianError as error:
        raise ConsoleError(f"Cannot resolve task identity for {task_id}: {error}") from error
    branch = identity.branch_name
    worktree = worktrees.get(branch)
    if _git_optional(project, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is None:
        return None, None, None, worktree
    ref = f"refs/heads/{branch}"

    def show(relative: str) -> str | None:
        return _git_optional(project, "show", f"{ref}:{relative}")

    record_relative = _relative(project, identity.task_path)
    archived_relative = str(Path(record_relative).parent / "done" / Path(record_relative).name)

    def record_loader():
        for relative in (record_relative, archived_relative):
            if worktree and (Path(worktree) / relative).is_file():
                return _read_text(Path(worktree) / relative)
            text = show(relative)
            if text is not None:
                return text
        return None

    branch_state = branch_error = None
    state_source = f"task state on branch {branch}"
    if worktree and Path(worktree).is_dir():
        state_source = f"task state in worktree {branch}"
        branch_state, branch_error = _read_console_state(Path(worktree), profile, task_id, record_loader)
    else:
        state_text = show(_relative(project, state_path(project, task_id)))
        if state_text is not None:
            branch_state, branch_error = _read_console_state(
                project, profile, task_id, record_loader, text=state_text)

    def status_reader(row_id: str, _cells: dict[str, str]) -> str | None:
        if row_id != task_id:
            return None
        state = branch_state if branch_state is not None else main_state
        return "STATE_ERROR" if branch_error else state["status"] if state else None

    queue_text = show(queue)
    row = next((item for item in parse_queue(queue_text, f"{branch}:{queue}", profile, status_reader)
                if item.task_id == task_id), None) if queue_text is not None else None
    if row is None:
        record_path = None
    elif has_link(row.link):
        record_path = link_target(queue, row.link)
    else:
        record_path = main_record
    record = show(record_path) if record_path else None
    if record is None and resolver and row and not has_link(row.link):
        # The branch moved the record: resolve it in the branch tree by the same rules.
        record_path = resolver.find_on_ref(ref, task_id)
        record = show(record_path) if record_path else None
    legacy = branch_state is None and main_state is None and branch_error is None
    review = (show(_relative(project, identity.review_path))
              if profile.name == "governed-sdd" and legacy else None)
    base = "refs/heads/main" if _git_optional(
        project, "rev-parse", "--verify", "--quiet", "refs/heads/main") is not None else "HEAD"
    ahead = (_git_optional(project, "rev-list", "--count", f"{base}..{ref}") or "0").strip() != "0"
    dirty = bool(worktree and (_git_optional(worktree, "status", "--porcelain") or "").strip())
    working_row = None
    if dirty and worktree and legacy:
        try:
            working_text = _read_text(Path(worktree) / queue)
            working_row = next(
                (item for item in parse_queue(working_text, f"{worktree}:{queue}", profile)
                 if item.task_id == task_id),
                None,
            )
        except ConsoleError:
            # An unreadable or invalid uncommitted queue cannot supersede the
            # committed branch state.
            pass
    facts = BranchFacts(
        branch=branch, row=row, record=record_status(record) if legacy else None,
        handoff=handoff_status(show(_relative(project, identity.handoff_path))),
        review_verdict=latest_review_verdict(review) if legacy else None, ahead=ahead,
        worktree=worktree, dirty=dirty, working_row=working_row,
        record_path=record_path,
        worktree_available=bool(worktree and Path(worktree).is_dir()),
        state=branch_state, state_error=branch_error, state_source=state_source,
    )
    return facts, record, record_path, worktree


def _dependency_ids(row: QueueRow) -> tuple[str, ...]:
    dependencies = tuple(
        item.strip().strip("`") for item in row.dependencies.split(",")
        if item.strip() not in ("", "—", "-")
    )
    if any(not ID_PATTERN.fullmatch(item) for item in dependencies):
        raise ConsoleError(f"Task {row.task_id} has an invalid dependency")
    return dependencies


def _dependency_states(profile: Profile, by_id: dict[str, str],
                       dependencies: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (item, {
            "done": "Done", "in_progress": "Working",
            "ready_for_review": "Review", "todo": "Open",
        }[profile.phases[by_id[item]]])
        for item in dependencies if item in by_id
    )


# closure-status steps that mean closure work remains after `integrate stage`.
CLOSING_STEPS = frozenset({"C6", "C7", "C9", "C10"})


def _closing_task(project: Path, profile: Profile, row: QueueRow, queue: Path,
                  worktrees: dict[str, str], identities: IdentityCache | None,
                  resolver: RecordResolver, by_id: dict[str, str]) -> Task | None:
    """List a terminal task with closure work or a cleanup-only hint.

    The queue keeps its real status; `CLOSING` is derived from the registered
    canonical worktree and the lifecycle command, and nothing is written. The
    check costs no subprocess for a done row without a registered worktree.
    """
    if row.status != profile.closing_status:
        return None
    needle = row.task_id.casefold()
    if not any(needle in branch.casefold() for branch in worktrees):
        return None
    try:
        identity = (identities or IdentityCache()).resolve(project, row.task_id)
    except MeridianError:
        return None
    worktree = worktrees.get(identity.branch_name)
    if worktree is None:
        return None
    closure: dict[str, object] | None = None
    try:
        report, _ready = closure_status(row.task_id, None, project, identity=identity)
        if (isinstance(report, dict) and report.get("step") in CLOSING_STEPS
                and "resume" in report and "stop_reason" in report
                and (report["resume"] is None or isinstance(report["resume"], str))
                and (report["stop_reason"] is None or isinstance(report["stop_reason"], str))):
            closure = report
    except (MeridianError, OSError, ValueError):
        # A transient lifecycle read keeps the task listed with unavailable progress.
        pass
    if closure is not None and closure["step"] == "C10" and closure["resume"] is None:
        return None
    cleanup_pending = bool(closure and closure["step"] == "C10" and closure["resume"])
    started_at = None
    try:
        started_at = lifecycle_started_at(row.task_id, project, identity=identity)
    except (MeridianError, OSError, ValueError):
        pass
    progress_phase, remaining_gates = (
        _lifecycle_progress(str(closure["step"]), True) if closure else ("unavailable", ()))
    try:
        path, _problem = _task_path(project, queue, row, resolver)
        text = _read_text(path) if path else None
    except ConsoleError:
        path, text = None, None
    dependencies = _dependency_ids(row)
    return Task(
        task_id=row.task_id, title=row.title or heading_title(text or "") or row.task_id,
        status=row.status, phase=row.section, dependencies=dependencies, path=path,
        objective=_section(text or "", "Objective", "Goal"),
        criteria=_section(text or "", "Acceptance Criteria"),
        worktree=worktree, readiness="DONE" if cleanup_pending else "CLOSING",
        lifecycle="done" if cleanup_pending else "closing", source="main",
        cleanup_pending=cleanup_pending,
        registered_worktree=True, workflow=profile.name,
        updated_at=_committed_update(project, _relative(project, path)) if path else None,
        closure_stop_reason=closure["stop_reason"] if closure else None,
        closure_resume=closure["resume"] if closure else None,
        started_at=started_at, progress_phase=progress_phase, remaining_gates=remaining_gates,
        dependency_states=_dependency_states(profile, by_id, dependencies),
    )


def _cached_identity(project: Path, task_id: str,
                     identities: IdentityCache | None) -> ResolvedTaskIdentity | None:
    """Return the console's resolved identity, or None to let the reader resolve (and report)."""
    try:
        return (identities or IdentityCache()).resolve(project, task_id)
    except MeridianError:
        return None


def _delivery_pending(project: Path, worktree: str | None, task_id: str, heads: dict[str, str],
                      identities: IdentityCache | None, cache: DeliveryCache,
                      shared: dict[str, object]) -> str | None:
    """Return why a review-ready task is not deliverable, or None when it is."""
    if not worktree:
        return "canonical worktree unavailable"
    identity = _cached_identity(project, task_id, identities)
    if identity is None:
        # The gate resolves identity itself and reports the failure verbatim.
        try:
            delivery_readiness(Path(worktree), task_id, verify_worktree=False)
            return None
        except (MeridianError, OSError, ValueError) as error:
            return str(error)
    if "main" not in shared:
        shared["main"] = (_git_optional(project, "rev-parse", "--verify", "--quiet",
                                        "refs/heads/main") or "").strip() or None
        try:
            shared["common"] = canonical_git_common_dir(project)
        except (MeridianError, OSError):
            shared["common"] = None
    return cache.pending(project, Path(worktree), heads.get(worktree, ""), task_id, identity,
                         shared["main"], shared["common"])


def load_snapshot(project: Path, identities: IdentityCache | None = None,
                  deliveries: DeliveryCache | None = None) -> Snapshot:
    return _load_snapshot(project, identities, deliveries=deliveries)


def load_task(project: Path, task_id: str,
              identities: IdentityCache | None = None) -> Task | None:
    """Read only one queued or closing task, or None when the queues no longer hold it."""
    snapshot = _load_snapshot(project, identities, only=task_id)
    return snapshot.tasks[0] if snapshot.tasks else None


def _load_snapshot(project: Path, identities: IdentityCache | None = None,
                   only: str | None = None, deliveries: DeliveryCache | None = None) -> Snapshot:
    """Build the snapshot; `only` restricts the per-task Git reads to one task.

    Git lists the registered worktrees once; every lifecycle reader below
    shares that read.
    """
    project = project.expanduser().resolve()
    with contextlib.ExitStack() as stack:
        return _build_snapshot(project, identities, only, deliveries, stack)


def _build_snapshot(project: Path, identities: IdentityCache | None, only: str | None,
                    deliveries: DeliveryCache | None, stack: contextlib.ExitStack) -> Snapshot:
    # Read the registered worktrees first so that profile and location detection
    # share the one read; a failure surfaces where the read used to happen.
    records: list[dict[str, str]] = []
    listing_error: ConsoleError | None = None
    try:
        records = parse_worktree_records(_git(project, "worktree", "list", "--porcelain"))
        stack.enter_context(shared_worktree_records(records))
    except ConsoleError as error:
        listing_error = error
    profile = _select_profile(project)
    try:
        locations = resolve_project_locations(project)
    except Exception as error:
        raise ConsoleError(f"Cannot resolve canonical queue: {error}") from error
    queue = project / locations.queue
    archive = queue.with_name("QUEUE_ARCHIVE.md")
    resolver = RecordResolver(project, locations)
    states: dict[str, dict | None] = {}
    state_errors: dict[str, str | None] = {}

    def status_reader(task_id: str, cells: dict[str, str]) -> str | None:
        provisional = QueueRow(
            task_id, "", "", (), "", cells.get("File", cells.get("Task file", "")), None)

        def record_loader():
            path, _problem = _task_path(project, queue, provisional, resolver)
            return _read_text(path) if path else None
        states[task_id], state_errors[task_id] = _read_console_state(
            project, profile, task_id, record_loader)
        if state_errors[task_id]:
            return "STATE_ERROR"
        return states[task_id]["status"] if states[task_id] else None

    active_rows = parse_queue(_read_text(queue), str(queue), profile, status_reader)
    archived_rows = parse_queue(_read_text(archive), str(archive), profile) if archive.is_file() else []
    by_id: dict[str, str] = {}
    for row in (*active_rows, *archived_rows):
        if row.task_id in by_id:
            raise ConsoleError(f"Duplicate task ID across queues: {row.task_id}")
        by_id[row.task_id] = row.status
    # A single-task read needs neither the branch line nor the change count.
    status_lines = ["## "] if only is not None else _git(
        project, "status", "--porcelain=v1", "--branch").splitlines()
    if not status_lines:
        raise ConsoleError("Git status returned no branch line")
    branch_line = status_lines[0].removeprefix("## ")
    branch = branch_line.split("...", 1)[0].split(" [", 1)[0]
    if listing_error:
        raise listing_error
    worktrees, heads = _worktrees(records)
    delivery_cache = deliveries or DeliveryCache()
    deliveries_shared: dict[str, object] = {}
    queue_relative = _relative(project, queue)
    tasks: list[Task] = []
    closing_count = 0
    # A phase archived by `integrate stage` leaves the active queue while its
    # task still has closure work, so archived rows are checked too.
    for row in archived_rows:
        if only is not None and row.task_id != only:
            continue
        closing = _closing_task(project, profile, row, queue, worktrees, identities,
                                resolver, by_id)
        if closing:
            tasks.append(closing)
            closing_count += int(not closing.cleanup_pending)
    for row in active_rows:
        if only is not None and row.task_id != only:
            continue
        if state_errors[row.task_id]:
            tasks.append(Task(
                row.task_id, row.title or row.task_id, "STATE_ERROR", row.section, (), None, (), (),
                lifecycle="in_progress", readiness="STATE ERROR", legacy=False,
                source="task state on main", state_error=state_errors[row.task_id], workflow=profile.name,
            ))
            continue
        if profile.phases[row.status] == "done":
            closing = _closing_task(project, profile, row, queue, worktrees, identities,
                                    resolver, by_id)
            if closing:
                state = states[row.task_id]
                closing = replace(closing, legacy=state is None,
                                  review_verdict=state.get("review", {}).get("verdict") if state else None)
                tasks.append(closing)
                closing_count += int(not closing.cleanup_pending)
            continue
        dependencies = _dependency_ids(row)
        path, main_problem = _task_path(project, queue, row, resolver)
        primary_text = _read_text(path) if path else None
        if main_problem:
            # Task identity needs exactly one record, so a task without one has no branch state.
            facts, branch_text, branch_path, worktree = None, None, None, None
        else:
            facts, branch_text, branch_path, worktree = _branch_facts(
                project, profile, row.task_id, queue_relative, worktrees, identities, resolver,
                _relative(project, path) if path and not has_link(row.link) else None,
                main_state=states[row.task_id],
                archived_link=bool(path and has_link(row.link) and
                                   path != (project / link_target(queue_relative, row.link)).resolve()))
        branch_policy_text = (branch_text if facts and facts.row
                              and facts.row.status != row.status else primary_text)
        state = facts.state if facts and facts.state is not None else states[row.task_id]
        state_error = facts.state_error if facts else None
        review = ("REQUIRED" if state.get("review", {}).get("required", profile.name == "governed-sdd")
                  else "NOT REQUIRED") if state else (
                      row.review if row.review is not None else record_review(branch_policy_text))
        effective = effective_state(profile, row, None if state or state_error else record_status(primary_text),
                                    facts, review, states[row.task_id], state_error)
        closure_reason = closure_resume = None
        started_at = None
        progress_phase = "unavailable"
        remaining_gates: tuple[str, ...] = ()
        # The lifecycle command is authoritative for closure guidance.  Restrict
        # the extra read to registered active worktrees; queued tasks retain the
        # constant-cost refresh path established by task 078.
        if (facts and facts.worktree and profile.name == "governed-sdd"
                and effective.lifecycle == "ready_for_review"):
            # A task waiting for approval stops at the review gate (C3), which
            # closure-status never reports; keep its timing and gate visible.
            progress_phase, remaining_gates = _lifecycle_progress("C3", True)
            try:
                started_at = lifecycle_started_at(
                    row.task_id, project, identity=_cached_identity(project, row.task_id, identities))
            except (MeridianError, OSError, ValueError):
                pass
        if facts and facts.worktree and effective.lifecycle == "in_progress":
            known = _cached_identity(project, row.task_id, identities)
            try:
                closure, _ready = closure_status(row.task_id, None, project, identity=known)
                closure_reason = closure["stop_reason"]
                closure_resume = closure["resume"]
                progress_phase, remaining_gates = _lifecycle_progress(
                    str(closure.get("step", "")), bool(facts and facts.worktree),
                )
            except (MeridianError, OSError, ValueError):
                # A transient lifecycle read must not make the entire dashboard stale.
                pass
            try:
                started_at = lifecycle_started_at(row.task_id, project, identity=known)
            except (MeridianError, OSError, ValueError):
                # Legacy or unreadable timing data is intentionally non-fatal.
                pass
        if state and profile.name == "governed-sdd":
            started_at = next((item["at"] for item in state["transitions"]
                               if item["to"] == "IN_PROGRESS"), None)
        from_branch = facts is not None and branch_text is not None and effective.source != "main"
        task_text = branch_text if from_branch else primary_text
        problem = None if task_text is not None else (main_problem or "task record not found")
        # Dependencies are satisfied by integrated state only: a task accepted on its
        # branch does not unblock dependents until it reaches the primary queue.
        missing = [item for item in dependencies if item not in by_id]
        waiting = [item for item in dependencies
                   if item in by_id and by_id[item] not in profile.satisfying]
        if state_error:
            readiness = "STATE ERROR"
        elif effective.mismatch:
            readiness = "MISMATCH"
        elif problem:
            readiness = "UNKNOWN: " + problem.split(":", 1)[0]
        elif missing:
            readiness = "UNKNOWN: missing " + ", ".join(missing)
        elif waiting:
            readiness = "BLOCKED: " + ", ".join(waiting)
        else:
            readiness = {
                "todo": "READY", "in_progress": "IN PROGRESS",
                "ready_for_review": "READY FOR REVIEW", "done": "DONE ON BRANCH",
            }[effective.lifecycle]
        delivery_pending = None
        if state and profile.name == "governed-sdd" and state["status"] == "READY_FOR_REVIEW":
            delivery_pending = _delivery_pending(
                project, worktree, row.task_id, heads, identities, delivery_cache, deliveries_shared)
            if delivery_pending is not None:
                readiness = "PENDING DELIVERY/CHANGES"
        updated_path = branch_path if from_branch else (_relative(project, path) if path else None)
        updated_ref = ("refs/heads/" + facts.branch) if from_branch else "HEAD"
        title = row.title or heading_title(task_text or "") or row.task_id
        tasks.append(Task(
            task_id=row.task_id, title=title, status=effective.status,
            phase=row.section, dependencies=dependencies, path=path,
            objective=_section(task_text or "", "Objective", "Goal"),
            criteria=_section(task_text or "", "Acceptance Criteria"),
            worktree=worktree, readiness=readiness,
            updated_at=_committed_update(project, updated_path, updated_ref) if updated_path else None,
            lifecycle=effective.lifecycle, source=effective.source,
            mismatch=effective.mismatch, changes_requested=effective.changes_requested,
            active_writer=effective.active_writer,
            registered_worktree=bool(
                facts and facts.worktree and not facts.dirty and facts.row
                and facts.row.status == row.status
            ),
            record_problem=problem, review=review,
            workflow=profile.name,
            closure_stop_reason=closure_reason,
            closure_resume=closure_resume,
            started_at=started_at,
            progress_phase=progress_phase,
            remaining_gates=remaining_gates,
            dependency_states=_dependency_states(profile, by_id, dependencies),
            legacy=state is None and state_error is None,
            review_verdict=state.get("review", {}).get("verdict") if state else (facts.review_verdict if facts else None),
            state_error=state_error, delivery_pending=delivery_pending,
        ))
    return Snapshot(
        project=project, queue=queue, branch=branch_line,
        git_summary="clean" if len(status_lines) == 1 else f"{len(status_lines) - 1} changed paths",
        git_changes=len(status_lines) - 1, tasks=tuple(tasks),
        done_count=sum(profile.phases[status] == "done" for status in by_id.values()) - closing_count,
    )


class ConsoleState:
    """Snapshot, staleness and refresh state shown by the console.

    `refresh` loads synchronously. `start_refresh` loads on one background
    thread and hands the result over through `apply_pending`, so the display
    only ever changes on the caller's thread and never shows a mixed state.
    """

    def __init__(self, project: Path):
        self.project = project
        self.framework = _framework_identity()
        self.agent_defaults = _agent_defaults()
        self.snapshot: Snapshot | None = None
        self.last_success: datetime | None = None
        self.error: str | None = None
        self.identities = IdentityCache()
        self.deliveries = DeliveryCache()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._pending: tuple[Snapshot | None, str | None] | None = None
        self._launcher: threading.Thread | None = None
        self.launch_target = ""
        self._launch_result: tuple[bool, str] | None = None

    def _load(self) -> tuple[Snapshot | None, str | None]:
        try:
            return load_snapshot(self.project, self.identities, self.deliveries), None
        except ConsoleError as error:
            return None, str(error)

    def _apply(self, candidate: Snapshot | None, error: str | None) -> None:
        if candidate is None:
            self.error = error
            return
        self.snapshot = candidate
        self.last_success = datetime.now().astimezone()
        self.error = None

    def refresh(self) -> None:
        self._apply(*self._load())

    @property
    def refreshing(self) -> bool:
        with self._lock:
            return self._worker is not None

    def start_refresh(self) -> bool:
        """Start a background refresh unless one is already running."""
        with self._lock:
            if self._worker is not None:
                return False
            self._worker = threading.Thread(target=self._run, daemon=True)
            worker = self._worker
        worker.start()
        return True

    def _run(self) -> None:
        try:
            result = self._load()
        except Exception as error:  # a worker must never die silently
            result = (None, f"Refresh failed: {error}")
        with self._lock:
            self._pending = result
            self._worker = None

    @property
    def launching(self) -> bool:
        with self._lock:
            return self._launcher is not None

    def start_launch(self, task: Task, agent: str, dirty_confirmed: bool = False) -> bool:
        """Revalidate and launch on one background thread; False while one is pending."""
        with self._lock:
            if self._launcher is not None:
                return False
            self.launch_target = f"{agent} for task {task.task_id}"
            self._launcher = threading.Thread(
                target=self._run_launch, args=(task, agent, dirty_confirmed), daemon=True)
            launcher = self._launcher
        launcher.start()
        return True

    def _run_launch(self, task: Task, agent: str, dirty_confirmed: bool) -> None:
        try:
            result = _launch_selected(self, task, agent, dirty_confirmed)
        except Exception as error:  # a worker must never die silently
            result = (False, f"Launch failed: {error}; [copy] remains available")
        with self._lock:
            self._launch_result = result
            self._launcher = None

    def take_launch_result(self) -> tuple[bool, str] | None:
        with self._lock:
            result, self._launch_result = self._launch_result, None
        return result

    def apply_pending(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is not None:
            self._apply(*pending)


def one_shot(state: ConsoleState) -> str:
    if state.error:
        return f"STALE: {state.error}"
    snapshot = state.snapshot
    if snapshot is None:
        return "No project snapshot available"
    stamp = state.last_success.strftime("%Y-%m-%d %H:%M:%S %Z") if state.last_success else "unknown"
    lines = [
        (f"MERIDIAN | {state.framework.label} | {snapshot.project} | {snapshot.branch}"
         f" | {snapshot.git_summary}"),
        (f"Updated: {stamp} | Open: {sum(not task.cleanup_pending for task in snapshot.tasks)}"
         f" | Done: {snapshot.done_count}"),
    ]
    for task in snapshot.tasks:
        objective = " ".join(task.objective)
        lines.append(f"{task.task_id} [{task.readiness}] {task.title}")
        if objective:
            lines.append(f"  {objective}")
        lines.append(f"  Dependencies: {', '.join(task.dependencies) or 'none'}")
        lines.append(f"  Status: {task.status} | Verdict: {task.review_verdict or 'none'}"
                     + (" | legacy" if task.legacy else ""))
        if task.state_error:
            lines.append(f"  State error: {task.state_error}")
        if task.source != "main":
            lines.append(f"  State from: {task.source}")
        if task.mismatch:
            lines.append(f"  Mismatch: {task.mismatch}")
        if task.closure_stop_reason:
            lines.append(f"  Closure stop: {task.closure_stop_reason}")
        if task.cleanup_pending:
            lines.append("  Cleanup pending")
        if task.closure_resume:
            lines.append(f"  Resume: {task.closure_resume}")
        if task.shows_progress:
            lines.append(f"  Elapsed: {_elapsed(task.started_at)}")
            lines.append(f"  Progress: {task.progress_phase}")
            lines.append(f"  Remaining gates: {', '.join(task.remaining_gates) or 'none'}")
        if task.markers:
            lines.append(f"  Markers: {', '.join(task.markers)}")
        if task.record_problem:
            lines.append(f"  Record: {task.record_problem}")
        lines.append(f"  Next action: {task.next_action}")
        if task.worktree:
            lines.append(f"  Worktree: {task.worktree}")
    lines.append("Agent activity: unavailable (no verified local source)")
    return "\n".join(lines)


def _put(screen, y: int, x: int, value: str, width: int, attr: int = 0) -> None:
    height, screen_width = screen.getmaxyx()
    if y < 0 or y >= height or x >= screen_width or width <= 0:
        return
    try:
        screen.addnstr(y, x, value, min(width, screen_width - x - 1), attr)
    except curses.error:
        pass


def _fill(screen, y: int, x: int, width: int, attr: int) -> None:
    _put(screen, y, x, " " * max(0, width), width, attr)


def _palette(screen) -> dict[str, int]:
    """Use the terminal background while preserving console foreground colors."""
    if not curses.has_colors():
        screen.bkgd(" ", curses.A_NORMAL)
        return {
            "base": curses.A_NORMAL, "text": curses.A_BOLD,
            "muted": curses.A_DIM, "line": curses.A_DIM,
            "ready": curses.A_BOLD, "working": curses.A_BOLD,
            "blocked": curses.A_BOLD, "unknown": curses.A_BOLD,
            "stale": curses.A_REVERSE | curses.A_BOLD,
            "selected": curses.A_REVERSE | curses.A_BOLD,
            "tab": curses.A_REVERSE | curses.A_BOLD,
            "tab_underline": curses.A_BOLD,
            "title": curses.A_BOLD,
            "action": curses.A_BOLD,
        }
    curses.start_color()
    try:
        curses.use_default_colors()
        background = -1
    except curses.error:
        background = 233 if curses.COLORS >= 256 else curses.COLOR_BLACK
    if curses.COLORS >= 256:
        colors = (
            (253, background), (253, background), (245, background),
            (240, background), (80, background), (141, background),
            (221, background), (203, background), (231, 52), (16, 75),
            (253, 238), (181, background), (150, background),
            (117, background),
        )
    else:
        colors = (
            (curses.COLOR_WHITE, background),
            (curses.COLOR_WHITE, background),
            (curses.COLOR_WHITE, background),
            (curses.COLOR_WHITE, background),
            (curses.COLOR_CYAN, background),
            (curses.COLOR_MAGENTA, background),
            (curses.COLOR_YELLOW, background),
            (curses.COLOR_RED, background),
            (curses.COLOR_WHITE, curses.COLOR_RED),
            (curses.COLOR_BLACK, curses.COLOR_CYAN),
            (curses.COLOR_WHITE, curses.COLOR_BLUE),
            (curses.COLOR_MAGENTA, background),
            (curses.COLOR_GREEN, background),
            (curses.COLOR_CYAN, background),
        )
    names = ("base", "text", "muted", "line", "ready", "working",
             "blocked", "unknown", "stale", "selected", "tab", "title", "action",
             "tab_underline")
    palette = {}
    for index, (name, (foreground, background)) in enumerate(zip(names, colors), 1):
        curses.init_pair(index, foreground, background)
        palette[name] = curses.color_pair(index)
    palette["text"] |= curses.A_BOLD
    palette["title"] |= curses.A_BOLD
    screen.bkgd(" ", palette["base"])
    return palette


def _wrapped(lines: tuple[str, ...] | list[str], width: int) -> list[str]:
    output: list[str] = []
    for line in lines:
        output.extend(textwrap.wrap(line, max(10, width), replace_whitespace=False) or [""])
    return output


FILTERS = ("Ready", "Working", "Blocked", "Unknown", "Review", "Mismatch", "Closing")


def _state_label(task: Task) -> tuple[str, str]:
    if task.state_error:
        return "Unknown", "blocked"
    if task.cleanup_pending:
        return "Done", "muted"
    if task.readiness == "MISMATCH":
        return "Mismatch", "blocked"
    if task.lifecycle == "closing":
        return "Closing", "working"
    if task.lifecycle in ("ready_for_review", "done") and not task.readiness.startswith(
            ("BLOCKED", "UNKNOWN")):
        return "Review", "ready"
    if task.readiness == "READY":
        return "Ready", "ready"
    if task.readiness == "IN PROGRESS":
        return "Working", "working"
    if task.readiness.startswith("BLOCKED"):
        return "Blocked", "blocked"
    return "Unknown", "unknown"


def _filter_counts(snapshot: Snapshot | None) -> dict[str, int]:
    counts = {name: 0 for name in FILTERS}
    for task in snapshot.tasks if snapshot else ():
        if not task.cleanup_pending:
            counts[_state_label(task)[0]] += 1
    return counts


def _cycle_filter(snapshot: Snapshot | None, current: str, direction: int) -> str:
    filters = ("All", *FILTERS)
    counts = _filter_counts(snapshot)
    start = filters.index(current)
    for step in range(1, len(filters) + 1):
        candidate = filters[(start + direction * step) % len(filters)]
        if candidate == "All" or counts[candidate]:
            return candidate
    return "All"


def _tab_at(snapshot: Snapshot | None, x: int, y: int) -> str | None:
    if y != 1:
        return None
    counts = _filter_counts(snapshot)
    tabs = (("All", len(snapshot.tasks) if snapshot else 0), *counts.items())
    left = 1
    for name, count in tabs:
        right = left + len(f" {name} {count} ")
        if left <= x < right:
            return name
        left = right + 1
    return None


def _copy_to_clipboard(value: str) -> bool:
    if sys.platform == "darwin":
        commands = (("pbcopy",),)
    elif sys.platform == "win32":
        commands = (("clip",),)
    else:
        commands = (("wl-copy",), ("xclip", "-selection", "clipboard"))
    for command in commands:
        try:
            result = subprocess.run(command, input=value, text=True,
                                    capture_output=True, check=False, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return True
    return False


def _action_hit(x: int, y: int,
                bounds: tuple[int, int, set[int]] | None) -> bool:
    return bool(bounds and bounds[0] <= x <= bounds[1] and y in bounds[2])


def _age(timestamp: int | None) -> str:
    if timestamp is None:
        return "—"
    seconds = max(0, int(time.time()) - timestamp)
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _elapsed(started_at: str | None, now: datetime | None = None) -> str:
    """Format wall-clock cycle time, including idle periods, without an ETA."""
    if not started_at:
        return "unavailable"
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return "unavailable"
    if started.tzinfo is None:
        return "unavailable"
    seconds = max(0, int(((now or datetime.now(timezone.utc)) - started).total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _lifecycle_progress(step: str, active: bool) -> tuple[str, tuple[str, ...]]:
    """Map closure-status's authoritative steps to display-only ordered gates."""
    gates = ("Run task validation", "Record validation evidence", "Stage integration",
             "Run candidate validation", "Push main", "Clean up worktree")
    if step == "C1":
        return "working", gates
    if step == "C3":
        return "review pending", ("Independent review", *gates[2:])
    if step == "C5":
        return "validation/evidence pending", gates
    if step in {"C6", "C7"}:
        return "candidate validation", gates[2:]
    if step == "C9":
        return "push pending", gates[4:]
    if step == "C10":
        return ("cleanup pending", (gates[-1],)) if active else ("done", ())
    return "unavailable", ()


def _clip(value: str, width: int) -> str:
    return value if len(value) <= width else value[:max(0, width - 1)] + "…"


def _header_framework_label(identity: FrameworkIdentity, width: int,
                            project_name: str, branch: str) -> str:
    """Keep the watched project and branch visible by shortening the framework root first."""
    version = "version unknown" if identity.version == "unknown" else f"v{identity.version}"
    fixed = len("Project command center      ") + len(version) + len(project_name) + len(branch)
    return f"{version} | {_clip(identity.root_label, max(8, width - fixed))}"


def _detail_lines(task: Task, width: int, palette: dict[str, int],
                  compact: bool = False) -> list[tuple[str, int]]:
    lines: list[tuple[str, int]] = []

    def add(value: str, style: str = "base") -> None:
        for part in _wrapped([value], width):
            lines.append((part, palette[style]))

    label, color = _state_label(task)
    add("Task details", "text")
    add("")
    if not compact:
        add("")
    add(task.title, "title")
    add(f"Task {task.task_id}", "muted")
    add(f"○ {label}", color)
    add(f"Status: {task.status}; verdict: {task.review_verdict or 'none'}", "muted")
    if task.legacy:
        add("legacy", "muted")
    if task.state_error:
        add(f"State error: {task.state_error}", "blocked")
    if task.source != "main":
        add(f"State from {task.source}", "muted")
    if task.mismatch:
        add(f"Mismatch: {task.mismatch}", "blocked")
    for marker in task.markers:
        add(f"● {marker.capitalize()}", "working")
    if task.record_problem:
        add(task.record_problem[:1].upper() + task.record_problem[1:], "blocked")
    if task.closure_stop_reason:
        add(f"Closure stop: {task.closure_stop_reason}", "blocked")
    if task.cleanup_pending:
        add("Cleanup pending", "muted")
    if task.closure_resume:
        add(f"Resume: {task.closure_resume}", "action")
    if task.shows_progress:
        add(f"Elapsed cycle time: {_elapsed(task.started_at)}", "muted")
        add(f"Last activity: {_age(task.updated_at)}", "muted")
        add(f"Lifecycle progress: {task.progress_phase}", "muted")
        add("Remaining gates: " + (", ".join(task.remaining_gates) or "none"), "muted")
    add("")
    add("Dependencies", "muted")
    states = dict(task.dependency_states)
    for dependency in task.dependencies:
        add(f"{dependency} — {states.get(dependency, 'state unavailable')}")
    if not task.dependencies:
        add("none")
    if not compact:
        add("")
    add("Objective", "muted")
    for value in task.objective or ("Unavailable", "Searched headings: Objective, Goal"):
        add(value)
    if not compact:
        add("")
    if task.criteria:
        add("Acceptance criteria", "muted")
        for value in task.criteria:
            add(value)
        if not compact:
            add("")
    add("─" * min(20, width), "line")
    if not compact:
        add("")
    add("Next directive", "muted")
    command = task.launch_command
    action = "Resume" if task.is_resume else "launch"
    add(f"{command}  [copy]  [l {action}]" if command else task.next_action, "action")
    return lines


def _visible_tasks(snapshot: Snapshot | None, status_filter: str, search: str) -> list[Task]:
    tasks = snapshot.tasks if snapshot else ()
    return [
        task for task in tasks
        if (status_filter == "All" or _state_label(task)[0] == status_filter)
        and search.casefold() in (
            f"{task.task_id} {task.title} "
            + " ".join(_group_label(heading) for heading in task.phase)
        ).casefold()
    ]


def _group_label(heading: str) -> str:
    """Remove a queue descriptor while retaining the heading's identity."""
    return re.sub(r"\s+Queue(?=\s*(?:[—–:]|$))", "", heading, flags=re.IGNORECASE)


def _draw_header(screen, state: ConsoleState, palette: dict[str, int],
                 status_filter: str, width: int) -> None:
    snapshot = state.snapshot
    project_name = snapshot.project.name if snapshot else state.project.name
    branch = snapshot.branch.split("...", 1)[0] if snapshot else "unavailable"
    summary = snapshot.git_summary if snapshot else "unknown"
    framework = _header_framework_label(state.framework, width, project_name, branch)
    left = f"Project command center  {framework}  {project_name}  {branch}"
    _put(screen, 0, 1, left, width - 2, palette["text"])
    ahead = re.search(r"\[ahead (\d+)", snapshot.branch) if snapshot else None
    local = f"↑ {ahead.group(1)} local · " if ahead else ""
    age = _age(int(state.last_success.timestamp())) if state.last_success else "never"
    right = f"{local}{summary} · refreshed {age}"
    right_x = width - len(right) - 2
    if right_x > len(left) + 2:
        _put(screen, 0, right_x, right, len(right), palette["blocked"])
    if state.error:
        _put(screen, 1, max(1, width - 9), "STALE", 7, palette["stale"])
    counts = _filter_counts(snapshot)
    tabs = (("All", len(snapshot.tasks) if snapshot else 0), *((name, count) for name, count in counts.items()))
    x = 1
    for name, count in tabs:
        label = f" {name} {count} "
        attr = palette["tab"] if name == status_filter else palette[
            {"All": "text", "Ready": "ready", "Working": "working",
             "Blocked": "blocked", "Unknown": "unknown", "Review": "ready",
             "Closing": "working", "Mismatch": "blocked"}[name]
        ]
        _put(screen, 1, x, label, len(label), attr)
        x += len(label) + 1
    if snapshot and x + 9 < width:
        _put(screen, 1, x + 1, f"Done {snapshot.done_count}", width - x - 2, palette["muted"])
    hint = "tab/shift+tab filter"
    if width - len(hint) - 2 > x + 9:
        _put(screen, 1, width - len(hint) - 2, hint, len(hint), palette["muted"])
    _put(screen, 2, 0, "─" * max(0, width - 1), width - 1, palette["line"])
    selected_x = 1
    for name, count in tabs:
        label_width = len(f" {name} {count} ")
        if name == status_filter:
            _put(screen, 2, selected_x + 1, "━" * max(1, label_width - 2),
                 label_width - 2, palette["tab_underline"])
            break
        selected_x += label_width + 1


LIST_ID_X = 3
LIST_STATUS_WIDTH = 11
LIST_AGE_WIDTH = 9
LIST_MIN_TITLE_WIDTH = 8


@dataclass(frozen=True)
class ListLayout:
    id_x: int
    id_width: int
    title_x: int
    title_width: int
    status_x: int
    age_x: int


def _list_layout(all_tasks: tuple[Task, ...] | list[Task], left_width: int) -> ListLayout:
    """Column positions for the task list.

    The ID width follows the longest ID of the full open task set, so filtering
    or searching never moves a column. It is capped at a third of the pane and
    never squeezes the title below its minimum width.
    """
    status_x = left_width - LIST_STATUS_WIDTH - LIST_AGE_WIDTH - 2
    longest = max((len(task.task_id) for task in all_tasks), default=0)
    room = status_x - 2 - LIST_MIN_TITLE_WIDTH - LIST_ID_X - 1
    id_width = max(1, min(longest, left_width // 3, room))
    title_x = LIST_ID_X + id_width + 1
    return ListLayout(
        LIST_ID_X, id_width, title_x,
        max(LIST_MIN_TITLE_WIDTH, status_x - 2 - title_x),
        status_x, left_width - LIST_AGE_WIDTH - 1,
    )


def _draw_list(screen, tasks: list[Task], selected_id: str | None,
               offset: int, left_width: int, height: int,
               palette: dict[str, int],
               all_tasks: tuple[Task, ...] | list[Task] | None = None) -> int:
    layout = _list_layout(tasks if all_tasks is None else all_tasks, left_width)
    title_width = layout.title_width
    _put(screen, 3, 2, "Tasks", layout.title_x + title_width - 2, palette["muted"])
    _put(screen, 3, layout.status_x, "Status", LIST_STATUS_WIDTH, palette["muted"])
    _put(screen, 3, layout.age_x, "Updated", LIST_AGE_WIDTH, palette["muted"])
    entries: list[tuple[str, Task | None]] = []
    previous: tuple[str, ...] = ()
    for task in tasks:
        shared = 0
        for old, new in zip(previous, task.phase):
            if old != new:
                break
            shared += 1
        for depth, heading in enumerate(task.phase[shared:], shared):
            entries.append(("  " * depth + _group_label(heading), None))
        entries.append(("", task))
        previous = task.phase
    body_top = 5
    body_lines = max(1, height - body_top - 2)
    selected_line = next((i for i, (_, task) in enumerate(entries)
                          if task and task.task_id == selected_id), 0)
    if selected_line < offset:
        offset = selected_line
    if selected_line >= offset + body_lines:
        offset = selected_line - body_lines + 1
    offset = min(offset, max(0, len(entries) - body_lines))
    for line_number, (heading, task) in enumerate(entries[offset:offset + body_lines], body_top):
        if task is None:
            _put(screen, line_number, 1, heading, left_width - 3, palette["muted"])
            continue
        selected = task.task_id == selected_id
        row_attr = palette["selected"] if selected else palette["base"]
        _fill(screen, line_number, 0, left_width - 1, row_attr)
        _put(screen, line_number, 1, "›" if selected else " ", 1, row_attr)
        _put(screen, line_number, layout.id_x, _clip(task.task_id, layout.id_width),
             layout.id_width, row_attr if selected else palette["muted"])
        _put(screen, line_number, layout.title_x, _clip(f"○ {task.title}", title_width),
             title_width, row_attr)
        label, color = _state_label(task)
        flags = ("↺" if task.changes_requested else "") + ("●" if task.active_writer else "")
        _put(screen, line_number, layout.status_x,
             f"{label} {flags}" if flags else label, LIST_STATUS_WIDTH,
             row_attr if selected else palette[color])
        _put(screen, line_number, layout.age_x,
             _age(task.updated_at), LIST_AGE_WIDTH, row_attr if selected else palette["muted"])
    if not tasks:
        _put(screen, body_top + 1, 2, "No matching open tasks", left_width - 4, palette["muted"])
    return offset


def _detail_view(task: Task | None, width: int, height: int, top: int,
                 offset: int, palette: dict[str, int]) -> tuple[list[tuple[str, int]], int, int]:
    """Build a detail viewport and clamp its offset for this exact terminal size."""
    if task is None:
        return [], 0, 1
    lines = _detail_lines(task, width - 2, palette, compact=height < 30)
    body_lines = max(1, height - top - 2)
    return lines, min(max(0, offset), max(0, len(lines) - body_lines)), body_lines


def _scroll_detail(task: Task | None, width: int, height: int, top: int,
                   offset: int, delta: int, palette: dict[str, int]) -> int:
    lines, offset, body_lines = _detail_view(task, width, height, top, offset, palette)
    return min(max(0, offset + delta), max(0, len(lines) - body_lines))


def _draw_detail(screen, task: Task | None, x: int, top: int, width: int,
                 height: int, offset: int, palette: dict[str, int]) -> set[int]:
    if task is None:
        _put(screen, top, x, "No task selected", width, palette["muted"])
        return set()
    lines, offset, body_lines = _detail_view(task, width, height, top, offset, palette)
    for y, (value, attr) in enumerate(lines[offset:offset + body_lines], top):
        _put(screen, y, x, value, width - 1, attr)
    if offset:
        _put(screen, top, x + max(0, width - 13), "↑ more above", 12, palette["muted"])
    if offset + body_lines < len(lines):
        _put(screen, top + body_lines - 1, x + max(0, width - 13), "↓ more below", 12,
             palette["muted"])
    if not task.launch_command:
        return set()
    action_start = next(i for i, (value, _) in enumerate(lines)
                        if value == "Next directive") + 1
    return {
        top + i - offset for i in range(action_start, len(lines))
        if offset <= i < offset + body_lines
    }


def _draw_launch_prompt(screen, width: int, height: int, task: Task | None,
                        confirmation: int,
                        project: Path, defaults: dict[str, AgentDefaults],
                        palette: dict[str, int]) -> None:
    """Draw an opaque, single-choice launch panel over the console."""
    if task is None:
        return
    if task.is_resume and confirmation == 0:
        lines = (
            ("Confirm Resume", "title"),
            ("The console cannot tell whether an agent is still active.", "blocked"),
            (f"Task: {task.task_id} — {task.title}", "text"),
            (f"Directive: {task.launch_command or 'unavailable'}", "text"),
            ("Press y to continue or Esc to cancel. Nothing has started.", "muted"),
        )
    elif task.is_resume and task.active_writer and confirmation == 1:
        lines = (
            ("Confirm dirty worktree", "title"),
            ("This task worktree has uncommitted changes.", "blocked"),
            ("Another agent may still be writing there.", "blocked"),
            (f"Task: {task.task_id} — {task.title}", "text"),
            ("Press y again to continue or Esc to cancel.", "muted"),
        )
    else:
        lines = (
            ("Launch agent", "title"),
            ("This starts an agent that may modify the project.", "blocked"),
            (f"Task: {task.task_id} — {task.title}", "text"),
            (f"Directive: {task.launch_command or 'unavailable'}", "text"),
            (f"Project: {project.name}", "text"),
            (f"1 Claude Code — {defaults['claude'].label}", "text"),
            (f"2 Codex — {defaults['codex'].label}", "text"),
            ("Esc cancels. Nothing has started.", "muted"),
        )
    panel_width = min(width - 4, max(len(value) for value, _ in lines) + 4)
    top = max(3, (height - len(lines) - 2) // 2)
    left = max(2, (width - panel_width) // 2)
    for y in range(top, min(height - 1, top + len(lines) + 2)):
        _fill(screen, y, left, panel_width, palette["base"])
    _put(screen, top, left, "┌" + "─" * (panel_width - 2) + "┐", panel_width, palette["line"])
    for index, (value, style) in enumerate(lines):
        y = top + index + 1
        _put(screen, y, left, "│", 1, palette["line"])
        _put(screen, y, left + 2, value, panel_width - 4, palette[style])
        _put(screen, y, left + panel_width - 1, "│", 1, palette["line"])
    _put(screen, top + len(lines) + 1, left,
         "└" + "─" * (panel_width - 2) + "┘", panel_width, palette["line"])


def run_terminal(screen, state: ConsoleState, interval: float) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    palette = _palette(screen)
    try:
        curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED
                         | getattr(curses, "BUTTON4_PRESSED", 0)
                         | getattr(curses, "BUTTON5_PRESSED", 0))
    except curses.error:
        pass
    screen.timeout(100)
    selected_id: str | None = None
    offset = 0
    detail_offset = 0
    search = ""
    searching = False
    help_visible = False
    detail_open = False
    detail_focused = False
    status_filter = "All"
    last_poll = 0.0
    notice = ""
    notice_until = 0.0
    launch_task: Task | None = None
    launch_confirmation = 0
    while True:
        now = time.monotonic()
        state.apply_pending()
        finished = state.take_launch_result()
        if finished is not None:
            notice, notice_until = finished[1], time.monotonic() + (3 if finished[0] else 5)
        if now - last_poll >= interval and state.start_refresh():
            last_poll = now
        snapshot = state.snapshot
        visible = _visible_tasks(snapshot, status_filter, search)
        if selected_id not in {task.task_id for task in visible}:
            selected_id = visible[0].task_id if visible else None
            detail_offset = 0
        selected_task = next((task for task in visible if task.task_id == selected_id), None)
        height, width = screen.getmaxyx()
        screen.erase()
        action_bounds: tuple[int, int, set[int]] | None = None
        detail_bounds: tuple[int, int] | None = None
        detail_width = 0
        if height < 12 or width < 50:
            _put(screen, 0, 0, "Terminal too small (minimum 50x12). Press q to quit.", width,
                 palette["text"])
        else:
            _draw_header(screen, state, palette, status_filter, width)
            wide = width >= 110
            if help_visible:
                help_lines = (
                    "Navigation", "↑/↓ or j/k  Select task", "Tab/Shift+Tab  Filter by status",
                    "Enter  Open full task details", "Esc  Return to task list",
                    "/  Search task ID or title", "[ / ]  Scroll task details",
                    "c or click [copy]  Copy a permitted task directive",
                    "l  Choose Claude Code or Codex to launch an iTerm2 split pane",
                    "Tab  Cycle All and nonempty states; click any tab",
                    "r  Refresh now", "q  Quit", "",
                    "Project state is read-only; copy writes to the clipboard.",
                    "Updated is the last committed change to the task file.",
                    "Agent activity is unavailable without a verified source.",
                    "Launching uses macOS iTerm2 after selecting an agent.",
                )
                for y, line in enumerate(help_lines, 4):
                    _put(screen, y, 2, line, width - 4, palette["text"] if y == 4 else palette["base"])
            elif detail_open:
                detail_width = width - 4
                detail_bounds = (2, width - 3)
                _, detail_offset, _ = _detail_view(selected_task, detail_width, height, 4,
                                                   detail_offset, palette)
                action_rows = _draw_detail(screen, selected_task, 2, 4, width - 4,
                                           height, detail_offset, palette)
                action_bounds = (2, width - 4, action_rows)
            else:
                left_width = int(width * .68) if wide else width
                offset = _draw_list(screen, visible, selected_id, offset, left_width,
                                    height, palette,
                                    snapshot.tasks if snapshot else ())
                if wide:
                    divider = left_width - 1
                    for y in range(3, height - 2):
                        _put(screen, y, divider, "│", 1, palette["line"])
                    detail_x = left_width + 1
                    detail_width = width - left_width - 2
                    detail_bounds = (detail_x, width - 3)
                    _, detail_offset, _ = _detail_view(selected_task, detail_width, height, 4,
                                                       detail_offset, palette)
                    action_rows = _draw_detail(screen, selected_task, detail_x, 4,
                                               width - left_width - 2, height,
                                               detail_offset, palette)
                    action_bounds = (detail_x, width - 3, action_rows)
            _draw_launch_prompt(screen, width, height, launch_task, launch_confirmation,
                                state.project,
                                state.agent_defaults, palette)
            if notice and time.monotonic() < notice_until:
                footer = notice
            elif state.launching:
                footer = f"Launching {state.launch_target}…"
            elif state.error:
                footer = f"STALE: {state.error}"
            elif searching:
                footer = f"Search: {search}"
            elif detail_open or help_visible:
                footer = "Esc back   [/] scroll   r refresh   q quit"
            else:
                footer = ("? help   ↑/↓ move   [/] scroll detail   tab filter   enter details   "
                          "c copy   l launch   / search   r refresh   q quit")
            _put(screen, height - 2, 0, "─" * max(0, width - 1),
                 width - 1, palette["line"])
            _put(screen, height - 1, 1, footer, width - 2,
                 palette["stale"] if state.error else palette["muted"])
        screen.refresh()
        key = screen.getch()
        if key == -1:
            continue
        if launch_task is not None:
            if key == 27:
                launch_task = None
                notice, notice_until = "Launch cancelled", time.monotonic() + 2
            elif launch_confirmation < launch_task.resume_confirmations:
                if key in (ord("y"), ord("Y")):
                    launch_confirmation += 1
            elif key in (ord("1"), ord("2")):
                selected = "claude" if key == ord("1") else "codex"
                task_to_launch = launch_task
                launch_task = None
                if state.start_launch(
                    task_to_launch, selected,
                    dirty_confirmed=task_to_launch.active_writer and launch_confirmation >= 2,
                ):
                    notice, notice_until = (
                        f"Launching {state.launch_target}…", time.monotonic() + 2)
                else:
                    notice, notice_until = (
                        f"A launch is already pending ({state.launch_target})",
                        time.monotonic() + 3)
            continue
        if key == curses.KEY_MOUSE:
            try:
                _, mouse_x, mouse_y, _, button_state = curses.getmouse()
            except curses.error:
                continue
            wheel_up = getattr(curses, "BUTTON4_PRESSED", 0)
            wheel_down = getattr(curses, "BUTTON5_PRESSED", 0)
            in_detail = bool(detail_bounds and detail_bounds[0] <= mouse_x <= detail_bounds[1])
            if button_state & (wheel_up | wheel_down):
                if selected_task and (detail_open or in_detail) and detail_width:
                    detail_offset = _scroll_detail(
                        selected_task, detail_width, height, 4, detail_offset,
                        -3 if button_state & wheel_up else 3, palette)
                continue
            if not button_state & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):
                continue
            tab = _tab_at(snapshot, mouse_x, mouse_y)
            if tab and not help_visible and not detail_open:
                status_filter = tab
                offset = detail_offset = 0
            elif selected_task and _action_hit(mouse_x, mouse_y, action_bounds):
                command = selected_task.launch_command
                if command:
                    notice = (f"Copied: {command}" if _copy_to_clipboard(command)
                              else "Clipboard unavailable")
                    notice_until = time.monotonic() + 2
            elif in_detail:
                detail_focused = True
            continue
        if searching:
            if key in (10, 13, 27):
                searching = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                search = search[:-1]
                detail_offset = offset = 0
            elif 32 <= key <= 126:
                search += chr(key)
                detail_offset = offset = 0
            continue
        if key == 27:
            detail_open = detail_focused = help_visible = False
            continue
        if key in (ord("q"), ord("Q")):
            return
        scroll_focus = detail_open or detail_focused
        page = max(1, height - 4 - 2)
        if (key in (ord("j"), curses.KEY_DOWN) and scroll_focus and not help_visible
                and selected_task and detail_width):
            detail_offset = _scroll_detail(selected_task, detail_width, height, 4,
                                           detail_offset, 1, palette)
        elif (key in (ord("k"), curses.KEY_UP) and scroll_focus and not help_visible
              and selected_task and detail_width):
            detail_offset = _scroll_detail(selected_task, detail_width, height, 4,
                                           detail_offset, -1, palette)
        elif key == curses.KEY_NPAGE and selected_task and detail_width:
            detail_offset = _scroll_detail(selected_task, detail_width, height, 4,
                                           detail_offset, page, palette)
        elif key == curses.KEY_PPAGE and selected_task and detail_width:
            detail_offset = _scroll_detail(selected_task, detail_width, height, 4,
                                           detail_offset, -page, palette)
        elif key in (ord("j"), curses.KEY_DOWN) and not detail_open and not help_visible:
            if visible:
                index = next((i for i, task in enumerate(visible)
                              if task.task_id == selected_id), 0)
                selected_id = visible[min(index + 1, len(visible) - 1)].task_id
            detail_offset = 0
        elif key in (ord("k"), curses.KEY_UP) and not detail_open and not help_visible:
            if visible:
                index = next((i for i, task in enumerate(visible)
                              if task.task_id == selected_id), 0)
                selected_id = visible[max(0, index - 1)].task_id
            detail_offset = 0
        elif key == ord("["):
            detail_offset = max(0, detail_offset - 1)
        elif key == ord("]") and selected_task and detail_width:
            detail_offset = _scroll_detail(selected_task, detail_width, height, 4,
                                           detail_offset, 1, palette)
        elif key in (9, curses.KEY_BTAB) and not detail_open and not help_visible:
            direction = -1 if key == curses.KEY_BTAB else 1
            status_filter = _cycle_filter(snapshot, status_filter, direction)
            offset = detail_offset = 0
        elif key in (10, 13) and selected_task and not help_visible:
            detail_open = True
            detail_focused = True
            detail_offset = 0
        elif key == ord("/"):
            searching = True
            search = ""
        elif key == ord("r"):
            if state.start_refresh():
                last_poll = time.monotonic()
        elif key == ord("c") and selected_task and not help_visible:
            command = selected_task.launch_command
            notice = (f"Copied: {command}" if command and _copy_to_clipboard(command)
                      else "Clipboard unavailable" if command
                      else "No launch command for this task")
            notice_until = time.monotonic() + 2
        elif key in (ord("l"), ord("L")) and selected_task and not help_visible:
            if state.launching:
                notice, notice_until = (
                    f"A launch is already pending ({state.launch_target})",
                    time.monotonic() + 3)
            elif selected_task.launch_command:
                launch_task = selected_task
                launch_confirmation = 0
            else:
                notice, notice_until = "No eligible directive for this task", time.monotonic() + 2
        elif key == ord("?"):
            help_visible = not help_visible


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--interval", type=float, default=2.0,
                        help="seconds between local refreshes (default: 2)")
    parser.add_argument("--once", action="store_true", help="print one snapshot and exit")
    args = parser.parse_args(argv)
    if not 0.2 <= args.interval <= 60:
        parser.error("--interval must be between 0.2 and 60 seconds")
    state = ConsoleState(args.project)
    if args.once:
        state.refresh()
        print(one_shot(state))
        return 1 if state.error else 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("interactive mode requires a terminal; use --once")
    _set_terminal_title(args.project)
    curses.wrapper(run_terminal, state, args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
