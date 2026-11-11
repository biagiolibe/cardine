"""Project onboarding remains read-only and reflects resolved options."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectGuideTest(unittest.TestCase):
    def test_formats_and_configurations_are_read_only(self):
        for ci_enabled in (False, True):
            with self.subTest(ci_enabled=ci_enabled), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                project = root / 'project'
                (project / '.cardine').mkdir(parents=True)
                declaration = {'version': 1, 'preset': 'lean', 'ci': 'none'}
                if ci_enabled:
                    declaration.update(ci={'provider': 'github', 'requiredChecks': ['tests']},
                                       taskDefaults={'ciBeforeLanding': True, 'review': 'required'})
                (project / '.cardine/project.json').write_text(json.dumps(declaration))
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'))
                def run(*args):
                    return subprocess.run([str(ROOT / 'bin/cardine'), 'guide', '--project', str(project), *args],
                                          env=env, capture_output=True, text=True)
                result = run('--format', 'json')
                self.assertEqual(result.returncode, 0, result.stderr)
                guide = json.loads(result.stdout)
                self.assertEqual(guide['facts']['task_defaults']['ciBeforeLanding'], ci_enabled)
                self.assertEqual(guide['facts']['host_policy'], 'unverified')
                self.assertEqual(guide['facts']['remote_ci'], 'unverified')
                text = run()
                self.assertEqual(text.returncode, 0, text.stderr)
                for entries in guide['sections'].values():
                    for entry in entries:
                        self.assertIn(entry, text.stdout)
                self.assertIn('Validation: not declared; run cardine init', text.stdout)
                for literal in ('{', '}', 'True', 'False', 'None'):
                    self.assertNotIn(literal, text.stdout)
                self.assertIn('Next steps:', text.stdout)
                self.assertIn('This project:', text.stdout)
                self.assertEqual(sorted(guide['sections']), ['choices', 'first_task', 'references'])
                after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                self.assertEqual(before, after)

    def test_unconfigured_checkout_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / 'project'
            project.mkdir()
            subprocess.run(['git', 'init', '-q', str(project)], check=True)
            def run(path, *args):
                return subprocess.run([str(ROOT / 'bin/cardine'), 'guide', '--project', str(path), *args], capture_output=True, text=True)
            before = set(project.rglob('*'))
            result = run(project, '--format', 'json')
            self.assertEqual(result.returncode, 0, result.stderr)
            guide = json.loads(result.stdout)
            self.assertEqual(guide['facts']['configuration'], 'missing')
            text = run(project)
            for entries in guide['sections'].values():
                for entry in entries:
                    self.assertIn(entry, text.stdout)
            self.assertEqual(before, set(project.rglob('*')))
            self.assertEqual(guide['sections']['bootstrap'][0], 'This checkout is not configured for Cardine yet.')
            self.assertIn('cardine init --project', guide['sections']['bootstrap'][1])
            self.assertRegex(guide['sections']['references'][0],
                             r'^https://github.com/biagiolibe/cardine/blob/v\d+\.\d+\.\d+[^/]*/docs/QUICKSTART.md$')
            self.assertIn('unsupported checkout', run(root).stderr)
            (project / '.cardine').mkdir()
            (project / '.cardine/project.json').write_text('{broken')
            self.assertIn('invalid project declaration', run(project).stderr)
