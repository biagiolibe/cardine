"""Regression coverage for the development entry point's dispatch and output."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from meridian_cli_support import ROOT
import dev


class DevCommandsTest(unittest.TestCase):
    def test_profile_doctor_forwards_roots_and_preserves_exit_status(self):
        with patch.object(dev, "profile_doctor", return_value=2) as doctor:
            self.assertEqual(dev.main(["profile", "doctor", "example", "--project", str(ROOT)]), 2)
        doctor.assert_called_once_with(ROOT, ROOT, "example")

    def test_profile_bootstrap_preserves_json_and_apply_flag(self):
        declaration = {"capabilities": {"example": 1}}
        for action in ("--check", "--apply"):
            with self.subTest(action=action), patch.object(dev, "bootstrap_capability_profile", return_value={"capabilityProfiles": {"example": declaration}}) as bootstrap:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(dev.main(["profile", "bootstrap", "example", "--project", str(ROOT), action]), 0)
                self.assertEqual(json.loads(output.getvalue()), declaration)
                bootstrap.assert_called_once_with(ROOT, ROOT, "example", apply=action == "--apply")

    def test_agent_eval_arguments_and_exit_status_are_forwarded(self):
        with patch("run_agent_evals.main", return_value=3) as evaluate:
            self.assertEqual(dev.main(["agent-evals", "--host", "codex", "--runs", "2"]), 3)
        evaluate.assert_called_once_with(["--host", "codex", "--runs", "2"])

    def test_agent_eval_help_is_reachable_without_running_an_agent(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/dev.py"), "agent-evals", "--help"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--scenario", result.stdout)
        self.assertIn("--host", result.stdout)
