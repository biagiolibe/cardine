"""Interactive onboarding against real Git repositories."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cardine.cli import build_parser
from cardine.templates.init import init_cli
from cardine.templates.interactive_init import interactive_init

ROOT = Path(__file__).resolve().parents[1]


class InteractiveInitTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.root / 'README').write_text('initial\n')
        self.git('add', 'README')
        self.git('commit', '-qm', 'initial')
        subprocess.run(['git', 'init', '--bare', '-q', str(self.base / 'remote')], check=True)
        self.git('remote', 'add', 'origin', str(self.base / 'remote'))
        self.args = build_parser().parse_args(['init', '--project', str(self.root)])
        self.env = patch.dict(os.environ, HOME=str(self.base), XDG_CONFIG_HOME=str(self.base / 'config'))
        self.env.start()
        self.addCleanup(self.env.stop)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, text=True, capture_output=True, check=True).stdout

    def invoke(self, answers, tty=True):
        out, err = io.StringIO(), io.StringIO()
        with patch('cardine.templates.interactive_init._interactive', return_value=tty), \
             patch('builtins.input', side_effect=answers), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = interactive_init(self.args, ROOT)
        return code, out.getvalue(), err.getvalue()

    def test_real_tty_probe_and_explicit_check(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        with patch('sys.stdin', Terminal()), patch('sys.stdout', Terminal()) as output:
            args = build_parser().parse_args(['init', '--project', str(self.root), '--check'])
            self.assertEqual(init_cli(args, ROOT), 0)
            self.assertIn('missing: validation', output.getvalue())
        with patch('sys.stdin', Terminal('\n\n\n\n\ntrue\nn\n')), patch('sys.stdout', Terminal()) as output:
            self.assertEqual(interactive_init(self.args, ROOT), 0)
            self.assertIn('result: cancelled', output.getvalue())

    def test_no_tty_and_decline_apply(self):
        code, _, err = self.invoke([], False)
        self.assertEqual(code, 2)
        self.assertIn('--check or --apply', err)
        code, out, err = self.invoke(['', '', '', '', '', 'true', 'n'])
        self.assertEqual(code, 0, err)
        self.assertIn('result: cancelled', out)
        self.assertFalse((self.root / '.cardine').exists())

    def test_decline_publication_and_edited_choices(self):
        code, out, err = self.invoke(['Custom', 'custom', 'governed', 'Italian', 'opaque', 'true', 'y', 'n'])
        self.assertEqual(code, 0, err)
        self.assertIn('publication declined', out)
        self.assertEqual(out.strip().splitlines()[-1].split(' --project')[0], 'Next: cardine guide')
        self.assertIn('Custom', (self.root / '.cardine/project.json').read_text())
        self.assertEqual(self.git('rev-list', '--count', 'HEAD').strip(), '1')

    def test_publish_excludes_unrelated_changes(self):
        (self.root / 'staged').write_text('staged')
        self.git('add', 'staged')
        (self.root / 'README').write_text('changed')
        code, out, err = self.invoke(['', '', '', '', '', 'true', 'y', 'y'])
        self.assertEqual(code, 0, err)
        self.assertIn('committed and pushed', out)
        committed = self.git('show', '--pretty=', '--name-only', 'HEAD')
        self.assertNotIn('staged', committed)
        self.assertNotIn('README', committed.splitlines())
        self.assertIn('staged', self.git('diff', '--cached', '--name-only'))
        self.assertIn('README', self.git('diff', '--name-only'))

    def test_rejected_push_retains_commit(self):
        hook = self.base / 'remote/hooks/pre-receive'
        hook.write_text('#!/bin/sh\necho rejected >&2\nexit 1\n')
        hook.chmod(0o755)
        code, _, err = self.invoke(['', '', '', '', '', 'true', 'y', 'y'])
        self.assertEqual(code, 2)
        self.assertIn('rejected', err)
        self.assertIn('git push origin main', err)
        self.assertEqual(self.git('rev-list', '--count', 'HEAD').strip(), '2')

    def test_adoption_applies_after_confirmation(self):
        (self.root / 'AGENTS.md').write_text('Existing instructions\n')
        self.git('add', 'AGENTS.md')
        self.git('commit', '-qm', 'existing')
        code, out, err = self.invoke(['', '', '', '', '', 'true', 'y', 'n'])
        self.assertEqual(code, 0, err)
        self.assertIn('plan: adoption', out)
        self.assertIn('Existing instructions', (self.root / 'AGENTS.md').read_text())
        self.assertTrue((self.root / '.cardine/project.json').exists())

    def test_adoption_route_and_dirty_planned_path(self):
        (self.root / 'AGENTS.md').write_text('Existing instructions\n')
        self.git('add', 'AGENTS.md')
        self.git('commit', '-qm', 'existing')
        code, out, err = self.invoke(['', '', '', '', '', 'true', 'n'])
        self.assertEqual(code, 0, err)
        self.assertIn('plan: adoption', out)
        (self.root / 'AGENTS.md').write_text('uncommitted\n')
        code, _, err = self.invoke(['', '', '', '', '', 'true'])
        self.assertEqual(code, 2)
        self.assertIn('ADOPT_DIRTY', err)
