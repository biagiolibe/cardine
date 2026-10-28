"""Framework CLI regression tests for worktree lifecycle."""

from __future__ import annotations

from cardine_cli_support import CLI, ROOT
import importlib
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION, write_state, freeze_record, seal_state
from unittest import mock
from cardine import cli as owner_cli
from cardine.tasks import transitions as owner_tasks_transitions
from cardine.stops import registry as stops_registry
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.stops import render as owner_stops_render
from cardine.worktree import storage as owner_worktree_storage
import cardine_cli
from stop_recovery_support import run_recovery, resume_from
from fixture_restore_support import RestorableFixture


def build_lifecycle_fixture(directory):
    test = WorktreeLifecycleCliTest()
    with mock.patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(directory / 'worktrees'),
                                     'PYTHONPATH': str(ROOT / 'src')}):
        test._build_fixture(directory)
    return {}


LIFECYCLE_FIXTURE = RestorableFixture('worktree-lifecycle', build_lifecycle_fixture)


class WorktreeLifecycleCliTest(unittest.TestCase):
    def setUp(self, *, seed: bool = True) -> None:
        if seed:
            self.root, _ = LIFECYCLE_FIXTURE.restore()
        else:
            # The walkthrough intentionally starts without a task or a commit.
            self.temporary = tempfile.TemporaryDirectory()
            self.addCleanup(self.temporary.cleanup)
            self.root = Path(self.temporary.name)
            self._build_fixture(self.root, seed=False)
        self.project = self.root / "project"
        self.worktree_root = self.root / "worktrees"
        self.environment = mock.patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.worktree_root),
                                                        'PYTHONPATH': str(ROOT / 'src')})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def _build_fixture(self, directory, *, seed=True):
        self.root = directory
        self.project = self.root / "project"
        self.project.mkdir()
        write_project_config(self.project, validation=VALIDATION)
        subprocess.run(["git", "init", "-b", "main"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Cardine Test"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.email", "cardine@example.invalid"], cwd=self.project, check=True)
        # Fixture commits must not leave detached Git maintenance running during snapshots.
        subprocess.run(["git", "config", "maintenance.auto", "false"], cwd=self.project, check=True)
        self.worktree_root = self.root / "worktrees"
        self.worktree_root.mkdir()
        if not seed:
            return
        (self.project / "tasks").mkdir()
        (self.project / "tasks/056-lifecycle.md").write_text(
            contract_record("056").replace("Change the documented deliverable only.", "- `**`"), encoding="utf-8"
        )
        (self.project / "tasks/QUEUE.md").write_text(
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n",
            encoding="utf-8",
        )
        write_state(self.project, "056", "in_progress", review_required=False)
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.project, check=True, capture_output=True)

    def git(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *arguments], cwd=cwd or self.project, text=True, capture_output=True, check=True)

    def measure(self, worktree: Path) -> None:
        """Deliver and validate through the real engine; landing reads only that attempt."""
        from worktree_support import measure_task
        measure_task(self, worktree, "056")

    def commit_abort_receipts(self):
        identity = owner_tasks_identity.resolve_task_identity(self.project, '056', 'existing')
        metadata = owner_worktree_storage._lifecycle_paths(self.project, identity)[0]
        worker = Path(json.loads(metadata.read_bytes())['worktree'])
        subprocess.run(['git', 'add', '--', '.cardine/tasks/056.json'], cwd=worker, check=True)
        subprocess.run(['git', 'commit', '-m', 'Record owned abort receipts'], cwd=worker,
                       check=True, capture_output=True)

    def create_bare_origin(self) -> Path:
        remote = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=self.project, check=True)
        return remote

    def tearDown(self) -> None:
        self.environment.stop()

    def run_cli(self, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "tests/control_cli.py"), "--framework-root", str(ROOT), *arguments],
            cwd=cwd or self.project,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_path_alias_is_equivalent_and_deprecated(self) -> None:
        current = self.run_cli(
            "worktree", "path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root),
        )
        alias = self.run_cli(
            "codex", "worktree-path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root),
        )
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertEqual(alias.returncode, 0, alias.stderr)
        self.assertEqual(current.stdout, alias.stdout)
        self.assertIn("DEPRECATED", alias.stderr)

    def test_worktree_and_codex_commands_accept_the_resolved_root_without_an_option(self) -> None:
        environment = {**os.environ, "CARDINE_WORKTREE_ROOT": str(self.worktree_root)}
        worktree = subprocess.run(
            [sys.executable, str(CLI), "worktree", "path", "056", "--project", str(self.project)],
            cwd=self.project,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        codex = subprocess.run(
            [sys.executable, str(CLI), "codex", "worktree-path", "056", "--project", str(self.project)],
            cwd=self.project,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(worktree.returncode, 0, worktree.stderr)
        self.assertEqual(codex.returncode, 0, codex.stderr)
        self.assertEqual(worktree.stdout, codex.stdout)

    def test_prepare_and_worker_check_json_exit_codes(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        contract = json.loads(prepared.stdout)
        wrong = self.run_cli(
            "worktree", "check", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(wrong.returncode, 2)
        self.assertIn("wrong-worktree", json.loads(wrong.stdout)["errors"])
        errors = ", ".join(json.loads(wrong.stdout)["errors"])
        self.assertEqual(
            wrong.stderr.strip(),
            f"BLOCKED WRONG_WORKTREE: worktree check reported: {errors}; resume: cardine worktree prepare 056 "
            f"--project {self.project.resolve()} --format json",
        )
        recovery = run_recovery(resume_from(wrong.stderr), self.project, self.worktree_root)
        self.assertEqual(recovery.returncode, 0, recovery.stderr)
        self.assertEqual(json.loads(recovery.stdout)["worktree"], contract["worktree"])
        correct = self.run_cli(
            "worktree", "check", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
            cwd=Path(contract["worktree"]),
        )
        self.assertEqual(correct.returncode, 0, correct.stderr)
        self.assertEqual(json.loads(correct.stdout)["status"], "ready")

    def test_prepare_records_and_preserves_started_at_without_fabricating_legacy_timing(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        first = json.loads(prepared.stdout)
        self.assertTrue(first["created"])
        self.assertRegex(first["started_at"], r"^\d{4}-\d\d-\d\dT.*Z$")
        repeated = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        repeated_contract = json.loads(repeated.stdout)
        self.assertFalse(repeated_contract["created"])
        self.assertEqual(repeated_contract["worktree"], first["worktree"])
        self.assertEqual(repeated_contract["started_at"], first["started_at"])
        worktrees = subprocess.run(
            ("git", "worktree", "list", "--porcelain"), cwd=self.project,
            text=True, capture_output=True, check=True,
        ).stdout
        self.assertEqual(worktrees.count("\nworktree ") + worktrees.startswith("worktree "), 2)

        identity = owner_tasks_identity.resolve_task_identity(self.project, "056", "existing")
        state_path, _lease, _integration = owner_worktree_storage._lifecycle_paths(self.project, identity)
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        legacy.pop("started_at")
        state_path.write_text(json.dumps(legacy), encoding="utf-8")
        preserved = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(preserved.returncode, 2, preserved.stderr)
        self.assertIn('worktree preparation receipt', preserved.stderr)
        self.assertEqual(json.loads(state_path.read_text()), legacy)

    def test_handoff_worktree_value_is_root_relative_and_legacy_absolute_is_accepted(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        contract = json.loads(prepared.stdout)
        relative = contract["handoff_worktree"]
        self.assertFalse(Path(relative).is_absolute())
        self.assertEqual(self.worktree_root.resolve() / relative, Path(contract["worktree"]))
        printed = self.run_cli(
            "worktree", "path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(json.loads(printed.stdout)["handoff_worktree"], relative)
        handoff = Path(contract["handoff"])
        handoff.parent.mkdir(parents=True, exist_ok=True)

        for value, expected in (
            (relative, True),
            (contract["worktree"], True),
            ("elsewhere/task-056", True),
        ):
            with self.subTest(value=value):
                handoff.write_text(f"- Worktree: `{value}`\n", encoding="utf-8")
                result = self.run_cli(
                    "worktree", "check", "056", "--project", str(self.project),
                    "--worktree-root", str(self.worktree_root), "--format", "json",
                    cwd=Path(contract["worktree"]),
                )
                report = json.loads(result.stdout)
                self.assertEqual(report["handoff_worktree"], relative)
                self.assertNotIn("handoff_consistent", report)
                self.assertEqual(result.returncode, 0, result.stdout)

    def test_usage_errors_exit_64(self) -> None:
        result = self.run_cli("worktree", "prepare", "056")
        self.assertEqual(result.returncode, 64)

    def test_closure_status_covers_lifecycle_states_without_mutation(self) -> None:
        def snapshot(*roots: Path) -> dict[str, str]:
            return {
                f"{root.name}/{path.relative_to(root)}": hashlib.sha256(path.read_bytes()).hexdigest()
                for root in roots
                for path in root.rglob("*")
                if path.is_file()
            }

        def status(
            expected_step: str, expected_reason: str | None, *, text: bool = False,
            resume_contains: str | None = None,
        ) -> None:
            before = snapshot(self.project, worktree)
            result = self.run_cli(
                "worktree", "closure-status", "056", "--project", str(self.project),
                "--worktree-root", str(self.worktree_root),
                *( () if text else ("--format", "json") ),
            )
            self.assertEqual(snapshot(self.project, worktree), before)
            self.assertEqual(result.returncode, 2 if expected_reason and stops_registry.load_stop_registry()[expected_reason]["human_decision"] else 0, result.stderr)
            if text:
                self.assertEqual(
                    result.stdout.strip(),
                    f"BLOCKED {expected_reason}: the task worktree, branch, or lifecycle state is missing or does not "
                    f"match; resume: cardine worktree prepare 056 --project {self.project.resolve()} --format json",
                )
                return
            report = json.loads(result.stdout)
            self.assertEqual(report["step"], expected_step)
            self.assertEqual(report["stop_reason"], expected_reason)
            self.assertIn("resume", report)
            if resume_contains is not None:
                self.assertIn(resume_contains, report["resume"])

        worktree = self.worktree_root / "unused"
        status("C4", "WRONG_WORKTREE", text=True)

        remote = self.root / "origin.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        (self.project / "tasks/handoffs").mkdir()
        (self.project / "tasks/handoffs/056.md").write_text("# Completion Report — 056\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "handoff"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=self.project, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.project, check=True, capture_output=True)

        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        worktree = Path(json.loads(prepared.stdout)["worktree"])
        status("C1", "ACCEPTANCE_UNMET")

        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        status("C5", "EVIDENCE_INCOMPLETE")

        identity = owner_tasks_identity.resolve_task_identity(self.project, "056", "existing")
        state, lease, integration = owner_worktree_storage._lifecycle_paths(self.project, identity)
        # A declared evidence file is never read: only the measured attempt moves C5 to C6.
        forged = state.with_suffix(".evidence.json")
        forged.write_text(json.dumps({"accepted": True, "validation_passed": True}), encoding="utf-8")
        status("C5", "EVIDENCE_INCOMPLETE")
        forged.unlink()
        self.measure(worktree)
        status("C6", None)
        legacy = self.project / ".cardine/budget.json"
        legacy.parent.mkdir(exist_ok=True)
        legacy.write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "add", ".cardine/budget.json"], cwd=self.project, check=True)
        status("C6", "PRIMARY_DIRTY", resume_contains="primary checkout is dirty")
        subprocess.run(["git", "reset", "HEAD", "--", ".cardine/budget.json"], cwd=self.project, check=True)
        legacy.unlink()
        lease.write_text(json.dumps({"task_id": identity.canonical_id}), encoding="utf-8")
        integration.write_text(json.dumps({"task_id": identity.canonical_id}), encoding="utf-8")
        status("C7", None)
        integration.unlink()
        status("C6", "LEASE_HELD")
        lease.unlink()

        subprocess.run(["git", "merge", "--no-ff", "task-056", "-m", "integrate"], cwd=self.project, check=True)
        write_state(self.project, "056", "done")
        subprocess.run(["git", "add", ".cardine/tasks/056.json"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "Record fixture landing"], cwd=self.project, check=True, capture_output=True)
        status("C9", "PUSH_PENDING")
        subprocess.run(["git", "push", "origin", "main"], cwd=self.project, check=True, capture_output=True)
        status("C10", None)

        cleaned = self.run_cli(
            "worktree", "cleanup", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        worktree = self.worktree_root / "removed"
        status("C10", None)

    def _stage_ready_task_with_origin(self, local_ahead: bool = False, *, measured: bool = True) -> Path:
        """Prepare and measure a completed task branch; returns its worktree."""
        self.create_bare_origin()
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.project, check=True, capture_output=True)
        if local_ahead:
            (self.project / "unpushed.txt").write_text("unpushed\n", encoding="utf-8")
            (self.project / ".cardine").mkdir(exist_ok=True)
            (self.project / ".cardine/candidate-validation.json").write_text(
                '{"version": 1, "state": "none"}\n', encoding="utf-8"
            )
            write_project_config(self.project, "lean", validation=VALIDATION)
            seal_state(self.project, "056")  # Fixture authority for the policy this commit changes.
            (self.project / "tasks").mkdir(exist_ok=True)
            (self.project / "tasks/QUEUE.md").write_text(
                "| Status | ID | Title | Priority | Depends | Task |\n"
                "|---|---|---|---|---|---|\n"
                "| `[ ]` | 056 | Fixture task | P2 | — | [056](056-fixture.md) |\n",
                encoding="utf-8",
            )
            (self.project / "PROJECT_PLAN.md").write_text("- `[ ]` 056 — Fixture task.\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "unpushed.txt", ".cardine/candidate-validation.json", ".cardine/project.json", ".cardine/tasks/056.json", ".cardine/receipt-authority.json",
                 "tasks/QUEUE.md", "PROJECT_PLAN.md"],
                cwd=self.project, check=True,
            )
            subprocess.run(["git", "commit", "-m", "unpushed governance commit"], cwd=self.project, check=True, capture_output=True)
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        worktree = Path(json.loads(prepared.stdout)["worktree"])
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        if measured:
            self.measure(worktree)
        return worktree

    def test_integrate_stage_blocks_when_fetched_origin_main_is_ahead(self) -> None:
        renamed = self.root / "project with spaces"
        self.project.rename(renamed)
        self.project = renamed
        worktree = self._stage_ready_task_with_origin(local_ahead=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=self.project, check=True, capture_output=True)
        remote = self.root / "origin.git"
        clone = self.root / "origin-writer"
        subprocess.run(["git", "clone", "--branch", "main", str(remote), str(clone)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Cardine Test"], cwd=clone, check=True)
        subprocess.run(["git", "config", "user.email", "cardine@example.invalid"], cwd=clone, check=True)
        (clone / "upstream.txt").write_text("upstream\n", encoding="utf-8")
        subprocess.run(["git", "add", "upstream.txt"], cwd=clone, check=True)
        subprocess.run(["git", "commit", "-m", "upstream advance"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "fetch", "origin"], cwd=self.project, check=True, capture_output=True)

        result = self.run_cli(
            "worktree", "integrate", "stage", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root),
            "--format", "json",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("local main is behind the already fetched origin/main", result.stderr)
        local = subprocess.run(
            ["git", "rev-parse", "--short=12", "main"], cwd=self.project, check=True, capture_output=True, text=True
        ).stdout.strip()
        fetched = subprocess.run(
            ["git", "rev-parse", "--short=12", "refs/remotes/origin/main"],
            cwd=self.project, check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(
            result.stderr.strip(),
            "NEXT MAIN_BEHIND_ORIGIN: local main is behind the already fetched origin/main "
            f"(local main {local}, origin/main {fetched}); resume: "
            f"git -C {shlex.quote(str(self.project.resolve()))} merge --ff-only origin/main",
        )

        recovery = run_recovery(resume_from(result.stderr), self.project, self.worktree_root)
        self.assertEqual(recovery.returncode, 0, recovery.stderr)
        staged = self.run_cli(*self._stage_args())
        self.assertEqual(staged.returncode, 0, staged.stderr)

    def _stage_args(self) -> tuple[str, ...]:
        return (
            "worktree", "integrate", "stage", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )

    def test_stop_helper_formats_registered_codes_and_rejects_others(self) -> None:
        self.assertEqual(
            owner_stops_render.format_stop("PUSH_PENDING", "main is ahead"),
            "NEXT PUSH_PENDING: main is ahead; resume: git push origin main",
        )
        with self.assertRaises(shared_errors.InternalStopError):
            owner_stops_render.format_stop("NOT_A_REGISTERED_CODE", "detail", resume="x")
        with self.assertRaises(shared_errors.InternalStopError):
            owner_stops_render.stop_resume("WRONG_WORKTREE", task_id="056")

    def test_stop_registry_covers_closure_codes_and_names_real_tests(self) -> None:
        registry = stops_registry.load_stop_registry()
        closure = (
            "ACCEPTANCE_UNMET", "VALIDATION_FAILED", "VALIDATION_RETRY_LIMIT", "WRONG_WORKTREE", "EVIDENCE_INCOMPLETE",
            "PRIMARY_DIRTY", "MAIN_BEHIND_ORIGIN", "LEASE_HELD", "INTEGRATION_CONFLICT", "GIT_OPERATION_FAILED",
            "CANDIDATE_VALIDATION_FAILED", "EVIDENCE_MISMATCH", "PUSH_PENDING", "PUSH_REJECTED", "CLEANUP_BLOCKED",
            "UNDECLARED_VALIDATION_COMMANDS", "STALE_WORKTREE_BASE", "REVIEW_NOT_APPROVED",
            "WORKTREE_RELOCATE", "LEASE_INTERRUPTED", "CLEANUP_PARTIAL", "TASK_STEP_PENDING", "DEPENDENCY_PENDING",
        )
        gates = (
            "EXECUTION_CONTRACT_UNRESOLVED", "VALIDATION_ENTRY_FORMAT",
            "TASK_RECORD_INCOMPLETE", "TASK_STATUS_REJECTED",
            "TASK_STATE_MISSING", "TASK_STATE_INVALID", "TASK_STATE_INTERRUPTED",
        )
        remaining = (
            "COMMAND_REFUSED", "OS_ACCESS_FAILED", "VALIDATION_ID_UNDECLARED",
            "HOST_IMPACT_DECLARATION_INVALID", "UPGRADE_BLOCKED",
            "RULE_CONFLICT", "SCOPE_CHANGE_REQUIRED",
            "REVIEW_LOOP_EXHAUSTED", "SELF_UPDATE_PLUGIN_CACHE", "SELF_UPDATE_DIRTY",
            "SELF_UPDATE_BRANCH", "SELF_UPDATE_TARGET", "SELF_UPDATE_VERIFY",
            "SELF_UPDATE_INPUT_INVALID", "OS_PATH_MISSING", "OS_PATH_BUSY", "UPGRADE_OUTPUT_PENDING",
        )
        self.assertEqual(set(registry), set(closure) | set(gates) | set(remaining))
        self.assertEqual(
            {code for code, entry in registry.items() if entry["class"] == "judgment"},
            {
                "ACCEPTANCE_UNMET", "RULE_CONFLICT",
                "SCOPE_CHANGE_REQUIRED", "VALIDATION_RETRY_LIMIT",
            },
        )
        self.assertEqual(registry["PUSH_PENDING"]["kind"], "status")
        for code, entry in registry.items():
            with self.subTest(code=code):
                if entry["class"] == "tool" and entry["kind"] == "stop":
                    module_name, class_name, method = str(entry["test"]).rsplit(".", 2)
                    owner = getattr(importlib.import_module(module_name), class_name)
                    self.assertTrue(callable(getattr(owner, method, None)), entry["test"])

    def test_stop_registry_matches_its_schema_shape(self) -> None:
        schema = json.loads((ROOT / "schemas/stop-codes-v1.schema.json").read_text(encoding="utf-8"))
        item = schema["properties"]["stops"]["items"]
        for code, entry in stops_registry.load_stop_registry().items():
            with self.subTest(code=code):
                self.assertLessEqual(set(entry), set(item["properties"]))
                self.assertTrue(set(item["required"]) <= set(entry))
                self.assertIn(entry["class"], item["properties"]["class"]["enum"])
                self.assertIn(entry["kind"], item["properties"]["kind"]["enum"])
                self.assertTrue(set(entry["workflows"]) <= set(item["properties"]["workflows"]["items"]["enum"]))

    def test_runtime_registry_rejects_invalid_resolution(self) -> None:
        path = self.root / "capabilities/stop-codes-v1.json"
        path.parent.mkdir()
        entry = dict(stops_registry.load_stop_registry()["STALE_WORKTREE_BASE"])
        for resolution, human in ((None, False), ("unknown", False), ("recoverable", True), ("failing-work", True)):
            with self.subTest(resolution=resolution, human=human):
                candidate = {**entry, "human_decision": human}
                if resolution is None:
                    candidate.pop("resolution")
                else:
                    candidate["resolution"] = resolution
                path.write_text(json.dumps({"version": 1, "stops": [candidate]}), encoding="utf-8")
                with mock.patch.object(stops_registry, "SCRIPTS_ROOT", self.root / "scripts"), \
                     mock.patch.object(stops_registry, "_stop_registry_cache", None), \
                     self.assertRaises(shared_errors.InternalStopError):
                    stops_registry.load_stop_registry()

    def test_closure_status_text_reports_incomplete_evidence_through_the_registry(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        worktree = Path(json.loads(prepared.stdout)["worktree"])
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        result = self.run_cli(
            "worktree", "closure-status", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout.strip(),
            "NEXT EVIDENCE_INCOMPLETE: machine evidence for the validated task commit is missing or "
            f"incomplete; resume: cardine run 056 --project {shlex.quote(str(self.project.resolve()))}",
        )

    def test_integrate_stage_reports_primary_dirty_through_the_registry(self) -> None:
        worktree = self._stage_ready_task_with_origin(local_ahead=True)
        (self.project / "stray.txt").write_text("stray\n", encoding="utf-8")
        result = self.run_cli(*self._stage_args())
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED PRIMARY_DIRTY: primary checkout must be clean; resume: clean the primary checkout and run "
            "integration stage",
        )

    def test_integrate_stage_reports_a_held_lease_through_the_registry(self) -> None:
        worktree = self._stage_ready_task_with_origin(local_ahead=True)
        identity = owner_tasks_identity.resolve_task_identity(self.project, "056", "existing")
        _state, lease, _integration = owner_worktree_storage._lifecycle_paths(self.project, identity)
        lease.write_text(json.dumps({"task_id": "056"}), encoding="utf-8")
        result = self.run_cli(*self._stage_args())
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            f"BLOCKED LEASE_HELD: an interrupted integration lease is retained at {lease}; use "
            "`cardine worktree integrate abort`; resume: cardine worktree integrate abort 056 "
            f"--project {self.project.resolve()} --format json",
        )

        original = lease.read_bytes()
        recovered = run_recovery(resume_from(result.stderr), self.project, self.worktree_root,
                                 control_host=True)
        self.assertEqual(recovered.returncode, 2, recovered.stderr)
        self.assertIn('foreign integration ownership', recovered.stderr)
        self.assertEqual(lease.read_bytes(), original)
        # An explicit fixture operator now supplies the missing issued ownership.
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.project, text=True).strip()
        lease.write_text(json.dumps(dict(version=1, task_id='056', branch=identity.branch_name,
            project=str(self.project.resolve()), main_commit=head)))
        recovered = run_recovery(resume_from(result.stderr), self.project, self.worktree_root,
                                 control_host=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.commit_abort_receipts()
        restaged = self.run_cli(*self._stage_args())
        self.assertEqual(restaged.returncode, 0, restaged.stderr)


    def test_integrate_stage_reports_undeclared_validation_commands_through_the_registry(self) -> None:
        # Receipt-gated preparation rejects unsigned pre-contract inputs before
        # staging. Retain the Internal diagnostic's registered rendering contract.
        from cardine.integration.evidence import undeclared_validation_commands_error
        error = undeclared_validation_commands_error(self.project)
        self.assertEqual(error.code, 'UNDECLARED_VALIDATION_COMMANDS')
        self.assertIn('Proposed declaration:', str(error))
        self.assertIn('resume: declare the missing execution or candidate validation policy', str(error))

    def test_integrate_stage_refuses_unsigned_precontract_state(self) -> None:
        path = self.project / ".cardine/tasks/056.json"
        state = json.loads(path.read_text())
        del state["contract"]
        path.write_text(json.dumps(state))
        before = path.read_bytes()
        result = self.run_cli('worktree', 'prepare', '056', '--project', str(self.project),
                              '--worktree-root', str(self.worktree_root), '--format', 'json')
        self.assertEqual(result.returncode, 0)
        self.assertIn('TASK_STATE_MISSING', result.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_integrate_stage_reports_an_integration_conflict_through_the_registry(self) -> None:
        worktree = self._stage_ready_task_with_origin(local_ahead=True)
        (self.project / "implementation.txt").write_text("main side\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "conflicting main change"], cwd=self.project, check=True, capture_output=True)
        result = self.run_cli(*self._stage_args())
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED INTEGRATION_CONFLICT: textual integration conflict; resume: "
            "the developer resolves the conflict on the task branch, then rerun cardine "
            f"worktree integrate stage 056 --project {self.project.resolve()} "
            "--format json",
        )

    def test_integrate_finalize_reports_an_evidence_mismatch_through_the_registry(self) -> None:
        worktree = self._stage_ready_task_with_origin(local_ahead=True)
        staged = self.run_cli(*self._stage_args())
        self.assertEqual(staged.returncode, 0, staged.stderr)
        validation = self.root / "candidate-validation-evidence.json"
        validation.write_text(json.dumps({"passed": False}), encoding="utf-8")
        result = self.run_cli(
            "worktree", "integrate", "finalize", "056", "--project", str(self.project),
            "--evidence", str(validation), "--format", "json",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stderr.strip(),
            "NEXT EVIDENCE_MISMATCH: no current measured candidate validation; resume: "
            f"cardine worktree integrate abort 056 --project {self.project.resolve()} --format json",
        )

        recovered = run_recovery(resume_from(result.stderr), self.project, self.worktree_root, control_host=True)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.commit_abort_receipts()
        restaged = self.run_cli(*self._stage_args())
        self.assertEqual(restaged.returncode, 0, restaged.stderr)

    def test_cleanup_reports_blocked_cleanup_through_the_registry(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        worktree = Path(json.loads(prepared.stdout)["worktree"])
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        result = self.run_cli(
            "worktree", "cleanup", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            result.stderr.strip(),
            "BLOCKED CLEANUP_BLOCKED: task commit is not integrated into main; resume: "
            + shlex.join(['cardine', 'worktree', 'cleanup', '056', '--project', str(self.project.resolve()),
                          '--worktree-root', str(self.worktree_root.resolve()), '--format', 'json']),
        )

    def test_integrate_stage_accepts_local_main_ahead_of_fetched_origin_main(self) -> None:
        worktree = self._stage_ready_task_with_origin(local_ahead=True)
        result = self.run_cli(
            "worktree", "integrate", "stage", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root),
            "--format", "json",
        )
        self.assertNotIn("MAIN_BEHIND_ORIGIN", result.stderr + result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)

    def _advance_ready_task(self, candidate_command="scripts/check_repository.py") -> Path:
        """A completed task branch with origin and a handoff but no measured validation."""
        (self.project / "tasks/handoffs").mkdir()
        (self.project / "tasks/handoffs/056.md").write_text("# Completion Report — 056\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "handoff"], cwd=self.project, check=True, capture_output=True)
        self._stage_ready_task_with_origin(local_ahead=True, measured=False)
        worktree = Path(json.loads(self.run_cli(
            "worktree", "path", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        ).stdout)["path"])
        # The task's own validation command really runs when the attempt is measured.
        check = worktree / "scripts/check_repository.py"
        check.parent.mkdir(exist_ok=True)
        check.write_text("#!/usr/bin/env python3\nraise SystemExit(0)\n", encoding="utf-8")
        check.chmod(0o755)
        # Freeze the gate this fixture exercises before creating its contract.
        record = worktree / "tasks/056-lifecycle.md"
        record.write_text(record.read_text().replace("python3 -c 'pass'", candidate_command))
        write_state(worktree, "056")
        freeze_record(worktree, "056", record)
        owner_tasks_transitions.transition_task_state(worktree, "056", "in_progress")
        subprocess.run(["git", "add", "."], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "record terminal state"], cwd=worktree, check=True, capture_output=True)
        (self.project / ".cardine/candidate-validation.json").write_text(
            json.dumps({"version": 1, "state": "declared", "outcomes": {
                "REUSE": ["scripts/check_repository.py"],
                "BOUNDED": ["scripts/check_repository.py"],
                "FULL": ["scripts/check_repository.py", "unittest discover"],
            }}), encoding="utf-8",
        )
        subprocess.run(["git", "add", ".cardine/candidate-validation.json"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "declare"], cwd=self.project, check=True, capture_output=True)
        return worktree

    def _advance(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "worktree", "advance", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), *extra, "--format", "json",
        )

    def _journal(self) -> list[dict[str, object]]:
        journal = self.project / ".git/cardine-journal.jsonl"
        return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]

    def test_advance_runs_to_candidate_validation_and_reruns_without_repeating(self) -> None:
        worktree = self._advance_ready_task()
        waiting = self._advance()
        self.assertEqual(waiting.returncode, 0, waiting.stderr)
        self.assertEqual(json.loads(waiting.stdout)['step'], 'C5')
        self.measure(worktree)
        staged = self._advance()
        self.assertEqual(staged.returncode, 0, staged.stderr)
        report = json.loads(staged.stdout)
        self.assertEqual((report['step'], report['performed']), ('C7', ['C6']))
        self.assertEqual(report['commands'], ['git diff --check', 'scripts/check_repository.py'])
        finalized = self._advance()
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        self.assertEqual(json.loads(finalized.stdout)['action_required'], 'push')
        self.assertEqual([line['command'] for line in self._journal()].count('integrate stage'), 1)
        self.assertEqual([line['command'] for line in self._journal()].count('integrate finalize'), 1)


    def test_advance_complete_commands_run_unchanged_and_finalize(self) -> None:
        worktree = self._advance_ready_task(candidate_command="python3 scripts/check_repository.py")
        self.measure(worktree)
        staged = self._advance()
        self.assertEqual(staged.returncode, 0, staged.stderr)
        self.assertEqual(json.loads(staged.stdout)['commands'], ['git diff --check', 'python3 scripts/check_repository.py'])
        finalized = self._advance()
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        self.assertEqual(json.loads(finalized.stdout)['action_required'], 'push')
        from cardine.integration.candidate import operation_path, locations_for
        from cardine.lifecycle import receipts
        measured = receipts._load_intent(operation_path(locations_for('056', self.project)))['progress']
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain'], cwd=worktree, text=True), '')
        self.assertEqual([r['command'] for r in measured['runs'][0]], ['git diff --check', 'python3 scripts/check_repository.py'])
        self.assertTrue(all(r['exitStatus'] == 0 for r in measured['runs'][0]))


    def test_advance_resumes_after_each_mechanical_step_and_reaches_cleanup(self) -> None:
        worktree = self._advance_ready_task()
        self.measure(worktree)
        reported = self.run_cli(
            "worktree", "evidence", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json", cwd=worktree,
        )
        self.assertEqual(reported.returncode, 0, reported.stderr)
        self.assertTrue(json.loads(reported.stdout)["validation_passed"])
        staged = json.loads(self._advance().stdout)
        self.assertEqual((staged["step"], staged["performed"]), ("C7", ["C6"]))

        identity = owner_tasks_identity.resolve_task_identity(self.project, "056", "existing")
        _state, lease, integration = owner_worktree_storage._lifecycle_paths(self.project, identity)
        subprocess.run(["git", "merge", "--abort"], cwd=self.project, check=True)
        lease.unlink()
        integration.unlink()
        subprocess.run(["git", "merge", "--no-ff", "task-056", "-m", "integrate"], cwd=self.project, check=True, capture_output=True)
        write_state(self.project, "056", "done")
        subprocess.run(["git", "add", ".cardine/tasks/056.json"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "Record fixture landing"], cwd=self.project, check=True, capture_output=True)
        push = json.loads(self._advance().stdout)
        self.assertEqual(
            (push["step"], push["action_required"], push["commands"], push["stop_code"]),
            ("C9", "push", ["git push origin main"], "PUSH_PENDING"),
        )
        self.assertEqual(push["performed"], [])
        subprocess.run(["git", "push", "origin", "main"], cwd=self.project, check=True, capture_output=True)

        done = self._advance()
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual((report["step"], report["action_required"], report["performed"]), ("C10", "none", ["C10"]))
        self.assertEqual(self._journal()[-2]["command"], "cleanup")
        again = json.loads(self._advance().stdout)
        self.assertEqual((again["action_required"], again["performed"]), ("none", []))
        self.assertEqual([line["command"] for line in self._journal()].count("cleanup"), 1)

    def test_advance_has_no_declared_result_options_and_stops_without_a_measured_attempt(self) -> None:
        self._advance_ready_task()
        for options in (("--accepted",), ("--validation-command", "check", "--validation-exit-code", "0")):
            with self.subTest(options=options):
                self.assertNotEqual(self._advance(*options).returncode, 0)
        stopped = self._advance()
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        report = json.loads(stopped.stdout)
        self.assertEqual((report["step"], report["action_required"], report["stop_code"], report["performed"]),
                         ("C5", "run-validation", "EVIDENCE_INCOMPLETE", []))
        self.assertEqual(report["resume"], f"cardine run 056 --project {shlex.quote(str(self.project.resolve()))}")
        self.assertFalse(list((self.project / ".git/cardine-worktrees").glob("*.evidence.json")))
        self.assertEqual([line for line in self._journal() if line["result"] == "blocked"], [])

    def test_advance_without_task_commits_asks_for_work(self) -> None:
        prepared = self.run_cli(
            "worktree", "prepare", "056", "--project", str(self.project),
            "--worktree-root", str(self.worktree_root), "--format", "json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        result = self._advance()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["step"], report["action_required"], report["stop_code"]), ("C1", "run-validation", "ACCEPTANCE_UNMET"))

    def test_advance_reports_a_blocked_stage_as_a_stop(self) -> None:
        worktree = self._advance_ready_task()
        self.measure(worktree)
        (self.project / "implementation.txt").write_text("main side\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "conflicting main change"], cwd=self.project, check=True, capture_output=True)
        result = self._advance()
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            (report["step"], report["action_required"], report["stop_code"], report["performed"]),
            ("C6", "human", "INTEGRATION_CONFLICT", []),
        )
        self.assertIn("integrate stage 056", report["resume"])
        self.assertEqual(report["stop_detail"],
                         "textual integration conflict")
        last = self._journal()[-1]
        self.assertEqual((last["command"], last["result"], last["stop_code"]), ("advance", "blocked", "INTEGRATION_CONFLICT"))

    def test_advance_names_the_resume_for_a_stop_the_agent_resolves(self) -> None:
        self._advance_ready_task()
        (self.project / "stray.txt").write_text("stray\n", encoding="utf-8")
        result = self._advance()
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            (report["step"], report["action_required"], report["stop_code"], report["performed"]),
            ("C6", "human", "PRIMARY_DIRTY", []),
        )

    def _staged_at_c7(self) -> None:
        self.measure(self._advance_ready_task())
        staged = json.loads(self._advance().stdout)
        self.assertEqual(staged["step"], "C7", staged)

    def _main_subject(self) -> str:
        return subprocess.run(
            ["git", "log", "-1", "--format=%s"], cwd=self.project, text=True, capture_output=True, check=True
        ).stdout.strip()

    def test_advance_finalizes_from_measured_candidate_and_asks_for_the_push(self) -> None:
        self._staged_at_c7()
        result = self._advance()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            (report["step"], report["action_required"], report["commands"], report["performed"]),
            ("C9", "push", ["git push origin main"], ["C8"]),
        )
        self.assertEqual(self._main_subject(), "Integrate 056")
        self.assertEqual([line["command"] for line in self._journal()].count("integrate finalize"), 1)

    def test_push_pending_recovery_runs_unchanged(self) -> None:
        self._staged_at_c7()
        finalized = self._advance()
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        stopped = self.run_cli("worktree", "closure-status", "056", "--project", str(self.project),
                               "--worktree-root", str(self.worktree_root))
        self.assertIn("PUSH_PENDING", stopped.stdout)
        command = resume_from(stopped.stdout)
        pushed = run_recovery(command, self.project, self.worktree_root)
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        status = self.run_cli("worktree", "closure-status", "056", "--project", str(self.project),
                              "--worktree-root", str(self.worktree_root), "--format", "json")
        self.assertEqual(json.loads(status.stdout)["step"], "C10")

    def test_advance_reruns_after_an_interruption_between_finalize_and_push(self) -> None:
        self._staged_at_c7()
        self._advance()
        rerun = self._advance()
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        report = json.loads(rerun.stdout)
        self.assertEqual((report["step"], report["action_required"], report["performed"]), ("C9", "push", []))
        self.assertEqual([line["command"] for line in self._journal()].count("integrate finalize"), 1)

    def test_advance_preserves_changed_candidate_command_bytes(self) -> None:
        self._staged_at_c7()
        # The real command succeeds on the worker, fails in the primary checkout.
        script = self.project / 'scripts/check_repository.py'
        original = script.read_bytes()
        # Changing candidate bytes cannot be used to simulate a measured result.
        script.write_bytes(original + b'raise SystemExit(7)\n')
        result = self._advance()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report['step'], report['stop_code']), ('C7', 'EVIDENCE_MISMATCH'))
        self.assertTrue((self.project / '.git/MERGE_HEAD').exists())
        self.assertEqual(script.read_bytes(), original + b'raise SystemExit(7)\n')


    def test_advance_rejects_caller_candidate_results_without_finalizing(self) -> None:
        self._staged_at_c7()
        result = self._advance('--candidate-command', 'python3 scripts/check_repository.py', '--candidate-exit-code', '0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unrecognized arguments', result.stderr)
        self.assertTrue((self.project / '.git/MERGE_HEAD').exists())
        self.assertNotIn('integrate finalize', [line['command'] for line in self._journal()])


    def test_advance_reports_a_candidate_tree_that_changed_after_stage(self) -> None:
        self._staged_at_c7()
        (self.project / "late.txt").write_text("late\n", encoding="utf-8")
        subprocess.run(["git", "add", "late.txt"], cwd=self.project, check=True)
        result = self._advance()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual((report["step"], report["stop_code"]), ("C7", "EVIDENCE_MISMATCH"))
        self.assertIn("integrate abort", report["resume"])
        self.assertEqual(report["stop_detail"], "candidate tree or main changed")
        self.assertTrue((self.project / ".git/MERGE_HEAD").exists())
        self.assertEqual(self._journal()[-1]["stop_code"], "EVIDENCE_MISMATCH")

    def test_advance_rejects_unpaired_candidate_results(self) -> None:
        self._staged_at_c7()
        result = self._advance("--candidate-command", "git diff --check")
        self.assertNotEqual(result.returncode, 0)

    def run_console(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(ROOT),
                "console",
                "--project",
                str(self.project),
                *arguments,
            ],
            text=True,
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )

    def test_console_rejects_out_of_range_interval(self) -> None:
        for value in ("0.1", "61"):
            result = self.run_console("--interval", value)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--interval must be between 0.2 and 60", result.stderr)

    def test_console_requires_a_terminal(self) -> None:
        result = self.run_console()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("interactive console requires a terminal", result.stderr)

    def test_console_dispatches_to_framework_console_with_project_and_interval(self) -> None:
        from cardine.console import entry as project_console

        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "cardine",
                    "--framework-root",
                    str(ROOT),
                    "console",
                    "--project",
                    str(self.project),
                    "--interval",
                    "5",
                ],
            ),
            mock.patch.object(sys.stdin, "isatty", return_value=True),
            mock.patch.object(sys.stdout, "isatty", return_value=True),
            mock.patch.object(project_console, "main", return_value=0) as launched,
        ):
            result = owner_cli.main()

        self.assertEqual(result, 0)
        launched.assert_called_once_with(
            ["--project", str(self.project.resolve()), "--interval", "5.0"]
        )
