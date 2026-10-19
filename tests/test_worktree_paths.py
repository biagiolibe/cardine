"""Task-worktree paths tests."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import cardine.integration.decision as integration_decision


class TaskWorktreeIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.primary = self.root / "project"
        self.primary.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Meridian Test")
        self.git("config", "user.email", "meridian@example.invalid")
        (self.primary / "QUEUE.md").write_text(
            "Task 051: TODO\n"
            + "\n".join(f"shared context {index}" for index in range(10))
            + "\nTask 052: TODO\n",
            encoding="utf-8",
        )
        self.git("add", "QUEUE.md")
        self.git("commit", "-m", "initial")
        self.base = self.git("rev-parse", "main").stdout.strip()
        declaration = self.primary / ".cardine/candidate-validation.json"
        declaration.parent.mkdir()
        declaration.write_text(json.dumps({
            "version": 1, "state": "declared", "outcomes": {
                "REUSE": ["scripts/check_repository.py"], "BOUNDED": ["scripts/check_repository.py"],
                "FULL": ["scripts/check_repository.py", "unittest discover"],
            },
        }), encoding="utf-8")
        self.git("add", ".cardine/candidate-validation.json")
        self.git("commit", "-m", "declare candidate validation")
        self.base = self.git("rev-parse", "main").stdout.strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(
        self, *arguments: str, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd or self.primary,
            text=True,
            capture_output=True,
            check=check,
        )

    def create_task(self, task_id: str) -> Path:
        worktree = self.root / f"project-{task_id}"
        self.git("worktree", "add", "-b", task_id, str(worktree), "main")
        return worktree

    def commit_task(self, worktree: Path, task_id: str, queue_change: tuple[str, str]) -> str:
        queue = worktree / "QUEUE.md"
        queue.write_text(
            queue.read_text(encoding="utf-8").replace(*queue_change), encoding="utf-8"
        )
        (worktree / f"{task_id}.txt").write_text(f"isolated {task_id}\n", encoding="utf-8")
        self.git("add", "QUEUE.md", f"{task_id}.txt", cwd=worktree)
        self.git("commit", "-m", f"complete {task_id}", cwd=worktree)
        return self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()

    def integrate(self, branch: str) -> str:
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        merged = self.git("merge", "--no-ff", "--no-commit", branch, check=False)
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
        self.git("commit", "-m", f"integrate {branch}")
        return self.git("rev-parse", "HEAD").stdout.strip()

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
        diff_check = self.git("diff", "--check", check=False)
        invoked.append("git diff --check")
        passed = diff_check.returncode == 0
        if passed and smoke_command is not None:
            invoked.append("smoke")
            passed = subprocess.run(smoke_command, cwd=self.primary, check=False).returncode == 0
        if passed and decision.outcome == integration_decision.IntegrationValidationOutcome.FULL:
            invoked.append("complete baseline")
        if not passed:
            self.git("merge", "--abort")
        return passed, invoked

    def test_two_tasks_remain_isolated_and_integrate_serially(self) -> None:
        first = self.create_task("task-051")
        second = self.create_task("task-052")
        first_commit = self.commit_task(first, "task-051", ("Task 051: TODO", "Task 051: DONE"))
        second_commit = self.commit_task(second, "task-052", ("Task 052: TODO", "Task 052: DONE"))

        first_before = (first / "QUEUE.md").read_text(encoding="utf-8")
        second_before = (second / "QUEUE.md").read_text(encoding="utf-8")
        self.git("switch", "-c", "coordination")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=first).stdout.strip(), first_commit)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=second).stdout.strip(), second_commit)
        self.assertEqual((first / "QUEUE.md").read_text(encoding="utf-8"), first_before)
        self.assertEqual((second / "QUEUE.md").read_text(encoding="utf-8"), second_before)
        self.git("switch", "main")

        first_merge = self.integrate("task-051")
        self.assertNotEqual(
            self.git("merge-base", "--is-ancestor", first_merge, "task-052", check=False).returncode,
            0,
            "the second task deliberately starts from the old main",
        )
        second_merge = self.integrate("task-052")

        queue = (self.primary / "QUEUE.md").read_text(encoding="utf-8")
        self.assertIn("Task 051: DONE", queue)
        self.assertIn("Task 052: DONE", queue)
        self.assertTrue((self.primary / "task-051.txt").is_file())
        self.assertTrue((self.primary / "task-052.txt").is_file())
        for task_commit in (first_commit, second_commit):
            self.assertEqual(
                self.git("merge-base", "--is-ancestor", task_commit, second_merge).returncode,
                0,
            )
        self.assertEqual(len(self.git("rev-list", "--parents", "-n", "1", second_merge).stdout.split()), 3)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=first).stdout.strip(), first_commit)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=second).stdout.strip(), second_commit)

    def test_conflicting_integration_aborts_and_preserves_task_state(self) -> None:
        first = self.create_task("task-051")
        second = self.create_task("task-052")
        first_commit = self.commit_task(first, "task-051", ("shared context 5", "first task value"))
        second_commit = self.commit_task(second, "task-052", ("shared context 5", "second task value"))
        self.integrate("task-051")

        conflicted = self.git("merge", "--no-ff", "--no-commit", "task-052", check=False)
        self.assertNotEqual(conflicted.returncode, 0)
        self.git("merge", "--abort")
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(self.git("rev-parse", "task-051").stdout.strip(), first_commit)
        self.assertEqual(self.git("rev-parse", "task-052").stdout.strip(), second_commit)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=second).stdout.strip(), second_commit)
        self.assertIn("second task value", (second / "QUEUE.md").read_text(encoding="utf-8"))

    def test_unchanged_base_reuses_evidence_without_complete_baseline(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        decision = self.validation_decision(task_commit)

        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.REUSE)
        passed, invoked = self.run_candidate_gate("task-055", decision)
        self.assertTrue(passed)
        self.assertEqual(invoked, ["git diff --check"])

    def test_advanced_main_independent_change_uses_bounded_gate(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        (self.primary / "independent.txt").write_text("main change\n", encoding="utf-8")
        self.git("add", "independent.txt")
        self.git("commit", "-m", "advance main independently")
        decision = self.validation_decision(task_commit, main_paths=("independent.txt",))

        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.BOUNDED)
        passed, invoked = self.run_candidate_gate("task-055", decision)
        self.assertTrue(passed)
        self.assertNotIn("complete baseline", invoked)

    def test_advanced_main_interacting_surface_requires_full_validation(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        (self.primary / "dependency.lock").write_text("main dependency\n", encoding="utf-8")
        self.git("add", "dependency.lock")
        self.git("commit", "-m", "advance shared dependency")
        decision = self.validation_decision(
            task_commit,
            main_paths=("dependency.lock",),
            task_dependencies=("runtime",),
            main_dependencies=("runtime",),
        )

        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.FULL)
        passed, invoked = self.run_candidate_gate("task-055", decision)
        self.assertTrue(passed)
        self.assertIn("complete baseline", invoked)

    def test_stale_task_commit_is_blocked_before_merge(self) -> None:
        task = self.create_task("task-055")
        validated_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        (task / "later.txt").write_text("changed after validation\n", encoding="utf-8")
        self.git("add", "later.txt", cwd=task)
        self.git("commit", "-m", "change after validation", cwd=task)
        current_commit = self.git("rev-parse", "HEAD", cwd=task).stdout.strip()

        decision = self.validation_decision(
            current_commit, validated_task_commit=validated_commit
        )
        self.assertEqual(decision.outcome, integration_decision.IntegrationValidationOutcome.BLOCKED)



if __name__ == "__main__":
    unittest.main()
