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
from cardine.integration import projections as owner_integration_projections
import cardine.integration.decision as integration_decision
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage

import worktree_support as support


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
        path = self.primary / ".meridian/candidate-validation.json"
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
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [], "validation_commands": ["pytest -q"],
        }), encoding="utf-8")
        (self.primary / ".meridian/candidate-validation.json").unlink()
        self.git("add", ".meridian/candidate-validation.json")
        self.git("commit", "-m", "remove declaration")
        with self.assertRaisesRegex(shared_errors.CardineError, "UNDECLARED_VALIDATION_COMMANDS"):
            owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
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
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        validation_path = self.root / "candidate-validation.json"
        validation_path.write_text(json.dumps({
            "candidate_tree": staged["candidate_tree"], "passed": True,
            "scope": "bounded", "commands": ["python3 scripts/check_repository.py"],
        }), encoding="utf-8")

        with self.assertRaisesRegex(shared_errors.CardineError, r"git diff --check"):
            owner_integration_merge.finalize_task_integration("056", validation_path, self.primary)
        (self.primary / ".meridian/candidate-validation.json").write_text(
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
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_evidence_command_records_git_facts_without_running_validation(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        previous = Path.cwd()
        try:
            os.chdir(task_worktree)
            recorded = owner_integration_evidence.record_task_evidence(
                "056", self.worktree_root, ["python3 -m unittest"], [0],
                accepted=True,
                task_dependencies=[], task_behavioral_surfaces=[],
                main_advanced_dependencies=[], main_advanced_behavioral_surfaces=[],
                full_validation_required=False, supplied_project=self.primary,
            )
        finally:
            os.chdir(previous)
        evidence = json.loads(Path(str(recorded["evidence"])).read_text(encoding="utf-8"))
        self.assertEqual(evidence["validated_task_commit"], self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip())
        self.assertEqual(evidence["validated_base_commit"], self.base)
        self.assertEqual(evidence["task_paths"], ["feature.txt"])
        self.assertEqual(evidence["validation_commands"], ["python3 -m unittest"])
        self.assertEqual(evidence["validation_exit_codes"], [0])


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
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": [], "task_dependencies": [], "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [], "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
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
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"], "task_dependencies": [], "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [], "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "BOUNDED")
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_completes_rows_after_main_registration_advance(self) -> None:
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
            plan.read_text(encoding="utf-8") + "- `[ ]` 999 — Registered\n",
            encoding="utf-8",
        )
        self.git("add", "tasks/QUEUE.md", "PROJECT_PLAN.md")
        self.git("commit", "-m", "register tasks on main")
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")

        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "BOUNDED")
        self.assertIn("| `[x]` | 056 | Lifecycle |", queue.read_text(encoding="utf-8"))
        self.assertIn("- `[x]` 056 — Lifecycle", plan.read_text(encoding="utf-8"))
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_reports_an_unreadable_queue_section_without_changing_the_tree(self) -> None:
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
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")

        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(len(staged["warnings"]), 1)
        self.assertIn("## Phase 2 — Unreadable", staged["warnings"][0])
        report = {item["section"]: item for item in staged["archival"]}
        self.assertFalse(report["## Phase 2 — Unreadable"]["archive"])
        self.assertTrue(report["## Phase 2 — Unreadable"]["reason"])
        self.assertIn(unreadable, queue.read_text(encoding="utf-8"))
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_queue_archival_warnings_name_the_unrecognized_section_and_reason(self) -> None:
        issue_example = (
            "## Phase 2 — Wrong level\n\n"
            "| Status | ID | Title | Dependencies | Estimate |\n|---|---|---|---|---|\n"
            "| `[x]` | 090 | Done | — | 1h |\n"
        )
        warnings = owner_integration_projections._queue_archival_warnings(issue_example)
        self.assertEqual(len(warnings), 1)
        self.assertIn("## Phase 2 — Wrong level", warnings[0])
        self.assertIn("heading level 2", warnings[0])
        column_order = (
            "### Phase 3 — Column order\n\n"
            "| ID | Status | Title |\n|---|---|---|\n| 090 | `[x]` | Done |\n"
        )
        warnings = owner_integration_projections._queue_archival_warnings(column_order)
        self.assertEqual(len(warnings), 1)
        self.assertIn("### Phase 3 — Column order", warnings[0])
        self.assertIn("expected columns", warnings[0])


    def test_queue_archival_warnings_ignore_recognized_sections_and_tables_without_status(self) -> None:
        contents = (
            "### Phase 1 — Open\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| `[x]` | 056 | Lifecycle |\n\n"
            "#### Nested\n\n| Status | ID |\n|---|---|\n| `[ ]` | 057 |\n"
        )
        self.assertEqual(owner_integration_projections._queue_archival_warnings(contents), [])
        notes = "## Notes\n\n| Term | Meaning |\n|---|---|\n| a | b |\n"
        self.assertEqual(owner_integration_projections._queue_archival_warnings(notes), [])


    def test_queue_archival_warnings_report_a_section_held_open_by_inconclusive(self) -> None:
        header = (
            "### Phase 1 — Governed\n\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---:|---|---|---|---|---|---|\n"
        )
        held = header + (
            "| 1 | 056 | P0 | INCONCLUSIVE | SPIKE | — | [056](056.md) |\n"
            "| 2 | 057 | P0 | ACCEPTED | NOT_REQUIRED | — | [057](057.md) |\n"
        )
        warnings = owner_integration_projections._queue_archival_warnings(held, "governed-sdd")
        self.assertEqual(len(warnings), 1)
        self.assertIn("INCONCLUSIVE", warnings[0])
        self.assertIn("056", warnings[0])
        self.assertNotIn("057", warnings[0])
        queued = held.replace("ACCEPTED", "QUEUED")
        self.assertEqual(owner_integration_projections._queue_archival_warnings(queued, "governed-sdd"), [])
        retained, archive = owner_integration_projections._archive_completed_queue_sections(
            held, self.primary / "tasks/QUEUE.md", self.primary / "tasks/QUEUE_ARCHIVE.md", "governed-sdd"
        )
        self.assertEqual(retained, held)
        self.assertIsNone(archive)


    def test_stage_uses_the_declared_project_plan(self) -> None:
        plan = self.primary / "docs/PLAN.md"
        plan.parent.mkdir()
        (self.primary / "PROJECT_PLAN.md").rename(plan)
        declaration = self.primary / ".meridian/project.json"
        declaration.write_text(json.dumps({"version": 1, "locations": {"plan": "docs/PLAN.md"}}), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "declare custom project plan")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")

        owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertIn("- `[x]` 056 — Lifecycle", plan.read_text(encoding="utf-8"))
        self.assertFalse((self.primary / "PROJECT_PLAN.md").exists())
        self.assertIn("docs/PLAN.md", self.git("diff", "--cached", "--name-only").stdout.splitlines())
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_accepts_exact_task_record_archive_after_validation(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        validated_task = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()

        queue = task_worktree / "tasks/QUEUE.md"
        queue.write_text(queue.read_text(encoding="utf-8").replace("`[ ]`", "`[x]`"), encoding="utf-8")
        plan = task_worktree / "PROJECT_PLAN.md"
        plan.write_text("- `[x]` 056 — Lifecycle\n", encoding="utf-8")
        handoff = task_worktree / "tasks/handoffs/056.md"
        handoff.parent.mkdir()
        handoff.write_text("validated\n", encoding="utf-8")
        archive = task_worktree / "tasks/done"
        archive.mkdir()
        self.git("mv", "tasks/056-lifecycle.md", "tasks/done/056-lifecycle.md", cwd=task_worktree)
        self.git("add", "tasks/QUEUE.md", "PROJECT_PLAN.md", "tasks/handoffs/056.md", cwd=task_worktree)
        self.git("commit", "-m", "close task", cwd=task_worktree)

        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True,
            "validation_passed": True,
            "validated_task_commit": validated_task,
            "validated_base_commit": self.base,
            "full_validation_required": False,
            "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"],
            "task_dependencies": [],
            "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")

        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "REUSE")
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_stage_relinks_the_queue_row_to_the_archived_task_record(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            "| Status | ID | Title | Task file |\n|---|---|---|---|\n"
            "| `[ ]` | 056 | Lifecycle | [056](056-lifecycle.md) |\n",
            encoding="utf-8",
        )
        self.git("add", "tasks/QUEUE.md")
        self.git("commit", "-m", "link the task row")
        base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        validated_task = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        (task_worktree / "tasks/done").mkdir()
        self.git("mv", "tasks/056-lifecycle.md", "tasks/done/056-lifecycle.md", cwd=task_worktree)
        self.git("commit", "-m", "archive task record", cwd=task_worktree)
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True,
            "validation_passed": True,
            "validated_task_commit": validated_task,
            "validated_base_commit": base,
            "full_validation_required": False,
            "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"],
            "task_dependencies": [],
            "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")

        owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        row = [line for line in queue.read_text(encoding="utf-8").splitlines() if "| 056 |" in line][0]
        self.assertEqual(row, "| `[x]` | 056 | Lifecycle | [056](done/056-lifecycle.md) |")
        self.assertTrue((self.primary / "tasks/done/056-lifecycle.md").is_file())
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_lifecycle_change_parser_rejects_inexact_task_record_changes(self) -> None:
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        active = "tasks/056-lifecycle.md"
        archive = "tasks/done/056-lifecycle.md"
        invalid_diffs = {
            "deletion": f"D\0{active}\0",
            "separate archive addition": f"A\0{archive}\0",
            "changed-content rename": f"R099\0{active}\0{archive}\0",
            "wrong archive destination": f"R100\0{active}\0tasks/done/other.md\0",
            "different task path": "A\0tasks/done/057-other.md\0",
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


    def test_completion_rows_reject_unknown_shape_without_editing_queue(self) -> None:
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        queue = self.primary / "tasks/QUEUE.md"
        original_queue = queue.read_text(encoding="utf-8")
        (self.primary / "PROJECT_PLAN.md").write_text("Task 056: TODO\n", encoding="utf-8")

        with self.assertRaisesRegex(shared_errors.CardineError, r"unrecognized completion row"):
            owner_integration_projections._apply_task_completion_rows(self.primary, identity)

        self.assertEqual(queue.read_text(encoding="utf-8"), original_queue)


    def test_completion_rows_archive_a_closing_phase_and_create_the_archive(self) -> None:
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            "### Phase 1 — Closing\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n",
            encoding="utf-8",
        )
        owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        archive = self.primary / "tasks/QUEUE_ARCHIVE.md"
        self.assertEqual(queue.read_text(encoding="utf-8"), "\n")
        self.assertIn("### Phase 1 — Closing", archive.read_text(encoding="utf-8"))
        self.assertIn("| `[x]` | 056 | Lifecycle |", archive.read_text(encoding="utf-8"))


    def test_archival_checks_all_tables_and_nested_rows_in_both_modes(self) -> None:
        for mode in ("lean-delivery", "governed-sdd"):
            if mode == "lean-delivery":
                header = "| Status | ID | Title |\n|---|---|---|\n"
                closed = "| `[x]` | A | Done |\n"
                terminals = ("[x]",)
                open_states = ("[ ]", "[/]")
                row = lambda status: f"| `{status}` | B | Other |\n"
            else:
                header = "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n|---|---|---|---|---|---|---|\n"
                closed = "| 1 | A | P0 | ACCEPTED | NOT_REQUIRED | — | A.md |\n"
                terminals = ("ACCEPTED", "ANSWERED")
                open_states = ("QUEUED", "IN_PROGRESS", "CHANGES_REQUESTED", "READY_FOR_REVIEW", "INCONCLUSIVE")
                row = lambda status: f"| 2 | B | P0 | {status} | SPIKE | — | B.md |\n"
            for nested in ("", "#### Nested\n", "##### Deep\n"):
                for status in terminals + open_states:
                    with self.subTest(mode=mode, nested=nested, status=status):
                        contents = "### Phase\n" + header + closed + "\n" + nested + header + row(status)
                        retained, archive = owner_integration_projections._archive_completed_queue_sections(
                            contents, self.primary / "custom/QUEUE.md", self.primary / "archive.md", mode
                        )
                        if status in terminals:
                            self.assertEqual(retained, "\n")
                            self.assertEqual((archive or "").count(closed), 1)
                            self.assertEqual((archive or "").count(row(status)), 1)
                        else:
                            self.assertEqual(retained, contents)
                            self.assertIsNone(archive)
                for malformed in (header + row("UNKNOWN"), header.splitlines()[0] + "\n", header + row(terminals[0]).replace(" | B |", " | B | extra |")):
                    contents = "### Ambiguous\n" + header + closed + "\n" + nested + malformed
                    retained, archive = owner_integration_projections._archive_completed_queue_sections(
                        contents, self.primary / "QUEUE.md", self.primary / "archive.md", mode
                    )
                    self.assertEqual(retained, contents)
                    self.assertIsNone(archive)
                    warnings = owner_integration_projections._queue_archival_warnings(contents, mode)
                    self.assertEqual(len(warnings), 1)
                    self.assertIn("### Ambiguous", warnings[0])


    def test_archival_mixed_boundaries_do_not_duplicate_nested_content(self) -> None:
        table = "| Status | ID | Title |\n|---|---|---|\n| `[x]` | A | Done |\n"
        contents = "# Queue\n## Parent\n### One\n" + table + "#### Notes\nText\n### Two\n" + table + "# Later\nKeep me\n"
        retained, archive = owner_integration_projections._archive_completed_queue_sections(
            contents, self.primary / "QUEUE.md", self.primary / "archive.md"
        )
        self.assertEqual(retained, "# Queue\n## Parent\n# Later\nKeep me\n")
        self.assertEqual((archive or "").count("#### Notes"), 1)
        self.assertEqual((archive or "").count(table), 2)
        self.assertNotIn("Keep me", archive or "")
        self.assertEqual(owner_integration_projections._queue_archival_warnings(contents), [])


    def test_issue_8_archival_does_not_carry_later_open_phase(self) -> None:
        contents = (
            "## Phase A\n### Completed\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 1 | A | P0 | ACCEPTED | NOT_REQUIRED | — | A.md |\n"
            "## Phase B\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 1 | B-SPIKE | P0 | QUEUED | SPIKE | — | B.md |\n"
        )
        retained, archive = owner_integration_projections._archive_completed_queue_sections(
            contents, self.primary / "docs/QUEUE.md", self.primary / "archive.md", "governed-sdd"
        )
        self.assertIn("B-SPIKE", retained)
        self.assertNotIn("B-SPIKE", archive or "")
        self.assertIn("A.md", archive or "")
        self.assertNotIn("tasks/QUEUE.md", archive or "")
        warnings = owner_integration_projections._queue_archival_warnings(contents, "governed-sdd")
        self.assertEqual(len(warnings), 1)
        self.assertIn("## Phase B", warnings[0])


    def test_completed_queue_archival_leaves_an_open_phase_in_place(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        contents = (
            "### Phase 1 — Open\n\n"
            "| Status | ID | Title |\n|---|---|---|\n"
            "| `[x]` | 056 | Lifecycle |\n| `[ ]` | 057 | Follow-up |\n"
        )
        queue.write_text(contents, encoding="utf-8")
        archived, archive_contents = owner_integration_projections._archive_completed_queue_sections(
            contents, queue, self.primary / "tasks/QUEUE_ARCHIVE.md"
        )
        self.assertEqual(archived, contents)
        self.assertIsNone(archive_contents)


    def test_completion_rows_complete_an_in_progress_task(self) -> None:
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        queue = self.primary / "tasks/QUEUE.md"
        plan = self.primary / "PROJECT_PLAN.md"
        queue.write_text(
            queue.read_text(encoding="utf-8").replace("`[ ]`", "`[/]`"), encoding="utf-8"
        )
        plan.write_text("- `[/]` 056 — Lifecycle\n", encoding="utf-8")
        owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        self.assertIn("| `[x]` | 056 | Lifecycle |", queue.read_text(encoding="utf-8"))
        self.assertEqual(plan.read_text(encoding="utf-8"), "- `[x]` 056 — Lifecycle\n")


    def test_completed_queue_archival_keeps_a_section_with_an_in_progress_row(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        contents = (
            "### Phase 1 — Open\n\n"
            "| Status | ID | Title |\n|---|---|---|\n"
            "| `[x]` | 056 | Lifecycle |\n| `[/]` | 057 | Follow-up |\n"
        )
        queue.write_text(contents, encoding="utf-8")
        archived, archive_contents = owner_integration_projections._archive_completed_queue_sections(
            contents, queue, self.primary / "tasks/QUEUE_ARCHIVE.md"
        )
        self.assertEqual(archived, contents)
        self.assertIsNone(archive_contents)


    def test_completed_queue_archival_is_idempotent_on_rerun(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        contents = (
            "### Phase 1 — Closing\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| `[x]` | 056 | Lifecycle |\n"
        )
        archived, archive_contents = owner_integration_projections._archive_completed_queue_sections(
            contents, queue, self.primary / "tasks/QUEUE_ARCHIVE.md"
        )
        archive = self.primary / "tasks/QUEUE_ARCHIVE.md"
        archive.write_text(archive_contents or "", encoding="utf-8")
        repeated_queue, repeated_archive = owner_integration_projections._archive_completed_queue_sections(
            archived, queue, archive
        )
        self.assertEqual(repeated_queue, archived)
        self.assertIsNone(repeated_archive)


    def test_completion_rows_retain_ambiguous_archival_section_with_warning(self) -> None:
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        queue = self.primary / "tasks/QUEUE.md"
        contents = (
            "### Phase 1 — Current\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n\n"
            "### Phase 2 — Malformed\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| [x] | 057 | Malformed status |\n"
        )
        queue.write_text(contents, encoding="utf-8")
        result = owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        retained = queue.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn(contents[contents.index("### Phase 2"):], retained)
        warnings = owner_integration_projections._queue_archival_warnings(retained)
        self.assertEqual(len(warnings), 1)
        self.assertIn("### Phase 2 — Malformed", warnings[0])
        self.assertIn("unrecognized task row", warnings[0])


    def test_stage_blocks_invalid_archive_before_creating_lifecycle_state(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        validated_task = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        archive = task_worktree / "tasks/done"
        archive.mkdir()
        self.git("mv", "tasks/056-lifecycle.md", "tasks/done/other.md", cwd=task_worktree)
        self.git("commit", "-am", "archive to wrong destination", cwd=task_worktree)
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": validated_task, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        state_path, lease_path, integration_path = owner_worktree_storage._lifecycle_paths(self.primary, identity)
        references = self.git("show-ref").stdout
        worktree_state = state_path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, r"paths changed after validation: .*other.md"):
            owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)
        self.assertEqual(self.git("show-ref").stdout, references)
        self.assertEqual(state_path.read_text(encoding="utf-8"), worktree_state)
        self.assertFalse(lease_path.exists())
        self.assertFalse(integration_path.exists())
        self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())


    def test_missing_validation_evidence_is_blocked(self) -> None:
        decision = integration_decision.decide_integration_validation(
            evidence_complete=False,
            validated_task_commit="",
            current_task_commit="task",
            validated_base_commit=self.base,
            current_main_commit=self.base,
            validated_base_is_task_ancestor=True,
            full_validation_required=False,
        )
        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.BLOCKED)


    def test_governance_only_commit_after_validation_keeps_evidence_current(self) -> None:
        decision = integration_decision.decide_integration_validation(
            evidence_complete=True,
            validated_task_commit="validated",
            current_task_commit="accepted",
            validated_base_commit=self.base,
            current_main_commit=self.base,
            validated_base_is_task_ancestor=True,
            validated_task_is_current_ancestor=True,
            relevant_tree_unchanged_after_validation=True,
            full_validation_required=False,
        )
        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.REUSE)


    def test_task_can_require_full_combined_tree_validation(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        decision = self.validation_decision(task_commit, full_required=True)

        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.FULL)
        passed, invoked = self.run_candidate_gate("task-055", decision)
        self.assertTrue(passed)
        self.assertIn("complete baseline", invoked)


    def test_unknown_advanced_main_interaction_is_blocked(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        (self.primary / "advance.txt").write_text("main change\n", encoding="utf-8")
        self.git("add", "advance.txt")
        self.git("commit", "-m", "advance main")

        decision = self.validation_decision(task_commit, assessment_complete=False)
        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.BLOCKED)


    def test_lean_completion_matrix_handles_links_records_and_plan_rows(self) -> None:
        links = {"active": "[056](056-lifecycle.md)", "archived": "[056](done/056-lifecycle.md)", "absent": "—"}
        for status in ("[ ]", "[/]", "[x]"):
            for link_name, link in links.items():
                for archived_record in (False, True):
                    for plan_present in (False, True):
                        with self.subTest(status=status, link=link_name, archived=archived_record, plan=plan_present):
                            queue = self.primary / "tasks/QUEUE.md"
                            queue.write_text(
                                "### Phase 1 — Lean\n\n| Status | ID | Title | Task file |\n|---|---|---|---|\n"
                                f"| `{status}` | 056 | Lifecycle | {link} |\n"
                                "| `[ ]` | 057 | Follow-up | [057](057.md) |\n",
                                encoding="utf-8",
                            )
                            plan = self.primary / "PROJECT_PLAN.md"
                            if plan_present:
                                plan.write_text("- `[ ]` 056 — Lifecycle\n", encoding="utf-8")
                            elif plan.exists():
                                plan.unlink()
                            active = self.primary / "tasks/056-lifecycle.md"
                            done = self.primary / "tasks/done/056-lifecycle.md"
                            done.parent.mkdir(exist_ok=True)
                            if not active.exists():
                                done.rename(active)
                            identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
                            if archived_record:
                                active.rename(done)
                            if not plan_present:
                                with self.assertRaisesRegex(shared_errors.CardineError, "unrecognized completion row"):
                                    owner_integration_projections._apply_task_completion_rows(self.primary, identity)
                                continue
                            owner_integration_projections._apply_task_completion_rows(self.primary, identity)
                            row = next(line for line in queue.read_text(encoding="utf-8").splitlines() if "| 056 |" in line)
                            self.assertIn("| `[x]` | 056 |", row)
                            if link_name != "absent":
                                expected = "done/056-lifecycle.md" if archived_record else "056-lifecycle.md"
                                self.assertIn(f"[056]({expected})", row)
                            self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())



if __name__ == "__main__":
    unittest.main()
