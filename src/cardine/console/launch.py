"""Agent launch support for the console."""

from __future__ import annotations

from cardine.console.snapshot import load_task, IdentityCache
from cardine.shared.console_workflow import ConsoleError

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from cardine.console.models import AgentDefaults, LaunchRequest, Task
from cardine.console.snapshot import _primary_checkout
from cardine.shared.console_workflow import ID_PATTERN


UUID_PATTERN = (r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


ITERM_SESSION_ID_PATTERN = re.compile(r"w\d+t\d+p\d+:(" + UUID_PATTERN + r")")


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
        sys.stdout.write(f"\033]0;Cardine console — {project.name}\007")
        sys.stdout.flush()
    except OSError:
        pass


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
        "if targetSession is missing value then error \"CARDINE_SESSION_NOT_FOUND\"",
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
        if "CARDINE_SESSION_NOT_FOUND" in detail:
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
