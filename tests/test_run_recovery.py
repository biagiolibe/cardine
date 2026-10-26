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
from cardine.integration import cleanup as owner_cleanup
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
from stop_recovery_support import ROOT, resume_from, run_recovery as _run_recovery
from task_contract_support import VALIDATION, contract_record, seal_state, write_state

def run_recovery(command, cwd, worktree_root=None):
    return _run_recovery(command, cwd, worktree_root, control_host=True)


FAMILY = frozenset({
    "WRONG_WORKTREE", "LEASE_HELD", "PRIMARY_DIRTY", "CLEANUP_BLOCKED", "TASK_STATE_INVALID",
    "TASK_STATUS_REJECTED", "COMMAND_REFUSED", "OS_ACCESS_FAILED", "WORKTREE_RELOCATE",
    "LEASE_INTERRUPTED", "TASK_STATE_INTERRUPTED", "CLEANUP_PARTIAL", "PUSH_PENDING",
    "TASK_STEP_PENDING", "DEPENDENCY_PENDING",
})
EMITTING_CALLS = frozenset({"stop_error", "stop_factory", "stop_resume", "format_stop"})
POINTS = ("before_intent", "after_intent", "before_staged_pair", "after_staged_pair",
          "before_state_replace", "after_state_replace", "before_result_receipt", "after_result_receipt")
