"""A restored run engine fixture is exactly the state it was copied from."""
import os
import shutil
import subprocess
import unittest

from cardine.lifecycle import receipts
from cardine.stops.render import stop_error
from cardine.tasks.state import read_task_state
from fixture_restore_support import ReadySnapshot, tree_digest
import test_run_cleanup
import test_run_delivery
import test_run_preparation
import worktree_support
import test_worktree_lifecycle
import test_execution_boundaries
import test_task_integration_state


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.DEVNULL)


class FixtureRestoreTest(unittest.TestCase):
    def observe(self, fixture, primary, root):
        directory = fixture.live
        index = subprocess.check_output(['git', '-C', str(primary), 'rev-parse', '--git-path', 'index'], text=True).strip()
        return {
            'tree': tree_digest(directory),
            'worktrees': git(primary, 'worktree', 'list', '--porcelain'),
            'refs': git(primary, 'for-each-ref'),
            'head': git(root, 'rev-parse', 'HEAD'),
            'index': git(root, 'ls-files', '--stage'),
            'index-file': (primary / '.git/index').read_bytes() if index == '.git/index' else b'',
        }

    def check(self, fixture, make, root_of, *, primary_of=lambda test: test.root,
              task_id='001', has_state=True):
        test = make()
        test.setUp()
        self.addCleanup(test.doCleanups)
        primary = primary_of(test)
        root = root_of(test)
        self.assertEqual(tree_digest(fixture.live), fixture.digest)
        self.assertEqual(tree_digest(fixture.live), tree_digest(fixture.copy))
        before = self.observe(fixture, primary, root)
        if has_state:
            state = read_task_state(root, task_id, 'single', stop_factory=stop_error)
            receipts.verify_receipts(root, state)
        else:
            receipts.require_authority(root)
        # A case that changes the fixture, in the main checkout and the worktree.
        (primary / 'case-scratch.txt').write_text('added by a case\n')
        (primary.parent / 'case-outside.txt').write_text('added by a case\n')
        if has_state:
            (primary / f'.cardine/tasks/{task_id}.json').write_text('{}\n')
        git(primary, 'add', '.')
        git(primary, 'commit', '-m', 'Case change')
        git(primary, 'branch', 'case-branch')
        if root != primary:
            (root / 'case-worker.txt').write_text('changed worktree\n')
            git(root, 'add', '.')
            git(root, 'commit', '-m', 'Case worker change')
        (primary / 'case-index.txt').write_text('staged only\n')
        git(primary, 'add', 'case-index.txt')
        test.doCleanups()
        again = make()
        again.setUp()
        self.addCleanup(again.doCleanups)
        primary = primary_of(again)
        root = root_of(again)
        after = self.observe(fixture, primary, root)
        self.assertEqual(after, before)
        self.assertEqual(tree_digest(fixture.live), fixture.digest)
        self.assertFalse((primary / 'case-scratch.txt').exists())
        self.assertFalse((primary.parent / 'case-outside.txt').exists())
        if has_state:
            state = read_task_state(root, task_id, 'single', stop_factory=stop_error)
            receipts.verify_receipts(root, state)
        else:
            receipts.require_authority(root)

    def test_preparation_fixture_restores_identically(self):
        self.check(test_run_preparation.PREPARATION_FIXTURE, test_run_preparation.RunPreparationTest,
                   lambda test: test.root)

    def test_delivery_fixture_restores_identically(self):
        self.check(test_run_delivery.DELIVERY_FIXTURE, test_run_delivery.RunDeliveryTest,
                   lambda test: test.worker)

    def test_bounded_worktree_fixture_restores_identically(self):
        self.check(worktree_support.BOUNDED_FIXTURE,
                   worktree_support.BoundedWorktreeLifecycleFixture,
                   lambda test: test.primary, primary_of=lambda test: test.primary, task_id='056')

    def test_lifecycle_fixture_restores_identically(self):
        self.check(test_worktree_lifecycle.LIFECYCLE_FIXTURE,
                   test_worktree_lifecycle.WorktreeLifecycleCliTest,
                   lambda test: test.project, primary_of=lambda test: test.project, task_id='056')

    def test_execution_governed_fixture_restores_identically(self):
        self.check(test_execution_boundaries.EXECUTION_FIXTURES['governed'],
                   test_execution_boundaries.ExecutionBoundariesTest,
                   lambda test: test.worker, primary_of=lambda test: test.primary)

    def test_execution_lean_fixture_restores_identically(self):
        def make():
            test = test_execution_boundaries.ExecutionBoundariesTest()
            test.preset = 'lean'
            return test
        self.check(test_execution_boundaries.EXECUTION_FIXTURES['lean'], make,
                   lambda test: test.worker, primary_of=lambda test: test.primary)

    def test_integration_state_fixture_restores_identically(self):
        # This fixture intentionally removes task state before each case, which
        # exercises missing-state integration. Its authority bytes still match.
        self.check(test_task_integration_state.INTEGRATION_STATE_FIXTURE,
                   test_task_integration_state.TaskIntegrationStateTest,
                   lambda test: test.primary, primary_of=lambda test: test.primary,
                   task_id='056', has_state=False)

    def test_cleanup_ready_snapshot_restores_identically(self):
        test = test_run_cleanup.CleanupTest('test_recorded_remote_is_compare_deleted')
        test.setUp()
        self.addCleanup(test.doCleanups)
        snapshot = ReadySnapshot(test.root)
        self.addCleanup(snapshot.close)
        self.addCleanup(os.chdir, test.previous_cwd)

        def observe():
            return {
                'tree': tree_digest(test.root),
                'worktrees': git(test.primary, 'worktree', 'list', '--porcelain'),
                'refs': git(test.primary, 'for-each-ref'),
                'heads': (git(test.primary, 'rev-parse', 'HEAD'), git(test.worker, 'rev-parse', 'HEAD')),
                'indexes': (git(test.primary, 'ls-files', '--stage'), git(test.worker, 'ls-files', '--stage')),
                'origin-refs': git(test.origin, 'for-each-ref'),
            }

        def verify():
            state = read_task_state(test.primary, '056', 'single', stop_factory=stop_error)
            receipts.verify_receipts(test.primary, state)

        before = observe()
        verify()
        # A scenario pushes, is interrupted, then changes and deletes fixture state.
        test.own_remote()
        test.kill('after_cleanup_remote')
        test.git('remote', 'set-url', 'origin', '/foreign')
        (test.worker / 'scenario.txt').write_text('scenario\n')
        test.git('add', 'scenario.txt', cwd=test.worker)
        shutil.rmtree(test.worker / 'feature.txt', ignore_errors=True)
        self.assertNotEqual(observe(), before)
        snapshot.restore()
        os.chdir(test.primary)
        self.assertEqual(observe(), before)
        verify()
        self.assertFalse((test.worker / 'scenario.txt').exists())
        self.assertIsNone(test.remote('task-056'))


if __name__ == '__main__':
    unittest.main()
