"""Non-discovered task-worktree repository fixtures."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cardine.integration import merge as owner_integration_merge
from cardine.worktree import checkout as owner_worktree_checkout
import cardine.integration.decision as integration_decision
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage


from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION, write_state, freeze_record


class BoundedWorktreeLifecycleFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.primary = self.root / "project"
        self.primary.mkdir()
        from unittest.mock import patch
        self.worktree_root = self.root / "worktrees"
        self.environment = patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.worktree_root)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Cardine Test")
        self.git("config", "user.email", "cardine@example.invalid")
        tasks = self.primary / "tasks"
        tasks.mkdir()
        (tasks / "056-lifecycle.md").write_text(
            contract_record("056"), encoding="utf-8"
        )
        (tasks / "QUEUE.md").write_text(
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n",
            encoding="utf-8",
        )
        (self.primary / "QUEUE.md").write_text(
            "Task 051: TODO\nshared context\nTask 052: TODO\n", encoding="utf-8"
        )
        (self.primary / "PROJECT_PLAN.md").write_text(
            "- `[ ]` 056 — Lifecycle\n", encoding="utf-8"
        )
        write_project_config(self.primary, validation=VALIDATION)
        write_state(self.primary, "056", "in_progress", review_required=False)
        freeze_record(self.primary, "056", tasks / "056-lifecycle.md")
        (self.primary / "README.md").write_text("base\n", encoding="utf-8")
        declaration = self.primary / ".cardine/candidate-validation.json"
        declaration.parent.mkdir(exist_ok=True)
        declaration.write_text(json.dumps({
            "version": 1, "state": "declared", "outcomes": {
                "REUSE": ["scripts/check_repository.py"],
                "BOUNDED": ["scripts/check_repository.py"],
                "FULL": ["scripts/check_repository.py", "unittest discover"],
            },
        }), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "initial")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.worktree_root = self.root / "worktrees"
        self.worktree_root.mkdir()
        self.previous_cwd = Path.cwd()
        os.chdir(self.primary)


    def tearDown(self) -> None:
        os.chdir(self.previous_cwd)
        self.temporary.cleanup()


    def git(self, *arguments: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd or self.primary,
            text=True,
            capture_output=True,
            check=check,
        )


    def prepare(self) -> dict[str, object]:
        return owner_worktree_checkout.prepare_task_worktree("056", self.worktree_root, self.primary)


    def create_task(self, task_id: str) -> Path:
        worktree = self.root / f"project-{task_id}"
        self.git("worktree", "add", "-b", task_id, str(worktree), "main")
        return worktree


    def commit_task(self, worktree: Path, task_id: str, queue_change: tuple[str, str]) -> str:
        queue = worktree / "QUEUE.md"
        queue.write_text(queue.read_text(encoding="utf-8").replace(*queue_change), encoding="utf-8")
        (worktree / f"{task_id}.txt").write_text(f"isolated {task_id}\n", encoding="utf-8")
        self.git("add", "QUEUE.md", f"{task_id}.txt", cwd=worktree)
        self.git("commit", "-m", f"complete {task_id}", cwd=worktree)
        return self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()


    def validation_decision(
        self,
        task_commit: str,
        *,
        validated_task_commit: str | None = None,
        current_main: str | None = None,
        full_required: bool = False,
        assessment_complete: bool = True,
        task_paths: tuple[str, ...] = ("feature.txt",),
        main_paths: tuple[str, ...] = (),
        task_dependencies: tuple[str, ...] = (),
        main_dependencies: tuple[str, ...] = (),
        task_surfaces: tuple[str, ...] = (),
        main_surfaces: tuple[str, ...] = (),
    ) -> integration_decision.IntegrationValidationDecision:
        return integration_decision.decide_integration_validation(
            evidence_complete=True,
            validated_task_commit=validated_task_commit or task_commit,
            current_task_commit=task_commit,
            validated_base_commit=self.base,
            current_main_commit=current_main or self.git("rev-parse", "main").stdout.strip(),
            validated_base_is_task_ancestor=True,
            full_validation_required=full_required,
            interaction_assessment_complete=assessment_complete,
            task_paths=task_paths,
            main_advanced_paths=main_paths,
            task_dependencies=task_dependencies,
            main_advanced_dependencies=main_dependencies,
            task_behavioral_surfaces=task_surfaces,
            main_advanced_behavioral_surfaces=main_surfaces,
        )


    def run_candidate_gate(
        self,
        branch: str,
        decision: integration_decision.IntegrationValidationDecision,
        *,
        smoke_command: tuple[str, ...] | None = None,
    ) -> tuple[bool, list[str]]:
        invoked: list[str] = []
        merged = self.git("merge", "--no-ff", "--no-commit", branch, check=False)
        if merged.returncode != 0:
            self.git("merge", "--abort")
            return False, invoked
        invoked.append("git diff --check")
        passed = self.git("diff", "--check", check=False).returncode == 0
        if passed and smoke_command is not None:
            invoked.append("smoke")
            passed = subprocess.run(smoke_command, cwd=self.primary, check=False).returncode == 0
        if passed and decision.outcome == integration_decision.IntegrationValidationOutcome.FULL:
            invoked.append("complete baseline")
        if not passed:
            self.git("merge", "--abort")
        return passed, invoked


    def resume(self) -> dict[str, object]:
        return owner_worktree_checkout.prepare_task_worktree("056", self.worktree_root, self.primary, resume=True)


    def stale_base(self) -> tuple[dict[str, object], Path]:
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        (self.primary / "upstream.txt").write_text("main advancement\n", encoding="utf-8")
        self.git("add", "upstream.txt")
        self.git("commit", "-m", "advance main")
        self.git("merge", "main", "--ff-only", cwd=worktree)
        return prepared, worktree


    def dirty_worktree(self) -> tuple[dict[str, object], Path]:
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        (worktree / "README.md").write_text("edited\n", encoding="utf-8")
        (worktree / "new.txt").write_text("new\n", encoding="utf-8")
        return prepared, worktree


    def snapshot(self, worktree: Path) -> tuple[bytes, dict[str, bytes], str]:
        index = Path(self.git("rev-parse", "--git-path", "index", cwd=worktree).stdout.strip())
        index = index if index.is_absolute() else worktree / index
        files = {
            str(item.relative_to(worktree)): item.read_bytes()
            for item in sorted(worktree.iterdir()) if item.is_file()
        }
        state = {item.name: item.read_bytes()
                 for item in sorted((self.primary / ".git/cardine-worktrees").glob("*"))}
        return index.read_bytes(), files, state


    def assert_cleanup_finished(self, prepared, recovered_from):
        result = owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
        self.assertEqual(result["status"], "cleaned")
        self.assertEqual(result["recovered_from"], recovered_from)
        worktree = Path(prepared["worktree"])
        self.assertTrue(worktree.is_dir())
        self.assertEqual(list(worktree.iterdir()), [])
        self.assertNotIn(str(worktree), self.git("worktree", "list", "--porcelain").stdout)
        self.assertNotEqual(self.git("rev-parse", "--verify", "task-056", check=False).returncode, 0)
        state, _, _ = owner_worktree_storage._lifecycle_paths(
            self.primary, owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing"))
        self.assertFalse(state.exists())
        self.assertTrue(owner_integration_merge.cleanup_task_worktree(
            "056", self.worktree_root, self.primary)["already_cleaned"])


class GovernedCompletionRowsFixture(unittest.TestCase):
    def setUp(self) -> None:
        BoundedWorktreeLifecycleFixture.setUp(self)
        write_project_config(self.primary, "governed", validation=VALIDATION)
        (self.primary / "tasks/QUEUE.md").write_text(
            "### Phase 1 — Governed\n\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---:|---|---|---|---|---|---|\n"
            "| 1 | 056 | P0 | queued | NOT_REQUIRED | — | [056](056-lifecycle.md) |\n",
            encoding="utf-8",
        )
        (self.primary / "PROJECT_PLAN.md").unlink()
        freeze_record(self.primary, "056", self.primary / "tasks/056-lifecycle.md")
        self.git("add", "-A")
        self.git("commit", "-m", "configure governed fixture")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()


    def tearDown(self) -> None:
        BoundedWorktreeLifecycleFixture.tearDown(self)


    def git(self, *arguments: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments], cwd=cwd or self.primary, text=True,
            capture_output=True, check=check,
        )


    def prepare(self) -> dict[str, object]:
        return owner_worktree_checkout.prepare_task_worktree("056", self.worktree_root, self.primary)
