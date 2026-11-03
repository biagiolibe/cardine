"""Disposable end-to-end delivery of a no-review task to landing (C3c).

The test plays the implementer and `run` performs every other step against a
private project, a private home directory, and a local bare remote.
"""
import io
import contextlib
import shlex
import unittest

from cardine.lifecycle.engine import run_preview_cli
from run_delivery_support import KILLED, TASK, DisposableDelivery

LANDING = [('candidate', 'C6', 'next'),
           ('candidate', 'validate-candidate', 'next'), ('landing', 'finalize', 'next'),
           ('landing', 'cleanup', 'done')]


class DisposableDeliveryTest(unittest.TestCase):
    def assert_landed(self, project):
        branches = project.git('branch', '--list', 'task-' + TASK)
        self.assertEqual(branches, '')
        # Cleanup unregisters the worktree and keeps only an empty placeholder directory.
        self.assertEqual(project.git('worktree', 'list', '--porcelain').count('worktree '), 1)
        self.assertEqual(list(project.locations.worktree.iterdir()), [])
        self.assertEqual(project.remote_main(), project.git('rev-parse', 'main'))
        self.assertEqual(project.git('status', '--porcelain'), '')
        self.assertEqual(project.git('show', 'main:src/result.py'), 'result = 1')
        self.assertEqual(project.drive()[-1][2], 'done')  # A rerun after landing converges.
        self.assertEqual(project.remote_main(), project.git('rev-parse', 'main'))

    def test_queued_task_lands_and_is_cleaned(self):
        with DisposableDelivery() as project:
            first = project.run()
            self.assertEqual((first['step'], first['action'], first['outcome']), ('worktree', 'execution-start', 'next'))
            self.assertTrue(project.locations.worktree.is_dir())
            self.assertEqual(project.run()['step'], 'implementation')
            project.implement()
            self.assertEqual(project.drive(), LANDING)
            self.assert_landed(project)
            self.assertEqual(project.git('log', '-1', '--format=%s'), 'Integrate ' + TASK)

    def test_evidence_incomplete_is_recovered_through_run(self):
        with DisposableDelivery() as project:
            project.run()
            project.implement()
            report = project.closure()
            self.assertEqual((report['step'], report['stop_reason']), ('C5', 'EVIDENCE_INCOMPLETE'))
            argv = shlex.split(report['resume'])
            self.assertEqual(argv[:3], ['cardine', 'run', TASK])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run_preview_cli(argv[2:]), 0)
            after = project.closure()
            self.assertEqual((after['step'], after['stop_reason']), ('C6', None))
            self.assertEqual(project.drive()[-1][2], 'done')
            self.assert_landed(project)

    def converge_after_kill(self, mode, point):
        with DisposableDelivery() as project:
            project.run()
            if mode == 'deliver':
                project.commit_implementation()
            else:
                project.implement()
            done = project.kill(mode, point)
            self.assertEqual(done.returncode, KILLED, done.stderr)
            if mode == 'deliver':
                project.deliver()
            project.drive()
            self.assert_landed(project)

    def test_rerun_after_a_kill_before_the_delivery_commit_converges(self):
        self.converge_after_kill('deliver', 'before_delivery_commit')

    def test_rerun_after_a_kill_before_the_delivery_state_write_converges(self):
        self.converge_after_kill('deliver', 'before_delivery_state')

    def test_rerun_after_a_kill_before_the_merge_commit_converges(self):
        self.converge_after_kill('run', 'before_finalize_commit')

    def test_rerun_after_a_kill_before_the_push_converges(self):
        self.converge_after_kill('run', 'before_cleanup_push')

    def test_rerun_after_a_kill_after_the_worktree_removal_converges(self):
        self.converge_after_kill('run', 'after_cleanup_worktree')


if __name__ == '__main__':
    unittest.main()
