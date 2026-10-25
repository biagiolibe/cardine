"""Measured candidates and replay across the finalize effect boundaries (RE5b)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
from cardine.integration import candidate, merge
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError, CardineStop
from cardine.tasks.state import state_path
from cardine.worktree.storage import _lifecycle_paths
from cardine.tasks.identity import resolve_task_identity
import worktree_support as support


class CandidateTest(support.BoundedWorktreeLifecycleFixture):
    def setUp(self):
        super().setUp()
        environment = mock.patch.dict(os.environ, {'PYTHONPATH': str(ROOT / 'src')})
        environment.start()
        self.addCleanup(environment.stop)

    def ready(self, command=None):
        if command:
            from task_contract_support import freeze_record
            from project_config_support import write_project_config
            policy = dict(commands={'check': command}, baseline=[],
                          candidate={key: ['check'] for key in ('REUSE', 'BOUNDED', 'FULL')})
            write_project_config(self.primary, validation=policy)
            freeze_record(self.primary, '056', self.primary / 'tasks/056-lifecycle.md')
            self.git('add', '.')
            self.git('commit', '-m', 'freeze candidate policy')
        self.worker = Path(self.prepare()['worktree'])
        (self.worker / 'feature.txt').write_text('implemented\n')
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'implement', cwd=self.worker)
        self.measure(self.worker)
        return merge.stage_task_integration('056', self.worktree_root, None, self.primary)

    def paths(self):
        return _lifecycle_paths(self.primary, resolve_task_identity(self.primary, '056', 'existing'))

    def run_candidate(self):
        return candidate.run_candidate_validation('056', self.primary)

    def finalize(self):
        return merge.finalize_task_integration('056', None, self.primary)

    def kill(self, point, action):
        script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.integration.candidate import run_candidate_validation
from cardine.integration.merge import finalize_task_integration
receipts.boundary = lambda name: os._exit(97) if name == sys.argv[2] else None
root = Path(sys.argv[1])
if sys.argv[3] == 'candidate': run_candidate_validation('056', root)
else: finalize_task_integration('056', None, root)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.primary), point, action],
            cwd=self.primary, env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 97, result.stderr)

    def test_actual_results_and_repeat_do_not_rerun_commands(self):
        self.ready('printf candidate-output')
        first = self.run_candidate()
        self.assertEqual(first['phase'], 'passed')
        self.assertEqual(first['runs'][0][-1]['stdout'], 'candidate-output')
        with mock.patch.object(candidate, 'execute_command', side_effect=AssertionError('repeated process')):
            self.assertEqual(self.run_candidate(), first)
        result = self.finalize()
        self.assertEqual(self.finalize(), result)
        self.assertEqual(self.git('rev-list', '--count', '--merges', 'main').stdout.strip(), '1')
        self.assertEqual(self.git('show', '-s', '--format=%T').stdout.strip(), result['candidate_tree'])

    def test_declared_pass_file_has_no_authority(self):
        staged = self.ready()
        forged = self.root / 'passed.json'
        forged.write_text(json.dumps(dict(candidate_tree=staged['candidate_tree'], passed=True,
                                        commands=['git diff --check'], scope='bounded')))
        with self.assertRaisesRegex(CardineStop, 'no current measured'):
            merge.finalize_task_integration('056', forged, self.primary)
        self.assertTrue(self.paths()[1].exists())

    def test_changed_tree_configuration_and_foreign_lease_fail_closed(self):
        self.ready()
        self.run_candidate()
        _, lease, staged = self.paths()
        before = lease.read_bytes()
        foreign = json.loads(before)
        foreign['task_id'] = '999'
        lease.write_text(json.dumps(foreign))
        with self.assertRaisesRegex(CardineError, 'foreign candidate'):
            self.finalize()
        self.assertEqual(json.loads(lease.read_bytes()), foreign)
        lease.write_bytes(before)
        policy = self.primary / '.cardine/project.json'
        original = policy.read_bytes()
        policy.write_bytes(original + b'\n')
        with self.assertRaises(CardineError):
            self.finalize()
        policy.write_bytes(original)
        (self.primary / 'late.txt').write_text('late')
        self.git('add', 'late.txt')
        with self.assertRaisesRegex(CardineStop, 'candidate tree or main changed'):
            self.finalize()
        self.assertTrue(staged.exists())

    def test_process_mutating_tree_cannot_publish_a_pass(self):
        self.ready('printf changed > feature.txt')
        with self.assertRaisesRegex(CardineError, 'candidate tree or main changed'):
            self.run_candidate()
        self.assertNotIn('candidateValidation', json.loads(state_path(self.worker, '056').read_bytes())['run'])

    def test_failure_shares_task_allowance_and_is_counted_once(self):
        self.ready('exit 7')
        first = self.run_candidate()
        self.assertEqual((first['phase'], first['consecutiveFailures'], len(first['runs'])), ('failed', 1, 2))
        self.assertEqual(self.run_candidate(), first)
        state = json.loads(state_path(self.worker, '056').read_bytes())
        self.assertEqual(state['run']['validation']['consecutiveFailures'], 1)
        merge.abort_task_integration('056', self.primary)
        self.assertFalse(self.paths()[1].exists())
        self.assertTrue((self.worker / 'feature.txt').exists())

    def test_unchanged_rerun_is_measured_intermittent(self):
        marker = self.root / 'marker'
        self.ready(f'test -f {marker} || (touch {marker}; exit 1)')
        result = self.run_candidate()
        self.assertEqual((result['phase'], result['consecutiveFailures'], len(result['runs'])), ('passed', 0, 2))
        self.assertEqual(len(result['intermittent']), 1)

    def test_wait_is_bounded_and_release_recomputes_main(self):
        self.ready()
        locations = candidate.locations_for('056', self.primary)
        _, lease, _ = self.paths()
        foreign = json.loads(lease.read_bytes())
        foreign.update(task_id='999', branch='task-999')
        lease.write_text(json.dumps(foreign))
        ticks = [0]
        def sleep(seconds):
            self.assertGreaterEqual(seconds, 5)
            ticks[0] += seconds
        self.assertFalse(candidate.wait_for_lease(locations, sleep=sleep, clock=lambda: ticks[0]))
        self.assertEqual(ticks[0], 60)
        preserved = lease.read_bytes()
        with self.assertRaises(CardineError):
            merge.abort_task_integration('056', self.primary)
        self.assertEqual(lease.read_bytes(), preserved)
        def release(seconds):
            sleep(seconds)
            lease.unlink()
        self.assertTrue(candidate.wait_for_lease(locations, sleep=release, clock=lambda: ticks[0]))

    def test_textual_conflict_and_transient_git_failure_are_distinct(self):
        self.ready()
        merge.abort_task_integration('056', self.primary)
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'record owned abort', cwd=self.worker)
        real = merge._run_git
        def fail(root, *args, **kwargs):
            if args[:3] == ('merge', '--no-ff', '--no-commit'):
                return subprocess.CompletedProcess(args, 128, '', 'temporary index lock')
            return real(root, *args, **kwargs)
        with mock.patch.object(merge, '_run_git', side_effect=fail), self.assertRaises(CardineStop) as raised:
            merge.stage_task_integration('056', self.worktree_root, None, self.primary)
        self.assertEqual(raised.exception.code, 'GIT_OPERATION_FAILED')
        self.assertFalse(self.paths()[1].exists())
        (self.primary / 'feature.txt').write_text('conflicting main\n')
        self.git('add', 'feature.txt')
        self.git('commit', '-m', 'conflicting main')
        with self.assertRaises(CardineStop) as raised:
            merge.stage_task_integration('056', self.worktree_root, None, self.primary)
        self.assertEqual(raised.exception.code, 'INTEGRATION_CONFLICT')
        self.assertFalse((self.primary / '.git/MERGE_HEAD').exists())
        self.assertEqual((self.primary / 'feature.txt').read_text(), 'conflicting main\n')

    def test_run_commands_execute_from_unrelated_directory(self):
        self.ready('printf isolated-output')
        command = [sys.executable, '-m', 'cardine.cli', 'run', '056', '--project', str(self.primary)]
        for action in ('validate-candidate', 'finalize'):
            result = subprocess.run(command, cwd=self.root, env=dict(os.environ), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            value = json.loads(result.stdout)
            self.assertEqual(value['action'], action)
            self.assertNotIn('isolated-output', result.stdout)
        self.assertEqual(self.git('rev-list', '--count', '--merges', 'main').stdout.strip(), '1')

    def test_candidate_exhaustion_aborts_before_the_guardrail(self):
        self.ready('exit 7')
        from copy import deepcopy
        from cardine.lifecycle.control import operation_state
        state, _ = operation_state(self.worker, '056')
        updated = deepcopy(state)
        updated['run']['validation']['consecutiveFailures'] = 2
        with receipts.task_lock(self.worker, '056'):
            receipts.write_operation(self.worker, '056', updated, previous=state, kind='fixture-allowance')
        from cardine.lifecycle.engine import run_integration_step
        with self.assertRaises(CardineStop) as raised:
            run_integration_step(candidate.locations_for('056', self.primary))
        self.assertEqual(raised.exception.code, 'VALIDATION_RETRY_LIMIT')
        self.assertFalse(self.paths()[1].exists() or self.paths()[2].exists())
        state, _ = operation_state(self.worker, '056')
        self.assertEqual(candidate.failure_count(state), 3)
        with self.assertRaises(CardineStop) as raised:
            candidate.require_budget(state, '056', self.primary)
        self.assertEqual(raised.exception.code, 'VALIDATION_RETRY_LIMIT')

    def test_finalize_replay_preserves_a_foreign_lease_after_commit(self):
        self.ready()
        self.run_candidate()
        self.kill('after_finalize_commit', 'finalize')
        _, lease, staged = self.paths()
        original = lease.read_bytes()
        foreign = json.loads(original)
        foreign['task_id'] = '999'
        lease.write_text(json.dumps(foreign))
        with self.assertRaisesRegex(CardineError, 'foreign integration output'):
            self.finalize()
        self.assertEqual(json.loads(lease.read_bytes()), foreign)
        self.assertTrue(staged.exists())
        lease.write_bytes(original)
        result = self.finalize()
        self.assertEqual(self.finalize(), result)
        self.assertEqual(self.git('rev-list', '--count', '--merges', 'main').stdout.strip(), '1')

    def test_finalize_intent_rejects_changed_task_inputs(self):
        self.ready()
        self.run_candidate()
        self.kill('after_finalize_intent', 'finalize')
        (self.worker / 'feature.txt').write_text('foreign changed work')
        with self.assertRaisesRegex(CardineError, 'finalize task inputs changed'):
            self.finalize()
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.base)
        self.assertTrue(self.paths()[1].exists() and self.paths()[2].exists())

    def test_concurrent_tasks_wait_then_recompute_advanced_main(self):
        from test_per_task_evidence import PerTaskEvidenceIntegrationTest
        fixture = PerTaskEvidenceIntegrationTest()
        fixture.setUp()
        try:
            workers = fixture.prepare_pair()
            first = fixture.stage('056', workers['056'])
            locations = candidate.locations_for('057', fixture.primary)
            ticks = [0]
            def release(seconds):
                ticks[0] += seconds
                fixture.finalize('056', first)
            self.assertTrue(candidate.wait_for_lease(locations, sleep=release, clock=lambda: ticks[0]))
            self.assertEqual(ticks[0], 5)
            second = fixture.stage('057', workers['057'])
            self.assertNotEqual(second['main_commit'], first['main_commit'])
            self.assertEqual(second['decision'], 'BOUNDED')
            self.assertIn('feature-056.txt', second['main_advanced_paths'])
            fixture.finalize('057', second)
            self.assertEqual(fixture.git('rev-list', '--count', '--merges', 'main').stdout.strip(), '2')
        finally:
            fixture.tearDown()
            fixture.doCleanups()

    def test_failed_candidate_returns_repair_on_identical_run(self):
        self.ready('exit 7')
        from cardine.lifecycle.engine import run_integration_step, run_validation_step
        locations = candidate.locations_for('056', self.primary)
        first = run_integration_step(locations)
        self.assertEqual((first['outcome'], first['step']), ('iterate', 'implementation'))
        self.assertEqual(first['work']['role'], 'implementer')
        self.assertFalse(self.paths()[1].exists())
        repeated = run_validation_step(locations)
        self.assertEqual((repeated['outcome'], repeated['step']), ('iterate', 'implementation'))
        state = json.loads(state_path(self.worker, '056').read_bytes())
        self.assertEqual(candidate.failure_count(state), 1)

    def uncommitted_validation(self):
        self.worker = Path(self.prepare()['worktree'])
        (self.worker / 'feature.txt').write_text('implementation')
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'implement', cwd=self.worker)
        from cardine.lifecycle.engine import deliver_run_implementation, resolve_run_locations
        from cardine.lifecycle.validation import run_task_validation
        previous = Path.cwd()
        os.chdir(self.worker)
        try:
            deliver_run_implementation(resolve_run_locations('056', self.worker))
            run_task_validation(self.worker, '056')
        finally:
            os.chdir(previous)
        return candidate.locations_for('056', self.primary)

    def test_engine_commits_measured_closure_then_validates_candidate(self):
        locations = self.uncommitted_validation()
        from cardine.lifecycle.engine import run_validation_step
        first = run_validation_step(locations)
        self.assertEqual(first['action'], 'validate-candidate')
        self.assertEqual(self.git('log', '-1', '--format=%s', cwd=self.worker).stdout.strip(), 'Record 056 measured closure')
        self.assertEqual(first['step'], 'candidate')
        self.assertTrue(self.paths()[2].exists())

    def test_closure_record_commit_boundaries_converge(self):
        for label in ('closure_intent', 'closure_add', 'closure_commit', 'closure_result'):
            for prefix in ('before_', 'after_'):
                with self.subTest(point=prefix + label):
                    fixture = CandidateTest()
                    fixture.setUp()
                    try:
                        locations = fixture.uncommitted_validation()
                        script = """import os,sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.integration.candidate import locations_for
