"""Task-worktree cleanup tests."""

from __future__ import annotations

import subprocess
import shutil
import sys
import unittest
import json
import os
import shlex
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import meridian
from cardine.integration import merge as owner_integration_merge
from cardine.worktree import checkout as owner_worktree_checkout
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage

import worktree_support as support


class WorktreeCleanupTest(support.BoundedWorktreeLifecycleFixture):
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
        staged = owner_integration_merge.stage_task_integration(
            "056", self.worktree_root, evidence_path, self.primary
        )
        self.assertEqual(staged["decision"], "REUSE")
        self.assertFalse(queue.read_text(encoding="utf-8").strip())
        self.assertIn("### Phase 1 — Closing", (self.primary / "tasks/QUEUE_ARCHIVE.md").read_text(encoding="utf-8"))
        self.assertEqual(
            owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary),
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
        finalized = owner_integration_merge.finalize_task_integration("056", validation_path, self.primary)
        self.assertEqual(finalized["decision"], "REUSE")
        self.assertTrue((self.primary / "feature.txt").is_file())
        cleaned = owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
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
        repeated = owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
        self.assertTrue(repeated["already_cleaned"])


    def test_cleanup_recovers_prunable_entry_without_pruning_other_worktrees(self):
        prepared = self.prepare()
        worktree = Path(prepared["worktree"])
        other = self.create_task("other")
        shutil.rmtree(other)
        shutil.rmtree(worktree)
        inspection, ready = owner_worktree_checkout.inspect_task_worktree(
            "056", self.worktree_root, self.primary, require_effective_worktree=False)
        self.assertFalse(ready)
        self.assertEqual(inspection["errors"], ["missing-worktree"])
        self.assertIn("prunable", self.git("worktree", "list", "--porcelain").stdout)
        self.assert_cleanup_finished(prepared, "registered-directory-missing")
        self.assertIn(str(other), self.git("worktree", "list", "--porcelain").stdout)


    def test_cleanup_recovers_unregistered_worktree(self):
        prepared = self.prepare()
        self.git("worktree", "remove", prepared["worktree"])
        self.assert_cleanup_finished(prepared, "unregistered-worktree")


    def test_cleanup_missing_branch_requires_tracked_terminal_state(self):
        prepared = self.prepare()
        self.git("worktree", "remove", prepared["worktree"])
        self.git("branch", "-d", prepared["branch"])
        with self.assertRaisesRegex(shared_errors.MeridianError, "tracked task state on main must be done"):
            owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
        state = {"version": 1, "task_id": "056", "workflow": "lean-delivery",
                 "status": "QUEUED", "transitions": []}
        path = self.primary / ".meridian/tasks/056.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        self.git("add", ".meridian/tasks/056.json")
        self.git("commit", "-m", "track queued state")
        with self.assertRaisesRegex(shared_errors.MeridianError, "nonterminal tracked task state"):
            owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
        state.update(status="DONE", transitions=[{"from": "QUEUED", "to": "DONE",
                     "at": "2026-10-17T00:00:00Z", "commit": self.base}])
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.MeridianError, "primary checkout must be clean"):
            owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
        self.git("add", ".meridian/tasks/056.json")
        self.git("commit", "-m", "track terminal state")
        self.assert_cleanup_finished(prepared, "branch-already-deleted")


    def test_cleanup_retains_dirty_and_unmerged_worktrees(self):
        prepared = self.prepare()
        worktree = Path(prepared["worktree"])
        (worktree / "README.md").write_text("changed", encoding="utf-8")
        inspection, ready = owner_worktree_checkout.inspect_task_worktree(
            "056", self.worktree_root, self.primary, require_effective_worktree=False)
        self.assertFalse(ready)
        self.assertEqual(inspection["errors"], ["dirty-worktree"])
        with self.assertRaisesRegex(shared_errors.MeridianError, "dirty-worktree"):
            owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
        self.assertEqual((worktree / "README.md").read_text(), "changed")
        self.git("add", "README.md", cwd=worktree)
        self.git("commit", "-m", "unmerged task", cwd=worktree)
        for partial in ("registered", "missing", "unregistered"):
            with self.subTest(partial=partial):
                if partial == "missing":
                    shutil.rmtree(worktree)
                elif partial == "unregistered":
                    self.git("worktree", "remove", str(worktree))
                with self.assertRaisesRegex(shared_errors.MeridianError, "not integrated into main"):
                    owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
                self.assertEqual(self.git("rev-parse", "--verify", "task-056").returncode, 0)


    def test_cleanup_recovery_preserves_all_other_gates(self):
        prepared = self.prepare()
        shutil.rmtree(prepared["worktree"])
        _, lease, integration = owner_worktree_storage._lifecycle_paths(
            self.primary, owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing"))
        for gate in (lease, integration, self.primary / ".git/MERGE_HEAD"):
            with self.subTest(gate=gate):
                gate.write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(shared_errors.MeridianError, "integration lease or staged merge"):
                    owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
                gate.unlink()
        self.git("remote", "add", "origin", str(self.root / "remote.git"))
        with self.assertRaisesRegex(shared_errors.MeridianError, "not proven pushed"):
            owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.assert_cleanup_finished(prepared, "registered-directory-missing")


    def test_cleanup_resume_after_directory_removed_but_git_write_denied(self):
        prepared = self.prepare()
        worktree = Path(prepared["worktree"])
        run_git = owner_integration_merge._run_git

        def deny_removal(project, *arguments):
            if arguments[:2] == ("worktree", "remove"):
                shutil.rmtree(worktree)
                return subprocess.CompletedProcess(arguments, 128, "", "Permission denied")
            return run_git(project, *arguments)

        with mock.patch.object(owner_integration_merge, "_run_git", side_effect=deny_removal):
            with self.assertRaisesRegex(shared_errors.MeridianError,
                    r"CLEANUP_BLOCKED.*registered-directory-missing.*write access.*primary checkout's .git") as caught:
                owner_integration_merge.cleanup_task_worktree("056", self.worktree_root, self.primary)
        resume = str(caught.exception).split("resume: ", 1)[1].strip()
        # Run the emitted arguments using the repository CLI entry point.
        import shlex
        result = subprocess.run([sys.executable, str(ROOT / "scripts/meridian.py"),
                                 *shlex.split(resume)[1:]], cwd=self.primary, text=True, capture_output=True,
                                env={**os.environ, "MERIDIAN_WORKTREE_ROOT": str(self.worktree_root)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["recovered_from"], "registered-directory-missing")
        self.assertTrue(worktree.is_dir())
        self.assertEqual(list(worktree.iterdir()), [])


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
        owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        aborted = owner_integration_merge.abort_task_integration("056", self.primary)
        self.assertEqual(aborted["status"], "aborted")
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=task_worktree).stdout.strip(), task_commit)


    def test_abort_recovers_an_owned_lease_before_merge_state_exists(self) -> None:
        self.prepare()
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        _task_state, lease_path, integration_path = owner_worktree_storage._lifecycle_paths(self.primary, identity)
        meridian._write_json_atomic(
            lease_path,
            {"version": 1, "task_id": "056", "branch": "task-056", "project": str(self.primary)},
            exclusive=True,
        )
        self.assertFalse(integration_path.exists())
        recovered = owner_integration_merge.abort_task_integration("056", self.primary)
        self.assertEqual(recovered["status"], "aborted")
        self.assertFalse(lease_path.exists())
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)


    def test_abort_recovers_when_the_queue_link_is_stale(self) -> None:
        self.prepare()
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        _task_state, lease_path, _integration_path = owner_worktree_storage._lifecycle_paths(self.primary, identity)
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
        with self.assertRaisesRegex(shared_errors.MeridianError, "queue link for task 056"):
            owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        recovered = owner_integration_merge.abort_task_integration("056", self.primary)
        self.assertEqual(recovered["status"], "aborted")
        self.assertFalse(lease_path.exists())


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



if __name__ == "__main__":
    unittest.main()
