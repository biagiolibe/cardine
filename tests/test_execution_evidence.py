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


class ExecutionEvidenceTest(unittest.TestCase):
    """Execution evidence remains durable without self-reported counters."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        (self.project / "tasks").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_task(self, task_id: str, status: str, **overrides: str) -> None:
        lines = [f"Status: {status}"]
        for field, value in overrides.items():
            lines.append(f"{field}: {value}")
        (self.project / "tasks" / f"{task_id}.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


    def append_contract(self, task_id: str) -> None:
        path = self.project / "tasks" / f"{task_id}.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n" + owner_tasks_preflight.execution_contract(self.project, task_id) + "\n", encoding="utf-8")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments, "--project", str(self.project)],
            text=True,
            capture_output=True,
            check=False,
        )


    def test_locations_and_preflight_use_the_declared_queue(self) -> None:
        (self.project / "docs/tasks/M19").mkdir(parents=True)
        (self.project / "docs/tasks/M19/TASK-007.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )
        (self.project / "docs/TASK_QUEUE.md").write_text(
            "| Order | ID | Priority | Status | Dependencies |\n|---:|---|---|---|---|\n"
            "| 1 | TASK-007 | P0 | QUEUED | — |\n",
            encoding="utf-8",
        )
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "PROJECT_WORKFLOW.md").write_text(
            "<!-- MERIDIAN:BEGIN capability=execution-assets v1 -->\n<!-- MERIDIAN:END -->\n"
            "Task files live under `docs/tasks/<milestone>/`; queue is `docs/TASK_QUEUE.md`.\n\n## Roles\n",
            encoding="utf-8",
        )
        nested_task = self.project / "docs/tasks/M19/TASK-007.md"
        nested_task.write_text(
            nested_task.read_text(encoding="utf-8") + "\n" + owner_tasks_preflight.execution_contract(self.project, "TASK-007") + "\n",
            encoding="utf-8",
        )
        locations = self.run_cli("locations", "--field", "queue")
        self.assertEqual(locations.stdout.strip(), "docs/TASK_QUEUE.md")
        preflight = self.run_cli("execution", "preflight", "TASK-007")
        self.assertNotEqual(preflight.returncode, 0)
        self.assertIn(
            "BLOCKED QUEUE_STATUS_MISMATCH: rule: the task record and its queue row must agree; sources checked: "
            "Status in docs/tasks/M19/TASK-007.md and the Status column of row TASK-007 in docs/TASK_QUEUE.md; "
            "accepted: equal values; found: task IN_PROGRESS, queue QUEUED; the actor may change "
            "docs/tasks/M19/TASK-007.md and docs/TASK_QUEUE.md together through the lifecycle; resume: change only "
            "the document the message says this actor may change so the statuses are accepted, then rerun meridian "
            "execution preflight TASK-007 --project .",
            preflight.stderr,
        )

    def remediation_project(self, branch: str, record_status: str, queue_status: str = "QUEUED") -> Path:
        """A Git project on `branch` whose queue row is `queue_status` and whose record is `record_status`."""
        subprocess.run(["git", "init", "-q", "-b", branch, str(self.project)], check=True)
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-007.md"
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
        return task

    def test_task_branch_preflight_accepts_every_state_the_workflow_produces(self) -> None:
        # Issue #6: a task branch cannot edit the queue, and a review returns the record to IN_PROGRESS.
        task = self.remediation_project("task-007", "IN_PROGRESS")
        for status in ("QUEUED", "IN_PROGRESS", "CHANGES_REQUESTED", "READY_FOR_REVIEW"):
            with self.subTest(status=status):
                text = task.read_text(encoding="utf-8")
                task.write_text(f"Status: {status}\n" + text.split("\n", 1)[1], encoding="utf-8")
                result = self.run_cli("execution", "preflight", "TASK-007")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_remediation_commands_share_the_preflight_on_a_task_branch(self) -> None:
        self.remediation_project("task-007", "IN_PROGRESS")
        validated = self.run_cli("execution", "validate", "TASK-007", "check")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        investigated = self.run_cli(
            "execution", "investigate", "TASK-007", "--question", "q", "--source", "tasks/TASK-007.md",
            "--finding", "f",
        )
        self.assertNotIn("QUEUE_STATUS_MISMATCH", investigated.stderr)
        self.assertNotIn("TASK_STATUS_REJECTED", investigated.stderr)
        report = self.project / "ready.md"
        report.write_text("## Completion Report — TASK-007\n", encoding="utf-8")
        ready = self.run_cli("execution", "ready-check", "TASK-007", str(report))
        self.assertNotIn("QUEUE_STATUS_MISMATCH", ready.stderr)
        self.assertNotIn("TASK_STATUS_REJECTED", ready.stderr)

    def test_task_branch_preflight_still_rejects_states_the_workflow_cannot_produce(self) -> None:
        self.remediation_project("task-007", "IN_PROGRESS", queue_status="DONE")
        mismatch = self.run_cli("execution", "preflight", "TASK-007")
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn(
            "BLOCKED QUEUE_STATUS_MISMATCH: rule: the task record and its queue row must agree; sources checked: "
            "Status in tasks/TASK-007.md and the Status column of row TASK-007 in tasks/QUEUE.md; accepted: equal "
            "values, or queue QUEUED with task QUEUED, IN_PROGRESS, CHANGES_REQUESTED, READY_FOR_REVIEW; "
            "found: task IN_PROGRESS, queue DONE; on task branch task-007 the actor may change only "
            "tasks/TASK-007.md, and the queue row stays QUEUED; resume: ",
            mismatch.stderr,
        )
        task = self.project / "tasks/TASK-007.md"
        task.write_text(task.read_text(encoding="utf-8").replace("Status: IN_PROGRESS", "Status: ACCEPTED"), encoding="utf-8")
        rejected = self.run_cli("execution", "preflight", "TASK-007")
        self.assertIn(
            "BLOCKED TASK_STATUS_REJECTED: rule: preflight runs only on an open task; field checked: Status in "
            "tasks/TASK-007.md; accepted: QUEUED, IN_PROGRESS, CHANGES_REQUESTED, READY_FOR_REVIEW; found: ACCEPTED",
            rejected.stderr,
        )

    def test_outside_the_task_branch_the_record_and_queue_must_still_agree(self) -> None:
        self.remediation_project("main", "IN_PROGRESS")
        result = self.run_cli("execution", "preflight", "TASK-007")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("accepted: equal values; found: task IN_PROGRESS, queue QUEUED", result.stderr)
        self.assertIn("together through the lifecycle", result.stderr)
        task = self.project / "tasks/TASK-007.md"
        task.write_text(task.read_text(encoding="utf-8").replace("Status: IN_PROGRESS", "Status: CHANGES_REQUESTED"), encoding="utf-8")
        self.assertIn("accepted: QUEUED, IN_PROGRESS; found: CHANGES_REQUESTED", self.run_cli("execution", "preflight", "TASK-007").stderr)

    def test_execution_preflight_requires_profile_and_task_contract(self) -> None:
        self.write_task("TASK-008", "QUEUED")
        missing = self.run_cli("execution", "preflight", "TASK-008")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("BLOCKED EXECUTION_PROFILE_MISSING:", missing.stderr)
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-008.md").write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-008")
        passed = self.run_cli("execution", "preflight", "TASK-008")
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn("Execution contract:", passed.stdout)

    def test_execution_preflight_uses_spike_shape(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-018.md"
        task.write_text(
            "Status: QUEUED\nClass: SPIKE\nQuestion: What behavior is correct?\n"
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
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn("BLOCKED TASK_RECORD_INCOMPLETE:", blocked.stderr)
                self.assertIn(f"missing: {field}", blocked.stderr)
                task.write_text(text, encoding="utf-8")

    def test_execution_preflight_validates_host_impact_declarations(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-019.md"
        base = "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n"
        not_applicable = "\n## Host impact\n\nClassification: NOT_APPLICABLE\nRationale: This task changes only application behavior.\n"
        task.write_text(base + not_applicable, encoding="utf-8")
        self.append_contract("TASK-019")
        self.assertEqual(self.run_cli("execution", "preflight", "TASK-019").returncode, 0)

        task.write_text(task.read_text(encoding="utf-8").replace("Rationale: This task changes only application behavior.\n", ""), encoding="utf-8")
        missing_rationale = self.run_cli("execution", "preflight", "TASK-019")
        self.assertNotEqual(missing_rationale.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing_rationale),
            "BLOCKED HOST_IMPACT_DECLARATION_INVALID: NOT_APPLICABLE declaration is missing Rationale; resume: correct "
            "the task's Host impact declaration as the detail names, then rerun the blocked meridian execution command",
        )

        required = """Classification: REQUIRED
