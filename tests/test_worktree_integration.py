"""Task-worktree integration tests."""

from __future__ import annotations

import subprocess
import sys
import unittest
import json
import os
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cardine.integration import merge as owner_integration_merge
from cardine.integration import evidence as owner_integration_evidence
import cardine.integration.decision as integration_decision
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage

import worktree_support as support
from task_contract_support import freeze_record


class WorktreeIntegrationTest(support.BoundedWorktreeLifecycleFixture):
    def test_candidate_validation_commands_cover_each_decision(self) -> None:
        baseline = "set -o pipefail; python3 scripts/check_repository.py 2>&1 | tail -n 200"
        suite = "python3 -m unittest discover -s tests -q 2>&1 | tail -n 40"
        for decision, commands, expected in (
            ("REUSE", ["git diff --check", baseline], ()),
            ("BOUNDED", ["git diff --check", baseline], ()),
            ("FULL", ["git diff --check", baseline, suite], ()),
            ("REUSE", [baseline], ("git diff --check",)),
            ("BOUNDED", [], ("git diff --check", "scripts/check_repository.py")),
            ("FULL", [suite], ("git diff --check", "scripts/check_repository.py")),
            ("FULL", ["git diff --check", baseline], ("unittest discover",)),
        ):
            with self.subTest(decision=decision, commands=commands):
                self.assertEqual(
                    owner_integration_merge.missing_candidate_validation_commands(decision, commands), expected
                )


    def test_candidate_validation_declaration_states_and_malformed_input(self) -> None:
        path = self.primary / ".cardine/candidate-validation.json"
        path.write_text(json.dumps({"version": 1, "state": "none"}), encoding="utf-8")
        self.assertEqual(owner_integration_evidence.candidate_validation_declaration(self.primary), ("none", {}))
        path.unlink()
        self.assertEqual(owner_integration_evidence.candidate_validation_declaration(self.primary), ("undeclared", {}))
        path.write_text('{"version": 1, "state": "declared", "outcomes": {}}', encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, "outcomes must declare"):
            owner_integration_evidence.candidate_validation_declaration(self.primary)


    def test_undeclared_validation_stops_before_lease_or_merge(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        self.measure(task_worktree)
        (self.primary / ".cardine/candidate-validation.json").unlink()
        self.git("add", ".cardine/candidate-validation.json")
        self.git("commit", "-m", "remove declaration")
        # Exercise the stop branch directly: modern task fixtures freeze candidate
        # commands and no longer fall back to the mutable project declaration.
        with mock.patch.object(owner_integration_merge, "candidate_validation_declaration",
                               return_value=("undeclared", {})), self.assertRaisesRegex(
                                   shared_errors.CardineError, "UNDECLARED_VALIDATION_COMMANDS"):
            owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        _state, lease_path, integration_path = owner_worktree_storage._lifecycle_paths(self.primary, identity)
        self.assertFalse(lease_path.exists())
        self.assertFalse(integration_path.exists())
        self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())


    def test_finalize_rejection_for_missing_command_keeps_staged_state(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        self.measure(task_worktree)
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        validation_path = self.root / "candidate-validation.json"
        validation_path.write_text(json.dumps({
            "candidate_tree": staged["candidate_tree"], "passed": True,
            "scope": "bounded", "commands": ["python3 scripts/check_repository.py"],
        }), encoding="utf-8")

        with self.assertRaisesRegex(shared_errors.CardineError, r"git diff --check"):
            owner_integration_merge.finalize_task_integration("056", validation_path, self.primary)
        declaration = self.primary / ".cardine/candidate-validation.json"
        original_policy = declaration.read_bytes()
        declaration.write_text(
            json.dumps({"version": 1, "state": "none"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(shared_errors.CardineError, r"git diff --check"):
            owner_integration_merge.finalize_task_integration("056", validation_path, self.primary)

        _state, lease_path, integration_path = owner_worktree_storage._lifecycle_paths(
            self.primary, owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        )
        self.assertTrue(lease_path.is_file())
        self.assertTrue(integration_path.is_file())
        self.assertTrue((self.primary / ".git/MERGE_HEAD").is_file())
        foreign_policy = declaration.read_bytes()
        with self.assertRaisesRegex(shared_errors.CardineError, 'foreign candidate changes'):
            owner_integration_merge.abort_task_integration('056', self.primary)
        self.assertEqual(declaration.read_bytes(), foreign_policy)
        self.assertTrue(lease_path.exists())
        self.assertTrue(integration_path.exists())
        declaration.write_bytes(original_policy)  # Fixture operator restores its own policy edit.
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_recomputes_main_path_overlap_to_require_full_validation(self) -> None:
        (self.primary / "feature.txt").write_text("first\nmiddle\nlast\n", encoding="utf-8")
        self.git("add", "feature.txt")
        self.git("commit", "-m", "add feature base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("task\nmiddle\nlast\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        (self.primary / "feature.txt").write_text("first\nmiddle\nmain\n", encoding="utf-8")
        self.git("add", "feature.txt")
        self.git("commit", "-m", "advance main")
        self.measure(task_worktree)
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        self.assertEqual(staged["decision"], "FULL")
        self.assertEqual(staged["main_advanced_paths"], ["feature.txt"])
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_keeps_independent_main_advance_bounded(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("task\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        (self.primary / "independent.txt").write_text("main\n", encoding="utf-8")
        self.git("add", "independent.txt")
        self.git("commit", "-m", "advance main independently")
        self.measure(task_worktree)
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        self.assertEqual(staged["decision"], "BOUNDED")
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_completes_rows_after_main_registration_advance(self) -> None:
        freeze_record(self.primary, "056", self.primary / "tasks/056-lifecycle.md")
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-m", "freeze fixture contract")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            queue.read_text(encoding="utf-8") + "".join(
                f"| `[ ]` | {index:03d} | Registered |\n" for index in range(10)
            ),
            encoding="utf-8",
        )
        plan = self.primary / "PROJECT_PLAN.md"
        plan.write_text(
            plan.read_text(encoding="utf-8") + "\n<!-- cardine-status:begin -->\n<!-- cardine-status:end -->\n",
            encoding="utf-8",
        )
        self.git("add", "tasks/QUEUE.md", "PROJECT_PLAN.md")
        self.git("commit", "-m", "register tasks on main")
        self.measure(task_worktree)

        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        self.assertEqual(staged["decision"], "BOUNDED")
        self.assertEqual(staged["views"]["status"], "REGENERATED", staged)
        self.assertIn("cardine status --write", queue.read_text(encoding="utf-8"))
        self.assertNotIn("Registered", queue.read_text(encoding="utf-8"))
        self.assertIn("| done | 056 |", plan.read_text(encoding="utf-8"))
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_reports_stale_views_and_keeps_a_hand_written_queue(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        queue = self.primary / "tasks/QUEUE.md"
        unreadable = (
            "\n## Phase 2 — Unreadable\n\n"
            "| Status | ID | Title | Dependencies | Estimate |\n|---|---|---|---|---|\n"
            "| `[x]` | 090 | Done | — | 1h |\n"
        )
        queue.write_text(queue.read_text(encoding="utf-8") + unreadable, encoding="utf-8")
        self.git("add", "tasks/QUEUE.md")
        self.git("commit", "-m", "register unreadable section")
        self.measure(task_worktree)

        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        self.assertNotIn("archival", staged)
        self.assertEqual(staged["views"]["status"], "STALE")
        self.assertEqual(len(staged["warnings"]), 1)
        self.assertIn("cardine status --write", staged["warnings"][0])
        self.assertIn(unreadable, queue.read_text(encoding="utf-8"))
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_uses_the_declared_project_plan(self) -> None:
        plan = self.primary / "docs/PLAN.md"
        plan.parent.mkdir()
        (self.primary / "PROJECT_PLAN.md").rename(plan)
        declaration = self.primary / ".cardine/project.json"
        declaration.write_text(json.dumps({"version": 1, "preset": "lean", "locations": {"plan": "docs/PLAN.md"}}), encoding="utf-8")
        plan.write_text("Narrative.\n<!-- cardine-status:begin -->\n<!-- cardine-status:end -->\n", encoding="utf-8")
        freeze_record(self.primary, "056", self.primary / "tasks/056-lifecycle.md")
        self.git("add", "-A")
        self.git("commit", "-m", "declare custom project plan")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        self.measure(task_worktree)

        owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        self.assertIn("| done | 056 |", plan.read_text(encoding="utf-8"))
        self.assertTrue(plan.read_text(encoding="utf-8").startswith("Narrative.\n"))
        self.assertFalse((self.primary / "PROJECT_PLAN.md").exists())
        self.assertIn("docs/PLAN.md", self.git("diff", "--cached", "--name-only").stdout.splitlines())
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_accepts_record_and_handoff_changes_after_validation(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        validated_task = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()

        record = task_worktree / "tasks/056-lifecycle.md"
        record.write_text(record.read_text(encoding="utf-8") + "\nValidation evidence.\n", encoding="utf-8")
        handoff = task_worktree / "tasks/handoffs/056.md"
        handoff.parent.mkdir()
        handoff.write_text("validated\n", encoding="utf-8")
        self.git("add", "tasks/056-lifecycle.md", "tasks/handoffs/056.md", cwd=task_worktree)
        self.git("commit", "-m", "close task", cwd=task_worktree)

        self.measure(task_worktree)

        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        self.assertEqual(staged["decision"], "REUSE")
        self.assertTrue((self.primary / "tasks/056-lifecycle.md").is_file())
        self.assertFalse((self.primary / "tasks/done").exists())
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_lifecycle_change_parser_rejects_inexact_task_record_changes(self) -> None:
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        active = "tasks/056-lifecycle.md"
        archive = "tasks/done/056-lifecycle.md"
        invalid_diffs = {
            "deletion": f"D\0{active}\0",
            "separate archive addition": f"A\0{archive}\0",
            "exact archive move": f"D\0{active}\0A\0{archive}\0",
            "wrong archive destination": f"D\0{active}\0A\0tasks/done/other.md\0",
            "different task path": "A\0tasks/done/057-other.md\0",
            "queue edit": "M\0tasks/QUEUE.md\0",
            "plan edit": "M\0PROJECT_PLAN.md\0",
            "queue archive": "A\0tasks/QUEUE_ARCHIVE.md\0",
        }
        for label, diff in invalid_diffs.items():
            with self.subTest(label=label), mock.patch.object(
                owner_integration_evidence,
                "_run_git",
                side_effect=(
                    subprocess.CompletedProcess([], 0, diff, ""),
                    subprocess.CompletedProcess([], 1, "", ""),
                ),
            ):
                unchanged, offending = owner_integration_evidence._lifecycle_changes_after_validation(
                    self.primary, identity, "validated", "current"
                )
                self.assertFalse(unchanged)
                self.assertTrue(offending)
        valid = f"M\0{active}\0A\0tasks/handoffs/056.md\0M\0.cardine/tasks/056.json\0"
        with mock.patch.object(owner_integration_evidence, "_run_git",
                               return_value=subprocess.CompletedProcess([], 0, valid, "")):
            self.assertEqual(owner_integration_evidence._lifecycle_changes_after_validation(
                self.primary, identity, "validated", "current"), (True, ()))


    def test_stage_blocks_invalid_archive_before_creating_lifecycle_state(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        self.measure(task_worktree)
        archive = task_worktree / "tasks/done"
        archive.mkdir()
        self.git("mv", "tasks/056-lifecycle.md", "tasks/done/other.md", cwd=task_worktree)
        self.git("commit", "-am", "archive to wrong destination", cwd=task_worktree)
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        state_path, lease_path, integration_path = owner_worktree_storage._lifecycle_paths(self.primary, identity)
        references = self.git("show-ref").stdout
        worktree_state = state_path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, "EVIDENCE_INCOMPLETE"):
            owner_integration_merge.stage_task_integration("056", self.worktree_root, None, self.primary)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)
        self.assertEqual(self.git("show-ref").stdout, references)
        self.assertEqual(state_path.read_text(encoding="utf-8"), worktree_state)
        self.assertFalse(lease_path.exists())
        self.assertFalse(integration_path.exists())
        self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())


    def test_missing_validation_evidence_is_blocked(self) -> None:
        decision = integration_decision.decide_integration_validation(
            validation_measured=False,
            validated_task_commit="",
            current_task_commit="task",
            validated_base_commit=self.base,
            current_main_commit=self.base,
            validated_base_is_task_ancestor=True,
        )
        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.BLOCKED)


    def test_governance_only_commit_after_validation_keeps_evidence_current(self) -> None:
        decision = integration_decision.decide_integration_validation(
            validation_measured=True,
            validated_task_commit="validated",
            current_task_commit="accepted",
            validated_base_commit=self.base,
            current_main_commit=self.base,
            validated_base_is_task_ancestor=True,
            validated_task_is_current_ancestor=True,
            relevant_tree_unchanged_after_validation=True,
        )
        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.REUSE)


    def test_unknown_advanced_main_independence_requires_full_validation(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: done"))
        (self.primary / "advance.txt").write_text("main change\n", encoding="utf-8")
        self.git("add", "advance.txt")
        self.git("commit", "-m", "advance main")

        decision = self.validation_decision(task_commit, task_paths=())
        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.FULL)
        passed, invoked = self.run_candidate_gate("task-055", decision)
        self.assertTrue(passed)
        self.assertIn("complete baseline", invoked)
