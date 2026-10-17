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
sys.path.insert(0, str(ROOT / "scripts"))
import project_console as console  # noqa: E402


HEADER = (
    "| Status | ID | Title | Priority | Depends on | File |\n"
    "|--------|----|-------|----------|------------|------|\n"
)

ITERM2_DICTIONARY_PROBE = (
    'tell application "iTerm2" to get unique id of current session of current tab of current window'
)


def _compile_applescript(script: str, output: Path) -> subprocess.CompletedProcess[str]:
    """Compile an AppleScript using the same isolated output handling for each check."""
    return subprocess.run(
        ("osacompile", "-o", str(output), "-e", script),
        capture_output=True, text=True, check=False, timeout=30,
    )


def _osacompile_can_resolve_iterm2_dictionary() -> tuple[bool, str]:
    """Probe whether osacompile can resolve the iTerm2 dictionary used by the payload."""
    with tempfile.TemporaryDirectory() as directory:
        try:
            result = _compile_applescript(ITERM2_DICTIONARY_PROBE, Path(directory) / "probe.scpt")
        except subprocess.TimeoutExpired:
            return False, "timed out"
    if result.returncode:
        return False, result.stderr
    return True, ""


RESUME_001 = "Proceed with 001 (Resume: run meridian worktree prepare 001 --resume --format json)"


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

    def snapshot(self) -> console.Snapshot:
        with mock.patch.object(console, "_git", side_effect=lambda _project, *args: (
            "## main...origin/main\n" if args[0] == "status"
            else "worktree /tmp/task-002\nbranch refs/heads/task-002\n"
        )):
            return console.load_snapshot(self.project)

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

        with mock.patch.object(console, "_git", side_effect=git):
            task = console.load_task(self.project, "002")
            missing = console.load_task(self.project, "999")
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
        state = console.ConsoleState(self.project)
        with mock.patch.object(console, "_git", side_effect=lambda _project, *args: (
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
        with self.assertRaisesRegex(console.ConsoleError, "Duplicate task ID"):
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
        with self.assertRaisesRegex(console.ConsoleError, "Task 002 file is unavailable"):
            self.snapshot()

    def test_missing_link_target_with_multiple_records_is_rejected(self) -> None:
        self.write_queue()
        record = self.project / "tasks/002-second.md"
        for directory in ("done", "copies"):
            target = self.project / "tasks" / directory
            target.mkdir()
            (target / record.name).write_text(record.read_text(), encoding="utf-8")
        record.unlink()
        with self.assertRaisesRegex(console.ConsoleError, "Task 002 file is unavailable"):
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
        with self.assertRaisesRegex(console.ConsoleError, "Task 002 file is unavailable"):
            self.snapshot()
        resolver = console.RecordResolver(self.project.resolve(),
                                          console.resolve_project_locations(self.project))
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
                with self.assertRaisesRegex(console.ConsoleError, "Task 002 file is unavailable"):
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
        resolver = console.RecordResolver(self.project.resolve(),
                                          console.resolve_project_locations(self.project))
        with mock.patch.object(console.os, "walk", wraps=os.walk) as walk:
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
                with self.assertRaisesRegex(console.ConsoleError, message):
                    self.snapshot()

    def test_link_resolving_outside_project_does_not_use_fallback(self) -> None:
        self.write_queue()
        (self.project / "tasks/escape").symlink_to(self.project.parent, target_is_directory=True)
        queue = self.project / "tasks/QUEUE.md"
        queue.write_text(queue.read_text().replace("[002](002-second.md)",
                                                  "[002](escape/missing.md)"), encoding="utf-8")
        with self.assertRaisesRegex(console.ConsoleError, "unavailable within the project"):
            self.snapshot()

    def test_elapsed_formatting_is_wall_clock_and_legacy_values_are_unavailable(self) -> None:
        start = "2026-01-01T00:00:00Z"
        now = datetime(2026, 1, 2, 2, 3, 4, tzinfo=console.timezone.utc)
        self.assertEqual(console._elapsed(start, now), "1d 2h")
        self.assertEqual(console._elapsed(None, now), "unavailable")
        self.assertEqual(console._elapsed("not-a-timestamp", now), "unavailable")

    def test_lifecycle_progress_covers_each_displayed_phase(self) -> None:
        cases = {
            "C1": "working", "C5": "validation/evidence pending", "C6": "candidate validation",
            "C7": "candidate validation", "C9": "push pending",
        }
        for step, phase in cases.items():
            with self.subTest(step=step):
                self.assertEqual(console._lifecycle_progress(step, True)[0], phase)
        self.assertEqual(console._lifecycle_progress("C10", True)[0], "cleanup pending")
        self.assertEqual(console._lifecycle_progress("C10", False), ("done", ()))

    def test_active_task_one_shot_and_detail_keep_elapsed_and_last_activity_separate(self) -> None:
        task = console.Task(
            "001", "Task", "IN_PROGRESS", (), (), None, (), (), readiness="IN PROGRESS",
            lifecycle="in_progress", updated_at=0, started_at="2026-01-01T00:00:00Z",
            progress_phase="working", remaining_gates=("Run task validation",),
        )
        state = console.ConsoleState(self.project)
        state.snapshot = console.Snapshot(self.project, self.project / "tasks/QUEUE.md", "main", "clean", 0, (task,), 0)
        output = console.one_shot(state)
        self.assertIn("Elapsed:", output)
        self.assertIn("Progress: working", output)
        palette = {name: 0 for name in ("base", "text", "title", "ready", "working", "muted", "line", "action", "blocked")}
        lines = [value for value, _ in console._detail_lines(task, 80, palette)]
        self.assertTrue(any(value.startswith("Elapsed cycle time:") for value in lines))
        self.assertTrue(any(value.startswith("Last activity:") for value in lines))

    def test_framework_identity_reads_version_and_shortens_a_home_root(self) -> None:
        home = self.project / "home"
        root = home / "framework"
        script = root / "scripts" / "project_console.py"
        script.parent.mkdir(parents=True)
        (root / "VERSION").write_text("9.8.7\n", encoding="utf-8")
        self.write_queue()
        with mock.patch.object(console.Path, "home", return_value=home):
            identity = console._framework_identity(script)
            self.assertEqual(identity.version, "9.8.7")
            self.assertEqual(identity.root_label, "~/framework")
            state = console.ConsoleState(self.project)
            state.framework = identity
            state.snapshot = self.snapshot()
            output = console.one_shot(state)
            self.assertTrue(output.startswith("MERIDIAN | v9.8.7 | ~/framework |"))

    def test_framework_identity_missing_version_is_nonfatal(self) -> None:
        identity = console._framework_identity(self.project / "framework" / "scripts" / "console.py")
        self.assertEqual(identity.version, "unknown")
        self.assertIn("version unknown", identity.label)
        self.write_queue()
        state = console.ConsoleState(self.project)
        state.framework = identity
        state.snapshot = self.snapshot()
        self.assertIn("MERIDIAN | version unknown |", console.one_shot(state))

    def test_terminal_title_identifies_console_without_an_absolute_path(self) -> None:
        output = mock.Mock()
        with mock.patch.object(console.sys, "stdout", output):
            console._set_terminal_title(Path("/private/project-name"))
        self.assertIn("Meridian console", output.write.call_args.args[0])
        self.assertIn("project-name", output.write.call_args.args[0])
        self.assertNotIn("/private", output.write.call_args.args[0])

    def test_detail_pane_keeps_the_approved_content_hierarchy(self) -> None:
        self.write_queue()
        task = self.snapshot().tasks[0]
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "muted", "line", "action"
        )}
        lines = [value for value, _ in console._detail_lines(task, 40, palette)]
        self.assertEqual(lines[0], "Task details")
        self.assertLess(lines.index("Dependencies"), lines.index("Objective"))
        self.assertLess(lines.index("Objective"), lines.index("Acceptance criteria"))
        self.assertLess(lines.index("Dependencies"), lines.index("Next directive"))
        self.assertIn("- [ ] Second check.", lines)

    def test_detail_sections_accept_governed_headings_and_show_dependency_states(self) -> None:
        self.write_queue()
        task = self.snapshot().tasks[0]
        governed = "# Task\n\n## 🎯 Goal\n\nGoverned goal.\n\n## ✅ Acceptance criteria\n\n- [ ] Done.\n"
        self.assertEqual(console._section(governed, "Objective", "Goal"), ("Governed goal.",))
        self.assertEqual(console._section(governed, "Acceptance Criteria"), ("- [ ] Done.",))
        detailed = console.Task(
            task.task_id, task.title, task.status, task.phase, ("001",), task.path,
            task.objective, task.criteria, readiness=task.readiness,
            dependency_states=(("001", "Done"),),
        )
        palette = {name: 0 for name in ("base", "text", "title", "ready", "muted", "line", "action")}
        lines = [value for value, _ in console._detail_lines(detailed, 50, palette)]
        self.assertLess(lines.index("Dependencies"), lines.index("Objective"))
        self.assertIn("001 — Done", lines)

    def test_detail_view_clamps_scroll_across_resize_and_draws_hidden_indicators(self) -> None:
        palette = {name: 0 for name in ("base", "text", "title", "ready", "muted", "line", "action")}
        task = console.Task(
            "LONG", "A long task", "[ ]", (), ("001",), None,
            tuple(f"Objective line {number} needs enough text to wrap in narrow panes." for number in range(12)),
            (), readiness="READY", dependency_states=(("001", "Done"),),
        )
        lines, offset, body = console._detail_view(task, 32, 14, 4, 999, palette)
        self.assertEqual(offset, len(lines) - body)
        self.assertEqual(console._scroll_detail(task, 32, 14, 4, offset, 1, palette), offset)
        self.assertEqual(console._scroll_detail(task, 32, 14, 4, offset, -1, palette), offset - 1)
        _, resized, resized_body = console._detail_view(task, 72, 28, 4, offset, palette)
        self.assertLessEqual(resized, max(0, len(console._detail_view(task, 72, 28, 4, 0, palette)[0]) - resized_body))
        screen = FakeScreen(14, 40)
        console._draw_detail(screen, task, 2, 4, 32, 14, offset, palette)
        self.assertIn("more above", "\n".join(screen.row(y) for y in range(4, 12)))

    def test_header_right_aligns_git_and_underlines_active_all_tab(self) -> None:
        self.write_queue()
        state = console.ConsoleState(self.project)
        state.framework = console.FrameworkIdentity("1.4.0", Path("/fw"))
        state.snapshot = self.snapshot()
        state.last_success = datetime.now().astimezone()
        screen = mock.Mock()
        screen.getmaxyx.return_value = (35, 140)
        palette = {name: 0 for name in (
            "text", "blocked", "stale", "tab", "ready", "working",
            "unknown", "muted", "line", "tab_underline"
        )}
        console._draw_header(screen, state, palette, "All", 140)
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
        self.assertEqual(console._cycle_filter(snapshot, "Ready", 1), "All")
        self.assertEqual(console._cycle_filter(snapshot, "Ready", -1), "All")
        self.assertEqual(console._cycle_filter(snapshot, "All", 1), "Ready")
        self.assertEqual(console._tab_at(snapshot, 2, 1), "All")
        self.assertEqual(console._tab_at(snapshot, 20, 1), "Working")

    def test_ready_directive_copy_hit_and_clipboard_result(self) -> None:
        self.write_queue()
        task = self.snapshot().tasks[0]
        self.assertEqual(task.launch_command, "Proceed with 002")
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "muted", "line", "action"
        )}
        screen = mock.Mock()
        screen.getmaxyx.return_value = (35, 140)
        rows = console._draw_detail(screen, task, 95, 4, 43, 35, 0, palette)
        self.assertTrue(rows)
        self.assertTrue(console._action_hit(100, min(rows), (95, 136, rows)))
        self.assertFalse(console._action_hit(94, min(rows), (95, 136, rows)))
        with mock.patch.object(console.sys, "platform", "darwin"), \
             mock.patch.object(console.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(console._copy_to_clipboard(task.launch_command))
            run.assert_called_once_with(
                ("pbcopy",), input="Proceed with 002", text=True,
                capture_output=True, check=False, timeout=2,
            )
            run.return_value.returncode = 1
            self.assertFalse(console._copy_to_clipboard(task.launch_command))

    def test_new_tabs_are_appended_after_existing_ones(self) -> None:
        self.write_queue()
        snapshot = self.snapshot()
        self.assertEqual(
            tuple(console._filter_counts(snapshot)),
            ("Ready", "Working", "Blocked", "Unknown", "Review", "Mismatch", "Closing"),
        )


class AgentLaunchTest(unittest.TestCase):
    SESSION_ID = "w0t1p2:12345678-1234-1234-1234-123456789abc"

    def task(self, **changes) -> console.Task:
        values = dict(
            task_id="001", title="First", status="TODO", phase=(), dependencies=(), path=None,
            objective=(), criteria=(), readiness="READY", lifecycle="todo",
        )
        values.update(changes)
        return console.Task(**values)

    def test_permitted_directive_matrix_refuses_writers_and_mismatches(self) -> None:
        self.assertEqual(self.task().launch_command, "Proceed with 001")
        self.assertFalse(self.task().is_resume)
        self.assertEqual(self.task().resume_confirmations, 0)
        for workflow in ("lean-delivery", "governed-sdd"):
            with self.subTest(workflow=workflow):
                resumed = self.task(workflow=workflow, readiness="IN PROGRESS",
                                    lifecycle="in_progress")
                self.assertTrue(resumed.is_resume)
                self.assertEqual(resumed.launch_command, "Proceed with 001")
                self.assertEqual(resumed.resume_confirmations, 1)
                self.assertEqual(
                    self.task(workflow=workflow, readiness="IN PROGRESS",
                              lifecycle="in_progress", active_writer=True).launch_command,
                    RESUME_001,
                )
                self.assertEqual(
                    self.task(workflow=workflow, readiness="IN PROGRESS",
                              lifecycle="in_progress", active_writer=True).resume_confirmations,
                    2,
                )
        self.assertEqual(self.task(workflow="lean-delivery", readiness="READY FOR REVIEW",
                                   lifecycle="ready_for_review").launch_command, "Review 001")
        self.assertEqual(self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                                   lifecycle="ready_for_review", review="REQUIRED").launch_command,
                         "Review 001")
        self.assertFalse(self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                                   lifecycle="ready_for_review", review="REQUIRED").is_resume)
        self.assertEqual(self.task(workflow="governed-sdd", readiness="IN PROGRESS",
                                   lifecycle="in_progress", changes_requested=True).launch_command,
                         "Address review 001")
        self.assertIsNone(self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                                    lifecycle="ready_for_review", review="NOT_REQUIRED").launch_command)
        self.assertIsNone(self.task(readiness="MISMATCH", active_writer=True).launch_command)
        self.assertIsNone(self.task(active_writer=True).launch_command)
        self.assertIsNone(self.task(lifecycle="done", readiness="DONE ON BRANCH").launch_command)
        self.assertIsNone(self.task(lifecycle="closing", readiness="CLOSING").launch_command)
        self.assertIsNone(self.task(lifecycle="in_progress", readiness="IN PROGRESS",
                                    record_problem="duplicate record").launch_command)

    def test_next_action_explains_review_launches_and_refusals(self) -> None:
        required = self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                             lifecycle="ready_for_review", review="REQUIRED")
        self.assertEqual(required.next_action, "If assigned: Review 001")
        self.assertEqual(
            self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                      lifecycle="ready_for_review").next_action,
            "Review unavailable: review policy not declared",
        )
        self.assertEqual(
            self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                      lifecycle="ready_for_review", review="NOT REQUIRED").next_action,
            "Review unavailable: Review: NOT REQUIRED",
        )
        self.assertEqual(
            self.task(workflow="governed-sdd", readiness="READY FOR REVIEW",
                      lifecycle="ready_for_review", review="REQUIRED", active_writer=True).next_action,
            "Review unavailable: active writer",
        )
        self.assertEqual(
            self.task(readiness="MISMATCH", mismatch="state conflict").next_action,
            "Resolve the state disagreement: state conflict",
        )
        self.assertEqual(
            self.task(readiness="READY FOR REVIEW", lifecycle="ready_for_review",
                      record_problem="task record not found").next_action,
            "Resolve the task record: task record not found",
        )
        lean = self.task(workflow="lean-delivery", readiness="READY FOR REVIEW",
                         lifecycle="ready_for_review")
        self.assertEqual(lean.next_action, "If assigned: Review 001")

    def test_request_revalidates_id_and_preserves_an_argument_vector(self) -> None:
        with mock.patch.dict(console.os.environ, {"ITERM_SESSION_ID": self.SESSION_ID}, clear=False):
            request, error = console._launch_request(self.task(), Path("."), "codex")
        self.assertIsNone(error)
        self.assertIsNotNone(request)
        self.assertEqual(request.directive, "Proceed with 001")
        self.assertEqual(request.session_uuid, "12345678-1234-1234-1234-123456789abc")
        self.assertIn("exec codex 'Proceed with 001'", request.shell_command)
        with mock.patch.dict(console.os.environ, {"ITERM_SESSION_ID": self.SESSION_ID}, clear=False):
            hostile, error = console._launch_request(self.task(task_id="001; rm -rf /"), Path("."), "codex")
        self.assertIsNone(hostile)
        self.assertIn("task ID", error or "")

    def test_defaults_read_only_known_and_unknown_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            (home / ".claude").mkdir()
            (home / ".codex" / "config.toml").write_text(
                'model = "gpt-test"\nmodel_reasoning_effort = "high"\n', encoding="utf-8")
            (home / ".claude" / "settings.json").write_text(
                '{"model": "claude-test", "effort": "medium"}', encoding="utf-8")
            defaults = console._agent_defaults(home)
            self.assertEqual(defaults["codex"], console.AgentDefaults("gpt-test", "high"))
            self.assertEqual(defaults["claude"], console.AgentDefaults("claude-test", "medium"))
            (home / ".codex" / "config.toml").write_text("not = [valid", encoding="utf-8")
            (home / ".claude" / "settings.json").write_text("{", encoding="utf-8")
            defaults = console._agent_defaults(home)
            self.assertEqual(defaults["codex"], console.AgentDefaults())
            self.assertEqual(defaults["claude"], console.AgentDefaults())

    def test_launch_panel_is_bordered_and_identifies_the_choice(self) -> None:
        screen = FakeScreen(20, 100)
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "muted", "line", "action", "blocked",
        )}
        console._draw_launch_prompt(
            screen, 100, 20, self.task(), 0, Path("/project"),
            {"claude": console.AgentDefaults("claude-test", "medium"),
             "codex": console.AgentDefaults("gpt-test", "high")}, palette,
        )
        rendered = "\n".join(screen.row(y) for y in range(20))
        self.assertIn("┌", rendered)
        self.assertIn("Task: 001", rendered)
        self.assertIn("Directive: Proceed with 001", rendered)
        self.assertIn("1 Claude Code", rendered)
        self.assertIn("2 Codex", rendered)
        self.assertIn("Esc cancels", rendered)

    def test_resume_prompts_for_liveness_and_a_second_dirty_confirmation(self) -> None:
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "muted", "line", "action", "blocked",
        )}
        defaults = {"claude": console.AgentDefaults(), "codex": console.AgentDefaults()}
        clean = self.task(readiness="IN PROGRESS", lifecycle="in_progress")
        screen = FakeScreen(20, 100)
        console._draw_launch_prompt(screen, 100, 20, clean, 0, Path("/project"),
                                    defaults, palette)
        rendered = "\n".join(screen.row(y) for y in range(20))
        self.assertIn("cannot tell whether an agent is still active", rendered)
        self.assertIn("Press y to continue", rendered)

        dirty = self.task(readiness="IN PROGRESS", lifecycle="in_progress",
                          active_writer=True)
        screen = FakeScreen(20, 100)
        console._draw_launch_prompt(screen, 100, 20, dirty, 1, Path("/project"),
                                    defaults, palette)
        rendered = "\n".join(screen.row(y) for y in range(20))
        self.assertIn("uncommitted changes", rendered)
        self.assertIn("Press y again", rendered)

    def test_resume_copy_and_launch_use_the_identical_directive(self) -> None:
        task = self.task(readiness="IN PROGRESS", lifecycle="in_progress")
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "working", "muted", "line", "action",
            "blocked",
        )}
        lines = [value for value, _style in console._detail_lines(task, 80, palette)]
        self.assertIn(f"{task.launch_command}  [copy]  [l Resume]", lines)

    def test_agent_selection_revalidates_and_launches_without_enter(self) -> None:
        task = self.task()
        state = mock.Mock(project=Path("/project"))
        with mock.patch.object(console, "load_task", return_value=task) as reload, \
             mock.patch.object(console, "load_snapshot") as full, \
             mock.patch.object(console, "_launch_request") as request, \
             mock.patch.object(console, "_start_launch", return_value=(True, "Started")) as start:
            request.return_value = (
                console.LaunchRequest("codex", "Proceed with 001", Path("/project"), "001",
                                      "12345678-1234-1234-1234-123456789abc"), None)
            self.assertEqual(console._launch_selected(state, task, "codex"),
                             (True, "Started"))
        reload.assert_called_once()
        self.assertEqual(reload.call_args.args[:2], (Path("/project"), task.task_id))
        full.assert_not_called()
        state.refresh.assert_not_called()
        request.assert_called_once_with(task, Path("/project"), "codex")
        start.assert_called_once()

    def test_agent_selection_stops_on_revalidation_failure(self) -> None:
        task = self.task(readiness="IN PROGRESS", lifecycle="in_progress")
        closing = self.task(readiness="CLOSING", lifecycle="closing")
        for label, current in (("closing", closing), ("done", None)):
            with self.subTest(label=label):
                state = mock.Mock(project=Path("/project"))
                with mock.patch.object(console, "load_task", return_value=current), \
                     mock.patch.object(console, "_launch_request") as request, \
                     mock.patch.object(console, "_start_launch") as start:
                    success, message = console._launch_selected(state, task, "claude")
                self.assertFalse(success)
                self.assertIn("state changed", message)
                request.assert_not_called()
                start.assert_not_called()

    def test_agent_selection_requires_new_confirmation_if_worktree_became_dirty(self) -> None:
        selected = self.task(readiness="IN PROGRESS", lifecycle="in_progress")
        current = self.task(readiness="IN PROGRESS", lifecycle="in_progress",
                            active_writer=True)
        state = mock.Mock(project=Path("/project"))
        with mock.patch.object(console, "load_task", return_value=current), \
             mock.patch.object(console, "_launch_request") as request:
            success, message = console._launch_selected(state, selected, "codex")
        self.assertFalse(success)
        self.assertIn("state changed", message)  # the directive changed to the resume form
        request.assert_not_called()

    def test_unconfirmed_dirty_resume_is_refused_before_launch(self) -> None:
        task = self.task(readiness="IN PROGRESS", lifecycle="in_progress", active_writer=True)
        state = mock.Mock(project=Path("/project"))
        with mock.patch.object(console, "load_task", return_value=task), \
             mock.patch.object(console, "_launch_request") as request:
            success, message = console._launch_selected(state, task, "codex")
        self.assertFalse(success)
        self.assertIn("became dirty", message)
        request.assert_not_called()

    def test_resume_flag_is_only_in_the_dirty_resume_directive(self) -> None:
        for workflow in ("lean-delivery", "governed-sdd"):
            for fields in (
                dict(readiness="READY", lifecycle="todo"),
                dict(readiness="IN PROGRESS", lifecycle="in_progress"),
                dict(readiness="READY FOR REVIEW", lifecycle="ready_for_review", review="REQUIRED"),
                dict(readiness="IN PROGRESS", lifecycle="in_progress", changes_requested=True),
            ):
                with self.subTest(workflow=workflow, fields=fields):
                    directive = self.task(workflow=workflow, **fields).launch_command
                    self.assertTrue(directive is None or "--resume" not in directive)
        resume = self.task(readiness="IN PROGRESS", lifecycle="in_progress", active_writer=True)
        self.assertEqual(resume.launch_command, RESUME_001)
        self.assertIn("prepare 001 --resume --format json", RESUME_001)
        request, error = console._launch_request(resume, Path("/project"), "codex")
        self.assertIsNone(request)  # no iTerm session here; the directive itself is unchanged
        with mock.patch.dict(os.environ, {"ITERM_SESSION_ID": "w0t1p2:12345678-1234-1234-1234-123456789abc"}), \
             mock.patch.object(console, "_primary_checkout", return_value=(Path("/project"), None)):
            request, error = console._launch_request(resume, Path("/project"), "codex")
        self.assertIsNone(error)
        self.assertEqual(request.directive, RESUME_001)
        self.assertIn(RESUME_001, request.shell_command)

    def test_request_refuses_missing_or_malformed_console_session(self) -> None:
        for session_id in (None, "w0t1p2:not-a-uuid", "wrong:12345678-1234-1234-1234-123456789abc"):
            environment = {} if session_id is None else {"ITERM_SESSION_ID": session_id}
            with self.subTest(session_id=session_id), \
                 mock.patch.dict(console.os.environ, environment, clear=True):
                request, error = console._launch_request(self.task(), Path("."), "codex")
            self.assertIsNone(request)
            self.assertEqual(error, "iTerm2 console session is missing or invalid; [copy] remains available")

    def test_launch_failure_modes_leave_copy_as_fallback(self) -> None:
        request = console.LaunchRequest(
            "codex", "Proceed with 001", Path("/project"), "001",
            "12345678-1234-1234-1234-123456789abc",
        )
        with mock.patch.object(console.sys, "platform", "linux"):
            self.assertIn("macOS", console._start_launch(request)[1])
        with mock.patch.object(console.sys, "platform", "darwin"), \
             mock.patch.object(console.shutil, "which", return_value=None):
            self.assertIn("codex is not available", console._start_launch(request)[1])
        with mock.patch.object(console.sys, "platform", "darwin"), \
             mock.patch.object(console.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(console.subprocess, "run", side_effect=subprocess.TimeoutExpired("osascript", 10)):
            self.assertIn("timed out", console._start_launch(request)[1])

    def test_osascript_receives_quoted_command_and_reports_iterm_failure(self) -> None:
        request = console.LaunchRequest(
            "claude", "Proceed with 001; echo nope", Path("/project name"), "001",
            "12345678-1234-1234-1234-123456789abc",
        )
        with mock.patch.object(console.sys, "platform", "darwin"), \
             mock.patch.object(console.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(console.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stderr="Application isn't running", stdout="")
            success, message = console._start_launch(request)
        self.assertFalse(success)
        self.assertIn("iTerm2 is unavailable", message)
        command = run.call_args.args[0]
        self.assertEqual(command[0], "osascript")
        self.assertIn("exec claude 'Proceed with 001; echo nope'", command[2])
        self.assertIn("split horizontally with default profile", command[2])
        self.assertIn('if unique id of aSession is "12345678-1234-1234-1234-123456789abc"', command[2])
        self.assertIn("repeat with aSession in sessions of aTab", command[2])
        self.assertIn("tell newSession to write text", command[2])
        self.assertNotIn("w0t1p2", command[2])
        self.assertNotIn("create tab", command[2])
        self.assertNotIn("create window", command[2])

    @unittest.skipUnless(
        sys.platform == "darwin" and shutil.which("osacompile")
        and Path("/Applications/iTerm.app").exists(),
        "requires macOS osacompile and iTerm2",
    )
    def test_split_payload_compiles_as_applescript(self) -> None:
        usable, reason = _osacompile_can_resolve_iterm2_dictionary()
        if not usable:
            self.skipTest(
                "osacompile cannot resolve the iTerm2 dictionary in this environment: "
                f"{reason}",
            )
        payload = console._apple_script(
            "exec claude 'a \"q\" \\ b'", "12345678-1234-1234-1234-123456789abc",
        )
        with tempfile.TemporaryDirectory() as directory:
            result = _compile_applescript(payload, Path(directory) / "payload.scpt")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_iterm2_dictionary_probe_skips_or_preserves_payload_failure(self) -> None:
        success = mock.Mock(returncode=0, stderr="")
        dictionary_failure = mock.Mock(
            returncode=1, stderr="Expected \u201cthen\u201d but found property. (-2741)\n(-2740)",
        )
        payload_failure = mock.Mock(returncode=1, stderr="payload does not compile")

        with self.subTest("probe failure skips"):
            with mock.patch.object(subprocess, "run", return_value=dictionary_failure):
                usable, reason = _osacompile_can_resolve_iterm2_dictionary()
            self.assertFalse(usable)
            with self.assertRaisesRegex(
                unittest.SkipTest,
                "^osacompile cannot resolve the iTerm2 dictionary in this environment: .*\\(-2741\\)",
            ):
                if not usable:
                    self.skipTest(
                        "osacompile cannot resolve the iTerm2 dictionary in this environment: "
                        f"{reason}",
                    )

        with self.subTest("probe timeout skips"):
            with mock.patch.object(
                subprocess, "run", side_effect=subprocess.TimeoutExpired("osacompile", 30),
            ):
                usable, reason = _osacompile_can_resolve_iterm2_dictionary()
            self.assertFalse(usable)
            with self.assertRaisesRegex(
                unittest.SkipTest,
                "^osacompile cannot resolve the iTerm2 dictionary in this environment: timed out",
            ):
                if not usable:
                    self.skipTest(
                        "osacompile cannot resolve the iTerm2 dictionary in this environment: "
                        f"{reason}",
                    )

        with self.subTest("successful probe preserves payload failure"):
            with mock.patch.object(subprocess, "run", side_effect=(success, payload_failure)):
                usable, reason = _osacompile_can_resolve_iterm2_dictionary()
                self.assertTrue(usable, reason)
                result = _compile_applescript("invalid payload", Path("payload.scpt"))
            with self.assertRaisesRegex(AssertionError, "payload does not compile"):
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unmatched_console_session_leaves_copy_as_fallback(self) -> None:
        request = console.LaunchRequest(
            "codex", "Proceed with 001", Path("/project"), "001",
            "12345678-1234-1234-1234-123456789abc",
        )
        with mock.patch.object(console.sys, "platform", "darwin"), \
             mock.patch.object(console.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(console.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stderr="MERIDIAN_SESSION_NOT_FOUND", stdout="")
            success, message = console._start_launch(request)
        self.assertFalse(success)
        self.assertEqual(message, "iTerm2 console session was not found; [copy] remains available")

    def test_start_revalidates_task_and_session_ids(self) -> None:
        request = console.LaunchRequest("codex", "Proceed with 001", Path("/project"), "001; rm -rf /", "bad")
        with mock.patch.object(console.sys, "platform", "darwin"), \
             mock.patch.object(console.shutil, "which", return_value="/usr/bin/tool"):
            success, message = console._start_launch(request)
        self.assertFalse(success)
        self.assertIn("task ID", message)


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
    def task(task_id: str, title: str = "Title") -> console.Task:
        return console.Task(task_id, title, "[ ]", ("Phase 1",), (), None, (), (),
                            readiness="READY")

    def render(self, tasks, width: int, all_tasks=None):
        screen = FakeScreen(20, width)
        console._draw_list(screen, list(tasks), tasks[0].task_id, 0, width, 20,
                           self.PALETTE, all_tasks)
        return screen

    def test_columns_follow_the_longest_id_for_3_8_13_and_18_characters(self) -> None:
        for length in (3, 8, 13, 18):
            with self.subTest(length=length):
                task_id = "X" * (length - 1) + "1"
                tasks = [self.task("001"), self.task(task_id, "Visible title")]
                screen = self.render(tasks, 110)
                layout = console._list_layout(tasks, 110)
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
        rows = console.parse_queue(queue, "fixture", console.PROFILES["lean-delivery"])
        tasks = [
            console.Task(row.task_id, row.title, row.status, row.section,
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
        snapshot = console.Snapshot(Path("/p"), Path("/p/q"), "main", "clean", 0,
                                    tuple(tasks), 0)
        self.assertEqual([task.task_id for task in console._visible_tasks(snapshot, "All", "program")],
                         ["001", "002", "003"])
        self.assertEqual([task.task_id for task in console._visible_tasks(snapshot, "All", "phase 2")],
                         ["003"])

    def test_lean_active_queue_wrapper_keeps_phase_only_rendering(self) -> None:
        queue = ("# Queue\n\n## 🏃 Active Queue\n\n### Phase 29 — Work\n\n"
                 + HEADER + "| `[ ]` | 001 | First | P2 | — | — |\n")
        row = console.parse_queue(queue, "fixture", console.PROFILES["lean-delivery"])[0]
        self.assertEqual(row.section, ("Phase 29 — Work",))
        task = console.Task(row.task_id, row.title, row.status, row.section,
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
                row = console.parse_queue(queue, "fixture", console.PROFILES["lean-delivery"])[0]
                task = console.Task(row.task_id, row.title, row.status, row.section,
                                    (), None, (), (), readiness="READY")
                self.assertEqual(row.section, (label,))
                self.assertEqual(self.render([task], 100).row(5).strip(),
                                 f"Level {level} — Work")

    def test_three_character_ids_keep_their_position_with_actual_width(self) -> None:
        tasks = [self.task("075"), self.task("076")]
        layout = console._list_layout(tasks, 110)
        self.assertEqual((layout.id_x, layout.id_width, layout.title_x), (3, 3, 7))
        self.assertEqual(self.render(tasks, 110).row(6)[1], "›")

    def test_id_is_capped_clipped_and_never_overlaps_title_or_status(self) -> None:
        long_id = "M20-EVENT-002-CORR"
        tasks = [self.task(long_id, "Title")]
        self.assertTrue(console._list_layout(tasks, 50).id_width < len(long_id))
        for width in (50, 60, 74, 110):
            with self.subTest(width=width):
                layout = console._list_layout(tasks, width)
                self.assertLessEqual(layout.id_width, width // 3)
                self.assertGreaterEqual(layout.title_width, console.LIST_MIN_TITLE_WIDTH)
                self.assertLessEqual(layout.title_x + layout.title_width + 2, layout.status_x)
                row = self.render(tasks, width).row(6)
                shown = row[3:3 + layout.id_width]
                self.assertEqual(shown, console._clip(long_id, layout.id_width))
                self.assertEqual(shown.endswith("…"), layout.id_width < len(long_id))
                self.assertEqual(row[3 + layout.id_width], " ")
                self.assertTrue(row[layout.title_x:].startswith("○ "))

    def test_filtering_does_not_move_columns(self) -> None:
        everything = [self.task("001"), self.task("M20-EVENT-002")]
        full = console._list_layout(everything, 110)
        filtered = self.render(everything[:1], 110, everything)
        self.assertEqual(filtered.row(6)[3:6], "001")
        self.assertEqual(filtered.row(6)[full.title_x:full.title_x + 7], "○ Title")
        self.assertEqual(filtered.row(3)[full.status_x:full.status_x + 6], "Status")
        self.assertNotEqual(full, console._list_layout(everything[:1], 110))

    def test_full_id_is_in_detail_copy_directive_and_one_shot(self) -> None:
        task = self.task("M20-EVENT-002-CORR")
        lines = [value for value, _ in console._detail_lines(task, 60, self.PALETTE)]
        self.assertIn("Task M20-EVENT-002-CORR", lines)
        self.assertEqual(task.launch_command, "Proceed with M20-EVENT-002-CORR")
        state = console.ConsoleState(Path("."))
        state.snapshot = console.Snapshot(
            Path("."), Path("tasks/QUEUE.md"), "main", "clean", 0, (task,), 0,
        )
        state.last_success = datetime.now().astimezone()
        self.assertIn("M20-EVENT-002-CORR [READY] Title", console.one_shot(state))


class RepoCase(unittest.TestCase):
    """Throwaway Git repository with a primary checkout and task worktrees."""

    lock = "LEAN_DELIVERY"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.git(self.project, "init", "-q", "-b", "main")
        self.write(self.project, "PROJECT_WORKFLOW.md", f"# {self.lock}\n")

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "user.name=Test",
             "-c", "user.email=test@example.com", "-C", str(cwd), *args],
            capture_output=True, text=True, check=True,
        ).stdout

    def write(self, root: Path, relative: str, text: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, cwd: Path, message: str = "change") -> None:
        self.git(cwd, "add", "-A")
        self.git(cwd, "commit", "-q", "-m", message)

    def worktree(self, branch: str) -> Path:
        path = self.root / f"wt-{branch}"
        self.git(self.project, "worktree", "add", "-q", "-b", branch, str(path))
        return path

    def load(self) -> dict[str, console.Task]:
        return {task.task_id: task for task in console.load_snapshot(self.project).tasks}

    def refs_and_status(self) -> tuple[str, str]:
        return (self.git(self.project, "for-each-ref"),
                self.git(self.project, "status", "--porcelain"))


class LeanEffectiveStateTest(RepoCase):
    def queue(self, statuses: dict[str, str], deps: dict[str, str] | None = None) -> str:
        rows = "".join(
            f"| `[{token}]` | {task_id} | Task {task_id} | P2 | {(deps or {}).get(task_id, '—')} "
            f"| [{task_id}]({task_id}-task.md) |\n"
            for task_id, token in statuses.items()
        )
        return ("# Queue\n\n### Phase 1\n\n" + HEADER + rows)

    def setup_project(self, statuses: dict[str, str], deps: dict[str, str] | None = None) -> None:
        self.write(self.project, "tasks/QUEUE.md", self.queue(statuses, deps))
        for task_id in statuses:
            self.write(
                self.project, f"tasks/{task_id}-task.md",
                f"# Task {task_id} — Title {task_id}\n\n> **ID**: `{task_id}`\n\n"
                "## Objective\n\nDo it.\n\n## Acceptance Criteria\n\n- [ ] Check.\n",
            )
        self.commit(self.project, "initial")

    def set_branch_status(self, wt: Path, task_id: str, token: str, handoff: str | None = None) -> None:
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8")
        queue = re.sub(rf"\| `\[.\]` \| {task_id} \|", f"| `[{token}]` | {task_id} |", queue)
        self.write(wt, "tasks/QUEUE.md", queue)
        if handoff:
            self.write(wt, f"tasks/handoffs/{task_id}.md",
                       f"# Completion Report — {task_id}\n\n- Status: `{handoff}`\n")
        self.commit(wt, f"{task_id} {token}")

    def test_task_without_branch_keeps_current_behavior(self) -> None:
        self.setup_project({"001": " "})
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle, task.source), ("READY", "todo", "main"))
        self.assertEqual(task.launch_command, "Proceed with 001")
        self.assertFalse(task.active_writer)

    def test_reserved_branch_state_wins_without_any_write(self) -> None:
        self.setup_project({"001": " "})
        self.set_branch_status(self.worktree("task-001"), "001", "/")
        before = self.refs_and_status()
        task = self.load()["001"]
        self.assertEqual(self.refs_and_status(), before)
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertEqual(task.source, "branch task-001")
        self.assertEqual(task.launch_command, "Proceed with 001")
        self.assertEqual(task.next_action, "If assigned: Proceed with 001")
        self.assertEqual(task.worktree, str(self.root / "wt-task-001"))
        self.assertIn("[ ]", (self.project / "tasks/QUEUE.md").read_text(encoding="utf-8"))

    def test_clean_prepared_worktree_derives_in_progress_without_queue_write(self) -> None:
        self.setup_project({"001": " "})
        self.worktree("task-001")
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle, task.source),
                         ("IN PROGRESS", "in_progress", "branch task-001"))
        self.assertFalse(task.active_writer)
        self.assertEqual(task.markers, ("registered worktree",))
        self.assertIn("[ ]", (self.project / "tasks/QUEUE.md").read_text(encoding="utf-8"))

    def test_closure_status_is_shown_in_the_detail_pane(self) -> None:
        self.setup_project({"001": " "})
        self.worktree("task-001")
        report = {"stop_reason": "REVIEW_REQUIRED", "resume": "After approval, continue at C4"}
        with mock.patch.object(console, "closure_status", return_value=(report, False)):
            task = self.load()["001"]
        self.assertEqual(task.closure_stop_reason, "REVIEW_REQUIRED")
        self.assertEqual(task.closure_resume, "After approval, continue at C4")
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "working", "muted", "line", "action", "blocked"
        )}
        lines = [value for value, _ in console._detail_lines(task, 60, palette)]
        self.assertIn("Closure stop: REVIEW_REQUIRED", lines)
        self.assertIn("Resume: After approval, continue at C4", lines)

    def test_every_closure_stop_is_rendered_without_special_cases(self) -> None:
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "working", "muted", "line", "action", "blocked"
        )}
        reasons = (
            "ACCEPTANCE_UNMET", "VALIDATION_FAILED", "REVIEW_REQUIRED", "WRONG_WORKTREE",
            "EVIDENCE_INCOMPLETE", "PRIMARY_DIRTY", "MAIN_BEHIND_ORIGIN", "LEASE_HELD",
            "INTEGRATION_CONFLICT", "CANDIDATE_VALIDATION_FAILED", "EVIDENCE_MISMATCH",
            "PUSH_PENDING", "PUSH_REJECTED", "CLEANUP_BLOCKED",
        )
        for reason in reasons:
            task = console.Task("001", "Task", "IN_PROGRESS", (), (), None, (), (),
                                readiness="IN PROGRESS", lifecycle="in_progress",
                                closure_stop_reason=reason, closure_resume="resume command")
            lines = [value for value, _ in console._detail_lines(task, 60, palette)]
            self.assertIn(f"Closure stop: {reason}", lines)
            self.assertIn("Resume: resume command", lines)

    def test_queued_tasks_do_not_read_closure_status(self) -> None:
        self.setup_project({"001": " ", "002": " "})
        with mock.patch.object(console, "closure_status") as status:
            self.load()
        status.assert_not_called()

    def test_uncommitted_in_progress_row_supersedes_committed_todo(self) -> None:
        self.setup_project({"001": " "})
        wt = self.worktree("task-001")
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8").replace("| `[ ]` | 001 |", "| `[/]` | 001 |")
        self.write(wt, "tasks/QUEUE.md", queue)
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertEqual(task.source, "uncommitted task-001")
        self.assertTrue(task.active_writer)

    def test_working_tree_behind_committed_row_is_a_mismatch(self) -> None:
        self.setup_project({"001": " "})
        wt = self.worktree("task-001")
        self.set_branch_status(wt, "001", "/")
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8").replace("| `[/]` | 001 |", "| `[ ]` | 001 |")
        self.write(wt, "tasks/QUEUE.md", queue)
        task = self.load()["001"]
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("working tree TODO", task.mismatch or "")

    def test_unparseable_working_queue_falls_back_to_committed_state(self) -> None:
        self.setup_project({"001": " "})
        wt = self.worktree("task-001")
        self.set_branch_status(wt, "001", "/")
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8").replace("`[/]`", "`[?]`")
        self.write(wt, "tasks/QUEUE.md", queue)
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.source), ("IN PROGRESS", "branch task-001"))

    def test_missing_registered_worktree_directory_does_not_break_snapshot(self) -> None:
        self.setup_project({"001": " "})
        wt = self.worktree("task-001")
        moved = wt.with_name("missing-task-001")
        wt.rename(moved)
        self.addCleanup(lambda: moved.rename(wt) if moved.exists() else None)
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.source), ("READY", "main"))
        self.assertEqual(task.worktree, str(wt))

    def test_completed_branch_with_done_handoff_is_ready_for_review(self) -> None:
        self.setup_project({"001": " "})
        self.set_branch_status(self.worktree("task-001"), "001", "x", handoff="DONE")
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle), ("READY FOR REVIEW", "ready_for_review"))
        self.assertEqual(console._state_label(task), ("Review", "ready"))
        self.assertEqual(task.launch_command, "Review 001")

    def test_completed_row_without_done_handoff_is_a_mismatch(self) -> None:
        self.setup_project({"001": " "})
        self.set_branch_status(self.worktree("task-001"), "001", "x", handoff="BLOCKED")
        task = self.load()["001"]
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("handoff BLOCKED", task.mismatch or "")

    def test_completed_branch_with_dirty_worktree_stays_in_progress(self) -> None:
        self.setup_project({"001": " "})
        wt = self.worktree("task-001")
        self.set_branch_status(wt, "001", "x", handoff="DONE")
        self.write(wt, "scratch.txt", "uncommitted")
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertTrue(task.active_writer)

    def test_dirty_worktree_is_advisory_and_never_changes_state(self) -> None:
        self.setup_project({"001": " "})
        wt = self.worktree("task-001")
        self.set_branch_status(wt, "001", "/")
        clean = self.load()["001"]
        self.write(wt, "scratch.txt", "uncommitted")
        dirty = self.load()["001"]
        self.assertFalse(clean.active_writer)
        self.assertTrue(dirty.active_writer)
        self.assertEqual((clean.readiness, clean.lifecycle), (dirty.readiness, dirty.lifecycle))
        self.assertEqual(dirty.markers, ("active writer",))
        self.assertEqual(clean.launch_command, "Proceed with 001")
        self.assertEqual(dirty.launch_command, RESUME_001)

    def test_branch_behind_primary_is_a_mismatch_without_directive(self) -> None:
        self.setup_project({"001": "/"})
        self.worktree("task-001")
        wt = self.root / "wt-task-001"
        self.set_branch_status(wt, "001", " ")
        task = self.load()["001"]
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("main IN_PROGRESS", task.mismatch or "")
        self.assertIn("task-001 TODO", task.mismatch or "")
        self.assertIsNone(task.launch_command)
        self.assertEqual(console._state_label(task)[0], "Mismatch")

    def test_dependencies_are_satisfied_by_integrated_state_only(self) -> None:
        self.setup_project({"001": " ", "002": " "}, deps={"002": "001"})
        self.set_branch_status(self.worktree("task-001"), "001", "x", handoff="DONE")
        tasks = self.load()
        self.assertEqual(tasks["001"].readiness, "READY FOR REVIEW")
        self.assertEqual(tasks["002"].readiness, "BLOCKED: 001")
        self.assertIsNone(tasks["002"].launch_command)

    def test_milestone_identity_resolves_the_task_branch(self) -> None:
        self.write(self.project, ".meridian/task-identity.json",
                   json.dumps({"version": 1, "mode": "milestone"}))
        self.setup_project({"M1-CORE-001": " "})
        self.set_branch_status(self.worktree("m1-core-001"), "M1-CORE-001", "/")
        task = self.load()["M1-CORE-001"]
        self.assertEqual(task.source, "branch m1-core-001")
        self.assertEqual(task.readiness, "IN PROGRESS")

    def test_one_shot_reports_source_markers_and_mismatch(self) -> None:
        self.setup_project({"001": " ", "002": "/"})
        wt = self.worktree("task-001")
        self.set_branch_status(wt, "001", "/")
        self.write(wt, "scratch.txt", "uncommitted")
        self.set_branch_status(self.worktree("task-002"), "002", " ")
        state = console.ConsoleState(self.project)
        state.refresh()
        output = console.one_shot(state)
        self.assertIn("State from: branch task-001", output)
        self.assertIn("Markers: active writer", output)
        self.assertIn("Mismatch: main IN_PROGRESS, task-002 TODO", output)


