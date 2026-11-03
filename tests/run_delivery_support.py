"""A disposable no-review project with a local bare remote, driven only through `run`.

The test plays the implementer: it edits and commits inside the task worktree
that `run` created, and every other step is performed by `dispatch_run`. Nothing
here touches the real home directory, the real worktree root, or a real remote.
"""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

from cardine.lifecycle.commands import execution_deliver
from cardine.lifecycle.context import resolve_run_locations
from cardine.lifecycle.engine import dispatch_run
from cardine.tasks.creation import create_task
from project_config_support import write_project_config
from task_contract_support import VALIDATION, contract_record

TASK = '001'
ROOT = Path(__file__).resolve().parents[1]
KILLED = 77


class DisposableDelivery:
    """One queued no-review task, a bare origin, and a private home directory."""

    def __init__(self):
        self.directory = Path(tempfile.mkdtemp(prefix='cardine-delivery-')).resolve()
        self.root = self.directory / 'project'
        self.origin = self.directory / 'origin.git'
        self.home = self.directory / 'home'
        self.worktrees = self.directory / 'worktrees'
        self._stack = ExitStack()

    def __enter__(self):
        self.home.mkdir()
        # The candidate binding digests the environment, so a killed subprocess and the
        # rerun in this process must see the same one.
        environment = {'PYTHONPATH': str(ROOT / 'src'), 'HOME': str(self.home), 'GIT_CONFIG_GLOBAL': os.devnull,
                       'CARDINE_WORKTREE_ROOT': str(self.worktrees),
                       'GIT_AUTHOR_NAME': 'Delivery Test', 'GIT_AUTHOR_EMAIL': 'delivery@example.test',
                       'GIT_COMMITTER_NAME': 'Delivery Test', 'GIT_COMMITTER_EMAIL': 'delivery@example.test'}
        self._stack.enter_context(patch.dict(os.environ, environment))
        previous = Path.cwd()
        self._stack.callback(os.chdir, previous)
        self._stack.callback(shutil.rmtree, self.directory, ignore_errors=True)
        self.root.mkdir()
        subprocess.run(['git', 'init', '--bare', '-b', 'main', str(self.origin)], check=True, capture_output=True)
        self.git('init', '-b', 'main')
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
        self.git('add', '.')
        self.git('commit', '-m', 'Initial policy')
        create_task(self.root, TASK, contract_record().replace(
            'Change the documented deliverable only.', '- `src/**`'))
        self.git('add', '.')
        self.git('commit', '-m', 'Create task')
        self.git('remote', 'add', 'origin', str(self.origin))
        self.git('push', 'origin', 'main')
        os.chdir(self.root)
        return self

    def __exit__(self, *exc):
        self._stack.close()

    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', '-C', str(cwd or self.root), *args],
                                       text=True, stderr=subprocess.STDOUT).strip()

    def remote_main(self):
        return subprocess.check_output(['git', '--git-dir', str(self.origin), 'rev-parse', 'refs/heads/main'],
                                       text=True).strip()

    @property
    def locations(self):
        return resolve_run_locations(TASK, self.root)

    def run(self):
        return dispatch_run(self.locations)

    def commit_implementation(self, text='result = 1\n'):
        """Play the implementer: write the declared deliverable and commit it in the worktree."""
        worker = self.locations.worktree
        (worker / 'src').mkdir(exist_ok=True)
        (worker / 'src/result.py').write_text(text)
        self.git('add', '.', cwd=worker)
        self.git('commit', '-m', 'Implement result', cwd=worker)
        return worker

    def implement(self):
        """Commit the implementation, then run the implementer's `execution deliver`."""
        self.commit_implementation()
        return self.deliver()

    def deliver(self):
        """The implementer's `execution deliver`, run from inside the task worktree."""
        worker = self.locations.worktree
        os.chdir(worker)
        try:
            return execution_deliver(worker, TASK)
        finally:
            os.chdir(self.root)

    def drive(self, limit=12):
        """Rerun `run` until it reports done; return each (step, action, outcome)."""
        seen = []
        for _ in range(limit):
            result = self.run()
            seen.append((result['step'], result['action'], result['outcome']))
            if result['outcome'] == 'done':
                return seen
            if result['outcome'] != 'next' or result['diagnostics']:
                raise AssertionError(result)
        raise AssertionError(seen)

    def closure(self):
        from cardine.worktree.closure_status import closure_status
        return closure_status(TASK, self.worktrees, self.root)[0]

    def kill(self, mode, point):
        """Run `deliver` or `run` in a subprocess that exits at one named effect boundary."""
        script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
receipts.boundary = lambda name: os._exit(%d) if name == sys.argv[3] else None
root, mode = Path(sys.argv[1]), sys.argv[2]
if mode == 'deliver':
    from cardine.lifecycle.commands import execution_deliver
    from cardine.lifecycle.context import resolve_run_locations
    worker = resolve_run_locations('%s', root).worktree
    os.chdir(worker)
    execution_deliver(worker, '%s')
else:
    from cardine.lifecycle.context import resolve_run_locations
    from cardine.lifecycle.engine import dispatch_run
    for _ in range(12):
        if dispatch_run(resolve_run_locations('%s', root))['outcome'] == 'done':
            break
''' % (KILLED, TASK, TASK, TASK)
        done = subprocess.run([sys.executable, '-c', script, str(self.root), mode, point], cwd=self.root,
                              env=dict(os.environ), capture_output=True, text=True)
        return done
