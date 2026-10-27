"""RE7b: end-to-end audit of the run engine inside the declared trust boundary.

Each class is a data-driven audit over the shipped registry, parser, sources and
the forgery inventory, so a new stop code, command, effect boundary or attack row
fails here until it is classified. The effect-level crash tests stay with their
owning rows; this module proves that none of them is missing.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from cardine import cli as cardine_cli  # noqa: E402
from cardine.lifecycle.engine import render_output, resolve_run, validate_output  # noqa: E402
from cardine.lifecycle.model import RunFacts  # noqa: E402
from cardine.shared.journal import LifecycleJournalEntry  # noqa: E402
from cardine.stops.registry import load_stop_registry  # noqa: E402
from cardine.stops.render import outcome_for_code, stop_resume  # noqa: E402
from stop_recovery_support import run_recovery  # noqa: E402
from task_contract_support import contract_record, seal_state, write_state  # noqa: E402

WEIRD = "/tmp/consumer project ; $(touch SENTINEL) 'q'"
STEPS = ("contract", "worktree", "implementation", "validation", "review", "candidate", "landing")


def has_test(dotted: str) -> bool:
    """True when `tests.<module>.<Class>.<method>` or `<module>.<method>` resolves by import."""
    parts = dotted.removeprefix("tests.").split(".")
    module = importlib.import_module(parts[0])
    if len(parts) == 3:
        owner = getattr(module, parts[1], None)
        return owner is not None and callable(getattr(owner, parts[2], None))
    return any(callable(getattr(value, parts[1], None)) for value in vars(module).values()
               if isinstance(value, type))


class RegistryAuditTest(unittest.TestCase):
    """Every then-current registry entry, not a sample."""

    def test_blocked_exactly_for_guardrails_that_need_a_human(self) -> None:
        for code, entry in load_stop_registry().items():
            with self.subTest(code=code):
                blocked = outcome_for_code(code) == "blocked"
                self.assertEqual(blocked, entry["resolution"] == "guardrail")
                self.assertEqual(blocked, entry["human_decision"])

    def test_every_recoverable_entry_has_an_executable_progress_proof(self) -> None:
        for code, entry in load_stop_registry().items():
            if entry["resolution"] != "recoverable":
                continue
            with self.subTest(code=code):
                self.assertTrue(entry.get("test"), "recoverable entries need a progress proof")
                self.assertTrue(has_test(entry["test"]), entry["test"])

    def test_every_cardine_resume_parses_from_a_metacharacter_project(self) -> None:
        parser = cardine_cli.build_parser()
        checked = 0
        for code, entry in load_stop_registry().items():
            if not entry["resume"].startswith("cardine "):
                continue
            with self.subTest(code=code):
                text = stop_resume(code, task_id="115", project=WEIRD).replace("<STATUS>", "in_progress")
                argv = shlex.split(text)
                self.assertEqual(argv[0], "cardine")
                if "{project}" in entry["resume"]:  # one quoted argument, never shell text
                    self.assertTrue({WEIRD, str(Path(WEIRD).resolve())} & set(argv), argv)
                with mock.patch.object(parser, "exit", side_effect=AssertionError(text)), \
                     mock.patch.object(parser, "error", side_effect=AssertionError(text)):
                    parser.parse_args(argv[1:])
                checked += 1
        self.assertGreater(checked, 10)

    def test_every_stop_event_names_cause_resolution_owner_operation_and_next(self) -> None:
        for code, entry in load_stop_registry().items():
            with self.subTest(code=code):
                journal = LifecycleJournalEntry()
                journal.command = "integrate stage"
                journal.task = "115"
                with mock.patch("cardine.shared.journal.append_journal_line") as append, \
                     mock.patch("cardine.shared.journal._verified_lifecycle_project", return_value=ROOT):
                    journal.stopped(code)
                    journal.write(2 if entry["human_decision"] else 0)
                line = append.call_args.args[1]
                self.assertEqual((line["cause"], line["resolution"], line["operation"], line["next"]),
                                 (entry["summary"], entry["resolution"], "integrate stage", entry["resume"]))
                self.assertEqual(line["owner"], "developer" if entry["human_decision"] else "cardine")
                self.assertEqual(line["result"] == "blocked", entry["human_decision"])


class StepMatrixTest(unittest.TestCase):
    def test_both_presets_and_all_seven_steps_emit_runnable_envelopes(self) -> None:
        parser = cardine_cli.build_parser()
        for preset in ("lean", "governed"):
            facts = RunFacts("115", Path(WEIRD), "queued", review_required=preset == "governed")
            stages = [("contract", {}), ("worktree", {"contract_ready": True}),
                      ("implementation", {"worktree_ready": True, "status": "in_progress"}),
                      ("validation", {"implementation_delivered": True}),
                      ("review" if preset == "governed" else "candidate", {"validation_passed": True}),
                      ("candidate", {"review_approved": True}),
                      ("landing", {"candidate_validated": True})]
            seen = []
            for expected, changes in stages:
                facts = replace(facts, **changes)
                result = resolve_run(facts)
                seen.append(result["step"])
                with self.subTest(preset=preset, step=expected):
                    self.assertEqual(result["step"], expected)
                    validate_output(result)
                    self.assertEqual(render_output(result), render_output(resolve_run(facts)))
                    argv = result["next"]["argv"]
                    self.assertEqual(shlex.split(result["next"]["command"]), argv)
                    self.assertIn(WEIRD, argv)
                    if argv[1:2] == ["review"]:
                        # The reviewer handoff is routed by `main` before argparse, like `run`.
                        self.assertEqual((argv[3], argv[5:]), ("--project", []))
                        self.assertFalse(argv[2].startswith("-") or argv[2] == "verdict")
                        continue
                    with mock.patch.object(parser, "error", side_effect=AssertionError(argv)):
                        parser.parse_args(argv[1:])
            seen = [step for index, step in enumerate(seen) if index == 0 or step != seen[index - 1]]
            self.assertEqual(seen, [step for step in STEPS if preset == "governed" or step != "review"])
            done = resolve_run(replace(facts, status="done", landing_complete=True))
            self.assertEqual((done["outcome"], done["next"]), ("done", None))


class ProjectFixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.worktrees = self.base / "worktrees"
        self.root = self.base / "consumer ; $(touch SENTINEL)"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / ".cardine").mkdir()
        (self.root / ".cardine/project.json").write_text(json.dumps({"version": 1, "preset": "lean"}))
        (self.root / "tasks").mkdir()
        (self.root / "tasks/001.md").write_text(contract_record())
        write_state(self.root)
        self.git("add", ".")
        self.git("commit", "-m", "Fixture")
        seal_state(self.root, "001")
        self.git("add", ".")
        self.git("commit", "-m", "Receipt fixture state")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def tree(self) -> dict[str, bytes]:
        return {path.relative_to(self.root).as_posix(): path.read_bytes() for path in self.root.rglob("*")
                if path.is_file() and ".git/" not in path.as_posix() + "/"}

    def run_command(self, command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return run_recovery(command, cwd, self.worktrees)


class UnrelatedDirectoryTest(ProjectFixture):
    def test_emitted_next_command_runs_unchanged_from_an_unrelated_directory(self) -> None:
        unrelated = self.base / "elsewhere ; dir"
        unrelated.mkdir()
        first = self.run_command(f"cardine run 001 --project {shlex.quote(str(self.root))}", unrelated)
        self.assertIn(first.returncode, (0, 2), first.stderr)
        envelope = json.loads(first.stdout)
        validate_output(envelope)
        self.assertEqual(envelope["project"], str(self.root))
        before = self.tree()
        if envelope["next"] is not None:
            again = self.run_command(envelope["next"]["command"], unrelated)
            self.assertEqual(again.returncode, first.returncode, again.stderr)
            self.assertEqual(json.loads(again.stdout)["step"], envelope["step"])
        self.assertEqual(self.tree(), before)
        self.assertFalse((unrelated / "SENTINEL").exists() or (self.base / "SENTINEL").exists())


class JournalNeverGatesTest(ProjectFixture):
    JOURNAL_FIELDS = ("stop_code", "resolution", "cause", "owner", "operation", "next")

    def test_historical_and_forged_journal_lines_never_change_progress(self) -> None:
        unrelated = self.base / "elsewhere"
        unrelated.mkdir()
        command = f"cardine run 001 --project {shlex.quote(str(self.root))}"
        clean = self.run_command(command, unrelated)
        journal = self.root / ".git/cardine-journal.jsonl"
        forged = [
            {"version": 1, "ts": "2020-01-01T00:00:00Z", "command": "cleanup", "task": "001",
             "result": "blocked", "exit": 2, "stop_code": "CLEANUP_BLOCKED", "resolution": "guardrail"},
            {"version": 1, "command": "prepare", "task": "001", "result": "ok", "exit": 0},  # older shape
            {"version": 99, "task": "001", "stop_code": "NOT_A_CODE", "owner": "cardine", "next": "rm -rf /"},
        ]
        journal.write_text("".join(json.dumps(line) + "\n" for line in forged) + "not json at all\n\x00\n")
        marker = {name: path.read_bytes() for name, path in
                  ((p.name, p) for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts)}
        after = self.run_command(command, unrelated)
        self.assertEqual((after.returncode, after.stdout), (clean.returncode, clean.stdout))
        self.assertEqual(marker, {p.name: p.read_bytes() for p in self.root.rglob("*")
                                  if p.is_file() and ".git" not in p.parts})

    def test_no_engine_module_reads_the_journal(self) -> None:
        readers = []
        for package in ("lifecycle", "tasks", "integration", "worktree", "review", "stops", "hosts"):
            for path in (ROOT / "src/cardine" / package).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | \
                        {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | \
                        {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                         for alias in node.names}
                if names & {"journal_name", "journal_rotated_name", "JOURNAL_NAME", "JOURNAL_ROTATED_NAME"}:
                    readers.append(path.relative_to(ROOT).as_posix())
                if "cardine.shared.flow" in path.read_text(encoding="utf-8"):
                    readers.append(path.relative_to(ROOT).as_posix())
        # Closure and checkout only append their own best-effort lines; none reads one back.
        self.assertEqual(sorted(set(readers)), [])


class LegacyIsolationTest(ProjectFixture):
    def test_missing_product_declaration_never_selects_the_legacy_reader(self) -> None:
        (self.root / ".cardine/project.json").unlink()
        (self.root / ".meridian").mkdir()
        (self.root / ".meridian/manifest.json").write_text("{}")
        (self.root / "PROJECT_WORKFLOW.md").write_text("# Lean Delivery Workflow — Meridian\n")
        (self.root / "tasks/QUEUE.md").write_text("| `[ ]` | 001 | Fixture |\n")
        before = self.tree()
        unrelated = self.base / "elsewhere"
        unrelated.mkdir()
        result = self.run_command(f"cardine run 001 --project {shlex.quote(str(self.root))}", unrelated)
        self.assertIn(result.returncode, (2, 64), result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.tree(), before)

    def test_only_the_explicit_boundaries_import_the_legacy_package(self) -> None:
        importers = set()
        for path in (ROOT / "src/cardine").rglob("*.py"):
            relative = path.relative_to(ROOT).as_posix()
            if relative.startswith("src/cardine/legacy/"):
                continue
            if re.search(r"^\s*(from|import) cardine\.legacy\b", path.read_text(encoding="utf-8"), re.MULTILINE):
                importers.add(relative)
        for relative in importers:
            self.assertFalse(relative.startswith(("src/cardine/lifecycle/", "src/cardine/integration/",
                                                  "src/cardine/review/", "src/cardine/worktree/",
                                                  "src/cardine/stops/")), relative)


class ReplayInventoryTest(unittest.TestCase):
    """Every module that crosses an effect boundary has an executable replay test."""

    REPLAY = {
        "src/cardine/integration/records.py": ["test_run_integration.CandidateTest.test_closure_record_commit_boundaries_converge"],
        "src/cardine/integration/ci.py": ["test_run_ci.CiTest.converges_after_kill"],
        "src/cardine/integration/merge.py": ["test_run_recovery.RunRecoveryTest.assert_stage_kill_recovers"],
        "src/cardine/integration/finalize.py": ["test_run_integration.CandidateTest.test_finalize_every_effect_boundary_returns_the_same_commit"],
        "src/cardine/integration/candidate.py": ["test_run_integration.CandidateTest.test_candidate_result_boundaries_replay_once"],
        "src/cardine/integration/residue.py": ["test_run_recovery.RunRecoveryTest.assert_residue_clear_converges"],
        "src/cardine/lifecycle/delivery.py": ["test_run_delivery.RunDeliveryTest.test_all_delivery_boundaries_converge_once_and_keep_original_source"],
        "src/cardine/worktree/checkout.py": ["test_run_preparation.RunPreparationTest.test_resume_receipt_survives_both_effect_boundaries"],
        "src/cardine/worktree/preparation.py": ["test_run_preparation.RunPreparationTest.test_preparation_all_effect_boundaries_converge_without_state_transition"],
        "src/cardine/lifecycle/receipts.py": ["test_run_review.RunReviewTest.test_every_state_projection_and_receipt_boundary_converges_once",
                                              "test_run_receipts.RunReceiptsTest.test_creation_killed_before_and_after_all_four_boundaries"],
        "src/cardine/lifecycle/control_abort.py": ["test_run_control.RunAbortTest.test_every_abort_and_receipt_boundary_converges_once"],
        "src/cardine/lifecycle/control.py": ["test_run_control.RunCancelTest.test_every_cancel_and_receipt_boundary_retains_branch_and_time_once"],
        "src/cardine/lifecycle/validation.py": ["test_run_validation.RunValidationTest.test_replay_before_validation_process",
                                                "test_run_validation.RunValidationTest.test_replay_after_validation_result"],
        "src/cardine/hosts/launch.py": ["test_run_host_roles.RunHostRolesTest.test_every_host_and_receipt_boundary_restarts_same_session"],
    }

    def boundary_modules(self) -> set[str]:
        found = set()
        for path in (ROOT / "src/cardine").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "boundary"
                        and node.args and isinstance(node.args[0], (ast.Constant, ast.BinOp))):
                    found.add(path.relative_to(ROOT).as_posix())
        return found

    def test_every_boundary_module_names_an_existing_replay_test(self) -> None:
        self.assertEqual(self.boundary_modules(), set(self.REPLAY))
        for module, tests in self.REPLAY.items():
            for dotted in tests:
                with self.subTest(module=module, test=dotted):
                    self.assertTrue(has_test(dotted), dotted)

    def test_cleanup_and_two_task_interleaving_are_covered(self) -> None:
        for dotted in ("test_run_cleanup.CleanupTest.test_every_effect_boundary_replays_identically",
                       "test_run_recovery.RunRecoveryTest.test_cleanup_killed_around_each_effect_converges_without_foreign_loss",
                       "test_run_integration.CandidateTest.test_finalized_task_replays_after_another_task_advances_main",
                       "test_run_integration.CandidateTest.test_concurrent_tasks_wait_then_recompute_advanced_main"):
            with self.subTest(test=dotted):
                self.assertTrue(has_test(dotted), dotted)


class AbortLandingRestoreTest(unittest.TestCase):
    """The one abort boundary no row's loop reaches: owned landing dirt beside a staged merge."""

    def setUp(self) -> None:
        import worktree_support
        self.fixture = worktree_support.BoundedWorktreeLifecycleFixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)
        self.primary = self.fixture.primary
        self.worker = Path(self.fixture.prepare()["worktree"])
        (self.worker / "feature.txt").write_text("candidate\n")
        self.fixture.git("add", ".", cwd=self.worker)
        self.fixture.git("commit", "-m", "Implement candidate", cwd=self.worker)
        self.fixture.measure(self.worker)
        from cardine.integration.merge import stage_task_integration
        from cardine.lifecycle import receipts

        class Crash(BaseException):
            """Stands for a killed process: no `except Exception` handler may run."""

        def stop(name):
            if name == "after_state_replace":
                raise Crash

        with mock.patch.object(receipts, "boundary", stop), self.assertRaises(Crash):
            stage_task_integration("056", self.fixture.worktree_root, None, self.primary)

    def abort(self):
        from cardine.lifecycle.control_abort import abort_owned
        from control_support import adapter
        return abort_owned("056", self.primary, adapter=adapter("coordinator"))

    def test_kill_around_the_landing_restore_converges_without_losing_work(self) -> None:
        import test_run_control
        for point in ("before_abort_landing_restore", "after_abort_landing_restore"):
            with self.subTest(point=point):
                if point.startswith("after"):
                    self.doCleanups()
                    self.setUp()
                head = self.fixture.git("rev-parse", "HEAD", cwd=self.worker).stdout.strip()
                killed = test_run_control.killed(self.primary, point, "abort")
                self.assertEqual(killed.returncode, 77, killed.stderr)
                self.assertEqual(self.abort(), self.abort())
                self.assertFalse((self.primary / ".git/MERGE_HEAD").exists())
                self.assertEqual(self.fixture.git("rev-parse", "HEAD").stdout.strip(), self.fixture.base)
                self.assertEqual(self.fixture.git("rev-parse", "HEAD", cwd=self.worker).stdout.strip(), head)
                self.assertEqual((self.worker / "feature.txt").read_text(), "candidate\n")


