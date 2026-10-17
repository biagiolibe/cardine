"""End-to-end Git evidence for the task-worktree delivery contract."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import json
import os
import re
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import meridian  # noqa: E402
import project_console  # noqa: E402


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
        declaration = self.primary / ".meridian/candidate-validation.json"
        declaration.parent.mkdir()
        declaration.write_text(json.dumps({
            "version": 1, "state": "declared", "outcomes": {
                "REUSE": ["scripts/check_repository.py"], "BOUNDED": ["scripts/check_repository.py"],
                "FULL": ["scripts/check_repository.py", "unittest discover"],
            },
        }), encoding="utf-8")
        self.git("add", ".meridian/candidate-validation.json")
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
    ) -> meridian.IntegrationValidationDecision:
        return meridian.decide_integration_validation(
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
        decision: meridian.IntegrationValidationDecision,
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
        if passed and decision.outcome == meridian.IntegrationValidationOutcome.FULL:
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

        self.assertEqual(decision.outcome, meridian.IntegrationValidationOutcome.REUSE)
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

        self.assertEqual(decision.outcome, meridian.IntegrationValidationOutcome.BOUNDED)
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

        self.assertEqual(decision.outcome, meridian.IntegrationValidationOutcome.FULL)
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
        self.assertEqual(decision.outcome, meridian.IntegrationValidationOutcome.BLOCKED)


class BoundedWorktreeLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.primary = self.root / "project"
        self.primary.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Meridian Test")
        self.git("config", "user.email", "meridian@example.invalid")
        tasks = self.primary / "tasks"
        tasks.mkdir()
        (tasks / "056-lifecycle.md").write_text(
            "# Task 056\n\n> **ID**: `056`\n", encoding="utf-8"
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
        (self.primary / "PROJECT_WORKFLOW.md").write_text(
            "# Workflow\n\nThis file selects `LEAN_DELIVERY` exclusively.\n", encoding="utf-8"
        )
        (self.primary / "README.md").write_text("base\n", encoding="utf-8")
        declaration = self.primary / ".meridian/candidate-validation.json"
        declaration.parent.mkdir()
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

    def retired_budget(self, counters):
        prepared = self.prepare()
        self.git("worktree", "remove", prepared["worktree"])
        self.git("branch", "-d", prepared["branch"])
        state = {"056": {"attempt": 1, "lastStatus": "UNKNOWN"}, "056:1": counters}
        meridian.write_budget_state(self.primary, state)
        return state

    def test_prepare_blocks_inherited_budget_spends(self):
        state = self.retired_budget({"diagnostic": 2, "captures:AC1": 1})
        with self.assertRaisesRegex(meridian.MeridianError, "BLOCKED BUDGET_ATTEMPT_REQUIRES_AUTHORIZATION.*diagnostic.*resume:"):
            self.prepare()
        self.assertEqual(meridian.load_budget_state(self.primary), state)
        self.assertEqual(len(meridian._git_worktrees(self.primary)), 1)

    def test_prepare_retired_without_spends(self):
        self.retired_budget({"diagnostic": 0})
        self.assertTrue(self.prepare()["created"])
        self.assertIn("Attempt 1", meridian.budget_show(self.primary, "056"))

    def test_new_budget_attempt_preserves_history_and_journals_reason(self):
        state = self.retired_budget({"diagnostic": 2, "captures:AC1": 1})
        task = meridian.find_task_file(self.primary, "056")
        original = task.read_bytes()
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/meridian.py"), "worktree", "prepare", "056",
            "--project", str(self.primary), "--worktree-root", str(self.worktree_root),
            "--new-attempt", "--reason", "Developer approved redesign", "--format", "json",
        ], cwd=self.primary, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = meridian.load_budget_state(self.primary)
        self.assertEqual(ledger["056:1"], state["056:1"])
        self.assertEqual(ledger["056:2"], {})
        self.assertEqual(ledger["056"]["attempt"], 2)
        self.assertEqual(task.read_bytes(), original)
        self.assertIn("Attempt 2", meridian.budget_show(self.primary, "056"))
        journal = meridian.canonical_git_common_dir(self.primary) / meridian.JOURNAL_NAME
        event = next(json.loads(line) for line in journal.read_text().splitlines()
                     if json.loads(line)["command"] == "worktree prepare new-attempt")
        self.assertEqual(event["task"], "056")
        self.assertEqual((event["previous_attempt"], event["new_attempt"]), (1, 2))
        self.assertEqual(event["historical_counters"], state["056:1"])
        self.assertEqual(event["reason"], "Developer approved redesign")

    def test_new_budget_attempt_requires_reason_and_retired_worktree(self):
        for reason in (None, "", "   "):
            with self.assertRaisesRegex(meridian.MeridianError, "non-empty --reason"):
                meridian.prepare_task_worktree("056", self.worktree_root, self.primary,
                                               new_attempt=True, reason=reason)
        self.prepare()
        with self.assertRaisesRegex(meridian.MeridianError, "registered task worktree"):
            meridian.prepare_task_worktree("056", self.worktree_root, self.primary,
                                           new_attempt=True, reason="Approved")
        self.assertEqual(meridian.load_budget_state(self.primary), {})

    def prepare(self) -> dict[str, object]:
        return meridian.prepare_task_worktree("056", self.worktree_root, self.primary)

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
    ) -> meridian.IntegrationValidationDecision:
        return meridian.decide_integration_validation(
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
        decision: meridian.IntegrationValidationDecision,
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
        if passed and decision.outcome == meridian.IntegrationValidationOutcome.FULL:
            invoked.append("complete baseline")
        if not passed:
            self.git("merge", "--abort")
        return passed, invoked

    def resume(self) -> dict[str, object]:
        return meridian.prepare_task_worktree("056", self.worktree_root, self.primary, resume=True)

    def stale_base(self) -> tuple[dict[str, object], Path]:
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        (self.primary / "upstream.txt").write_text("main advancement\n", encoding="utf-8")
        self.git("add", "upstream.txt")
        self.git("commit", "-m", "advance main")
        self.git("merge", "main", "--ff-only", cwd=worktree)
        return prepared, worktree

    def test_stale_base_check_and_repair(self) -> None:
        prepared, worktree = self.stale_base()
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        state_path, _, _ = meridian._lifecycle_paths(self.primary, identity)
        evidence_path = state_path.with_suffix(".evidence.json")
        evidence_path.write_text(json.dumps({"validated_base_commit": self.base}), encoding="utf-8")
        evidence_before = evidence_path.read_bytes()
        before = self.snapshot(worktree)
        os.chdir(worktree)
        report, ready = meridian.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertFalse(ready)
        self.assertEqual(report["errors"], ["stale-base-record"])
        self.assertEqual(report["stop_reason"], "STALE_WORKTREE_BASE")
        self.assertEqual(before, self.snapshot(worktree))
        command = [sys.executable, str(ROOT / "scripts/meridian.py"), "worktree", "check",
                   "056", "--project", str(self.primary), "--worktree-root", str(self.worktree_root),
                   "--format", "json"]
        checked = subprocess.run(command, cwd=worktree, text=True, capture_output=True, check=False)
        self.assertEqual(checked.returncode, 2)
        self.assertEqual(checked.stderr.strip(),
                         "BLOCKED STALE_WORKTREE_BASE: worktree check reported: stale-base-record; resume: "
                         + str(report["resume"]))
        self.assertEqual(before, self.snapshot(worktree))
        self.assertEqual(self.resume()["base_commit"], self.base)
        self.assertEqual(before, self.snapshot(worktree))
        with self.assertRaisesRegex(meridian.MeridianError, "BLOCKED STALE_WORKTREE_BASE:"):
            self.prepare()
        closure, _ = meridian.closure_status("056", self.worktree_root, self.primary)
        self.assertEqual(closure["stop_reason"], "STALE_WORKTREE_BASE")
        original = json.loads(state_path.read_text(encoding="utf-8"))
        recovered = meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)
        self.assertTrue(recovered["repaired"])
        self.assertTrue(recovered["evidence_renewal_required"])
        renewed = json.loads(state_path.read_text(encoding="utf-8"))
        head = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.assertEqual(renewed, {**original, "base_commit": head, "task_commit": head})
        self.assertEqual(renewed["started_at"], prepared["started_at"])
        self.assertEqual(evidence_before, evidence_path.read_bytes())
        snapshot = self.snapshot(worktree)
        self.assertFalse(meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)["repaired"])
        command[3] = "repair-base"
        repeated = subprocess.run(command, cwd=worktree, text=True, capture_output=True, check=False)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertFalse(json.loads(repeated.stdout)["repaired"])
        self.assertEqual(snapshot, self.snapshot(worktree))
        self.assertTrue(meridian.inspect_task_worktree("056", self.worktree_root, self.primary)[1])
        # Another main fast-forward after recovery remains provable.
        (self.primary / "second.txt").write_text("second main advancement\n", encoding="utf-8")
        self.git("add", "second.txt")
        self.git("commit", "-m", "advance main again")
        self.git("merge", "main", "--ff-only", cwd=worktree)
        self.assertEqual(meridian.inspect_task_worktree("056", self.worktree_root, self.primary)[0]["stop_reason"],
                         "STALE_WORKTREE_BASE")
        self.assertTrue(meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)["repaired"])

    def test_repaired_base_rejects_old_validation_evidence(self) -> None:
        _, worktree = self.stale_base()
        meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)
        (worktree / "task.txt").write_text("task work\n", encoding="utf-8")
        self.git("add", "task.txt", cwd=worktree)
        self.git("commit", "-m", "task work", cwd=worktree)
        os.chdir(worktree)
        recorded = meridian.record_task_evidence(
            "056", self.worktree_root, validation_commands=["git diff --check"], validation_exit_codes=[0],
            accepted=True, task_dependencies=[], task_behavioral_surfaces=[], main_advanced_dependencies=[],
            main_advanced_behavioral_surfaces=[], full_validation_required=False, supplied_project=self.primary,
        )
        evidence_path = Path(str(recorded["evidence"]))
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["validated_base_commit"] = self.base
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        before = evidence_path.read_bytes()
        os.chdir(self.primary)
        self.assertEqual(meridian.closure_status("056", self.worktree_root, self.primary)[0]["step"], "C5")
        with self.assertRaisesRegex(meridian.MeridianError, "BLOCKED EVIDENCE_MISMATCH:"):
            meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(evidence_path.read_bytes(), before)
        self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())

    def test_base_repair_rejects_unsafe_worktree_facts(self) -> None:
        _, worktree = self.stale_base()
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        state_path, lease, integration = meridian._lifecycle_paths(self.primary, identity)
        original = state_path.read_bytes()
        mutations = [
            (worktree / "dirty.txt", "dirty\n"),
            (lease, '{}'), (integration, '{}'),
        ]
        for path, contents in mutations:
            with self.subTest(path=path.name):
                path.write_text(contents, encoding="utf-8")
                with self.assertRaisesRegex(meridian.MeridianError, "BLOCKED WRONG_WORKTREE:"):
                    meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)
                self.assertEqual(state_path.read_bytes(), original)
                path.unlink()
        for field in ("task_id", "project", "worktree", "branch", "worktree_root", "git_common_dir"):
            with self.subTest(field=field):
                state = json.loads(original)
                state[field] = "unrelated"
                state_path.write_text(json.dumps(state), encoding="utf-8")
                before = state_path.read_bytes()
                with self.assertRaisesRegex(meridian.MeridianError, "BLOCKED WRONG_WORKTREE:"):
                    meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)
                self.assertEqual(state_path.read_bytes(), before)
                state_path.write_bytes(original)
        self.git("switch", "-c", "unrelated", cwd=worktree)
        with self.assertRaisesRegex(meridian.MeridianError, "BLOCKED WRONG_WORKTREE:"):
            meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)

    def test_task_commits_and_normal_main_advancement_are_not_stale(self) -> None:
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        (worktree / "task.txt").write_text("task work\n", encoding="utf-8")
        self.git("add", "task.txt", cwd=worktree)
        self.git("commit", "-m", "task work", cwd=worktree)
        (self.primary / "upstream.txt").write_text("main work\n", encoding="utf-8")
        self.git("add", "upstream.txt")
        self.git("commit", "-m", "main work")
        self.assertTrue(meridian.inspect_task_worktree("056", self.worktree_root, self.primary,
                                                      require_effective_worktree=False)[1])
        with self.assertRaisesRegex(meridian.MeridianError, "unproven-fast-forward"):
            meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)
        # Even after main contains the task commit, ancestry alone cannot prove recovery.
        self.git("merge", "task-056", "--no-edit")
        self.git("merge", "main", "--ff-only", cwd=worktree)
        self.assertTrue(meridian.inspect_task_worktree("056", self.worktree_root, self.primary,
                                                      require_effective_worktree=False)[1])
        with self.assertRaisesRegex(meridian.MeridianError, "unproven-fast-forward"):
            meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)

    def test_base_repair_requires_intact_fast_forward_reflog(self) -> None:
        _, worktree = self.stale_base()
        self.git("reflog", "expire", "--expire=now", "refs/heads/task-056")
        self.assertTrue(meridian.inspect_task_worktree("056", self.worktree_root, self.primary,
                                                      require_effective_worktree=False)[1])
        with self.assertRaisesRegex(meridian.MeridianError, "unproven-fast-forward"):
            meridian.repair_task_worktree_base("056", self.worktree_root, self.primary)

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
        state = next((self.primary / ".git/meridian-worktrees").glob("*.json")).read_text(encoding="utf-8")
        return index.read_bytes(), files, state

    def test_resume_accepts_a_dirty_worktree_and_changes_nothing(self) -> None:
        prepared, worktree = self.dirty_worktree()
        before = self.snapshot(worktree)
        with self.assertRaisesRegex(meridian.MeridianError, "existing task worktree is dirty and was retained"):
            self.prepare()
        resumed = self.resume()
        self.assertEqual(self.snapshot(worktree), before)
        self.assertEqual(
            {key: resumed[key] for key in ("resumed", "dirty", "changed_paths", "untracked_paths", "created")},
            {"resumed": True, "dirty": True, "changed_paths": 1, "untracked_paths": 1, "created": False},
        )
        self.assertEqual(resumed["next_action"], "inspect-dirty")
        self.assertEqual(resumed["started_at"], prepared["started_at"])
        self.assertEqual(resumed["base_commit"], prepared["base_commit"])
        self.assertEqual(resumed["branch"], "task-056")
        self.assertEqual(resumed["worktree"], prepared["worktree"])
        self.assertEqual(resumed["handoff_worktree"], prepared["handoff_worktree"])
        self.assertNotIn("new.txt", json.dumps(resumed))
        os.chdir(worktree)
        report, ready = meridian.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertFalse(ready)
        self.assertEqual(report["errors"], ["dirty-worktree"])

    def test_resume_never_attempts_a_lifecycle_state_write(self) -> None:
        prepared, worktree = self.dirty_worktree()
        state_directory = self.primary / ".git/meridian-worktrees"
        before = sorted(item.name for item in state_directory.iterdir())
        state_path = next(state_directory.glob("*.json"))
        original = state_path.read_bytes()
        with mock.patch.object(meridian, "_write_json_atomic", side_effect=AssertionError("state write")), \
                mock.patch.object(meridian.tempfile, "mkstemp", side_effect=AssertionError("temporary file")):
            resumed = self.resume()
        self.assertEqual(sorted(item.name for item in state_directory.iterdir()), before)
        self.assertEqual(state_path.read_bytes(), original)
        self.assertEqual(
            {key: resumed[key] for key in ("branch", "worktree", "base_commit", "started_at")},
            {key: prepared[key] for key in ("branch", "worktree", "base_commit", "started_at")},
        )
        self.assertNotIn("state", resumed)

    def test_resume_stops_with_a_registered_code_on_mismatched_state(self) -> None:
        self.dirty_worktree()
        state_path = next((self.primary / ".git/meridian-worktrees").glob("*.json"))
        original = state_path.read_text(encoding="utf-8")
        state_path.write_text(original.replace('"branch": "task-056"', '"branch": "other"'), encoding="utf-8")
        with self.assertRaises(meridian.MeridianStop) as raised:
            self.resume()
        self.assertEqual(raised.exception.code, "WRONG_WORKTREE")
        message = str(raised.exception)
        self.assertTrue(message.startswith("BLOCKED WRONG_WORKTREE: "))
        for expected in (str(state_path), "branch task-056", "branch other"):
            self.assertIn(expected, message)
        self.assertEqual(state_path.read_text(encoding="utf-8").count('"other"'), 1)

    def test_resume_with_missing_state_derives_from_git_and_repairs_later(self) -> None:
        prepared, worktree = self.dirty_worktree()
        state_directory = self.primary / ".git/meridian-worktrees"
        next(state_directory.glob("*.json")).unlink()
        with mock.patch.object(meridian, "_write_json_atomic", side_effect=AssertionError("state write")):
            resumed = self.resume()
        self.assertEqual(list(state_directory.glob("*.json")), [])
        self.assertEqual(resumed["base_commit"], prepared["base_commit"])
        self.assertEqual(resumed["base_commit_source"], "derived")
        self.assertEqual(resumed["state"], "missing")
        self.assertNotIn("started_at", resumed)
        self.assertEqual((resumed["resumed"], resumed["dirty"], resumed["branch"]), (True, True, "task-056"))
        self.assertEqual(
            resumed["state_repair"],
            f"meridian worktree prepare 056 --project {self.primary.resolve()} --format json",
        )
        with self.assertRaisesRegex(meridian.MeridianError, "dirty and was retained"):
            self.prepare()
        self.git("checkout", "--", "README.md", cwd=worktree)
        (worktree / "new.txt").unlink()
        repaired = self.prepare()
        self.assertEqual(repaired["base_commit"], prepared["base_commit"])
        self.assertEqual(len(list(state_directory.glob("*.json"))), 1)
        self.assertNotIn("state", self.resume())

    def test_resume_counts_renames_and_clean_worktrees(self) -> None:
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        clean = self.resume()
        self.assertEqual((clean["dirty"], clean["next_action"]), (False, "check"))
        self.git("mv", "README.md", "RENAMED.md", cwd=worktree)
        (worktree / "tasks/QUEUE.md").write_text("changed\n", encoding="utf-8")
        resumed = self.resume()
        self.assertEqual((resumed["changed_paths"], resumed["untracked_paths"]), (2, 0))

    def test_ordinary_prepare_output_has_no_resume_fields(self) -> None:
        self.assertFalse({"resumed", "dirty", "changed_paths"} & set(self.prepare()))
        self.assertFalse({"resumed", "dirty", "changed_paths"} & set(self.prepare()))

    def test_resume_without_a_worktree_creates_nothing(self) -> None:
        with self.assertRaisesRegex(meridian.MeridianError, "nothing to resume"):
            self.resume()
        self.assertEqual(self.git("branch", "--list", "task-056").stdout, "")
        self.assertEqual(list(self.worktree_root.rglob("task-056")), [])
        self.assertFalse((self.primary / ".git/meridian-worktrees").exists())

    def test_resume_keeps_every_other_prepare_block(self) -> None:
        prepared, worktree = self.dirty_worktree()
        state_path = next((self.primary / ".git/meridian-worktrees").glob("*.json"))
        original = state_path.read_text(encoding="utf-8")
        state_path.write_text(original.replace('"branch": "task-056"', '"branch": "other"'), encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, "lifecycle state mismatch"):
            self.resume()
        state_path.write_text(original, encoding="utf-8")
        for name in ("meridian-integration.lock", "meridian-integration.json"):
            with self.subTest(retained=name):
                retained = self.primary / ".git" / name
                retained.write_text(json.dumps({"task_id": "056"}), encoding="utf-8")
                with self.assertRaisesRegex(meridian.MeridianError, "integration lease or staged merge"):
                    self.resume()
                retained.unlink()
        self.git("checkout", "-b", "elsewhere", cwd=worktree)
        with self.assertRaisesRegex(meridian.MeridianError, "canonical worktree mismatch"):
            self.resume()
        self.git("checkout", "task-056", cwd=worktree)
        self.git("commit", "--allow-empty", "-m", "advance", cwd=worktree)
        self.assertTrue(self.resume()["dirty"])
        self.git("worktree", "remove", "--force", str(worktree))
        with self.assertRaisesRegex(meridian.MeridianError, "partial task state"):
            self.resume()
        self.git("branch", "-D", "task-056")
        collision = Path(str(prepared["worktree"]))
        collision.mkdir(parents=True)
        with self.assertRaisesRegex(meridian.MeridianError, "nothing to resume"):
            self.resume()
        with self.assertRaisesRegex(meridian.MeridianError, "worktree path collision"):
            self.prepare()

    def test_console_resume_directive_is_accepted_by_prepare_resume(self) -> None:
        prepared, worktree = self.dirty_worktree()
        task = project_console.Task(
            task_id="056", title="t", status="IN_PROGRESS", phase=(), dependencies=(), path=None,
            objective=(), criteria=(), readiness="IN PROGRESS", lifecycle="in_progress",
            active_writer=True,
        )
        directive = str(task.launch_command)
        match = re.fullmatch(r"Proceed with 056 \(Resume: run (meridian worktree prepare 056 .*)\)", directive)
        self.assertIsNotNone(match, directive)
        arguments = match.group(1).split()[1:]
        self.assertIn("--resume", arguments)
        clean = project_console.Task(**{**task.__dict__, "active_writer": False})
        self.assertEqual(clean.launch_command, "Proceed with 056")
        command = [sys.executable, str(ROOT / "scripts/meridian.py"), *arguments,
                   "--project", str(self.primary), "--worktree-root", str(self.worktree_root)]
        ordinary = [part for part in command if part != "--resume"]
        refused = subprocess.run(ordinary, cwd=self.primary, text=True, capture_output=True, check=False)
        self.assertNotEqual(refused.returncode, 0)
        accepted = subprocess.run(command, cwd=self.primary, text=True, capture_output=True, check=False)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        output = json.loads(accepted.stdout)
        self.assertEqual((output["resumed"], output["dirty"]), (True, True))
        self.assertEqual(output["started_at"], prepared["started_at"])
        self.assertEqual((worktree / "README.md").read_text(encoding="utf-8"), "edited\n")

    def test_prepare_is_idempotent_and_check_rejects_wrong_worker(self) -> None:
        prepared = self.prepare()
        self.assertTrue(prepared["created"])
        repeated = self.prepare()
        self.assertFalse(repeated["created"])
        self.assertEqual(prepared["worktree"], repeated["worktree"])

        wrong, ready = meridian.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertFalse(ready)
        self.assertIn("wrong-worktree", wrong["errors"])

        os.chdir(Path(str(prepared["worktree"])))
        correct, ready = meridian.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertTrue(ready, correct)
        self.assertEqual(correct["branch"], "task-056")
        self.assertTrue(correct["clean"])

    def test_stage_finalize_and_verified_cleanup(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            "### Phase 1 — Closing\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n",
            encoding="utf-8",
        )
        self.git("add", "tasks/QUEUE.md")
        self.git("commit", "-m", "add closing phase")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(
            json.dumps({
                "accepted": True,
                "validation_passed": True,
                "validated_task_commit": task_commit,
                "validated_base_commit": self.base,
                "full_validation_required": False,
                "interaction_assessment_complete": True,
                "task_paths": ["feature.txt"],
                "task_dependencies": [],
                "task_behavioral_surfaces": ["feature behavior"],
                "main_advanced_dependencies": [],
                "main_advanced_behavioral_surfaces": [],
            }),
            encoding="utf-8",
        )
        staged = meridian.stage_task_integration(
            "056", self.worktree_root, evidence_path, self.primary
        )
        self.assertEqual(staged["decision"], "REUSE")
        self.assertFalse(queue.read_text(encoding="utf-8").strip())
        self.assertIn("### Phase 1 — Closing", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"))
        self.assertEqual(
            meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary),
            staged,
        )
        validation_path = self.root / "candidate-validation.json"
        validation_path.write_text(
            json.dumps({
                "candidate_tree": staged["candidate_tree"],
                "passed": True,
                "scope": "bounded",
                "commands": ["git diff --check", "python3 scripts/check_repository.py"],
            }),
            encoding="utf-8",
        )
        finalized = meridian.finalize_task_integration("056", validation_path, self.primary)
        self.assertEqual(finalized["decision"], "REUSE")
        self.assertTrue((self.primary / "feature.txt").is_file())
        cleaned = meridian.cleanup_task_worktree("056", self.worktree_root, self.primary)
        self.assertEqual(cleaned["status"], "cleaned")
        self.assertTrue(task_worktree.is_dir())
        self.assertEqual(list(task_worktree.iterdir()), [])
        self.assertNotIn(str(task_worktree), self.git("worktree", "list", "--porcelain").stdout)
        for hook in ("read-guard", "stop-audit"):
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/meridian.py"), "hook", hook, "--host", "codex"],
                cwd=task_worktree, input=json.dumps({"cwd": str(task_worktree),
                    "tool_name": "Bash", "tool_input": {"command": "cat missing.txt"},
                    "last_assistant_message": "BLOCKED WRONG_WORKTREE"}),
                text=True, capture_output=True,
            )
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(list(task_worktree.iterdir()), [])
        self.assertNotEqual(self.git("show-ref", "--verify", "refs/heads/task-056", check=False).returncode, 0)
        repeated = meridian.cleanup_task_worktree("056", self.worktree_root, self.primary)
        self.assertTrue(repeated["already_cleaned"])

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
                    meridian.missing_candidate_validation_commands(decision, commands), expected
                )

    def test_candidate_validation_declaration_states_and_malformed_input(self) -> None:
        path = self.primary / ".meridian/candidate-validation.json"
        path.write_text(json.dumps({"version": 1, "state": "none"}), encoding="utf-8")
        self.assertEqual(meridian.candidate_validation_declaration(self.primary), ("none", {}))
        path.unlink()
        self.assertEqual(meridian.candidate_validation_declaration(self.primary), ("undeclared", {}))
        path.write_text('{"version": 1, "state": "declared", "outcomes": {}}', encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, "outcomes must declare"):
            meridian.candidate_validation_declaration(self.primary)

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
        with self.assertRaisesRegex(meridian.MeridianError, "UNDECLARED_VALIDATION_COMMANDS"):
            meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        _state, lease_path, integration_path = meridian._lifecycle_paths(self.primary, identity)
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
        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        validation_path = self.root / "candidate-validation.json"
        validation_path.write_text(json.dumps({
            "candidate_tree": staged["candidate_tree"], "passed": True,
            "scope": "bounded", "commands": ["python3 scripts/check_repository.py"],
        }), encoding="utf-8")

        with self.assertRaisesRegex(meridian.MeridianError, r"git diff --check"):
            meridian.finalize_task_integration("056", validation_path, self.primary)
        (self.primary / ".meridian/candidate-validation.json").write_text(
            json.dumps({"version": 1, "state": "none"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(meridian.MeridianError, r"git diff --check"):
            meridian.finalize_task_integration("056", validation_path, self.primary)

        _state, lease_path, integration_path = meridian._lifecycle_paths(
            self.primary, meridian.resolve_task_identity(self.primary, "056", "existing")
        )
        self.assertTrue(lease_path.is_file())
        self.assertTrue(integration_path.is_file())
        self.assertTrue((self.primary / ".git/MERGE_HEAD").is_file())
        meridian.abort_task_integration("056", self.primary)

    def test_evidence_command_records_git_facts_without_running_validation(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        previous = Path.cwd()
        try:
            os.chdir(task_worktree)
            recorded = meridian.record_task_evidence(
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
        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "FULL")
        self.assertEqual(staged["main_advanced_paths"], ["feature.txt"])
        meridian.abort_task_integration("056", self.primary)

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
        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "BOUNDED")
        meridian.abort_task_integration("056", self.primary)

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

        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "BOUNDED")
        self.assertIn("| `[x]` | 056 | Lifecycle |", queue.read_text(encoding="utf-8"))
        self.assertIn("- `[x]` 056 — Lifecycle", plan.read_text(encoding="utf-8"))
        meridian.abort_task_integration("056", self.primary)

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

        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(len(staged["warnings"]), 1)
        self.assertIn("## Phase 2 — Unreadable", staged["warnings"][0])
        report = {item["section"]: item for item in staged["archival"]}
        self.assertFalse(report["## Phase 2 — Unreadable"]["archive"])
        self.assertTrue(report["## Phase 2 — Unreadable"]["reason"])
        self.assertIn(unreadable, queue.read_text(encoding="utf-8"))
        meridian.abort_task_integration("056", self.primary)

    def test_queue_archival_warnings_name_the_unrecognized_section_and_reason(self) -> None:
        issue_example = (
            "## Phase 2 — Wrong level\n\n"
            "| Status | ID | Title | Dependencies | Estimate |\n|---|---|---|---|---|\n"
            "| `[x]` | 090 | Done | — | 1h |\n"
        )
        warnings = meridian._queue_archival_warnings(issue_example)
        self.assertEqual(len(warnings), 1)
        self.assertIn("## Phase 2 — Wrong level", warnings[0])
        self.assertIn("heading level 2", warnings[0])
        column_order = (
            "### Phase 3 — Column order\n\n"
            "| ID | Status | Title |\n|---|---|---|\n| 090 | `[x]` | Done |\n"
        )
        warnings = meridian._queue_archival_warnings(column_order)
        self.assertEqual(len(warnings), 1)
        self.assertIn("### Phase 3 — Column order", warnings[0])
        self.assertIn("expected columns", warnings[0])

    def test_queue_archival_warnings_ignore_recognized_sections_and_tables_without_status(self) -> None:
        contents = (
            "### Phase 1 — Open\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| `[x]` | 056 | Lifecycle |\n\n"
            "#### Nested\n\n| Status | ID |\n|---|---|\n| `[ ]` | 057 |\n"
        )
        self.assertEqual(meridian._queue_archival_warnings(contents), [])
        notes = "## Notes\n\n| Term | Meaning |\n|---|---|\n| a | b |\n"
        self.assertEqual(meridian._queue_archival_warnings(notes), [])

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
        warnings = meridian._queue_archival_warnings(held, "governed-sdd")
        self.assertEqual(len(warnings), 1)
        self.assertIn("INCONCLUSIVE", warnings[0])
        self.assertIn("056", warnings[0])
        self.assertNotIn("057", warnings[0])
        queued = held.replace("ACCEPTED", "QUEUED")
        self.assertEqual(meridian._queue_archival_warnings(queued, "governed-sdd"), [])
        retained, archive = meridian._archive_completed_queue_sections(
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

        meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertIn("- `[x]` 056 — Lifecycle", plan.read_text(encoding="utf-8"))
        self.assertFalse((self.primary / "PROJECT_PLAN.md").exists())
        self.assertIn("docs/PLAN.md", self.git("diff", "--cached", "--name-only").stdout.splitlines())
        meridian.abort_task_integration("056", self.primary)

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

        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "REUSE")
        meridian.abort_task_integration("056", self.primary)

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

        meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        row = [line for line in queue.read_text(encoding="utf-8").splitlines() if "| 056 |" in line][0]
        self.assertEqual(row, "| `[x]` | 056 | Lifecycle | [056](done/056-lifecycle.md) |")
        self.assertTrue((self.primary / "tasks/done/056-lifecycle.md").is_file())
        meridian.abort_task_integration("056", self.primary)

    def test_lifecycle_change_parser_rejects_inexact_task_record_changes(self) -> None:
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
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
                meridian,
                "_run_git",
                side_effect=(
                    subprocess.CompletedProcess([], 0, diff, ""),
                    subprocess.CompletedProcess([], 1, "", ""),
                ),
            ):
                unchanged, offending = meridian._lifecycle_changes_after_validation(
                    self.primary, identity, "validated", "current"
                )
                self.assertFalse(unchanged)
                self.assertTrue(offending)

    def test_completion_rows_reject_unknown_shape_without_editing_queue(self) -> None:
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        queue = self.primary / "tasks/QUEUE.md"
        original_queue = queue.read_text(encoding="utf-8")
        (self.primary / "PROJECT_PLAN.md").write_text("Task 056: TODO\n", encoding="utf-8")

        with self.assertRaisesRegex(meridian.MeridianError, r"unrecognized completion row"):
            meridian._apply_task_completion_rows(self.primary, identity)

        self.assertEqual(queue.read_text(encoding="utf-8"), original_queue)

    def test_completion_rows_archive_a_closing_phase_and_create_the_archive(self) -> None:
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            "### Phase 1 — Closing\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n",
            encoding="utf-8",
        )
        meridian._apply_task_completion_rows(self.primary, identity)
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
                        retained, archive = meridian._archive_completed_queue_sections(
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
                    retained, archive = meridian._archive_completed_queue_sections(
                        contents, self.primary / "QUEUE.md", self.primary / "archive.md", mode
                    )
                    self.assertEqual(retained, contents)
                    self.assertIsNone(archive)
                    warnings = meridian._queue_archival_warnings(contents, mode)
                    self.assertEqual(len(warnings), 1)
                    self.assertIn("### Ambiguous", warnings[0])

    def test_archival_mixed_boundaries_do_not_duplicate_nested_content(self) -> None:
        table = "| Status | ID | Title |\n|---|---|---|\n| `[x]` | A | Done |\n"
        contents = "# Queue\n## Parent\n### One\n" + table + "#### Notes\nText\n### Two\n" + table + "# Later\nKeep me\n"
        retained, archive = meridian._archive_completed_queue_sections(
            contents, self.primary / "QUEUE.md", self.primary / "archive.md"
        )
        self.assertEqual(retained, "# Queue\n## Parent\n# Later\nKeep me\n")
        self.assertEqual((archive or "").count("#### Notes"), 1)
        self.assertEqual((archive or "").count(table), 2)
        self.assertNotIn("Keep me", archive or "")
        self.assertEqual(meridian._queue_archival_warnings(contents), [])

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
        retained, archive = meridian._archive_completed_queue_sections(
            contents, self.primary / "docs/QUEUE.md", self.primary / "archive.md", "governed-sdd"
        )
        self.assertIn("B-SPIKE", retained)
        self.assertNotIn("B-SPIKE", archive or "")
        self.assertIn("A.md", archive or "")
        self.assertNotIn("tasks/QUEUE.md", archive or "")
        warnings = meridian._queue_archival_warnings(contents, "governed-sdd")
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
        archived, archive_contents = meridian._archive_completed_queue_sections(
            contents, queue, self.primary / "tasks/QUEUE_ARCHIVE.md"
        )
        self.assertEqual(archived, contents)
        self.assertIsNone(archive_contents)

    def test_completion_rows_complete_an_in_progress_task(self) -> None:
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        queue = self.primary / "tasks/QUEUE.md"
        plan = self.primary / "PROJECT_PLAN.md"
        queue.write_text(
            queue.read_text(encoding="utf-8").replace("`[ ]`", "`[/]`"), encoding="utf-8"
        )
        plan.write_text("- `[/]` 056 — Lifecycle\n", encoding="utf-8")
        meridian._apply_task_completion_rows(self.primary, identity)
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
        archived, archive_contents = meridian._archive_completed_queue_sections(
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
        archived, archive_contents = meridian._archive_completed_queue_sections(
            contents, queue, self.primary / "tasks/QUEUE_ARCHIVE.md"
        )
        archive = self.primary / "tasks/QUEUE_ARCHIVE.md"
        archive.write_text(archive_contents or "", encoding="utf-8")
        repeated_queue, repeated_archive = meridian._archive_completed_queue_sections(
            archived, queue, archive
        )
        self.assertEqual(repeated_queue, archived)
        self.assertIsNone(repeated_archive)

    def test_completion_rows_retain_ambiguous_archival_section_with_warning(self) -> None:
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        queue = self.primary / "tasks/QUEUE.md"
        contents = (
            "### Phase 1 — Current\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n\n"
            "### Phase 2 — Malformed\n\n"
            "| Status | ID | Title |\n|---|---|---|\n| [x] | 057 | Malformed status |\n"
        )
        queue.write_text(contents, encoding="utf-8")
        result = meridian._apply_task_completion_rows(self.primary, identity)
        retained = queue.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn(contents[contents.index("### Phase 2"):], retained)
        warnings = meridian._queue_archival_warnings(retained)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        state_path, lease_path, integration_path = meridian._lifecycle_paths(self.primary, identity)
        references = self.git("show-ref").stdout
        worktree_state = state_path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(meridian.MeridianError, r"paths changed after validation: .*other.md"):
            meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)
        self.assertEqual(self.git("show-ref").stdout, references)
        self.assertEqual(state_path.read_text(encoding="utf-8"), worktree_state)
        self.assertFalse(lease_path.exists())
        self.assertFalse(integration_path.exists())
        self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())

    def test_abort_requires_owned_state_and_preserves_task(self) -> None:
        prepared = self.prepare()
        task_worktree = Path(str(prepared["worktree"]))
        (task_worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")
        self.git("add", "feature.txt", cwd=task_worktree)
        self.git("commit", "-m", "implement task", cwd=task_worktree)
        task_commit = self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip()
        evidence_path = self.root / "integration-evidence.json"
        evidence_path.write_text(json.dumps({
            "accepted": True,
            "validation_passed": True,
            "validated_task_commit": task_commit,
            "validated_base_commit": self.base,
            "full_validation_required": False,
            "interaction_assessment_complete": True,
            "task_paths": ["feature.txt"],
            "task_dependencies": [],
            "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [],
            "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        aborted = meridian.abort_task_integration("056", self.primary)
        self.assertEqual(aborted["status"], "aborted")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip(), task_commit)

    def test_abort_recovers_an_owned_lease_before_merge_state_exists(self) -> None:
        self.prepare()
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        _task_state, lease_path, integration_path = meridian._lifecycle_paths(self.primary, identity)
        meridian._write_json_atomic(
            lease_path,
            {"version": 1, "task_id": "056", "branch": "task-056", "project": str(self.primary)},
            exclusive=True,
        )
        self.assertFalse(integration_path.exists())
        recovered = meridian.abort_task_integration("056", self.primary)
        self.assertEqual(recovered["status"], "aborted")
        self.assertFalse(lease_path.exists())
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)

    def test_abort_recovers_when_the_queue_link_is_stale(self) -> None:
        self.prepare()
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        _task_state, lease_path, _integration_path = meridian._lifecycle_paths(self.primary, identity)
        meridian._write_json_atomic(
            lease_path,
            {"version": 1, "task_id": "056", "branch": "task-056", "project": str(self.primary)},
            exclusive=True,
        )
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            queue.read_text(encoding="utf-8").replace(
                "| 056 |", "| [056](missing/056-lifecycle.md) |"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(meridian.MeridianError, "queue link for task 056"):
            meridian.resolve_task_identity(self.primary, "056", "existing")
        recovered = meridian.abort_task_integration("056", self.primary)
        self.assertEqual(recovered["status"], "aborted")
        self.assertFalse(lease_path.exists())

    def test_missing_validation_evidence_is_blocked(self) -> None:
        decision = meridian.decide_integration_validation(
            evidence_complete=False,
            validated_task_commit="",
            current_task_commit="task",
            validated_base_commit=self.base,
            current_main_commit=self.base,
            validated_base_is_task_ancestor=True,
            full_validation_required=False,
        )
        self.assertEqual(decision.outcome, meridian.IntegrationValidationOutcome.BLOCKED)

    def test_governance_only_commit_after_validation_keeps_evidence_current(self) -> None:
        decision = meridian.decide_integration_validation(
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
        self.assertEqual(decision.outcome, meridian.IntegrationValidationOutcome.REUSE)

    def test_missing_smoke_configuration_does_not_expand_gate(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        decision = self.validation_decision(task_commit)

        passed, invoked = self.run_candidate_gate("task-055", decision, smoke_command=None)
        self.assertTrue(passed)
        self.assertEqual(invoked, ["git diff --check"])

    def test_smoke_failure_aborts_clean_merge_and_retains_task(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        decision = self.validation_decision(task_commit)

        passed, invoked = self.run_candidate_gate("task-055", decision, smoke_command=("false",))
        self.assertFalse(passed)
        self.assertEqual(invoked, ["git diff --check", "smoke"])
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        self.assertEqual(self.git("rev-parse", "task-055").stdout.strip(), task_commit)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=task).stdout.strip(), task_commit)

    def test_task_can_require_full_combined_tree_validation(self) -> None:
        task = self.create_task("task-055")
        task_commit = self.commit_task(task, "task-055", ("Task 051: TODO", "Task 051: DONE"))
        decision = self.validation_decision(task_commit, full_required=True)

        self.assertEqual(decision.outcome, meridian.IntegrationValidationOutcome.FULL)
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
        self.assertEqual(decision.outcome, meridian.IntegrationValidationOutcome.BLOCKED)

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
                            identity = meridian.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
                            if archived_record:
                                active.rename(done)
                            if not plan_present:
                                with self.assertRaisesRegex(meridian.MeridianError, "unrecognized completion row"):
                                    meridian._apply_task_completion_rows(self.primary, identity)
                                continue
                            meridian._apply_task_completion_rows(self.primary, identity)
                            row = next(line for line in queue.read_text(encoding="utf-8").splitlines() if "| 056 |" in line)
                            self.assertIn("| `[x]` | 056 |", row)
                            if link_name != "absent":
                                expected = "done/056-lifecycle.md" if archived_record else "056-lifecycle.md"
                                self.assertIn(f"[056]({expected})", row)
                            self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())


class GovernedCompletionRowsTest(unittest.TestCase):
    """Completion rows use the shipped Governed template's table shape."""

    def setUp(self) -> None:
        BoundedWorktreeLifecycleTest.setUp(self)
        template = ROOT / "templates/workflows/governed-sdd"
        (self.primary / "PROJECT_WORKFLOW.md").write_text(
            (template / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (self.primary / "tasks/QUEUE.md").write_text(
            "### Phase 1 — Governed\n\n"
            "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n"
            "|---:|---|---|---|---|---|---|\n"
            "| 1 | 056 | P0 | QUEUED | NOT_REQUIRED | — | [056](056-lifecycle.md) |\n",
            encoding="utf-8",
        )
        (self.primary / "PROJECT_PLAN.md").unlink()
        self.git("add", "-A")
        self.git("commit", "-m", "configure governed fixture")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self) -> None:
        BoundedWorktreeLifecycleTest.tearDown(self)

    def git(self, *arguments: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments], cwd=cwd or self.primary, text=True,
            capture_output=True, check=check,
        )

    def prepare(self) -> dict[str, object]:
        return meridian.prepare_task_worktree("056", self.worktree_root, self.primary)

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
        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "REUSE")
        self.assertIn(
            "| ACCEPTED | NOT_REQUIRED |",
            (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"),
        )
        meridian.abort_task_integration("056", self.primary)

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
        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["completion"]["status"], "COMPLETED")
        self.assertEqual(staged["completion"]["reason"], "latest review verdict is APPROVE")
        self.assertIn(
            "| ACCEPTED | REQUIRED |",
            (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"),
        )
        meridian.abort_task_integration("056", self.primary)

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
        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["completion"]["status"], "COMPLETED")
        self.assertIn("ANSWERED | SPIKE", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"))
        meridian.abort_task_integration("056", self.primary)

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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        result = meridian._apply_task_completion_rows(self.primary, identity)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn("ANSWERED | SPIKE", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"))
        inconclusive = contents.replace("QUEUED", "INCONCLUSIVE")
        retained, archive = meridian._archive_completed_queue_sections(
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
            "Question: Does the declared probe pass?\nBudget: 1 iteration\n"
            "Deliverable: `docs/answer.md#result`\n\n## Authority\n\n"
            "## Validation\n\n- `probe`: `test -f docs/answer.md`\n",
            encoding="utf-8",
        )
        task.write_text(task.read_text(encoding="utf-8") + "\n" +
                        meridian.execution_contract(self.primary, "056") + "\n", encoding="utf-8")
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
        ledger = worktree / meridian.EXECUTION_EVIDENCE_PATH
        evidence_bytes = ledger.read_bytes()
        entry = json.loads(evidence_bytes)["056"][0]
        self.assertEqual({key: entry[key] for key in ("id", "command", "exitStatus")},
                         {"id": "probe", "command": "test -f docs/answer.md", "exitStatus": 0})
        self.assertEqual(entry["commit"], self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip())
        self.assertEqual(entry["sourceDigest"], meridian.execution_source_digest(worktree, "056"))
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
            "task_paths": [str(meridian.EXECUTION_EVIDENCE_PATH), "docs/answer.md", "tasks/056-lifecycle.md"],
            "task_dependencies": [], "task_behavioral_surfaces": [],
            "main_advanced_dependencies": [], "main_advanced_behavioral_surfaces": [],
        }), encoding="utf-8")
        staged = meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(staged["decision"], "REUSE")
        self.assertEqual((self.primary / meridian.EXECUTION_EVIDENCE_PATH).read_bytes(), evidence_bytes)
        self.assertEqual(self.git("show", f":{meridian.EXECUTION_EVIDENCE_PATH}").stdout.encode(), evidence_bytes)
        candidate = self.root / "candidate-validation.json"
        candidate.write_text(json.dumps({
            "candidate_tree": staged["candidate_tree"], "passed": True, "scope": "bounded",
            "commands": ["git diff --check", "python3 scripts/check_repository.py"],
        }), encoding="utf-8")
        meridian.finalize_task_integration("056", candidate, self.primary)
        self.assertEqual((self.primary / meridian.EXECUTION_EVIDENCE_PATH).read_bytes(), evidence_bytes)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        commit = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.assertEqual(set(meridian._spike_disallowed_paths(self.primary.resolve(), identity, self.base, commit)), {
            ".meridian/execution-evidence-extra.json", ".meridian/other.json", "docs/undeclared.md", "source.py",
        })
        task.write_text(task.read_text(encoding="utf-8").replace("Class: SPIKE", "Class: NORMAL"), encoding="utf-8")
        self.git("add", "tasks/056-lifecycle.md", cwd=worktree)
        self.git("commit", "-m", "exercise normal task path behavior", cwd=worktree)
        commit = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.assertEqual(meridian._spike_disallowed_paths(self.primary.resolve(), identity, self.base, commit), ())

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
        with self.assertRaisesRegex(meridian.MeridianError, r"source.py"):
            meridian.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        _state, lease, staged = meridian._lifecycle_paths(self.primary, identity)
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
                            identity = meridian.resolve_task_identity(
                                self.primary, "056", "existing", check_queue_links=False
                            )
                            if archived_record:
                                active.rename(done)
                            meridian._apply_task_completion_rows(self.primary, identity)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        with self.assertRaisesRegex(meridian.MeridianStop, "BLOCKED REVIEW_NOT_APPROVED:"):
            meridian._apply_task_completion_rows(self.primary, identity)
        self.assertEqual(queue.read_text(encoding="utf-8"), original)

    def test_governed_required_review_uses_the_latest_attempt(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        queue.write_text(
            queue.read_text(encoding="utf-8").replace("NOT_REQUIRED", "REQUIRED")
            + "| 2 | 057 | P1 | QUEUED | NOT_REQUIRED | — | [057](057.md) |\n",
            encoding="utf-8",
        )
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
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
                    result = meridian._apply_task_completion_rows(self.primary, identity)
                else:
                    with self.assertRaisesRegex(meridian.MeridianStop, "BLOCKED REVIEW_NOT_APPROVED:"):
                        meridian._apply_task_completion_rows(self.primary, identity)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        identity.review_path.parent.mkdir(exist_ok=True)
        identity.review_path.write_text(
            "# Review Record — 056\n\n## Attempt 1 — CHANGES_REQUESTED\n\n- [x] P1 — fixed\n\n"
            "## Attempt 2 — APPROVE\n\n- Approved by: owner\n- Reviewed commit: `abc`\n- Base `main` commit: `def`\n",
            encoding="utf-8",
        )
        result = meridian._apply_task_completion_rows(self.primary, identity)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
        archived = self.primary / "tasks/done/056-lifecycle.md"
        archived.parent.mkdir(exist_ok=True)
        identity.task_path.rename(archived)
        with self.assertRaisesRegex(meridian.MeridianStop, "BLOCKED REVIEW_NOT_APPROVED:"):
            meridian._apply_task_completion_rows(self.primary, identity)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        meridian._apply_task_completion_rows(self.primary, identity)
        self.assertIn("| ACCEPTED |", queue.read_text(encoding="utf-8"))
        self.assertFalse((self.primary / "tasks/QUEUE_ARCHIVE.md").exists())

    def test_governed_unrecognized_row_blocks_without_queue_edit(self) -> None:
        queue = self.primary / "tasks/QUEUE.md"
        original = queue.read_text(encoding="utf-8").replace("| 1 | 056 | P0 | QUEUED |", "| 1 | 056 | P0 | UNKNOWN |")
        queue.write_text(original, encoding="utf-8")
        identity = meridian.resolve_task_identity(self.primary, "056", "existing")
        with self.assertRaisesRegex(meridian.MeridianError, "unrecognized completion row"):
            meridian._apply_task_completion_rows(self.primary, identity)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
        task = identity.task_path
        task.write_text("# Task 056\n\nReview: NOT REQUIRED\n", encoding="utf-8")
        result = meridian._apply_task_completion_rows(self.primary, identity)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
        with self.assertRaisesRegex(meridian.MeridianStop, "BLOCKED REVIEW_NOT_APPROVED:"):
            meridian._apply_task_completion_rows(self.primary, identity)
        self.assertEqual(queue.read_text(encoding="utf-8"), original)
        identity.review_path.parent.mkdir(exist_ok=True)
        identity.review_path.write_text("## Attempt 1 — APPROVE\n", encoding="utf-8")
        result = meridian._apply_task_completion_rows(self.primary, identity)
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
        identity = meridian.resolve_task_identity(self.primary, "056", "existing", check_queue_links=False)
        queue = self.primary / "tasks/QUEUE.md"
        for label, (contents, message) in cases.items():
            with self.subTest(label=label):
                queue.write_text(contents, encoding="utf-8")
                with self.assertRaisesRegex(meridian.MeridianError, message):
                    meridian._apply_task_completion_rows(self.primary, identity)
                self.assertEqual(queue.read_text(encoding="utf-8"), contents)


if __name__ == "__main__":
    unittest.main()
