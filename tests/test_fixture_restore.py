"""A restored run engine fixture is exactly the state it was copied from."""
import subprocess
import unittest

from cardine.lifecycle import receipts
from cardine.stops.render import stop_error
from cardine.tasks.state import read_task_state
from fixture_restore_support import tree_digest
import test_run_delivery
import test_run_preparation


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.DEVNULL)


class FixtureRestoreTest(unittest.TestCase):
    def observe(self, fixture, test, root):
        directory = fixture.live
        index = subprocess.check_output(['git', '-C', str(test.root), 'rev-parse', '--git-path', 'index'], text=True).strip()
        return {
            'tree': tree_digest(directory),
            'worktrees': git(test.root, 'worktree', 'list', '--porcelain'),
            'refs': git(test.root, 'for-each-ref'),
            'head': git(root, 'rev-parse', 'HEAD'),
            'index': git(root, 'ls-files', '--stage'),
            'index-file': (test.root / '.git/index').read_bytes() if index == '.git/index' else b'',
        }

    def check(self, fixture, make, root_of):
        test = make()
        test.setUp()
        root = root_of(test)
        self.assertEqual(tree_digest(fixture.live), fixture.digest)
        self.assertEqual(tree_digest(fixture.live), tree_digest(fixture.copy))
        before = self.observe(fixture, test, root)
        state = read_task_state(root, '001', 'single', stop_factory=stop_error)
        receipts.verify_receipts(root, state)
        # A case that changes the fixture, in the main checkout and the worktree.
        (test.root / 'case-scratch.txt').write_text('added by a case\n')
        (test.root.parent / 'case-outside.txt').write_text('added by a case\n')
        (test.root / '.cardine/tasks/001.json').write_text('{}\n')
        git(test.root, 'add', '.')
        git(test.root, 'commit', '-m', 'Case change')
        git(test.root, 'branch', 'case-branch')
        test.doCleanups()
        again = make()
        again.setUp()
        self.addCleanup(again.doCleanups)
        root = root_of(again)
        after = self.observe(fixture, again, root)
        self.assertEqual(after, before)
        self.assertEqual(tree_digest(fixture.live), fixture.digest)
        self.assertFalse((again.root / 'case-scratch.txt').exists())
        self.assertFalse((again.root.parent / 'case-outside.txt').exists())
        state = read_task_state(root, '001', 'single', stop_factory=stop_error)
        receipts.verify_receipts(root, state)

    def test_preparation_fixture_restores_identically(self):
        self.check(test_run_preparation.PREPARATION_FIXTURE, test_run_preparation.RunPreparationTest,
                   lambda test: test.root)

    def test_delivery_fixture_restores_identically(self):
        self.check(test_run_delivery.DELIVERY_FIXTURE, test_run_delivery.RunDeliveryTest,
                   lambda test: test.worker)


if __name__ == '__main__':
    unittest.main()
