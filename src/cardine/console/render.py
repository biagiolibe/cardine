"""Local terminal dashboard for a Meridian project."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
import curses
import re
import subprocess
import sys
import textwrap
import time

from cardine.console.models import AgentDefaults, FrameworkIdentity, Snapshot, Task


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
