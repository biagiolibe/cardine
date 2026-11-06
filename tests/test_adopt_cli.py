"""Command surface for project adoption."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AdoptCliTest(unittest.TestCase):
    def invoke(self, home, *args):
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'))
        return subprocess.run([str(ROOT / 'bin/cardine'), 'adopt', *args], env=env,
                              text=True, capture_output=True)

    def test_check_is_read_only_and_reports_missing_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            before = sorted(root.rglob('*'))
            result = self.invoke(root, '--project', str(project), '--check')
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertEqual(envelope['outcome'], 'done')
            self.assertEqual(envelope['plan']['case'], 'A')
            self.assertIn('validation', envelope['plan']['missing'])
            self.assertEqual(sorted(root.rglob('*')), before)

    def test_missing_inputs_block_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.invoke(Path(temp), '--project', temp, '--apply')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['outcome'], 'blocked')

    def test_invalid_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.invoke(Path(temp), '--project', temp, '--check', '--apply')
            self.assertEqual(result.returncode, 64)
            self.assertEqual(json.loads(result.stdout)['outcome'], 'invalid')
