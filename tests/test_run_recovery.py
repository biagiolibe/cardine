"""Cause classification of worktree, state, lease and cleanup stops (RE2a).

Classification only reads. A recoverable cause needs a measured ownership fact;
every ambiguous, corrupt, foreign, live or denied case keeps its guardrail code.
"""

from __future__ import annotations

import ast
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

import test_worktree_lifecycle as lifecycle
from cardine.integration import merge as owner_merge
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineStop
from cardine.stops import causes
from cardine.stops.registry import load_stop_registry
from cardine.stops.render import stop_error
from cardine.tasks import identity as owner_identity
from cardine.tasks.creation import create_task
from cardine.tasks.state import read_task_state
from cardine.worktree import storage as owner_storage
from project_config_support import write_project_config
from stop_recovery_support import ROOT, resume_from, run_recovery
from task_contract_support import VALIDATION, contract_record, seal_state, write_state

FAMILY = frozenset({
    "WRONG_WORKTREE", "LEASE_HELD", "PRIMARY_DIRTY", "CLEANUP_BLOCKED", "TASK_STATE_INVALID",
    "TASK_STATUS_REJECTED", "COMMAND_REFUSED", "OS_ACCESS_FAILED", "WORKTREE_RELOCATE",
    "LEASE_INTERRUPTED", "TASK_STATE_INTERRUPTED", "CLEANUP_PARTIAL", "PUSH_PENDING",
})
EMITTING_CALLS = frozenset({"stop_error", "stop_factory", "stop_resume", "format_stop"})
SPLIT = {"WORKTREE_RELOCATE", "LEASE_INTERRUPTED", "TASK_STATE_INTERRUPTED", "CLEANUP_PARTIAL"}


