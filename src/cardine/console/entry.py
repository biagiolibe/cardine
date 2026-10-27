"""Local terminal dashboard for a Cardine project."""

from __future__ import annotations

from pathlib import Path
import argparse
import curses
import sys
import time

from cardine.console.launch import _set_terminal_title
from cardine.console.models import Task
from cardine.console.render import _action_hit, _copy_to_clipboard, _cycle_filter, _detail_view, _draw_detail, _draw_header, _draw_launch_prompt, _draw_list, _palette, _put, _scroll_detail, _tab_at, _visible_tasks
from cardine.console.state import ConsoleState, one_shot


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
    launch_action = 'run'
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
                                state.agent_defaults, palette, action=launch_action)
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
                          "c copy   l launch   x cancel task   a abort   / search   r refresh   q quit")
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
                    action=launch_action,
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
        if key in (ord('x'), ord('a')) and selected_task and not selected_task.legacy:
            launch_task, launch_confirmation = selected_task, 0
            launch_action = 'cancel' if key == ord('x') else 'abort'
            continue
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
                launch_action = 'run'
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
