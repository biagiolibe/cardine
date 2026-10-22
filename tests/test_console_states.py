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

class LeanEffectiveStateTest(support.LeanEffectiveStateFixture):



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
        with mock.patch.object(owner_console_snapshot, "closure_status", return_value=(report, False)):
            task = self.load()["001"]
        self.assertEqual(task.closure_stop_reason, "REVIEW_REQUIRED")
        self.assertEqual(task.closure_resume, "After approval, continue at C4")
        palette = {name: 0 for name in (
            "base", "text", "title", "ready", "working", "muted", "line", "action", "blocked"
        )}
        lines = [value for value, _ in owner_console_render._detail_lines(task, 60, palette)]
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
            task = owner_console_models.Task("001", "Task", "in_progress", (), (), None, (), (),
                                readiness="IN PROGRESS", lifecycle="in_progress",
                                closure_stop_reason=reason, closure_resume="resume command")
            lines = [value for value, _ in owner_console_render._detail_lines(task, 60, palette)]
            self.assertIn(f"Closure stop: {reason}", lines)
            self.assertIn("Resume: resume command", lines)

    def test_queued_tasks_do_not_read_closure_status(self) -> None:
        self.setup_project({"001": " ", "002": " "})
        with mock.patch.object(owner_console_snapshot, "closure_status") as status:
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
        self.assertIn("working tree queued", task.mismatch or "")

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
        self.set_branch_status(self.worktree("task-001"), "001", "x", handoff="done")
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle), ("READY FOR REVIEW", "ready_for_review"))
        self.assertEqual(owner_console_render._state_label(task), ("Review", "ready"))
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
        self.set_branch_status(wt, "001", "x", handoff="done")
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
        self.assertIn("main in_progress", task.mismatch or "")
        self.assertIn("task-001 queued", task.mismatch or "")
        self.assertIsNone(task.launch_command)
        self.assertEqual(owner_console_render._state_label(task)[0], "Mismatch")

    def test_dependencies_are_satisfied_by_integrated_state_only(self) -> None:
        self.setup_project({"001": " ", "002": " "}, deps={"002": "001"})
        self.set_branch_status(self.worktree("task-001"), "001", "x", handoff="done")
        tasks = self.load()
        self.assertEqual(tasks["001"].readiness, "READY FOR REVIEW")
        self.assertEqual(tasks["002"].readiness, "BLOCKED: 001")
        self.assertIsNone(tasks["002"].launch_command)

    def test_milestone_identity_resolves_the_task_branch(self) -> None:
        self.write(self.project, ".cardine/task-identity.json",
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
        state = owner_console_state.ConsoleState(self.project)
        state.refresh()
        output = owner_console_state.one_shot(state)
        self.assertIn("State from: branch task-001", output)
        self.assertIn("Markers: active writer", output)
        self.assertIn("Mismatch: main in_progress, task-002 queued", output)



class GovernedEffectiveStateTest(support.GovernedEffectiveStateFixture):




    def test_queue_statuses_map_to_normalized_phases_and_dependencies(self) -> None:
        self.setup_project([
            ("TASK-001", "done", "REQUIRED", "—"),
            ("TASK-002", "queued", "REQUIRED", "TASK-001"),
            ("TASK-003", "in_progress", "REQUIRED", "—"),
            ("TASK-004", "in_review", "REQUIRED", "—"),
            ("TASK-005", "done", "SPIKE", "—"),
            ("TASK-006", "queued", "REQUIRED", "TASK-005"),
            ("TASK-007", "done", "SPIKE", "—"),
            ("TASK-008", "queued", "REQUIRED", "TASK-007"),
        ])
        for task_id, outcome in (("TASK-005", "ANSWERED"), ("TASK-007", "INCONCLUSIVE")):
            self.write_record(self.project, task_id, "done")
            path = self.project / f"tasks/{task_id}.md"
            path.write_text(path.read_text() + "\nClass: spike\n")
            support.MachineStateConsoleFixture.state(self, self.project, task_id, "done", required=False)
            state_path = self.project / f".cardine/tasks/{task_id}.json"
            snapshot = json.loads(state_path.read_text())
            snapshot["outcome"] = outcome
            state_path.write_text(json.dumps(snapshot))
        self.commit(self.project, "landed spike outcomes")
        tasks = self.load()
        self.assertEqual({tid: t.lifecycle for tid, t in tasks.items()}, {
            "TASK-002": "todo", "TASK-003": "in_progress", "TASK-004": "ready_for_review",
            "TASK-006": "todo", "TASK-008": "todo",
        })
        self.assertEqual(tasks["TASK-002"].readiness, "READY")
        self.assertEqual(tasks["TASK-006"].readiness, "READY")
        self.assertEqual(tasks["TASK-008"].readiness, "BLOCKED: TASK-007")
        self.assertEqual(tasks["TASK-004"].title, "TASK-004")
        self.assertEqual(tasks["TASK-003"].launch_command, "Proceed with TASK-003")
        self.assertEqual(tasks["TASK-004"].launch_command, "Review TASK-004")

    def test_dependency_on_unaccepted_task_is_blocked(self) -> None:
        self.setup_project([
            ("TASK-001", "in_review", "REQUIRED", "—"),
            ("TASK-002", "queued", "REQUIRED", "TASK-001"),
        ])
        self.assertEqual(self.load()["TASK-002"].readiness, "BLOCKED: TASK-001")

    def test_unrecognized_status_is_an_explicit_error(self) -> None:
        self.setup_project([("TASK-001", "CHANGES_REQUESTED", "REQUIRED", "—")])
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "Unknown task status"):
            owner_console_snapshot.load_snapshot(self.project)

    def test_ready_for_review_requires_record_queue_and_review_agreement(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.set_branch(wt, "TASK-001", "in_review")
        task = self.load()["TASK-001"]
        self.assertEqual((task.readiness, task.lifecycle), ("READY FOR REVIEW", "ready_for_review"))
        self.assertEqual(task.source, "branch task-001")
        self.set_branch(wt, "TASK-001", "in_review", record="in_progress")
        task = self.load()["TASK-001"]
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("task record in_progress", task.mismatch or "")
        self.assertIsNone(task.launch_command)

    def test_ready_for_review_without_required_review_is_a_mismatch(self) -> None:
        self.setup_project([("TASK-001", "queued", "NOT_REQUIRED", "—")])
        self.set_branch(self.worktree("task-001"), "TASK-001", "in_review")
        task = self.load()["TASK-001"]
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("Review NOT_REQUIRED", task.mismatch or "")

    def test_latest_changes_requested_attempt_marks_in_progress_task(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        review = (
            "# Review Record — TASK-001\n\n## Attempt 1 — CHANGES_REQUESTED\n\n- x\n\n"
            "## Attempt 2 — CHANGES_REQUESTED\n\n- y\n"
        )
        self.set_branch(wt, "TASK-001", "in_progress", review=review)
        task = self.load()["TASK-001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertTrue(task.changes_requested)
        self.assertEqual(task.markers, ("changes requested",))
        self.assertEqual(task.launch_command, "Address review TASK-001")
        approved = review + "\n## Attempt 3 — APPROVE\n\n- z\n"
        self.set_branch(wt, "TASK-001", "in_progress", review=approved)
        self.assertFalse(self.load()["TASK-001"].changes_requested)

    def test_resubmission_after_changes_requested_is_ready_for_review(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        review = "# Review Record — TASK-001\n\n## Attempt 1 — CHANGES_REQUESTED\n\n- x\n"
        self.set_branch(self.worktree("task-001"), "TASK-001", "in_review", review=review)
        task = self.load()["TASK-001"]
        self.assertEqual(task.lifecycle, "ready_for_review")
        self.assertFalse(task.changes_requested)

    def test_branch_accepted_is_done_on_branch_and_does_not_unblock_dependents(self) -> None:
        self.setup_project([
            ("TASK-001", "queued", "REQUIRED", "—"),
            ("TASK-002", "queued", "REQUIRED", "TASK-001"),
        ])
        self.set_branch(self.worktree("task-001"), "TASK-001", "in_progress", review="## Attempt 1 — APPROVE\n")
        tasks = self.load()
        self.assertEqual(tasks["TASK-001"].readiness, "IN PROGRESS")
        self.assertEqual(tasks["TASK-002"].readiness, "BLOCKED: TASK-001")

    def test_dirty_worktree_shows_active_writer(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.set_branch(wt, "TASK-001", "in_progress")
        self.write(wt, "scratch.txt", "uncommitted")
        task = self.load()["TASK-001"]
        self.assertTrue(task.active_writer)
        self.assertEqual(task.readiness, "IN PROGRESS")
        self.assertEqual(
            task.launch_command,
            "Proceed with TASK-001 (Resume: run cardine worktree prepare TASK-001 --resume --format json)",
        )

    def test_uncommitted_in_progress_row_supersedes_committed_queued(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        queue = (wt / "tasks/QUEUE.md").read_text(encoding="utf-8").replace(
            "| TASK-001 | P1 | queued", "| TASK-001 | P1 | in_progress")
        self.write(wt, "tasks/QUEUE.md", queue)
        task = self.load()["TASK-001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertEqual(task.source, "uncommitted task-001")



class WorkflowModeLockTest(support.RepoCase):
    def test_missing_unknown_and_malformed_configurations_are_explicit_errors(self) -> None:
        (self.project / ".cardine/project.json").unlink()
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "missing project configuration") as raised:
            owner_console_snapshot.load_snapshot(self.project)
        self.assertNotIn("--mode", str(raised.exception))
        self.write(self.project, ".cardine/project.json", '{"version": 1, "preset": "unknown"}')
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "preset"):
            owner_console_snapshot.load_snapshot(self.project)
        self.write(self.project, ".cardine/project.json", "{")
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "invalid project declaration"):
            owner_console_snapshot.load_snapshot(self.project)


class MachineStateConsoleTest(support.MachineStateConsoleFixture):


    def test_state_wins_over_queue_record_and_review_prose(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.state(wt, "TASK-001", "in_progress", verdict="CHANGES_REQUESTED")
        self.write_record(wt, "TASK-001", "done")
        self.write(wt, "tasks/reviews/TASK-001.md", "## Attempt 9 — APPROVE\n")
        self.commit(wt)
        before = self.refs_and_status()
        task = self.load()["TASK-001"]
        self.assertEqual(self.refs_and_status(), before)
        self.assertEqual(task.status, "in_progress")
        self.assertEqual(task.review_verdict, "CHANGES_REQUESTED")
        self.assertTrue(task.changes_requested)
        self.assertFalse(task.legacy)
        self.assertIsNone(task.mismatch)
        self.assertEqual(task.launch_command, "Address review TASK-001")

    def test_state_is_read_before_even_an_unknown_queue_status(self) -> None:
        self.setup_project([("TASK-001", "BROKEN_PROJECTION", "NOT REQUIRED", "—")])
        self.state(self.project, "TASK-001", "in_review")
        task = self.load()["TASK-001"]
        self.assertEqual(task.status, "in_review")
        self.assertEqual(task.review, "REQUIRED")
        self.assertIsNone(task.launch_command)
        self.assertEqual(task.readiness, "PENDING DELIVERY/CHANGES")

    def test_invalid_state_is_per_task_and_never_falls_back(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—"),
                            ("TASK-002", "queued", "REQUIRED", "—")])
        self.write(self.project, ".cardine/tasks/TASK-001.json", '{"version": 99}')
        tasks = self.load()
        invalid, legacy = tasks["TASK-001"], tasks["TASK-002"]
        self.assertIn("TASK_STATE_INVALID", invalid.state_error)
        self.assertIn("state.task_id", invalid.state_error)
        self.assertIsNone(invalid.launch_command)
        self.assertFalse(invalid.legacy)
        self.assertTrue(legacy.legacy)
        self.assertEqual(legacy.launch_command, "Proceed with TASK-002")
        state = owner_console_state.ConsoleState(self.project)
        state.snapshot = owner_console_snapshot.load_snapshot(self.project)
        output = owner_console_state.one_shot(state)
        self.assertIn("State error: BLOCKED TASK_STATE_INVALID", output)
        self.assertIn("Status: queued | Verdict: none | legacy", output)
        palette = dict.fromkeys(("base", "text", "title", "muted", "blocked", "action", "working", "ready", "unknown", "line"), 0)
        self.assertIn("legacy", [text for text, _style in owner_console_render._detail_lines(legacy, 100, palette)])

    def test_uncommitted_invalid_worktree_state_blocks_only_that_task(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.state(wt, "TASK-001", "in_progress")
        self.commit(wt)
        self.write(wt, ".cardine/tasks/TASK-001.json", "invalid JSON")
        task = self.load()["TASK-001"]
        self.assertIn("TASK_STATE_INVALID", task.state_error)
        self.assertIsNone(task.launch_command)

    def test_archived_state_files_are_never_opened_or_enumerated(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        self.state(self.project, "TASK-001", "in_progress")
        archived = self.header + "".join(
            f"| {n} | OLD-{n} | P1 | done | REQUIRED | — | — |\n" for n in range(150))
        self.write(self.project, "tasks/QUEUE_ARCHIVE.md", archived)
        for n in range(150):
            self.write(self.project, f".cardine/tasks/OLD-{n}.json", "invalid archived state")
        original = Path.read_text
        opened = []
        def observe(path, *args, **kwargs):
            if path.parent.name == "tasks" and path.suffix == ".json":
                opened.append(path.name)
            return original(path, *args, **kwargs)
        original_glob = Path.glob
        def observe_glob(path, *args, **kwargs):
            if path == self.project / ".cardine/tasks":
                raise AssertionError("state directory scan")
            return original_glob(path, *args, **kwargs)
        with mock.patch.object(Path, "read_text", observe), mock.patch.object(Path, "glob", observe_glob):
            snapshot = owner_console_snapshot.load_snapshot(self.project)
        self.assertEqual(opened, ["TASK-001.json"])
        self.assertEqual(snapshot.done_count, 150)
        self.assertEqual(snapshot.tasks[0].status, "in_progress")

    def test_state_on_branch_without_worktree_and_spike_terminal_state(self) -> None:
        self.setup_project([("TASK-001", "queued", "REQUIRED", "—")])
        wt = self.worktree("task-001")
        self.state(wt, "TASK-001", "in_progress", verdict="APPROVE")
        self.commit(wt)
        self.git(self.project, "worktree", "remove", str(wt))
        task = self.load()["TASK-001"]
        self.assertEqual(task.status, "in_progress")
        self.assertEqual(task.review_verdict, "APPROVE")
        self.assertFalse(task.legacy)
        self.assertIn("branch task-001", task.source)
        self.write(self.project, "tasks/TASK-001.md", "# Task TASK-001 — Spike\nClass: SPIKE\nStatus: queued\n")
        self.write(self.project, ".cardine/tasks/TASK-001.json", json.dumps({
            "version": 1, "task_id": "TASK-001", "workflow": "single", "status": "done", "outcome": "ANSWERED",
            "transitions": [{"from": before, "to": after, "commit": "a" * 40,
                             "at": "2026-10-11T12:00:00Z"}
                            for before, after in [("queued", "in_progress"), ("in_progress", "done")]],
        }))
        snapshot = owner_console_snapshot.load_snapshot(self.project)
        self.assertEqual(snapshot.done_count, 1)
        self.assertEqual(snapshot.tasks, ())

    def test_lean_machine_state_keeps_worktree_derived_progress(self) -> None:
        support.write_project_config(self.project, "lean")
        support.LeanEffectiveStateFixture.setup_project(self, {"001": " "})
        self.state(self.project, "001", "queued", workflow="single")
        self.commit(self.project)
        self.worktree("task-001")
        task = self.load()["001"]
        self.assertEqual((task.status, task.lifecycle), ("queued", "in_progress"))
        self.assertFalse(task.legacy)




if __name__ == "__main__":
    unittest.main()
