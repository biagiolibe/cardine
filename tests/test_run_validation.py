"""Real exits, bounded complete attempts, receipt forgery and crash recovery."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine.lifecycle import receipts
from cardine.lifecycle.validation import run_task_validation, verified_validation, operation_path
from cardine.shared.errors import CardineError, CardineStop
from cardine.tasks.state import state_path
import test_run_delivery

ROOT = Path(__file__).resolve().parents[1]
POINTS = tuple(prefix + name for name in ('validation_intent', 'validation_process',
    'validation_exit', 'validation_logs', 'validation_counter', 'validation_evidence',
    'validation_result', 'intent', 'staged_pair', 'state_replace', 'result_receipt')
    for prefix in ('before_', 'after_'))


class RunValidationTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_delivery.RunDeliveryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.worker = self.fixture.worker
        self.git = self.fixture.git
        self.state = self.fixture.state
        self.configure({'one': 'printf actual-output', 'two': 'printf actual-error >&2'})

    def configure(self, commands, *, limit=3, scoping=(), profiles=None):
        original = self.state()
        updated = deepcopy(original)
        contract = updated['contract']
        contract['validation']['commands'].update(commands)
        contract['validation']['baseline'] = list(commands)
        contract['options']['validationRetryLimit'] = limit
        contract['options']['review'] = 'not_required'
        contract['deliverables'] = ['src/result.py']
        contract['validationScoping'] = list(scoping)
        contract['hostImpact']['profiles'] = profiles or {}
        with receipts.task_lock(self.worker, '001'):
            receipts.write_operation(self.worker, '001', updated, previous=original, kind='fixture-validation')
        self.git('add', '.')
        self.git('commit', '-m', 'Freeze measured validation')
        self.fixture.deliver()

    def run_attempt(self):
        return run_task_validation(self.worker, '001')

    def kill(self, point):
        script = '''
import os,sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.lifecycle.validation import run_task_validation
def kill(name):
    if name == sys.argv[2]: os._exit(77)
receipts.boundary = kill
run_task_validation(Path(sys.argv[1]), '001')
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.worker), point], cwd=self.worker,
            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_actual_results_and_repeated_resolution_write_nothing(self):
        progress = self.run_attempt()
        self.assertEqual(progress['phase'], 'passed')
        self.assertEqual([item['exitStatus'] for item in progress['runs'][0]], [0, 0])
        self.assertEqual(progress['runs'][0][0]['stdout'], 'actual-output')
        self.assertEqual(progress['runs'][0][1]['stderr'], 'actual-error')
        self.assertEqual(progress['acceptanceReferences'][0]['path'], 'src/result.py')
        state = state_path(self.worker, '001').read_bytes()
        self.assertEqual(self.run_attempt(), progress)
        self.assertEqual(state_path(self.worker, '001').read_bytes(), state)

    def test_n_failures_count_complete_sets_once_and_exhaustion_survives_new_source(self):
        self.configure({'one': 'exit 7', 'two': 'exit 9'}, limit=2)
        first = self.run_attempt()
        self.assertEqual(first['consecutiveFailures'], 1)
        self.assertEqual(len(first['runs']), 2)
        self.assertEqual(self.run_attempt(), first)
        self.repair()
        with self.assertRaises(CardineStop) as caught:
            self.run_attempt()
        self.assertEqual(caught.exception.code, 'VALIDATION_RETRY_LIMIT')
        self.assertEqual(self.state()['run']['validation']['consecutiveFailures'], 2)
        self.repair()
        with self.assertRaises(CardineStop) as caught:
            self.run_attempt()
        self.assertEqual(caught.exception.code, 'VALIDATION_RETRY_LIMIT')

    def repair(self):
        path = self.worker / 'src/result.py'
        path.write_text(path.read_text() + '# repair\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Repair source')
        self.fixture.deliver()

    def test_full_unchanged_rerun_records_actual_intermittent_and_resets_count(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'marker'
            command = f'if test -f {shlex.quote(str(marker))}; then exit 0; else touch {shlex.quote(str(marker))}; exit 17; fi'
            self.configure({'one': command, 'two': 'printf full-set'})
            result = self.run_attempt()
        self.assertEqual(result['consecutiveFailures'], 0)
        self.assertEqual(len(result['runs']), 2)
        self.assertEqual(result['intermittent'][0]['exitStatus'], 17)
        self.assertEqual(result['runs'][1][1]['stdout'], 'full-set')
        handoff = self.worker / 'tasks/handoffs/001.md'
        self.assertIn('Intermittent commands: one', handoff.read_text())

    def test_scoping_and_host_checks_use_only_frozen_commands(self):
        self.configure({'one': 'exit 99', 'codex': 'printf observed'}, profiles={'codex': 'enforced'},
            scoping=[dict(paths=['docs/**'], commands=['one'])])
        progress = self.run_attempt()
        self.assertEqual(progress['phase'], 'passed')
        self.assertEqual(progress['inputs']['skips'][0]['id'], 'one')
        self.assertEqual(progress['hostObservations'][0]['exitStatus'], 0)
        self.assertTrue(progress['hostObservations'][0]['observed'])
        from cardine.tasks.contract import verify_execution_evidence
        verify_execution_evidence(self.worker, '001')

    def test_changed_source_environment_and_stale_ledger_never_reuse_success(self):
        original = self.run_attempt()
        with patch.dict(os.environ, {'CARDINE_TEST_ENVIRONMENT': 'changed'}):
            self.assertIsNone(verified_validation(self.worker, '001'))
            changed = self.run_attempt()
            self.assertNotEqual(changed['attemptId'], original['attemptId'])
        path = self.worker / '.cardine/evidence/001.json'
        saved = path.read_bytes()
        ledger = json.loads(saved)
        ledger['001'][0]['exitStatus'] = 42
        path.write_text(json.dumps(ledger))
        with self.assertRaises(CardineError):
            verified_validation(self.worker, '001')
        path.write_bytes(saved)
        (self.worker / 'src/result.py').write_text('changed')
        self.assertIsNone(verified_validation(self.worker, '001'))

    def test_f04_f05_f15_forged_results_contract_and_source_fail_closed(self):
        ledger = self.worker / '.cardine/evidence/001.json'
        ledger.parent.mkdir(exist_ok=True)
        ledger.write_text(json.dumps({'001': [dict(id='one', command='printf actual-output', exitStatus=0)]}))
        # An unreceipted ledger cannot establish current attempt progress.
        self.assertIsNone(verified_validation(self.worker, '001'))
        ledger.unlink()
        self.run_attempt()
        original = state_path(self.worker, '001').read_bytes()
        forged = json.loads(original)
        forged['run']['validation']['consecutiveFailures'] = 999
        state_path(self.worker, '001').write_text(json.dumps(forged))
        with self.assertRaises(CardineError):
            self.run_attempt()
        state_path(self.worker, '001').write_bytes(original)
        (self.worker / 'foreign.py').write_text('outside authority')
        with self.assertRaisesRegex(CardineError, 'outside expected surface'):
            self.run_attempt()

    def test_missing_evidence_exact_recovery_command_reaches_c6(self):
        from cardine.worktree.closure_status import closure_status
        status, ready = closure_status('001', None, self.fixture.root)
        self.assertFalse(ready)
        self.assertEqual((status['step'], status['stop_reason']), ('C5', 'EVIDENCE_INCOMPLETE'))
        argv = shlex.split(status['resume'])
        with tempfile.TemporaryDirectory() as directory:
            shim = Path(directory) / 'cardine'
            shim.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -m cardine.cli "$@"\n')
            shim.chmod(0o755)
            result = subprocess.run(argv, cwd=self.worker, env={**os.environ,
                'PATH': directory + os.pathsep + os.environ['PATH'], 'PYTHONPATH': str(ROOT / 'src')},
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        value = json.loads(result.stdout)
        self.assertEqual((value['step'], value['action']), ('candidate', 'validate-candidate'))
        self.assertEqual(self.state()['run']['validation']['phase'], 'passed')

    def test_changed_environment_before_rerun_invalidates_without_intermittence_or_count(self):
        self.configure({'one': 'exit 8'})
        changed_environment = patch.dict(os.environ, {'CARDINE_CHANGED_DURING_ATTEMPT': 'yes'})
        self.addCleanup(changed_environment.stop)
        def change(name):
            if name == 'after_validation_logs':
                changed_environment.start()
        with patch.object(receipts, 'boundary', change):
            with self.assertRaises(CardineStop) as caught:
                self.run_attempt()
            self.assertEqual(caught.exception.code, 'VALIDATION_FAILED')
        changed_environment.stop()
        self.assertNotIn('validation', self.state()['run'])
        result = self.run_attempt()
        self.assertEqual(result['consecutiveFailures'], 1)
        self.assertEqual(result['intermittent'], [])

    def test_missing_acceptance_deliverable_returns_implementation_work(self):
        self.git('rm', 'src/result.py')
        self.git('commit', '-m', 'Remove required result')
        from cardine.lifecycle.engine import run_validation_step, resolve_run_locations
        result = run_validation_step(resolve_run_locations('001', self.worker))
        self.assertEqual(result['step'], 'implementation')
        self.assertEqual(result['work']['role'], 'implementer')

    def test_external_success_record_does_not_replace_actual_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory) / 'success.json'
            proof.write_text(json.dumps(dict(passed=True, exitStatus=0, attested_by='developer')))
            self.configure({'one': 'exit 19'})
            result = self.run_attempt()
        self.assertEqual(result['phase'], 'failed')
        self.assertEqual(result['runs'][0][0]['exitStatus'], 19)

    def test_success_after_repair_resets_consecutive_failures(self):
        self.configure({'one': 'exit 7'})
        self.assertEqual(self.run_attempt()['consecutiveFailures'], 1)
        self.configure({'one': 'true'})
        self.assertEqual(self.run_attempt()['consecutiveFailures'], 0)

    def test_live_runner_never_starts_a_second_process(self):
        from concurrent.futures import ThreadPoolExecutor
        from cardine.lifecycle.validation import runner_lock
        with runner_lock(self.worker, '001'), ThreadPoolExecutor() as pool:
            with self.assertRaisesRegex(CardineError, 'live foreign validation'):
                pool.submit(self.run_attempt).result()

    def test_commands_mutating_source_invalidate_and_fresh_delivery_can_recover(self):
        self.configure({'one': 'printf mutated > src/result.py'})
        with self.assertRaises(CardineStop) as caught:
            self.run_attempt()
        self.assertEqual(caught.exception.code, 'VALIDATION_FAILED')
        self.assertNotIn('validation', self.state()['run'])
        self.git('add', '.')
        self.git('commit', '-m', 'Deliver changed implementation')
        self.fixture.deliver()
        result = self.run_attempt()
        self.assertEqual((result['phase'], len(result['runs']), result['consecutiveFailures']), ('passed', 1, 0))

    def test_large_process_output_is_bounded_and_marked_without_losing_exit(self):
        from cardine.lifecycle.validation import LOG_LIMIT
        command = shlex.quote(sys.executable) + ' -c ' + shlex.quote(
            'import sys; sys.stdout.write("x"*100000); sys.stderr.write("y"*100000)')
        self.configure({'one': command})
        result = self.run_attempt()['runs'][0][0]
        self.assertEqual(result['exitStatus'], 0)
        for stream in ('stdout', 'stderr'):
            self.assertEqual(len(result[stream]), LOG_LIMIT)
            self.assertTrue(result[stream + 'Truncated'])

    def test_exhausted_interrupted_publication_can_resume_after_authorized_budget_revision(self):
        self.configure({'one': 'exit 7'}, limit=1)
        with patch.dict(os.environ, {'PYTHONPATH': str(ROOT / 'src')}):
            self.kill('after_validation_evidence')
            self.assertEqual(self.state()['run']['validation']['consecutiveFailures'], 1)
            self.configure({'one': 'true'}, limit=2)
            self.assertEqual(self.run_attempt()['consecutiveFailures'], 0)


def interrupted(point):
    def test(self):
        head = self.git('rev-parse', 'HEAD')
        with patch.dict(os.environ, {'PYTHONPATH': str(ROOT / 'src')}):
            self.kill(point)
            result = self.run_attempt()
            self.assertEqual(result['phase'], 'passed')
            self.assertEqual(self.run_attempt(), result)
        state = self.state()
        self.assertEqual(sum(r['kind'] == 'task-validation' for r in state['run']['receipts']), 1)
        self.assertEqual(state['run']['validation']['consecutiveFailures'], 0)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(json.loads((self.worker / '.cardine/evidence/001.json').read_bytes())['001'], result['runs'][0])
    return test


for _point in POINTS:
    setattr(RunValidationTest, 'test_replay_' + _point, interrupted(_point))


def changed_input_and_owner(point):
    def test(self):
        with patch.dict(os.environ, {'PYTHONPATH': str(ROOT / 'src')}):
            self.kill(point)
            path = self.worker / 'src/result.py'
            original = path.read_bytes()
            path.write_text('foreign input; preserve\n')
            with self.assertRaises(CardineError):
                self.run_attempt()
            self.assertEqual(path.read_text(), 'foreign input; preserve\n')
            path.write_bytes(original)
            operation = operation_path(self.worker, '001')
            intent = receipts._load_intent(operation) if operation.exists() else dict(
                root=str(self.worker), authority=receipts.require_authority(self.worker))
            receipts._save_intent(operation, dict(intent, task_id='foreign'))
            before = state_path(self.worker, '001').read_bytes()
            with self.assertRaisesRegex(CardineError, 'foreign owner'):
                self.run_attempt()
            self.assertEqual(state_path(self.worker, '001').read_bytes(), before)
    return test


for _point in POINTS:
    setattr(RunValidationTest, 'test_negative_' + _point, changed_input_and_owner(_point))


def interrupted_failure(point):
    def test(self):
        self.configure({'one': 'exit 7', 'two': 'exit 9'}, limit=1)
        with patch.dict(os.environ, {'PYTHONPATH': str(ROOT / 'src')}):
            self.kill(point)
            for _ in range(2):
                with self.assertRaises(CardineStop) as caught:
                    self.run_attempt()
                self.assertEqual(caught.exception.code, 'VALIDATION_RETRY_LIMIT')
        state = self.state()
        self.assertEqual(state['run']['validation']['consecutiveFailures'], 1)
        self.assertEqual(len(state['run']['validation']['runs']), 2)
        self.assertEqual(sum(r['kind'] == 'task-validation' for r in state['run']['receipts']), 1)
    return test


for _point in POINTS:
    setattr(RunValidationTest, 'test_failed_replay_' + _point, interrupted_failure(_point))


if __name__ == '__main__':
    unittest.main()
