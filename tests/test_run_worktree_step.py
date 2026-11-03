"""`run` performs the contract and worktree steps once and converges after a kill (C3b)."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from cardine.lifecycle.context import resolve_run_locations
from cardine.lifecycle.engine import dispatch_run
from test_run_preparation import PREPARATION_FIXTURE, ROOT


class RunWorktreeStepTest(unittest.TestCase):
    def setUp(self):
        directory, _ = PREPARATION_FIXTURE.restore()
        self.root = directory / 'project'
        self.worktrees = directory / 'worktrees'
        environment = patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.worktrees)})
        environment.start()
        self.addCleanup(environment.stop)
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args],
                                       text=True, stderr=subprocess.DEVNULL).strip()

    def run_once(self):
        return dispatch_run(resolve_run_locations('001', self.root))

    def worktree_count(self):
        return len(self.git('worktree', 'list', '--porcelain').split('worktree ')) - 1

    def started(self, locations):
        from cardine.lifecycle.control import operation_state
        return operation_state(locations.worktree, '001')[0]

    def test_queued_task_gets_one_worktree_and_one_start(self):
        locations = resolve_run_locations('001', self.root)
        self.assertFalse(locations.worktree.exists())
        first = self.run_once()
        self.assertEqual((first['step'], first['action'], first['outcome']), ('worktree', 'execution-start', 'next'))
        self.assertEqual(self.worktree_count(), 2)
        state = self.started(locations)
        self.assertEqual(state['status'], 'in_progress')
        self.assertEqual(len(state['transitions']), 1)
        second = self.run_once()
        self.assertNotEqual(second['action'], 'execution-start')
        self.assertEqual(self.worktree_count(), 2)
        self.assertEqual(self.started(locations)['transitions'], state['transitions'])

    def kill(self, point):
        script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.lifecycle.context import resolve_run_locations
from cardine.lifecycle.engine import dispatch_run
def stop(name):
    if name == sys.argv[2]: os._exit(77)
receipts.boundary = stop
dispatch_run(resolve_run_locations('001', Path(sys.argv[1])))
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), point],
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_rerun_after_a_kill_converges(self):
        points = ('after_preparation_intent', 'after_worktree_registration', 'after_lifecycle_json',
                  'after_run_prepare', 'before_state_replace', 'after_state_replace',
                  'after_run_execution_start')
        for point in points:
            with self.subTest(point=point):
                if point != points[0]:
                    self.doCleanups()
                    self.setUp()
                locations = resolve_run_locations('001', self.root)
                self.kill(point)
                result = self.run_once()
                if point != 'after_run_execution_start':
                    self.assertEqual((result['step'], result['action'], result['outcome']),
                                     ('worktree', 'execution-start', 'next'), result)
                    self.assertFalse(result['diagnostics'], result)
                # A completed start is never repeated.
                self.assertNotEqual(self.run_once()['action'], 'execution-start')
                self.assertEqual(self.worktree_count(), 2)
                state = self.started(locations)
                self.assertEqual(state['status'], 'in_progress')
                self.assertEqual(len(state['transitions']), 1)


if __name__ == '__main__':
    unittest.main()
