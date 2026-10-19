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
from cardine.integration import projections as owner_integration_projections
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage
from cardine.tasks import contract as owner_tasks_contract

import worktree_support as support


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
        self.assertIn(
            "| ACCEPTED | NOT_REQUIRED |",
            (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"),
        )
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
        self.assertEqual(staged["completion"]["status"], "COMPLETED")
        self.assertEqual(staged["completion"]["reason"], "latest review verdict is APPROVE")
        self.assertIn(
            "| ACCEPTED | REQUIRED |",
            (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"),
        )
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_governed_stage_accepts_a_template_spike_row_for_another_task(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            "### Phase 1 — Governed\n\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---:|---|---|---|---|---|---|\n"
            "| 1 | 055 | P0 | ANSWERED | SPIKE | — | [055](055-spike.md) |\n"
            "| 2 | 056 | P0 | QUEUED | NOT_REQUIRED | — | [056](056-lifecycle.md) |\n",
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
        self.assertEqual(staged["completion"]["status"], "COMPLETED")
        self.assertIn("ANSWERED | SPIKE", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"))
        owner_integration_merge.abort_task_integration("056", self.primary)


    def test_governed_spike_completion_and_archival_terminal_states(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        task = self.primary / "tasks/056-lifecycle.md"
        task.write_text("# Task 056\n\n> **ID**: `056`\n\nClass: SPIKE\nStatus: ANSWERED\n", encoding="utf-8")
        contents = (
            "### Phase 1 — Governed\n\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---:|---|---|---|---|---|---|\n"
            "| 1 | 056 | P0 | QUEUED | SPIKE | — | [056](056-lifecycle.md) |\n"
        )
        queue.write_text(contents, encoding="utf-8")
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        result = owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn("ANSWERED | SPIKE", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"))
        inconclusive = contents.replace("QUEUED", "INCONCLUSIVE")
        retained, archive = owner_integration_projections._archive_completed_queue_sections(
            inconclusive, queue, self.primary / "tasks/QUEUE_ARCHIVE.md", "governed-sdd"
        )
        self.assertEqual(retained, inconclusive)
        self.assertIsNone(archive)


    def test_governed_spike_integrates_declared_validation_evidence(self) -> None:
        docs = self.primary / "docs"
        docs.mkdir()
        (docs / "EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.primary / "tasks/056-lifecycle.md"
        task.write_text(
            "# Task 056\n\n> **ID**: `056`\n\nClass: SPIKE\nStatus: QUEUED\n"
            "Question: Does the declared probe pass?\nTimebox: 1 iteration\n"
            "Deliverable: `docs/answer.md#result`\n\n## Authority\n\n"
            "## Validation\n\n- `probe`: `test -f docs/answer.md`\n",
            encoding="utf-8",
        )
        task.write_text(task.read_text(encoding="utf-8") + "\n" +
                        owner_tasks_preflight.execution_contract(self.primary, "056") + "\n", encoding="utf-8")
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(queue.read_text(encoding="utf-8").replace("NOT_REQUIRED", "SPIKE"), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-m", "declare spike validation")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        (worktree / "docs/answer.md").write_text("# Result\n\nThe probe passes.\n", encoding="utf-8")
        validated = subprocess.run(
            [sys.executable, str(ROOT / "scripts/meridian.py"), "execution", "validate", "056", "probe",
             "--project", str(worktree)], cwd=worktree, text=True, capture_output=True, check=False,
        )
        self.assertEqual(validated.returncode, 0, validated.stderr)
        ledger = worktree / owner_tasks_contract.EXECUTION_EVIDENCE_PATH
        evidence_bytes = ledger.read_bytes()
        entry = json.loads(evidence_bytes)["056"][0]
        self.assertEqual({key: entry[key] for key in ("id", "command", "exitStatus")},
                         {"id": "probe", "command": "test -f docs/answer.md", "exitStatus": 0})
        self.assertEqual(entry["commit"], self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip())
        self.assertEqual(entry["sourceDigest"], owner_lifecycle_execution.execution_source_digest(worktree, "056"))
        task = worktree / "tasks/056-lifecycle.md"
        task.write_text(task.read_text(encoding="utf-8").replace("Status: QUEUED", "Status: ANSWERED"), encoding="utf-8")
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
            "commands": ["git diff --check", "python3 scripts/check_repository.py"],
        }), encoding="utf-8")
        owner_integration_merge.finalize_task_integration("056", candidate, self.primary)
        self.assertEqual((self.primary / owner_tasks_contract.EXECUTION_EVIDENCE_PATH).read_bytes(), evidence_bytes)
        self.assertEqual((self.primary / "docs/answer.md").read_bytes(), (worktree / "docs/answer.md").read_bytes())
        self.assertIn("ANSWERED | SPIKE", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"))


    def test_spike_path_allowlist_stays_exact_and_does_not_restrict_normal_tasks(self) -> None:
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        task = worktree / "tasks/056-lifecycle.md"
        task.write_text(task.read_text(encoding="utf-8") +
                        "\nClass: SPIKE\nDeliverable: `docs/answer.md`\n", encoding="utf-8")
        paths = [".meridian/execution-evidence.json", ".meridian/execution-evidence-extra.json",
                 ".meridian/other.json", "docs/answer.md", "docs/undeclared.md", "source.py"]
        for path in paths:
            target = worktree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("changed\n", encoding="utf-8")
        self.git("add", "-A", cwd=worktree)
        self.git("commit", "-m", "exercise exact spike path boundary", cwd=worktree)
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        commit = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.assertEqual(set(owner_integration_merge._spike_disallowed_paths(self.primary.resolve(), identity, self.base, commit)), {
            ".meridian/execution-evidence-extra.json", ".meridian/other.json", "docs/undeclared.md", "source.py",
        })
        task.write_text(task.read_text(encoding="utf-8").replace("Class: SPIKE", "Class: NORMAL"), encoding="utf-8")
        self.git("add", "tasks/056-lifecycle.md", cwd=worktree)
        self.git("commit", "-m", "exercise normal task path behavior", cwd=worktree)
        commit = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.assertEqual(owner_integration_merge._spike_disallowed_paths(self.primary.resolve(), identity, self.base, commit), ())


    def test_governed_stage_blocks_a_spike_source_change_before_a_lease(self) -> None:
        task = self.primary / "tasks/056-lifecycle.md"
        task.write_text(
            "# Task 056\n\n> **ID**: `056`\n\nClass: SPIKE\nStatus: ANSWERED\nDeliverable: `docs/answer.md`\n",
            encoding="utf-8",
        )
        self.git("add", "tasks/056-lifecycle.md")
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


    def test_governed_completion_matrix_relinks_archives_and_ignores_plan(self) -> None:
        statuses = ("QUEUED", "IN_PROGRESS", "CHANGES_REQUESTED", "READY_FOR_REVIEW", "ACCEPTED")
        links = {
            "active": "[056](056-lifecycle.md)",
            "archived": "[056](done/056-lifecycle.md)",
            "absent": "—",
        }
        for status in statuses:
            for link_name, link in links.items():
                for archived_record in (False, True):
                    for plan_present in (False, True):
                        with self.subTest(status=status, link=link_name, archived=archived_record, plan=plan_present):
                            queue = self.primary / "tasks/QUEUE.md"
                            queue.write_text(
                                "### Phase 1 — Governed\n\n"
                                "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
                                "|---:|---|---|---|---|---|---|\n"
                                f"| 1 | 056 | P0 | {status} | NOT_REQUIRED | — | {link} |\n"
                                "| 2 | 057 | P1 | QUEUED | NOT_REQUIRED | — | [057](057.md) |\n",
                                encoding="utf-8",
                            )
                            plan = self.primary / "PROJECT_PLAN.md"
                            if plan_present:
                                plan.write_text("unrelated plan\n", encoding="utf-8")
                            elif plan.exists():
                                plan.unlink()
                            active = self.primary / "tasks/056-lifecycle.md"
                            done = self.primary / "tasks/done/056-lifecycle.md"
                            done.parent.mkdir(exist_ok=True)
                            if not active.exists():
                                done.rename(active)
                            identity = owner_tasks_identity.resolve_task_identity(
                                self.primary, "056", "existing", check_queue_links=False
                            )
                            if archived_record:
                                active.rename(done)
                            owner_integration_projections._apply_task_completion_rows(self.primary, identity)
                            row = next(line for line in queue.read_text(encoding="utf-8").splitlines() if "| 056 |" in line)
                            self.assertIn("| ACCEPTED | NOT_REQUIRED |", row)
                            if link_name != "absent":
                                expected_link = "done/056-lifecycle.md" if archived_record else "056-lifecycle.md"
                                self.assertIn(f"[056]({expected_link})", row)
                            self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())


    def test_governed_required_review_is_not_accepted(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        original = queue.read_text(encoding="utf-8").replace("NOT_REQUIRED", "REQUIRED")
        queue.write_text(original, encoding="utf-8")
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        with self.assertRaisesRegex(shared_errors.CardineStop, "BLOCKED REVIEW_NOT_APPROVED:"):
            owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        self.assertEqual(queue.read_text(encoding="utf-8"), original)


    def test_governed_required_review_uses_the_latest_attempt(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            queue.read_text(encoding="utf-8").replace("NOT_REQUIRED", "REQUIRED")
            + "| 2 | 057 | P1 | QUEUED | NOT_REQUIRED | — | [057](057.md) |\n",
            encoding="utf-8",
        )
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        review = identity.review_path
        review.parent.mkdir(exist_ok=True)
        cases = {
            "approve": "## Attempt 1 — APPROVE\n",
            "changes requested": "## Attempt 1 — CHANGES_REQUESTED\n",
            "blocked": "## Attempt 1 — BLOCKED\n",
            "latest wins": "## Attempt 1 — APPROVE\n\n## Attempt 2 — CHANGES_REQUESTED\n",
            "missing": None,
            "malformed": "review pending\n",
        }
        for label, record in cases.items():
            with self.subTest(label=label):
                queue.write_text(queue.read_text(encoding="utf-8").replace("ACCEPTED", "QUEUED"), encoding="utf-8")
                if record is None:
                    review.unlink(missing_ok=True)
                else:
                    review.write_text(record, encoding="utf-8")
                if label == "approve":
                    result = owner_integration_projections._apply_task_completion_rows(self.primary, identity)
                else:
                    with self.assertRaisesRegex(shared_errors.CardineStop, "BLOCKED REVIEW_NOT_APPROVED:"):
                        owner_integration_projections._apply_task_completion_rows(self.primary, identity)
                row = next(line for line in queue.read_text(encoding="utf-8").splitlines() if "| 056 |" in line)
                if label == "approve":
                    self.assertIn("| ACCEPTED | REQUIRED |", row)
                    self.assertEqual(result["status"], "COMPLETED")
                else:
                    self.assertIn("| QUEUED | REQUIRED |", row)
                    self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())


    def test_owner_accept_text_uses_command_and_legacy_approve_attempt_is_supported(self) -> None:
        workflow = (ROOT / "templates/workflows/governed-sdd/docs/workflows/LIFECYCLE.md").read_text(encoding="utf-8")
        record_template = (ROOT / "templates/workflows/governed-sdd/docs/REVIEW_RECORD_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertIn("meridian review verdict <TASK-ID> APPROVE --owner", workflow)
        self.assertIn('`approved_by: "owner"`', workflow)
        self.assertIn("continue at C6 under the `Proceed with` authority", workflow)
        self.assertIn("owner acceptance adds `--owner`", record_template)
        heading = re.search(r"^## Attempt <N> — <(.+?)>$", record_template, re.MULTILINE)
        self.assertIsNotNone(heading)
        self.assertIn("APPROVE", heading.group(1))
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            queue.read_text(encoding="utf-8").replace("NOT_REQUIRED", "REQUIRED")
            + "| 2 | 057 | P1 | QUEUED | NOT_REQUIRED | — | [057](057.md) |\n",
            encoding="utf-8",
        )
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        identity.review_path.parent.mkdir(exist_ok=True)
        identity.review_path.write_text(
            "# Review Record — 056\n\n## Attempt 1 — CHANGES_REQUESTED\n\n- [x] P1 — fixed\n\n"
            "## Attempt 2 — APPROVE\n\n- Approved by: owner\n- Reviewed commit: `abc`\n- Base `main` commit: `def`\n",
            encoding="utf-8",
        )
        result = owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        row = next(line for line in queue.read_text(encoding="utf-8").splitlines() if "| 056 |" in line)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn("| ACCEPTED | REQUIRED |", row)


    def test_required_review_relinks_an_archived_task_without_accepting(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            "### Phase 1 — Governed\n\n| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---:|---|---|---|---|---|---|\n"
            "| 1 | 056 | P0 | QUEUED | REQUIRED | — | [056](056-lifecycle.md) |\n"
            "| 2 | 057 | P1 | QUEUED | NOT_REQUIRED | — | [057](057.md) |\n",
            encoding="utf-8",
        )
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
        archived = self.primary / "tasks/done/056-lifecycle.md"
        archived.parent.mkdir(exist_ok=True)
        identity.task_path.rename(archived)
        with self.assertRaisesRegex(shared_errors.CardineStop, "BLOCKED REVIEW_NOT_APPROVED:"):
            owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        row = next(line for line in queue.read_text(encoding="utf-8").splitlines() if "| 056 |" in line)
        self.assertIn("| QUEUED | REQUIRED |", row)
        self.assertIn("[056](056-lifecycle.md)", row)
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())


    def test_governed_archive_requires_every_row_accepted(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            "### Phase 1 — Governed\n\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---:|---|---|---|---|---|---|\n"
            "| 1 | 056 | P0 | QUEUED | NOT_REQUIRED | — | [056](056-lifecycle.md) |\n"
            "| 2 | 057 | P1 | QUEUED | NOT_REQUIRED | — | [057](057.md) |\n",
            encoding="utf-8",
        )
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        self.assertIn("| ACCEPTED |", queue.read_text(encoding="utf-8"))
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())


    def test_governed_unrecognized_row_blocks_without_queue_edit(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        original = queue.read_text(encoding="utf-8").replace("| 1 | 056 | P0 | QUEUED |", "| 1 | 056 | P0 | UNKNOWN |")
        queue.write_text(original, encoding="utf-8")
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        with self.assertRaisesRegex(shared_errors.CardineError, "unrecognized completion row"):
            owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        self.assertEqual(queue.read_text(encoding="utf-8"), original)


    def test_governed_project_shaped_queue_updates_only_status_and_is_not_archived(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        original = (
            "## Milestone 37 — Causes — complete\n\n"
            "| Order | Estimate | Status | Dependencies | ID | Priority |\n"
            "|---:|---|---|---|---|---|\n"
            "| 2 | 60–90m | QUEUED | — | `056` | P0 |\n"
        )
        queue.write_text(original, encoding="utf-8")
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
        task = identity.task_path
        task.write_text("# Task 056\n\nReview: NOT REQUIRED\n", encoding="utf-8")
        result = owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        expected = original.replace("QUEUED", "ACCEPTED")
        self.assertEqual(queue.read_text(encoding="utf-8"), expected)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())


    def test_governed_project_shaped_queue_uses_review_column_in_any_position(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        original = (
            "#### Milestone 37\n\n"
            "| ID | Review | Estimate | Status | Dependencies |\n"
            "|---|---|---|---|---|\n"
            "| 056 | REQUIRED | 60–90m | QUEUED | — |\n"
        )
        queue.write_text(original, encoding="utf-8")
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
        with self.assertRaisesRegex(shared_errors.CardineStop, "BLOCKED REVIEW_NOT_APPROVED:"):
            owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        self.assertEqual(queue.read_text(encoding="utf-8"), original)
        identity.review_path.parent.mkdir(exist_ok=True)
        identity.review_path.write_text("## Attempt 1 — APPROVE\n", encoding="utf-8")
        result = owner_integration_projections._apply_task_completion_rows(self.primary, identity)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(queue.read_text(encoding="utf-8"), original.replace("QUEUED", "ACCEPTED"))


    def test_governed_project_shaped_queue_rejects_ambiguous_or_invalid_rows(self) -> None:
        cases = {
            "missing status": (
                "### Milestone\n\n| ID | Estimate |\n|---|---|\n| 056 | 60m |\n",
                "no table header has both ID and Status columns",
            ),
            "duplicate": (
                "### One\n\n| ID | Status |\n|---|---|\n| 056 | QUEUED |\n\n"
                "### Two\n\n| ID | Status |\n|---|---|\n| 056 | QUEUED |\n",
                "appears 2 times",
            ),
            "cell count": (
                "### Milestone\n\n| ID | Status | Estimate |\n|---|---|---|\n| 056 | QUEUED |\n",
                "cell count differs",
            ),
            "unknown status": (
                "### Milestone\n\n| ID | Status |\n|---|---|\n| 056 | UNKNOWN |\n",
                "unknown Governed status",
            ),
        }
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
        queue = self.primary / "tasks/QUEUE.md"
        for label, (contents, message) in cases.items():
            with self.subTest(label=label):
                queue.write_text(contents, encoding="utf-8")
                with self.assertRaisesRegex(shared_errors.CardineError, message):
                    owner_integration_projections._apply_task_completion_rows(self.primary, identity)
                self.assertEqual(queue.read_text(encoding="utf-8"), contents)



if __name__ == "__main__":
    unittest.main()
