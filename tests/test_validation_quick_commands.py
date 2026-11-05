"""Retry variants can confirm failure but cannot pass a validation attempt."""
from copy import deepcopy
from pathlib import Path
import shlex
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from cardine.lifecycle import receipts
from cardine.lifecycle.validation import run_task_validation
from cardine.integration.candidate import run_candidate_validation
from cardine.integration import merge
import test_run_delivery
import worktree_support as support
from project_config_support import write_project_config
from task_contract_support import freeze_record


def kill_after_variant(root, kind):
    script = """
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.lifecycle.validation import run_task_validation
from cardine.integration.candidate import run_candidate_validation
count = 0
def boundary(name):
    global count
    if name == ('after_validation_logs' if sys.argv[2] == 'task' else 'after_candidate_logs'):
        count += 1
        if count == 2:
            os._exit(77)
receipts.boundary = boundary
if sys.argv[2] == 'task':
    run_task_validation(Path(sys.argv[1]), '001')
else:
    run_candidate_validation('056', Path(sys.argv[1]))
"""
    source = str(Path(__file__).resolve().parents[1] / 'src')
    result = subprocess.run([sys.executable, '-c', script, str(root), kind], cwd=root,
                            env={**os.environ, 'PYTHONPATH': source}, capture_output=True, text=True)
    if result.returncode != 77:
        raise AssertionError(result.stderr)


