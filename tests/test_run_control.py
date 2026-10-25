"""Cancel retains work; abort replays only exact owned integration effects."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from cardine.lifecycle import receipts
from cardine.lifecycle.control import cancel_task
from cardine.lifecycle.control_abort import abort_owned
from cardine.shared.errors import CardineError
from cardine.tasks.transitions import transition_task_state
from cardine.tasks.state import state_path, read_task_state
from cardine.stops.render import stop_error
from cardine.worktree.storage import _lifecycle_paths
from cardine.tasks.identity import resolve_task_identity
import test_run_delivery
import worktree_support
from control_support import adapter

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_POINTS = tuple(prefix + name for name in ('intent', 'staged_pair', 'state_replace', 'result_receipt')
                       for prefix in ('before_', 'after_'))
ABORT_POINTS = tuple(prefix + name for name in ('abort_intent', 'abort_merge', 'abort_state_unlink',
                      'abort_lease_unlink', 'abort_result') for prefix in ('before_', 'after_'))


def killed(root, point, action, primary=None, phase=1):
    script = '''
import os,sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.lifecycle.control import cancel_task
from cardine.lifecycle.control_abort import abort_owned
from control_support import adapter
seen = 0
def kill(name):
    global seen
    if name == sys.argv[2]:
        seen += 1
        if seen == int(sys.argv[4]): os._exit(77)
receipts.boundary = kill
if sys.argv[3] == 'cancel':
    cancel_task('001', Path(sys.argv[1]), reason='Superseded', adapter=adapter())
else:
    abort_owned('056', Path(sys.argv[1]), adapter=adapter('coordinator'))
'''
    return subprocess.run([sys.executable, '-c', script, str(primary or root), point, action, str(phase)], cwd=root,
        env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT/'src'), str(ROOT/'tests')])},
        capture_output=True, text=True)


class RunCancelTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_delivery.RunDeliveryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.worker

    def cancel(self, **kwargs):
        return cancel_task('001', self.root, reason=kwargs.pop('reason', 'Superseded'),
                           adapter=kwargs.pop('adapter', adapter()), **kwargs)

    def test_every_cancel_and_receipt_boundary_retains_branch_and_time_once(self):
        for index, point in enumerate((*RECEIPT_POINTS, 'before_cancel_transition', 'after_cancel_transition')):
            with self.subTest(point=point):
                if index:
                    self.doCleanups()
                    self.setUp()
                head = self.fixture.git('rev-parse', 'HEAD')
                (self.root/'src/uncommitted.py').write_text('retained = True\n')
                result = killed(self.root, point, 'cancel')
                self.assertEqual(result.returncode, 77, result.stderr)
                state = self.cancel()
                self.assertEqual(self.cancel(), state)
                self.assertEqual(state['status'], 'cancelled')
                self.assertEqual(sum(t['to'] == 'cancelled' for t in state['transitions']), 1)
                self.assertEqual(self.fixture.git('rev-parse', 'HEAD'), head)
                self.assertEqual(self.fixture.git('branch', '--show-current'), 'task-001')
                self.assertTrue((self.root/'src/uncommitted.py').exists())
                with self.assertRaises(CardineError):
                    transition_task_state(self.root, '001', 'in_progress')

    def test_cancel_changed_inputs_owner_and_unknown_operation_refuse(self):
        for point in ('after_intent', 'after_state_replace', 'after_result_receipt', 'after_cancel_transition'):
            for change in ('source', 'reason', 'owner'):
                self.doCleanups()
                self.setUp()
                result = killed(self.root, point, 'cancel')
                self.assertEqual(result.returncode, 77, result.stderr)
                if change == 'source':
                    (self.root/'src/result.py').write_text('changed\n')
                before = state_path(self.root, '001').read_bytes()
                with self.assertRaises(CardineError):
                    self.cancel(reason='Changed' if change == 'reason' else 'Superseded',
                                adapter=adapter('reviewer') if change == 'owner' else adapter())
                self.assertEqual(state_path(self.root, '001').read_bytes(), before)
        self.doCleanups()
        self.setUp()
        before = self.fixture.state()
        with self.assertRaises(CardineError):
            transition_task_state(self.root, '001', 'cancelled', cancellation_authority='owner', reason='Spoofed')
        self.assertEqual(self.fixture.state(), before)

    def test_cancelled_resolves_terminal_and_restart_uses_new_task(self):
        from cardine.lifecycle.engine import resolve_run, RunFacts, run_preview_cli
        self.cancel()
        from cardine.lifecycle.context import resolve_run_locations
        locations = resolve_run_locations('001', self.root)
        result = resolve_run(RunFacts('001', locations.primary, 'cancelled'))
        self.assertEqual(result['outcome'], 'done')
        self.assertIsNone(result['next'])
        from cardine.tasks.creation import create_task
        # The same ID is never reopened by creation, even with developer reason.
        with self.assertRaises(CardineError):
            create_task(self.root, '001', 'Restart')
        self.assertEqual(self.fixture.state()['status'], 'cancelled')
        from task_contract_support import contract_record
        created = create_task(self.root, '002', contract_record('002'))
        self.assertEqual(read_task_state(self.root, '002', 'single', stop_factory=stop_error)['task_id'], '002')
        self.assertEqual(self.fixture.state()['status'], 'cancelled')

    def test_queued_cancellation_does_not_prepare_a_worktree_or_branch(self):
        import test_run_preparation
        fixture = test_run_preparation.RunPreparationTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        state = cancel_task('001', fixture.root, reason='Superseded before launch', adapter=adapter())
        self.assertEqual(state['status'], 'cancelled')
        self.assertEqual(fixture.git('branch', '--show-current'), 'main')
        self.assertNotIn('task-001', fixture.git('branch', '--list'))
        self.assertEqual(state, cancel_task('001', fixture.root, reason='Superseded before launch', adapter=adapter()))


class RunAbortTest(unittest.TestCase):
    def setUp(self):
        self.fixture = worktree_support.BoundedWorktreeLifecycleFixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)
        self.primary = self.fixture.primary
        self.worker = Path(self.fixture.prepare()['worktree'])
        (self.worker/'feature.txt').write_text('candidate\n')
        self.fixture.git('add', '.', cwd=self.worker)
        self.fixture.git('commit', '-m', 'Implement candidate', cwd=self.worker)
        self.fixture.measure(self.worker)
        from cardine.integration.merge import stage_task_integration
        stage_task_integration('056', self.fixture.worktree_root, None, self.primary)
        identity = resolve_task_identity(self.primary, '056', 'existing')
        _, self.lease, self.staged = _lifecycle_paths(self.primary, identity)

    def abort(self, **kwargs):
        return abort_owned('056', self.primary, adapter=kwargs.pop('adapter', adapter('coordinator')), **kwargs)

    def test_every_abort_and_receipt_boundary_converges_once(self):
        cases = [(point, 1) for point in (*ABORT_POINTS, *RECEIPT_POINTS)]
        cases += [(point, 2) for point in RECEIPT_POINTS]
        for index, (point, phase) in enumerate(cases):
            with self.subTest(point=point, phase=phase):
                if index:
                    self.doCleanups()
                    self.setUp()
                head = self.fixture.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip()
                result = killed(self.primary, point, 'abort', phase=phase)
                self.assertEqual(result.returncode, 77, result.stderr)
                self.assertEqual(self.abort(), self.abort())
                self.assertFalse(self.lease.exists())
                self.assertFalse(self.staged.exists())
                self.assertFalse((self.primary/'.git/MERGE_HEAD').exists())
                self.assertEqual(self.fixture.git('rev-parse', 'HEAD').stdout.strip(), self.fixture.base)
                self.assertEqual(self.fixture.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip(), head)
                state = read_task_state(self.worker, '056', 'single', stop_factory=stop_error)
                self.assertEqual(state['status'], 'in_progress')
                self.assertEqual(sum(r['kind'].startswith('abort:') for r in state['run']['receipts']), 1)
                self.assertEqual(sum(r['kind'].startswith('abort-result:') for r in state['run']['receipts']), 1)
                self.assertEqual(state['run']['ownedAbortResult']['result'], 'verified')

    def test_each_effect_rejects_foreign_owner_changed_source_and_lease(self):
        for point in ('after_abort_intent', 'after_abort_merge', 'after_abort_state_unlink',
                      'after_abort_lease_unlink', 'after_abort_result'):
            for change in ('owner', 'source', 'lease'):
                self.doCleanups()
                self.setUp()
                result = killed(self.primary, point, 'abort')
                self.assertEqual(result.returncode, 77, result.stderr)
                if change == 'source':
                    (self.worker/'feature.txt').write_text('foreign source\n')
                elif change == 'lease':
                    self.lease.write_text(json.dumps(dict(task_id='foreign', project=str(self.primary), branch='foreign')))
                before = self.lease.read_bytes() if self.lease.exists() else None
                with self.assertRaises(CardineError):
                    self.abort(adapter=adapter('developer') if change == 'owner' else adapter('coordinator'))
                self.assertEqual(self.lease.read_bytes() if self.lease.exists() else None, before)


    def test_foreign_primary_work_and_changed_index_are_never_aborted(self):
        readme = self.primary/'README.md'
        readme.write_text('foreign primary work\n')
        before = self.lease.read_bytes()
        with self.assertRaisesRegex(CardineError, 'foreign candidate changes'):
            self.abort()
        self.assertEqual(readme.read_text(), 'foreign primary work\n')
        self.assertEqual(self.lease.read_bytes(), before)
        self.doCleanups()
        self.setUp()
        result = killed(self.primary, 'after_abort_intent', 'abort')
        self.assertEqual(result.returncode, 77, result.stderr)
        self.fixture.git('restore', '--staged', '--', 'feature.txt')
        before = self.lease.read_bytes()
        with self.assertRaisesRegex(CardineError, 'candidate changed'):
            self.abort()
        self.assertEqual(self.lease.read_bytes(), before)
        self.assertEqual((self.primary/'feature.txt').read_text(), 'candidate\n')
