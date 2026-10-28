"""Verify light entry paths in fresh interpreters with disposable homes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from project_config_support import write_project_config


ROOT = Path(__file__).resolve().parents[1]
NETWORK_MODULES = ("http", "ssl", "email")


class CliStartupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cardine-startup-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        write_project_config(self.project)

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def probe(self, body, *, payload="{}"):
        environment = dict(os.environ, HOME=str(self.home),
                           CODEX_HOME=str(self.home / ".codex"),
                           CLAUDE_CONFIG_DIR=str(self.home / ".claude"),
                           XDG_CONFIG_HOME=str(self.home / ".config"),
                           PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        code = """import sys, json, time, io, contextlib, runpy
started = time.perf_counter()
output = io.StringIO()
with contextlib.redirect_stdout(output):
""" + "".join("    " + line + "\n" for line in body.splitlines()) + """
print(json.dumps(dict(modules=sorted(sys.modules), output=output.getvalue(),
                      elapsed_seconds=time.perf_counter() - started)))
"""
        result = subprocess.run([sys.executable, "-X", "importtime", "-c", code],
                                cwd=self.home, env=environment, input=payload,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, "\n".join(result.stderr.splitlines()[-20:]))
        return json.loads(result.stdout), result.stderr

    def assert_light(self, result, trace):
        loaded = [name for name in result["modules"]
                  if name.split(".")[0] in NETWORK_MODULES]
        self.assertEqual(loaded, [])
        for line in trace.splitlines():
            if line.startswith("import time:") and "|" in line:
                self.assertNotIn(line.rsplit("|", 1)[1].strip().split(".")[0], NETWORK_MODULES)
        # Timing is diagnostic; there is deliberately no machine-specific ceiling.
        self.assertGreaterEqual(result["elapsed_seconds"], 0)

    def test_cli_import_defers_command_implementations(self):
        before = self.snapshot()
        result, trace = self.probe("import cardine.cli")
        self.assert_light(result, trace)
        for module in ("cardine.release.update", "cardine.hosts.setup",
                       "cardine.integration.merge", "cardine.shared.journal"):
            self.assertNotIn(module, result["modules"])
        self.assertEqual(self.snapshot(), before)

    def test_update_import_defers_network_stack(self):
        before = self.snapshot()
        result, trace = self.probe("import cardine.release.update")
        self.assert_light(result, trace)
        self.assertEqual(self.snapshot(), before)

    def test_briefing_repeats_without_network_imports_or_writes(self):
        before = self.snapshot()
        for host in ("claude", "codex"):
            body = f"""from cardine.hosts.briefing import briefing_main
assert briefing_main(['--project', {str(self.project)!r}, '--host', {host!r}]) == 0"""
            first, trace = self.probe(body)
            self.assert_light(first, trace)
            second, trace = self.probe(body)
            self.assert_light(second, trace)
            self.assertEqual(first["output"], second["output"])
            self.assertIn("Tasks:", first["output"])
            self.assertEqual(self.snapshot(), before)

    def test_hook_dispatch_is_light_and_repeatable(self):
        before = self.snapshot()
        for hook in ("read-guard", "stop-audit"):
            body = f"""sys.argv = ['cardine', 'hook', {hook!r}, '--host', 'claude']
from cardine.cli import main
assert main() == 0"""
            for _ in range(2):
                result, trace = self.probe(body)
                self.assert_light(result, trace)
                self.assertNotIn("cardine.release.update", result["modules"])
                self.assertNotIn("cardine.hosts.setup", result["modules"])
                self.assertNotIn("cardine.integration.merge", result["modules"])
                self.assertEqual(self.snapshot(), before)

    def test_release_dispatch_preserves_arguments(self):
        before = self.snapshot()
        for command, options, function in (
            ("self-check", ["--check-latest"], "run_self_check"),
            ("self-update", ["--check", "--to", "v1.2.3"], "run_self_update"),
        ):
            expected_kwargs = {} if command == "self-check" else dict(apply=False, target_tag="v1.2.3")
            body = f"""from unittest.mock import patch
from cardine.cli import main
sys.argv = ['cardine', '--framework-root', {str(self.project)!r}, {command!r}] + {options!r}
with patch('cardine.release.update.{function}', return_value=7) as implementation:
    assert main() == 7
    implementation.assert_called_once()
    args, kwargs = implementation.call_args
    assert args[0] == {('Path(' + repr(str(self.project)) + ').resolve()') if command == 'self-check' else 'SCRIPTS_ROOT.parent'}
    assert kwargs == {expected_kwargs!r}"""
            body = "from pathlib import Path\nfrom cardine.shared.paths import SCRIPTS_ROOT\n" + body
            self.probe(body)
            self.assertEqual(self.snapshot(), before)
