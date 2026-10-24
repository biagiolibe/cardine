"""Expected surface enforcement across real Git changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from cardine.lifecycle.scope import enforce_scope, normalize_surface, parse_surface
from cardine.shared.errors import CardineError


class RunScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Scope Test')
        self.git('config', 'user.email', 'scope@example.test')
        (self.root / 'src').mkdir()
        (self.root / 'src/code.py').write_text('old')
        (self.root / 'foreign.txt').write_text('preserve')
        self.git('add', '.')
        self.git('commit', '-m', 'Base')
        self.base = self.git('rev-parse', 'HEAD')
        self.state = dict(task_id='001', contract=dict(expectedCodeSurface=['src/**']))

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def check(self):
        return enforce_scope(self.root, self.state, self.base)

    def test_tracked_deleted_untracked_and_owned_paths(self):
        (self.root / 'src/code.py').unlink()
        (self.root / 'src/new file.py').write_text('new')
        expected = {'src/code.py', 'src/new file.py'}
        self.assertEqual(self.check(), expected)
        self.assertEqual(self.check(), expected)
        (self.root / 'owned.json').write_text('cli')
        self.assertEqual(enforce_scope(self.root, self.state, self.base, owned={'owned.json'}), expected)
        with self.assertRaises(CardineError):
            self.check()

    def test_rename_checks_both_ends(self):
        self.git('mv', 'foreign.txt', 'src/foreign.txt')
        with self.assertRaisesRegex(CardineError, 'foreign.txt'):
            self.check()

    def test_deleted_foreign_file_and_committed_escape_are_rejected(self):
        (self.root / 'foreign.txt').unlink()
        with self.assertRaises(CardineError):
            self.check()
        self.git('add', '.')
        self.git('commit', '-m', 'Forbidden deletion')
        with self.assertRaises(CardineError):
            self.check()

    def test_symlink_escape_including_directory_ancestor(self):
        (self.root / 'src/link').symlink_to(self.root.parent)
        with self.assertRaisesRegex(CardineError, 'symlink escapes'):
            self.check()
        self.assertTrue((self.root / 'src/link').is_symlink())

    def test_normalization_and_segment_globs(self):
        for value in ('../escape', '/tmp/file', 'src/../other', 'src//file', './src', '.git/config', 'a\\b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_surface([value])
        (self.root / 'src/nested').mkdir()
        (self.root / 'src/nested/new.py').write_text('new')
        self.state['contract']['expectedCodeSurface'] = ['src/*']
        with self.assertRaises(CardineError):
            self.check()
        self.assertEqual(parse_surface('## Expected code surface\n- `src/**`\n## Validation\nx'), ['src/**'])

    def test_absent_surface_and_prose_never_grant_unattended_authority(self):
        self.state['contract'] = {}
        with self.assertRaisesRegex(CardineError, 'frozen Expected'):
            self.check()
        self.assertEqual(parse_surface('## Expected code surface\nChange anything needed.\n'), [])


if __name__ == '__main__':
    unittest.main()
