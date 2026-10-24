"""Repository template copies preserve Git state without sharing mutable files."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from project_config_support import write_project_config
from repository_template_support import RepositoryTemplate
from task_contract_support import contract_record


def git(project, *args):
    return subprocess.run(['git', *args], cwd=project, check=True,
                          capture_output=True).stdout


def build(project):
    project.mkdir()
    git(project, 'init', '-q', '-b', 'main')
    git(project, 'config', 'user.name', 'Template Test')
    git(project, 'config', 'user.email', 'template@example.invalid')
    git(project, 'config', 'maintenance.auto', 'false')
    write_project_config(project)
    (project / 'tasks').mkdir()
    (project / 'tasks/001.md').write_text(contract_record())
    git(project, 'add', '.')
    git(project, 'commit', '-qm', 'Initial fixture')


class RepositoryTemplateTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.template = RepositoryTemplate(build)
        self.addCleanup(self.template.cleanup)

    def test_copies_have_independent_worktrees_indexes_and_configuration(self):
        first = self.template.copy_to(self.root / 'first')
        second = self.template.copy_to(self.root / 'second')
        (first / 'tasks/001.md').write_text('Changed only in the first copy.\n')
        git(first, 'add', '.')
        git(first, 'config', 'user.name', 'Changed')
        git(first, 'worktree', 'add', '-qb', 'task-001', str(self.root / 'worker'))
        self.assertEqual((second / 'tasks/001.md').read_text(), contract_record())
        self.assertEqual(git(second, 'status', '--porcelain'), b'')
        self.assertEqual(git(second, 'config', 'user.name'), b'Template Test\n')
        self.assertFalse((second / '.git/worktrees').exists())
        self.assertFalse((self.template.project / '.git/worktrees').exists())
        self.assertEqual((self.template.project / 'tasks/001.md').read_text(), contract_record())
        self.assertNotEqual((first / '.git/index').stat().st_ino,
                            (second / '.git/index').stat().st_ino)

    def test_copy_matches_fresh_head_tree_index_and_git_configuration(self):
        copied = self.template.copy_to(self.root / 'copied')
        self.assertEqual((copied / '.git/index').read_bytes(),
                         (self.template.project / '.git/index').read_bytes())
        fresh = self.root / 'fresh'
        build(fresh)
        for args in [('rev-parse', 'HEAD^{tree}'), ('ls-files', '--stage'),
                     ('config', '--local', '--list'), ('status', '--porcelain')]:
            with self.subTest(command=args):
                self.assertEqual(git(copied, *args), git(fresh, *args))

    def test_template_rejects_registered_worktrees_and_cleans_temporary_space(self):
        paths = []
        def registered(project):
            build(project)
            paths.append(project.parent)
            (project / '.git/worktrees').mkdir()
        with self.assertRaisesRegex(ValueError, 'without worktree registrations'):
            RepositoryTemplate(registered)
        self.assertFalse(paths[0].exists())
        path = self.template.project.parent
        self.template.cleanup()
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
