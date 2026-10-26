"""Exact-repository CI before direct landing, with a real bare origin and a fake gh (RE6a)."""
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
from cardine.integration import candidate, ci
from cardine.lifecycle import engine, receipts
from cardine.shared.errors import CardineError, CardineStop
from cardine.tasks.state import state_path
from project_config_support import write_project_config
from task_contract_support import VALIDATION, freeze_record
import worktree_support as support

REPOSITORY = 'https://github.com/acme/widgets.git'
FAKE_GH = '''#!{python}
import json, os, sys
with open(os.environ['FAKE_GH_LOG'], 'a') as handle:
    handle.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ.get('FAKE_GH_FORBID'):
    sys.exit(99)
state = json.load(open(os.environ['FAKE_GH_STATE']))
if state.get('fail'):
    sys.stderr.write(state['fail'])
    sys.exit(1)
sha = sys.argv[-1].split('/commits/')[1].split('/')[0]
runs = state['runs'].get(sha, [])
print(json.dumps({{'total_count': len(runs), 'check_runs': runs}}))
'''


class CiTest(support.BoundedWorktreeLifecycleFixture):
    def setUp(self):
        super().setUp()
        self.origin = self.root / 'origin.git'
        subprocess.run(['git', 'init', '--bare', '-b', 'main', str(self.origin)], check=True, capture_output=True)
        self.pushes = self.root / 'pushes.log'
        hook = self.origin / 'hooks/post-receive'
        hook.write_text(f'#!/bin/sh\ncat >> {self.pushes}\n')
        hook.chmod(0o755)
        self.git('remote', 'add', 'origin', REPOSITORY)
        self.git('config', f'url.{self.origin}.insteadOf', REPOSITORY)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        gh = self.bin / 'gh'
        gh.write_text(FAKE_GH.format(python=sys.executable))
        gh.chmod(0o755)
        self.gh_log, self.gh_state = self.root / 'gh.log', self.root / 'gh-state.json'
        self.gh_state.write_text(json.dumps(dict(runs={})))
        home = self.root / 'home'
        home.mkdir()
        environment = mock.patch.dict(os.environ, {
            'PYTHONPATH': str(ROOT / 'src'), 'PATH': f'{self.bin}{os.pathsep}{os.environ["PATH"]}',
            'HOME': str(home), 'GH_CONFIG_DIR': str(home / 'gh'), 'FAKE_GH_LOG': str(self.gh_log),
            'FAKE_GH_STATE': str(self.gh_state), 'GIT_CONFIG_GLOBAL': os.devnull})
        environment.start()
        self.addCleanup(environment.stop)

    def ready(self, *, enabled=True):
        if enabled:
            write_project_config(self.primary, validation=VALIDATION, taskDefaults=dict(ciBeforeLanding=True),
                                 ci=dict(provider='github', requiredChecks=['validate', 'lint']))
            freeze_record(self.primary, '056', self.primary / 'tasks/056-lifecycle.md')
            self.git('add', '.')
            self.git('commit', '-m', 'require CI')
        self.worker = Path(self.prepare()['worktree'])
        self.implement('first')
        return candidate.locations_for('056', self.primary)

    def implement(self, text):
        (self.worker / 'feature.txt').write_text(text)
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'implement ' + text, cwd=self.worker)
        self.measure(self.worker)
        return self.head()

    def head(self):
        return json.loads(state_path(self.worker, '056').read_bytes())['run']['delivery']['source']

    def checks(self, sha, *, status='completed', conclusion='success', names=('validate', 'lint'), head=None):
        state = json.loads(self.gh_state.read_text())
        state['runs'][sha] = [dict(name=name, id=index + 1, status=status, conclusion=conclusion,
                                   head_sha=head or sha) for index, name in enumerate(names)]
        self.gh_state.write_text(json.dumps(state))

    def push_count(self):
        return len(self.pushes.read_text().splitlines()) if self.pushes.exists() else 0

    def gh_calls(self):
        return len(self.gh_log.read_text().splitlines()) if self.gh_log.exists() else 0

    def remote_tip(self):
        out = subprocess.run(['git', '--git-dir', str(self.origin), 'rev-parse', '--verify', '-q', 'refs/heads/task-056'],
                             capture_output=True, text=True).stdout.strip()
        return out or None

    def state(self):
        return json.loads(state_path(self.worker, '056').read_bytes())

    def kinds(self):
        return [r['kind'] for r in self.state()['run']['receipts']]

    def gate(self, locations):
        return ci.ci_gate(locations)

    def no_writes(self):
        return mock.patch.object(receipts, '_durable', side_effect=AssertionError('repeated resolution wrote'))

    def test_disabled_ci_runs_no_gh_and_no_git(self):
        locations = self.ready(enabled=False)
        with mock.patch.dict(os.environ, {'FAKE_GH_FORBID': '1'}), \
                mock.patch.object(ci, '_run_git', side_effect=AssertionError('git ran')), \
                mock.patch.object(ci.shutil, 'which', side_effect=AssertionError('gh looked up')):
            self.assertIsNone(self.gate(locations))
        with mock.patch('cardine.shared.git.subprocess.run', side_effect=AssertionError('process ran')):
            self.assertIsNone(engine.run_ci_step(locations, None, None, self.state()))
        self.assertEqual((self.gh_calls(), self.push_count()), (0, 0))

    def test_missing_gh_stops_before_any_push(self):
        locations = self.ready()
        with mock.patch.object(ci.shutil, 'which', return_value=None), \
                self.assertRaisesRegex(CardineError, 'requires the gh command'):
            self.gate(locations)
        self.assertEqual((self.push_count(), self.remote_tip()), (0, None))

    def test_one_push_per_delivered_head_and_pass_is_reused_only_for_that_head(self):
        locations = self.ready()
        first = self.head()
        waiting = self.gate(locations)
        self.assertEqual((waiting['phase'], waiting['head']), ('waiting', first))
        self.assertEqual((self.push_count(), self.remote_tip()), (1, first))
        self.assertEqual(self.kinds().count('ci-push'), 1)
        before = self.state()
        with self.no_writes():
            self.assertEqual(self.gate(locations)['phase'], 'waiting')
        self.assertEqual((self.push_count(), self.state()), (1, before))
        self.checks(first)
        passed = self.gate(locations)
        self.assertEqual((passed['phase'], passed['changed']), ('passed', True))
        calls = self.gh_calls()
        with self.no_writes():
            again = self.gate(locations)
        self.assertEqual((again['phase'], again['changed']), ('passed', False))
        self.assertEqual((self.gh_calls(), self.push_count(), self.kinds().count('ci-result')), (calls, 1, 1))
        second = self.implement('second')
        self.assertNotEqual(second, first)
        self.assertEqual(self.gate(locations)['phase'], 'waiting')
        self.assertEqual((self.push_count(), self.remote_tip()), (2, second))

    def test_pending_failed_and_wrong_sha_checks_never_pass(self):
        locations = self.ready()
        head = self.head()
        self.gate(locations)
        self.checks(head, status='in_progress', conclusion=None)
        with self.no_writes():
            self.assertEqual(self.gate(locations)['phase'], 'waiting')
        self.checks(head, head='f' * 40)  # Reported for another SHA.
        with self.no_writes():
            self.assertEqual(self.gate(locations)['phase'], 'waiting')
        self.checks(head, names=('validate',))  # A required check is absent.
        with self.no_writes():
            self.assertEqual(self.gate(locations)['phase'], 'waiting')
        state = json.loads(self.gh_state.read_text())
        state['runs']['e' * 40] = [dict(name=n, id=i, status='completed', conclusion='success', head_sha='e' * 40)
                                   for i, n in enumerate(('validate', 'lint'))]
        self.gh_state.write_text(json.dumps(state))
        self.checks(head, conclusion='failure', names=('validate', 'lint'))
        with self.no_writes():
            failed = self.gate(locations)
        self.assertEqual(failed['phase'], 'failed')
        self.assertIn('validate concluded failure', failed['detail'])
        self.assertNotIn('ci-result', self.kinds())

    def test_provider_refusal_is_a_guardrail_and_outage_only_waits(self):
        locations = self.ready()
        self.gate(locations)
        self.gh_state.write_text(json.dumps(dict(runs={}, fail='HTTP 403: Resource not accessible')))
        with self.assertRaisesRegex(CardineError, 'refused the query'):
            self.gate(locations)
        self.gh_state.write_text(json.dumps(dict(runs={}, fail='HTTP 502: bad gateway')))
        self.assertEqual(self.gate(locations)['phase'], 'waiting')

    def test_fabricated_records_and_tracking_refs_have_no_authority(self):
        locations = self.ready()
        head = self.head()
        forged = dict(version=1, task_id='056', status='passed', level='T1_CI', commit=head, exit_code=0,
                      ci=dict(conclusion='success', head_sha=head), attested_by='developer', statement='ok',
                      shards=[], passed=True)
        for name in ('ci.json', 'validation.json', 'attestation.json'):
            (self.worker / name).write_text(json.dumps(forged))
        self.git('update-ref', 'refs/remotes/origin/task-056', head)  # A local tracking ref says it is published.
        self.assertEqual(self.gate(locations)['phase'], 'waiting')
        self.assertEqual((self.push_count(), self.remote_tip()), (1, head))
        command = [sys.executable, '-m', 'cardine.cli', 'validation', 'check', 'ci.json', '--format', 'json']
        self.assertNotEqual(subprocess.run(command, cwd=self.worker, capture_output=True, text=True).returncode, 0)

    def test_forged_cached_result_without_a_receipt_is_rejected(self):
        locations = self.ready()
        head = self.head()
        self.gate(locations)
        path = state_path(self.worker, '056')
        state = json.loads(path.read_bytes())
        state['run']['ci']['phase'] = 'passed'
        state['run']['ci']['checks'] = [dict(name=n, id=i, status='completed', conclusion='success', head_sha=head)
                                       for i, n in enumerate(('validate', 'lint'))]
        path.write_bytes(receipts.encoded(state))
        with self.assertRaises(CardineError):
            self.gate(locations)
        self.assertNotIn('ci-result', self.kinds())

    def test_foreign_remote_work_and_refused_push_are_guardrails(self):
        locations = self.ready()
        foreign = self.root / 'foreign'
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(foreign)], check=True, capture_output=True)
        for key, value in (('user.name', 'Other'), ('user.email', 'other@example.invalid')):
            subprocess.run(['git', '-C', str(foreign), 'config', key, value], check=True)
        (foreign / 'other.txt').write_text('other')
        subprocess.run(['git', '-C', str(foreign), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(foreign), 'commit', '-qm', 'other'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(foreign), 'push', '-q', 'origin', 'HEAD:refs/heads/task-056'], check=True,
                       capture_output=True)
        tip = self.remote_tip()
        pushes = self.push_count()
        with self.assertRaises(CardineStop) as raised:
            self.gate(locations)
        self.assertEqual(raised.exception.code, 'PUSH_REJECTED')
        self.assertEqual((self.remote_tip(), self.push_count(), self.gh_calls()), (tip, pushes, 0))
        subprocess.run(['git', '--git-dir', str(self.origin), 'update-ref', '-d', 'refs/heads/task-056'], check=True)
        hook = self.origin / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\necho protected >&2\nexit 1\n')
        hook.chmod(0o755)
        with self.assertRaises(CardineStop) as raised:
            self.gate(locations)
        self.assertEqual(raised.exception.code, 'PUSH_REJECTED')
        self.assertNotIn('ci-push', self.kinds())

    def test_foreign_or_changed_intent_and_pending_owner_fail_closed(self):
        locations = self.ready()
        head = self.head()
        path = candidate.operation_path(locations, 'ci')
        state, _ = engine_state(self.worker)
        policy = ci.ci_policy(state['contract'])
        binding = ci.ci_binding(locations, state, policy)
        for change in (dict(repository='github.com/evil/other'), dict(contract='0' * 64), dict(task_id='999')):
            receipts._save_intent(path, dict(binding=dict(binding, **change), expected=None, done=False))
            with self.assertRaisesRegex(CardineError, 'foreign CI operation'):
                self.gate(locations)
            self.assertEqual((self.push_count(), self.remote_tip(), self.gh_calls()), (0, None, 0))
        # A changed head with the same identity is simply a new delivered head.
        receipts._save_intent(path, dict(binding=dict(binding, head='a' * 40), expected=None, done=False))
        self.assertEqual(self.gate(locations)['phase'], 'waiting')
        self.assertEqual(self.remote_tip(), head)

    def test_pending_push_receipt_with_a_rewritten_or_missing_intent_is_refused(self):
        locations = self.ready()
        head = self.head()
        self.checks(head)
        self.kill('after_intent', 1)
        self.assertTrue(receipts.pending_operation(self.worker, '056'))
        path = candidate.operation_path(locations, 'ci')
        original = path.read_bytes()
        intent = receipts._intent_path(self.worker, '056')
        for name in ('rewritten', 'missing'):
            with self.subTest(name):
                if name == 'rewritten':
                    receipts._save_intent(path, dict(receipts._load_intent(path), expected=None))
                else:
                    path.unlink()
                before = (state_path(self.worker, '056').read_bytes(), intent.read_bytes(), self.push_count(), self.gh_calls())
                with self.assertRaisesRegex(CardineError, 'foreign pending operation before CI'):
                    self.gate(locations)
                self.assertEqual(before, (state_path(self.worker, '056').read_bytes(), intent.read_bytes(),
                                          self.push_count(), self.gh_calls()))
                path.write_bytes(original)
        self.assertEqual(self.gate(locations)['phase'], 'passed')
        self.assertEqual((self.push_count(), self.kinds().count('ci-push'), self.kinds().count('ci-result')), (1, 1, 1))

    def test_result_write_refuses_inputs_changed_after_the_query(self):
        locations = self.ready()
        head = self.head()
        self.gate(locations)
        self.checks(head)
        real = ci.query_checks

        def changed(binding):
            outcome = real(binding)
            from copy import deepcopy
            state, _ = engine_state(self.worker)
            updated = deepcopy(state)
            updated['run']['validation']['consecutiveFailures'] = 1
            with receipts.task_lock(self.worker, '056'):
                receipts.write_operation(self.worker, '056', updated, previous=state, kind='fixture-change')
            return outcome

        with mock.patch.object(ci, 'query_checks', side_effect=changed), \
                self.assertRaisesRegex(CardineError, 'CI inputs changed before the result write'):
            self.gate(locations)
        self.assertNotIn('ci-result', self.kinds())
        self.assertEqual(self.gate(locations)['phase'], 'passed')

    def test_lost_push_response_is_reconciled_from_the_remote_without_a_second_push(self):
        locations = self.ready()
        real = ci._run_git

        def lost(root, *args, **kwargs):
            result = real(root, *args, **kwargs)
            if args[0] == 'push':
                return subprocess.CompletedProcess(args, 1, '', 'connection reset by peer')
            return result

        with mock.patch.object(ci, '_run_git', side_effect=lost):
            self.assertEqual(self.gate(locations)['phase'], 'waiting')
            self.assertEqual(self.gate(locations)['phase'], 'waiting')
        self.assertEqual((self.push_count(), self.remote_tip(), self.kinds().count('ci-push')), (1, self.head(), 1))

    def test_timed_out_push_that_never_arrived_is_retried_exactly_once(self):
        locations = self.ready()
        real = ci._run_git

        def stalled(root, *args, **kwargs):
            if args[0] == 'push':
                raise subprocess.TimeoutExpired(args, 1)
            return real(root, *args, **kwargs)

        with mock.patch.object(ci, '_run_git', side_effect=stalled), self.assertRaises(CardineStop) as raised:
            self.gate(locations)
        self.assertEqual(raised.exception.code, 'GIT_OPERATION_FAILED')
        self.assertTrue(raised.exception.resume().startswith('cardine run 056'))
        self.assertEqual((self.push_count(), self.remote_tip()), (0, None))
        self.assertNotIn('ci-push', self.kinds())
        self.assertEqual(self.gate(locations)['phase'], 'waiting')
        self.assertEqual((self.push_count(), self.remote_tip()), (1, self.head()))

    def test_staging_is_refused_without_a_receipt_covered_pass_for_the_delivered_head(self):
        from cardine.integration import merge
        locations = self.ready()
        head = self.head()
        with self.assertRaises(CardineStop) as raised:
            merge.stage_task_integration('056', self.worktree_root, None, self.primary)
        self.assertEqual(raised.exception.code, 'EVIDENCE_INCOMPLETE')
        self.assertEqual((self.push_count(), self.gh_calls()), (0, 0))
        self.checks(head)
        self.assertEqual(self.gate(locations)['phase'], 'passed')
        from cardine.integration.direct import DirectLanding
        self.assertIn('candidate_tree', DirectLanding().prepare_candidate('056', None, self.primary))

    def test_run_command_emits_a_valid_waiting_envelope_from_an_unrelated_directory(self):
        self.ready()
        command = [sys.executable, '-m', 'cardine.cli', 'run', '056', '--project', str(self.primary)]
        result = subprocess.run(command, cwd=self.root, env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        value = json.loads(result.stdout)
        engine.validate_output(value)
        self.assertEqual((value['outcome'], value['step'], value['action']), ('waiting', 'candidate', 'poll-ci'))
        self.assertEqual(self.push_count(), 1)

    def kill(self, name, occurrence):
        script = '''
import sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.integration import candidate, ci
count = {}
def boundary(name):
    count[name] = count.get(name, 0) + 1
    if name == sys.argv[2] and count[name] == int(sys.argv[3]):
        import os
        os._exit(97)
receipts.boundary = boundary
ci.ci_gate(candidate.locations_for('056', Path(sys.argv[1])))
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.primary), name, str(occurrence)],
                                cwd=self.primary, env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual(result.returncode, 97, (name, occurrence, result.stderr))

    def converges_after_kill(self, name, occurrence):
        locations = self.ready()
        head = self.head()
        self.checks(head)
        self.kill(name, occurrence)
        result = None
        for _ in range(3):
            result = self.gate(locations)
            if result['phase'] == 'passed' and self.state()['run']['ci']['phase'] == 'passed':
                break
        self.assertEqual(result['phase'], 'passed')
        self.assertEqual((self.push_count(), self.remote_tip()), (1, head))
        self.assertEqual((self.kinds().count('ci-push'), self.kinds().count('ci-result')), (1, 1))
        self.assertFalse(receipts.pending_operation(self.worker, '056'))
        with self.no_writes():
            self.assertFalse(self.gate(locations)['changed'])

    def test_engine_waits_then_passes_then_stages_the_candidate(self):
        locations = self.ready()
        head = self.head()
        first = engine.run_validation_step(locations)
        engine.validate_output(first)
        self.assertEqual((first['outcome'], first['step'], first['action']), ('waiting', 'candidate', 'poll-ci'))
        self.assertGreater(first['retry_after_seconds'], 0)
        self.assertEqual(first['evidence'][0]['identity'], head)
        self.assertEqual(first['next']['argv'][:2], ['cardine', 'run'])
        self.checks(head, conclusion='failure')
        failed = engine.run_validation_step(locations)
        engine.validate_output(failed)
        self.assertEqual((failed['outcome'], failed['step'], failed['action']), ('iterate', 'implementation', 'ci-failed'))
        self.assertEqual(failed['diagnostics'][0]['code'], 'VALIDATION_FAILED')
        self.checks(head)
        passed = engine.run_validation_step(locations)
        engine.validate_output(passed)
        self.assertEqual((passed['outcome'], passed['action']), ('next', 'ci-passed'))
        staged = engine.run_validation_step(locations)
        self.assertEqual(staged['action'], 'validate-candidate')
        self.assertEqual(self.push_count(), 1)


# Each listed boundary is killed once; occurrence 2 of a receipt boundary is the result write.
POINTS = [(name, 1) for name in ('before_ci_push', 'after_ci_push', 'before_ci_query', 'after_ci_query')]
POINTS += [(name, occurrence) for occurrence in (1, 2) for name in (
    'before_intent', 'after_intent', 'before_staged_pair', 'after_staged_pair', 'before_state_replace',
    'after_state_replace', 'before_result_receipt', 'after_result_receipt')]
for _name, _occurrence in POINTS:
    setattr(CiTest, f'test_kill_at_{_name}_{_occurrence}_converges',
            lambda self, n=_name, o=_occurrence: self.converges_after_kill(n, o))


def engine_state(worker):
    from cardine.lifecycle.control import operation_state
    return operation_state(worker, '056')


if __name__ == '__main__':
    unittest.main()
