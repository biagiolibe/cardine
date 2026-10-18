#!/usr/bin/env python3
"""Local terminal dashboard for a Meridian project."""

from __future__ import annotations

import argparse
import curses
import re
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.dont_write_bytecode = True
# Resolve package modules from this executable checkout.
if str(Path(__file__).resolve().parents[1] / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.console.launch import (  # noqa: E402
    _agent_defaults,
    _launch_request,
    _set_terminal_title,
    _start_launch,
)
from cardine.console.models import AgentDefaults, FrameworkIdentity, Snapshot, Task  # noqa: E402
from cardine.console.snapshot import (  # noqa: E402
    DeliveryCache,
    IdentityCache,
    load_snapshot,
    load_task,
)
from cardine.shared.console_workflow import ConsoleError  # noqa: E402


def _framework_identity(script_path: Path | None = None) -> FrameworkIdentity:
    """Read this running framework's identity once; identity lookup must not block the console."""
    root = (script_path or Path(__file__)).resolve().parent.parent
    try:
        version = (root / "VERSION").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        version = "unknown"
    return FrameworkIdentity(version or "unknown", root)


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
