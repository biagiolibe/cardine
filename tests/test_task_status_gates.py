"""Product gates use validated JSON despite contradictory human prose."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import subprocess
import tempfile
import unittest
from unittest import mock

from project_config_support import write_project_config
from task_contract_support import contract_record, write_state, VALIDATION
from cardine.tasks import preflight, transitions, audit, importer
from cardine.tasks.identity import resolve_task_identity
from cardine.shared.errors import CardineStop


class TaskStatusGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        write_project_config(self.root, "lean", validation=VALIDATION)
        (self.root / "tasks").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "docs/EXECUTION_EVIDENCE_PROFILE.md").write_text("profile\n")
        self.record = self.root / "tasks/001.md"
        self.record.write_text(contract_record(extra="Status: cancelled\n"))
        self.record.write_text(self.record.read_text() + "\n" + preflight.execution_contract(self.root, "001") + "\n")
        self.path = write_state(self.root)
        self.queue = self.root / "tasks/QUEUE.md"
        self.queue.write_text("| Order | ID | Status | File |\n|---|---|---|---|\n| 1 | 001 | done | [001](missing.md) |\n")
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.test",
                        "commit", "-qm", "Fixture"], check=True)

    def test_preflight_ignores_record_status_and_queue_agreement(self):
        before = self.record.read_bytes(), self.queue.read_bytes()
        self.assertIn("Execution contract:", preflight.execution_preflight(self.root, "001"))
        self.assertEqual((self.record.read_bytes(), self.queue.read_bytes()), before)
        write_state(self.root, status="done")
        with self.assertRaises(CardineStop) as caught:
            preflight.execution_preflight(self.root, "001")
        self.assertEqual(caught.exception.code, "TASK_STATUS_REJECTED")

    def test_reconcile_uses_state_for_terminal_and_open_tasks(self):
        self.assertNotIn("skipped", preflight.reconcile_execution_contract(self.root, "001", False))
        write_state(self.root, status="done")
        self.record.write_text(self.record.read_text().replace("Status: cancelled", "Status: queued"))
        self.assertIn("terminal task 001 (done)", preflight.reconcile_execution_contract(self.root, "001", True))

    def test_transition_preserves_record_and_queue_bytes(self):
        before = self.record.read_bytes(), self.queue.read_bytes()
        state = transitions.transition_task_state(self.root, "001", "in_progress")
        self.assertEqual(state["status"], "in_progress")
        self.assertEqual((self.record.read_bytes(), self.queue.read_bytes()), before)

    def test_missing_state_never_bootstraps_or_calls_importer(self):
        self.path.unlink()
        before = self.record.read_bytes(), self.queue.read_bytes()
        with mock.patch.object(importer, "import_task_states", side_effect=AssertionError("implicit import")):
            for action in (lambda: transitions.transition_task_state(self.root, "001", "in_progress"),
                           lambda: preflight.execution_preflight(self.root, "001"),
                           lambda: preflight.reconcile_execution_contract(self.root, "001", True)):
                with self.assertRaises(CardineStop) as caught:
                    action()
                self.assertEqual(caught.exception.code, "TASK_STATE_MISSING")
        self.assertFalse(self.path.exists())
        self.assertEqual((self.record.read_bytes(), self.queue.read_bytes()), before)

    def test_identity_ignores_duplicate_stale_and_unsafe_generated_links(self):
        self.queue.write_text(self.queue.read_text().replace("missing.md", "../../outside.md") * 2)
        self.assertEqual(resolve_task_identity(self.root, "001", "existing").task_path, self.record)

    def test_audit_validates_state_and_reports_generated_output_separately(self):
        rows = audit.audit_task_state_projections(self.root, "single")
        states = [row for row in rows if row.identity == "task-state"]
        self.assertEqual([row.status for row in states], ["PASS"])
        generated = [row for row in rows if row.identity == "generated-status"]
        self.assertEqual([row.status for row in generated], ["ADVISORY"])
        self.assertIn("cardine status --write", generated[0].detail)
        self.path.write_text("{")
        self.assertEqual(audit.audit_task_state_projections(self.root, "single")[0].status, "FAIL")


if __name__ == "__main__":
    unittest.main()
