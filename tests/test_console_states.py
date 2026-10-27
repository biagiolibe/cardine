"""Console task states derive from validated task state, never from queue or record prose."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from cardine.console import state as owner_console_state
from cardine.console import render as owner_console_render
from cardine.console import models as owner_console_models
from cardine.console import snapshot as owner_console_snapshot
from cardine.shared import console_workflow as owner_console_workflow
from cardine.tasks.status import load_task_status


from console_support import RESUME_001
import console_support as support

PALETTE = {name: 0 for name in (
    "base", "text", "title", "ready", "working", "muted", "line", "action", "blocked", "unknown")}


@contextlib.contextmanager
def delivery_ready():
    """Treat every review-ready task as deliverable; the gate itself has its own tests."""
    with mock.patch.object(owner_console_snapshot, "delivery_readiness", return_value={}):
        yield


class BranchStateTest(support.StateConsoleFixture):

    def test_task_without_branch_is_ready_from_main_state(self) -> None:
        self.setup_project({"001": "queued"})
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle, task.source),
                         ("READY", "todo", "task state on main"))
        self.assertEqual(task.launch_command, f"cardine run 001 --project {self.project}")
        self.assertFalse(task.active_writer)
        self.assertFalse(task.legacy)

    def test_reserved_branch_state_wins_without_any_write(self) -> None:
        self.setup_project({"001": "queued"})
        self.branch_state(self.worktree("task-001"), "001", "in_progress")
        before = self.refs_and_status()
        task = self.load()["001"]
        self.assertEqual(self.refs_and_status(), before)
        self.assertEqual((task.readiness, task.lifecycle, task.status), ("IN PROGRESS", "in_progress", "in_progress"))
        self.assertEqual(task.source, "task state in worktree task-001")
        self.assertEqual(task.launch_command, f"cardine run 001 --project {self.project}")
        self.assertEqual(task.next_action, f"cardine run 001 --project {self.project}")
        self.assertEqual(task.worktree, str(self.root / "wt-task-001"))

    def test_clean_prepared_worktree_offers_resume_without_a_state_write(self) -> None:
        self.setup_project({"001": "queued"})
        self.worktree("task-001")
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle, task.source, task.status),
                         ("IN PROGRESS", "in_progress", "branch task-001", "queued"))
        self.assertFalse(task.active_writer)
        self.assertEqual(task.markers, ("registered worktree",))
        # The status service keeps the state-only answer; the worktree is a display fact.
        self.assertTrue(load_task_status(self.project)["tasks"][0]["startable"])

    def test_prepared_worktree_never_overrides_unmet_dependencies(self) -> None:
        self.setup_project({"001": "queued", "002": "queued"}, deps={"002": "001"})
        self.worktree("task-002")
        task = self.load()["002"]
        self.assertEqual((task.readiness, task.lifecycle), ("BLOCKED: 001", "todo"))
        self.assertIsNone(task.launch_command)
        self.assertFalse(task.is_resume)

    def test_legacy_closure_advice_cannot_override_the_run_preview(self) -> None:
        self.setup_project({"001": "queued"})
        self.worktree("task-001")
        report = {"stop_reason": "REVIEW_NOT_APPROVED", "resume": "After approval, continue at C4"}
        with mock.patch.object(owner_console_snapshot, "closure_status", return_value=(report, False)) as old:
            task = self.load()["001"]
        old.assert_not_called()
        self.assertIsNone(task.closure_stop_reason)
        self.assertEqual(task.closure_resume, f"cardine run 001 --project {self.project}")
        lines = [value for value, _ in owner_console_render._detail_lines(task, 200, PALETTE)]
        self.assertNotIn("Closure stop: REVIEW_NOT_APPROVED", lines)
        self.assertNotIn("Resume: After approval, continue at C4", lines)

    def test_every_closure_stop_is_rendered_without_special_cases(self) -> None:
        reasons = (
            "ACCEPTANCE_UNMET", "VALIDATION_FAILED", "REVIEW_NOT_APPROVED", "WRONG_WORKTREE",
            "EVIDENCE_INCOMPLETE", "PRIMARY_DIRTY", "MAIN_BEHIND_ORIGIN", "LEASE_HELD",
            "INTEGRATION_CONFLICT", "CANDIDATE_VALIDATION_FAILED", "EVIDENCE_MISMATCH",
            "PUSH_PENDING", "PUSH_REJECTED", "CLEANUP_BLOCKED",
        )
        for reason in reasons:
            task = owner_console_models.Task("001", "Task", "in_progress", (), (), None, (), (),
                                readiness="IN PROGRESS", lifecycle="in_progress",
                                closure_stop_reason=reason, closure_resume="resume command")
            lines = [value for value, _ in owner_console_render._detail_lines(task, 60, PALETTE)]
            self.assertIn(f"Closure stop: {reason}", lines)
            self.assertIn("Resume: resume command", lines)

    def test_queued_tasks_do_not_read_closure_status(self) -> None:
        self.setup_project({"001": "queued", "002": "queued"})
        with mock.patch.object(owner_console_snapshot, "closure_status") as status:
            self.load()
        status.assert_not_called()

    def test_uncommitted_worktree_state_supersedes_committed_queued(self) -> None:
        self.setup_project({"001": "queued"})
        wt = self.worktree("task-001")
        self.branch_state(wt, "001", "in_progress", commit=False)
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertEqual(task.source, "task state in worktree task-001")
        self.assertTrue(task.active_writer)

    def test_missing_registered_worktree_directory_does_not_break_snapshot(self) -> None:
        self.setup_project({"001": "queued"})
        wt = self.worktree("task-001")
        moved = wt.with_name("missing-task-001")
        wt.rename(moved)
        self.addCleanup(lambda: moved.rename(wt) if moved.exists() else None)
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.source), ("READY", "task state on main"))
        self.assertEqual(task.worktree, str(wt))

    def test_in_review_branch_state_is_ready_for_review(self) -> None:
        self.setup_project({"001": "queued"})
        self.branch_state(self.worktree("task-001"), "001", "in_review")
        with delivery_ready():
            task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle), ("READY FOR REVIEW", "ready_for_review"))
        self.assertEqual(owner_console_render._state_label(task), ("Review", "ready"))
        self.assertEqual((task.review, task.launch_command), ("REQUIRED", f"cardine run 001 --project {self.project}"))

    def test_review_not_required_is_shown_and_never_offers_review(self) -> None:
        self.add("001", "queued", required=False)
        self.commit(self.project, "initial")
        wt = self.worktree("task-001")
        support.set_state(wt, "001", "in_progress", required=False)
        self.commit(wt)
        task = self.load()["001"]
        self.assertEqual((task.review, task.lifecycle), ("NOT REQUIRED", "in_progress"))
        self.assertEqual(task.launch_command, f"cardine run 001 --project {self.project}")

    def test_unverified_review_branch_cannot_select_a_reviewer(self) -> None:
        self.setup_project({"001": "queued"})
        self.branch_state(self.worktree("task-001"), "001", "in_review")
        task = self.load()["001"]
        self.assertEqual(task.run_preview["step"], "contract")
        self.assertIsNone(task.run_preview["work"])
        self.assertEqual(task.launch_command, f"cardine run 001 --project {self.project}")

    def test_changes_requested_verdict_marks_the_in_progress_task(self) -> None:
        self.setup_project({"001": "queued"})
        wt = self.worktree("task-001")
        self.branch_state(wt, "001", "in_progress", verdict="CHANGES_REQUESTED")
        task = self.load()["001"]
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertTrue(task.changes_requested)
        self.assertEqual(task.markers, ("changes requested",))
        self.assertEqual(task.launch_command, f"cardine run 001 --project {self.project}")
        self.assertEqual(task.review_verdict, "CHANGES_REQUESTED")
        self.branch_state(wt, "001", "in_progress", verdict="APPROVE")
        self.assertFalse(self.load()["001"].changes_requested)

    def test_resubmission_after_changes_requested_is_ready_for_review(self) -> None:
        self.setup_project({"001": "queued"})
        self.branch_state(self.worktree("task-001"), "001", "in_review")
        with delivery_ready():
            task = self.load()["001"]
        self.assertEqual(task.lifecycle, "ready_for_review")
        self.assertFalse(task.changes_requested)

    def test_dirty_worktree_is_advisory_and_never_changes_state(self) -> None:
        self.setup_project({"001": "queued"})
        wt = self.worktree("task-001")
        self.branch_state(wt, "001", "in_progress")
        clean = self.load()["001"]
        self.write(wt, "scratch.txt", "uncommitted")
        dirty = self.load()["001"]
        self.assertFalse(clean.active_writer)
        self.assertTrue(dirty.active_writer)
        self.assertEqual((clean.readiness, clean.lifecycle), (dirty.readiness, dirty.lifecycle))
        self.assertEqual(dirty.markers, ("active writer",))
        self.assertEqual(clean.launch_command, f"cardine run 001 --project {self.project}")
        self.assertEqual(dirty.launch_command, f"cardine run 001 --project {self.project}")

    def test_branch_behind_primary_is_a_mismatch_without_directive(self) -> None:
        self.setup_project({"001": "in_progress"})
        self.worktree("task-001")
        self.branch_state(self.root / "wt-task-001", "001", "queued")
        task = self.load()["001"]
        self.assertEqual(task.readiness, "MISMATCH")
        self.assertIn("main in_progress", task.mismatch or "")
        self.assertIn("task-001 queued", task.mismatch or "")
        self.assertIsNone(task.launch_command)
        self.assertEqual(owner_console_render._state_label(task)[0], "Mismatch")

    def test_dependencies_are_satisfied_by_integrated_state_only(self) -> None:
        self.setup_project({"001": "queued", "002": "queued"}, deps={"002": "001"})
        self.branch_state(self.worktree("task-001"), "001", "in_review")
        with delivery_ready():
            tasks = self.load()
        self.assertEqual(tasks["001"].readiness, "READY FOR REVIEW")
        self.assertEqual(tasks["002"].readiness, "BLOCKED: 001")
        self.assertIsNone(tasks["002"].launch_command)

    def test_milestone_identity_resolves_the_task_branch(self) -> None:
        self.write(self.project, ".cardine/task-identity.json", json.dumps({"version": 1, "mode": "milestone"}))
        self.setup_project({"M1-CORE-001": "queued"})
        self.branch_state(self.worktree("m1-core-001"), "M1-CORE-001", "in_progress")
        task = self.load()["M1-CORE-001"]
        self.assertEqual(task.source, "task state in worktree m1-core-001")
        self.assertEqual(task.readiness, "IN PROGRESS")

    def test_one_shot_reports_source_markers_and_mismatch(self) -> None:
        self.setup_project({"001": "queued", "002": "in_progress"})
        wt = self.worktree("task-001")
        self.branch_state(wt, "001", "in_progress")
        self.write(wt, "scratch.txt", "uncommitted")
        self.branch_state(self.worktree("task-002"), "002", "queued")
        state = owner_console_state.ConsoleState(self.project)
        state.refresh()
        output = owner_console_state.one_shot(state)
        self.assertIn("State from: task state in worktree task-001", output)
        self.assertIn("Markers: active writer", output)
        self.assertIn("Mismatch: main in_progress, task-002 queued", output)

    def test_state_on_branch_without_worktree_is_read_from_the_ref(self) -> None:
        self.setup_project({"001": "queued"})
        wt = self.worktree("task-001")
        self.branch_state(wt, "001", "in_progress", verdict="APPROVE")
        self.git(self.project, "worktree", "remove", str(wt))
        task = self.load()["001"]
        self.assertEqual((task.status, task.review_verdict), ("in_progress", "APPROVE"))
        self.assertEqual(task.source, "task state on branch task-001")
        self.assertFalse(task.legacy)


class StateAuthorityTest(support.StateConsoleFixture):
    """Queue, record, handoff, and review prose never decide what the console shows."""

    def test_state_wins_over_queue_record_and_review_prose(self) -> None:
        self.setup_project({"001": "queued"})
        wt = self.worktree("task-001")
        self.branch_state(wt, "001", "in_progress", verdict="CHANGES_REQUESTED")
        self.write(self.project, "tasks/QUEUE.md",
                   "| Status | ID |\n|---|---|\n| `[x]` | 001 |\n")
        self.write(wt, "tasks/001.md", "# Task 001\n\nStatus: done\nReview: NOT REQUIRED\n")
        self.write(wt, "tasks/reviews/001.md", "## Attempt 9 — APPROVE\n")
        self.write(wt, "tasks/handoffs/001.md", "- Status: `done`\n")
        self.commit(wt)
        before = self.refs_and_status()
        task = self.load()["001"]
        self.assertEqual(self.refs_and_status(), before)
        self.assertEqual(task.status, "in_progress")
        self.assertEqual(task.review_verdict, "CHANGES_REQUESTED")
        self.assertEqual(task.review, "REQUIRED")
        self.assertTrue(task.changes_requested)
        self.assertIsNone(task.mismatch)
        self.assertEqual(task.launch_command, f"cardine run 001 --project {self.project}")

    def test_queued_row_with_met_dependencies_and_in_progress_state_is_not_startable(self) -> None:
        self.setup_project({"001": "done", "002": "in_progress"}, deps={"002": "001"})
        self.write(self.project, "tasks/QUEUE.md", "| `[ ]` | 002 | queued | 001 |\n")
        task = self.load()["002"]
        self.assertNotEqual(task.readiness, "READY")
        self.assertEqual((task.readiness, task.lifecycle), ("IN PROGRESS", "in_progress"))
        self.assertTrue(task.is_resume)
        self.assertEqual(task.launch_command, f"cardine run 002 --project {self.project}")
        self.assertEqual(task.next_action, f"cardine run 002 --project {self.project}")
        self.assertFalse(load_task_status(self.project)["tasks"][0]["startable"])

    def test_queued_row_with_met_dependencies_and_in_review_state_is_not_startable(self) -> None:
        self.setup_project({"001": "done", "002": "in_review"}, deps={"002": "001"})
        self.write(self.project, "tasks/QUEUE.md", "| `[ ]` | 002 | queued | 001 |\n")
        self.worktree("task-002")
        with delivery_ready():
            task = self.load()["002"]
        self.assertEqual((task.readiness, task.lifecycle), ("READY FOR REVIEW", "ready_for_review"))
        self.assertFalse(task.is_resume)
        self.assertEqual(task.launch_command, f"cardine run 002 --project {self.project}")
        self.assertFalse(load_task_status(self.project)["tasks"][0]["startable"])

    def test_empty_queue_with_done_states_preserves_totals(self) -> None:
        self.setup_project({"001": "done", "002": "done", "003": "cancelled", "004": "queued"})
        self.write(self.project, "tasks/QUEUE.md", "")
        snapshot = owner_console_snapshot.load_snapshot(self.project)
        self.assertEqual([task.task_id for task in snapshot.tasks], ["004"])
        self.assertEqual(snapshot.done_count, 3)
        self.assertEqual(snapshot.tasks[0].readiness, "READY")
        self.assertEqual(load_task_status(self.project)["totals"]["total"], 4)

    def test_one_shot_prints_preset_and_the_status_totals(self) -> None:
        self.setup_project({"001": "done", "002": "queued", "003": "in_progress", "004": "queued"})
        self.write(self.project, ".cardine/tasks/005.json", "{")
        state = owner_console_state.ConsoleState(self.project)
        state.refresh()
        output = owner_console_state.one_shot(state)
        self.assertEqual(state.snapshot.preset, "lean")
        self.assertIn("Preset: lean | Totals: queued=2, in_progress=1, in_review=0, done=1, cancelled=0, total=4", output)
        # The invalid state is listed as an error, but it is neither open nor counted.
        self.assertIn("Open: 3 | Done: 1", output)
        self.assertEqual(dict(state.snapshot.totals), load_task_status(self.project)["totals"])

    def test_no_queue_or_archive_file_is_needed(self) -> None:
        self.setup_project({"001": "queued"})
        self.assertFalse((self.project / "tasks/QUEUE.md").exists())
        self.assertFalse((self.project / "tasks/QUEUE_ARCHIVE.md").exists())
        self.assertEqual(self.load()["001"].readiness, "READY")

    def test_stale_queue_rows_enumerate_nothing(self) -> None:
        self.setup_project({"001": "queued"})
        self.write(self.project, "tasks/QUEUE.md",
                   "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 001 | One |\n| `[ ]` | 099 | Ghost |\n")
        self.assertEqual(sorted(self.load()), ["001"])

    def test_invalid_state_is_per_task_and_never_falls_back(self) -> None:
        self.setup_project({"001": "queued", "002": "queued"})
        self.write(self.project, ".cardine/tasks/001.json", '{"version": 99}')
        tasks = self.load()
        invalid, valid = tasks["001"], tasks["002"]
        self.assertEqual(invalid.readiness, "STATE ERROR")
        self.assertIn("state.task_id", invalid.state_error)
        self.assertIsNone(invalid.launch_command)
        self.assertFalse(invalid.legacy)
        self.assertEqual(valid.launch_command, f"cardine run 002 --project {self.project}")
        state = owner_console_state.ConsoleState(self.project)
        state.snapshot = owner_console_snapshot.load_snapshot(self.project)
        output = owner_console_state.one_shot(state)
        self.assertIn("State error:", output)
        self.assertIn("Status: queued | Verdict: none", output)
        self.assertNotIn("legacy", output)

    def test_uncommitted_invalid_worktree_state_blocks_only_that_task(self) -> None:
        self.setup_project({"001": "queued", "002": "queued"})
        wt = self.worktree("task-001")
        self.branch_state(wt, "001", "in_progress")
        self.write(wt, ".cardine/tasks/001.json", "invalid JSON")
        tasks = self.load()
        self.assertIn("TASK_STATE_INVALID", tasks["001"].state_error)
        self.assertIsNone(tasks["001"].launch_command)
        self.assertEqual(tasks["002"].readiness, "READY")

    def test_state_naming_another_task_is_a_per_task_error(self) -> None:
        self.setup_project({"001": "queued"})
        state = json.loads((self.project / ".cardine/tasks/001.json").read_text())
        state["task_id"] = "002"
        self.write(self.project, ".cardine/tasks/001.json", json.dumps(state))
        self.assertEqual(self.load()["001"].readiness, "STATE ERROR")

    def test_spike_outcome_is_terminal_and_unblocks_only_when_answered(self) -> None:
        self.add("001", "done", outcome="ANSWERED", required=False)
        self.add("002", "done", outcome="INCONCLUSIVE", required=False)
        self.add("003", "queued", "001")
        self.add("004", "queued", "002")
        self.commit(self.project, "spikes")
        snapshot = owner_console_snapshot.load_snapshot(self.project)
        tasks = {task.task_id: task for task in snapshot.tasks}
        self.assertEqual(sorted(tasks), ["003", "004"])
        self.assertEqual(snapshot.done_count, 2)
        self.assertEqual(tasks["003"].readiness, "READY")
        self.assertEqual(tasks["004"].readiness, "BLOCKED: 002")

    def test_missing_dependency_and_cycles_are_not_ready(self) -> None:
        self.setup_project({"001": "queued", "002": "queued", "003": "queued"},
                           deps={"001": "002", "002": "001", "003": "999"})
        tasks = self.load()
        self.assertEqual(tasks["003"].readiness, "UNKNOWN: missing 999")
        for task_id in ("001", "002"):
            self.assertNotEqual(tasks[task_id].readiness, "READY")
            self.assertIsNone(tasks[task_id].launch_command)

    def test_closing_task_is_listed_from_a_done_state_with_a_worktree(self) -> None:
        self.setup_project({"001": "done"})
        self.worktree("task-001")
        report = {"step": "C9", "stop_reason": "PUSH_PENDING", "resume": "git push origin main"}
        with mock.patch.object(owner_console_snapshot, "closure_status", return_value=(report, False)):
            snapshot = owner_console_snapshot.load_snapshot(self.project)
        task = snapshot.tasks[0]
        self.assertEqual((task.readiness, task.lifecycle, task.status), ("CLOSING", "closing", "done"))
        self.assertEqual(task.closure_resume, f"cardine run 001 --project {self.project}")
        self.assertEqual(snapshot.done_count, 0)


class ConfigurationErrorTest(support.RepoCase):
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

    def test_task_creation_in_progress_is_an_incomplete_snapshot(self) -> None:
        self.write(self.project, ".cardine/task-creation.lock", "held\n")
        with self.assertRaisesRegex(owner_console_workflow.ConsoleError, "task creation is in progress"):
            owner_console_snapshot.load_snapshot(self.project)


if __name__ == "__main__":
    import unittest
    unittest.main()
