"""Task-worktree checkout tests."""

from __future__ import annotations

import subprocess
import sys
import unittest
import json
import os
import re
import shlex
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import cardine_cli
from cardine.integration import merge as owner_integration_merge
from cardine.worktree import closure_status as owner_worktree_closure_status
from cardine.integration import evidence as owner_integration_evidence
from cardine.worktree import checkout as owner_worktree_checkout
from cardine.shared import journal as owner_shared_journal
import cardine.shared.errors as shared_errors
from cardine.console import models as project_console
from cardine.tasks import identity as owner_tasks_identity
from cardine.worktree import storage as owner_worktree_storage

from stop_recovery_support import run_recovery, resume_from
import worktree_support as support


class WorktreeCheckoutTest(support.BoundedWorktreeLifecycleFixture):
    # MERIDIAN-OLD-NAME-TEST
    def test_old_integration_files_do_not_block_prepare_resume_or_check(self):
        retained = [self.primary / ".git" / name for name in (
            "meridian-integration.lock", "meridian-integration.json",  # MERIDIAN-OLD-NAME-TEST
        )]
        for path in retained:
            path.write_text(json.dumps({"task_id": "056"}))
        before = [path.read_bytes() for path in retained]
        prepared = self.prepare()
        worktree = Path(prepared["worktree"])
        self.assertEqual(self.resume()["next_action"], "check")
        os.chdir(worktree)
        report, ready = owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertTrue(ready, report)
        self.assertFalse(report["integration_active"])
        self.assertEqual([path.read_bytes() for path in retained], before)
        for path in retained:
            path.write_text("invalid old integration file")
        self.assertTrue(owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)[1])
        self.assertEqual([path.read_text() for path in retained], ["invalid old integration file"] * 2)

    # MERIDIAN-OLD-NAME-TEST
    def test_old_worktree_registration_is_not_a_product_alias(self):
        prepared = self.prepare()
        worktree = Path(prepared["worktree"])
        state_path = next((self.primary / ".git/cardine-worktrees").glob("*.json"))
        old_state = self.primary / ".git/meridian-worktrees" / state_path.name  # MERIDIAN-OLD-NAME-TEST
        old_state.parent.mkdir()
        state_path.rename(old_state)
        before = old_state.read_bytes()
        os.chdir(worktree)
        report, ready = owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertFalse(ready)
        self.assertIn("missing-state", report["errors"])
        self.assertEqual(owner_worktree_checkout.registered_worktree_task_states(self.primary), [])
        self.assertEqual(old_state.read_bytes(), before)
        self.assertFalse(state_path.exists())

    def test_prepare_does_not_read_or_write_the_retired_ledger(self):
        ledger = cardine_cli.canonical_git_common_dir(self.primary) / "cardine-budget.json"
        ledger.write_text("invalid retired ledger\n", encoding="utf-8")
        self.assertTrue(self.prepare()["created"])
        self.assertEqual(ledger.read_text(encoding="utf-8"), "invalid retired ledger\n")


    def test_stale_base_check_and_repair(self) -> None:
        prepared, worktree = self.stale_base()
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        state_path, _, _ = owner_worktree_storage._lifecycle_paths(self.primary, identity)
        evidence_path = state_path.with_suffix(".evidence.json")
        evidence_path.write_text(json.dumps({"validated_base_commit": self.base}), encoding="utf-8")
        evidence_before = evidence_path.read_bytes()
        before = self.snapshot(worktree)
        os.chdir(worktree)
        report, ready = owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertFalse(ready)
        self.assertEqual(report["errors"], ["stale-base-record"])
        self.assertEqual(report["stop_reason"], "STALE_WORKTREE_BASE")
        self.assertEqual(before, self.snapshot(worktree))
        command = [sys.executable, str(ROOT / "scripts/cardine_cli.py"), "worktree", "check",
                   "056", "--project", str(self.primary), "--worktree-root", str(self.worktree_root),
                   "--format", "json"]
        checked = subprocess.run(command, cwd=worktree, text=True, capture_output=True, check=False)
        self.assertEqual(checked.returncode, 0)
        self.assertEqual(checked.stderr.strip(),
                         "NEXT STALE_WORKTREE_BASE: worktree check reported: stale-base-record; resume: "
                         + str(report["resume"]))
        self.assertEqual(before, self.snapshot(worktree))
        self.assertEqual(self.resume()["base_commit"], self.base)
        self.assertEqual(before, self.snapshot(worktree))
        with self.assertRaisesRegex(shared_errors.CardineError, "NEXT STALE_WORKTREE_BASE:"):
            self.prepare()
        closure, _ = owner_worktree_closure_status.closure_status("056", self.worktree_root, self.primary)
        self.assertEqual(closure["stop_reason"], "STALE_WORKTREE_BASE")
        original = json.loads(state_path.read_text(encoding="utf-8"))
        recovery = run_recovery(resume_from(checked.stderr), worktree, self.worktree_root)
        self.assertEqual(recovery.returncode, 0, recovery.stderr)
        recovered = json.loads(recovery.stdout)
        self.assertTrue(recovered["repaired"])
        self.assertTrue(recovered["evidence_renewal_required"])
        renewed = json.loads(state_path.read_text(encoding="utf-8"))
        head = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.assertEqual(renewed, {**original, "base_commit": head, "task_commit": head})
        self.assertEqual(renewed["started_at"], prepared["started_at"])
        self.assertEqual(evidence_before, evidence_path.read_bytes())
        snapshot = self.snapshot(worktree)
        self.assertFalse(owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)["repaired"])
        command[3] = "repair-base"
        repeated = subprocess.run(command, cwd=worktree, text=True, capture_output=True, check=False)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertFalse(json.loads(repeated.stdout)["repaired"])
        self.assertEqual(snapshot, self.snapshot(worktree))
        self.assertTrue(owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)[1])
        # Another main fast-forward after recovery remains provable.
        (self.primary / "second.txt").write_text("second main advancement\n", encoding="utf-8")
        self.git("add", "second.txt")
        self.git("commit", "-m", "advance main again")
        self.git("merge", "main", "--ff-only", cwd=worktree)
        self.assertEqual(owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)[0]["stop_reason"],
                         "STALE_WORKTREE_BASE")
        self.assertTrue(owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)["repaired"])


    def test_repaired_base_rejects_old_validation_evidence(self) -> None:
        _, worktree = self.stale_base()
        owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)
        (worktree / "task.txt").write_text("task work\n", encoding="utf-8")
        self.git("add", "task.txt", cwd=worktree)
        self.git("commit", "-m", "task work", cwd=worktree)
        os.chdir(worktree)
        recorded = owner_integration_evidence.record_task_evidence(
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
        self.assertEqual(owner_worktree_closure_status.closure_status("056", self.worktree_root, self.primary)[0]["step"], "C5")
        with self.assertRaisesRegex(shared_errors.CardineError, "NEXT EVIDENCE_MISMATCH:"):
            owner_integration_merge.stage_task_integration("056", self.worktree_root, evidence_path, self.primary)
        self.assertEqual(evidence_path.read_bytes(), before)
        self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())


    def test_base_repair_rejects_unsafe_worktree_facts(self) -> None:
        _, worktree = self.stale_base()
        identity = owner_tasks_identity.resolve_task_identity(self.primary, "056", "existing")
        state_path, lease, integration = owner_worktree_storage._lifecycle_paths(self.primary, identity)
        original = state_path.read_bytes()
        mutations = [
            (worktree / "dirty.txt", "dirty\n"),
            (lease, '{}'), (integration, '{}'),
        ]
        for path, contents in mutations:
            with self.subTest(path=path.name):
                path.write_text(contents, encoding="utf-8")
                with self.assertRaisesRegex(shared_errors.CardineError, "BLOCKED WRONG_WORKTREE:"):
                    owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)
                self.assertEqual(state_path.read_bytes(), original)
                path.unlink()
        for field in ("task_id", "project", "worktree", "branch", "worktree_root", "git_common_dir"):
            with self.subTest(field=field):
                state = json.loads(original)
                state[field] = "unrelated"
                state_path.write_text(json.dumps(state), encoding="utf-8")
                before = state_path.read_bytes()
                with self.assertRaisesRegex(shared_errors.CardineError, "BLOCKED WRONG_WORKTREE:"):
                    owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)
                self.assertEqual(state_path.read_bytes(), before)
                state_path.write_bytes(original)
        self.git("switch", "-c", "unrelated", cwd=worktree)
        with self.assertRaisesRegex(shared_errors.CardineError, "BLOCKED WRONG_WORKTREE:"):
            owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)


    def test_task_commits_and_normal_main_advancement_are_not_stale(self) -> None:
        prepared = self.prepare()
        worktree = Path(str(prepared["worktree"]))
        (worktree / "task.txt").write_text("task work\n", encoding="utf-8")
        self.git("add", "task.txt", cwd=worktree)
        self.git("commit", "-m", "task work", cwd=worktree)
        (self.primary / "upstream.txt").write_text("main work\n", encoding="utf-8")
        self.git("add", "upstream.txt")
        self.git("commit", "-m", "main work")
        self.assertTrue(owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary,
                                                      require_effective_worktree=False)[1])
        with self.assertRaisesRegex(shared_errors.CardineError, "unproven-fast-forward"):
            owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)
        # Even after main contains the task commit, ancestry alone cannot prove recovery.
        self.git("merge", "task-056", "--no-edit")
        self.git("merge", "main", "--ff-only", cwd=worktree)
        self.assertTrue(owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary,
                                                      require_effective_worktree=False)[1])
        with self.assertRaisesRegex(shared_errors.CardineError, "unproven-fast-forward"):
            owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)


    def test_base_repair_requires_intact_fast_forward_reflog(self) -> None:
        _, worktree = self.stale_base()
        self.git("reflog", "expire", "--expire=now", "refs/heads/task-056")
        self.assertTrue(owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary,
                                                      require_effective_worktree=False)[1])
        with self.assertRaisesRegex(shared_errors.CardineError, "unproven-fast-forward"):
            owner_worktree_checkout.repair_task_worktree_base("056", self.worktree_root, self.primary)


    def test_resume_accepts_a_dirty_worktree_and_changes_nothing(self) -> None:
        prepared, worktree = self.dirty_worktree()
        before = self.snapshot(worktree)
        with self.assertRaisesRegex(shared_errors.CardineError, "existing task worktree is dirty and was retained"):
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
        report, ready = owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertFalse(ready)
        self.assertEqual(report["errors"], ["dirty-worktree"])
        self.assertIn("prepare 056 --resume", report["resume"])
        report, ready = owner_worktree_checkout.inspect_task_worktree(
            "056", self.worktree_root, self.primary, resume=True)
        self.assertTrue(ready)
        self.assertEqual((report["status"], report["next_action"]), ("ready-dirty", "inspect-dirty"))
        self.assertEqual((report["changed_paths"], report["untracked_paths"]), (1, 1))
        self.assertEqual(self.snapshot(worktree), before)
        self.assertEqual(shlex.split(resumed["next_command"]), [
            "cardine", "worktree", "check", "056", "--resume", "--project", str(self.primary.resolve()), "--format", "json"])


    def test_resume_never_attempts_a_lifecycle_state_write(self) -> None:
        prepared, worktree = self.dirty_worktree()
        state_directory = self.primary / ".git/cardine-worktrees"
        before = sorted(item.name for item in state_directory.iterdir())
        state_path = next(state_directory.glob("*.json"))
        original = state_path.read_bytes()
        with mock.patch.object(owner_worktree_checkout, "_write_json_atomic", side_effect=AssertionError("state write")), \
                mock.patch.object(cardine_cli.tempfile, "mkstemp", side_effect=AssertionError("temporary file")):
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
        state_path = next((self.primary / ".git/cardine-worktrees").glob("*.json"))
        original = state_path.read_text(encoding="utf-8")
        state_path.write_text(original.replace('"branch": "task-056"', '"branch": "other"'), encoding="utf-8")
        with self.assertRaises(shared_errors.CardineStop) as raised:
            self.resume()
        self.assertEqual(raised.exception.code, "WRONG_WORKTREE")
        message = str(raised.exception)
        self.assertTrue(message.startswith("BLOCKED WRONG_WORKTREE: "))
        for expected in (str(state_path), "branch task-056", "branch other"):
            self.assertIn(expected, message)
        self.assertEqual(state_path.read_text(encoding="utf-8").count('"other"'), 1)


    def test_resume_with_missing_state_requires_covered_registration(self) -> None:
        prepared, worktree = self.dirty_worktree()
        state_directory = self.primary / ".git/cardine-worktrees"
        next(state_directory.glob("*.json")).unlink()
        before = self.snapshot(worktree)
        with self.assertRaisesRegex(shared_errors.CardineError, "missing covered lifecycle registration"):
            self.resume()
        self.assertEqual(before, self.snapshot(worktree))
        with self.assertRaisesRegex(shared_errors.CardineError, "missing covered lifecycle registration"):
            self.prepare()
        self.assertEqual(list(state_directory.glob("*.json")), [])
        self.assertEqual(Path(prepared["worktree"]), worktree)

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
        with self.assertRaisesRegex(shared_errors.CardineError, "nothing to resume"):
            self.resume()
        self.assertEqual(self.git("branch", "--list", "task-056").stdout, "")
        self.assertEqual(list(self.worktree_root.rglob("task-056")), [])
        self.assertFalse((self.primary / ".git/cardine-worktrees").exists())


    def test_resume_keeps_every_other_prepare_block(self) -> None:
        prepared, worktree = self.dirty_worktree()
        state_path = next((self.primary / ".git/cardine-worktrees").glob("*.json"))
        original = state_path.read_text(encoding="utf-8")
        state_path.write_text(original.replace('"branch": "task-056"', '"branch": "other"'), encoding="utf-8")
        with self.assertRaisesRegex(shared_errors.CardineError, "lifecycle state mismatch"):
            self.resume()
        state_path.write_text(original, encoding="utf-8")
        for name in ("cardine-integration.lock", "cardine-integration.json"):
            with self.subTest(retained=name):
                retained = self.primary / ".git" / name
                retained.write_text(json.dumps({"task_id": "056"}), encoding="utf-8")
                with self.assertRaisesRegex(shared_errors.CardineError, "integration lease or staged merge"):
                    self.resume()
                retained.unlink()
        self.git("checkout", "-b", "elsewhere", cwd=worktree)
        with self.assertRaisesRegex(shared_errors.CardineError, "canonical worktree mismatch"):
            self.resume()
        self.git("checkout", "task-056", cwd=worktree)
        self.git("commit", "--allow-empty", "-m", "advance", cwd=worktree)
        self.assertTrue(self.resume()["dirty"])
        self.git("worktree", "remove", "--force", str(worktree))
        with self.assertRaisesRegex(shared_errors.CardineError, "nothing to resume"):
            self.resume()
        self.git("branch", "-D", "task-056")
        collision = Path(str(prepared["worktree"]))
        collision.mkdir(parents=True)
        with self.assertRaisesRegex(shared_errors.CardineError, "nothing to resume"):
            self.resume()
        with self.assertRaisesRegex(shared_errors.CardineError, "worktree path collision"):
            self.prepare()


    def test_console_resume_directive_is_accepted_by_prepare_resume(self) -> None:
        prepared, worktree = self.dirty_worktree()
        task = project_console.Task(
            task_id="056", title="t", status="in_progress", phase=(), dependencies=(), path=None,
            objective=(), criteria=(), readiness="IN PROGRESS", lifecycle="in_progress",
            active_writer=True,
        )
        directive = str(task.launch_command)
        match = re.fullmatch(r"Proceed with 056 \(Resume: run (cardine worktree prepare 056 .*)\)", directive)
        self.assertIsNotNone(match, directive)
        arguments = match.group(1).split()[1:]
        self.assertIn("--resume", arguments)
        clean = project_console.Task(**{**task.__dict__, "active_writer": False})
        self.assertEqual(clean.launch_command, "Proceed with 056")
        command = [sys.executable, str(ROOT / "scripts/cardine_cli.py"), *arguments,
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

        wrong, ready = owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertFalse(ready)
        self.assertIn("wrong-worktree", wrong["errors"])

        os.chdir(Path(str(prepared["worktree"])))
        correct, ready = owner_worktree_checkout.inspect_task_worktree("056", self.worktree_root, self.primary)
        self.assertTrue(ready, correct)
        self.assertEqual(correct["branch"], "task-056")
        self.assertTrue(correct["clean"])


if __name__ == "__main__":
    unittest.main()
