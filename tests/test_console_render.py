"""Read-only project console snapshot and output tests."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from cardine.console import state as owner_console_state
from cardine.console import render as owner_console_render
from cardine.console import entry as owner_console_entry
from cardine.console import launch as owner_console_launch
from cardine.console import models as owner_console_models
from cardine.console import snapshot as owner_console_snapshot
from cardine.shared import console_workflow as owner_console_workflow
from cardine.shared import errors as owner_shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage


from console_support import HEADER, RESUME_001
import console_support as support

class FakeScreen:
    """Records what curses would draw, as a character grid read back by row."""

    def __init__(self, height: int, width: int) -> None:
        self.height, self.width = height, width
        self.rows = [[" "] * width for _ in range(height)]

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def addnstr(self, y: int, x: int, value: str, count: int, attr: int = 0) -> None:
        for offset, char in enumerate(value[:count]):
            self.rows[y][x + offset] = char

    def row(self, y: int) -> str:
        return "".join(self.rows[y])



class ConsoleListLayoutTest(unittest.TestCase):
    PALETTE = {name: 0 for name in (
        "base", "text", "title", "ready", "muted", "line", "action", "selected",
        "working", "blocked", "unknown",
    )}

    @staticmethod
    def task(task_id: str, title: str = "Title") -> owner_console_models.Task:
        return owner_console_models.Task(task_id, title, "[ ]", ("Phase 1",), (), None, (), (),
                            readiness="READY")

    def render(self, tasks, width: int, all_tasks=None):
        screen = FakeScreen(20, width)
        owner_console_render._draw_list(screen, list(tasks), tasks[0].task_id, 0, width, 20,
                           self.PALETTE, all_tasks)
        return screen

    def test_columns_follow_the_longest_id_for_3_8_13_and_18_characters(self) -> None:
        for length in (3, 8, 13, 18):
            with self.subTest(length=length):
                task_id = "X" * (length - 1) + "1"
                tasks = [self.task("001"), self.task(task_id, "Visible title")]
                screen = self.render(tasks, 110)
                layout = owner_console_render._list_layout(tasks, 110)
                self.assertEqual(layout.id_width, length)
                self.assertEqual(layout.title_x, 3 + length + 1)
                row = screen.row(7)
                self.assertEqual(row[3:3 + length], task_id)
                self.assertEqual(row[layout.title_x:layout.title_x + 15], "○ Visible title")
                self.assertEqual(row[layout.status_x:layout.status_x + 5], "Ready")
                self.assertEqual(screen.row(3)[layout.status_x:layout.status_x + 6], "Status")
                self.assertEqual(screen.row(3)[layout.age_x:layout.age_x + 7], "Updated")

    def test_two_level_groups_render_once_and_search_both_labels(self) -> None:
        queue = ("# Queue\n\n## Program Queue\n\n### Phase 1\n\n" + HEADER
                 + "| `[ ]` | 001 | First | P2 | — | — |\n"
                 + "| `[ ]` | 002 | Second | P2 | — | — |\n\n"
                 + "### Phase 2\n\n" + HEADER
                 + "| `[ ]` | 003 | Third | P2 | — | — |\n")
        rows = owner_console_workflow.parse_queue(queue, "fixture", owner_console_workflow.PROFILES["single"])
        tasks = [
            owner_console_models.Task(row.task_id, row.title, row.status, row.section,
                         (), None, (), (), readiness="READY")
            for row in rows
        ]
        screen = self.render(tasks, 100)
        drawn = [screen.row(y).strip() for y in range(5, 12)]
        self.assertEqual(drawn[0], "Program")
        self.assertEqual(drawn[1], "Phase 1")
        self.assertIn("001", drawn[2])
        self.assertIn("002", drawn[3])
        self.assertEqual(drawn[4], "Phase 2")
        self.assertIn("003", drawn[5])
        self.assertEqual(sum(line == "Program" for line in drawn), 1)
        snapshot = owner_console_models.Snapshot(Path("/p"), Path("/p/q"), "main", "clean", 0,
                                    tuple(tasks), 0)
        self.assertEqual([task.task_id for task in owner_console_render._visible_tasks(snapshot, "All", "program")],
                         ["001", "002", "003"])
        self.assertEqual([task.task_id for task in owner_console_render._visible_tasks(snapshot, "All", "phase 2")],
                         ["003"])

    def test_lean_active_queue_wrapper_keeps_phase_only_rendering(self) -> None:
        queue = ("# Queue\n\n## 🏃 Active Queue\n\n### Phase 29 — Work\n\n"
                 + HEADER + "| `[ ]` | 001 | First | P2 | — | — |\n")
        row = owner_console_workflow.parse_queue(queue, "fixture", owner_console_workflow.PROFILES["single"])[0]
        self.assertEqual(row.section, ("Phase 29 — Work",))
        task = owner_console_models.Task(row.task_id, row.title, row.status, row.section,
                            (), None, (), (), readiness="READY")
        screen = self.render([task], 100)
        self.assertEqual(screen.row(5).strip(), "Phase 29 — Work")
        self.assertNotIn("Active Queue", " ".join(screen.row(y) for y in range(5, 8)))

    def test_queue_heading_levels_two_through_six_render(self) -> None:
        for level in range(2, 7):
            with self.subTest(level=level):
                label = f"Level {level} Queue — Work"
                queue = (f"# Queue\n\n{'#' * level} {label}\n\n" + HEADER
                         + "| `[ ]` | 001 | First | P2 | — | — |\n")
                row = owner_console_workflow.parse_queue(queue, "fixture", owner_console_workflow.PROFILES["single"])[0]
                task = owner_console_models.Task(row.task_id, row.title, row.status, row.section,
                                    (), None, (), (), readiness="READY")
                self.assertEqual(row.section, (label,))
                self.assertEqual(self.render([task], 100).row(5).strip(),
                                 f"Level {level} — Work")

    def test_three_character_ids_keep_their_position_with_actual_width(self) -> None:
        tasks = [self.task("075"), self.task("076")]
        layout = owner_console_render._list_layout(tasks, 110)
        self.assertEqual((layout.id_x, layout.id_width, layout.title_x), (3, 3, 7))
        self.assertEqual(self.render(tasks, 110).row(6)[1], "›")

    def test_id_is_capped_clipped_and_never_overlaps_title_or_status(self) -> None:
        long_id = "M20-EVENT-002-CORR"
        tasks = [self.task(long_id, "Title")]
        self.assertTrue(owner_console_render._list_layout(tasks, 50).id_width < len(long_id))
        for width in (50, 60, 74, 110):
            with self.subTest(width=width):
                layout = owner_console_render._list_layout(tasks, width)
                self.assertLessEqual(layout.id_width, width // 3)
                self.assertGreaterEqual(layout.title_width, owner_console_render.LIST_MIN_TITLE_WIDTH)
                self.assertLessEqual(layout.title_x + layout.title_width + 2, layout.status_x)
                row = self.render(tasks, width).row(6)
                shown = row[3:3 + layout.id_width]
                self.assertEqual(shown, owner_console_render._clip(long_id, layout.id_width))
                self.assertEqual(shown.endswith("…"), layout.id_width < len(long_id))
                self.assertEqual(row[3 + layout.id_width], " ")
                self.assertTrue(row[layout.title_x:].startswith("○ "))

    def test_filtering_does_not_move_columns(self) -> None:
        everything = [self.task("001"), self.task("M20-EVENT-002")]
        full = owner_console_render._list_layout(everything, 110)
        filtered = self.render(everything[:1], 110, everything)
        self.assertEqual(filtered.row(6)[3:6], "001")
        self.assertEqual(filtered.row(6)[full.title_x:full.title_x + 7], "○ Title")
        self.assertEqual(filtered.row(3)[full.status_x:full.status_x + 6], "Status")
        self.assertNotEqual(full, owner_console_render._list_layout(everything[:1], 110))

    def test_full_id_is_in_detail_copy_directive_and_one_shot(self) -> None:
        task = self.task("M20-EVENT-002-CORR")
        lines = [value for value, _ in owner_console_render._detail_lines(task, 60, self.PALETTE)]
        self.assertIn("Task M20-EVENT-002-CORR", lines)
        self.assertEqual(task.launch_command, "Proceed with M20-EVENT-002-CORR")
        state = owner_console_state.ConsoleState(Path("."))
        state.snapshot = owner_console_models.Snapshot(
            Path("."), Path("tasks/QUEUE.md"), "main", "clean", 0, (task,), 0,
        )
        state.last_success = datetime.now().astimezone()
        self.assertIn("M20-EVENT-002-CORR [READY] Title", owner_console_state.one_shot(state))



if __name__ == "__main__":
    unittest.main()