from cardine.integration.records import commit_closure_records
receipts.boundary = lambda name: os._exit(97) if name == sys.argv[2] else None
commit_closure_records(locations_for('056', Path(sys.argv[1])))
"""
                        result = subprocess.run([sys.executable, '-c', script, str(fixture.primary), prefix + label],
                            env=dict(os.environ), cwd=fixture.root, capture_output=True, text=True)
                        self.assertEqual(result.returncode, 97, result.stderr)
                        from cardine.integration.records import commit_closure_records
                        head = commit_closure_records(locations)
                        self.assertEqual(commit_closure_records(locations), head)
                        self.assertEqual(fixture.git('status', '--porcelain', cwd=fixture.worker).stdout, '')
                        self.assertEqual(fixture.git('log', '--format=%s', cwd=fixture.worker).stdout.count('Record 056 measured closure'), 1)
                    finally:
                        fixture.tearDown()
                        fixture.doCleanups()

    def test_closure_commit_preserves_uncovered_and_foreign_changes(self):
        locations = self.uncommitted_validation()
        from cardine.integration.records import commit_closure_records
        handoff = self.worker / 'tasks/handoffs/056.md'
        original = handoff.read_bytes()
        handoff.write_bytes(original + b'foreign edit')
        with self.assertRaisesRegex(CardineError, 'uncovered closure output'):
            commit_closure_records(locations)
        self.assertTrue(handoff.read_bytes().endswith(b'foreign edit'))
        handoff.write_bytes(original)
        (self.worker / 'foreign.txt').write_text('foreign')
        with self.assertRaisesRegex(CardineError, 'foreign changes'):
            commit_closure_records(locations)
        self.assertEqual((self.worker / 'foreign.txt').read_text(), 'foreign')
        (self.worker / 'foreign.txt').unlink()
        def interrupt(name):
            if name == 'after_closure_intent':
                raise InterruptedError('test interruption')
        with mock.patch.object(receipts, 'boundary', interrupt), self.assertRaises(InterruptedError):
            commit_closure_records(locations)
        path = candidate.operation_path(locations, 'closure')
        original_intent = path.read_bytes()
        intent = receipts._load_intent(path)
        receipts._save_intent(path, dict(intent, task_id='999'))
        foreign = path.read_bytes()
        with self.assertRaisesRegex(CardineError, 'inputs or owner changed'):
            commit_closure_records(locations)
        self.assertEqual(path.read_bytes(), foreign)
        path.write_bytes(original_intent)
        handoff.write_bytes(original + b'changed after intent')
        with self.assertRaisesRegex(CardineError, 'closure output changed'):
            commit_closure_records(locations)

    def test_candidate_result_boundaries_replay_once(self):
        for label in ('candidate_intent', 'candidate_logs', 'candidate_result', 'intent',
                      'staged_pair', 'state_replace', 'result_receipt'):
            for prefix in ('before_', 'after_'):
                point = prefix + label
                with self.subTest(point=point):
                    fixture = CandidateTest()
                    fixture.setUp()
                    try:
                        fixture.ready('exit 7')
                        fixture.kill(point, 'candidate')
                        first = fixture.run_candidate()
                        self.assertEqual(fixture.run_candidate(), first)
                        self.assertEqual(first['consecutiveFailures'], 1)
                        merge.abort_task_integration('056', fixture.primary)
                    finally:
                        fixture.tearDown()
                        fixture.doCleanups()

    def test_finalize_every_effect_boundary_returns_the_same_commit(self):
        for label in ('finalize_intent', 'finalize_commit', 'finalize_result',
                      'finalize_json_unlink', 'finalize_lease_unlink'):
            for prefix in ('before_', 'after_'):
                point = prefix + label
                with self.subTest(point=point):
                    fixture = CandidateTest()
                    fixture.setUp()
                    try:
                        fixture.ready()
                        fixture.run_candidate()
                        fixture.kill(point, 'finalize')
                        first = fixture.finalize()
                        self.assertEqual(fixture.finalize(), first)
                        self.assertEqual(fixture.git('rev-list', '--count', '--merges', 'main').stdout.strip(), '1')
                        self.assertFalse(fixture.paths()[1].exists() or fixture.paths()[2].exists())
                    finally:
                        fixture.tearDown()
                        fixture.doCleanups()

    def test_interrupted_result_rejects_changed_inputs_and_foreign_owner(self):
        self.ready()
        self.kill('before_candidate_result', 'candidate')
        _, lease, _ = self.paths()
        saved = lease.read_bytes()
        lease.write_text(json.dumps(dict(task_id='999')))
        with self.assertRaises(CardineError):
            self.run_candidate()
        lease.write_bytes(saved)
        (self.worker / 'feature.txt').write_text('changed')
        with self.assertRaisesRegex(CardineError, 'inputs changed'):
            self.run_candidate()


if __name__ == '__main__':
    unittest.main()
