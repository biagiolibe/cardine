"""Task-state and commit-bound review gates run before integration mutations."""

import json
import os
import subprocess
import sys
import unittest
from unittest import mock
import shlex
import shutil
import tempfile
from repository_template_support import RepositoryTemplate, authorize_copy
from pathlib import Path
from project_config_support import write_project_config
from task_contract_support import freeze_record, seal_state

from tests import worktree_support as fixtures

import cardine_cli
from cardine.lifecycle import closure as owner_lifecycle_closure
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.stops import render as owner_stops_render
from cardine.worktree import storage as owner_worktree_storage
from cardine.worktree import checkout as owner_worktree_checkout
from cardine.integration import merge as owner_integration_merge


class TaskIntegrationStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def build(project):
            fixture = cls()
            try:
                fixtures.GovernedCompletionRowsFixture.setUp(fixture)
                shutil.copytree(fixture.primary, project)
            finally:
                fixtures.BoundedWorktreeLifecycleFixture.tearDown(fixture)
                fixture.doCleanups()
        cls.template = RepositoryTemplate(build)
        cls.addClassCleanup(cls.template.cleanup)

    def setUp(self):
        from control_support import adapter
        host = mock.patch('cardine.lifecycle.control.host_adapter', return_value=adapter('coordinator'))
        host.start()
        self.addCleanup(host.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.primary = self.root / "project"
        self.template.copy_to(self.primary)
        self.worktree_root = self.root / "worktrees"
        self.worktree_root.mkdir()
        self.environment = mock.patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.worktree_root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        authorize_copy(self.primary)
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.previous_cwd = Path.cwd()
        os.chdir(self.primary)
        path = self.primary / ".cardine/tasks/056.json"
        path.unlink()
        path.with_name(".056.guard").unlink(missing_ok=True)
        path.parent.rmdir()

    def tearDown(self):
        fixtures.BoundedWorktreeLifecycleFixture.tearDown(self)

    git = fixtures.BoundedWorktreeLifecycleFixture.git

    def start(self, *, workflow="single", spike=False, preset="governed", plan=None):
        if preset == "lean":
            write_project_config(self.primary, "lean", validation=fixtures.VALIDATION)
            (self.primary / "tasks/QUEUE.md").write_text("| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n")
            (self.primary / "PROJECT_PLAN.md").write_text(plan if plan is not None else
                "Narrative stays.\n\n<!-- cardine-status:begin -->\n<!-- cardine-status:end -->\n\nTail stays.\n")
        elif spike:
            (self.primary / "tasks/056-lifecycle.md").write_text(
                "# Task 056\n\n> **ID**: `056`\nClass: SPIKE\nStatus: in_progress\n")
        freeze_record(self.primary, "056", self.primary / "tasks/056-lifecycle.md")
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-m", "configure task")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = owner_worktree_checkout.prepare_task_worktree("056", self.worktree_root, self.primary)
        self.worker = Path(prepared["worktree"])
        # Preparation consumes a valid state; these tests independently exercise
        # missing-state integration, so remove it from the implementation fixture.
        fixture_state = self.worker / '.cardine/tasks/056.json'
        fixture_state.unlink()
        fixture_state.with_name('.056.guard').unlink(missing_ok=True)
        fixture_state.parent.rmdir()
        if not spike:
            (self.worker / "feature.txt").write_text("approved code\n")
        self.git("add", ".", cwd=self.worker)
        self.git("commit", "--allow-empty", "-m", "implement task", cwd=self.worker)
        self.reviewed = self.git("rev-parse", "HEAD", cwd=self.worker).stdout.strip()
        self.workflow = workflow

    def write_state(self, *, required=True, verdict="APPROVE", status=None, reviewed=None, spike=False):
        outcome = status if spike else None
        status = "in_progress" if status in (None, "ANSWERED", "INCONCLUSIVE") else status
        sequence = ["queued", "in_progress"]
        if required:
            sequence += ["in_review", "in_progress"]
        if status == "in_review":
            sequence = ["queued", "in_progress", "in_review"]
        state = {"version": 1, "task_id": "056", "workflow": self.workflow, "status": status,
                 "transitions": [{"from": before, "to": after, "commit": self.reviewed,
                                  "at": "2026-10-11T00:00:00Z"}
                                 for before, after in zip(sequence, sequence[1:])]}
        state["review"] = {"required": required, "verdict": verdict, "attempt": 1,
                           "reviewed_commit": reviewed or self.reviewed, "approved_by": "reviewer"}
        if spike:
            state["outcome"] = outcome or "ANSWERED"
        self.state_file = self.worker / ".cardine/tasks/056.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state))
        frozen = freeze_record(self.worker, "056", self.worker / "tasks/056-lifecycle.md")
        frozen["contract"]["options"]["review"] = "required" if required else "not_required"
        self.state_file.write_text(json.dumps(frozen))
        seal_state(self.worker, "056")
        from control_support import bind_fixture_approval
        bind_fixture_approval(self.worker, "056")
        self.commit()

    def commit(self):
        self.git("add", ".", cwd=self.worker)
        self.git("commit", "--allow-empty", "-m", "record task evidence", cwd=self.worker)

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
        return owner_integration_merge.stage_task_integration("056", self.worktree_root, self.evidence(validated), self.primary)

    def assert_stop(self, code, detail):
        before = self.git("rev-parse", "HEAD").stdout
        tree = self.git("write-tree").stdout
        queue = (self.primary / "tasks/QUEUE.md").read_bytes()
        with self.assertRaises(shared_errors.CardineStop) as caught:
            self.stage()
        from cardine.stops.render import outcome_for_code
        prefix = {"blocked": "BLOCKED", "next": "NEXT", "iterate": "ITERATE"}[outcome_for_code(code)]
        self.assertTrue(str(caught.exception).startswith(f"{prefix} {code}:"), str(caught.exception))
        self.assertIn(detail, str(caught.exception))
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        _state, lease, integration = owner_worktree_storage._lifecycle_paths(self.primary, identity)
        self.assertFalse(lease.exists())
        self.assertFalse(integration.exists())
        self.assertFalse(owner_worktree_storage._merge_head_path(self.primary).exists())
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
        self.assertEqual(staged["landed_status"], "done")
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())
        validation = self.root / "candidate.json"
        validation.write_text(json.dumps({"candidate_tree": staged["candidate_tree"], "passed": True,
                                         "scope": "bounded", "commands": ["git diff --check", "scripts/check_repository.py", "python3 -c 'pass'"]}))
        owner_integration_merge.finalize_task_integration("056", validation, self.primary)
        self.assertEqual((self.primary / "feature.txt").read_text(), "approved code\n")

    def test_stale_review_stop(self):
        self.start()
        self.write_state()
        (self.worker / "feature.txt").write_text("changed after review\n")
        self.commit()
        self.assert_stop("REVIEW_NOT_APPROVED", "feature.txt")

    def test_reverted_implementation_commit_still_invalidates_approval(self):
        self.start()
        self.write_state()
        (self.worker / "feature.txt").write_text("change after approval\n")
        self.commit()
        (self.worker / "feature.txt").write_text("approved code\n")
        self.commit()
        self.assert_stop("REVIEW_NOT_APPROVED", "feature.txt")

    def test_missing_verdict_stop(self):
        self.start()
        self.write_state(verdict=None)
        error = self.assert_stop("REVIEW_NOT_APPROVED", "review.verdict expected APPROVE; found None")
        self.assertIn("cause: missing;", str(error))

    def test_absent_review_and_rejected_verdict_stop(self):
        self.start()
        self.write_state(verdict="CHANGES_REQUESTED")
        self.assert_stop("REVIEW_NOT_APPROVED", "found 'CHANGES_REQUESTED'")
        state = json.loads(self.state_file.read_text())
        del state["review"]
        self.state_file.write_text(json.dumps(state))
        seal_state(self.worker, '056')
        self.commit()
        self.assert_stop("REVIEW_NOT_APPROVED", "found None")

    def test_missing_state_stop(self):
        self.start()
        (self.worker / ".cardine/tasks").mkdir()
        self.assert_stop("TASK_STATE_MISSING", ".cardine/tasks/056.json")

    def test_invalid_state_stop(self):
        self.start()
        self.write_state()
        self.state_file.write_text("{invalid")
        self.commit()
        self.assert_stop("TASK_STATE_INVALID", ".cardine/tasks/056.json")

    def test_non_utf8_state_stop(self):
        self.start()
        self.write_state()
        self.state_file.write_bytes(b"\xff")
        self.commit()
        self.assert_stop("TASK_STATE_INVALID", "expected readable UTF-8 JSON")

    def test_nonterminal_state_stop(self):
        self.start()
        self.write_state(status="in_review")
        self.assert_stop("TASK_STATE_INVALID", "status expected ('in_progress',); found 'in_review'")

    def test_nonancestor_review_stop(self):
        self.start()
        self.write_state(reviewed="f" * 40)
        self.assert_stop("REVIEW_NOT_APPROVED", "review.reviewed_commit expected ancestor")

    def test_only_own_governance_changes_preserve_approval(self):
        self.start()
        self.write_state()
        record = self.worker / "tasks/056-lifecycle.md"
        record.write_text(record.read_text() + "\nCompletion evidence.\n")
        handoff = self.worker / "tasks/handoffs/056.md"
        handoff.parent.mkdir()
        handoff.write_text("Completion evidence.\n")
        (self.worker / ".cardine/evidence").mkdir()
        (self.worker / ".cardine/evidence/056.json").write_text("{}\n")
        self.commit()
        staged = self.stage()
        self.assertEqual(staged["landed_status"], "done")
        self.assertTrue((self.primary / "tasks/056-lifecycle.md").is_file())
        owner_integration_merge.abort_task_integration("056", self.primary)

    def test_record_move_or_queue_edit_after_validation_is_not_governance(self):
        for label, change in (
            ("archive move", lambda: (self.worker / "tasks/done").mkdir() or
             (self.worker / "tasks/056-lifecycle.md").rename(self.worker / "tasks/done/056-lifecycle.md")),
            ("queue edit", lambda: (self.worker / "tasks/QUEUE.md").write_text(
                (self.worker / "tasks/QUEUE.md").read_text() + "edited\n")),
            ("queue archive", lambda: (self.worker / "tasks/QUEUE_ARCHIVE.md").write_text("archive\n")),
        ):
            with self.subTest(label):
                self.start()
                self.write_state()
                change()
                self.commit()
                error = self.assert_stop("REVIEW_NOT_APPROVED", "offending paths")
                self.assertNotIn(".cardine/tasks/056.json", str(error).split("offending paths:")[1].split(";")[0])
                self.git("worktree", "remove", "--force", str(self.worker))
                self.git("branch", "-D", "task-056")
                self.git("reset", "--hard", self.base)
                identity = owner_tasks_identity.resolve_task_identity(self.primary, '056', 'existing')
                lifecycle, _, _ = owner_worktree_storage._lifecycle_paths(self.primary, identity)
                lifecycle.unlink(missing_ok=True)
                lifecycle.with_suffix('.preparation').unlink(missing_ok=True)

    def test_other_task_state_invalidates_approval(self):
        self.start()
        self.write_state()
        (self.worker / ".cardine/tasks/057.json").write_text("{}\n")
        self.commit()
        self.assert_stop("REVIEW_NOT_APPROVED", ".cardine/tasks/057.json")

    def test_schema_valid_but_impossible_history_stops(self):
        self.start()
        self.write_state()
        state = json.loads(self.state_file.read_text())
        state["transitions"][0]["to"] = "done"
        self.state_file.write_text(json.dumps(state))
        self.commit()
        self.assert_stop("TASK_STATE_INVALID", "transitions[0].to")

    def test_not_required_task_integrates_without_prose(self):
        self.start()
        self.write_state(required=False, verdict=None)
        self.assertEqual(self.stage()["landed_status"], "done")
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())
        owner_integration_merge.abort_task_integration("056", self.primary)

    def check_spike_projection(self, status, *, required=False):
        self.start(spike=True)
        self.write_state(spike=True, status=status, verdict="APPROVE" if required else None, required=required)
        staged = self.stage(self.reviewed)
        self.assertEqual(staged["decision"], "REUSE")
        self.assertEqual(staged["landed_status"], "done")
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())
        owner_integration_merge.abort_task_integration("056", self.primary)

    def test_spike_terminal_projection_ignores_record_status(self):
        self.check_spike_projection("ANSWERED", required=True)

    def test_inconclusive_spike_projection(self):
        self.check_spike_projection("INCONCLUSIVE")

    def test_ordinary_task_cannot_use_spike_state_to_skip_review(self):
        self.start()
        self.write_state(spike=True, verdict=None)
        self.assert_stop("TASK_STATE_INVALID", "outcome")

    def test_spike_cannot_integrate_with_accepted_status(self):
        self.start(spike=True)
        self.write_state(required=False)
        self.assert_stop("TASK_STATE_INVALID", "spike landing requires an outcome")

    def test_lean_done_projection(self):
        self.start(workflow="single", preset="lean")
        self.write_state(required=False)
        freeze_record(self.worker, "056", self.worker / "tasks/056-lifecycle.md")
        self.commit()
        staged = self.stage(self.reviewed)
        self.assertEqual(staged["landed_status"], "done")
        self.assertEqual(staged["views"]["status"], "REGENERATED", staged)
        self.assertIn("| done | 056 |", (self.primary / "PROJECT_PLAN.md").read_text())
        self.assertNotIn("| 056 |", (self.primary / "tasks/QUEUE.md").read_text())
        plan = (self.primary / "PROJECT_PLAN.md").read_text()
        self.assertTrue(plan.startswith("Narrative stays.\n\n") and plan.endswith("\n\nTail stays.\n"))
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout.split(),
                         [".cardine/tasks/056.json", "PROJECT_PLAN.md", "feature.txt", "tasks/QUEUE.md"])
        owner_integration_merge.abort_task_integration("056", self.primary)

    def test_abort_restores_state_and_views_together(self):
        self.start(workflow="single", preset="lean", plan="")
        (self.primary / "PROJECT_PLAN.md").unlink()
        self.git("commit", "-am", "no plan on main")
        self.write_state(required=False)
        freeze_record(self.worker, "056", self.worker / "tasks/056-lifecycle.md")
        self.commit()
        before_tree = self.git("rev-parse", "HEAD^{tree}").stdout
        queue = (self.primary / "tasks/QUEUE.md").read_bytes()
        self.assertFalse((self.primary / "PROJECT_PLAN.md").exists())
        staged = self.stage(self.reviewed)
        self.assertEqual(staged["views"]["status"], "REGENERATED", staged)
        self.assertTrue((self.primary / "PROJECT_PLAN.md").is_file())
        owner_integration_merge.abort_task_integration("056", self.primary)
        self.assertFalse((self.primary / "PROJECT_PLAN.md").exists())
        self.assertEqual((self.primary / "tasks/QUEUE.md").read_bytes(), queue)
        self.assertEqual(json.loads((self.primary / ".cardine/tasks/056.json").read_text())["status"], "queued")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").stdout, before_tree)

    def test_failed_view_write_reports_stale_view_and_keeps_landed_state(self):
        self.start(workflow="single", preset="lean", plan="No region here.\n")
        self.write_state(required=False)
        staged = self.stage(self.reviewed)
        self.assertEqual(staged["landed_status"], "done")
        self.assertEqual(staged["views"]["status"], "STALE")
        self.assertIn("cardine status --write", staged["warnings"][0])
        self.assertEqual((self.primary / "PROJECT_PLAN.md").read_text(), "No region here.\n")
        landed = json.loads((self.primary / ".cardine/tasks/056.json").read_text())
        self.assertEqual(landed["status"], "done")
        owner_integration_merge.abort_task_integration("056", self.primary)

    def test_advance_reports_review_gate(self):
        self.start()
        self.write_state(verdict=None)
        result, blocked = owner_lifecycle_closure.advance_task_closure(
            "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
        self.assertTrue(blocked)
        self.assertEqual(result["stop_code"], "REVIEW_NOT_APPROVED")
        self.assertEqual(result["step"], "C6")

    def test_advance_reports_invalid_review_history_detail(self):
        self.start()
        self.write_state(required=False)
        state = json.loads(self.state_file.read_text())
        state["transitions"].append({**state["transitions"][0], "from": "in_progress", "to": "in_review"})
        state["status"] = "in_review"
        self.state_file.write_text(json.dumps(state))
        self.commit()
        with mock.patch.object(owner_lifecycle_closure, "stage_task_integration") as stage:
            result, blocked = owner_lifecycle_closure.advance_task_closure(
                "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
        stage.assert_not_called()
        self.assertTrue(blocked)
        self.assertEqual((result["step"], result["stop_code"]), ("C6", "TASK_STATE_INVALID"))
        self.assertIn(".cardine/tasks/056.json", result["stop_detail"])
        self.assertIn("transitions[1].to", result["stop_detail"])
        self.assertIn("allowed", result["stop_detail"])
        self.assertIn("found 'in_review'", result["stop_detail"])
        self.assertNotIn("BLOCKED TASK_STATE_INVALID:", result["stop_detail"])
        self.assertNotIn("; resume:", result["stop_detail"])

    def test_advance_status_detail_uses_only_the_available_reason(self):
        self.start()
        for reason in ("recorded validation failed", None):
            with self.subTest(reason=reason), mock.patch.object(
                owner_lifecycle_closure, "closure_status",
                return_value=({"step": "C2", "stop_reason": "VALIDATION_FAILED", "resume": reason}, False),
            ):
                result, blocked = owner_lifecycle_closure.advance_task_closure(
                    "056", self.worktree_root, [], [], accepted=True, supplied_project=self.primary)
                self.assertTrue(blocked)
                self.assertEqual(result["stop_detail"], reason or "")

    def test_advance_state_gate_runs_before_stage(self):
        self.start(workflow="single", preset="lean")
        self.write_state(required=False, status="queued")
        for missing in (True, False):
            with self.subTest(missing=missing):
                if missing:
                    self.state_file.unlink()
                else:
                    self.write_state(required=False, status="queued")
                self.git("add", "-A", cwd=self.worker)
                self.git("commit", "--allow-empty", "-m", "set closure state", cwd=self.worker)
                before = {path: self.git("write-tree", cwd=path).stdout for path in (self.primary, self.worker)}
                with mock.patch.object(owner_lifecycle_closure, "stage_task_integration") as stage:
                    result, blocked = owner_lifecycle_closure.advance_task_closure(
                        "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
                stage.assert_not_called()
                self.assertTrue(blocked)
                self.assertEqual(result["stop_code"], "TASK_STATE_MISSING" if missing else "TASK_STATE_INVALID")
                self.assertIn(".cardine/tasks/056.json", result["stop_detail"])
                if missing:
                    command = shlex.split(result["commands"][0])
                    self.assertEqual(command[:4], ["cardine", "task", "state", "import"])
                    self.assertEqual(command[command.index("cardine"):command.index("cardine") + 4],
                                     ["cardine", "task", "state", "import"])
                    self.assertEqual(command[command.index("--project") + 1], str(self.worker))
                    self.assertEqual(len(result["commands"]), 1)
                    self.assertEqual(result["resume"], " && ".join(result["commands"]))
                for path, tree in before.items():
                    self.assertEqual(self.git("write-tree", cwd=path).stdout, tree)
                self.assertFalse(owner_worktree_storage._merge_head_path(self.primary).exists())

    def test_advance_requires_state_even_before_machine_state_adoption(self):
        self.start(workflow="single", preset="lean")
        self.assertFalse((self.worker / ".cardine/tasks").exists())
        with mock.patch.object(owner_lifecycle_closure, "stage_task_integration") as stage:
            result, blocked = owner_lifecycle_closure.advance_task_closure(
                "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
        stage.assert_not_called()
        self.assertTrue(blocked)
        self.assertEqual(result["stop_code"], "TASK_STATE_MISSING")

    def test_advance_missing_state_recovery_commands_run_unchanged(self):
        self.start(workflow="single", preset="lean")
        handoff = self.worker / "tasks/handoffs/056.md"
        handoff.parent.mkdir(exist_ok=True)
        handoff.write_text("Validated task completion.\n")
        self.commit()
        for archived in (False, True):
            with self.subTest(archived=archived):
                if archived:
                    record = self.worker / "tasks/056-lifecycle.md"
                    target = record.parent / "done" / record.name
                    target.parent.mkdir(exist_ok=True)
                    record.rename(target)
                    self.commit()
                before = self.git("write-tree", cwd=self.worker).stdout
                result, blocked = owner_lifecycle_closure.advance_task_closure(
                    "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
                self.assertTrue(blocked)
                self.assertEqual(result["stop_code"], "TASK_STATE_MISSING")
                self.assertIn("task state import 056", result["resume"])
                self.assertNotIn("task transition", result["resume"])
                self.assertEqual(result["commands"], [result["resume"]])
                self.assertFalse((self.worker / ".cardine/tasks/056.json").exists())
                self.assertEqual(self.git("write-tree", cwd=self.worker).stdout, before)


    def test_advance_governed_missing_state_keeps_import_resume(self):
        self.start()
        result, blocked = owner_lifecycle_closure.advance_task_closure(
            "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
        self.assertTrue(blocked)
        # Both presets now use the same contract-aware closure recovery.
        self.assertIn("task state import 056", result["resume"])
        self.assertNotIn("task close 056", result["resume"])
        self.assertNotIn("worktree advance 056", result["resume"])
        self.assertEqual(result["resume"], " && ".join(result["commands"]))

    def test_advance_terminal_state_reaches_stage(self):
        self.start(workflow="single", preset="lean")
        self.write_state(required=False)
        original = owner_integration_merge.stage_task_integration
        with mock.patch.object(owner_lifecycle_closure, "stage_task_integration", wraps=original) as stage:
            result, blocked = owner_lifecycle_closure.advance_task_closure(
                "056", self.worktree_root, ["test task"], [0], accepted=True, supplied_project=self.primary)
        stage.assert_called_once()
        self.assertFalse(blocked)
        self.assertEqual(result["action_required"], "run-candidate-validation")
        owner_integration_merge.abort_task_integration("056", self.primary)

    def test_missing_state_resume_selects_registered_worktree(self):
        self.start()
        resume = owner_stops_render.stop_resume("TASK_STATE_MISSING", task_id="056", project=self.primary)
        self.assertEqual(shlex.split(resume)[shlex.split(resume).index("--project") + 1], str(self.worker))
        (self.worker / ".cardine/tasks").mkdir()
        error = self.assert_stop("TASK_STATE_MISSING", ".cardine/tasks/056.json")
        self.assertIn(resume, str(error))

    def test_legacy_stage_is_labeled_and_missing_approval_blocks(self):
        self.start()
        report = self.worker / "tasks/reviews/056.md"
        report.parent.mkdir(exist_ok=True)
        report.write_text("## Attempt 1 — APPROVE\n")
        self.commit()
        self.assert_stop("TASK_STATE_MISSING", "tracked state")
        self.write_state(required=True, verdict=None)
        self.assert_stop("REVIEW_NOT_APPROVED", "review.verdict")