RESIDUE_POINTS = frozenset(POINTS[1:])
STAGE_BOUNDARIES = ("before_stage_lease", "after_stage_lease", "before_stage_json", "after_stage_json")
STAGE_KILL_POINTS = ("before_merge", "after_merge", *POINTS, "after_views", *STAGE_BOUNDARIES)
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
    measure = lifecycle.WorktreeLifecycleCliTest.measure

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
                    self.assertIn(code, shipped)

    # WORKTREE_RELOCATE ------------------------------------------------------------

    def test_project_selection_routes_to_the_registered_worktree(self) -> None:
        worktree = self.prepare()
        result = self.run_cli("execution", "start", "056", "--project", str(self.project))
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stderr.startswith("NEXT WORKTREE_RELOCATE:"), result.stderr)
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
        self._stage_ready_task_with_origin(local_ahead=True)
        lease = self.lease()
        owned_bytes = lease.read_bytes()
        result = self.run_cli(*self._stage_args())
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stderr.startswith("NEXT LEASE_INTERRUPTED:"), result.stderr)
        self.assertEqual(lease.read_bytes(), owned_bytes)  # classification wrote nothing
        again = self.run_cli(*self._stage_args())
        self.assertEqual(again.stderr, result.stderr)  # repeated resolution is stable
        status = self.run_cli("worktree", "closure-status", "056", "--project", str(self.project),
                              "--worktree-root", str(self.worktree_root), "--format", "json")
        self.assertEqual(json.loads(status.stdout)["stop_reason"], "LEASE_INTERRUPTED")
        recovered = run_recovery(resume_from(result.stderr), self.project, self.worktree_root)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertFalse(lease.exists())
        worker = Path(owner_storage._read_json_object(
            owner_storage._lifecycle_paths(self.project, self.identity())[0], 'worktree')['worktree'])
        self.git('add', '--', '.cardine/tasks/056.json', cwd=worker)
        self.git('commit', '-m', 'Record owned abort receipts', cwd=worker)
        restaged = self.run_cli(*self._stage_args())
        self.assertEqual(restaged.returncode, 0, restaged.stderr)

    def test_lease_without_ownership_proof_stays_held(self) -> None:
        self._stage_ready_task_with_origin(local_ahead=True)
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
                result = self.run_cli(*self._stage_args())
                self.assertTrue(result.stderr.startswith("BLOCKED LEASE_HELD:"), result.stderr)
                self.assertEqual(lease.read_bytes(), before)
                lease.unlink()

    def lease_text(self, text: str) -> Path:
        _state, lease_path, _integration = owner_storage._lifecycle_paths(self.project, self.identity())
        lease_path.write_text(text, encoding="utf-8")
        return lease_path

    def test_live_writer_keeps_an_owned_lease_held(self) -> None:
        self._stage_ready_task_with_origin(local_ahead=True)
        lease = self.lease()
        self.hold_writer()
        result = self.run_cli(*self._stage_args())
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

    def test_foreign_merge_with_an_owned_lease_is_never_aborted(self) -> None:
        self._stage_ready_task_with_origin(local_ahead=True)
        self.enter_project()
        self.git("checkout", "-q", "-b", "other")
        (self.project / "other.txt").write_text("other\n", encoding="utf-8")
        self.git("add", "other.txt")
        self.git("commit", "-q", "-m", "other work")
        self.git("checkout", "-q", "main")
        self.git("checkout", "-q", "-b", "diverged")
        (self.project / "diverged.txt").write_text("diverged\n", encoding="utf-8")
        self.git("add", "diverged.txt")
        self.git("commit", "-q", "-m", "diverged work")
        self.git("checkout", "-q", "main")
        self.git("merge", "--no-ff", "--no-commit", "other")  # a foreign merge at the lease's main commit
        lease = self.lease()
        merge_head = owner_storage._merge_head_path(self.project)
        self.assertTrue(merge_head.is_file())
        self.assertEqual(causes.lease_stop_code(self.project, self.identity(), lease), "LEASE_HELD")
        status = self.run_cli("worktree", "closure-status", "056", "--project", str(self.project),
                              "--worktree-root", str(self.worktree_root), "--format", "json")
        self.assertEqual(json.loads(status.stdout)["stop_reason"], "LEASE_HELD")
        self.assertTrue(merge_head.is_file())  # nothing aborted the foreign merge

    def kill_stage(self, point: str) -> None:
        script = (
            "import os, sys\nfrom pathlib import Path\nfrom cardine.integration import merge\n"
            "from cardine.lifecycle import receipts\npoint = sys.argv[1]\nreal = merge._run_git\n"
            "def git(project, *args, **kwargs):\n"
            "    if args[:3] == ('merge', '--no-ff', '--no-commit'):\n"
            "        if point == 'before_merge': os._exit(77)\n"
            "        result = real(project, *args, **kwargs)\n"
            "        if point == 'after_merge': os._exit(77)\n"
            "        return result\n"
            "    return real(project, *args, **kwargs)\n"
            "merge._run_git = git\n"
            "views = merge._regenerate_status_views\n"
            "def regenerated(project):\n    views(project)\n    os._exit(77)\n"
            "if point == 'after_views': merge._regenerate_status_views = regenerated\n"
            "def stop(name):\n    if name == point: os._exit(77)\n"
            "if point in %r: receipts.boundary = stop\n"
            "merge.stage_task_integration('056', Path(sys.argv[2]), None, Path(sys.argv[3]))\n" % ((*POINTS, *STAGE_BOUNDARIES),))
        self.kill_writer(script, point, str(self.worktree_root), str(self.project))

    def assert_stage_kill_recovers(self, point: str) -> None:
        self._stage_ready_task_with_origin(local_ahead=True)
        self.enter_project()
        head = self.git("rev-parse", "HEAD")
        self.kill_stage(point)
        if point == "before_stage_lease":
            # Nothing was created: the identical command simply stages.
            _state, lease, integration = owner_storage._lifecycle_paths(self.project, self.identity())
            self.assertFalse(lease.exists() or integration.exists())
            self.assertEqual(self.git("status", "--porcelain"), "")
            self.assertEqual(self.run_cli(*self._stage_args()).returncode, 0)
            return
        if point == "after_stage_json":
            # The candidate was fully staged: the identical command returns it unchanged.
            _state, _lease, integration = owner_storage._lifecycle_paths(self.project, self.identity())
            stored = json.loads(integration.read_text(encoding="utf-8"))
            again = self.run_cli(*self._stage_args())
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(json.loads(again.stdout), stored)
            resume = ("cardine worktree integrate abort 056 --project " + str(self.project) + " --format json")
        else:
            status = self.run_cli("worktree", "closure-status", "056", "--project", str(self.project),
                                  "--worktree-root", str(self.worktree_root), "--format", "json")
            self.assertEqual(json.loads(status.stdout)["stop_reason"], "LEASE_INTERRUPTED")
            resume = json.loads(status.stdout)["resume"]
        residue = sorted(line[3:] for line in self.git("status", "--porcelain").splitlines() if line.startswith("??"))
        self.assertEqual(bool(residue), point in RESIDUE_POINTS)
        recovered = run_recovery(resume, self.project, self.worktree_root)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)  # no commit was made
        _state, lease, integration = owner_storage._lifecycle_paths(self.project, self.identity())
        self.assertFalse(lease.exists() or integration.exists())
        worker = Path(owner_storage._read_json_object(
            owner_storage._lifecycle_paths(self.project, self.identity())[0], 'worktree')['worktree'])
        self.git('add', '--', '.cardine/tasks/056.json', cwd=worker)
        self.git('commit', '-m', 'Record owned abort receipts', cwd=worker)
        restaged = self.run_cli(*self._stage_args())
        # Owned residue is cleared as a recorded effect and the identical stage converges.
        self.assertEqual(restaged.returncode, 0, restaged.stderr)
        state = json.loads((self.project / ".cardine/tasks/056.json").read_text())
        landing = [item for item in state["run"]["receipts"] if item["kind"] == "landing_state"]
        self.assertEqual(len(landing), 1)  # exactly one landing receipt after recovery
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual([line for line in self.git("status", "--porcelain").splitlines() if line.startswith("??")], [])
        if point in RESIDUE_POINTS:
            record = receipts.safe_path(owner_storage.canonical_git_common_dir(self.project),
                                        "cardine-operations/056.residue.json")
            self.assertEqual(receipts._load_intent(record)["result"], "verified")

    # Engine-owned landing residue ---------------------------------------------------

    def residue_ready(self) -> str:
        """Kill a stage inside the landing write, abort it, and return the untouched main commit."""
        self._stage_ready_task_with_origin(local_ahead=True)
        self.enter_project()
        head = self.git("rev-parse", "HEAD")
        self.kill_stage("after_staged_pair")
        status = self.run_cli("worktree", "closure-status", "056", "--project", str(self.project),
                              "--worktree-root", str(self.worktree_root), "--format", "json")
        recovered = run_recovery(json.loads(status.stdout)["resume"], self.project, self.worktree_root)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        worker = Path(owner_storage._read_json_object(
            owner_storage._lifecycle_paths(self.project, self.identity())[0], "worktree")["worktree"])
        self.git("add", "--", ".cardine/tasks/056.json", cwd=worker)
        self.git("commit", "-m", "Record owned abort receipts", cwd=worker)
        return head

    def residue_paths(self) -> list[str]:
        return sorted(line[3:] for line in self.git("status", "--porcelain").splitlines() if line.startswith("??"))

    def residue_record(self) -> Path:
        return receipts.safe_path(owner_storage.canonical_git_common_dir(self.project),
                                  "cardine-operations/056.residue.json")

    def kill_residue(self, point: str) -> None:
        script = (
            "import os, sys\nfrom pathlib import Path\nfrom cardine.integration import merge\n"
            "from cardine.lifecycle import receipts\n"
            "def stop(name):\n    if name == sys.argv[1]: os._exit(77)\n"
            "receipts.boundary = stop\n"
            "merge.stage_task_integration('056', Path(sys.argv[2]), None, Path(sys.argv[3]))\n")
        self.kill_writer(script, point, str(self.worktree_root), str(self.project))

    def assert_residue_clear_converges(self, point: str) -> None:
        head = self.residue_ready()
        self.assertTrue(self.residue_paths())
        self.kill_residue(point)
        restaged = self.run_cli(*self._stage_args())
        self.assertEqual(restaged.returncode, 0, restaged.stderr)
        state = json.loads((self.project / ".cardine/tasks/056.json").read_text())
        self.assertEqual(sum(item["kind"] == "landing_state" for item in state["run"]["receipts"]), 1)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.residue_paths(), [])
        self.assertEqual(receipts._load_intent(self.residue_record())["result"], "verified")

    def test_changed_residue_bytes_stay_dirty_and_are_preserved(self) -> None:
        self.residue_ready()
        before = self.residue_paths()
        staged = next(path for path in before if path.endswith(".stage"))
        with (self.project / staged).open("ab") as handle:
            handle.write(b"foreign edit\n")
        content = {path: (self.project / path).read_bytes() for path in before}
        result = self.run_cli(*self._stage_args())
        self.assertTrue(result.stderr.startswith("BLOCKED PRIMARY_DIRTY:"), result.stderr)
        self.assertEqual({path: (self.project / path).read_bytes() for path in before}, content)
        self.assertFalse(self.residue_record().exists())

    def test_foreign_dirt_beside_owned_residue_preserves_everything(self) -> None:
        self.residue_ready()
        (self.project / "foreign.txt").write_text("dirt\n")
        before = self.residue_paths()
        result = self.run_cli(*self._stage_args())
        self.assertTrue(result.stderr.startswith("BLOCKED PRIMARY_DIRTY:"), result.stderr)
        self.assertEqual(self.residue_paths(), before)
        self.assertEqual((self.project / "foreign.txt").read_text(), "dirt\n")

    def test_residue_operation_of_another_source_is_foreign_and_residue_survives(self) -> None:
        self.residue_ready()
        before = self.residue_paths()
        record = self.residue_record()
        record.parent.mkdir(parents=True, exist_ok=True)
        receipts._save_intent(record, dict(task_id="056", head="0" * 40, authority={}, intent="x",
                                           intent_digest="x", staged={}, result="pending"))
        result = self.run_cli(*self._stage_args())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign landing residue operation", result.stderr)
        self.assertEqual(self.residue_paths(), before)

    def test_recovered_residue_is_not_replayed_for_a_later_clean_stage(self) -> None:
        self.residue_ready()
        self.assertEqual(self.run_cli(*self._stage_args()).returncode, 0)
        before = self.residue_record().read_bytes()
        again = self.run_cli(*self._stage_args())
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.residue_record().read_bytes(), before)

    # TASK_STATE_INTERRUPTED -------------------------------------------------------

    def kill_writer(self, script: str, *arguments: str) -> None:
        killed = subprocess.run([sys.executable, "-c", script, *arguments], cwd=self.project, capture_output=True,
                                text=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
        self.assertEqual(killed.returncode, 77, killed.stderr)

    def kill_transition(self, point: str) -> None:
        self.kill_writer(
            "import os, sys\nfrom pathlib import Path\nfrom cardine.lifecycle import receipts\n"
            "from cardine.tasks.transitions import transition_task_state\n"
            "def stop(name):\n    if name == sys.argv[2]: os._exit(77)\n"
            "receipts.boundary = stop\n"
            "transition_task_state(Path(sys.argv[1]), '056', 'in_progress', cancellation_authority='', reason='')\n", str(self.project), point)

    def read_state(self, root: Path, task_id: str = "056") -> CardineStop | None:
        try:
            read_task_state(root, task_id, "lean", stop_factory=stop_error)
        except CardineStop as error:
            return error
        return None

    def queue_task_state(self) -> None:
        self.enter_project()
        write_state(self.project, "056", "queued", review_required=False)
        seal_state(self.project, "056")
        self.git("add", ".cardine/tasks/056.json")
        self.git("commit", "-m", "queued task state")

    def test_interrupted_transition_is_recoverable_at_every_boundary(self) -> None:
        self.queue_task_state()
        for point in POINTS:
            with self.subTest(point=point):
                self.kill_transition(point)
                intent = receipts._intent_path(self.project, "056")
                stop = self.read_state(self.project)
                if not intent.exists():
                    self.assertIsNone(stop)  # killed before the intent: nothing pending, state intact
                    self.git("reset", "--hard", "-q")
                    continue
                self.assertEqual(stop.code, "TASK_STATE_INTERRUPTED", str(stop))
                before = intent.read_bytes()
                self.assertEqual(str(self.read_state(self.project)), str(stop))  # reading is pure
                self.assertEqual(intent.read_bytes(), before)
                recovered = run_recovery(resume_from(str(stop)), self.project, self.worktree_root)
                self.assertEqual(recovered.returncode, 0, recovered.stderr)
                state = json.loads((self.project / ".cardine/tasks/056.json").read_text())
                self.assertEqual(state["status"], "in_progress")
                self.assertEqual([item["to"] for item in state["transitions"]], ["in_progress"])
                kinds = [item["kind"] for item in state["run"]["receipts"]]
                self.assertEqual(sum(kind.startswith("transition:") for kind in kinds), 1)  # one receipt, no retry
                self.assertFalse(intent.exists())
                self.assertIsNone(self.read_state(self.project))
                self.git("reset", "--hard", "-q")
                self.git("clean", "-fdq")

    def test_foreign_corrupt_live_or_unreplayable_state_operation_stays_invalid(self) -> None:
        self.queue_task_state()
        self.kill_transition("after_intent")
        intent = receipts._intent_path(self.project, "056")
        original = intent.read_bytes()
        value = receipts._load_intent(intent)
        handle = None
        for label in ("corrupt bytes", "other task", "other command kind", "live writer"):
            with self.subTest(label):
                intent.write_bytes(original)
                if label == "corrupt bytes":
                    intent.write_bytes(b"{")
                elif label == "other task":
                    receipts._save_intent(intent, dict(value, task_id="057"))
                elif label == "other command kind":
                    changed = deepcopy(value)
                    changed["state"]["run"]["receipts"][-1]["kind"] = "landing_state"
                    receipts._save_intent(intent, changed)
                else:
                    handle = self.hold_writer()
                before = intent.read_bytes()
                self.assertEqual(self.read_state(self.project).code, "TASK_STATE_INVALID")
                self.assertEqual(intent.read_bytes(), before)
        handle.close()

    def test_interrupted_creation_has_no_single_replay_command_and_stays_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            write_project_config(root, "lean", validation=deepcopy(VALIDATION))
            (root / "proposal.txt").write_text(contract_record(), encoding="utf-8")
            killed = subprocess.run(
                [sys.executable, "-c",
                 "import os, sys\nfrom pathlib import Path\nfrom cardine.lifecycle import receipts\n"
                 "from cardine.tasks.creation import create_task\n"
                 "def stop(name):\n    if name == 'after_intent': os._exit(77)\n"
                 "receipts.boundary = stop\nroot = Path(sys.argv[1])\n"
                 "create_task(root, '001', (root / 'proposal.txt').read_text())\n", str(root)],
                capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
            self.assertEqual(killed.returncode, 77, killed.stderr)
            intent = receipts._intent_path(root, "001")
            before = intent.read_bytes()
            self.assertEqual(self.read_state(root, "001").code, "TASK_STATE_INVALID")
            self.assertEqual(intent.read_bytes(), before)
            create_task(root, "001", (root / "proposal.txt").read_text())  # the identical command still converges
            self.assertIsNone(self.read_state(root, "001"))

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
        real = owner_cleanup._run_git
        failures = []

        def fail_branch_delete(project, *args, **kwargs):
            if args[:2] == ("branch", "-d") and not failures:
                failures.append(args)
                return subprocess.CompletedProcess(args, 1, "", "injected failure after worktree removal")
            return real(project, *args, **kwargs)

        self.enter_project()
        with mock.patch.object(owner_cleanup, "_run_git", fail_branch_delete):
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
        if wrapper_target == '_remove_owned_file':
            target, attribute = receipts, 'boundary'
            original = failing
            failing = lambda name: original(name) if name == 'before_cleanup_lifecycle' else None
        else:
            target, attribute = owner_cleanup, wrapper_target
        with mock.patch.object(target, attribute, failing):
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
        real_git = owner_cleanup._run_git

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
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stderr.startswith("NEXT PUSH_PENDING:"), result.stderr)
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
        self.assertTrue(result.stderr.startswith("NEXT LEASE_INTERRUPTED:"), result.stderr)
        self.assertTrue(worktree.is_dir())
        lease.write_text(json.dumps({"task_id": "057"}), encoding="utf-8")
        foreign = self.run_cli(*self.cleanup_args())
        self.assertTrue(foreign.stderr.startswith("BLOCKED CLEANUP_BLOCKED:"), foreign.stderr)
        self.assertTrue(lease.exists())

    def test_dirty_primary_checkout_stays_a_guardrail(self) -> None:
        self._stage_ready_task_with_origin(local_ahead=True)
        (self.project / "foreign.txt").write_text("dirt\n", encoding="utf-8")
        result = self.run_cli(*self._stage_args())
        self.assertTrue(result.stderr.startswith("BLOCKED PRIMARY_DIRTY:"), result.stderr)
        self.assertEqual((self.project / "foreign.txt").read_text(), "dirt\n")


def _stage_kill_test(point: str):
    def test(self: RunRecoveryTest) -> None:
        self.assert_stage_kill_recovers(point)
    return test


for _point in STAGE_KILL_POINTS:
    setattr(RunRecoveryTest, f"test_stage_killed_at_{_point}_recovers_the_owned_lease", _stage_kill_test(_point))


RESIDUE_BOUNDARIES = ("before_residue_intent", "after_residue_intent", "before_residue_unlink",
                      "after_residue_unlink", "before_residue_result", "after_residue_result")


def _residue_kill_test(point: str):
    def test(self: RunRecoveryTest) -> None:
        self.assert_residue_clear_converges(point)
    return test


for _point in RESIDUE_BOUNDARIES:
    setattr(RunRecoveryTest, f"test_residue_clear_killed_at_{_point}_converges", _residue_kill_test(_point))


if __name__ == "__main__":
    unittest.main()


class PolicyRecoveryTest(unittest.TestCase):
    """Pure policy resolution never creates approval, state or configuration."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project with spaces"
        self.project.mkdir()
        write_project_config(self.project)

    def tearDown(self):
        self.temporary.cleanup()

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes()
                for p in self.project.rglob("*") if p.is_file()}

    def test_missing_policy_is_a_stable_authority_negative_without_writes(self):
        from cardine.tasks.contract import profile_digest
        before = self.snapshot()
        messages = []
        for _ in range(2):
            with self.assertRaises(CardineStop) as caught:
                profile_digest(self.project)
            self.assertEqual(caught.exception.code, "UNDECLARED_VALIDATION_COMMANDS")
            messages.append(str(caught.exception))
            self.assertIn("cause: execution-profile", messages[-1])
            self.assertEqual(before, self.snapshot())
        self.assertEqual(*messages)

    def test_installed_policy_resolves_without_installation_and_changes_invalidate_digest(self):
        from cardine.tasks.contract import profile_digest
        validation = {"commands": {"check": "python3 check.py"}, "baseline": ["check"],
                      "candidate": {name: ["check"] for name in ("REUSE", "BOUNDED", "FULL")}}
        write_project_config(self.project, validation=validation)
        before = self.snapshot()
        first = profile_digest(self.project)
        self.assertEqual(first, profile_digest(self.project))
        self.assertEqual(before, self.snapshot())
        validation["commands"]["check"] = "python3 changed.py"
        write_project_config(self.project, validation=validation)
        self.assertNotEqual(first, profile_digest(self.project))
        # Explicitly declaring no commands is still a policy choice, not a
        # missing source that needs a person's decision.
        empty = {"commands": {}, "baseline": [],
                 "candidate": {name: [] for name in ("REUSE", "BOUNDED", "FULL")}}
        write_project_config(self.project, validation=empty)
        before = self.snapshot()
        explicit_none = profile_digest(self.project)
        self.assertEqual(explicit_none, profile_digest(self.project))
        self.assertEqual(before, self.snapshot())
        self.assertNotEqual(first, explicit_none)
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("policy access denied")):
            with self.assertRaises(PermissionError):
                profile_digest(self.project)
        self.assertEqual(before, self.snapshot())
        config = self.project / ".cardine/project.json"
        config.write_text('{"version": 1, "preset": "foreign"}')
        before = self.snapshot()
        from cardine.shared.errors import CardineError
        for _ in range(2):
            with self.assertRaises(CardineError):
                profile_digest(self.project)
            self.assertEqual(before, self.snapshot())

    def test_pending_dependencies_keep_failed_results_as_guardrails(self):
        from cardine.tasks.preflight import check_dependencies
        from cardine.tasks import contract_snapshot, state
        from cardine.shared import git
        from cardine.templates import mode
        before = self.snapshot()
        with mock.patch.object(contract_snapshot, "read_human_contract", return_value={"dependencies": ["dep"]}), \
             mock.patch.object(git, "canonical_project_root", return_value=self.project), \
             mock.patch.object(git, "_run_git", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as git_run, \
             mock.patch.object(mode, "detect_mode", return_value="lean-delivery"), \
             mock.patch.object(state, "dependency_satisfied", return_value=False), \
             mock.patch.object(state, "read_task_state") as reader:
            for status, code in (("queued", "DEPENDENCY_PENDING"), ("in_progress", "DEPENDENCY_PENDING"),
                                 ("in_review", "DEPENDENCY_PENDING"), ("cancelled", "TASK_STATUS_REJECTED"),
                                 ("done", "TASK_STATUS_REJECTED")):
                reader.return_value = {"status": status}
                messages = []
                for _ in range(2):
                    with self.assertRaises(CardineStop) as caught:
                        check_dependencies(self.project, "task", "")
                    self.assertEqual(caught.exception.code, code)
                    messages.append(str(caught.exception))
                    self.assertEqual(before, self.snapshot())
                self.assertEqual(*messages)

            for listed_code, listed_paths, expected in (
                (0, "", "DEPENDENCY_PENDING"),
                (128, "", "TASK_STATUS_REJECTED"),
                (0, ".cardine/tasks/dep.json\n", "TASK_STATUS_REJECTED"),
            ):
                for _ in range(2):
                    git_run.side_effect = [
                        subprocess.CompletedProcess([], 128, "", "object read failed"),
                        subprocess.CompletedProcess([], listed_code, listed_paths, ""),
                    ]
                    with self.assertRaises(CardineStop) as caught:
                        check_dependencies(self.project, "task", "")
                    self.assertEqual(caught.exception.code, expected)
                    self.assertEqual(before, self.snapshot())
