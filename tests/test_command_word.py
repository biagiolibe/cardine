"""R6 command output and rejection of the retired command word."""

import ast
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from cardine.cli import build_parser
from cardine.hosts.claude import CLAUDE_PROJECT_ALLOWLIST
from cardine.hosts.codex import CODEX_USER_RULES
import align_queue


class CommandWordTest(unittest.TestCase):
    def test_stop_decisions_match_the_pre_task_snapshot(self):
        entries = json.loads((ROOT / "capabilities/stop-codes-v1.json").read_text())["stops"]
        # Snapshot of code, human_decision, and resolution at 84673a18828b50ec34ce712b009e9cf2b524184e.
        baseline = json.loads((ROOT / "tests/fixtures/stop-decisions-before-047.json").read_text())
        # SS5 removes the obsolete prose-agreement gate; every remaining decision is preserved.
        baseline.pop("QUEUE_STATUS_MISMATCH")
        # RX1 retires stops owned exclusively by the deleted self-report commands.
        for code in ("EXECUTION_EVIDENCE_ARGUMENTS", "HANDOFF_EXPLORATION_MISMATCH", "HANDOFF_EXPLORATION_SUMMARY_MISSING"):
            baseline.pop(code)
        self.assertEqual(len(entries), len(baseline))
        self.assertEqual({s["code"]: {k: s[k] for k in ("human_decision", "resolution")} for s in entries}, baseline)
        commands = []
        for entry in entries:
            # Prose and Git instructions remain recovery instructions in their own right.
            commands.extend(re.findall(r"(?<![\w/.-])(?:cardine|meridian)\s+\S+", entry["resume"]))  # MERIDIAN-OLD-NAME-TEST
        self.assertTrue(commands)
        self.assertTrue(all(command.startswith("cardine ") for command in commands))  # MERIDIAN-OLD-NAME-TEST

    def test_parser_names_cardine_and_rejects_old_program_as_a_command(self):
        parser = build_parser()
        self.assertEqual(parser.prog, "cardine")
        self.assertTrue(parser.format_help().startswith("usage: cardine "))
        with redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit) as caught:
            parser.parse_args(["meridian", "--version"])  # MERIDIAN-OLD-NAME-TEST
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("invalid choice", error.getvalue())

    def test_generated_allowlists_do_not_authorize_the_old_command(self):
        self.assertTrue(any(rule.startswith("Bash(cardine ") for rule in CLAUDE_PROJECT_ALLOWLIST))
        self.assertFalse(any(rule.startswith("Bash(meridian") for rule in CLAUDE_PROJECT_ALLOWLIST))  # MERIDIAN-OLD-NAME-TEST
        patterns = []
        for node in ast.walk(ast.parse(CODEX_USER_RULES)):
            if isinstance(node, ast.Call):
                patterns.extend(ast.literal_eval(k.value) for k in node.keywords if k.arg == "pattern")
        self.assertTrue(any(pattern[0] == "cardine" for pattern in patterns))
        self.assertFalse(any(pattern[0] == "meridian" for pattern in patterns))  # MERIDIAN-OLD-NAME-TEST

    def test_queue_resolver_ignores_the_old_path_command_and_option(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            with mock.patch.object(align_queue.shutil, "which", return_value=None) as lookup, mock.patch.object(align_queue.subprocess, "run") as run:
                self.assertEqual(align_queue.resolve_queue(project, None), project / "tasks/QUEUE.md")
            lookup.assert_called_once_with("cardine")  # MERIDIAN-OLD-NAME-TEST
            run.assert_not_called()
            result = subprocess.run([sys.executable, str(ROOT / "scripts/align_queue.py"), "--meridian", "ignored", str(project)], capture_output=True, text=True)  # MERIDIAN-OLD-NAME-TEST
            self.assertEqual(result.returncode, 2)
            self.assertIn("unrecognized arguments: --meridian", result.stderr)  # MERIDIAN-OLD-NAME-TEST

    def test_shell_path_fallbacks_ignore_the_old_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            hook = temporary / "hooks/stop-audit.sh"
            hook.parent.mkdir()
            shutil.copyfile(ROOT / "hooks/stop-audit.sh", hook)
            tools = temporary / "tools"
            tools.mkdir()
            marker = temporary / "called"
            old = tools / "meridian"  # MERIDIAN-OLD-NAME-TEST
            old.write_text(f"#!/bin/sh\nprintf called > '{marker}'\n")
            old.chmod(0o755)
            environment = {**os.environ, "PATH": str(tools) + ":/usr/bin:/bin", "PLUGIN_ROOT": "", "CLAUDE_PLUGIN_ROOT": "", "CARDINE_ROOT": ""}
            result = subprocess.run(["/bin/bash", str(hook)], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())  # MERIDIAN-OLD-NAME-TEST
            result = subprocess.run(["/bin/bash", str(ROOT / "scripts/upgrade_project.sh"), str(temporary)], env=environment, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("set CARDINE_ROOT or pass --cardine-root", result.stdout + result.stderr)
            self.assertFalse(marker.exists())  # MERIDIAN-OLD-NAME-TEST

    def test_upgrade_ignores_old_root_environment_and_rejects_old_option(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = {key: value for key, value in os.environ.items() if key != "CARDINE_ROOT"}
            environment.update(PATH="/usr/bin:/bin")
            environment["MERIDIAN_ROOT"] = str(ROOT)  # MERIDIAN-OLD-NAME-TEST
            command = ["/bin/bash", str(ROOT / "scripts/upgrade_project.sh"), directory]
            result = subprocess.run(command, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("set CARDINE_ROOT or pass --cardine-root", result.stderr)
            result = subprocess.run([*command, "--meridian-root", str(ROOT)], env=environment, capture_output=True, text=True)  # MERIDIAN-OLD-NAME-TEST
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown option: --meridian-root", result.stderr)  # MERIDIAN-OLD-NAME-TEST
            result = subprocess.run([*command, "--cardine-root", directory], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn(f"no executable {temporary}/bin/cardine", result.stderr)

    def test_stop_hook_ignores_old_bin_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            hook = temporary / "hooks/stop-audit.sh"
            hook.parent.mkdir()
            shutil.copyfile(ROOT / "hooks/stop-audit.sh", hook)
            tools = temporary / "tools"
            tools.mkdir()
            called = temporary / "called"
            current = tools / "cardine"
            current.write_text(f"#!/bin/sh\nprintf '%s' \"$*\" > '{called}'\n")
            current.chmod(0o755)
            environment = {**os.environ, "PATH": f"{tools}:/usr/bin:/bin", "PLUGIN_ROOT": "", "CLAUDE_PLUGIN_ROOT": ""}
            environment["MERIDIAN_BIN"] = "/retired/bin/meridian"  # MERIDIAN-OLD-NAME-TEST
            result = subprocess.run(["/bin/bash", str(hook)], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(called.read_text(), "hook stop-audit")
