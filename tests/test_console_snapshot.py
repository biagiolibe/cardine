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

import test_console_render as render_tests
from test_console_render import FakeScreen

class ProjectConsoleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        (self.project / "tasks").mkdir()
        (self.project / "PROJECT_WORKFLOW.md").write_text("# LEAN_DELIVERY\n", encoding="utf-8")
        (self.project / "tasks" / "001-first.md").write_text(
            "# Task 001\n\n> **ID**: `001`\n\n## Objective\n\nFirst task.\n\n"
            "## Acceptance Criteria\n\n- [ ] First check.\n", encoding="utf-8",
        )
        (self.project / "tasks" / "002-second.md").write_text(
            "# Task 002\n\n> **ID**: `002`\n\n## Objective\n\nSecond task.\n\n"
            "## Acceptance Criteria\n\n- [ ] Second check.\n", encoding="utf-8",
        )

    def write_queue(self, dependency: str = "001", done: bool = True) -> None:
        first_status = "`[x]`" if done else "`[ ]`"
        (self.project / "tasks" / "QUEUE.md").write_text(
            "# Queue\n\n### Phase 1\n\n" + HEADER
            + f"| {first_status} | 001 | First | P2 | — | [001](001-first.md) |\n"
            + f"| `[ ]` | 002 | Second | P2 | {dependency} | [002](002-second.md) |\n",
            encoding="utf-8",
        )

    def snapshot(self) -> owner_console_models.Snapshot:
        with mock.patch.object(owner_console_snapshot, "_git", side_effect=lambda _project, *args: (
            "## main...origin/main\n" if args[0] == "status"
            else "worktree /tmp/task-002\nbranch refs/heads/task-002\n"
        )):
            return owner_console_snapshot.load_snapshot(self.project)

    def test_completed_dependency_is_ready_and_task_details_are_loaded(self) -> None:
        self.write_queue()
        snapshot = self.snapshot()
        self.assertEqual([task.task_id for task in snapshot.tasks], ["002"])
        self.assertEqual(snapshot.tasks[0].readiness, "READY")
        self.assertEqual(snapshot.tasks[0].objective, ("Second task.",))
        self.assertEqual(snapshot.tasks[0].criteria, ("- [ ] Second check.",))
        self.assertEqual(snapshot.tasks[0].worktree, "/tmp/task-002")
        self.assertEqual(snapshot.tasks[0].next_action, "If assigned: Proceed with 002")

    def test_load_task_reads_only_the_addressed_task(self) -> None:
        self.write_queue()
        calls: list[tuple[str, ...]] = []

        def git(_project, *args):
            calls.append(args)
            return "worktree /tmp/task-002\nbranch refs/heads/task-002\n"

        with mock.patch.object(owner_console_snapshot, "_git", side_effect=git):
            task = owner_console_snapshot.load_task(self.project, "002")
            missing = owner_console_snapshot.load_task(self.project, "999")
        self.assertEqual((task.task_id, task.readiness, task.launch_command),
                         ("002", "READY", "Proceed with 002"))
        self.assertIsNone(missing)
        self.assertNotIn("status", [args[0] for args in calls])

    def test_open_and_missing_dependencies_are_not_ready(self) -> None:
        self.write_queue(done=False)
        snapshot = self.snapshot()
        self.assertEqual(snapshot.tasks[1].readiness, "BLOCKED: 001")
        self.write_queue(dependency="999")
        snapshot = self.snapshot()
        self.assertEqual(snapshot.tasks[0].readiness, "UNKNOWN: missing 999")

    def test_refresh_failure_retains_last_valid_snapshot(self) -> None:
        self.write_queue()
        state = owner_console_state.ConsoleState(self.project)
        with mock.patch.object(owner_console_snapshot, "_git", side_effect=lambda _project, *args: (
            "## main\n" if args[0] == "status" else ""
        )):
            state.refresh()
        previous = state.snapshot
        previous_time = state.last_success
        (self.project / "tasks" / "QUEUE.md").unlink()
        state.refresh()
        self.assertIs(state.snapshot, previous)
        self.assertEqual(state.last_success, previous_time)
        self.assertIsNotNone(state.error)

    def test_duplicate_task_id_is_rejected(self) -> None:
        self.write_queue()
        (self.project / "tasks" / "QUEUE_ARCHIVE.md").write_text(
            HEADER + "| `[x]` | 001 | Duplicate | P2 | — | [001](001-first.md) |\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "Duplicate task ID"):
            self.snapshot()

    def test_one_shot_against_fixture_repository(self) -> None:
        self.write_queue()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.project)],
                       capture_output=True, text=True, check=True)
        for archived in (False, True):
            with self.subTest(archived=archived):
                if archived:
                    target = self.project / "tasks/done/002-second.md"
                    target.parent.mkdir()
                    (self.project / "tasks/002-second.md").rename(target)
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "project_console.py"),
                     "--project", str(self.project), "--once"],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("MERIDIAN |", result.stdout)
                self.assertIn("Updated:", result.stdout)
                self.assertIn("Open:", result.stdout)
                self.assertIn("Agent activity: unavailable", result.stdout)

    def test_linked_record_resolves_before_and_after_archival(self) -> None:
        self.write_queue()
        before = self.snapshot()
        archived = self.project / "tasks/done/002-second.md"
        archived.parent.mkdir()
        (self.project / "tasks/002-second.md").rename(archived)
        after = self.snapshot()
        self.assertEqual(before.tasks[0].path, (self.project / "tasks/002-second.md").resolve())
        self.assertEqual(after.tasks[0].path, archived.resolve())
        self.assertIsNone(after.tasks[0].record_problem)
        self.assertEqual(after.tasks[0].objective, before.tasks[0].objective)
        self.assertEqual(after.tasks[0].criteria, before.tasks[0].criteria)
        self.assertEqual(after.tasks[0].readiness, before.tasks[0].readiness)
        self.assertEqual(after.done_count, before.done_count)

    def test_missing_link_target_with_no_record_is_rejected(self) -> None:
        self.write_queue()
        (self.project / "tasks/002-second.md").unlink()
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "Task 002 file is unavailable"):
            self.snapshot()

    def test_missing_link_target_with_multiple_records_is_rejected(self) -> None:
        self.write_queue()
        record = self.project / "tasks/002-second.md"
        for directory in ("done", "copies"):
            target = self.project / "tasks" / directory
            target.mkdir()
            (target / record.name).write_text(record.read_text(), encoding="utf-8")
        record.unlink()
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "Task 002 file is unavailable"):
            self.snapshot()

    def test_same_linked_filename_in_two_task_roots_is_rejected(self) -> None:
        self.write_queue()
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "# LEAN_DELIVERY\n"
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n"
            "Task files live under `docs/tasks/`\n"
            "<!-- MERIDIAN:END -->\n", encoding="utf-8")
        record = self.project / "tasks/002-second.md"
        for root in ("tasks/done", "docs/tasks"):
            target = self.project / root
            target.mkdir(parents=True)
            (target / record.name).write_text(record.read_text(), encoding="utf-8")
        record.unlink()
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "Task 002 file is unavailable"):
            self.snapshot()
        resolver = owner_console_snapshot.RecordResolver(self.project.resolve(),
                                          owner_tasks_identity.resolve_project_locations(self.project))
        path, problem = resolver.find_by_name(record.name)
        self.assertIsNone(path)
        self.assertIn("ambiguous task record:", problem)

    def test_archived_filename_with_wrong_heading_is_rejected(self) -> None:
        self.write_queue()
        record = self.project / "tasks/002-second.md"
        archived = self.project / "tasks/done" / record.name
        archived.parent.mkdir()
        record.rename(archived)
        for heading in ("# Task 003", "# Task 002-other", "# Unrelated"):
            with self.subTest(heading=heading):
                archived.write_text(heading + "\n\n> **ID**: `003`\n", encoding="utf-8")
                with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "Task 002 file is unavailable"):
                    self.snapshot()

    def test_filename_lookup_reuses_scan_and_excludes_non_records(self) -> None:
        self.write_queue()
        record = self.project / "tasks/002-second.md"
        archived = self.project / "tasks/done" / record.name
        archived.parent.mkdir()
        record.rename(archived)
        for directory in ("handoffs", "reviews"):
            target = self.project / "tasks" / directory
            target.mkdir()
            (target / record.name).write_text("# Task 002\n", encoding="utf-8")
        resolver = owner_console_snapshot.RecordResolver(self.project.resolve(),
                                          owner_tasks_identity.resolve_project_locations(self.project))
        with mock.patch.object(owner_console_snapshot.os, "walk", wraps=os.walk) as walk:
            self.assertEqual(resolver.find_by_name(record.name), (archived.resolve(), None))
            self.assertEqual(resolver.find("002"), (None, "task record not found"))
            self.assertEqual(resolver.find_by_name(record.name), (archived.resolve(), None))
        self.assertEqual(walk.call_count, len(resolver.roots))

    def test_unsafe_link_does_not_fall_back_to_matching_record(self) -> None:
        self.write_queue()
        queue = self.project / "tasks/QUEUE.md"
        text = queue.read_text()
        for link, message in (
            ("[002](../../outside.md)", "no unambiguous file link"),
            ("[002](002-second.md) [other](001-first.md)", "no unambiguous file link"),
            ("[002](../other/missing.md)", "unavailable within the project"),
            ("[002](handoffs/missing.md)", "unavailable within the project"),
        ):
            with self.subTest(link=link):
                queue.write_text(text.replace("[002](002-second.md)", link), encoding="utf-8")
                with self.assertRaisesRegex(owner_console_workflow.ConsoleError, message):
                    self.snapshot()

    def test_link_resolving_outside_project_does_not_use_fallback(self) -> None:
        self.write_queue()
        (self.project / "tasks/escape").symlink_to(self.project.parent, target_is_directory=True)
        queue = self.project / "tasks/QUEUE.md"
        queue.write_text(queue.read_text().replace("[002](002-second.md)",
                                                  "[002](escape/missing.md)"), encoding="utf-8")
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "unavailable within the project"):
            self.snapshot()

    def test_elapsed_formatting_is_wall_clock_and_legacy_values_are_unavailable(self) -> None:
        start = "2026-01-01T00:00:00Z"
        now = datetime(2026, 1, 2, 2, 3, 4, tzinfo=owner_console_render.timezone.utc)
        self.assertEqual(owner_console_render._elapsed(start, now), "1d 2h")
        self.assertEqual(owner_console_render._elapsed(None, now), "unavailable")
        self.assertEqual(owner_console_render._elapsed("not-a-timestamp", now), "unavailable")

    def test_lifecycle_progress_covers_each_displayed_phase(self) -> None:
        cases = {
            "C1": "working", "C5": "validation/evidence pending", "C6": "candidate validation",
            "C7": "candidate validation", "C9": "push pending",
        }
        for step, phase in cases.items():
            with self.subTest(step=step):
                self.assertEqual(owner_console_snapshot._lifecycle_progress(step, True)[0], phase)
        self.assertEqual(owner_console_snapshot._lifecycle_progress("C10", True)[0], "cleanup pending")
        self.assertEqual(owner_console_snapshot._lifecycle_progress("C10", False), ("done", ()))

    def test_active_task_one_shot_and_detail_keep_elapsed_and_last_activity_separate(self) -> None:
        task = owner_console_models.Task(
            "001", "Task", "IN_PROGRESS", (), (), None, (), (), readiness="IN PROGRESS",
            lifecycle="in_progress", updated_at=0, started_at="2026-01-01T00:00:00Z",
            progress_phase="working", remaining_gates=("Run task validation",),
        )
        state = owner_console_state.ConsoleState(self.project)
        state.snapshot = owner_console_models.Snapshot(self.project, self.project / "tasks/QUEUE.md", "main", "clean", 0, (task,), 0)
        output = owner_console_state.one_shot(state)
        self.assertIn("Elapsed:", output)
        self.assertIn("Progress: working", output)
        palette = {name: 0 for name in ("base", "text", "title", "ready", "working", "muted", "line", "action", "blocked")}
        lines = [value for value, _ in owner_console_render._detail_lines(task, 80, palette)]
        self.assertTrue(any(value.startswith("Elapsed cycle time:") for value in lines))
        self.assertTrue(any(value.startswith("Last activity:") for value in lines))

    def test_framework_identity_reads_version_and_shortens_a_home_root(self) -> None:
        home = self.project / "home"
        root = home / "framework"
        script = root / "scripts" / "project_console.py"
        script.parent.mkdir(parents=True)
        (root / "VERSION").write_text("9.8.7\n", encoding="utf-8")
        self.write_queue()
        with mock.patch.object(owner_console_models.Path, "home", return_value=home):
            identity = owner_console_state._framework_identity(script)
            self.assertEqual(identity.version, "9.8.7")
            self.assertEqual(identity.root_label, "~/framework")
            state = owner_console_state.ConsoleState(self.project)
            state.framework = identity
            state.snapshot = self.snapshot()
            output = owner_console_state.one_shot(state)
            self.assertTrue(output.startswith("MERIDIAN | v9.8.7 | ~/framework |"))

    def test_framework_identity_missing_version_is_nonfatal(self) -> None:
        identity = owner_console_state._framework_identity(self.project / "framework" / "scripts" / "console.py")
        self.assertEqual(identity.version, "unknown")
        self.assertIn("version unknown", identity.label)
        self.write_queue()
        state = owner_console_state.ConsoleState(self.project)
        state.framework = identity
        state.snapshot = self.snapshot()
        self.assertIn("MERIDIAN | version unknown |", owner_console_state.one_shot(state))

    def test_terminal_title_identifies_console_without_an_absolute_path(self) -> None:
        output = mock.Mock()
        with mock.patch.object(owner_console_launch.sys, "stdout", output):
            owner_console_launch._set_terminal_title(Path("/private/project-name"))
        self.assertIn("Meridian console", output.write.call_args.args[0])
        self.assertIn("project-name", output.write.call_args.args[0])
        self.assertNotIn("/private", output.write.call_args.args[0])

    def test_detail_pane_keeps_the_approved_content_hierarchy(self) -> None:
        self.write_queue()
        task = self.snapshot().tasks[0]
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "muted", "line", "action"
        )}
        lines = [value for value, _ in owner_console_render._detail_lines(task, 40, palette)]
        self.assertEqual(lines[0], "Task details")
        self.assertLess(lines.index("Dependencies"), lines.index("Objective"))
        self.assertLess(lines.index("Objective"), lines.index("Acceptance criteria"))
        self.assertLess(lines.index("Dependencies"), lines.index("Next directive"))
        self.assertIn("- [ ] Second check.", lines)

    def test_detail_sections_accept_governed_headings_and_show_dependency_states(self) -> None:
        self.write_queue()
        task = self.snapshot().tasks[0]
        governed = "# Task\n\n## 🎯 Goal\n\nGoverned goal.\n\n## ✅ Acceptance criteria\n\n- [ ] Done.\n"
        self.assertEqual(owner_console_snapshot._section(governed, "Objective", "Goal"), ("Governed goal.",))
        self.assertEqual(owner_console_snapshot._section(governed, "Acceptance Criteria"), ("- [ ] Done.",))
        detailed = owner_console_models.Task(
            task.task_id, task.title, task.status, task.phase, ("001",), task.path,
            task.objective, task.criteria, readiness=task.readiness,
            dependency_states=(("001", "Done"),),
        )
        palette = {name: 0 for name in ("base", "text", "title", "ready", "muted", "line", "action")}
        lines = [value for value, _ in owner_console_render._detail_lines(detailed, 50, palette)]
        self.assertLess(lines.index("Dependencies"), lines.index("Objective"))
        self.assertIn("001 — Done", lines)

    def test_detail_view_clamps_scroll_across_resize_and_draws_hidden_indicators(self) -> None:
        palette = {name: 0 for name in ("base", "text", "title", "ready", "muted", "line", "action")}
        task = owner_console_models.Task(
            "LONG", "A long task", "[ ]", (), ("001",), None,
            tuple(f"Objective line {number} needs enough text to wrap in narrow panes." for number in range(12)),
            (), readiness="READY", dependency_states=(("001", "Done"),),
        )
        lines, offset, body = owner_console_render._detail_view(task, 32, 14, 4, 999, palette)
        self.assertEqual(offset, len(lines) - body)
        self.assertEqual(owner_console_render._scroll_detail(task, 32, 14, 4, offset, 1, palette), offset)
        self.assertEqual(owner_console_render._scroll_detail(task, 32, 14, 4, offset, -1, palette), offset - 1)
        _, resized, resized_body = owner_console_render._detail_view(task, 72, 28, 4, offset, palette)
        self.assertLessEqual(resized, max(0, len(owner_console_render._detail_view(task, 72, 28, 4, 0, palette)[0]) - resized_body))
        screen = FakeScreen(14, 40)
        owner_console_render._draw_detail(screen, task, 2, 4, 32, 14, offset, palette)
        self.assertIn("more above", "\n".join(screen.row(y) for y in range(4, 12)))

    def test_header_right_aligns_git_and_underlines_active_all_tab(self) -> None:
        self.write_queue()
        state = owner_console_state.ConsoleState(self.project)
        state.framework = owner_console_models.FrameworkIdentity("1.4.0", Path("/fw"))
        state.snapshot = self.snapshot()
        state.last_success = datetime.now().astimezone()
        screen = mock.Mock()
        screen.getmaxyx.return_value = (35, 140)
        palette = {name: 0 for name in (
            "text", "blocked", "stale", "tab", "ready", "working",
            "unknown", "muted", "line", "tab_underline"
        )}
        owner_console_render._draw_header(screen, state, palette, "All", 140)
        writes = [call.args for call in screen.addnstr.call_args_list]
        self.assertTrue(any(y == 0 and x > 70 and "refreshed" in value
                            for y, x, value, *_ in writes))
        self.assertTrue(any(y == 1 and "All 1" in value
                            for y, x, value, *_ in writes))
        self.assertTrue(any(y == 2 and "━" in value
                            for y, x, value, *_ in writes))
        self.assertTrue(any(y == 0 and "v" in value for y, x, value, *_ in writes))

    def test_tab_wraps_through_all_and_empty_tabs_remain_clickable(self) -> None:
        self.write_queue()
        snapshot = self.snapshot()
        self.assertEqual(owner_console_render._cycle_filter(snapshot, "Ready", 1), "All")
        self.assertEqual(owner_console_render._cycle_filter(snapshot, "Ready", -1), "All")
        self.assertEqual(owner_console_render._cycle_filter(snapshot, "All", 1), "Ready")
        self.assertEqual(owner_console_render._tab_at(snapshot, 2, 1), "All")
        self.assertEqual(owner_console_render._tab_at(snapshot, 20, 1), "Working")

    def test_ready_directive_copy_hit_and_clipboard_result(self) -> None:
        self.write_queue()
        task = self.snapshot().tasks[0]
        self.assertEqual(task.launch_command, "Proceed with 002")
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "muted", "line", "action"
        )}
        screen = mock.Mock()
        screen.getmaxyx.return_value = (35, 140)
        rows = owner_console_render._draw_detail(screen, task, 95, 4, 43, 35, 0, palette)
        self.assertTrue(rows)
        self.assertTrue(owner_console_render._action_hit(100, min(rows), (95, 136, rows)))
        self.assertFalse(owner_console_render._action_hit(94, min(rows), (95, 136, rows)))
        with mock.patch.object(owner_console_render.sys, "platform", "darwin"), \
             mock.patch.object(owner_console_render.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(owner_console_render._copy_to_clipboard(task.launch_command))
            run.assert_called_once_with(
                ("pbcopy",), input="Proceed with 002", text=True,
                capture_output=True, check=False, timeout=2,
            )
            run.return_value.returncode = 1
            self.assertFalse(owner_console_render._copy_to_clipboard(task.launch_command))

    def test_new_tabs_are_appended_after_existing_ones(self) -> None:
        self.write_queue()
        snapshot = self.snapshot()
        self.assertEqual(
            tuple(owner_console_render._filter_counts(snapshot)),
            ("Ready", "Working", "Blocked", "Unknown", "Review", "Mismatch", "Closing"),
        )



class LinklessQueueTest(support.RepoCase):
    """A Governed SDD project shaped like consumer project A: no file or review column."""

    lock = "GOVERNED_SDD"
    header = (
        "| Order | ID | Priority | Status | Dependencies | Estimate |\n"
        "|---:|---|---|---|---|---|\n"
    )

    def setUp(self) -> None:
        super().setUp()
        self.write(self.project, ".meridian/task-identity.json",
                   json.dumps({"version": 1, "mode": "milestone"}))
        self.write(self.project, "PROJECT_WORKFLOW.md", (
            f"# {self.lock}\n\n<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n"
            "<!-- MERIDIAN:END -->\n\n"
            "The queue is `docs/TASK_QUEUE.md`. Task files live under "
            "`docs/tasks/<milestone>/<TASK-ID>.md`. Durable review records at "
            "`docs/tasks/reviews/<TASK-ID>.md`. Completion handoffs live at "
            "`tasks/handoffs/<TASK-ID>.md`.\n"
        ))

    def record(self, task_id: str, status: str = "QUEUED", milestone: str = "M37") -> str:
        return (f"docs/tasks/{milestone}/{task_id}.md",
                f"# {task_id} — Title of {task_id}\n\nStatus: {status}\n\n"
                f"## Objective\n\nObjective of {task_id}.\n")

    def setup_project(self, rows: list[tuple[str, str, str]], records: bool = True,
                      header: str | None = None) -> None:
        """Rows are (id, status, dependencies)."""
        body = "# Task Queue\n\n" + (header or self.header) + "".join(
            f"| {index} | {task_id} | P1 | {status} | {deps} | 2h |\n"
            for index, (task_id, status, deps) in enumerate(rows, 1)
        )
        self.write(self.project, "docs/TASK_QUEUE.md", body)
        for task_id, status, _deps in rows if records else ():
            path, text = self.record(task_id, status)
            self.write(self.project, path, text)
        self.commit(self.project, "initial")

    def test_consumer_project_a_shaped_project_lists_every_row_without_stale(self) -> None:
        rows = [
            ("M37-CAUSE-001", "ACCEPTED", "—"), ("M37-CAUSE-002", "QUEUED", "M37-CAUSE-001"),
            ("M37-CAUSE-003", "IN_PROGRESS", "—"), ("M37-CAUSE-004", "READY_FOR_REVIEW", "—"),
            ("M37-SPIKE-001", "ANSWERED", "—"), ("M37-CAUSE-005", "QUEUED", "M37-SPIKE-001"),
        ]
        self.setup_project(rows)
        for task_id, _status, _deps in rows:  # review and handoff records share the ID
            self.write(self.project, f"docs/tasks/reviews/{task_id}.md", "# Review\n")
            self.write(self.project, f"tasks/handoffs/{task_id}.md", "# Handoff\n")
        self.write(self.project, "docs/tasks/M36/notes/handoffs/M37-CAUSE-002.md", "# Stray\n")
        self.commit(self.project, "records")
        state = owner_console_state.ConsoleState(self.project)
        state.refresh()
        self.assertIsNone(state.error)
        self.assertNotIn("STALE", owner_console_state.one_shot(state))
        tasks = {task.task_id: task for task in state.snapshot.tasks}
        self.assertEqual(sorted(tasks), ["M37-CAUSE-002", "M37-CAUSE-003",
                                         "M37-CAUSE-004", "M37-CAUSE-005"])
        self.assertEqual(tasks["M37-CAUSE-002"].path,
                         self.project / "docs/tasks/M37/M37-CAUSE-002.md")
        self.assertEqual(tasks["M37-CAUSE-002"].title, "Title of M37-CAUSE-002")
        self.assertEqual(tasks["M37-CAUSE-002"].objective, ("Objective of M37-CAUSE-002.",))
        self.assertIsNone(tasks["M37-CAUSE-002"].record_problem)
        self.assertEqual(tasks["M37-CAUSE-002"].readiness, "READY")
        self.assertEqual(tasks["M37-CAUSE-002"].launch_command, "Proceed with M37-CAUSE-002")
        self.assertEqual(tasks["M37-CAUSE-005"].readiness, "READY")
        self.assertEqual(state.snapshot.done_count, 2)

    def test_milestone_headings_group_the_rendered_open_list(self) -> None:
        queue = "# Task Queue\n\n## Rules\n\nText only.\n\n## Priority\n\nText only.\n\n"
        counts = {}
        for number in range(1, 38):
            milestone = f"M{number:02}"
            task_id = f"{milestone}-CAUSE-001"
            status = "ACCEPTED" if number == 1 else "QUEUED"
            queue += (f"## {milestone} Queue — Milestone {number}\n\n" + self.header
                      + f"| {number} | {task_id} | P1 | {status} | — | 2h |\n\n")
            self.write(self.project, *self.record(task_id, status, milestone))
            counts[milestone] = 1
        queue += ("## F0 Queue — Presentation track\n\n" + self.header
                  + "| 38 | F0-PRES-001 | P1 | QUEUED | — | 2h |\n"
                  + "| 39 | F0-PRES-002 | P1 | QUEUED | — | 2h |\n")
        for task_id in ("F0-PRES-001", "F0-PRES-002"):
            self.write(self.project, *self.record(task_id, milestone="F0"))
        counts["F0"] = 2
        self.write(self.project, "docs/TASK_QUEUE.md", queue)
        self.commit(self.project, "milestone queue")

        snapshot = owner_console_snapshot.load_snapshot(self.project)
        self.assertEqual(snapshot.done_count, 1)
        self.assertEqual(len(snapshot.tasks), 38)
        grouped = {}
        for task in snapshot.tasks:
            grouped.setdefault(task.phase[0].split()[0], []).append(task.task_id)
        self.assertEqual({name: len(rows) for name, rows in grouped.items()},
                         {name: count for name, count in counts.items() if name != "M01"})

        screen = FakeScreen(100, 110)
        owner_console_render._draw_list(screen, list(snapshot.tasks), snapshot.tasks[0].task_id,
                           0, 110, 100, render_tests.ConsoleListLayoutTest.PALETTE)
        drawn = [screen.row(y).strip() for y in range(5, 85)]
        headings = [line for line in drawn if re.fullmatch(
            r"(?:M\d{2} — Milestone \d+|F0 — Presentation track)", line)]
        self.assertEqual(headings, [f"M{number:02} — Milestone {number}"
                                    for number in range(2, 38)]
                         + ["F0 — Presentation track"])
        self.assertFalse(any("Rules" in line or "Priority" in line or "M01" in line
                             for line in drawn))
        self.assertLess(drawn.index("M37 — Milestone 37"), drawn.index("F0 — Presentation track"))
        self.assertEqual([task.task_id for task in owner_console_render._visible_tasks(
            snapshot, "All", "presentation track")], ["F0-PRES-001", "F0-PRES-002"])

    def test_queue_without_review_column_declares_no_review_policy(self) -> None:
        self.setup_project([("M37-CAUSE-004", "READY_FOR_REVIEW", "—")])
        task = self.load()["M37-CAUSE-004"]
        self.assertIsNone(task.review)
        self.assertEqual((task.readiness, task.lifecycle), ("READY FOR REVIEW", "ready_for_review"))
        self.assertIsNone(task.launch_command)
        self.assertIsNone(task.mismatch)

    def test_task_record_review_values_are_strict(self) -> None:
        for value, expected in (
            ("REQUIRED", "REQUIRED"), (" NOT REQUIRED ", "NOT REQUIRED"),
            ("", None), ("required", None), ("OPTIONAL", None),
        ):
            with self.subTest(value=value):
                self.assertEqual(owner_console_workflow.record_review(f"Review: {value}\n"), expected)
        self.assertIsNone(owner_console_workflow.record_review("Status: READY_FOR_REVIEW\n"))

    def test_branch_task_record_review_required_offers_review(self) -> None:
        self.setup_project([("M37-CAUSE-004", "QUEUED", "—")])
        wt = self.worktree("m37-cause-004")
        queue = (wt / "docs/TASK_QUEUE.md").read_text(encoding="utf-8").replace(
            "QUEUED", "READY_FOR_REVIEW")
        self.write(wt, "docs/TASK_QUEUE.md", queue)
        path, text = self.record("M37-CAUSE-004", "READY_FOR_REVIEW")
        self.write(wt, path, text + "Review: REQUIRED\n")
        self.commit(wt)
        task = self.load()["M37-CAUSE-004"]
        self.assertEqual((task.source, task.review, task.readiness),
                         ("branch m37-cause-004", "REQUIRED", "READY FOR REVIEW"))
        self.assertEqual(task.launch_command, "Review M37-CAUSE-004")
        self.assertEqual(task.next_action, "If assigned: Review M37-CAUSE-004")

    def test_branch_task_record_not_required_uses_queue_mismatch_rule(self) -> None:
        self.setup_project([("M37-CAUSE-004", "QUEUED", "—")])
        wt = self.worktree("m37-cause-004")
        queue = (wt / "docs/TASK_QUEUE.md").read_text(encoding="utf-8").replace(
            "QUEUED", "READY_FOR_REVIEW")
        self.write(wt, "docs/TASK_QUEUE.md", queue)
        path, text = self.record("M37-CAUSE-004", "READY_FOR_REVIEW")
        self.write(wt, path, text + "Review: NOT REQUIRED\n")
        self.commit(wt)
        task = self.load()["M37-CAUSE-004"]
        self.assertEqual(task.review, "NOT REQUIRED")
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("Review NOT REQUIRED", task.mismatch or "")

    def test_review_column_still_gates_review_state(self) -> None:
        header = ("| Order | ID | Priority | Status | Review | Dependencies |\n"
                  "|---:|---|---|---|---|---|\n")
        self.write(self.project, "docs/TASK_QUEUE.md", "# Q\n\n" + header
                   + "| 1 | M37-CAUSE-004 | P1 | READY_FOR_REVIEW | NOT_REQUIRED | — |\n")
        path, text = self.record("M37-CAUSE-004", "READY_FOR_REVIEW")
        self.write(self.project, path, text)
        self.commit(self.project)
        task = self.load()["M37-CAUSE-004"]
        self.assertEqual((task.review, task.readiness), ("NOT_REQUIRED", "MISMATCH"))

    def test_missing_record_is_a_per_task_problem(self) -> None:
        self.setup_project([("M37-CAUSE-001", "QUEUED", "—"), ("M37-CAUSE-002", "QUEUED", "—")],
                           records=False)
        path, text = self.record("M37-CAUSE-002")
        self.write(self.project, path, text)
        self.commit(self.project)
        tasks = self.load()
        missing = tasks["M37-CAUSE-001"]
        self.assertEqual(missing.record_problem, "task record not found")
        self.assertEqual((missing.title, missing.status, missing.objective, missing.updated_at),
                         ("M37-CAUSE-001", "QUEUED", (), None))
        self.assertIsNone(missing.path)
        self.assertIsNone(missing.launch_command)
        self.assertNotEqual(missing.readiness, "READY")
        self.assertEqual(tasks["M37-CAUSE-002"].readiness, "READY")
        palette = {name: 0 for name in (
            "base", "text", "title", "muted", "line", "action", "blocked", "unknown")}
        lines = [value for value, _ in owner_console_render._detail_lines(missing, 60, palette)]
        self.assertIn("Task record not found", lines)
        self.assertIn("Unavailable", lines)
        self.assertNotIn("Proceed with", " ".join(lines))

    def test_duplicate_record_lists_the_paths_and_offers_no_directive(self) -> None:
        self.setup_project([("M37-CAUSE-001", "QUEUED", "—"), ("M37-CAUSE-002", "QUEUED", "—")])
        self.write(self.project, "tasks/M36/M37-CAUSE-001.md", "# Copy\n")
        self.commit(self.project)
        tasks = self.load()
        duplicate = tasks["M37-CAUSE-001"]
        self.assertEqual(
            duplicate.record_problem,
            "ambiguous task record: docs/tasks/M37/M37-CAUSE-001.md, tasks/M36/M37-CAUSE-001.md")
        self.assertIsNone(duplicate.launch_command)
        palette = {name: 0 for name in (
            "base", "text", "title", "muted", "line", "action", "blocked", "unknown")}
        lines = " ".join(value for value, _ in owner_console_render._detail_lines(duplicate, 200, palette))
        self.assertIn("docs/tasks/M37/M37-CAUSE-001.md, tasks/M36/M37-CAUSE-001.md", lines)
        self.assertIn("Record: ambiguous", self.one_shot())
        self.assertEqual(tasks["M37-CAUSE-002"].readiness, "READY")

    def one_shot(self) -> str:
        state = owner_console_state.ConsoleState(self.project)
        state.refresh()
        return owner_console_state.one_shot(state)

    def test_present_but_invalid_link_keeps_its_rejection(self) -> None:
        header = ("| Order | ID | Priority | Status | Dependencies | Task file |\n"
                  "|---:|---|---|---|---|---|\n")
        self.write(self.project, *self.record("M37-CAUSE-001"))
        for cell, message in (("see notes", "no unambiguous file link"),
                              ("[x](../../outside.md)", "no unambiguous file link"),
                              ("[x](other/missing.md)", "unavailable within the project")):
            self.write(self.project, "docs/TASK_QUEUE.md", "# Q\n\n" + header
                       + f"| 1 | M37-CAUSE-001 | P1 | QUEUED | — | {cell} |\n")
            with self.assertRaisesRegex(owner_console_workflow.ConsoleError, message, msg=cell):
                owner_console_snapshot.load_snapshot(self.project)

    def test_link_wins_over_the_search_when_present(self) -> None:
        header = ("| Order | ID | Priority | Status | Dependencies | Task file |\n"
                  "|---:|---|---|---|---|---|\n")
        self.write(self.project, "docs/TASK_QUEUE.md", "# Q\n\n" + header
                   + "| 1 | M37-CAUSE-001 | P1 | QUEUED | — | [t](tasks/M37/M37-CAUSE-001.md) |\n")
        self.write(self.project, "docs/tasks/M37/M37-CAUSE-001.md",
                   "# M37-CAUSE-001 — Linked\n\nStatus: QUEUED\n")
        self.commit(self.project)
        task = self.load()["M37-CAUSE-001"]
        self.assertEqual((task.title, task.record_problem), ("Linked", None))

    def test_record_is_read_from_the_task_branch_without_links(self) -> None:
        self.setup_project([("M37-CAUSE-001", "QUEUED", "—")])
        queue_path = self.project / "docs/TASK_QUEUE.md"
        queue_path.write_text(queue_path.read_text(encoding="utf-8").replace(
            "# Task Queue\n\n", "# Task Queue\n\n## M37 Queue — Main group\n\n"),
            encoding="utf-8")
        self.commit(self.project, "main group")
        wt = self.worktree("m37-cause-001")
        queue = (wt / "docs/TASK_QUEUE.md").read_text(encoding="utf-8").replace(
            "QUEUED", "IN_PROGRESS").replace("Main group", "Branch group")
        self.write(wt, "docs/TASK_QUEUE.md", queue)
        path, text = self.record("M37-CAUSE-001", "IN_PROGRESS")
        self.write(wt, path, text.replace("Objective of", "Branch objective of"))
        self.commit(wt)
        before = self.refs_and_status()
        task = self.load()["M37-CAUSE-001"]
        self.assertEqual(self.refs_and_status(), before)
        self.assertEqual((task.source, task.readiness), ("branch m37-cause-001", "IN PROGRESS"))
        self.assertIsNone(task.record_problem)
        self.assertEqual(task.objective, ("Branch objective of M37-CAUSE-001.",))
        self.assertEqual(task.path, self.project / path)
        self.assertIsNotNone(task.updated_at)
        self.assertEqual(task.phase, ("M37 Queue — Main group",))

    def test_branch_record_state_is_used_when_the_queue_has_no_links(self) -> None:
        self.setup_project([("M37-CAUSE-004", "QUEUED", "—")])
        wt = self.worktree("m37-cause-004")
        queue = (wt / "docs/TASK_QUEUE.md").read_text(encoding="utf-8").replace(
            "QUEUED", "READY_FOR_REVIEW")
        self.write(wt, "docs/TASK_QUEUE.md", queue)
        self.write(wt, *self.record("M37-CAUSE-004", "READY_FOR_REVIEW"))
        self.commit(wt)
        task = self.load()["M37-CAUSE-004"]
        self.assertEqual((task.source, task.readiness, task.mismatch),
                         ("branch m37-cause-004", "READY FOR REVIEW", None))

    def test_branch_that_moved_the_record_is_resolved_in_its_own_tree(self) -> None:
        self.setup_project([("M37-CAUSE-004", "QUEUED", "—")])
        wt = self.worktree("m37-cause-004")
        queue = (wt / "docs/TASK_QUEUE.md").read_text(encoding="utf-8").replace(
            "QUEUED", "READY_FOR_REVIEW")
        self.write(wt, "docs/TASK_QUEUE.md", queue)
        self.git(wt, "rm", "-q", "docs/tasks/M37/M37-CAUSE-004.md")
        self.write(wt, *self.record("M37-CAUSE-004", "READY_FOR_REVIEW", milestone="M38"))
        self.commit(wt)
        task = self.load()["M37-CAUSE-004"]
        self.assertEqual((task.source, task.readiness, task.mismatch),
                         ("branch m37-cause-004", "READY FOR REVIEW", None))
        self.assertEqual(task.path, self.project / "docs/tasks/M37/M37-CAUSE-004.md")

    def test_record_resolution_adds_no_per_task_subprocess_work(self) -> None:
        def calls(count: int, linked: bool) -> int:
            names = [f"M37-CAUSE-{n:03}" for n in range(count)]
            header = ("| Order | ID | Priority | Status | Dependencies | Task file |\n"
                      "|---:|---|---|---|---|---|\n") if linked else None
            self.setup_project([(name, "QUEUED", "—") for name in names], header=header)
            if linked:
                rows = "".join(
                    f"| {n} | {name} | P1 | QUEUED | — | [t](tasks/M37/{name}.md) |\n"
                    for n, name in enumerate(names, 1))
                self.write(self.project, "docs/TASK_QUEUE.md", "# Q\n\n" + header + rows)
                self.commit(self.project, "links")
            seen: list[list[str]] = []
            real = subprocess.run

            def counting(command, *args, **kwargs):
                seen.append(list(command))
                return real(command, *args, **kwargs)

            with mock.patch.object(subprocess, "run", side_effect=counting):
                owner_console_snapshot.load_snapshot(self.project, owner_console_snapshot.IdentityCache())
            return len(seen)

        for count in (2, 12):
            self.assertEqual(calls(count, linked=False), calls(count, linked=True), count)



class RefreshCostTest(support.RepoCase):
    """The cost of a refresh must not grow with the number of known tasks."""

    queue = support.LeanEffectiveStateFixture.queue
    setup_project = support.LeanEffectiveStateFixture.setup_project

    def setup_with_history(self, archived: int) -> None:
        self.setup_project({"001": " ", "002": " "})
        queue = (self.project / "tasks/QUEUE.md").read_text(encoding="utf-8")
        history = "".join(f"| `[x]` | {100 + n} | Done {n} | P2 | — | — |\n" for n in range(archived))
        self.write(self.project, "tasks/QUEUE.md", queue + history)
        self.commit(self.project, "history")

    def subprocess_calls(self, cache: owner_console_snapshot.IdentityCache | None) -> list[list[str]]:
        real = subprocess.run
        calls: list[list[str]] = []

        def counting(command, *args, **kwargs):
            calls.append(list(command))
            return real(command, *args, **kwargs)

        with mock.patch.object(subprocess, "run", side_effect=counting):
            owner_console_snapshot.load_snapshot(self.project, cache)
        return calls

    def test_subprocess_work_does_not_grow_with_known_tasks(self) -> None:
        self.setup_with_history(2)
        small = self.subprocess_calls(owner_console_snapshot.IdentityCache())
        self.setup_with_history(40)
        large = self.subprocess_calls(owner_console_snapshot.IdentityCache())
        self.assertEqual(len(small), len(large))
        checks = [call for call in large if "check-ref-format" in call]
        self.assertEqual(len(checks), 2, "one ref check per open task")

    def test_refresh_reads_worktree_queue_only_for_dirty_worktrees(self) -> None:
        statuses = {f"{number:03}": " " for number in range(1, 6)}
        self.setup_project(statuses)
        worktrees = {task_id: self.worktree(f"task-{task_id}") for task_id in statuses}
        self.write(worktrees["001"], "scratch.txt", "uncommitted")
        reads: list[Path] = []
        original = owner_console_snapshot._read_text

        def observing(path: Path) -> str:
            reads.append(path)
            return original(path)

        with mock.patch.object(owner_console_snapshot, "_read_text", side_effect=observing):
            owner_console_snapshot.load_snapshot(self.project, owner_console_snapshot.IdentityCache())
        self.assertIn(worktrees["001"] / "tasks/QUEUE.md", reads)
        for task_id, worktree in worktrees.items():
            if task_id != "001":
                self.assertNotIn(worktree / "tasks/QUEUE.md", reads)

    def test_warm_refresh_resolves_no_identity_and_spawns_no_ref_check(self) -> None:
        self.setup_with_history(5)
        cache = owner_console_snapshot.IdentityCache()
        self.subprocess_calls(cache)
        warm = self.subprocess_calls(cache)
        self.assertEqual([call for call in warm if "check-ref-format" in call], [])

    def test_identity_is_resolved_once_until_the_declaration_changes(self) -> None:
        self.setup_with_history(1)
        cache = owner_console_snapshot.IdentityCache()
        with mock.patch.object(owner_console_snapshot, "resolve_task_identity",
                               wraps=owner_console_snapshot.resolve_task_identity) as resolver:
            owner_console_snapshot.load_snapshot(self.project, cache)
            owner_console_snapshot.load_snapshot(self.project, cache)
            self.assertEqual(resolver.call_count, 2)
            self.write(self.project, ".meridian/task-identity.json",
                       json.dumps({"version": 1, "mode": "opaque"}))
            owner_console_snapshot.load_snapshot(self.project, cache)
            self.assertEqual(resolver.call_count, 4)
            owner_console_snapshot.load_snapshot(self.project, cache)
            self.assertEqual(resolver.call_count, 4)

    def test_failed_resolution_is_not_cached(self) -> None:
        cache = owner_console_snapshot.IdentityCache()
        self.setup_with_history(1)
        with self.assertRaises(owner_shared_errors.CardineError):
            cache.resolve(self.project, "999")
        self.write(self.project, "tasks/999-task.md", "# Task 999\n\n> **ID**: `999`\n")
        self.assertEqual(cache.resolve(self.project, "999").canonical_id, "999")



class SnapshotCostTest(support.RepoCase):
    """One worktree listing, resolved identities, and cached delivery gates."""

    lock = "GOVERNED_SDD"
    header = support.GovernedEffectiveStateFixture.header
    setup_project = support.GovernedEffectiveStateFixture.setup_project
    write_record = support.GovernedEffectiveStateFixture.write_record
    state = support.MachineStateConsoleFixture.state

    def populate(self) -> dict[str, Path]:
        """An in-progress, a review-ready, and a closing task, each with a worktree."""
        self.setup_project([
            ("TASK-001", "QUEUED", "REQUIRED", "—"),
            ("TASK-002", "QUEUED", "REQUIRED", "—"),
            ("TASK-003", "ACCEPTED", "REQUIRED", "—"),
        ])
        trees = {task_id: self.worktree(task_id.lower()) for task_id in
                 ("TASK-001", "TASK-002", "TASK-003")}
        self.state(trees["TASK-001"], "TASK-001", "IN_PROGRESS")
        self.state(trees["TASK-002"], "TASK-002", "READY_FOR_REVIEW")
        self.state(trees["TASK-003"], "TASK-003", "ACCEPTED", verdict="APPROVE")
        for wt in trees.values():
            self.commit(wt)
        return trees

    def run_snapshot(self, *loaders) -> list[list[str]]:
        real = subprocess.run
        calls: list[list[str]] = []

        def counting(command, *args, **kwargs):
            calls.append(list(command))
            return real(command, *args, **kwargs)

        with mock.patch.object(subprocess, "run", side_effect=counting), \
             mock.patch.object(Path, "cwd", return_value=self.project):
            for load in loaders:
                load()
        return calls

    @staticmethod
    def listings(calls: list[list[str]]) -> list[list[str]]:
        return [call for call in calls if call[-3:] == ["worktree", "list", "--porcelain"]]

    def test_worktrees_are_listed_once_per_snapshot(self) -> None:
        self.populate()
        calls = self.run_snapshot(lambda: owner_console_snapshot.load_snapshot(self.project))
        self.assertEqual(len(self.listings(calls)), 1)
        task = owner_console_snapshot.load_task(self.project, "TASK-003")
        self.assertIsNotNone(task)
        self.assertEqual(len(self.listings(self.run_snapshot(
            lambda: owner_console_snapshot.load_task(self.project, "TASK-003")))), 1)

    def test_closure_readers_receive_the_cached_identity(self) -> None:
        self.populate()
        cache = owner_console_snapshot.IdentityCache()
        seen: dict[str, list[object]] = {"closure": [], "started": []}
        real_closure = owner_console_snapshot.closure_status
        real_started = owner_console_snapshot.lifecycle_started_at

        def closure(*args, **kwargs):
            seen["closure"].append(kwargs.get("identity"))
            return real_closure(*args, **kwargs)

        def started(*args, **kwargs):
            seen["started"].append(kwargs.get("identity"))
            return real_started(*args, **kwargs)

        with mock.patch.object(owner_console_snapshot, "closure_status", side_effect=closure), \
             mock.patch.object(owner_console_snapshot, "lifecycle_started_at", side_effect=started), \
             mock.patch.object(Path, "cwd", return_value=self.project):
            owner_console_snapshot.load_snapshot(self.project, cache)
        for readers in seen.values():
            self.assertTrue(readers)
            for identity in readers:
                self.assertIsNotNone(identity)
                self.assertIs(identity, cache.resolve(self.project, identity.canonical_id))

    def test_lifecycle_readers_skip_resolution_when_given_an_identity(self) -> None:
        import cardine_cli
        from cardine.worktree import closure_status as owner_worktree_closure_status
        import cardine.shared.errors as shared_errors
        self.populate()
        identity = owner_tasks_identity.resolve_task_identity(self.project, "TASK-001", "existing")
        with mock.patch.object(Path, "cwd", return_value=self.project), \
             mock.patch.object(owner_worktree_closure_status, "resolve_task_identity",
                               side_effect=AssertionError("resolved again")), \
             mock.patch.object(owner_worktree_storage, "resolve_task_identity",
                               side_effect=AssertionError("resolved again")):
            report, _ready = owner_worktree_closure_status.closure_status(
                "TASK-001", None, self.project, identity=identity)
            self.assertEqual(report["task_id"], "TASK-001")
            # No lifecycle state was prepared, so the read ends on that, not on resolution.
            with self.assertRaisesRegex(shared_errors.CardineError, "worktree lifecycle state"):
                owner_worktree_storage.lifecycle_started_at("TASK-001", self.project, identity=identity)

    def test_snapshot_is_identical_with_and_without_caches(self) -> None:
        self.populate()
        with mock.patch.object(Path, "cwd", return_value=self.project):
            plain = owner_console_snapshot.load_snapshot(self.project)
            identities, deliveries = owner_console_snapshot.IdentityCache(), owner_console_snapshot.DeliveryCache()
            cold = owner_console_snapshot.load_snapshot(self.project, identities, deliveries)
            warm = owner_console_snapshot.load_snapshot(self.project, identities, deliveries)
        self.assertEqual({task.task_id for task in plain.tasks}, {"TASK-001", "TASK-002", "TASK-003"})
        self.assertEqual(plain, cold)
        self.assertEqual(plain, warm)

    def review_ready(self) -> tuple[Path, owner_console_snapshot.DeliveryCache, mock.Mock]:
        wt = self.populate()["TASK-002"]
        gate = mock.Mock(side_effect=owner_shared_errors.CardineError("evidence is incomplete"))
        return wt, owner_console_snapshot.DeliveryCache(), gate

    def load_with(self, deliveries: owner_console_snapshot.DeliveryCache, gate: mock.Mock) -> owner_console_models.Task:
        with mock.patch.object(owner_console_snapshot, "delivery_readiness", gate), \
             mock.patch.object(Path, "cwd", return_value=self.project):
            snapshot = owner_console_snapshot.load_snapshot(self.project, owner_console_snapshot.IdentityCache(), deliveries)
        return next(task for task in snapshot.tasks if task.task_id == "TASK-002")

    def test_unchanged_review_ready_task_is_not_rechecked(self) -> None:
        _wt, deliveries, gate = self.review_ready()
        first = self.load_with(deliveries, gate)
        second = self.load_with(deliveries, gate)
        self.assertEqual(gate.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(second.readiness, "PENDING DELIVERY/CHANGES")
        self.assertEqual(second.delivery_pending, "evidence is incomplete")

    def test_success_is_cached_and_a_changed_input_discards_it(self) -> None:
        wt, deliveries, gate = self.review_ready()
        gate.side_effect = None
        gate.return_value = {"status": "READY_FOR_REVIEW"}
        task = self.load_with(deliveries, gate)
        self.assertIsNone(task.delivery_pending)
        self.load_with(deliveries, gate)
        self.assertEqual(gate.call_count, 1)
        gate.side_effect = owner_shared_errors.CardineError("handoff changed")
        self.write(wt, "tasks/handoffs/TASK-002.md", "# Handoff\n")
        self.commit(wt)
        self.assertEqual(self.load_with(deliveries, gate).delivery_pending, "handoff changed")
        self.assertEqual(gate.call_count, 2)

    def test_each_cache_input_invalidates_the_entry(self) -> None:
        wt, deliveries, gate = self.review_ready()
        self.load_with(deliveries, gate)
        calls = 1

        def assert_rechecked(label: str) -> None:
            nonlocal calls
            self.load_with(deliveries, gate)
            calls += 1
            self.assertEqual(gate.call_count, calls, label)
            self.load_with(deliveries, gate)
            self.assertEqual(gate.call_count, calls, f"{label}: settled")

        self.load_with(deliveries, gate)
        self.assertEqual(gate.call_count, 1, "unchanged inputs stay cached")
        self.write(wt, "src.txt", "next\n")
        self.commit(wt)
        assert_rechecked("worktree HEAD")
        self.write(wt, "tasks/handoffs/TASK-002.md", "# Handoff\n")
        self.commit(wt)
        assert_rechecked("handoff added")
        for relative, label in (("tasks/handoffs/TASK-002.md", "handoff stat"),
                                (".meridian/tasks/TASK-002.json", "state file stat")):
            os.utime(wt / relative, ns=(1_000_000_000, 2_000_000_000 + calls))
            assert_rechecked(label)
        self.write(self.project, "main.txt", "main moved\n")
        self.commit(self.project)
        assert_rechecked("main commit")
        self.write(self.project, ".git/meridian-integration.lock", "held\n")
        assert_rechecked("lifecycle file")

    def test_dirty_worktree_is_checked_every_refresh(self) -> None:
        wt, deliveries, gate = self.review_ready()
        self.write(wt, "scratch.txt", "uncommitted\n")
        self.load_with(deliveries, gate)
        self.load_with(deliveries, gate)
        self.assertEqual(gate.call_count, 2)



if __name__ == "__main__":
    unittest.main()
