"""Execution contracts, provenance, and handoff regression tests."""

from __future__ import annotations

from cardine_cli_support import CLI
from stop_recovery_support import run_recovery, resume_from
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import cardine.shared.errors as shared_errors
from cardine.tasks import contract as owner_tasks_contract
from cardine.tasks import preflight as owner_tasks_preflight
from task_contract_support import write_state, freeze_record
from project_config_support import write_project_config


class ExecutionEvidenceTest(unittest.TestCase):
    """Execution evidence remains durable without self-reported counters."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        (self.project / "tasks").mkdir(parents=True)
        write_project_config(self.project, "governed")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_task(self, task_id: str, status: str, **overrides: str) -> None:
        write_state(self.project, task_id, status)
        lines = [f"Status: {status}"]
        for field, value in overrides.items():
            lines.append(f"{field}: {value}")
        (self.project / "tasks" / f"{task_id}.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


    def append_contract(self, task_id: str) -> None:
        write_state(self.project, task_id)
        self.freeze_pending_states()
        path = self.project / "tasks" / f"{task_id}.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n" + owner_tasks_preflight.execution_contract(self.project, task_id) + "\n", encoding="utf-8")

    def freeze_pending_states(self):
        # Legacy-shaped records still exercise the deferred prose gates, while
        # runtime policy always starts from a fixture snapshot.
        from cardine.tasks.identity import find_task_file
        for path in (self.project / '.cardine/tasks').glob('*.json'):
            state = json.loads(path.read_text())
            if 'contract' not in state:
                freeze_record(self.project, path.stem, find_task_file(self.project, path.stem))

    def contract_ready_check(self, task_id, report):
        self.freeze_pending_states()
        try:
            output = owner_tasks_preflight.readiness_check(self.project.resolve(), task_id)
            return subprocess.CompletedProcess([], 0, output, "")
        except shared_errors.CardineError as error:
            from cardine.stops.render import outcome_for_code
            code = 2 if not isinstance(error, shared_errors.CardineStop) or outcome_for_code(error.code) == "blocked" else 0
            return subprocess.CompletedProcess([], code, "", str(error))

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        self.freeze_pending_states()
        return subprocess.run(
            [sys.executable, str(CLI), *arguments, "--project", str(self.project)],
            text=True,
            capture_output=True,
            check=False,
        )


    def test_locations_and_preflight_use_the_declared_queue(self) -> None:
        (self.project / "docs/tasks/M19").mkdir(parents=True)
        (self.project / "docs/tasks/M19/TASK-007.md").write_text(
            "Status: in_progress\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )
        (self.project / "docs/TASK_QUEUE.md").write_text(
            "| Order | ID | Priority | Status | Dependencies |\n|---:|---|---|---|---|\n"
            "| 1 | TASK-007 | P0 | queued | — |\n",
            encoding="utf-8",
        )
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- CARDINE:BEGIN capability=execution-assets v1 -->\n<!-- CARDINE:END -->\n"
            "Task files live under `docs/tasks/<milestone>/`; queue is `docs/TASK_QUEUE.md`.\n\n## Roles\n",
            encoding="utf-8",
        )
        write_project_config(self.project, "governed", locations={"queue": "docs/TASK_QUEUE.md", "taskRoots": ["tasks", "docs/tasks"]})
        nested_task = self.project / "docs/tasks/M19/TASK-007.md"
        freeze_record(self.project, "TASK-007", nested_task)
        nested_task.write_text(
            nested_task.read_text(encoding="utf-8") + "\n" + owner_tasks_preflight.execution_contract(self.project, "TASK-007") + "\n",
            encoding="utf-8",
        )
        locations = self.run_cli("locations", "--field", "queue")
        self.assertEqual(locations.stdout.strip(), "docs/TASK_QUEUE.md")
        preflight = self.run_cli("execution", "preflight", "TASK-007")
        write_state(self.project, "TASK-007", "in_progress")
        preflight = self.run_cli("execution", "preflight", "TASK-007")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)

    def remediation_project(self, branch: str, record_status: str, queue_status: str = "queued") -> Path:
        """A Git project on `branch` whose queue row is `queue_status` and whose record is `record_status`."""
        subprocess.run(["git", "init", "-q", "-b", branch, str(self.project)], check=True)
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-007.md"
        write_state(self.project, "TASK-007")
        task.write_text(
            f"Status: {record_status}\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n"
            "- `check`: `python3 -c pass`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-007")
        (self.project / "tasks/QUEUE.md").write_text(
            "| Order | ID | Priority | Status | Dependencies |\n|---:|---|---|---|---|\n"
            f"| 1 | TASK-007 | P0 | {queue_status} | — |\n",
            encoding="utf-8",
        )
        write_state(self.project, "TASK-007", "in_progress")
        return task

    def test_task_branch_preflight_accepts_every_state_the_workflow_produces(self) -> None:
        # Issue #6: a task branch cannot edit the queue, and a review returns the record to in_progress.
        task = self.remediation_project("task-007", "in_progress")
        for status in ("queued", "in_progress", "in_review"):
            with self.subTest(status=status):
                write_state(self.project, "TASK-007", status, review_required=True)
                text = task.read_text(encoding="utf-8")
                task.write_text(f"Status: {status}\n" + text.split("\n", 1)[1], encoding="utf-8")
                result = self.run_cli("execution", "preflight", "TASK-007")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_remediation_commands_share_the_preflight_on_a_task_branch(self) -> None:
        self.remediation_project("task-007", "in_progress")
        validated = self.run_cli("execution", "validate", "TASK-007", "check")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        report = self.project / "ready.md"
        report.write_text("## Completion Report — TASK-007\n", encoding="utf-8")
        ready = self.run_cli("execution", "ready-check", "TASK-007", str(report))
        self.assertNotIn("QUEUE_STATUS_MISMATCH", ready.stderr)
        self.assertNotIn("TASK_STATUS_REJECTED", ready.stderr)

    def test_task_branch_preflight_still_rejects_states_the_workflow_cannot_produce(self) -> None:
        self.remediation_project("task-007", "in_progress", queue_status="done")
        mismatch = self.run_cli("execution", "preflight", "TASK-007")
        self.assertEqual(mismatch.returncode, 0, mismatch.stderr)
        write_state(self.project, "TASK-007", "done")
        rejected = self.run_cli("execution", "preflight", "TASK-007")
        self.assertIn("TASK_STEP_PENDING", rejected.stderr)
        self.assertIn("found: done", rejected.stderr)

    def test_outside_the_task_branch_the_record_and_queue_must_still_agree(self) -> None:
        self.remediation_project("main", "in_progress")
        result = self.run_cli("execution", "preflight", "TASK-007")
        self.assertEqual(result.returncode, 0, result.stderr)
        write_state(self.project, "TASK-007", "in_review", review_required=True)
        rejected = self.run_cli("execution", "preflight", "TASK-007")
        self.assertIn("accepted: queued, in_progress; found: in_review", rejected.stderr)

    def test_execution_preflight_requires_profile_and_task_contract(self) -> None:
        self.write_task("TASK-008", "queued")
        missing = self.run_cli("execution", "preflight", "TASK-008")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("BLOCKED UNDECLARED_VALIDATION_COMMANDS:", missing.stderr)
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-008.md").write_text(
            "Status: queued\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-008")
        passed = self.run_cli("execution", "preflight", "TASK-008")
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn("Execution contract:", passed.stdout)

    def blueprint_contract_section(self) -> str:
        blueprint = (Path(__file__).resolve().parents[1] / "templates/single/tasks/TASK_BLUEPRINT.md").read_text(encoding="utf-8")
        match = re.search(r"^## Execution contract — resolved\n.*?(?=^## )", blueprint, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match)
        return match.group(0)

    def test_blueprint_execution_commands_line_equals_the_generated_line(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        write_state(self.project, "TASK-021")
        (self.project / "tasks/TASK-021.md").write_text("## Validation\n- `check`: `true`\n", encoding="utf-8")
        self.freeze_pending_states()
        generated = owner_tasks_preflight.execution_contract(self.project, "TASK-021").splitlines()
        template_lines = [line for line in self.blueprint_contract_section().splitlines() if line.startswith("- Execution commands:")]
        self.assertEqual(template_lines, [owner_tasks_contract.EXECUTION_COMMANDS_LINE])
        self.assertEqual(generated[-1], template_lines[0])

    def test_a_record_from_the_product_blueprint_passes_preflight_without_regenerating(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        write_state(self.project, "TASK-022")
        section = self.blueprint_contract_section().replace(
            "<generated profile digest>", owner_tasks_contract.profile_digest(self.project)
        ).replace("<generated IDs>", "check")
        (self.project / "tasks/TASK-022.md").write_text(
            "Status: queued\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n- `check`: `true`\n\n"
            "## Host impact\n\nClassification: NOT_APPLICABLE\nRationale: This task changes only application behavior.\n\n"
            + section,
            encoding="utf-8",
        )
        passed = self.run_cli("execution", "preflight", "TASK-022")
        self.assertEqual(passed.returncode, 0, passed.stderr)

    def test_execution_preflight_uses_spike_shape(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-018.md"
        write_state(self.project, "TASK-018")
        task.write_text(
            "Status: queued\nClass: SPIKE\nQuestion: What behavior is correct?\n"
            "Timebox: 2 iterations\nDeliverable: An ADR\n\n## Authority\n\n## Validation\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-018")

        passed = self.run_cli("execution", "preflight", "TASK-018")
        self.assertEqual(passed.returncode, 0, passed.stderr)

        for field in ("Question", "Timebox", "Deliverable"):
            with self.subTest(field=field):
                text = task.read_text(encoding="utf-8")
                task.write_text(
                    re.sub(rf"^{field}:.*\n", "", text, flags=re.MULTILINE), encoding="utf-8"
                )
                blocked = self.run_cli("execution", "preflight", "TASK-018")
                self.assertEqual(blocked.returncode, 0, blocked.stderr)
                task.write_text(text, encoding="utf-8")

    def test_execution_preflight_validates_host_impact_declarations(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-019.md"
        write_state(self.project, "TASK-019")
        base = "Status: queued\n\n## Authority\n\n## Expected code surface\n\n## Validation\n"
        not_applicable = "\n## Host impact\n\nClassification: NOT_APPLICABLE\nRationale: This task changes only application behavior.\n"
        task.write_text(base + not_applicable, encoding="utf-8")
        self.append_contract("TASK-019")
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-019").returncode, 0)

        task.write_text(task.read_text(encoding="utf-8").replace("Rationale: This task changes only application behavior.\n", ""), encoding="utf-8")
        missing_rationale = self.run_cli("execution", "preflight", "TASK-019")
        self.assertEqual(missing_rationale.returncode, 0, missing_rationale.stderr)
        with self.assertRaisesRegex(shared_errors.CardineError, "missing Rationale"):
            owner_tasks_contract.validate_host_impact_declaration(task.read_text())

        required = """Classification: REQUIRED
