"""Preset display on isolated Claude and Codex hook invocations."""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import unittest

from installation_fixture import run_host_briefing
from project_config_support import write_project_config
from test_queue_briefing import GOVERNED_HEADER

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cardine.hosts.briefing import render_briefing


class SingleWorkflowBriefingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        (self.project / "tasks").mkdir()

    def write_queue(self, text):
        (self.project / "tasks/QUEUE.md").write_text(text, encoding="utf-8")

    def assert_hosts(self, preset):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = run_host_briefing(self.project, host)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines()[0], f"Preset: {preset}")
                # MERIDIAN-INSTALLATION-CHECK: copied-hook headings must be replaced.
                self.assertNotIn("[Meridian Governed Queue]", result.stdout)
                # MERIDIAN-INSTALLATION-CHECK
                self.assertNotIn("[Meridian Lean Delivery Queue]", result.stdout)

    def test_empty_queue_after_all_closed_phases_are_archived_on_both_hosts(self):
        for preset in ("lean", "governed"):
            with self.subTest(preset=preset):
                write_project_config(self.project, preset)
                self.write_queue("# Task Execution Queue\n\nNo open phases.\n")
                (self.project / "tasks/QUEUE_ARCHIVE.md").write_text(
                    GOVERNED_HEADER + "| 1 | TASK-001 | P1 | ACCEPTED | REQUIRED | — | done/001.md |\n",
                    encoding="utf-8",
                )
                self.assert_hosts(preset)

    def test_governed_looking_table_cannot_override_lean_configuration(self):
        write_project_config(self.project, "lean")
        self.write_queue(GOVERNED_HEADER + "| 1 | TASK-001 | P1 | QUEUED | REQUIRED | — | 001.md |\n")
        self.assert_hosts("lean")

    def test_workflow_text_cannot_override_configuration_without_a_queue(self):
        write_project_config(self.project, "governed")
        (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n", encoding="utf-8")
        self.assert_hosts("governed")

    def test_missing_configuration_is_a_diagnostic_on_both_hosts(self):
        self.write_queue(GOVERNED_HEADER)
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = run_host_briefing(self.project, host)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("Briefing configuration error: missing project configuration", result.stderr)

    def test_malformed_and_invalid_configuration_fail_closed_on_both_hosts(self):
        self.write_queue(GOVERNED_HEADER)
        write_project_config(self.project)
        for declaration in ('{', '{"version":1,"preset":"unknown"}',
                            '{"version":1,"preset":"lean","unexpected":true}'):
            (self.project / ".cardine/project.json").write_text(declaration, encoding="utf-8")
            for host in ("claude", "codex"):
                with self.subTest(host=host, declaration=declaration):
                    result = run_host_briefing(self.project, host)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("Briefing configuration error:", result.stderr)

    def test_adapter_preserves_non_heading_payload_exactly(self):
        write_project_config(self.project)
        # MERIDIAN-INSTALLATION-CHECK: exact frozen-hook payload compatibility.
        payload = "[Meridian Language Policy]\r\n  Conversation language: Italian\r\n"
        # MERIDIAN-INSTALLATION-CHECK
        payload += "[Meridian Governed Queue]\r\nQueued (startable): TASK-001\nAccepted: 2"
        self.assertEqual(render_briefing(self.project, payload),
                         # MERIDIAN-INSTALLATION-CHECK
                         "Preset: lean\n" + payload.replace("[Meridian Governed Queue]\r\n", ""))


if __name__ == "__main__":
    unittest.main()