Policy outcome: The lifecycle gate validates host-impact evidence.

| Profile | Before | Intended after | Activation preconditions | Fallback |
|---|---|---|---|---|
| Meridian CLI / direct invocation / project | advisory | enforced | Run through execution. | Block missing evidence. |

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
        self.assertNotEqual(missing_evidence.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing_evidence),
            "BLOCKED HOST_IMPACT_DECLARATION_INVALID: REQUIRED declaration is missing Host execution evidence plan; "
            "resume: correct the task's Host impact declaration as the detail names, then rerun the blocked meridian "
            "execution command",
        )

    def test_ready_check_requires_evidence_only_for_enforced_host_profiles(self) -> None:
        (self.project / "docs").mkdir(exist_ok=True)
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-020.md"
        task.write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n"
            "## Host impact\n\nClassification: REQUIRED\nPolicy outcome: Accurate host claims.\n\n"
            "| Profile | Before | Intended after | Activation preconditions | Fallback |\n"
            "|---|---|---|---|---|\n"
            "| Meridian CLI / direct / project | advisory | enforced | Run execution. | Block claim. |\n"
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
        missing = self.run_cli("execution", "ready-check", "TASK-020", str(report))
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing),
            "BLOCKED HOST_IMPACT_EVIDENCE_MISSING: enforced profile is missing Completion evidence: Meridian CLI / "
            "direct / project; resume: add a Completion evidence entry for each listed profile to the task's Host "
            "impact section, then rerun the blocked meridian execution command",
        )

        task.write_text(
            task.read_text(encoding="utf-8").replace(
                "\n## Execution contract — resolved",
                "\nCompletion evidence:\n- [Meridian CLI / direct / project]: fixture observed the gate.\n"
                "\n## Execution contract — resolved",
            ),
            encoding="utf-8",
        )
        passed = self.run_cli("execution", "ready-check", "TASK-020", str(report))
        self.assertEqual(passed.returncode, 0, passed.stderr)

    def test_reconcile_upgrades_a_nonterminal_legacy_contract_before_preflight(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-014.md"
        task.write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n## Completion\n",
            encoding="utf-8",
        )
        legacy_contract = owner_tasks_preflight.execution_contract(self.project, "TASK-014").replace(
            "- Execution commands: `required via meridian execution`", ""
        )
        task.write_text(task.read_text(encoding="utf-8").replace("## Completion", legacy_contract + "\n\n## Completion"), encoding="utf-8")
        blocked = self.run_cli("execution", "preflight", "TASK-014")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("BLOCKED EXECUTION_CONTRACT_UNRESOLVED:", blocked.stderr)
        self.assertIn("`required via meridian execution`", blocked.stderr)
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
        task.write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
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
        task.write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `cargo fmt --check`\n",
            encoding="utf-8",
        )

        reconcile = self.run_cli("execution", "reconcile", "TASK-017")
        self.assertNotEqual(reconcile.returncode, 0)
        self.assertIn("BLOCKED VALIDATION_ENTRY_FORMAT:", reconcile.stderr)
        preflight = self.run_cli("execution", "preflight", "TASK-017")
        self.assertNotEqual(preflight.returncode, 0)
        self.assertIn("BLOCKED VALIDATION_ENTRY_FORMAT:", preflight.stderr)

    def test_reconcile_preserves_terminal_task_history(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-015.md"
        task.write_text("Status: ACCEPTED\n\n## Completion\n- historical record\n", encoding="utf-8")
        original = task.read_text(encoding="utf-8")
        result = self.run_cli("execution", "reconcile", "TASK-015", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped for terminal task", result.stdout)
        self.assertEqual(task.read_text(encoding="utf-8"), original)


    def test_ready_check_combines_preflight_and_handoff(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-012.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n## Validation\n",
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
        result = self.run_cli("execution", "ready-check", "TASK-012", str(report))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("READY_FOR_REVIEW gate passed", result.stdout)

    def test_handoff_rejects_fabricated_validation_and_requires_recorded_investigation(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-013.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `probe`: `printf validation-ok`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-013")
        report = self.project / "evidence.md"
        report.write_text(
            "## Completion Report — TASK-013\n\n- Files changed: none\n"
            "- Validation: `printf validation-ok` exit 0\n- Manual verification: none\n"
            "- Validation skips: none\n"
            "- Acceptance criteria: all met\n"
            "- Isolated exploration: none\n- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        fabricated = self.run_cli("execution", "handoff-check", "TASK-013", str(report))
        self.assertNotEqual(fabricated.returncode, 0)
        self.assertIn("BLOCKED HANDOFF_VALIDATION_EVIDENCE_MISSING:", fabricated.stderr)

        self.assertEqual(self.run_cli("execution", "validate", "TASK-013", "probe").returncode, 0)
        investigated = self.run_cli(
            "execution", "investigate", "TASK-013", "--question", "Which API owns the value?",
            "--scope", "2", "--source", "vendor/api.rs", "--finding", "Window owns the value.",
        )
        self.assertEqual(investigated.returncode, 0, investigated.stderr)
        self.assertIn("Investigation TASK-013: recorded", investigated.stdout)
        missing_question = self.run_cli("execution", "handoff-check", "TASK-013", str(report))
        self.assertNotEqual(missing_question.returncode, 0)
        self.assertIn("BLOCKED HANDOFF_EXPLORATION_MISMATCH:", missing_question.stderr)
        self.assertIn("found: `none` with 1 recorded", missing_question.stderr)
        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Isolated exploration: none",
                "- Isolated exploration: Which API owns the value? — Window owns the value.",
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("execution", "handoff-check", "TASK-013", str(report)).returncode, 0)

    def test_handoff_accepts_report_with_or_without_rule_discrepancies(self) -> None:
        self.write_task("TASK-009", "IN_PROGRESS")
        report = self.project / "rule-discrepancies.md"
        body = (
            "## Completion Report — TASK-009\n\n- Files changed: none\n"
            "- Validation: `python3 -m unittest discover -s tests -v` exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n"
            "- Isolated exploration: none\n"
            "%s- Blockers/deviations: none\n"
        )
        for extra in (
            "",
            "- Rule discrepancies: none\n",
            "- Rule discrepancies: `main` ahead of origin; integrate stage accepted it; followed the command\n",
        ):
            report.write_text(body % extra, encoding="utf-8")
            result = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_handoff_accepts_non_project_specific_skips_and_rejects_failures(self) -> None:
        self.write_task("TASK-009", "IN_PROGRESS")
        report = self.project / "validation-skips.md"
        report.write_text(
            "## Completion Report — TASK-009\n\n- Files changed: none\n"
            "- Validation: `python3 -m unittest discover -s tests -v` exit 0\n"
            "- Validation skips: none\n"
            "- Manual verification: none\n- Acceptance criteria: all met\n"
            "- Isolated exploration: none\n"
            "- Blockers/deviations: none\n",
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("execution", "handoff-check", "TASK-009", str(report)).returncode, 0)

        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Validation skips: none\n",
                "- Validation skips: ConsumerSuite.test_unavailable_service — service unavailable; "
                "reported by `consumer-test --network`\n",
            ),
            encoding="utf-8",
        )
        documented_form = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertEqual(documented_form.returncode, 0, documented_form.stderr)

        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Validation skips: ConsumerSuite.test_unavailable_service — service unavailable; "
                "reported by `consumer-test --network`\n",
                "- Validation skips: network fixture unavailable\n",
            ),
            encoding="utf-8",
        )
        free_text = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertEqual(free_text.returncode, 0, free_text.stderr)

        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Validation: `python3 -m unittest discover -s tests -v` exit 0\n"
                "- Validation skips: network fixture unavailable\n",
                "- Validation: `python3 -m unittest discover -s tests -v` exit 1\n"
                "- Validation skips: none\n",
            ),
            encoding="utf-8",
        )
        rejected = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("BLOCKED HANDOFF_VALIDATION_FAILING:", rejected.stderr)
        self.assertIn("a failing validation needs a named skip", rejected.stderr)

        report.write_text(
            report.read_text(encoding="utf-8").replace(
                "- Validation skips: none\n",
                "- Validation skips: network fixture unavailable\n",
            ),
            encoding="utf-8",
        )
        named_skip_failure = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertNotEqual(named_skip_failure.returncode, 0)
        self.assertIn("a named skip does not make a failing validation pass", named_skip_failure.stderr)

        report.write_text(
            report.read_text(encoding="utf-8").replace("- Validation skips: network fixture unavailable\n", ""),
            encoding="utf-8",
        )
        absent = self.run_cli("execution", "handoff-check", "TASK-009", str(report))
        self.assertNotEqual(absent.returncode, 0)
        self.assertIn("Validation skips", absent.stderr)

    def blocked_line(self, result: subprocess.CompletedProcess[str]) -> str:
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        return next(line for line in result.stderr.splitlines() if line.startswith("BLOCKED "))

    def test_unresolved_contract_recovery_runs_unchanged(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-020.md").write_text(
            "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n", encoding="utf-8")
        stopped = self.run_cli("execution", "preflight", "TASK-020")
        self.assertIn("BLOCKED EXECUTION_CONTRACT_UNRESOLVED:", self.blocked_line(stopped))
        recovered = run_recovery(resume_from(stopped.stderr), self.project)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        retried = self.run_cli("execution", "preflight", "TASK-020")
        self.assertEqual(retried.returncode, 0, retried.stderr)

    def test_execution_gates_report_coded_actionable_stops(self) -> None:
        self.write_task("TASK-020", "QUEUED")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED EXECUTION_PROFILE_MISSING: rule: the execution contract derives from the project profile; "
            "source checked: docs/EXECUTION_EVIDENCE_PROFILE.md; expected: the file exists; found: no such file; "
            "resume: add docs/EXECUTION_EVIDENCE_PROFILE.md to the project, then rerun the blocked meridian "
            "execution command",
        )
        (self.project / "docs").mkdir()
        profile = self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md"
        profile.write_text("profile\n", encoding="utf-8")
        task = self.project / "tasks/TASK-020.md"
        body = "Status: QUEUED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n"
        task.write_text(body, encoding="utf-8")
        digest = owner_tasks_contract.profile_digest(self.project)
        resume = "resume: meridian execution reconcile TASK-020 --apply --project ."
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED EXECUTION_CONTRACT_UNRESOLVED: rule: a task needs a resolved execution contract; field "
            f"checked: `- Profile revision` in tasks/TASK-020.md; expected: sha256:{digest}; found: no such line; "
            + resume,
        )
        self.append_contract("TASK-020")
        profile.write_text("changed profile\n", encoding="utf-8")
        changed = owner_tasks_contract.profile_digest(self.project)
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED EXECUTION_CONTRACT_UNRESOLVED: rule: the resolved contract must match the current profile; "
            "field checked: `- Profile revision` in tasks/TASK-020.md against docs/EXECUTION_EVIDENCE_PROFILE.md; "
            f"expected: sha256:{changed}; found: sha256:{digest}; " + resume,
        )
        task.write_text(body.replace("## Expected code surface\n\n", ""), encoding="utf-8")
        self.append_contract("TASK-020")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED TASK_RECORD_INCOMPLETE: rule: a normal task record must contain its required headings; source "
            "checked: tasks/TASK-020.md; accepted: ## Authority, ## Validation, ## Expected code surface; missing: "
            "## Expected code surface; resume: add the listed sections or fields to the task record, then rerun "
            "meridian execution preflight TASK-020 --project .",
        )
        task.write_text(body.replace("QUEUED", "ACCEPTED"), encoding="utf-8")
        self.append_contract("TASK-020")
        accepted = (
            "resume: bring the task to QUEUED or IN_PROGRESS through its lifecycle, then rerun the blocked "
            "meridian execution command"
        )
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "preflight", "TASK-020")),
            "BLOCKED TASK_STATUS_REJECTED: rule: preflight runs only on an open task; field checked: Status in "
            "tasks/TASK-020.md; accepted: QUEUED, IN_PROGRESS; found: ACCEPTED; " + accepted,
        )
        task.write_text(body.replace("QUEUED", "DRAFT"), encoding="utf-8")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "reconcile", "TASK-020")),
            "BLOCKED TASK_STATUS_REJECTED: rule: reconcile refreshes only an open task; field checked: Status in "
            "tasks/TASK-020.md; accepted: QUEUED, IN_PROGRESS (terminal tasks are skipped); found: DRAFT; " + accepted,
        )
        task.write_text(body + "\n- `cargo fmt --check`\n", encoding="utf-8")
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "reconcile", "TASK-020")),
            "BLOCKED VALIDATION_ENTRY_FORMAT: rule: every entry in the task's ## Validation section must be a named "
            "literal command; accepted form: - `validation-id`: `literal command`; found: '- `cargo fmt --check`'; "
            "resume: rewrite each listed Validation entry as - `validation-id`: `literal command`, then rerun the "
            "blocked meridian execution command",
        )
        self.assertEqual(
            self.blocked_line(self.run_cli("execution", "evidence", "TASK-020", "diagnostic", "--gap", " ")),
            "BLOCKED EXECUTION_EVIDENCE_ARGUMENTS: rule: evidence is recorded with the gap that justifies it; option "
            "checked: --gap; accepted: a non-empty string; found: ' '; resume: rerun the meridian execution evidence "
            "command with the missing options",
        )
        self.assertIn(
            "missing: --artifact",
            self.blocked_line(self.run_cli(
                "execution", "evidence", "TASK-020", "captures", "--gap", "g", "--criterion", "AC-1",
            )),
        )

    def test_handoff_gates_report_coded_actionable_stops(self) -> None:
        self.write_task("TASK-021", "IN_PROGRESS")
        report = self.project / "report.md"
        fields = {
            "Files changed": "none", "Validation": "`x` exit 0", "Validation skips": "none",
            "Manual verification": "none", "Acceptance criteria": "all met",
            "Isolated exploration": "none", "Blockers/deviations": "none",
        }

        def write(heading: str = "TASK-021", **overrides: str | None) -> None:
            lines = [f"## Completion Report — {heading}", ""]
            for field, value in {**fields, **overrides}.items():
                if value is not None:
                    lines.append(f"- {field}: {value}")
            report.write_text("\n".join(lines) + "\n", encoding="utf-8")

        def check() -> subprocess.CompletedProcess[str]:
            return self.run_cli("execution", "handoff-check", "TASK-021", str(report))

        resume = "then rerun meridian execution handoff-check TASK-021 <report> --project ."
        self.assertEqual(
            self.blocked_line(check()),
            f"BLOCKED HANDOFF_REPORT_MISSING: rule: the handoff check reads a completion report; source checked: "
            f"{report}; expected: an existing file; found: no such file; resume: write the completion report, "
            "then run meridian execution handoff-check TASK-021 <report> --project .",
        )
        required = ", ".join(fields)
        write(Validation=None)
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_FIELDS_MISSING: rule: every required field needs a non-empty value; source checked: "
            "report.md; accepted form: `- <Field>: <value>`; required: " + required + "; missing: Validation; "
            "resume: add each missing field as `- <Field>: <value>`, " + resume,
        )
        report.write_text(report.read_text(encoding="utf-8") + "- Validation (commands): `x` exit 0\n", encoding="utf-8")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_FIELD_FORMAT: rule: a required field's name must be followed directly by the colon; "
            "source checked: report.md; accepted form: `- <Field>: <value>`; found: `- Validation (commands):` "
            "(expected `- Validation: <value>`); resume: rewrite each listed field as `- <Field>: <value>`, " + resume,
        )
        write("TASK-099")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_TASK_MISMATCH: rule: the report must identify its task; source checked: report.md; "
            "accepted: `Completion Report — TASK-021`; found: `Completion Report — TASK-099`; resume: correct "
            "the report heading to name this task, " + resume,
        )
        write(Validation="`x` exit 1")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_VALIDATION_FAILING: rule: a failing validation needs a named skip; field checked: "
            "Validation; accepted: no `exit <non-zero>`; found: `exit 1` with Validation skips: none; resume: fix "
            "the failing validation and report its passing result, " + resume,
        )
        write(Validation="`x` exit 1", **{"Validation skips": "network down"})
        self.assertIn(
            "rule: a named skip does not make a failing validation pass; field checked: Validation; accepted: no "
            "`exit <non-zero>`; found: `exit 1` with Validation skips: network down;",
            self.blocked_line(check()),
        )

    def test_handoff_isolated_exploration_and_durable_evidence_gates(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-022.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `probe`: `printf ok`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-022")
        report = self.project / "report.md"

        def write(exploration: str) -> None:
            report.write_text(
                "## Completion Report — TASK-022\n\n- Files changed: none\n- Validation: `printf ok` exit 0\n"
                "- Validation skips: none\n- Manual verification: none\n- Acceptance criteria: all met\n"
                f"- Isolated exploration: {exploration}\n- Blockers/deviations: none\n",
                encoding="utf-8",
            )

        def check() -> subprocess.CompletedProcess[str]:
            return self.run_cli("execution", "handoff-check", "TASK-022", str(report))

        write("none")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_VALIDATION_EVIDENCE_MISSING: rule: every declared validation needs a successful durable "
            "record; source checked: .meridian/execution-evidence.json for TASK-022; accepted: an entry with the "
            "declared id and command and exitStatus 0; missing for: probe; resume: run meridian execution validate "
            "TASK-022 <validation-id> --project . for each listed ID, then rerun the handoff check",
        )
        self.assertEqual(self.run_cli("execution", "validate", "TASK-022", "probe").returncode, 0)
        for accepted in ("none", "None", "none needed", "No isolated exploration was needed", "no"):
            with self.subTest(accepted=accepted):
                write(accepted)
                self.assertEqual(check().returncode, 0, accepted)
        write("explored the API")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_EXPLORATION_MISMATCH: rule: with no recorded investigation the report must say there was "
            "none; field checked: Isolated exploration against .meridian/execution-evidence.json; accepted: `none`, "
            "or text starting with `none` or `no`; found: 'explored the API'; expected `none` (or record the "
            "investigation); resume: correct the Isolated exploration field or record the investigation with meridian "
            "execution investigate TASK-022, then rerun the handoff check",
        )
        write("nothing")
        self.assertIn("found: 'nothing'", self.blocked_line(check()))
        self.assertEqual(
            self.run_cli(
                "execution", "investigate", "TASK-022", "--question", "Which API?", "--scope", "2",
                "--source", "a.rs", "--finding", "The window API.",
            ).returncode,
            0,
        )
        write("none")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_EXPLORATION_MISMATCH: rule: recorded investigations must be reported; field checked: "
            "Isolated exploration against .meridian/execution-evidence.json; accepted: a summary of each recorded "
            "investigation; found: `none` with 1 recorded; resume: correct the Isolated exploration field or record "
            "the investigation with meridian execution investigate TASK-022, then rerun the handoff check",
        )
        write("Which API?")
        self.assertEqual(
            self.blocked_line(check()),
            "BLOCKED HANDOFF_EXPLORATION_SUMMARY_MISSING: rule: the report must contain each recorded question and "
            "finding; source checked: .meridian/execution-evidence.json; accepted: the exact question and finding "
            "text; missing the question or finding of: Which API?; resume: add each listed question and finding to "
            "the report, then rerun meridian execution handoff-check TASK-022 <report> --project .",
        )

    def test_validation_runs_only_a_declared_literal_command_and_records_status(self) -> None:
        (self.project / "docs").mkdir()
        (self.project / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n", encoding="utf-8")
        (self.project / "tasks/TASK-010.md").write_text(
            "Status: IN_PROGRESS\n\n## Authority\n\n## Expected code surface\n\n"
            "## Validation\n\n- `probe`: `printf validation-ok`\n",
            encoding="utf-8",
        )
        self.append_contract("TASK-010")
        result = self.run_cli("execution", "validate", "TASK-010", "probe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("validation-ok", result.stdout)
        evidence = json.loads((self.project / ".meridian/execution-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["TASK-010"][0]["id"], "probe")
        missing = self.run_cli("execution", "validate", "TASK-010", "not-declared")
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(
            self.blocked_line(missing),
            "BLOCKED VALIDATION_ID_UNDECLARED: rule: only a task-declared validation ID runs; field checked: "
            "Validation in the TASK-010 record; accepted: probe; found: 'not-declared'; resume: rerun meridian "
            "execution validate with a validation ID listed in the task's Validation section, or declare the command "
            "there first",
        )

    def test_evidence_requires_a_gap_and_capture_provenance(self) -> None:
        self.write_task("TASK-011", "IN_PROGRESS")
        missing = self.run_cli("execution", "evidence", "TASK-011", "captures", "--gap", "text is perceptual")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("BLOCKED EXECUTION_EVIDENCE_ARGUMENTS:", missing.stderr)
        self.assertIn("missing: --criterion, --artifact", missing.stderr)
        recorded = self.run_cli(
            "execution", "evidence", "TASK-011", "captures", "--gap", "text is perceptual",
            "--criterion", "AC-4", "--artifact", "/tmp/capture.png",
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        evidence = json.loads((self.project / ".meridian/execution-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["TASK-011"][0]["criterion"], "AC-4")
        self.assertEqual(evidence["TASK-011"][0]["artifact"], "/tmp/capture.png")
        other = self.run_cli(
            "execution", "evidence", "TASK-011", "captures", "--gap", "second criterion",
            "--criterion", "AC-5", "--artifact", "/tmp/second.png",
        )
        self.assertEqual(other.returncode, 0, other.stderr)
        self.assertNotIn("count", evidence["TASK-011"][0])
        self.assertNotIn("cap", evidence["TASK-011"][0])


    def test_evidence_has_no_capture_cap_or_budget_ledger(self) -> None:
        self.write_task("TASK-011", "IN_PROGRESS")
        for index in range(4):
            recorded = self.run_cli(
                "execution", "evidence", "TASK-011", "captures", "--gap", "rendered property",
                "--criterion", "AC-1", "--artifact", f"capture-{index}.png",
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
        events = json.loads((self.project / ".meridian/execution-evidence.json").read_text())["TASK-011"]
        self.assertEqual(len(events), 4)
        self.assertTrue(all("count" not in event and "cap" not in event for event in events))
        self.assertFalse((self.project / ".meridian/budget.json").exists())

    def test_budget_command_is_removed(self) -> None:
        rejected = self.run_cli("budget", "show", "TASK-011")
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn("invalid choice: 'budget'", rejected.stderr)

    def test_investigation_arguments_name_the_missing_options(self) -> None:
        self.write_task("TASK-406", "IN_PROGRESS")
        result = self.run_cli("execution", "investigate", "TASK-406", "--question", " ", "--scope", "1", "--source", "x", "--finding", "")
        self.assertEqual(
            self.blocked_line(result),
            "BLOCKED EXECUTION_EVIDENCE_ARGUMENTS: rule: an investigation records its question, sources, and finding; "
            "options checked: --question, --source, --finding; accepted: a non-empty value for each; found: missing or "
            "empty --question, --finding; resume: rerun meridian execution investigate with --question, --source, and "
            "--finding",
        )

    def test_uncoded_command_refusal_reports_command_refused(self) -> None:
        refused = self.run_cli("task", "identity", "check", "TASK-404", "--format", "json")
        line = self.blocked_line(refused)
        self.assertTrue(line.startswith("BLOCKED COMMAND_REFUSED: "), line)
        self.assertTrue(
            line.endswith("; resume: correct the condition that the detail names, then rerun the same meridian command"),
            line,
        )
        self.assertNotIn("BLOCKED:", refused.stderr)

    def test_operating_system_failure_reports_os_access_failed(self) -> None:
        self.write_task("TASK-405", "IN_PROGRESS")
        (self.project / ".meridian").mkdir()
        (self.project / ".meridian/execution-evidence.json").mkdir()
        failed = self.run_cli("execution", "evidence", "TASK-405", "diagnostic", "--gap", "missing output")
        line = self.blocked_line(failed)
        self.assertTrue(line.startswith("BLOCKED OS_ACCESS_FAILED: "), line)
        self.assertTrue(
            line.endswith("; resume: fix the access problem that the detail names, then rerun the same meridian command"),
            line,
        )
