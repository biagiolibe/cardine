"""Framework CLI regression tests for launcher task audit."""

from __future__ import annotations

from cardine_cli_support import ROOT
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from cardine.templates import audit as owner_templates_audit
from cardine.tasks import audit as owner_tasks_audit


class LauncherTest(unittest.TestCase):
    def test_the_bin_launcher_starts_outside_the_scripts_directory(self) -> None:
        # The source launcher must resolve the package and script hook adapters
        # from its own checkout when invoked outside the repository.
        environment = dict(os.environ)
        environment.pop("CARDINE_ROOT", None)
        result = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "cardine"), "--version"],
            cwd=tempfile.gettempdir(), capture_output=True, text=True, check=False,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), (ROOT / "VERSION").read_text(encoding="utf-8").strip())


class TaskStateAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / "tasks").mkdir()
        (self.project / ".cardine/tasks").mkdir(parents=True)
        (self.project / "tasks/001.md").write_text("# Task 001 — Task\nStatus: queued\n")
        (self.project / "tasks/QUEUE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | queued | [001](001.md) |\n")
        self.path = self.project / ".cardine/tasks/001.json"
        self.path.write_text(json.dumps({"version": 1, "task_id": "001", "workflow": "single",
                                         "status": "queued", "transitions": []}))
        from task_contract_support import freeze_record
        freeze_record(self.project, '001')

    def test_audit_pass_and_drift_are_one_read_only_row_per_state(self):
        before = {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        rows = owner_tasks_audit.audit_task_state_projections(self.project, "single")
        self.assertEqual(len([r for r in rows if r.identity == "task-state"]), 1)
        self.assertEqual(rows[0].status, "PASS")
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        (self.project / "tasks/001.md").write_text("# Task 001 — Changed\nStatus: ACCEPTED\n")
        (self.project / "tasks/QUEUE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | in_progress | [001](001.md) |\n")
        before = {p: p.read_bytes() for p in before}
        rows = owner_tasks_audit.audit_task_state_projections(self.project, "single")
        self.assertEqual(len([r for r in rows if r.identity == "task-state"]), 1)
        self.assertEqual(rows[0].status, "PASS")
        generated = [row for row in rows if row.identity == "generated-status"]
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0].status, "ADVISORY")
        contracts = [row for row in rows if row.identity == "task-contract"]
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0].status, "ADVISORY")
        self.assertIn("contract drift", contracts[0].detail)
        self.assertIn("cardine task contract update 001", contracts[0].detail)
        self.assertIn(".cardine/tasks/001.json", rows[0].detail)
        self.assertIn("cardine status --write", generated[0].detail)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with mock.patch.object(owner_templates_audit, "audit_declared_capabilities", return_value=([], "single")), \
                mock.patch.object(owner_templates_audit, "audit_capability_markers", return_value=[]), \
                mock.patch.object(owner_templates_audit, "audit_duplicate_headings", return_value=[]), \
                mock.patch.object(owner_templates_audit, "audit_capability_moves", return_value=[]), \
                mock.patch.object(owner_templates_audit, "audit_entry_router", return_value=[]), redirect_stdout(io.StringIO()) as out:
            owner_templates_audit.run_audit(self.project, ROOT, "single")
        self.assertRegex(out.getvalue(), r"ADVISORY\s+generated-status")

    def test_audit_invalid_state_is_coded_and_other_rows_survive(self):
        self.path.write_text("not JSON")
        rows = owner_tasks_audit.audit_task_state_projections(self.project, "single")
        self.assertEqual(rows[0].status, "FAIL")
        self.assertIn("TASK_STATE_INVALID", rows[0].detail)

    def test_audit_normalizes_lean_checkbox_and_finds_archived_records(self):
        (self.project / "tasks/done").mkdir()
        (self.project / "tasks/001.md").rename(self.project / "tasks/done/001.md")
        (self.project / "tasks/done/001.md").write_text("# Task 001 — Task\nStatus: done\n")
        (self.project / "tasks/QUEUE.md").write_text("")
        (self.project / "tasks/QUEUE_ARCHIVE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | `[x]` | — |\n")
        self.path.write_text(json.dumps({"version": 1, "task_id": "001", "workflow": "single",
            "status": "done", "transitions": [{"from": before, "to": after, "commit": "a" * 40,
                                                "at": "2026-10-11T12:00:00Z"}
                                               for before, after in (("queued", "in_progress"), ("in_progress", "done"))]}))
        from task_contract_support import freeze_record
        freeze_record(self.project, '001', self.project / 'tasks/done/001.md')
        rows = owner_tasks_audit.audit_task_state_projections(self.project, "single")
        self.assertEqual(rows[0].status, "PASS")
