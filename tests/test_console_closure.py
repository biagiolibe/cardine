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

import test_console_states as state_tests

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
            owner_console_snapshot, "closure_status", return_value=report, side_effect=error)
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
        state = owner_console_state.ConsoleState(self.project)
        with mock.patch.object(owner_console_snapshot, "closure_status", return_value=self.report(
                "C10", None, resume)) as status:
            state.refresh()
        self.assertEqual(self.refs_and_status(), before)
        snapshot = state.snapshot
        task = next(item for item in snapshot.tasks if item.task_id == self.done_id)
        self.assertEqual(status.call_count, 1)
        self.assertEqual(snapshot.done_count, 1)
        self.assertEqual(owner_console_render._filter_counts(snapshot)["Closing"], 0)
        self.assertEqual(owner_console_render._visible_tasks(snapshot, "Closing", ""), [])
        self.assertIn(task, owner_console_render._visible_tasks(snapshot, "All", self.done_id))
        self.assertEqual(owner_console_render._state_label(task), ("Done", "muted"))
        self.assertEqual((task.readiness, task.lifecycle), ("DONE", "done"))
        self.assertTrue(task.cleanup_pending)
        self.assertFalse(task.shows_progress)
        self.assertIsNone(task.launch_command)
        self.assertEqual(task.next_action, resume)
        self.assertEqual(task.closure_resume, resume)
        self.assertEqual(task.progress_phase, "cleanup pending")
        self.assertEqual(owner_console_render._filter_counts(snapshot)["Working"], 0)
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "working", "muted", "line", "action", "blocked")}
        lines = [value for value, _ in owner_console_render._detail_lines(task, 200, palette)]
        self.assertIn("○ Done", lines)
        self.assertIn("Cleanup pending", lines)
        self.assertIn(f"Resume: {resume}", lines)
        text = owner_console_state.one_shot(state)
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
                    owner_console_snapshot, "closure_status", return_value=self.report(step)):
                snapshot = owner_console_snapshot.load_snapshot(self.project)
                task = next(item for item in snapshot.tasks if item.task_id == self.done_id)
                self.assertEqual(owner_console_render._state_label(task), ("Closing", "working"))
                self.assertEqual(snapshot.done_count, 0)
                self.assertEqual(owner_console_render._filter_counts(snapshot)["Closing"], 1)

    def test_missing_closure_fields_are_not_proof_of_completion(self) -> None:
        self.closing_project()
        for report in (None, {}, {"step": "C10"}, {"step": "C10", "resume": "cleanup"}):
            with self.subTest(report=report), mock.patch.object(
                    owner_console_snapshot, "closure_status", return_value=(report, False)):
                snapshot = owner_console_snapshot.load_snapshot(self.project)
                task = next(item for item in snapshot.tasks if item.task_id == self.done_id)
                self.assertEqual(owner_console_render._state_label(task), ("Closing", "working"))
                self.assertEqual(snapshot.done_count, 0)
                self.assertEqual(task.progress_phase, "unavailable")

    def test_completed_task_without_closure_work_is_hidden_without_reading_closure(self) -> None:
        self.closing_project(worktree=False)
        tasks, status = self.load_closing(self.report("C7"))
        self.assertNotIn(self.done_id, tasks)
        status.assert_not_called()

    def test_closing_task_is_counted_and_filtered_as_closing_only(self) -> None:
        self.closing_project()
        with mock.patch.object(owner_console_snapshot, "closure_status", return_value=self.report("C7")):
            snapshot = owner_console_snapshot.load_snapshot(self.project)
        counts = owner_console_render._filter_counts(snapshot)
        self.assertEqual(counts["Closing"], 1)
        self.assertEqual(counts["Ready"], 1)
        self.assertEqual(snapshot.done_count, 0)
        task = next(item for item in snapshot.tasks if item.task_id == self.done_id)
        self.assertEqual(owner_console_render._state_label(task), ("Closing", "working"))
        self.assertEqual([item.task_id for item in owner_console_render._visible_tasks(snapshot, "Closing", "")],
                         [self.done_id])
        self.assertNotIn(self.done_id, [
            item.task_id for item in owner_console_render._visible_tasks(snapshot, "Review", "")])
        self.assertIsNotNone(owner_console_render._tab_at(snapshot, 1, 1))

    def test_closing_task_does_not_launch_and_does_not_change_dependent_readiness(self) -> None:
        self.closing_project()
        tasks, _status = self.load_closing(self.report("C7"))
        self.assertIsNone(tasks[self.done_id].launch_command)
        self.assertEqual(tasks[self.open_id].readiness, "READY")
        self.assertEqual(tasks[self.open_id].dependency_states, ((self.done_id, "Done"),))

    def test_lifecycle_read_failure_keeps_the_task_with_unavailable_progress(self) -> None:
        self.closing_project()
        for error in (owner_shared_errors.MeridianError("boom"), OSError("boom"), ValueError("boom")):
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
        state = owner_console_state.ConsoleState(self.project)
        with mock.patch.object(owner_console_snapshot, "closure_status", return_value=self.report(
                "C9", "PUSH_PENDING", "git push origin main")), \
             mock.patch.object(owner_console_snapshot, "lifecycle_started_at", return_value="2026-01-01T00:00:00Z"):
            state.refresh()
        text = owner_console_state.one_shot(state)
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
        lines = [value for value, _ in owner_console_render._detail_lines(tasks[self.done_id], 80, palette)]
        self.assertIn("○ Closing", lines)
        self.assertIn("Lifecycle progress: candidate validation", lines)
        self.assertTrue(any(line.startswith("Elapsed cycle time:") for line in lines))



class LeanClosingTaskTest(ClosingTaskMixin, state_tests.LeanEffectiveStateTest):
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



class GovernedClosingTaskTest(ClosingTaskMixin, state_tests.GovernedEffectiveStateTest):
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
        with mock.patch.object(owner_console_snapshot, "closure_status") as status, \
             mock.patch.object(owner_console_snapshot, "lifecycle_started_at",
                               return_value="2026-01-01T00:00:00Z"):
            task = self.load()["TASK-001"]
        status.assert_not_called()
        self.assertEqual((task.readiness, task.lifecycle),
                         ("READY FOR REVIEW", "ready_for_review"))
        self.assertEqual(task.launch_command, "Review TASK-001")
        self.assertEqual(task.progress_phase, "review pending")
        self.assertEqual(task.remaining_gates[0], "Independent review")
        self.assertTrue(task.shows_progress)
        self.assertNotEqual(owner_console_render._elapsed(task.started_at), "unavailable")

    def test_ready_for_review_without_a_worktree_shows_no_progress(self) -> None:
        self.setup_project([("TASK-001", "READY_FOR_REVIEW", "REQUIRED", "—")])
        task = self.load()["TASK-001"]
        self.assertFalse(task.shows_progress)
        self.assertEqual(task.progress_phase, "unavailable")

    def test_review_gate_progress_phase(self) -> None:
        phase, gates = owner_console_snapshot._lifecycle_progress("C3", True)
        self.assertEqual(phase, "review pending")
        self.assertEqual(gates[0], "Independent review")



if __name__ == "__main__":
    unittest.main()
