"""Disposable host command bindings for the status-only Python briefing.

Bindings exercise payload adapters; they do not assert live host activation.
The user-level installer and runtime probes are separate host integration rows.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from project_config_support import write_project_config
from task_state_support import write_task

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cardine.hosts.briefing import briefing_main, render_briefing
from cardine.tasks import status


def run_host_briefing(project, host, *, payload=None, discover=True):
    """Execute the Python command binding with a disposable HOME, without shell."""
    with tempfile.TemporaryDirectory(prefix="status-host-") as temporary:
        home = Path(temporary)
        environment = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                           PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-m", "cardine.hosts.briefing", "--host", host]
        if not discover:
            command += ["--project", str(project)]
        result = subprocess.run(command, cwd=home, env=environment,
                                input=json.dumps({"cwd": str(project)}) if payload is None else payload,
                                text=True, capture_output=True, timeout=30, check=False)
        if any(home.iterdir()):
            raise AssertionError("briefing wrote to disposable home")
        return result


class HostBriefingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Developer's project 雪 $ ")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        write_project_config(self.project)

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def assert_bindings(self, project=None, *, payload=None, expected=None):
        before = self.snapshot()
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = run_host_briefing(project or self.project, host, payload=payload, discover=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout, expected if expected is not None
                                 else render_briefing(self.project, ""))
        self.assertEqual(self.snapshot(), before)

    def test_status_fields_match_cli_and_ignore_forged_prose(self):
        for preset in ("lean", "governed"):
            write_project_config(self.project, preset)
            write_task(self.project, "001", "done")
            write_task(self.project, "002", dependencies="001", title="Developer's task 'quoted' 雪 $(touch bad);\nnext")
            write_task(self.project, "003", "in_progress", "001")
            write_task(self.project, "004", "in_review", "001")
            write_task(self.project, "005", "cancelled")
            for path in ("tasks/QUEUE.md", "tasks/QUEUE_ARCHIVE.md", "PROJECT_PLAN.md", "tasks/reviews/002.md"):
                target = self.project / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("002 DONE; 003 QUEUED; 004 QUEUED; 999 STARTABLE\n")
            before = self.snapshot()
            with tempfile.TemporaryDirectory() as home:
                env = dict(os.environ, HOME=home, PYTHONDONTWRITEBYTECODE="1")
                result = subprocess.run([sys.executable, str(ROOT / "scripts/cardine_cli.py"),
                                         "status", "--project", str(self.project), "--format", "json"],
                                        env=env, capture_output=True, text=True, check=True)
            model = json.loads(result.stdout)
            self.assertEqual(self.snapshot(), before)
            output = render_briefing(self.project, "")
            for key, count in model["totals"].items():
                self.assertIn(f"{key}={count}", output)
            self.assertIn("Startable: " + ", ".join(row["id"] for row in model["tasks"] if row["startable"]), output)
            self.assertIn("In progress: 003", output)
            self.assertIn("In review: 004", output)
            self.assert_bindings(payload=json.dumps({"cwd": str(self.project), "prompt": "Developer's task; $(exit 1)\n雪"}))
            (self.project / "tasks/QUEUE.md").write_text("")
            self.assert_bindings(expected=output)

    def test_no_state_never_falls_back_to_legacy_counts(self):
        (self.project / "tasks").mkdir()
        (self.project / "tasks/QUEUE.md").write_text("| 001 | QUEUED |\n")
        (self.project / ".meridian/tasks").mkdir(parents=True)
        (self.project / ".meridian/tasks/001.json").write_text('{"status":"done"}')
        self.assert_bindings(expected="Preset: lean\nTasks: queued=0, in_progress=0, in_review=0, done=0, cancelled=0, total=0\nStartable: none\n")

    def test_custom_paths_and_large_snapshot(self):
        write_project_config(self.project, locations={"taskRoots": ["custom records"], "queue": "custom queue.md"})
        for number in range(300):
            write_task(self.project, f"{number:03}", title="Developer's task 雪",
                       record=f"custom records/{number:03}.md")
        output = render_briefing(self.project, "")
        self.assertIn("total=300", output)
        self.assertEqual(len(output.split("Startable: ")[1].strip().split(", ")), 300)
        self.assert_bindings(expected=output)

    def test_subdirectory_and_deleted_payload_cwd(self):
        child = self.project / "sub directory" / "deleted"
        child.mkdir(parents=True)
        self.assert_bindings(child)
        child.rmdir()
        self.assert_bindings(child)

    def test_outside_project_is_silent_and_invalid_payload_is_diagnostic(self):
        with tempfile.TemporaryDirectory() as outside:
            self.assert_bindings(Path(outside), expected="")
        before = self.snapshot()
        for payload in ("{", "[]", "null", '{}', '{"cwd":2}', '{"cwd":"relative"}', '{"cwd":"/bad\\u0000path"}'):
            for host in ("claude", "codex"):
                result = run_host_briefing(self.project, host, payload=payload, discover=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("Briefing configuration error:", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_state_and_creation_lock_on_both_adapters(self):
        write_task(self.project, "001")
        (self.project / ".cardine/tasks/002.json").write_text("{")
        self.assertIn("Diagnostics: 1", render_briefing(self.project, ""))
        self.assert_bindings()
        (self.project / ".cardine/task-creation.lock").touch()
        output = render_briefing(self.project, "")
        self.assertIn("Status unavailable:", output)
        self.assertNotIn("total=", output)
        self.assert_bindings(expected=output)

    def test_changing_inputs_rerun_and_interrupted_output_are_read_only(self):
        write_task(self.project, "001")
        before = self.snapshot()
        original = status._inputs
        calls = 0

        def changing(*args):
            nonlocal calls
            calls += 1
            return {**original(*args), self.project / "volatile": str(calls).encode()}

        with patch.object(status, "_inputs", changing):
            self.assertIn("inputs changed", render_briefing(self.project, ""))
        for host in ("claude", "codex"):
            with patch.object(sys, "stdin", io.StringIO(json.dumps({"cwd": str(self.project)}))), \
                 patch.object(sys, "stdout") as output:
                output.write.side_effect = BrokenPipeError
                self.assertEqual(briefing_main(["--host", host]), 0)
            self.assert_bindings()
        self.assertEqual(self.snapshot(), before)

    def test_unavailable_cli_cannot_fall_back_to_shell_queue_pipeline(self):
        # The hook binding uses an explicit interpreter, requiring no cardine in PATH.
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, PATH="", PYTHONPATH=str(ROOT / "src"),
                       PYTHONDONTWRITEBYTECODE="1")
            for host in ("claude", "codex"):
                result = subprocess.run([sys.executable, "-m", "cardine.hosts.briefing", "--host", host],
                                        env=env, cwd=home, input=json.dumps({"cwd": str(self.project)}),
                                        capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, render_briefing(self.project, ""))