Policy outcome: The lifecycle gate validates host-impact evidence.

| Profile | Before | Intended after | Activation preconditions | Fallback |
|---|---|---|---|---|
| Cardine CLI / direct invocation / project | advisory | enforced | Run through execution. | Block missing evidence. |

Evidence plan:
- Static: parser test
- Host execution: fixture command
- Manual activation: run from a project subdirectory
"""
        task.write_text(base + "\n## Host impact\n\n" + required, encoding="utf-8")
        self.append_contract("TASK-019")
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-019").returncode, 0)

        task.write_text(task.read_text(encoding="utf-8").replace("- Host execution: fixture command\n", ""), encoding="utf-8")
        missing_evidence = self.run_cli("execution", "preflight", "TASK-019")
        self.assertEqual(missing_evidence.returncode, 0, missing_evidence.stderr)
        with self.assertRaisesRegex(shared_errors.CardineError, "missing Host execution"):
            owner_tasks_contract.validate_host_impact_declaration(task.read_text())

    def test_ready_check_requires_evidence_only_for_enforced_host_profiles(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-020.md"
        write_state(self.project, "TASK-020")
        task.write_text(
            "Status: in_progress\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n"
            "## Host impact\n\nClassification: REQUIRED\nPolicy outcome: Accurate host claims.\n\n"
            "| Profile | Before | Intended after | Activation preconditions | Fallback |\n"
            "|---|---|---|---|---|\n"
            "| Cardine CLI / direct / project | advisory | enforced | Run execution. | Block claim. |\n"
            "| Codex / project / trusted rules | advisory | unverified | Probe unavailable. | Retain unverified. |\n\n"
            "Evidence plan:\n- Static: parser test\n- Host execution: fixture command\n- Manual activation: project subdirectory\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-020")
        report = self.project / "ready.md"
        report.write_text(
            "## Completion Report — TASK-020\n\n- Files changed: none\n- Validation: exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n"
            "- Isolated exploration: none\n- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        missing = self.contract_ready_check("TASK-020", report)
        self.assertEqual(missing.returncode, 0)
        self.assertIn('ITERATE EVIDENCE_INCOMPLETE:', missing.stderr)
        self.assertIn('current measured observations', missing.stderr)

        task.write_text(
            task.read_text(encoding="utf-8").replace(
                "\n## Execution contract — resolved",
                "\nCompletion evidence:\n- [Cardine CLI / direct / project]: fixture observed the gate.\n"
                "\n## Execution contract — resolved",
            ),
            encoding="utf-8",
        )
        passed = self.contract_ready_check("TASK-020", report)
        self.assertEqual(passed.returncode, 0)
        self.assertIn("current measured observations", passed.stderr)

    def test_reconcile_upgrades_a_nonterminal_legacy_contract_before_preflight(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-014.md"
        write_state(self.project, "TASK-014")
        task.write_text(
            "Status: queued\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n## Completion\n",
            encoding="utf-8",
        )
        self.freeze_pending_states()
        legacy_contract = owner_tasks_preflight.execution_contract(self.project, "TASK-014").replace(
            owner_tasks_contract.EXECUTION_COMMANDS_LINE, ""
        )
        task.write_text(task.read_text(encoding="utf-8").replace("## Completion", legacy_contract + "\n\n## Completion"), encoding="utf-8")
        blocked = self.run_cli("execution", "preflight", "TASK-014")
        self.assertEqual(blocked.returncode, 0)
        self.assertIn("NEXT EXECUTION_CONTRACT_UNRESOLVED:", blocked.stderr)
        self.assertIn("`required via cardine execution`", blocked.stderr)
        preview = self.run_cli("execution", "reconcile", "TASK-014")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("rerun with --apply", preview.stdout)
        applied = self.run_cli("execution", "reconcile", "TASK-014", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-014").returncode, 0)

    def test_reconcile_is_idempotent_when_contract_is_the_final_section(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-016.md"
        write_state(self.project, "TASK-016")
        task.write_text(
            "Status: queued\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )

        preview = self.run_cli("execution", "reconcile", "TASK-016")
        self.assertIn("rerun with --apply", preview.stdout)
        applied = self.run_cli("execution", "reconcile", "TASK-016", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        reconciled = task.read_text(encoding="utf-8")

        current = self.run_cli("execution", "reconcile", "TASK-016")
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertIn("already current", current.stdout)
        self.assertEqual(task.read_text(encoding="utf-8"), reconciled)

    def test_execution_contract_blocks_unnamed_validation_entries(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-017.md"
        write_state(self.project, "TASK-017")
        task.write_text(
            "Status: queued\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `cargo fmt --check`\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(shared_errors.CardineError, "VALIDATION_ENTRY_FORMAT"):
            owner_tasks_contract.require_named_validation_commands(task.read_text())
        task.write_text(task.read_text().replace("- `cargo fmt --check`", "- `check`: `true`"))
        self.append_contract("TASK-017")
        task.write_text(task.read_text().replace("- `check`: `true`", "- `cargo fmt --check`"))
        self.assertEqual(self.run_cli("execution", "reconcile", "TASK-017").returncode, 0)
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-017").returncode, 0)

    def test_reconcile_preserves_terminal_task_history(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-015.md"
        write_state(self.project, "TASK-015")
        write_state(self.project, "TASK-015", "done")
        task.write_text("Status: done\n\n## Completion\n- historical record\n", encoding="utf-8")
        original = task.read_text(encoding="utf-8")
        result = self.run_cli("execution", "reconcile", "TASK-015", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped for terminal task", result.stdout)
        self.assertEqual(task.read_text(encoding="utf-8"), original)


    def test_ready_check_combines_preflight_and_measured_results(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-012.md").write_text(
            "Status: in_progress\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-012")
        report = self.project / "ready.md"
        report.write_text(
            "## Completion Report — TASK-012\n\n- Files changed: none\n- Validation: exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n"
            "- Isolated exploration: none\n"
            "- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        handoff = self.project / "tasks/handoffs/TASK-012.md"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text("## Completion Report — TASK-012\n", encoding="utf-8")
        result = self.contract_ready_check("TASK-012", report)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("in_review gate passed", result.stdout)




    def blocked_line(self, result: subprocess.CompletedProcess[str]) -> str:
        line = next(line for line in result.stderr.splitlines() if line.startswith(("BLOCKED ", "NEXT ", "ITERATE ")))
        self.assertEqual(result.returncode, 2 if line.startswith("BLOCKED ") else 0, result.stdout + result.stderr)
        return line

    def test_unresolved_contract_recovery_runs_unchanged(self) -> None:
        write_state(self.project, "TASK-020")
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-020.md").write_text(
            "Status: queued\n\n## Authority\n\n## Expected code surface\n\n## Validation\n", encoding="utf-8")
        stopped = self.run_cli("execution", "preflight", "TASK-020")
        self.assertIn("NEXT EXECUTION_CONTRACT_UNRESOLVED:", self.blocked_line(stopped))
        recovered = run_recovery(resume_from(stopped.stderr), self.project)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        retried = self.run_cli("execution", "preflight", "TASK-020")
        self.assertEqual(retried.returncode, 0, retried.stderr)

    def test_execution_gates_report_coded_actionable_stops(self) -> None:
        self.write_task("TASK-020", "queued")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED UNDECLARED_VALIDATION_COMMANDS: cause: execution-profile; no "
            "docs/EXECUTION_EVIDENCE_PROFILE.md or installed validation policy; "
            "resume: declare the missing execution or candidate validation policy, then rerun the interrupted command",
        )
        (self.project / "docs").mkdir()
        profile = self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md"
        profile.write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-020.md"
        write_state(self.project, "TASK-020")
        body = "Status: queued\n\n## Authority\n\n## Expected code surface\n\n## Validation\n"
        task.write_text(body, encoding="utf-8")
        digest = owner_tasks_contract.profile_digest(self.project)
        resume = "resume: cardine execution reconcile TASK-020 --apply --project ."
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "NEXT EXECUTION_CONTRACT_UNRESOLVED: rule: a task needs a resolved execution contract; field "
            f"checked: `- Profile revision` in tasks/TASK-020.md; expected: sha256:{digest}; found: no such line; "
            + resume,
        )
        self.append_contract("TASK-020")
        profile.write_text("changed profile\n", encoding="utf-8")
        changed = owner_tasks_contract.profile_digest(self.project)
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "NEXT EXECUTION_CONTRACT_UNRESOLVED: rule: the resolved contract must match the current profile; "
            "field checked: `- Profile revision` in tasks/TASK-020.md against docs/EXECUTION_EVIDENCE_PROFILE.md; "
            f"expected: sha256:{changed}; found: sha256:{digest}; " + resume,
        )
        task.write_text(body.replace("## Expected code surface\n\n", ""), encoding="utf-8")
        self.append_contract("TASK-020")
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-020").returncode, 0)
        task.write_text(body.replace("queued", "ACCEPTED"), encoding="utf-8")
        self.append_contract("TASK-020")
        write_state(self.project, "TASK-020", "in_review", review_required=True)
        accepted = f"resume: cardine run TASK-020 --project {self.project.resolve()}"
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "NEXT TASK_STEP_PENDING: rule: preflight runs only on an open task; field checked: validated task state for "
            "tasks/TASK-020.md; accepted: queued, in_progress; found: in_review; " + accepted,
        )
        task.write_text(body.replace("queued", "DRAFT"), encoding="utf-8")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "reconcile", "TASK-020")),
            "NEXT TASK_STEP_PENDING: rule: reconcile refreshes only an open task; field checked: validated task state for "
            "tasks/TASK-020.md; accepted: queued, in_progress (terminal tasks are skipped); found: in_review; " + accepted,
        )
        write_state(self.project, "TASK-020")
        task.write_text(body + "\n- `cargo fmt --check`\n", encoding="utf-8")
        self.assertEqual(self.run_cli("execution", "reconcile", "TASK-020").returncode, 0)
        with self.assertRaisesRegex(shared_errors.CardineError, "VALIDATION_ENTRY_FORMAT"):
            owner_tasks_contract.require_named_validation_commands(task.read_text())



    def test_validation_runs_only_a_declared_literal_command_and_records_status(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-010.md").write_text(
            "Status: in_progress\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `probe`: `printf validation-ok`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-010")
        result = self.run_cli("execution", "validate", "TASK-010", "probe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validation-ok", result.stdout)
        evidence = json.loads((self.project / ".cardine/evidence/TASK-010.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["TASK-010"][0]["id"], "probe")
        missing = self.run_cli("execution", "validate", "TASK-010", "not-declared")
        self.assertEqual(missing.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing),
            "ITERATE VALIDATION_ID_UNDECLARED: rule: only a task-declared validation ID runs; field checked: "
            "validation.commands in the TASK-010 frozen contract; accepted: probe; found: 'not-declared'; resume: rerun cardine "
            "execution validate with a validation ID listed in the task's Validation section, or declare the command "
            "there first",
        )

    def test_budget_command_is_removed(self) -> None:
        rejected = self.run_cli("budget", "show", "TASK-011")
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn("invalid choice: 'budget'", rejected.stderr)

    def test_uncoded_command_refusal_reports_command_refused(self) -> None:
        refused = self.run_cli("task", "identity", "check", "TASK-404", "--format", "json")
        line = self.blocked_line(refused)
        self.assertTrue(line.startswith("BLOCKED COMMAND_REFUSED: "), line)
        self.assertTrue(
            line.endswith("; resume: correct the condition that the detail names, then rerun the same cardine command"),
            line,
        )
        self.assertNotIn("BLOCKED:", refused.stderr)

    def test_operating_system_failure_reports_os_access_failed(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n")
        self.write_task("TASK-405", "in_progress")
        task = self.project / "tasks/TASK-405.md"
        task.write_text(task.read_text() + "\n## Authority\n\n## Expected code surface\n\n## Validation\n\n- `probe`: `printf ok`\n")
        self.append_contract("TASK-405")
        (self.project / ".cardine").mkdir(exist_ok=True)
        (self.project / ".cardine/evidence/TASK-405.json").mkdir(parents=True)
        failed = self.run_cli("execution", "validate", "TASK-405", "probe")
        line = self.blocked_line(failed)
        self.assertTrue(line.startswith("BLOCKED OS_ACCESS_FAILED: "), line)
        self.assertTrue(
            line.endswith("; resume: fix the access problem that the detail names, then rerun the same cardine command"),
            line,
        )

    def test_self_reported_evidence_commands_are_removed(self) -> None:
        for command in ("evidence", "investigate"):
            with self.subTest(command=command):
                result = self.run_cli("execution", command, "TASK-011")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(f"invalid choice: '{command}'", result.stderr)