class GovernedEffectiveStateTest(RepoCase):
    lock = "GOVERNED_SDD"
    header = (
        "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
        "|---:|---|---|---|---|---|---|\n"
    )

    def setup_project(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Rows are (id, status, review, dependencies)."""
        body = "# Task Execution Queue\n\n" + self.header + "".join(
            f"| {index} | {task_id} | P1 | {status} | {review} | {deps} | "
            f"[{task_id}]({task_id}.md) |\n"
            for index, (task_id, status, review, deps) in enumerate(rows, 1)
        )
        self.write(self.project, "tasks/QUEUE.md", body)
        for task_id, status, review, _deps in rows:
            self.write_record(self.project, task_id, status)
        self.commit(self.project, "initial")

    def write_record(self, root: Path, task_id: str, status: str) -> None:
        self.write(root, f"tasks/{task_id}.md",
                   f"# Task {task_id} — Governed {task_id}\n\nPriority: P1\nStatus: {status}\n"
                   "Review: REQUIRED\n\n## Objective\n\nGoverned work.\n")

    def set_branch(self, wt: Path, task_id: str, status: str, record: str | None = None,
                   review: str | None = None) -> None:
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8")
        queue = re.sub(rf"(\| {task_id} \| P1 \| )\w+", rf"\g<1>{status}", queue)
        self.write(wt, "tasks/QUEUE.md", queue)
        self.write_record(wt, task_id, record or status)
        if review:
            self.write(wt, f"tasks/reviews/{task_id}.md", review)
        self.commit(wt, f"{task_id} {status}")

    def test_queue_statuses_map_to_normalized_phases_and_dependencies(self) -> None:
        self.setup_project([
            ("TASK-001", "ACCEPTED", "REQUIRED", "—"),
            ("TASK-002", "QUEUED", "REQUIRED", "TASK-001"),
            ("TASK-003", "IN_PROGRESS", "REQUIRED", "—"),
            ("TASK-004", "READY_FOR_REVIEW", "REQUIRED", "—"),
            ("TASK-005", "ANSWERED", "SPIKE", "—"),
            ("TASK-006", "QUEUED", "REQUIRED", "TASK-005"),
            ("TASK-007", "INCONCLUSIVE", "SPIKE", "—"),
            ("TASK-008", "QUEUED", "REQUIRED", "TASK-007"),
        ])
        tasks = self.load()
        self.assertEqual({tid: t.lifecycle for tid, t in tasks.items()}, {
            "TASK-002": "todo", "TASK-003": "in_progress", "TASK-004": "ready_for_review",
            "TASK-006": "todo", "TASK-008": "todo",
        })
        self.assertEqual(tasks["TASK-002"].readiness, "READY")
        self.assertEqual(tasks["TASK-006"].readiness, "READY")
        self.assertEqual(tasks["TASK-008"].readiness, "BLOCKED: TASK-007")
        self.assertEqual(tasks["TASK-004"].title, "Governed TASK-004")
        self.assertEqual(tasks["TASK-003"].launch_command, "Proceed with TASK-003")
        self.assertEqual(tasks["TASK-004"].launch_command, "Review TASK-004")

    def test_dependency_on_unaccepted_task_is_blocked(self) -> None:
        self.setup_project([
            ("TASK-001", "READY_FOR_REVIEW", "REQUIRED", "—"),
            ("TASK-002", "QUEUED", "REQUIRED", "TASK-001"),
        ])
        self.assertEqual(self.load()["TASK-002"].readiness, "BLOCKED: TASK-001")

    def test_unrecognized_status_is_an_explicit_error(self) -> None:
        self.setup_project([("TASK-001", "CHANGES_REQUESTED", "REQUIRED", "—")])
        with self.assertRaisesRegex(console.ConsoleError, "Unknown task status"):
            console.load_snapshot(self.project)

    def test_ready_for_review_requires_record_queue_and_review_agreement(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.set_branch(wt, "TASK-001", "READY_FOR_REVIEW")
        task = self.load()["TASK-001"]
        self.assertEqual((task.readiness, task.lifecycle), ("READY FOR REVIEW", "ready_for_review"))
        self.assertEqual(task.source, "branch task-001")
        self.set_branch(wt, "TASK-001", "READY_FOR_REVIEW", record="IN_PROGRESS")
        task = self.load()["TASK-001"]
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("task record IN_PROGRESS", task.mismatch or "")
        self.assertIsNone(task.launch_command)

    def test_ready_for_review_without_required_review_is_a_mismatch(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "NOT_REQUIRED", "—")])
        self.set_branch(self.worktree("task-001"), "TASK-001", "READY_FOR_REVIEW")
        task = self.load()["TASK-001"]
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("Review NOT_REQUIRED", task.mismatch or "")

    def test_latest_changes_requested_attempt_marks_in_progress_task(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        review = (
            "# Review Record — TASK-001\n\n## Attempt 1 — CHANGES_REQUESTED\n\n- x\n\n"
            "## Attempt 2 — CHANGES_REQUESTED\n\n- y\n"
        )
        self.set_branch(wt, "TASK-001", "IN_PROGRESS", review=review)
        task = self.load()["TASK-001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertTrue(task.changes_requested)
        self.assertEqual(task.markers, ("changes requested",))
        self.assertEqual(task.launch_command, "Address review TASK-001")
        approved = review + "\n## Attempt 3 — APPROVE\n\n- z\n"
        self.set_branch(wt, "TASK-001", "IN_PROGRESS", review=approved)
        self.assertFalse(self.load()["TASK-001"].changes_requested)

    def test_resubmission_after_changes_requested_is_ready_for_review(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        review = "# Review Record — TASK-001\n\n## Attempt 1 — CHANGES_REQUESTED\n\n- x\n"
        self.set_branch(self.worktree("task-001"), "TASK-001", "READY_FOR_REVIEW", review=review)
        task = self.load()["TASK-001"]
        self.assertEqual(task.lifecycle, "ready_for_review")
        self.assertFalse(task.changes_requested)

    def test_branch_accepted_is_done_on_branch_and_does_not_unblock_dependents(self) -> None:
        self.setup_project([
            ("TASK-001", "QUEUED", "REQUIRED", "—"),
            ("TASK-002", "QUEUED", "REQUIRED", "TASK-001"),
        ])
        self.set_branch(self.worktree("task-001"), "TASK-001", "ACCEPTED")
        tasks = self.load()
        self.assertEqual(tasks["TASK-001"].readiness, "DONE ON BRANCH")
        self.assertEqual(tasks["TASK-002"].readiness, "BLOCKED: TASK-001")

    def test_dirty_worktree_shows_active_writer(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.set_branch(wt, "TASK-001", "IN_PROGRESS")
        self.write(wt, "scratch.txt", "uncommitted")
        task = self.load()["TASK-001"]
        self.assertTrue(task.active_writer)
        self.assertEqual(task.readiness, "IN PROGRESS")
        self.assertEqual(
            task.launch_command,
            "Proceed with TASK-001 (Resume: run meridian worktree prepare TASK-001 --resume --format json)",
        )

    def test_uncommitted_in_progress_row_supersedes_committed_queued(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8").replace(
            "| TASK-001 | P1 | QUEUED", "| TASK-001 | P1 | IN_PROGRESS")
        self.write(wt, "tasks/QUEUE.md", queue)
        task = self.load()["TASK-001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertEqual(task.source, "uncommitted task-001")


class LinklessQueueTest(RepoCase):
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
        state = console.ConsoleState(self.project)
        state.refresh()
        self.assertIsNone(state.error)
        self.assertNotIn("STALE", console.one_shot(state))
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

        snapshot = console.load_snapshot(self.project)
        self.assertEqual(snapshot.done_count, 1)
        self.assertEqual(len(snapshot.tasks), 38)
        grouped = {}
        for task in snapshot.tasks:
            grouped.setdefault(task.phase[0].split()[0], []).append(task.task_id)
        self.assertEqual({name: len(rows) for name, rows in grouped.items()},
                         {name: count for name, count in counts.items() if name != "M01"})

        screen = FakeScreen(100, 110)
        console._draw_list(screen, list(snapshot.tasks), snapshot.tasks[0].task_id,
                           0, 110, 100, ConsoleListLayoutTest.PALETTE)
        drawn = [screen.row(y).strip() for y in range(5, 85)]
        headings = [line for line in drawn if re.fullmatch(
            r"(?:M\d{2} — Milestone \d+|F0 — Presentation track)", line)]
        self.assertEqual(headings, [f"M{number:02} — Milestone {number}"
                                    for number in range(2, 38)]
                         + ["F0 — Presentation track"])
        self.assertFalse(any("Rules" in line or "Priority" in line or "M01" in line
                             for line in drawn))
        self.assertLess(drawn.index("M37 — Milestone 37"), drawn.index("F0 — Presentation track"))
        self.assertEqual([task.task_id for task in console._visible_tasks(
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
                self.assertEqual(console.record_review(f"Review: {value}\n"), expected)
        self.assertIsNone(console.record_review("Status: READY_FOR_REVIEW\n"))

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
        lines = [value for value, _ in console._detail_lines(missing, 60, palette)]
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
        lines = " ".join(value for value, _ in console._detail_lines(duplicate, 200, palette))
        self.assertIn("docs/tasks/M37/M37-CAUSE-001.md, tasks/M36/M37-CAUSE-001.md", lines)
        self.assertIn("Record: ambiguous", self.one_shot())
        self.assertEqual(tasks["M37-CAUSE-002"].readiness, "READY")

    def one_shot(self) -> str:
        state = console.ConsoleState(self.project)
        state.refresh()
        return console.one_shot(state)

    def test_present_but_invalid_link_keeps_its_rejection(self) -> None:
        header = ("| Order | ID | Priority | Status | Dependencies | Task file |\n"
                  "|---:|---|---|---|---|---|\n")
        self.write(self.project, *self.record("M37-CAUSE-001"))
        for cell, message in (("see notes", "no unambiguous file link"),
                              ("[x](../../outside.md)", "no unambiguous file link"),
                              ("[x](other/missing.md)", "unavailable within the project")):
            self.write(self.project, "docs/TASK_QUEUE.md", "# Q\n\n" + header
                       + f"| 1 | M37-CAUSE-001 | P1 | QUEUED | — | {cell} |\n")
            with self.assertRaisesRegex(console.ConsoleError, message, msg=cell):
                console.load_snapshot(self.project)

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
                console.load_snapshot(self.project, console.IdentityCache())
            return len(seen)

        for count in (2, 12):
            self.assertEqual(calls(count, linked=False), calls(count, linked=True), count)


class RefreshCostTest(RepoCase):
    """The cost of a refresh must not grow with the number of known tasks."""

    queue = LeanEffectiveStateTest.queue
    setup_project = LeanEffectiveStateTest.setup_project

    def setup_with_history(self, archived: int) -> None:
        self.setup_project({"001": " ", "002": " "})
        queue = (self.project / "tasks/QUEUE.md").read_text(encoding="utf-8")
        history = "".join(f"| `[x]` | {100 + n} | Done {n} | P2 | — | — |\n" for n in range(archived))
        self.write(self.project, "tasks/QUEUE.md", queue + history)
        self.commit(self.project, "history")

    def subprocess_calls(self, cache: console.IdentityCache | None) -> list[list[str]]:
        real = subprocess.run
        calls: list[list[str]] = []

        def counting(command, *args, **kwargs):
            calls.append(list(command))
            return real(command, *args, **kwargs)

        with mock.patch.object(subprocess, "run", side_effect=counting):
            console.load_snapshot(self.project, cache)
        return calls

    def test_subprocess_work_does_not_grow_with_known_tasks(self) -> None:
        self.setup_with_history(2)
        small = self.subprocess_calls(console.IdentityCache())
        self.setup_with_history(40)
        large = self.subprocess_calls(console.IdentityCache())
        self.assertEqual(len(small), len(large))
        checks = [call for call in large if "check-ref-format" in call]
        self.assertEqual(len(checks), 2, "one ref check per open task")

    def test_refresh_reads_worktree_queue_only_for_dirty_worktrees(self) -> None:
        statuses = {f"{number:03}": " " for number in range(1, 6)}
        self.setup_project(statuses)
        worktrees = {task_id: self.worktree(f"task-{task_id}") for task_id in statuses}
        self.write(worktrees["001"], "scratch.txt", "uncommitted")
        reads: list[Path] = []
        original = console._read_text

        def observing(path: Path) -> str:
            reads.append(path)
            return original(path)

        with mock.patch.object(console, "_read_text", side_effect=observing):
            console.load_snapshot(self.project, console.IdentityCache())
        self.assertIn(worktrees["001"] / "tasks/QUEUE.md", reads)
        for task_id, worktree in worktrees.items():
            if task_id != "001":
                self.assertNotIn(worktree / "tasks/QUEUE.md", reads)

    def test_warm_refresh_resolves_no_identity_and_spawns_no_ref_check(self) -> None:
        self.setup_with_history(5)
        cache = console.IdentityCache()
        self.subprocess_calls(cache)
        warm = self.subprocess_calls(cache)
        self.assertEqual([call for call in warm if "check-ref-format" in call], [])

    def test_identity_is_resolved_once_until_the_declaration_changes(self) -> None:
        self.setup_with_history(1)
        cache = console.IdentityCache()
        with mock.patch.object(console, "resolve_task_identity",
                               wraps=console.resolve_task_identity) as resolver:
            console.load_snapshot(self.project, cache)
            console.load_snapshot(self.project, cache)
            self.assertEqual(resolver.call_count, 2)
            self.write(self.project, ".meridian/task-identity.json",
                       json.dumps({"version": 1, "mode": "opaque"}))
            console.load_snapshot(self.project, cache)
            self.assertEqual(resolver.call_count, 4)
            console.load_snapshot(self.project, cache)
            self.assertEqual(resolver.call_count, 4)

    def test_failed_resolution_is_not_cached(self) -> None:
        cache = console.IdentityCache()
        self.setup_with_history(1)
        with self.assertRaises(console.MeridianError):
            cache.resolve(self.project, "999")
        self.write(self.project, "tasks/999-task.md", "# Task 999\n\n> **ID**: `999`\n")
        self.assertEqual(cache.resolve(self.project, "999").canonical_id, "999")


class ClosingTaskMixin:
    """Terminal rows distinguish pending integration from cleanup in both workflows."""

    done_id: str
    open_id: str
    done_token: str

    def closing_project(self, worktree: bool = True, archived: bool = False) -> None:
        raise NotImplementedError

    def report(self, step: str, stop: str | None = None, resume: str | None = None):
        return {"step": step, "stop_reason": stop, "resume": resume}, stop is None

    def load_closing(self, report=None, error: Exception | None = None):
        patcher = mock.patch.object(
            console, "closure_status", return_value=report, side_effect=error)
        with patcher as status:
            tasks = self.load()
        return tasks, status

    def test_task_stays_visible_after_stage_with_derived_closing_state(self) -> None:
        self.closing_project()
        before = self.refs_and_status()
        queue = (self.project / "tasks/QUEUE.md").read_text(encoding="utf-8")
        tasks, _status = self.load_closing(
            self.report("C7", None, "run the selected candidate validation"))
        task = tasks[self.done_id]
        self.assertEqual(self.refs_and_status(), before)
        self.assertEqual((self.project / "tasks/QUEUE.md").read_text(encoding="utf-8"), queue)
        self.assertEqual((task.readiness, task.lifecycle, task.status),
                         ("CLOSING", "closing", self.done_token))
        self.assertEqual(task.progress_phase, "candidate validation")
        self.assertEqual(task.remaining_gates[0], "Stage integration")
        self.assertEqual(task.closure_resume, "run the selected candidate validation")
        self.assertEqual(task.next_action, "run the selected candidate validation")
        self.assertIsNone(task.launch_command)
        self.assertTrue(task.shows_progress)

    def test_task_stays_visible_after_finalize_with_a_pending_push(self) -> None:
        self.closing_project()
        tasks, _status = self.load_closing(self.report("C9", "PUSH_PENDING", "git push origin main"))
        task = tasks[self.done_id]
        self.assertEqual(task.progress_phase, "push pending")
        self.assertEqual(task.closure_stop_reason, "PUSH_PENDING")
        self.assertEqual(task.next_action, "PUSH_PENDING: git push origin main")

    def check_cleanup_only(self, archived: bool) -> None:
        self.closing_project(archived=archived)
        before = self.refs_and_status()
        resume = f"meridian worktree cleanup {self.done_id} --project /exact/project"
        state = console.ConsoleState(self.project)
        with mock.patch.object(console, "closure_status", return_value=self.report(
                "C10", None, resume)) as status:
            state.refresh()
        self.assertEqual(self.refs_and_status(), before)
        snapshot = state.snapshot
        task = next(item for item in snapshot.tasks if item.task_id == self.done_id)
        self.assertEqual(status.call_count, 1)
        self.assertEqual(snapshot.done_count, 1)
        self.assertEqual(console._filter_counts(snapshot)["Closing"], 0)
        self.assertEqual(console._visible_tasks(snapshot, "Closing", ""), [])
        self.assertIn(task, console._visible_tasks(snapshot, "All", self.done_id))
        self.assertEqual(console._state_label(task), ("Done", "muted"))
        self.assertEqual((task.readiness, task.lifecycle), ("DONE", "done"))
        self.assertTrue(task.cleanup_pending)
        self.assertFalse(task.shows_progress)
        self.assertIsNone(task.launch_command)
        self.assertEqual(task.next_action, resume)
        self.assertEqual(task.closure_resume, resume)
        self.assertEqual(task.progress_phase, "cleanup pending")
        self.assertEqual(console._filter_counts(snapshot)["Working"], 0)
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "working", "muted", "line", "action", "blocked")}
        lines = [value for value, _ in console._detail_lines(task, 200, palette)]
        self.assertIn("○ Done", lines)
        self.assertIn("Cleanup pending", lines)
        self.assertIn(f"Resume: {resume}", lines)
        text = console.one_shot(state)
        self.assertIn("Open: 1 | Done: 1", text)
        self.assertIn(f"{self.done_id} [DONE]", text)
        self.assertIn("  Cleanup pending", text)
        self.assertIn(f"  Resume: {resume}", text)
        self.assertNotIn("  Elapsed:", text)
        tasks, _status = self.load_closing(self.report("C10"))
        self.assertNotIn(self.done_id, tasks)
        self.assertIn(self.open_id, tasks)

    def test_cleanup_only_counts_as_done_with_accessible_hint_and_resume(self) -> None:
        self.check_cleanup_only(archived=False)

    def test_archived_cleanup_only_counts_as_done_with_accessible_hint_and_resume(self) -> None:
        self.check_cleanup_only(archived=True)

    def test_preceding_closure_steps_remain_closing(self) -> None:
        self.closing_project()
        for step in ("C6", "C7", "C9"):
            with self.subTest(step=step), mock.patch.object(
                    console, "closure_status", return_value=self.report(step)):
                snapshot = console.load_snapshot(self.project)
                task = next(item for item in snapshot.tasks if item.task_id == self.done_id)
                self.assertEqual(console._state_label(task), ("Closing", "working"))
                self.assertEqual(snapshot.done_count, 0)
                self.assertEqual(console._filter_counts(snapshot)["Closing"], 1)

    def test_missing_closure_fields_are_not_proof_of_completion(self) -> None:
        self.closing_project()
        for report in (None, {}, {"step": "C10"}, {"step": "C10", "resume": "cleanup"}):
            with self.subTest(report=report), mock.patch.object(
                    console, "closure_status", return_value=(report, False)):
                snapshot = console.load_snapshot(self.project)
                task = next(item for item in snapshot.tasks if item.task_id == self.done_id)
                self.assertEqual(console._state_label(task), ("Closing", "working"))
                self.assertEqual(snapshot.done_count, 0)
                self.assertEqual(task.progress_phase, "unavailable")

    def test_completed_task_without_closure_work_is_hidden_without_reading_closure(self) -> None:
        self.closing_project(worktree=False)
        tasks, status = self.load_closing(self.report("C7"))
        self.assertNotIn(self.done_id, tasks)
        status.assert_not_called()

    def test_closing_task_is_counted_and_filtered_as_closing_only(self) -> None:
        self.closing_project()
        with mock.patch.object(console, "closure_status", return_value=self.report("C7")):
            snapshot = console.load_snapshot(self.project)
        counts = console._filter_counts(snapshot)
        self.assertEqual(counts["Closing"], 1)
        self.assertEqual(counts["Ready"], 1)
        self.assertEqual(snapshot.done_count, 0)
        task = next(item for item in snapshot.tasks if item.task_id == self.done_id)
        self.assertEqual(console._state_label(task), ("Closing", "working"))
        self.assertEqual([item.task_id for item in console._visible_tasks(snapshot, "Closing", "")],
                         [self.done_id])
        self.assertNotIn(self.done_id, [
            item.task_id for item in console._visible_tasks(snapshot, "Review", "")])
        self.assertIsNotNone(console._tab_at(snapshot, 1, 1))

    def test_closing_task_does_not_launch_and_does_not_change_dependent_readiness(self) -> None:
        self.closing_project()
        tasks, _status = self.load_closing(self.report("C7"))
        self.assertIsNone(tasks[self.done_id].launch_command)
        self.assertEqual(tasks[self.open_id].readiness, "READY")
        self.assertEqual(tasks[self.open_id].dependency_states, ((self.done_id, "Done"),))

    def test_lifecycle_read_failure_keeps_the_task_with_unavailable_progress(self) -> None:
        self.closing_project()
        for error in (console.MeridianError("boom"), OSError("boom"), ValueError("boom")):
            with self.subTest(error=type(error).__name__):
                tasks, _status = self.load_closing(error=error)
                task = tasks[self.done_id]
                self.assertEqual(task.readiness, "CLOSING")
                self.assertEqual(task.progress_phase, "unavailable")
                self.assertIn("Closure state unavailable", task.next_action)

    def test_steps_that_are_not_closure_work_never_surface_a_prepare_resume(self) -> None:
        self.closing_project()
        tasks, _status = self.load_closing(self.report(
            "C4", "WRONG_WORKTREE", "meridian worktree prepare 1"))
        task = tasks[self.done_id]
        self.assertIsNone(task.closure_resume)
        self.assertIsNone(task.closure_stop_reason)
        self.assertEqual(task.progress_phase, "unavailable")

    def test_task_whose_phase_was_archived_at_stage_stays_visible(self) -> None:
        self.closing_project(archived=True)
        tasks, _status = self.load_closing(self.report("C9", None, "git push origin main"))
        self.assertEqual(tasks[self.done_id].progress_phase, "push pending")

    def test_once_output_lists_the_closing_task_with_the_same_facts(self) -> None:
        self.closing_project()
        state = console.ConsoleState(self.project)
        with mock.patch.object(console, "closure_status", return_value=self.report(
                "C9", "PUSH_PENDING", "git push origin main")), \
             mock.patch.object(console, "lifecycle_started_at", return_value="2026-01-01T00:00:00Z"):
            state.refresh()
        text = console.one_shot(state)
        self.assertIn("MERIDIAN | ", text)
        self.assertIn(f"{self.done_id} [CLOSING]", text)
        self.assertIn("  Closure stop: PUSH_PENDING", text)
        self.assertIn("  Resume: git push origin main", text)
        self.assertIn("  Progress: push pending", text)
        self.assertIn("  Remaining gates: Push main, Clean up worktree", text)
        self.assertNotIn("  Elapsed: unavailable", text)

    def test_detail_pane_shows_closing_progress(self) -> None:
        self.closing_project()
        tasks, _status = self.load_closing(self.report("C7", None, "run the selected candidate validation"))
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "working", "muted", "line", "action", "blocked")}
        lines = [value for value, _ in console._detail_lines(tasks[self.done_id], 80, palette)]
        self.assertIn("○ Closing", lines)
        self.assertIn("Lifecycle progress: candidate validation", lines)
        self.assertTrue(any(line.startswith("Elapsed cycle time:") for line in lines))


class LeanClosingTaskTest(ClosingTaskMixin, LeanEffectiveStateTest):
    done_id, open_id, done_token = "001", "002", "DONE"

    def closing_project(self, worktree: bool = True, archived: bool = False) -> None:
        self.setup_project({"001": "x", "002": " "}, {"002": "001"})
        if archived:
            queue = (self.project / "tasks/QUEUE.md").read_text(encoding="utf-8")
            lines = queue.splitlines(keepends=True)
            done_row = next(line for line in lines if "| 001 |" in line)
            self.write(self.project, "tasks/QUEUE.md", queue.replace(done_row, ""))
            self.write(self.project, "tasks/QUEUE_ARCHIVE.md", HEADER + done_row)
            self.commit(self.project, "archive")
        if worktree:
            self.worktree("task-001")


class GovernedClosingTaskTest(ClosingTaskMixin, GovernedEffectiveStateTest):
    done_id, open_id, done_token = "TASK-001", "TASK-002", "ACCEPTED"

    def closing_project(self, worktree: bool = True, archived: bool = False) -> None:
        self.setup_project([
            ("TASK-001", "ACCEPTED", "REQUIRED", "—"),
            ("TASK-002", "QUEUED", "REQUIRED", "TASK-001"),
        ])
        if archived:
            queue = (self.project / "tasks/QUEUE.md").read_text(encoding="utf-8")
            done_row = next(line for line in queue.splitlines(keepends=True) if "| TASK-001 |" in line)
            self.write(self.project, "tasks/QUEUE.md", queue.replace(done_row, ""))
            self.write(self.project, "tasks/QUEUE_ARCHIVE.md", self.header + done_row)
            self.commit(self.project, "archive")
        if worktree:
            self.worktree("task-001")

    def test_reserved_worktree_derives_in_progress_without_a_queue_edit(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        self.worktree("task-001")
        task = self.load()["TASK-001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertEqual(task.source, "branch task-001")
        self.assertIn("QUEUED", (self.project / "tasks/QUEUE.md").read_text(encoding="utf-8"))

    def test_record_ready_for_review_with_queued_row_is_derived_and_shows_progress(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.write_record(wt, "TASK-001", "READY_FOR_REVIEW")
        self.commit(wt, "ready")
        with mock.patch.object(console, "closure_status") as status, \
             mock.patch.object(console, "lifecycle_started_at",
                               return_value="2026-01-01T00:00:00Z"):
            task = self.load()["TASK-001"]
        status.assert_not_called()
        self.assertEqual((task.readiness, task.lifecycle),
                         ("READY FOR REVIEW", "ready_for_review"))
        self.assertEqual(task.launch_command, "Review TASK-001")
        self.assertEqual(task.progress_phase, "review pending")
        self.assertEqual(task.remaining_gates[0], "Independent review")
        self.assertTrue(task.shows_progress)
        self.assertNotEqual(console._elapsed(task.started_at), "unavailable")

    def test_ready_for_review_without_a_worktree_shows_no_progress(self) -> None:
        self.setup_project([("TASK-001", "READY_FOR_REVIEW", "REQUIRED", "—")])
        task = self.load()["TASK-001"]
        self.assertFalse(task.shows_progress)
        self.assertEqual(task.progress_phase, "unavailable")

    def test_review_gate_progress_phase(self) -> None:
        phase, gates = console._lifecycle_progress("C3", True)
        self.assertEqual(phase, "review pending")
        self.assertEqual(gates[0], "Independent review")


class BackgroundRefreshTest(unittest.TestCase):
    def wait_idle(self, state: console.ConsoleState) -> None:
        deadline = time.monotonic() + 5
        while state.refreshing and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(state.refreshing)

    def snapshot(self, marker: str) -> console.Snapshot:
        return console.Snapshot(
            project=Path("/p"), queue=Path("/p/q"), branch=marker, git_summary="clean",
            git_changes=0, tasks=(), done_count=0,
        )

    def test_refresh_is_non_blocking_single_flight_and_published_atomically(self) -> None:
        state = console.ConsoleState(Path("/p"))
        state.snapshot = self.snapshot("old")
        release = threading.Event()
        started = threading.Event()
        returned = threading.Event()

        def slow(_project, _identities, _deliveries=None):
            started.set()
            self.assertTrue(returned.wait(5), "start_refresh must return before loading completes")
            release.wait(5)
            return self.snapshot("new")

        with mock.patch.object(console, "load_snapshot", side_effect=slow) as loader:
            self.assertTrue(state.start_refresh())
            returned.set()
            self.assertTrue(started.wait(5))
            self.assertFalse(state.start_refresh(), "refreshes must not overlap")
            state.apply_pending()
            self.assertEqual(state.snapshot.branch, "old")
            release.set()
            self.wait_idle(state)
            self.assertEqual(state.snapshot.branch, "old", "published only when applied")
            state.apply_pending()
            self.assertEqual(state.snapshot.branch, "new")
            self.assertIsNone(state.error)
            self.assertEqual(loader.call_count, 1)

    def test_failed_background_refresh_keeps_last_snapshot_and_marks_it_stale(self) -> None:
        state = console.ConsoleState(Path("/p"))
        state.snapshot = self.snapshot("old")
        with mock.patch.object(console, "load_snapshot",
                               side_effect=console.ConsoleError("boom")):
            self.assertTrue(state.start_refresh())
            self.wait_idle(state)
        state.apply_pending()
        self.assertEqual(state.snapshot.branch, "old")
        self.assertEqual(state.error, "boom")
        with mock.patch.object(console, "load_snapshot", side_effect=RuntimeError("bug")):
            self.assertTrue(state.start_refresh())
            self.wait_idle(state)
        state.apply_pending()
        self.assertEqual(state.snapshot.branch, "old")
        self.assertIn("bug", state.error)
        with mock.patch.object(console, "load_snapshot", return_value=self.snapshot("fresh")):
            self.assertTrue(state.start_refresh())
            self.wait_idle(state)
        state.apply_pending()
        self.assertEqual((state.snapshot.branch, state.error), ("fresh", None))


    def test_launch_runs_off_the_caller_thread_and_is_single_flight(self) -> None:
        state = console.ConsoleState(Path("/p"))
        task = mock.Mock(task_id="001")
        release = threading.Event()
        started = threading.Event()

        def slow(_state, _task, _agent, _dirty):
            started.set()
            release.wait(5)
            return True, "Started"

        with mock.patch.object(console, "_launch_selected", side_effect=slow), \
             mock.patch.object(console, "load_snapshot",
                               side_effect=AssertionError("full snapshot")) as full:
            begun = time.monotonic()
            self.assertTrue(state.start_launch(task, "codex"))
            self.assertLess(time.monotonic() - begun, 1)
            self.assertTrue(started.wait(5))
            self.assertTrue(state.launching)
            self.assertFalse(state.start_launch(task, "claude"), "one launch in flight")
            self.assertIsNone(state.take_launch_result())
            release.set()
            deadline = time.monotonic() + 5
            while state.launching and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(state.take_launch_result(), (True, "Started"))
            self.assertIsNone(state.take_launch_result())
            full.assert_not_called()

    def test_launch_failure_or_crash_is_reported_not_raised(self) -> None:
        state = console.ConsoleState(Path("/p"))
        task = mock.Mock(task_id="001")
        for effect in (RuntimeError("boom"), console.ConsoleError("git timed out")):
            with self.subTest(effect=str(effect)), \
                 mock.patch.object(console, "load_task", side_effect=effect):
                self.assertTrue(state.start_launch(task, "codex"))
                deadline = time.monotonic() + 5
                while state.launching and time.monotonic() < deadline:
                    time.sleep(0.01)
                success, message = state.take_launch_result()
                self.assertFalse(success)
                self.assertTrue(message)

    def test_key_handler_returns_while_snapshot_and_osascript_are_slow(self) -> None:
        state = console.ConsoleState(Path("/p"))
        task = mock.Mock(task_id="001")
        gate = threading.Event()

        def blocked(*_args, **_kwargs):
            gate.wait(5)
            raise AssertionError("must not run on the caller thread")

        with mock.patch.object(console, "load_task", side_effect=blocked), \
             mock.patch.object(console.subprocess, "run", side_effect=blocked):
            begun = time.monotonic()
            self.assertTrue(state.start_launch(task, "codex"))
            self.assertLess(time.monotonic() - begun, 1)
            self.assertTrue(state.launching)
            gate.set()
            deadline = time.monotonic() + 5
            while state.launching and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertFalse(state.take_launch_result()[0])


class WorkflowModeLockTest(RepoCase):
    def test_missing_unknown_and_double_locks_are_explicit_errors(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").unlink()
        with self.assertRaisesRegex(console.ConsoleError, "PROJECT_WORKFLOW.md is missing") as raised:
            console.load_snapshot(self.project)
        self.assertNotIn("--mode", str(raised.exception))
        self.write(self.project, "PROJECT_WORKFLOW.md", "# nothing\n")
        with self.assertRaisesRegex(console.ConsoleError, "no recognized mode lock"):
            console.load_snapshot(self.project)
        self.write(self.project, "PROJECT_WORKFLOW.md", "LEAN_DELIVERY GOVERNED_SDD\n")
        with self.assertRaisesRegex(console.ConsoleError, "both mode locks"):
            console.load_snapshot(self.project)


class MachineStateConsoleTest(RepoCase):
    lock = "GOVERNED_SDD"
    header = GovernedEffectiveStateTest.header
    setup_project = GovernedEffectiveStateTest.setup_project
    write_record = GovernedEffectiveStateTest.write_record

    def state(self, root: Path, task_id: str, status: str, *, workflow="governed-sdd",
              verdict=None, required=True) -> None:
        route = (["QUEUED", "DONE"] if workflow == "lean-delivery" else
                 ["QUEUED", "IN_PROGRESS", "READY_FOR_REVIEW", status])
        route = route[:route.index(status) + 1]
        snapshot = {
            "version": 1, "task_id": task_id, "workflow": workflow, "status": status,
            "transitions": [{"from": before, "to": after, "commit": "a" * 40,
                             "at": "2026-10-11T12:00:00Z"}
                            for before, after in zip(route, route[1:])],
        }
        if verdict:
            snapshot["review"] = {"required": required, "verdict": verdict, "attempt": 1,
                                  "reviewed_commit": "a" * 40, "approved_by": "reviewer"}
        self.write(root, f".meridian/tasks/{task_id}.json", json.dumps(snapshot))

    def test_state_wins_over_queue_record_and_review_prose(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.state(wt, "TASK-001", "CHANGES_REQUESTED", verdict="CHANGES_REQUESTED")
        self.write_record(wt, "TASK-001", "ACCEPTED")
        self.write(wt, "tasks/reviews/TASK-001.md", "## Attempt 9 — APPROVE\n")
        self.commit(wt)
        before = self.refs_and_status()
        task = self.load()["TASK-001"]
        self.assertEqual(self.refs_and_status(), before)
        self.assertEqual(task.status, "CHANGES_REQUESTED")
        self.assertEqual(task.review_verdict, "CHANGES_REQUESTED")
        self.assertTrue(task.changes_requested)
        self.assertFalse(task.legacy)
        self.assertIsNone(task.mismatch)
        self.assertEqual(task.launch_command, "Address review TASK-001")

    def test_state_is_read_before_even_an_unknown_queue_status(self) -> None:
        self.setup_project([("TASK-001", "BROKEN_PROJECTION", "NOT REQUIRED", "—")])
        self.state(self.project, "TASK-001", "READY_FOR_REVIEW")
        task = self.load()["TASK-001"]
        self.assertEqual(task.status, "READY_FOR_REVIEW")
        self.assertEqual(task.review, "REQUIRED")
        self.assertIsNone(task.launch_command)
        self.assertEqual(task.readiness, "PENDING DELIVERY/CHANGES")

    def test_invalid_state_is_per_task_and_never_falls_back(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—"),
                            ("TASK-002", "QUEUED", "REQUIRED", "—")])
        self.write(self.project, ".meridian/tasks/TASK-001.json", '{"version": 99}')
        tasks = self.load()
        invalid, legacy = tasks["TASK-001"], tasks["TASK-002"]
        self.assertIn("TASK_STATE_INVALID", invalid.state_error)
        self.assertIn("state.task_id", invalid.state_error)
        self.assertIsNone(invalid.launch_command)
        self.assertFalse(invalid.legacy)
        self.assertTrue(legacy.legacy)
        self.assertEqual(legacy.launch_command, "Proceed with TASK-002")
        state = console.ConsoleState(self.project)
        state.snapshot = console.load_snapshot(self.project)
        output = console.one_shot(state)
        self.assertIn("State error: BLOCKED TASK_STATE_INVALID", output)
        self.assertIn("Status: QUEUED | Verdict: none | legacy", output)
        palette = dict.fromkeys(("base", "text", "title", "muted", "blocked", "action", "working", "ready", "unknown", "line"), 0)
        self.assertIn("legacy", [text for text, _style in console._detail_lines(legacy, 100, palette)])

    def test_uncommitted_invalid_worktree_state_blocks_only_that_task(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.state(wt, "TASK-001", "IN_PROGRESS")
        self.commit(wt)
        self.write(wt, ".meridian/tasks/TASK-001.json", "invalid JSON")
        task = self.load()["TASK-001"]
        self.assertIn("TASK_STATE_INVALID", task.state_error)
        self.assertIsNone(task.launch_command)

    def test_archived_state_files_are_never_opened_or_enumerated(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        self.state(self.project, "TASK-001", "IN_PROGRESS")
        archived = self.header + "".join(
            f"| {n} | OLD-{n} | P1 | ACCEPTED | REQUIRED | — | — |\n" for n in range(150))
        self.write(self.project, "tasks/QUEUE_ARCHIVE.md", archived)
        for n in range(150):
            self.write(self.project, f".meridian/tasks/OLD-{n}.json", "invalid archived state")
        original = Path.read_text
        opened = []
        def observe(path, *args, **kwargs):
            if path.parent.name == "tasks" and path.suffix == ".json":
                opened.append(path.name)
            return original(path, *args, **kwargs)
        original_glob = Path.glob
        def observe_glob(path, *args, **kwargs):
            if path == self.project / ".meridian/tasks":
                raise AssertionError("state directory scan")
            return original_glob(path, *args, **kwargs)
        with mock.patch.object(Path, "read_text", observe), mock.patch.object(Path, "glob", observe_glob):
            snapshot = console.load_snapshot(self.project)
        self.assertEqual(opened, ["TASK-001.json"])
        self.assertEqual(snapshot.done_count, 150)
        self.assertEqual(snapshot.tasks[0].status, "IN_PROGRESS")

    def test_state_on_branch_without_worktree_and_spike_terminal_state(self) -> None:
        self.setup_project([("TASK-001", "QUEUED", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.state(wt, "TASK-001", "ACCEPTED", verdict="APPROVE")
        self.commit(wt)
        self.git(self.project, "worktree", "remove", str(wt))
        task = self.load()["TASK-001"]
        self.assertEqual(task.status, "ACCEPTED")
        self.assertEqual(task.review_verdict, "APPROVE")
        self.assertFalse(task.legacy)
        self.assertIn("branch task-001", task.source)
        self.write(self.project, "tasks/TASK-001.md", "# Task TASK-001 — Spike\nClass: SPIKE\nStatus: QUEUED\n")
        self.write(self.project, ".meridian/tasks/TASK-001.json", json.dumps({
            "version": 1, "task_id": "TASK-001", "workflow": "governed-sdd", "status": "ANSWERED",
            "transitions": [{"from": before, "to": after, "commit": "a" * 40,
                             "at": "2026-10-11T12:00:00Z"}
                            for before, after in [("QUEUED", "IN_PROGRESS"), ("IN_PROGRESS", "ANSWERED")]],
        }))
        snapshot = console.load_snapshot(self.project)
        self.assertEqual(snapshot.done_count, 1)
        self.assertEqual(snapshot.tasks, ())

    def test_lean_machine_state_keeps_worktree_derived_progress(self) -> None:
        self.write(self.project, "PROJECT_WORKFLOW.md", "# LEAN_DELIVERY\n")
        LeanEffectiveStateTest.setup_project(self, {"001": " "})
        self.state(self.project, "001", "QUEUED", workflow="lean-delivery")
        self.commit(self.project)
        self.worktree("task-001")
        task = self.load()["001"]
        self.assertEqual((task.status, task.lifecycle), ("QUEUED", "in_progress"))
        self.assertFalse(task.legacy)

    queue = LeanEffectiveStateTest.queue


class SnapshotCostTest(RepoCase):
    """One worktree listing, resolved identities, and cached delivery gates."""

    lock = "GOVERNED_SDD"
    header = GovernedEffectiveStateTest.header
    setup_project = GovernedEffectiveStateTest.setup_project
    write_record = GovernedEffectiveStateTest.write_record
    state = MachineStateConsoleTest.state

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
        calls = self.run_snapshot(lambda: console.load_snapshot(self.project))
        self.assertEqual(len(self.listings(calls)), 1)
        task = console.load_task(self.project, "TASK-003")
        self.assertIsNotNone(task)
        self.assertEqual(len(self.listings(self.run_snapshot(
            lambda: console.load_task(self.project, "TASK-003")))), 1)

    def test_closure_readers_receive_the_cached_identity(self) -> None:
        self.populate()
        cache = console.IdentityCache()
        seen: dict[str, list[object]] = {"closure": [], "started": []}
        real_closure, real_started = console.closure_status, console.lifecycle_started_at

        def closure(*args, **kwargs):
            seen["closure"].append(kwargs.get("identity"))
            return real_closure(*args, **kwargs)

        def started(*args, **kwargs):
            seen["started"].append(kwargs.get("identity"))
            return real_started(*args, **kwargs)

        with mock.patch.object(console, "closure_status", side_effect=closure), \
             mock.patch.object(console, "lifecycle_started_at", side_effect=started), \
             mock.patch.object(Path, "cwd", return_value=self.project):
            console.load_snapshot(self.project, cache)
        for readers in seen.values():
            self.assertTrue(readers)
            for identity in readers:
                self.assertIsNotNone(identity)
                self.assertIs(identity, cache.resolve(self.project, identity.canonical_id))

    def test_lifecycle_readers_skip_resolution_when_given_an_identity(self) -> None:
        import meridian
        self.populate()
        identity = meridian.resolve_task_identity(self.project, "TASK-001", "existing")
        with mock.patch.object(Path, "cwd", return_value=self.project), \
             mock.patch.object(meridian, "resolve_task_identity",
                               side_effect=AssertionError("resolved again")):
            report, _ready = meridian.closure_status(
                "TASK-001", None, self.project, identity=identity)
            self.assertEqual(report["task_id"], "TASK-001")
            # No lifecycle state was prepared, so the read ends on that, not on resolution.
            with self.assertRaisesRegex(meridian.MeridianError, "worktree lifecycle state"):
                meridian.lifecycle_started_at("TASK-001", self.project, identity=identity)

    def test_snapshot_is_identical_with_and_without_caches(self) -> None:
        self.populate()
        with mock.patch.object(Path, "cwd", return_value=self.project):
            plain = console.load_snapshot(self.project)
            identities, deliveries = console.IdentityCache(), console.DeliveryCache()
            cold = console.load_snapshot(self.project, identities, deliveries)
            warm = console.load_snapshot(self.project, identities, deliveries)
        self.assertEqual({task.task_id for task in plain.tasks}, {"TASK-001", "TASK-002", "TASK-003"})
        self.assertEqual(plain, cold)
        self.assertEqual(plain, warm)

    def review_ready(self) -> tuple[Path, console.DeliveryCache, mock.Mock]:
        wt = self.populate()["TASK-002"]
        gate = mock.Mock(side_effect=console.MeridianError("evidence is incomplete"))
        return wt, console.DeliveryCache(), gate

    def load_with(self, deliveries: console.DeliveryCache, gate: mock.Mock) -> console.Task:
        with mock.patch.object(console, "delivery_readiness", gate), \
             mock.patch.object(Path, "cwd", return_value=self.project):
            snapshot = console.load_snapshot(self.project, console.IdentityCache(), deliveries)
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
        gate.side_effect = console.MeridianError("handoff changed")
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