class RetryTaskTest(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, {'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
        environment.start()
        self.addCleanup(environment.stop)
        self.fixture = test_run_delivery.RunDeliveryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.worker = self.fixture.worker
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def attempt(self, full, retry=None, *, kill=False, prefix=None):
        original = self.fixture.state()
        state = deepcopy(original)
        policy = state['contract']['validation']
        policy['commands']['check'] = full
        policy['baseline'] = ['check']
        if prefix is not None:
            policy['commands']['prefix'] = prefix
            policy['baseline'].insert(0, 'prefix')
        if retry is not None:
            policy['retry'] = {'check': retry}
        state['contract']['deliverables'] = ['src/result.py']
        state['contract']['validationScoping'] = []
        state['contract']['hostImpact']['profiles'] = {}
        with receipts.task_lock(self.worker, '001'):
            receipts.write_operation(self.worker, '001', state, previous=original, kind='fixture-validation')
        self.fixture.git('add', '.')
        self.fixture.git('commit', '-m', 'Freeze retry policy')
        self.fixture.deliver()
        if kill:
            kill_after_variant(self.worker, 'task')
        return run_task_validation(self.worker, '001')

    def test_variant_exit_one_ends_attempt(self):
        result = self.attempt('exit 1', 'exit 1')
        self.assertEqual([r[0]['exitStatus'] for r in result['runs']], [1, 1])
        self.assertEqual(result['phase'], 'failed')
        self.assertEqual(result['consecutiveFailures'], 1)

    def test_successful_variant_cannot_pass_a_failing_complete_set(self):
        result = self.attempt('exit 1', 'exit 0')
        self.assertEqual([r[0]['exitStatus'] for r in result['runs']], [1, 0, 1])
        self.assertEqual(result['phase'], 'failed')

    def test_variant_zero_allows_passing_full_rerun(self):
        marker = shlex.quote(str(Path(self.directory.name) / 'marker'))
        result = self.attempt(f'if test -f {marker}; then exit 0; else touch {marker}; exit 1; fi', 'exit 0')
        self.assertEqual([r[0]['exitStatus'] for r in result['runs']], [1, 0, 0])
        self.assertEqual(result['phase'], 'passed')

    def test_variant_other_status_and_omission_rerun_full(self):
        result = self.attempt('exit 1', 'exit 2')
        self.assertEqual([r[0]['exitStatus'] for r in result['runs']], [1, 2, 1])

    def test_order_dependent_failure_cannot_be_passed_by_variant(self):
        marker = shlex.quote(str(Path(self.directory.name) / 'order'))
        result = self.attempt(f'test ! -f {marker}', 'exit 0', prefix=f'touch {marker}')
        self.assertEqual(result['phase'], 'failed')
        self.assertEqual(result['runs'][-1][-1]['exitStatus'], 1)

    def test_interrupted_variant_replays(self):
        result = self.attempt('exit 1', 'exit 0', kill=True)
        self.assertEqual([r[0]['exitStatus'] for r in result['runs']], [1, 0, 1])

    def test_omission_reruns_full(self):
        result = self.attempt('exit 1')
        self.assertEqual([r[0]['exitStatus'] for r in result['runs']], [1, 1])


class RetryCandidateTest(support.BoundedWorktreeLifecycleFixture):
    def setUp(self):
        super().setUp()
        environment = mock.patch.dict(os.environ, {'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
        environment.start()
        self.addCleanup(environment.stop)

    def attempt(self, full, retry=None, *, kill=False, prefix=None):
        policy = dict(commands={'check': full}, baseline=[],
                      candidate={key: ['check'] for key in ('REUSE', 'BOUNDED', 'FULL')})
        if prefix is not None:
            policy['commands']['prefix'] = prefix
            for references in policy['candidate'].values():
                references.insert(0, 'prefix')
        if retry is not None:
            policy['retry'] = {'check': retry}
        write_project_config(self.primary, validation=policy)
        freeze_record(self.primary, '056', self.primary / 'tasks/056-lifecycle.md')
        self.git('add', '.')
        self.git('commit', '-m', 'Freeze candidate retry policy')
        self.worker = Path(self.prepare()['worktree'])
        (self.worker / 'feature.txt').write_text('implemented\n')
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'Implement', cwd=self.worker)
        self.measure(self.worker)
        merge.stage_task_integration('056', self.worktree_root, None, self.primary)
        if kill:
            kill_after_variant(self.primary, 'candidate')
        return run_candidate_validation('056', self.primary)

    def test_variant_exit_one_ends_attempt(self):
        result = self.attempt('exit 1', 'exit 1')
        self.assertEqual([r[-1]['exitStatus'] for r in result['runs']], [1, 1])
        self.assertEqual(result['phase'], 'failed')

    def test_variant_zero_does_not_pass_failing_full_set(self):
        result = self.attempt('exit 1', 'exit 0')
        self.assertEqual([r[-1]['exitStatus'] for r in result['runs']], [1, 0, 1])
        self.assertEqual(result['phase'], 'failed')

    def test_variant_zero_allows_passing_full_rerun(self):
        marker = shlex.quote(str(self.root / 'marker'))
        result = self.attempt(f'if test -f {marker}; then exit 0; else touch {marker}; exit 1; fi', 'exit 0')
        self.assertEqual([r[-1]['exitStatus'] for r in result['runs']], [1, 0, 0])
        self.assertEqual(result['phase'], 'passed')
        merge.finalize_task_integration('056', None, self.primary)

    def test_variant_other_status_reruns_full(self):
        result = self.attempt('exit 1', 'exit 2')
        self.assertEqual([r[-1]['exitStatus'] for r in result['runs']], [1, 2, 1])

    def test_order_dependent_failure_cannot_be_passed_by_variant(self):
        marker = shlex.quote(str(self.root / 'order'))
        result = self.attempt(f'test ! -f {marker}', 'exit 0', prefix=f'touch {marker}')
        self.assertEqual(result['phase'], 'failed')
        self.assertEqual(result['runs'][-1][-1]['exitStatus'], 1)

    def test_interrupted_variant_replays(self):
        result = self.attempt('exit 1', 'exit 0', kill=True)
        self.assertEqual([r[-1]['exitStatus'] for r in result['runs']], [1, 0, 1])

    def test_omission_reruns_full(self):
        result = self.attempt('exit 1')
        self.assertEqual([r[-1]['exitStatus'] for r in result['runs']], [1, 1])
