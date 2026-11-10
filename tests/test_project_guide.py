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
                self.assertIn('validation is missing', text.stdout)
                self.assertIn('task branch commit', text.stdout)
                after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                self.assertEqual(before, after)
