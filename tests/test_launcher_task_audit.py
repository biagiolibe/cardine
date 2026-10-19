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
        (self.project / ".meridian/tasks").mkdir(parents=True)
        (self.project / "tasks/001.md").write_text("# Task 001 — Task\nStatus: QUEUED\n")
        (self.project / "tasks/QUEUE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | QUEUED | [001](001.md) |\n")
        self.path = self.project / ".meridian/tasks/001.json"
        self.path.write_text(json.dumps({"version": 1, "task_id": "001", "workflow": "governed-sdd",
                                         "status": "QUEUED", "transitions": []}))

    def test_audit_pass_and_drift_are_one_read_only_row_per_state(self):
        before = {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        rows = owner_tasks_audit.audit_task_state_projections(self.project, "governed-sdd")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "PASS")
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        (self.project / "tasks/001.md").write_text("# Task 001 — Task\nStatus: ACCEPTED\n")
        (self.project / "tasks/QUEUE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | IN_PROGRESS | [001](001.md) |\n")
        before = {p: p.read_bytes() for p in before}
        rows = owner_tasks_audit.audit_task_state_projections(self.project, "governed-sdd")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "ADVISORY")
        self.assertIn(".meridian/tasks/001.json", rows[0].detail)
        self.assertIn("tasks/QUEUE.md queue Status: state=QUEUED, projection=IN_PROGRESS", rows[0].detail)
        self.assertIn("tasks/001.md record Status: state=QUEUED, projection=ACCEPTED", rows[0].detail)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        with mock.patch.object(owner_templates_audit, "audit_declared_capabilities", return_value=([], "governed-sdd")), \
                mock.patch.object(owner_templates_audit, "audit_capability_markers", return_value=[]), \
                mock.patch.object(owner_templates_audit, "audit_duplicate_headings", return_value=[]), \
                mock.patch.object(owner_templates_audit, "audit_capability_moves", return_value=[]), \
                mock.patch.object(owner_templates_audit, "audit_entry_router", return_value=[]), redirect_stdout(io.StringIO()) as out:
            owner_templates_audit.run_audit(self.project, ROOT, "governed-sdd")
        self.assertRegex(out.getvalue(), r"ADVISORY\s+task-state")

    def test_audit_invalid_state_is_coded_and_other_rows_survive(self):
        self.path.write_text("not JSON")
        rows = owner_tasks_audit.audit_task_state_projections(self.project, "governed-sdd")
        self.assertEqual(rows[0].status, "FAIL")
        self.assertIn("TASK_STATE_INVALID", rows[0].detail)

    def test_audit_normalizes_lean_checkbox_and_finds_archived_records(self):
        (self.project / "tasks/done").mkdir()
        (self.project / "tasks/001.md").rename(self.project / "tasks/done/001.md")
        (self.project / "tasks/done/001.md").write_text("# Task 001 — Task\nStatus: DONE\n")
        (self.project / "tasks/QUEUE.md").write_text("")
        (self.project / "tasks/QUEUE_ARCHIVE.md").write_text(
            "| ID | Status | File |\n|---|---|---|\n| 001 | `[x]` | — |\n")
        self.path.write_text(json.dumps({"version": 1, "task_id": "001", "workflow": "lean-delivery",
            "status": "DONE", "transitions": [{"from": "QUEUED", "to": "DONE", "commit": "a" * 40,
                                                "at": "2026-10-11T12:00:00Z"}]}))
        rows = owner_tasks_audit.audit_task_state_projections(self.project, "lean-delivery")
        self.assertEqual(rows[0].status, "PASS")
