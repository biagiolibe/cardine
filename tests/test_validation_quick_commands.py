"""Retry variants cannot pass an attempt; quick commands run first and limit their failures apart."""
from copy import deepcopy
from pathlib import Path
import shlex
import json
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
from cardine.shared.errors import CardineStop
from cardine.tasks.state import state_path
import test_run_delivery
import worktree_support as support
from project_config_support import write_project_config
from task_contract_support import freeze_record


def kill_after_variant(root, kind, count=2):
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
        if count == int(sys.argv[3]):
            os._exit(77)
receipts.boundary = boundary
if sys.argv[2] == 'task':
    run_task_validation(Path(sys.argv[1]), '001')
else:
    run_candidate_validation('056', Path(sys.argv[1]))
"""
    source = str(Path(__file__).resolve().parents[1] / 'src')
    result = subprocess.run([sys.executable, '-c', script, str(root), kind, str(count)], cwd=root,
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
        handoff = (self.worker / 'tasks/handoffs/001.md').read_text()
        self.assertIn('Round 2:', handoff)
        self.assertIn('`exit 1`', handoff)
        self.assertIn(result['runs'][1][0]['log'], handoff)

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
        result = self.attempt('exit 1', 'printf retry-output; printf retry-error >&2; exit 1')
        self.assertEqual([r[-1]['exitStatus'] for r in result['runs']], [1, 1])
        self.assertEqual(result['phase'], 'failed')
        state = json.loads(state_path(self.worker, '056').read_text())
        self.assertEqual(state['run']['candidateValidation']['runs'], result['runs'])
        variant = state['run']['candidateValidation']['runs'][1][0]
        self.assertEqual(variant['command'], 'printf retry-output; printf retry-error >&2; exit 1')
        self.assertEqual((variant['exitStatus'], variant['stdout'], variant['stderr']),
                         (1, 'retry-output', 'retry-error'))

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


class QuickTaskTest(unittest.TestCase):
    """Order, counters and replay of quick rounds, with literal marker-file commands."""

    def setUp(self):
        environment = mock.patch.dict(os.environ, {'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
        environment.start()
        self.addCleanup(environment.stop)
        self.fixture = test_run_delivery.RunDeliveryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.worker = self.fixture.worker
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.log = self.dir / 'log'

    def logged(self, name, status):
        return f'echo {name} >> {shlex.quote(str(self.log))}; ' + status

    def configure(self, full, *, retry=None, pre=None, limit=3, quick_limit=10):
        original = self.fixture.state()
        state = deepcopy(original)
        policy = state['contract']['validation']
        policy['commands']['check'] = full
        policy['baseline'] = ['check']
        policy.pop('retry', None)
        policy.pop('preflight', None)
        if retry is not None:
            policy['retry'] = {'check': retry}
        if pre is not None:
            policy['commands']['pre'] = pre
            policy['preflight'] = ['pre']
        state['contract']['options'].update(validationRetryLimit=limit, quickFailureLimit=quick_limit)
        state['contract']['deliverables'] = ['src/result.py']
        state['contract']['validationScoping'] = []
        state['contract']['hostImpact']['profiles'] = {}
        with receipts.task_lock(self.worker, '001'):
            receipts.write_operation(self.worker, '001', state, previous=original, kind='fixture-validation')
        self.fixture.git('add', '.')
        self.fixture.git('commit', '-m', 'Freeze quick policy')
        self.fixture.deliver()

    def repair(self):
        path = self.worker / 'src/result.py'
        path.write_text(path.read_text() + '# repair\n')
        self.fixture.git('add', '.')
        self.fixture.git('commit', '-m', 'Repair source')
        self.fixture.deliver()

    def attempt(self):
        self.log.write_text('')
        result = run_task_validation(self.worker, '001')
        return result, self.log.read_text().split()

    def shape(self, result):
        return [[item['exitStatus'] for item in run] for run in result['runs']]

    def test_order_is_variant_then_preflight_then_complete_set(self):
        flag = shlex.quote(str(self.dir / 'flag'))
        self.configure(self.logged('full', f'test -f {flag}'), retry=self.logged('variant', 'exit 0'),
                       pre=self.logged('pre', 'exit 0'))
        first, order = self.attempt()
        self.assertEqual(order, ['pre', 'full', 'variant', 'full'])  # No quick variant on the first attempt.
        self.assertEqual((first['consecutiveFailures'], first['quickRounds'], first['lastFailed']), (1, 1, ['check']))
        (self.dir / 'flag').write_text('')
        self.repair()
        second, order = self.attempt()
        self.assertEqual(order, ['variant', 'pre', 'full'])
        self.assertEqual((second['phase'], second['quickRounds'], self.shape(second)), ('passed', 2, [[0], [0], [0]]))
        self.assertEqual((second['consecutiveFailures'], second['quickFailures'], second['lastFailed']), (0, 0, []))
        handoff = (self.worker / 'tasks/handoffs/001.md').read_text()
        self.assertIn('Quick rounds: 2; quick failures: 0', handoff)
        self.assertIn('Round 3:', handoff)

    def test_failing_variant_runs_no_complete_set_and_spares_the_retry_limit(self):
        self.configure(self.logged('full', 'exit 1'), retry=self.logged('variant', 'exit 1'))
        first, _ = self.attempt()
        self.assertEqual((first['consecutiveFailures'], first['quickFailures']), (1, 0))
        self.repair()
        second, order = self.attempt()
        self.assertEqual(order, ['variant'])
        self.assertEqual((second['phase'], self.shape(second)), ('failed', [[1]]))
        self.assertEqual((second['consecutiveFailures'], second['quickFailures'], second['lastFailed']), (1, 1, ['check']))
        self.repair()
        third, order = self.attempt()
        self.assertEqual((order, third['consecutiveFailures'], third['quickFailures']), (['variant'], 1, 2))

    def test_variant_with_other_status_continues_to_the_complete_set(self):
        self.configure(self.logged('full', 'exit 1'), retry=self.logged('variant', 'exit 2'), pre=self.logged('pre', 'exit 0'))
        self.attempt()
        self.repair()
        second, order = self.attempt()
        self.assertEqual(order, ['variant', 'pre', 'full', 'variant', 'full'])
        self.assertEqual((second['quickFailures'], second['consecutiveFailures']), (0, 2))

    def test_preflight_failure_counts_apart_and_only_a_passing_complete_set_resets_it(self):
        flag = shlex.quote(str(self.dir / 'pre-ok'))
        self.configure(self.logged('full', 'exit 0'), pre=self.logged('pre', f'test -f {flag} || exit 3'))
        first, order = self.attempt()
        self.assertEqual((order, first['phase'], self.shape(first)), (['pre'], 'failed', [[3]]))
        self.assertEqual((first['consecutiveFailures'], first['quickFailures']), (0, 1))
        self.repair()
        second, order = self.attempt()
        self.assertEqual((order, second['quickFailures'], second['consecutiveFailures']), (['pre'], 2, 0))
        (self.dir / 'pre-ok').write_text('')
        self.repair()
        third, order = self.attempt()
        self.assertEqual(order, ['pre', 'full'])
        self.assertEqual((third['phase'], third['quickFailures']), ('passed', 0))
        self.assertEqual(self.fixture.state()['run']['validation']['quickFailures'], 0)

    def test_quick_limit_stops_with_its_own_detail(self):
        self.configure(self.logged('full', 'exit 0'), pre=self.logged('pre', 'exit 3'), quick_limit=2, limit=9)
        self.attempt()
        self.repair()
        with self.assertRaises(CardineStop) as caught:
            self.attempt()
        self.assertEqual(caught.exception.code, 'VALIDATION_RETRY_LIMIT')
        self.assertIn('Quick failure limit 2 reached; failed quick commands: pre', caught.exception.detail)
        self.assertEqual(self.fixture.state()['run']['validation']['consecutiveFailures'], 0)
        self.repair()
        with self.assertRaises(CardineStop) as caught:
            self.attempt()
        self.assertIn('Quick failure limit 2', caught.exception.detail)
        self.assertEqual(self.log.read_text().split(), [])  # Nothing ran once the limit was reached.

    def test_project_without_quick_commands_behaves_as_before(self):
        self.configure(self.logged('full', 'exit 0'))
        result, order = self.attempt()
        self.assertEqual((order, result['quickRounds'], result['quickFailures'], self.shape(result)), (['full'], 0, 0, [[0]]))

    def test_interrupted_quick_round_converges_without_double_counting(self):
        self.configure(self.logged('full', 'exit 1'), retry=self.logged('variant', 'exit 1'),
                       pre=self.logged('pre', 'exit 0'))
        self.attempt()
        self.repair()
        self.log.write_text('')
        kill_after_variant(self.worker, 'task', count=1)
        resumed, order = self.attempt()
        self.assertEqual(order, [])  # The recorded variant round is not run again.
        self.assertEqual((self.shape(resumed), resumed['quickFailures'], resumed['consecutiveFailures']), ([[1]], 1, 1))
        self.assertEqual(self.fixture.state()['run']['validation']['quickFailures'], 1)

    def test_interrupted_preflight_round_converges(self):
        self.configure(self.logged('full', 'exit 0'), pre=self.logged('pre', 'exit 3'))
        kill_after_variant(self.worker, 'task', count=1)
        resumed, order = self.attempt()
        self.assertEqual((order, self.shape(resumed), resumed['quickFailures']), ([], [[3]], 1))


class QuickCandidateTest(support.BoundedWorktreeLifecycleFixture):
    """Candidate validation orders and counts quick rounds like task validation."""

    def setUp(self):
        super().setUp()
        environment = mock.patch.dict(os.environ, {'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
        environment.start()
        self.addCleanup(environment.stop)
        self.log, self.broken = self.root / 'log', self.root / 'broken'
        self.pre = f'echo pre >> {shlex.quote(str(self.log))}; test ! -f {shlex.quote(str(self.broken))}'

    def logged(self, name, status):
        return f'echo {name} >> {shlex.quote(str(self.log))}; ' + status

    def stage(self, full, retry=None, quick_limit=10):
        """The preflight also guards task validation, so it passes until `broken` exists."""
        policy = dict(commands={'check': full, 'pre': self.pre}, baseline=[], preflight=['pre'],
                      candidate={key: ['check'] for key in ('REUSE', 'BOUNDED', 'FULL')})
        if retry is not None:
            policy['retry'] = {'check': retry}
        write_project_config(self.primary, validation=policy, taskDefaults={'quickFailureLimit': quick_limit})
        freeze_record(self.primary, '056', self.primary / 'tasks/056-lifecycle.md')
        self.git('add', '.')
        self.git('commit', '-m', 'Freeze candidate quick policy')
        self.worker = Path(self.prepare()['worktree'])
        self.restage('implemented\n')

    def restage(self, content):
        self.broken.unlink(missing_ok=True)
        (self.worker / 'feature.txt').write_text(content)
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'Implement ' + content.strip(), cwd=self.worker)
        self.measure(self.worker)
        merge.stage_task_integration('056', self.worktree_root, None, self.primary)

    def run_logged(self, *, broken):
        if broken:
            self.broken.write_text('')
        self.log.write_text('')
        return run_candidate_validation('056', self.primary), self.log.read_text().split()

    def test_order_and_quick_failure_counters(self):
        full, variant = self.logged('full', 'exit 1'), self.logged('variant', 'exit 1')
        self.stage(full, retry=variant)
        first, order = self.run_logged(broken=True)
        self.assertEqual(order, ['pre'])  # A preflight failure runs no complete set.
        self.assertEqual((first['phase'], first['consecutiveFailures'], first['quickFailures']), ('failed', 0, 1))
        merge.abort_task_integration('056', self.primary)
        self.restage('second\n')  # A passing task validation resets the shared counter.
        second, order = self.run_logged(broken=False)
        self.assertEqual(order, ['pre', 'full', 'variant'])  # The first attempt runs no quick variant.
        self.assertEqual((second['consecutiveFailures'], second['quickFailures'], second['lastFailed']), (1, 0, [full]))
        merge.abort_task_integration('056', self.primary)
        self.restage('third\n')
        third, order = self.run_logged(broken=False)
        self.assertEqual(order, ['variant'])  # The failed command's variant runs first on the next attempt.
        self.assertEqual((third['phase'], third['consecutiveFailures'], third['quickFailures'], third['quickRounds']),
                         ('failed', 0, 1, 1))
        state = json.loads(state_path(self.worker, '056').read_text())
        self.assertEqual(state['run']['validation']['quickFailures'], 1)

    def test_variant_then_preflight_then_complete_set(self):
        flag = shlex.quote(str(self.root / 'flag'))
        self.stage(self.logged('full', f'test -f {flag}'), retry=self.logged('variant', 'exit 0'))
        self.run_logged(broken=False)
        merge.abort_task_integration('056', self.primary)
        self.restage('second\n')
        (self.root / 'flag').write_text('')
        second, order = self.run_logged(broken=False)
        self.assertEqual(order, ['variant', 'pre', 'full'])
        self.assertEqual((second['phase'], second['quickFailures'], second['quickRounds']), ('passed', 0, 2))

    def test_quick_limit_stops_candidate_validation(self):
        self.stage('exit 0', quick_limit=1)
        with self.assertRaises(CardineStop) as caught:
            self.run_logged(broken=True)
        self.assertEqual(caught.exception.code, 'VALIDATION_RETRY_LIMIT')
        self.assertIn('Quick failure limit 1 reached; failed quick commands: ' + self.pre, caught.exception.detail)
        state = json.loads(state_path(self.worker, '056').read_text())
        self.assertEqual(state['run']['candidateValidation']['consecutiveFailures'], 0)

    def test_interrupted_quick_round_converges(self):
        self.stage('exit 0')
        self.broken.write_text('')
        kill_after_variant(self.primary, 'candidate', count=1)
        result, order = self.run_logged(broken=True)
        self.assertEqual((order, [[r['exitStatus'] for r in run] for run in result['runs']], result['quickFailures']),
                         ([], [[1]], 1))


class QuickDeclarationTest(unittest.TestCase):
    def declaration(self, **changes):
        validation = dict(commands={'a': 'true', 'b': 'true'}, baseline=['a'], preflight=['b'],
                          candidate={key: [] for key in ('REUSE', 'BOUNDED', 'FULL')})
        return {'version': 1, 'preset': 'lean', 'validation': {**validation, **changes.pop('validation', {})}, **changes}

    def test_declaration_accepts_and_defaults_both_settings(self):
        from cardine.shared.project import parse_project_declaration, preset_task_defaults
        parse_project_declaration(self.declaration(taskDefaults={'quickFailureLimit': 4}))
        self.assertEqual([preset_task_defaults(name)['quickFailureLimit'] for name in ('lean', 'governed')], [10, 10])
        parse_project_declaration(self.declaration(validation={'preflight': []}))

    def test_declaration_rejects_invalid_values(self):
        from cardine.shared.errors import CardineError
        from cardine.shared.project import parse_project_declaration
        for changes in (dict(validation={'preflight': ['missing']}), dict(validation={'preflight': ['b', 'b']}),
                        dict(taskDefaults={'quickFailureLimit': 0}), dict(taskDefaults={'quickFailureLimit': True})):
            with self.subTest(changes=changes), self.assertRaises(CardineError):
                parse_project_declaration(self.declaration(**changes))

    def test_task_option_overrides_the_project_default(self):
        from cardine.tasks.contract import task_contract_options
        self.assertEqual(task_contract_options('Options: {"quickFailureLimit": 2}\n'), {'quickFailureLimit': 2})