class ForgeryMatrixTest(unittest.TestCase):
    """F01–F20 within the declared same-user boundary; no authenticity claim."""

    OUTSIDE = {
        "F17": "installation manifest and probe authority are deferred after 1.0 and cannot authorize landing",
        "F20": "a trusted executable and schemas are outside the agent's reach only through a host permission",
    }
    EXECUTABLE = {
        "F01": ["test_run_receipts.RunReceiptsTest.test_chain_tampering_missing_receipts_and_fabricated_result_refuse"],
        "F02": ["test_run_receipts.RunReceiptsTest.test_state_contract_and_record_edits_are_uncovered"],
        "F03": ["test_run_receipts.RunReceiptsTest.test_task_branch_policy_cannot_pin_itself_as_accepted_main"],
        "F04": ["test_run_validation.RunValidationTest.test_f04_f05_f15_forged_results_contract_and_source_fail_closed"],
        "F05": ["test_run_ci.CiTest.test_fabricated_records_and_tracking_refs_have_no_authority"],
        "F06": ["test_run_integration.CandidateTest.test_interrupted_result_rejects_changed_inputs_and_foreign_owner"],
        "F07": ["test_run_integration.CandidateTest.test_declared_pass_file_has_no_authority"],
        "F08": ["test_run_integration.CandidateTest.test_changed_tree_configuration_and_foreign_lease_fail_closed"],
        "F09": ["test_run_preparation.RunPreparationTest.test_foreign_collision_changed_input_and_foreign_owner_refuse"],
        "F10": ["test_run_integration.CandidateTest.test_finalize_replay_preserves_a_foreign_lease_after_commit"],
        "F11": ["test_run_review.RunReviewTest.test_implementer_owner_spoof_and_exchanged_reviewer_session_write_nothing"],
        "F12": ["test_run_receipts.RunReceiptsTest.test_changed_staged_bytes_fail_closed_and_keep_foreign_files"],
        "F13": ["test_run_console.RunConsoleTest.test_journal_and_targets_cannot_change_preview_or_verified_observations",
                "test_run_end_to_end.JournalNeverGatesTest.test_historical_and_forged_journal_lines_never_change_progress"],
        "F14": ["test_run_console.RunConsoleTest.test_uncovered_terminal_state_cannot_hide_a_task_or_inflate_totals"],
        "F15": ["test_run_handoff.RunHandoffTest.test_absent_paraphrased_and_false_report_fields_change_no_gate_or_fact"],
        "F16": ["test_run_ci.CiTest.test_foreign_remote_work_and_refused_push_are_guardrails"],
        "F18": ["test_run_console.RunConsoleTest.test_forged_policy_invalidates_observations_without_legacy_fallback"],
        "F19": ["test_run_receipts.RunReceiptsTest.test_policy_and_runtime_override_cannot_authorize_themselves"],
    }

    def test_every_attack_row_is_executable_or_outside_the_declared_boundary(self) -> None:
        inventory = (ROOT / "docs/FORGERY_INVENTORY.md").read_text(encoding="utf-8")
        rows = set(re.findall(r"^\| (F\d\d) — ", inventory, re.MULTILINE))
        self.assertEqual(rows, {f"F{number:02d}" for number in range(1, 21)})
        self.assertEqual(set(self.EXECUTABLE) | set(self.OUTSIDE), rows)
        self.assertFalse(set(self.EXECUTABLE) & set(self.OUTSIDE))
        for row, tests in sorted(self.EXECUTABLE.items()):
            for dotted in tests:
                with self.subTest(row=row, test=dotted):
                    self.assertTrue(has_test(dotted), dotted)

    def test_no_document_claims_authenticity_beyond_the_trust_boundary(self) -> None:
        text = (ROOT / "docs/RUN_COMMANDS.md").read_text(encoding="utf-8")
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if re.search(r"authentic|signature|signed|authorship", sentence, re.IGNORECASE):
                self.assertRegex(sentence, r"\bno\b|\bnot\b|unavailable", sentence)