def scan_emitters() -> set[tuple[str, str, str]]:
    """Every literal emitter of the family and every dynamically coded stop call."""
    found: set[tuple[str, str, str]] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self, path: str) -> None:
            self.path, self.scope = path, []

        def _enter(self, node: ast.AST) -> None:
            self.scope.append(node.name)  # type: ignore[attr-defined]
            self.generic_visit(node)
            self.scope.pop()

        visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _enter

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and node.value in FAMILY:
                found.add((self.path, ".".join(self.scope), node.value))

        def visit_Call(self, node: ast.Call) -> None:
            function = node.func
            name = function.id if isinstance(function, ast.Name) else getattr(function, "attr", None)
            if name in EMITTING_CALLS and node.args and not (
                isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
            ):
                found.add((self.path, ".".join(self.scope), "<dynamic>"))
            self.generic_visit(node)

    for path in sorted((ROOT / "src/cardine").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith("src/cardine/stops/"):
            Visitor(relative).visit(ast.parse(path.read_text(encoding="utf-8")))
    return found


class RunRecoveryTest(unittest.TestCase):
    setUp = lifecycle.WorktreeLifecycleCliTest.setUp
    tearDown = lifecycle.WorktreeLifecycleCliTest.tearDown
    run_cli = lifecycle.WorktreeLifecycleCliTest.run_cli
    create_bare_origin = lifecycle.WorktreeLifecycleCliTest.create_bare_origin
    _stage_ready_task_with_origin = lifecycle.WorktreeLifecycleCliTest._stage_ready_task_with_origin
    _stage_args = lifecycle.WorktreeLifecycleCliTest._stage_args

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(["git", *args], cwd=cwd or self.project, check=True, capture_output=True,
                              text=True).stdout.strip()

    def identity(self):
        return owner_identity.resolve_task_identity(self.project, "056", "existing")

    def prepare(self) -> Path:
        prepared = self.run_cli("worktree", "prepare", "056", "--project", str(self.project),
                                "--worktree-root", str(self.worktree_root), "--format", "json")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        return Path(json.loads(prepared.stdout)["worktree"])

    def lease(self, **changes: object) -> Path:
        _state, lease_path, _integration = owner_storage._lifecycle_paths(self.project, self.identity())
        lease = {"version": 1, "task_id": "056", "branch": "task-056",
                 "project": str(self.project.resolve()), "main_commit": self.git("rev-parse", "main"), **changes}
        lease_path.write_text(json.dumps(lease), encoding="utf-8")
        return lease_path

    def hold_writer(self, task_id: str = "056"):
        path = receipts.guard_path(self.project, task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a")
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(handle.close)
        return handle

    # Inventory ------------------------------------------------------------------

    def test_every_emitter_of_the_family_has_a_cause_disposition(self) -> None:
        inventory = set(causes.EMITTER_CAUSES)
        self.assertEqual(scan_emitters() - inventory, set(), "emitter missing from stops/causes.py")
        self.assertEqual(inventory - scan_emitters(), set(), "inventory names an emitter that no longer exists")
        for key, (disposition, reason) in causes.EMITTER_CAUSES.items():
            with self.subTest(key=key):
                self.assertIn(disposition, {"split", "guardrail", "passthrough", "deferred"})
                self.assertTrue(reason)
                if key[2] in SPLIT:
                    self.assertEqual(disposition, "split")

    def test_split_codes_are_nonhuman_recoverable_and_guardrails_keep_authority(self) -> None:
        registry = load_stop_registry()
        for code in SPLIT | {"PUSH_PENDING"}:
            with self.subTest(code=code):
                self.assertEqual((registry[code]["resolution"], registry[code]["human_decision"]),
                                 ("recoverable", False))
        for code in ("WRONG_WORKTREE", "LEASE_HELD", "PRIMARY_DIRTY", "CLEANUP_BLOCKED",
                     "TASK_STATE_INVALID", "TASK_STATUS_REJECTED"):
            with self.subTest(code=code):
                self.assertEqual((registry[code]["resolution"], registry[code]["human_decision"]),
                                 ("guardrail", True))

    def test_judgment_emitters_are_enumerated_in_shipped_text(self) -> None:
        shipped = "\n".join(path.read_text(encoding="utf-8")
                            for path in (ROOT / "templates").rglob("*") if path.is_file()
                            and path.suffix in {".md", ".json"})
        for code, entry in load_stop_registry().items():
            if entry["class"] == "judgment":
                with self.subTest(code=code):
                    self.assertIn(code, shipped + (ROOT / "capabilities/stop-codes-v1.json").read_text())

    # WORKTREE_RELOCATE ------------------------------------------------------------

    def test_project_selection_routes_to_the_registered_worktree(self) -> None:
        worktree = self.prepare()
        result = self.run_cli("execution", "start", "056", "--project", str(self.project))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("BLOCKED WORKTREE_RELOCATE:"), result.stderr)
        resume = resume_from(result.stderr)
        self.assertIn(f"--project {worktree}", resume)
        recovered = run_recovery(resume, self.project, self.worktree_root)
        self.assertNotIn("WORKTREE_RELOCATE", recovered.stderr)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout)["task_id"], "056")

    def test_missing_worktree_stays_a_wrong_worktree_guardrail(self) -> None:
        result = self.run_cli("execution", "start", "056", "--project", str(self.project))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("BLOCKED WRONG_WORKTREE:"), result.stderr)

    # LEASE_INTERRUPTED ------------------------------------------------------------

    def test_owned_interrupted_lease_recovers_and_foreign_ownership_stays_held(self) -> None:
        evidence = self._stage_ready_task_with_origin(local_ahead=True)
        lease = self.lease()
        owned_bytes = lease.read_bytes()
        result = self.run_cli(*self._stage_args(evidence))
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("BLOCKED LEASE_INTERRUPTED:"), result.stderr)
        self.assertEqual(lease.read_bytes(), owned_bytes)  # classification wrote nothing
        again = self.run_cli(*self._stage_args(evidence))
        self.assertEqual(again.stderr, result.stderr)  # repeated resolution is stable
        status = self.run_cli("worktree", "closure-status", "056", "--project", str(self.project),
                              "--worktree-root", str(self.worktree_root), "--format", "json")
        self.assertEqual(json.loads(status.stdout)["stop_reason"], "LEASE_INTERRUPTED")
        recovered = run_recovery(resume_from(result.stderr), self.project, self.worktree_root)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertFalse(lease.exists())
        restaged = self.run_cli(*self._stage_args(evidence))
        self.assertEqual(restaged.returncode, 0, restaged.stderr)

    def test_lease_without_ownership_proof_stays_held(self) -> None:
        evidence = self._stage_ready_task_with_origin(local_ahead=True)
        for label, write in (
            ("other task", lambda: self.lease(task_id="057")),
            ("other branch", lambda: self.lease(branch="task-057")),
            ("other project", lambda: self.lease(project=str(self.root / "elsewhere"))),
            ("missing fields", lambda: self.lease_text(json.dumps({"task_id": "056"}))),
            ("corrupt json", lambda: self.lease_text("{not json")),
        ):
            with self.subTest(label):
                lease = write()
                before = lease.read_bytes()
                result = self.run_cli(*self._stage_args(evidence))
                self.assertTrue(result.stderr.startswith("BLOCKED LEASE_HELD:"), result.stderr)
                self.assertEqual(lease.read_bytes(), before)
                lease.unlink()

    def lease_text(self, text: str) -> Path:
        _state, lease_path, _integration = owner_storage._lifecycle_paths(self.project, self.identity())
        lease_path.write_text(text, encoding="utf-8")
        return lease_path

    def test_live_writer_keeps_an_owned_lease_held(self) -> None:
        evidence = self._stage_ready_task_with_origin(local_ahead=True)
        lease = self.lease()
        self.hold_writer()
        result = self.run_cli(*self._stage_args(evidence))
        self.assertTrue(result.stderr.startswith("BLOCKED LEASE_HELD:"), result.stderr)
        self.assertTrue(lease.exists())

    def test_staged_merge_that_no_longer_matches_the_lease_stays_held(self) -> None:
        self._stage_ready_task_with_origin(local_ahead=True)
        self.enter_project()
        lease = self.lease(main_commit="0" * 40)
        merge_head = owner_storage._merge_head_path(self.project)
        merge_head.write_text(self.git("rev-parse", "main") + "\n", encoding="utf-8")
        self.addCleanup(lambda: merge_head.unlink(missing_ok=True))
        self.assertEqual(causes.lease_stop_code(self.project, self.identity(), lease), "LEASE_HELD")

    # TASK_STATE_INTERRUPTED -------------------------------------------------------

    def interrupted_creation(self, root: Path) -> Path:
        write_project_config(root, "lean", validation=deepcopy(VALIDATION))
        (root / "proposal.txt").write_text(contract_record(), encoding="utf-8")
        script = (
            "import os, sys\nfrom pathlib import Path\n"
            "from cardine.lifecycle import receipts\nfrom cardine.tasks.creation import create_task\n"
            "def stop(name):\n    if name == 'after_intent': os._exit(77)\n"
            "receipts.boundary = stop\nroot = Path(sys.argv[1])\n"
            "create_task(root, '001', (root / 'proposal.txt').read_text())\n"
        )
        killed = subprocess.run([sys.executable, "-c", script, str(root)], capture_output=True, text=True,
                                env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        self.assertEqual(killed.returncode, 77, killed.stderr)
        return receipts._intent_path(root, "001")

    def read_state(self, root: Path) -> CardineStop | None:
        try:
            read_task_state(root, "001", "lean", stop_factory=stop_error)
        except CardineStop as error:
            return error
        return None

    def test_interrupted_state_operation_is_recoverable_and_corrupt_intent_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            intent = self.interrupted_creation(root)
            stop = self.read_state(root)
            self.assertEqual(stop.code, "TASK_STATE_INTERRUPTED")
            self.assertIn("rerun the identical interrupted cardine command for task 001", str(stop))
            before = intent.read_bytes()
            self.assertEqual(self.read_state(root).code, "TASK_STATE_INTERRUPTED")
            self.assertEqual(intent.read_bytes(), before)  # reading never touched the operation
            create_task(root, "001", (root / "proposal.txt").read_text())  # the identical command converges
            self.assertIsNone(self.read_state(root))
            self.assertFalse(intent.exists())

    def test_foreign_corrupt_or_live_state_operation_stays_invalid(self) -> None:
        for label in ("corrupt bytes", "other task", "live writer"):
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                intent = self.interrupted_creation(root)
                if label == "corrupt bytes":
                    intent.write_bytes(b"{")
                elif label == "other task":
                    value = receipts._load_intent(intent)
                    receipts._save_intent(intent, dict(value, task_id="002"))
                else:
                    handle = receipts.guard_path(root, "001")
                    handle.parent.mkdir(parents=True, exist_ok=True)
                    live = handle.open("a")
                    fcntl.flock(live, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.addCleanup(live.close)
                before = intent.read_bytes()
                self.assertEqual(self.read_state(root).code, "TASK_STATE_INVALID")
                self.assertEqual(intent.read_bytes(), before)

    # CLEANUP_PARTIAL, PUSH_PENDING ------------------------------------------------

    def landed_task(self, *, origin: bool = False) -> Path:
        """A task branch merged into main, its worktree still registered."""
        if origin:
            self.create_bare_origin()
            self.git("push", "-u", "origin", "main")
        worktree = self.prepare()
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        self.git("add", "implementation.txt", cwd=worktree)
        self.git("commit", "-m", "complete task", cwd=worktree)
        self.git("merge", "--no-ff", "-m", "Integrate 056", "task-056")
        return worktree

    def cleanup_args(self) -> tuple[str, ...]:
        return ("worktree", "cleanup", "056", "--project", str(self.project),
                "--worktree-root", str(self.worktree_root), "--format", "json")

    def test_partial_cleanup_reruns_and_denied_access_stays_blocked(self) -> None:
        worktree = self.landed_task()
        task_commit = self.git("rev-parse", "task-056")
        common = Path(self.git("rev-parse", "--git-common-dir"))
        common = (self.project / common).resolve()
        (self.project / "foreign.txt").write_text("foreign\n", encoding="utf-8")
        self.git("add", "foreign.txt")
        self.git("commit", "-m", "foreign work")
        real = owner_merge._run_git
        failures = []

        def fail_branch_delete(project, *args, **kwargs):
            if args[:2] == ("branch", "-d") and not failures:
                failures.append(args)
                return subprocess.CompletedProcess(args, 1, "", "injected failure after worktree removal")
            return real(project, *args, **kwargs)

        self.enter_project()
        with mock.patch.object(owner_merge, "_run_git", fail_branch_delete):
            with self.assertRaises(CardineStop) as raised:
                owner_merge.cleanup_task_worktree("056", self.worktree_root, self.project)
        self.assertEqual(raised.exception.code, "CLEANUP_PARTIAL")
        self.assertFalse(worktree.exists() and any(worktree.iterdir()))
        self.assertEqual(self.git("rev-parse", "task-056"), task_commit)  # the owned branch is retained
        self.assertTrue((self.project / "foreign.txt").is_file())
        recovered = run_recovery(resume_from(str(raised.exception)), self.project, self.worktree_root)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(json.loads(recovered.stdout)["status"], "cleaned")
        self.assertEqual(subprocess.run(["git", "rev-parse", "--verify", "--quiet", "refs/heads/task-056"],
                                        cwd=self.project, capture_output=True).returncode, 1)
        self.assertTrue((self.project / "foreign.txt").is_file())  # nothing foreign was deleted
        again = self.run_cli(*self.cleanup_args())
        self.assertEqual(again.returncode, 0, again.stderr)  # the identical command converges
        # Denied access and every unproven branch state keep the guardrail.
        branch = "task-056"
        self.assertEqual(causes.cleanup_branch_stop_code(self.project, branch, None, common), "CLEANUP_BLOCKED")
        self.assertEqual(causes.cleanup_branch_stop_code(self.project, branch, "1" * 40, common), "CLEANUP_BLOCKED")
        if os.geteuid() != 0:
            with tempfile.TemporaryDirectory() as locked:
                os.chmod(locked, 0o500)
                try:
                    self.assertEqual(causes.cleanup_branch_stop_code(self.project, branch, task_commit, Path(locked)),
                                     "CLEANUP_BLOCKED")
                finally:
                    os.chmod(locked, 0o700)

    def enter_project(self) -> None:
        previous = Path.cwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, previous)

    def interrupt_cleanup(self, wrapper_target: str, failing, expected: type[BaseException]) -> None:
        with mock.patch.object(owner_merge, wrapper_target, failing):
            with self.assertRaises(expected):
                owner_merge.cleanup_task_worktree("056", self.worktree_root, self.project)

    def test_cleanup_killed_around_each_effect_converges_without_foreign_loss(self) -> None:
        worktree = self.landed_task()
        self.enter_project()
        write_state(self.project, "056", "done", review_required=False)  # landing records the terminal state
        seal_state(self.project, "056")
        self.git("add", ".cardine/tasks/056.json")
        self.git("commit", "-m", "land task state")
        (worktree / "scratch.txt").write_text("unowned\n", encoding="utf-8")  # foreign dirt in the task worktree
        real_git = owner_merge._run_git

        def refuse_worktree_removal(project, *args, **kwargs):
            if args[:2] == ("worktree", "remove"):
                return subprocess.CompletedProcess(args, 1, "", "injected failure before the removal effect")
            return real_git(project, *args, **kwargs)

        # Before the removal effect: preflight already refuses dirty foreign work, nothing is deleted.
        result = self.run_cli(*self.cleanup_args())
        self.assertTrue(result.stderr.startswith("BLOCKED CLEANUP_BLOCKED:"), result.stderr)
        self.assertEqual((worktree / "scratch.txt").read_text(), "unowned\n")
        (worktree / "scratch.txt").unlink()
        self.interrupt_cleanup("_run_git", refuse_worktree_removal, CardineStop)
        self.assertTrue(worktree.is_dir() and any(worktree.iterdir()))
        # After the branch deletion, before the lifecycle file removal.
        calls = []

        def die_after_branch_deletion(path):
            calls.append(path)
            raise OSError("injected failure after the branch deletion effect")

        self.interrupt_cleanup("_remove_owned_file", die_after_branch_deletion, OSError)
        self.assertEqual(len(calls), 1)
        self.assertEqual(subprocess.run(["git", "rev-parse", "--verify", "--quiet", "refs/heads/task-056"],
                                        cwd=self.project, capture_output=True).returncode, 1)
        again = self.run_cli(*self.cleanup_args())  # the identical command finishes the remaining effect once
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.run_cli(*self.cleanup_args()).returncode, 0)

    def test_unmerged_or_protected_branches_are_never_a_partial_cleanup(self) -> None:
        worktree = self.prepare()
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        self.git("add", "implementation.txt", cwd=worktree)
        self.git("commit", "-m", "unmerged task work", cwd=worktree)
        tip = self.git("rev-parse", "task-056")
        result = self.run_cli(*self.cleanup_args())
        self.assertTrue(result.stderr.startswith("BLOCKED CLEANUP_BLOCKED: task commit is not integrated into main"),
                        result.stderr)
        self.assertEqual(self.git("rev-parse", "task-056"), tip)
        self.assertTrue(worktree.is_dir())
        common = (self.project / self.git("rev-parse", "--git-common-dir")).resolve()
        self.assertEqual(causes.cleanup_branch_stop_code(self.project, "task-056", tip, common), "CLEANUP_BLOCKED")
        self.git("checkout", "-b", "side")
        self.assertEqual(causes.cleanup_branch_stop_code(self.project, "task-056", tip, common), "CLEANUP_BLOCKED")

    def test_unpushed_main_is_a_pending_push_and_diverged_main_is_blocked(self) -> None:
        self.landed_task(origin=True)
        result = self.run_cli(*self.cleanup_args())
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("BLOCKED PUSH_PENDING:"), result.stderr)
        self.assertEqual(resume_from(result.stderr), "git push origin main")
        self.assertTrue((self.worktree_root / "").is_dir())
        pushed = run_recovery(resume_from(result.stderr), self.project, self.worktree_root)
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        self.assertEqual(self.run_cli(*self.cleanup_args()).returncode, 0)

    def test_diverged_origin_main_stays_a_cleanup_guardrail(self) -> None:
        self.landed_task(origin=True)
        clone = self.root / "writer"
        self.git("clone", "--branch", "main", str(self.root / "origin.git"), str(clone), cwd=self.root)
        self.git("config", "user.name", "Writer", cwd=clone)
        self.git("config", "user.email", "writer@example.invalid", cwd=clone)
        (clone / "upstream.txt").write_text("upstream\n", encoding="utf-8")
        self.git("add", "upstream.txt", cwd=clone)
        self.git("commit", "-m", "upstream", cwd=clone)
        self.git("push", "origin", "main", cwd=clone)
        self.git("fetch", "origin")
        self.assertFalse(causes.main_ahead_of_origin(self.project))
        result = self.run_cli(*self.cleanup_args())
        self.assertTrue(result.stderr.startswith("BLOCKED CLEANUP_BLOCKED: local main is not proven pushed"),
                        result.stderr)

    def test_owned_idle_lease_during_cleanup_is_recoverable_and_foreign_is_blocked(self) -> None:
        worktree = self.landed_task()
        lease = self.lease()
        result = self.run_cli(*self.cleanup_args())
        self.assertTrue(result.stderr.startswith("BLOCKED LEASE_INTERRUPTED:"), result.stderr)
        self.assertTrue(worktree.is_dir())
        lease.write_text(json.dumps({"task_id": "057"}), encoding="utf-8")
        foreign = self.run_cli(*self.cleanup_args())
        self.assertTrue(foreign.stderr.startswith("BLOCKED CLEANUP_BLOCKED:"), foreign.stderr)
        self.assertTrue(lease.exists())

    def test_dirty_primary_checkout_stays_a_guardrail(self) -> None:
        evidence = self._stage_ready_task_with_origin(local_ahead=True)
        (self.project / "foreign.txt").write_text("dirt\n", encoding="utf-8")
        result = self.run_cli(*self._stage_args(evidence))
        self.assertTrue(result.stderr.startswith("BLOCKED PRIMARY_DIRTY:"), result.stderr)
        self.assertEqual((self.project / "foreign.txt").read_text(), "dirt\n")


if __name__ == "__main__":
    unittest.main()
