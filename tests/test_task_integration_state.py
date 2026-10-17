"""Task-state and commit-bound review gates run before integration mutations."""

import json
import unittest
from unittest import mock
import shlex
from pathlib import Path

from tests import test_task_worktree_isolation as fixtures

meridian = fixtures.meridian


class TaskIntegrationStateTest(unittest.TestCase):
    def setUp(self):
        fixtures.GovernedCompletionRowsTest.setUp(self)

    def tearDown(self):
        fixtures.BoundedWorktreeLifecycleTest.tearDown(self)

    git = fixtures.BoundedWorktreeLifecycleTest.git

    def start(self, *, workflow="governed-sdd", spike=False):
        if workflow == "lean-delivery":
            (self.primary / "PROJECT_WORKFLOW.md").write_text("This file selects `LEAN_DELIVERY` exclusively.\n")
            (self.primary / "tasks/QUEUE.md").write_text("| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n")
            (self.primary / "PROJECT_PLAN.md").write_text("- `[ ]` 056 — Lifecycle\n")
        elif spike:
            (self.primary / "tasks/056-lifecycle.md").write_text(
                "# Task 056\n\n> **ID**: `056`\nClass: SPIKE\nStatus: IN_PROGRESS\n")
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-m", "configure task")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = meridian.prepare_task_worktree("056", self.worktree_root, self.primary)
        self.worker = Path(prepared["worktree"])
        if not spike:
            (self.worker / "feature.txt").write_text("approved code\n")
        self.git("add", ".", cwd=self.worker)
        self.git("commit", "--allow-empty", "-m", "implement task", cwd=self.worker)
        self.reviewed = self.git("rev-parse", "HEAD", cwd=self.worker).stdout.strip()
        self.workflow = workflow

    def write_state(self, *, required=True, verdict="APPROVE", status=None, reviewed=None, spike=False):
        status = status or ("DONE" if self.workflow == "lean-delivery" else "ANSWERED" if spike else "ACCEPTED")
        if self.workflow == "lean-delivery":
            sequence = ["QUEUED", "DONE"]
        elif spike:
            sequence = ["QUEUED", "IN_PROGRESS", status]
        elif required:
            sequence = ["QUEUED", "IN_PROGRESS", "READY_FOR_REVIEW", "ACCEPTED"]
        else:
            sequence = ["QUEUED", "IN_PROGRESS", "ACCEPTED"]
        if status in sequence:
            sequence = sequence[:sequence.index(status) + 1]
        state = {"version": 1, "task_id": "056", "workflow": self.workflow, "status": status,
                 "transitions": [{"from": before, "to": after, "commit": self.reviewed,
                                  "at": "2026-10-11T00:00:00Z"}
                                 for before, after in zip(sequence, sequence[1:])]}
        if self.workflow != "lean-delivery":
            state["review"] = {"required": required, "verdict": verdict, "attempt": 1,
                               "reviewed_commit": reviewed or self.reviewed, "approved_by": "reviewer"}
        self.state_file = self.worker / ".meridian/tasks/056.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state))
        self.commit()

    def commit(self):
        self.git("add", ".", cwd=self.worker)
        self.git("commit", "-m", "record task evidence", cwd=self.worker)

    def evidence(self, validated=None):
        head = self.git("rev-parse", "HEAD", cwd=self.worker).stdout.strip()
        self.evidence_file = self.root / "evidence.json"
        self.evidence_file.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": validated or head, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": [], "task_dependencies": [], "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [], "main_advanced_behavioral_surfaces": [],
        }))
        return self.evidence_file

    def stage(self, validated=None):
        return meridian.stage_task_integration("056", self.worktree_root, self.evidence(validated), self.primary)

    def assert_stop(self, code, detail):
        before = self.git("rev-parse", "HEAD").stdout
        tree = self.git("write-tree").stdout
        queue = (self.primary / "tasks/QUEUE.md").read_bytes()
        with self.assertRaises(meridian.MeridianStop) as caught:
            self.stage()
        self.assertTrue(str(caught.exception).startswith(f"BLOCKED {code}:"), str(caught.exception))
        self.assertIn(detail, str(caught.exception))
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        _state, lease, integration = meridian._lifecycle_paths(self.primary, identity)
        self.assertFalse(lease.exists())
        self.assertFalse(integration.exists())
        self.assertFalse(meridian._merge_head_path(self.primary).exists())
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, before)
        self.assertEqual(self.git("write-tree").stdout, tree)
        self.assertEqual((self.primary / "tasks/QUEUE.md").read_bytes(), queue)
        return caught.exception

    def test_approved_task_integrates_with_dated_review_heading(self):
        self.start()
        self.write_state()
        review = self.worker / "tasks/reviews/056.md"
        review.parent.mkdir()
        review.write_text("## Attempt 1 — 2026-10-11 — APPROVE\n")
        self.commit()
        staged = self.stage(self.reviewed)
        self.assertEqual(staged["decision"], "REUSE")
        self.assertEqual(staged["completion"]["source"], "machine")
        self.assertIn("| ACCEPTED |", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text())
        validation = self.root / "candidate.json"
        validation.write_text(json.dumps({"candidate_tree": staged["candidate_tree"], "passed": True,
                                         "scope": "bounded", "commands": ["git diff --check", "scripts/check_repository.py"]}))
        meridian.finalize_task_integration("056", validation, self.primary)
        self.assertEqual((self.primary / "feature.txt").read_text(), "approved code\n")

    def test_stale_review_stop(self):
        self.start()
        self.write_state()
        (self.worker / "feature.txt").write_text("changed after review\n")
        self.commit()
        self.assert_stop("REVIEW_STALE", "feature.txt")

    def test_missing_verdict_stop(self):
        self.start()
        self.write_state(verdict=None)
        self.assert_stop("REVIEW_NOT_APPROVED", "review.verdict expected APPROVE; found None")

    def test_absent_review_and_rejected_verdict_stop(self):
        self.start()
        self.write_state(verdict="CHANGES_REQUESTED")
        self.assert_stop("REVIEW_NOT_APPROVED", "found 'CHANGES_REQUESTED'")
        state = json.loads(self.state_file.read_text())
        del state["review"]
        self.state_file.write_text(json.dumps(state))
        self.commit()
        self.assert_stop("REVIEW_NOT_APPROVED", "found None")

    def test_missing_state_stop(self):
        self.start()
        (self.worker / ".meridian/tasks").mkdir()
        self.assert_stop("TASK_STATE_MISSING", ".meridian/tasks/056.json")

    def test_invalid_state_stop(self):
        self.start()
        self.write_state()
        self.state_file.write_text("{invalid")
        self.commit()
        self.assert_stop("TASK_STATE_INVALID", ".meridian/tasks/056.json")

    def test_non_utf8_state_stop(self):
        self.start()
        self.write_state()
        self.state_file.write_bytes(b"\xff")
        self.commit()
        self.assert_stop("TASK_STATE_INVALID", "expected readable UTF-8 JSON")

    def test_nonterminal_state_stop(self):
        self.start()
        self.write_state(status="READY_FOR_REVIEW")
        self.assert_stop("TASK_STATE_INVALID", "status expected ('ACCEPTED',); found 'READY_FOR_REVIEW'")

    def test_nonancestor_review_stop(self):
        self.start()
        self.write_state(reviewed="f" * 40)
        self.assert_stop("REVIEW_STALE", "review.reviewed_commit expected ancestor")

    def test_only_own_governance_changes_preserve_approval(self):
        self.start()
        self.write_state()
        record = self.worker / "tasks/056-lifecycle.md"
        record.write_text(record.read_text() + "\nCompletion evidence.\n")
        archive = self.worker / "tasks/done/056-lifecycle.md"
        archive.parent.mkdir()
        record.rename(archive)
        handoff = self.worker / "tasks/handoffs/056.md"
        handoff.parent.mkdir()
        handoff.write_text("Completion evidence.\n")
        (self.worker / ".meridian/execution-evidence.json").write_text("{}\n")
        self.commit()
        staged = self.stage()
        self.assertEqual(staged["completion"]["status"], "COMPLETED")
        meridian.abort_task_integration("056", self.primary)

    def test_other_task_state_invalidates_approval(self):
        self.start()
        self.write_state()
        (self.worker / ".meridian/tasks/057.json").write_text("{}\n")
        self.commit()
        self.assert_stop("REVIEW_STALE", ".meridian/tasks/057.json")

    def test_schema_valid_but_impossible_history_stops(self):
        self.start()
        self.write_state()
        state = json.loads(self.state_file.read_text())
        state["transitions"][0]["to"] = "ACCEPTED"
        self.state_file.write_text(json.dumps(state))
        self.commit()
        self.assert_stop("TASK_STATE_INVALID", "transitions[0].to")

    def test_not_required_task_integrates_without_prose(self):
        self.start()
        self.write_state(required=False, verdict=None)
        self.assertEqual(self.stage()["completion"]["source"], "machine")
        self.assertIn("| ACCEPTED |", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text())
        meridian.abort_task_integration("056", self.primary)

    def check_spike_projection(self, status):
        self.start(spike=True)
        self.write_state(spike=True, status=status, verdict=None)
        staged = self.stage(self.reviewed)
        self.assertEqual(staged["decision"], "REUSE")
        # Archival reads task state, so a terminal spike closes its section, INCONCLUSIVE included.
        self.assertIn(f"| {status} |", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text())
        meridian.abort_task_integration("056", self.primary)

    def test_spike_terminal_projection_ignores_record_status(self):
        self.check_spike_projection("ANSWERED")

    def test_inconclusive_spike_projection(self):
        self.check_spike_projection("INCONCLUSIVE")

    def test_ordinary_task_cannot_use_spike_state_to_skip_review(self):
        self.start()
        self.write_state(spike=True, verdict=None)
        self.assert_stop("TASK_STATE_INVALID", "transitions[1].to")

    def test_spike_cannot_integrate_with_accepted_status(self):
        self.start(spike=True)
        self.write_state(required=False)
        self.assert_stop("TASK_STATE_INVALID", "transitions[1].to")

    def test_lean_done_projection(self):
        self.start(workflow="lean-delivery")
        self.write_state(required=False)
        self.assertEqual(self.stage(self.reviewed)["completion"]["source"], "machine")
        self.assertIn("`[x]`", (self.primary / "tasks/QUEUE.md").read_text())
        self.assertIn("`[x]`", (self.primary / "PROJECT_PLAN.md").read_text())
        meridian.abort_task_integration("056", self.primary)

    def test_advance_reports_review_gate(self):
        self.start()
        self.write_state(verdict=None)
        result, blocked = meridian.advance_task_closure(
            "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
        self.assertTrue(blocked)
        self.assertEqual(result["stop_code"], "REVIEW_NOT_APPROVED")
        self.assertEqual(result["step"], "C6")

    def test_advance_state_gate_runs_before_stage(self):
        self.start(workflow="lean-delivery")
        self.write_state(required=False, status="QUEUED")
        for missing in (True, False):
            with self.subTest(missing=missing):
                if missing:
                    self.state_file.unlink()
                else:
                    self.write_state(required=False, status="QUEUED")
                self.git("add", "-A", cwd=self.worker)
                self.git("commit", "--allow-empty", "-m", "set closure state", cwd=self.worker)
                before = {path: self.git("write-tree", cwd=path).stdout for path in (self.primary, self.worker)}
                with mock.patch.object(meridian, "stage_task_integration") as stage:
                    result, blocked = meridian.advance_task_closure(
                        "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
                stage.assert_not_called()
                self.assertTrue(blocked)
                self.assertEqual(result["stop_code"], "TASK_STATE_MISSING" if missing else "TASK_STATE_INVALID")
                if missing:
                    command = shlex.split(result["commands"][0])
                    self.assertEqual(command[:5], ["meridian", "task", "transition", "056", "DONE"])
                    self.assertEqual(command[command.index("--project") + 1], str(self.worker))
                for path, tree in before.items():
                    self.assertEqual(self.git("write-tree", cwd=path).stdout, tree)
                self.assertFalse(meridian._merge_head_path(self.primary).exists())

    def test_advance_requires_state_even_before_machine_state_adoption(self):
        self.start(workflow="lean-delivery")
        self.assertFalse((self.worker / ".meridian/tasks").exists())
        with mock.patch.object(meridian, "stage_task_integration") as stage:
            result, blocked = meridian.advance_task_closure(
                "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
        stage.assert_not_called()
        self.assertTrue(blocked)
        self.assertEqual(result["stop_code"], "TASK_STATE_MISSING")

    def test_advance_terminal_state_reaches_stage(self):
        self.start(workflow="lean-delivery")
        self.write_state(required=False)
        original = meridian.stage_task_integration
        with mock.patch.object(meridian, "stage_task_integration", wraps=original) as stage:
            result, blocked = meridian.advance_task_closure(
                "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
        stage.assert_called_once()
        self.assertFalse(blocked)
        self.assertEqual(result["action_required"], "run-candidate-validation")
        meridian.abort_task_integration("056", self.primary)

    def test_missing_state_resume_selects_registered_worktree(self):
        self.start()
        resume = meridian.stop_resume("TASK_STATE_MISSING", task_id="056", project=self.primary)
        self.assertEqual(shlex.split(resume)[shlex.split(resume).index("--project") + 1], str(self.worker))
        (self.worker / ".meridian/tasks").mkdir()
        error = self.assert_stop("TASK_STATE_MISSING", ".meridian/tasks/056.json")
        self.assertIn(resume, str(error))

    def test_legacy_stage_is_labeled_and_missing_approval_blocks(self):
        self.start()
        staged = self.stage()
        self.assertEqual(staged["completion"]["source"], "legacy")
        meridian.abort_task_integration("056", self.primary)
        record = self.worker / "tasks/056-lifecycle.md"
        record.write_text(record.read_text() + "Review: REQUIRED\n")
        # A project-shaped queue without Review uses the legacy record policy.
        queue = self.worker / "tasks/QUEUE.md"
        queue.write_text("| ID | Status |\n|---|---|\n| 056 | QUEUED |\n")
        self.commit()
        self.assert_stop("REVIEW_NOT_APPROVED", "legacy")