class RunCommandsDocumentTest(unittest.TestCase):
    def test_every_command_the_document_names_exists_and_it_is_not_a_template(self) -> None:
        import check_repository as cr
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "docs/RUN_COMMANDS.md"
            target.parent.mkdir()
            target.write_text((ROOT / "docs/RUN_COMMANDS.md").read_text(encoding="utf-8"), encoding="utf-8")
            self.assertEqual(cr.unknown_template_commands(Path(directory), cr.command_tree(cardine_cli.build_parser())), [])
        self.assertFalse((ROOT / "templates/single/docs/RUN_COMMANDS.md").exists())
        catalog = (ROOT / "capabilities/catalog-v1.json").read_text(encoding="utf-8")
        self.assertNotIn("RUN_COMMANDS", catalog)

    def test_the_document_names_the_stable_surface_and_every_outcome(self) -> None:
        text = (ROOT / "docs/RUN_COMMANDS.md").read_text(encoding="utf-8")
        for command in ("cardine run", "cardine status", "cardine review verdict", "cardine cancel", "cardine abort"):
            self.assertIn(command, text)
        for outcome in ("progress", "next", "waiting", "iterate", "blocked", "done"):
            self.assertIn(f"`{outcome}`", text)
        for step in STEPS:
            self.assertIn(f"`{step}`", text)


if __name__ == "__main__":
    unittest.main()
