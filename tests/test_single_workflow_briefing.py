"""Preset display on isolated Claude and Codex hook invocations."""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import unittest

from installation_fixture import run_host_briefing
from project_config_support import write_project_config
from task_state_support import write_task
from task_contract_support import seal_state
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

    def assert_hosts(self, preset, *status_lines):
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = run_host_briefing(self.project, host)
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(lines[0], f"Preset: {preset}")
                self.assertEqual(lines[1:1 + len(status_lines)], list(status_lines))
                # MERIDIAN-INSTALLATION-CHECK: copied-hook headings must be replaced.
                self.assertNotIn("[Meridian Governed Queue]", result.stdout)
                # MERIDIAN-INSTALLATION-CHECK
                self.assertNotIn("[Meridian Lean Delivery Queue]", result.stdout)

    def test_empty_queue_with_closed_phases_still_reports_state_totals_on_both_hosts(self):
        write_project_config(self.project, "lean")
        write_task(self.project, "001", "done")
        write_task(self.project, "002", "queued", "001")
        write_task(self.project, "003", "in_progress")
        for preset in ("lean", "governed"):
            with self.subTest(preset=preset):
                write_project_config(self.project, preset)
                for task_id in ("001", "002", "003"):
                    seal_state(self.project, task_id)
                self.write_queue("# Task Execution Queue\n\nNo open phases.\n")
                (self.project / "tasks/QUEUE_ARCHIVE.md").write_text(
                    GOVERNED_HEADER + "| 1 | TASK-001 | P1 | ACCEPTED | REQUIRED | — | done/001.md |\n",
                    encoding="utf-8",
                )
                self.assert_hosts(
                    preset, "Tasks: queued=1, in_progress=1, in_review=0, done=1, cancelled=0, total=3",
                    "Startable: 002", "In progress: 003")

    def test_no_queue_file_and_no_tasks_report_zero_totals(self):
        write_project_config(self.project, "lean")
        (self.project / "tasks").rmdir()
        self.assert_hosts("lean", "Tasks: queued=0, in_progress=0, in_review=0, done=0, cancelled=0, total=0",
                          "Startable: none")

    def test_queued_queue_row_cannot_make_an_in_progress_or_in_review_task_startable(self):
        write_project_config(self.project, "lean")
        write_task(self.project, "001", "done")
        write_task(self.project, "002", "in_progress", "001")
        write_task(self.project, "003", "in_review", "001")
        self.write_queue("| `[ ]` | 002 | queued | 001 |\n| `[ ]` | 003 | queued | 001 |\n")
        self.assert_hosts(
            "lean", "Tasks: queued=0, in_progress=1, in_review=1, done=1, cancelled=0, total=3",
            "Startable: none", "In progress: 002", "In review: 003")

    def test_invalid_state_is_a_diagnostic_and_not_a_queued_task(self):
        write_project_config(self.project, "lean")
        write_task(self.project, "001", "queued")
        (self.project / ".cardine/tasks/002.json").write_text("{", encoding="utf-8")
        self.assert_hosts(
            "lean", "Tasks: queued=1, in_progress=0, in_review=0, done=0, cancelled=0, total=1",
            "Startable: 001", "Diagnostics: 1; run cardine status")

    def test_governed_looking_table_cannot_override_lean_configuration(self):
        write_project_config(self.project, "lean")
        self.write_queue(GOVERNED_HEADER + "| 1 | TASK-001 | P1 | QUEUED | REQUIRED | — | 001.md |\n")
        self.assert_hosts("lean", "Tasks: queued=0, in_progress=0, in_review=0, done=0, cancelled=0, total=0",
                          "Startable: none")

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

    def test_adapter_replaces_the_queue_block_and_preserves_every_other_byte(self):
        write_project_config(self.project)
        write_task(self.project, "TASK-009", "queued")
        # MERIDIAN-INSTALLATION-CHECK: headings emitted by the frozen copied hook.
        language = "[Meridian Language Policy]\r\n  Conversation language: Italian\r\n"
        # MERIDIAN-INSTALLATION-CHECK: exact frozen-hook payload compatibility.
        queue = "[Meridian Governed Queue]\r\nQueued (startable): TASK-001\n  Accepted: 2\n"
        # MERIDIAN-INSTALLATION-CHECK
        host = "[Meridian Host]\n  note without a trailing newline"
        status = ("Preset: lean\nTasks: queued=1, in_progress=0, in_review=0, done=0, cancelled=0, total=1\n"
                  "Startable: TASK-009\n")
        self.assertEqual(render_briefing(self.project, language + queue + host), status + language + host)
        self.assertEqual(render_briefing(self.project, queue), status)
        self.assertEqual(render_briefing(self.project, language), status + language)

    def test_incomplete_snapshot_is_reported_without_failing_the_hook(self):
        write_project_config(self.project)
        (self.project / ".cardine/task-creation.lock").write_text("held\n", encoding="utf-8")
        output = render_briefing(self.project, "")
        self.assertTrue(output.startswith("Preset: lean\nStatus unavailable: "), output)
        self.assertIn("task creation is in progress", output)


if __name__ == "__main__":
    unittest.main()
