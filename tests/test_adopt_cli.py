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

    def test_apply_points_to_guide_and_check_has_no_guide(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            subprocess.run(['git', 'init', '-q', '-b', 'main', str(project)], check=True)
            (project / 'README').write_text('Example\n')
            subprocess.run(['git', 'add', '.'], cwd=project, check=True)
            subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '-qm', 'Initial'], cwd=project, check=True)
            validation = root / 'validation.json'
            validation.write_text(json.dumps({'commands': {'test': 'true'}, 'baseline': ['test'],
                                              'candidate': {'REUSE': [], 'BOUNDED': [], 'FULL': []}}))
            args = ('--project', str(project), '--name', 'Example', '--slug', 'example',
                    '--preset', 'lean', '--language', 'English', '--task-identity', 'opaque',
                    '--validation', str(validation))
            check = self.invoke(root, *args, '--check')
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertNotIn('guide', json.loads(check.stdout))
            apply = self.invoke(root, *args, '--apply')
            self.assertEqual(apply.returncode, 0, apply.stdout + apply.stderr)
            self.assertIn('cardine guide --project', json.loads(apply.stdout)['guide'])
            guide = subprocess.run([str(ROOT / 'bin/cardine'), 'guide', '--project', str(project),
                                    '--format', 'json'], capture_output=True, text=True)
            self.assertEqual(guide.returncode, 0, guide.stderr)
            self.assertEqual(json.loads(guide.stdout)['facts']['preset'], 'lean')

    def test_missing_inputs_block_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.invoke(Path(temp), '--project', temp, '--apply')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['outcome'], 'blocked')

    def test_adopt_still_requires_an_explicit_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.invoke(Path(temp), '--project', temp)
            self.assertEqual(result.returncode, 64)
            self.assertEqual(json.loads(result.stdout)['outcome'], 'invalid')

    def test_invalid_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.invoke(Path(temp), '--project', temp, '--check', '--apply')
            self.assertEqual(result.returncode, 64)
            self.assertEqual(json.loads(result.stdout)['outcome'], 'invalid')
