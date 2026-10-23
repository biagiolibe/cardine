"""Task-worktree integration projections tests."""

from __future__ import annotations

import subprocess
import sys
import unittest
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cardine.integration import merge as owner_integration_merge
from cardine.lifecycle import execution as owner_lifecycle_execution
from cardine.tasks import preflight as owner_tasks_preflight
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage
from cardine.tasks import contract as owner_tasks_contract

import worktree_support as support
from task_contract_support import freeze_record


class GovernedCompletionRowsTest(support.GovernedCompletionRowsFixture):
    """Completion rows use the shipped Governed template's table shape."""

    def test_governed_stage_succeeds_without_project_plan(self) -> None:
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
        self.assertEqual(staged["decision"], "REUSE")
        self.assertEqual(staged["landed_status"], "done")
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_governed_stage_accepts_an_owner_approved_required_review_task(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(queue.read_text(encoding="utf-8").replace("NOT_REQUIRED", "REQUIRED"), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "require review")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        validated = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        # `Accept <TASK-ID>` per docs/workflows/LIFECYCLE.md: an owner APPROVE
        # attempt in the review record, committed alone as `docs: accept <TASK-ID>`.
        review = task_worktree / "tasks/reviews/056.md"
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text(
            "# Review Record — 056\n\n## Attempt 1 — APPROVE\n\n- Approved by: owner\n"
            f"- Reviewed commit: `{validated}`\n- Base `main` commit: `{self.base}`\n",
            encoding="utf-8",
        )
        state_path = task_worktree / ".cardine/tasks/056.json"
        state = json.loads(state_path.read_text())
        state["contract"]["options"]["review"] = "required"
        state.setdefault("review", {}).update(required=True, verdict="APPROVE", reviewed_commit=validated, approved_by="owner")
        state_path.write_text(json.dumps(state))
        self.git("add", ".cardine/tasks/056.json", cwd=task_worktree)
        self.git("add", "tasks/reviews/056.md", cwd=task_worktree)
        self.git("commit", "-m", "docs: accept 056", cwd=task_worktree)
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": validated, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["landed_status"], "done")
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_governed_stage_accepts_a_template_spike_row_for_another_task(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            "### Phase 1 — Governed\n\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---:|---|---|---|---|---|---|\n"
            "| 1 | 055 | P0 | done | NOT_REQUIRED | — | [055](055-spike.md) |\n"
            "| 2 | 056 | P0 | queued | NOT_REQUIRED | — | [056](056-lifecycle.md) |\n",
            encoding="utf-8",
        )
        self.git("add", "tasks/QUEUE.md")
        self.git("commit", "-m", "add answered spike row")
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
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["landed_status"], "done")
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_governed_spike_integrates_declared_validation_evidence(self) -> None:
        docs = self.primary / "docs"
        docs.mkdir()
        (docs / "EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.primary / "tasks/056-lifecycle.md"
        task.write_text(
            "# Task 056\n\n> **ID**: `056`\n\nClass: spike\nReview: NOT_REQUIRED\nStatus: queued\n"
            "Question: Does the declared probe pass?\nTimebox: 1 iteration\n"
            "Deliverable: `docs/answer.md#result`\n\n## Authority\n\n"
            "## Validation\n\n- `probe`: `test -f docs/answer.md`\n",
            encoding="utf-8",
        )
        task.write_text(task.read_text(encoding="utf-8") + "\n" +
                        owner_tasks_preflight.execution_contract(self.primary, "056") + "\n", encoding="utf-8")
        freeze_record(self.primary, "056", task)
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(queue.read_text(encoding="utf-8").replace("NOT_REQUIRED", "SPIKE"), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "declare spike validation")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        (worktree / "docs/answer.md").write_text("# Result\n\nThe probe passes.\n", encoding="utf-8")
        validated = subprocess.run(
            [sys.executable, str(ROOT / "scripts/cardine_cli.py"), "execution", "validate", "056", "probe",
             "--project", str(worktree)], cwd=worktree, text=True, capture_output=True, check=False,
        )
        self.assertEqual(validated.returncode, 0, validated.stderr)
        state_path = worktree / ".cardine/tasks/056.json"
        state = json.loads(state_path.read_text())
        state["outcome"] = "ANSWERED"
        state_path.write_text(json.dumps(state))
        ledger = worktree / owner_tasks_contract.EXECUTION_EVIDENCE_PATH
        evidence_bytes = ledger.read_bytes()
        entry = json.loads(evidence_bytes)["056"][0]
        self.assertEqual({key: entry[key] for key in ("id", "command", "exitStatus")},
                         {"id": "probe", "command": "test -f docs/answer.md", "exitStatus": 0})
        self.assertEqual(entry["commit"], self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip())
        self.assertEqual(entry["sourceDigest"], owner_lifecycle_execution.execution_source_digest(worktree, "056"))
        task = worktree / "tasks/056-lifecycle.md"
        task.write_text(task.read_text(encoding="utf-8").replace("Status: queued", "Status: done"), encoding="utf-8")
        self.git("add", "-A", cwd=worktree)
        self.git("commit", "-m", "answer spike with durable evidence", cwd=worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": [str(owner_tasks_contract.EXECUTION_EVIDENCE_PATH), "docs/answer.md", "tasks/056-lifecycle.md"],
            "task_dependencies": [], "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [], "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        staged = owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "REUSE")
        self.assertEqual((self.primary / owner_tasks_contract.EXECUTION_EVIDENCE_PATH).read_bytes(), evidence_bytes)
        self.assertEqual(self.git("show", f":{owner_tasks_contract.EXECUTION_EVIDENCE_PATH}").stdout.encode(), evidence_bytes)
        candidate = self.root / "candidate-validation.json"
        candidate.write_text(json.dumps({
            "candidate_tree": staged["candidate_tree"], "passed": True, "scope": "bounded",
            "commands": ["git diff --check", "python3 scripts/check_repository.py", "test -f docs/answer.md"],
        }), encoding="utf-8")
        owner_integration_merge.finalize_task_integration("056", candidate, self.primary)
        self.assertEqual((self.primary / owner_tasks_contract.EXECUTION_EVIDENCE_PATH).read_bytes(), evidence_bytes)
        self.assertEqual((self.primary / "docs/answer.md").read_bytes(), (worktree / "docs/answer.md").read_bytes())
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())


    def test_spike_path_allowlist_stays_exact_and_does_not_restrict_normal_tasks(self) -> None:
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        task = worktree / "tasks/056-lifecycle.md"
        task.write_text(task.read_text(encoding="utf-8") +
                        "\nClass: SPIKE\nDeliverable: `docs/answer.md`\n", encoding="utf-8")
        state = freeze_record(worktree, "056", task)
        paths = [".cardine/execution-evidence.json", ".cardine/execution-evidence-extra.json",
                 ".cardine/other.json", "docs/answer.md", "docs/undeclared.md", "source.py",
                 "tasks/reviews/056.md", "tasks/reviews/057.md"]
        for path in paths:
            target = worktree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("changed\n", encoding="utf-8")
        self.git("add", "-A", cwd=worktree)
        self.git("commit", "-m", "exercise exact spike path boundary", cwd=worktree)
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        commit = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.assertEqual(set(owner_integration_merge._spike_disallowed_paths(self.primary.resolve(), identity, self.base, commit, state)), {
            ".cardine/execution-evidence-extra.json", ".cardine/other.json", "docs/undeclared.md", "source.py",
            "tasks/reviews/057.md",
        })
        task.write_text(task.read_text(encoding="utf-8").replace("Class: SPIKE", "Class: NORMAL"), encoding="utf-8")
        self.git("add", "tasks/056-lifecycle.md", cwd=worktree)
        self.git("commit", "-m", "exercise normal task path behavior", cwd=worktree)
        commit = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        # The edited Class line cannot lift the frozen spike boundary.
        self.assertIn("source.py", owner_integration_merge._spike_disallowed_paths(
            self.primary.resolve(), identity, self.base, commit, state))
        from copy import deepcopy
        standard = deepcopy(state)
        standard["contract"]["class"] = "standard"
        self.assertEqual(owner_integration_merge._spike_disallowed_paths(
            self.primary.resolve(), identity, self.base, commit, standard), ())


    def test_governed_stage_blocks_a_spike_source_change_before_a_lease(self) -> None:
        task = self.primary / "tasks/056-lifecycle.md"
        task.write_text(
            "# Task 056\n\n> **ID**: `056`\n\nClass: spike\nReview: NOT_REQUIRED\nStatus: done\nDeliverable: `docs/answer.md`\n",
            encoding="utf-8",
        )
        state_path = self.primary / ".cardine/tasks/056.json"
        state = json.loads(state_path.read_text())
        state["outcome"] = "ANSWERED"
        state_path.write_text(json.dumps(state))
        freeze_record(self.primary, "056", task)
        self.git("add", "tasks/056-lifecycle.md", ".cardine/tasks/056.json")
        self.git("commit", "-m", "declare spike task")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "source.py").write_text("blocked\n", encoding="utf-8")
        self.git("add", "source.py", cwd=task_worktree)
        self.git("commit", "-m", "change source", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True, "validation_passed": True,
            "validated_task_commit": task_commit, "validated_base_commit": self.base,
            "full_validation_required": False, "interaction_assessment_complete": True,
            "task_paths": ["source.py"], "task_dependencies": [],
            "task_behavioral_surfaces": [], "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, r"source.py"):
            owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        _state, lease, staged = owner_worktree_storage._lifecycle_paths(self.primary, identity)
        self.assertFalse(lease.exists())
        self.assertFalse(staged.exists())


    def test_owner_accept_text_uses_command_and_legacy_approve_attempt_is_supported(self) -> None:
        workflow = (ROOT / "templates/single/docs/LIFECYCLE_ORCHESTRATION.md").read_text(encoding="utf-8")
        record_template = (ROOT / "templates/single/docs/REVIEW_RECORD_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertIn("cardine review verdict <TASK-ID> APPROVE --owner", workflow)
        self.assertIn('`approved_by: "owner"`', workflow)
        self.assertIn("continue at C6 under the `Proceed with` authority", workflow)
        self.assertIn("owner acceptance adds `--owner`", record_template)
        heading = re.search(r"^## Attempt <N> — <(.+?)>$", record_template, re.MULTILINE)
        self.assertIsNotNone(heading)
        self.assertIn("APPROVE", heading.group(1))
