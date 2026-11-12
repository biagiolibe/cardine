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

    def ready(self, *, enabled=True, review=False):
        if enabled:
            write_project_config(self.primary, validation=VALIDATION, taskDefaults=dict(ciBeforeLanding=True, review="required" if review else "not_required"),
                                 ci=dict(provider='github', requiredChecks=['validate', 'lint']))
            if review:
                path = state_path(self.primary, '056')
                state = json.loads(path.read_text())
                state['review']['required'] = True
                path.write_text(json.dumps(state))
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

    def approve(self):
        from control_support import issued_verdict
        from cardine.review.progress import prepare_review
        prepare_review(self.worker, '056')
        issued_verdict(self.worker, '056', 'APPROVE', owner=True)
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'Record approval', cwd=self.worker)

    def approved_with_main_advanced(self, *, conflicting=False):
        lines = ''.join(f'line {n}\n' for n in range(30))
        (self.primary / 'README.md').write_text(lines)
        self.git('add', '.')
        self.git('commit', '-m', 'Readme base')
        locations = self.ready(review=True)
        (self.worker / 'README.md').write_text(lines.replace('line 0\n', 'task line\n'))
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'Task readme', cwd=self.worker)
        self.measure(self.worker)
        self.checks(self.head())
        self.gate(locations)
        self.approve()
        attempt = self.state()['review']['attempt']
        (self.primary / 'README.md').write_text(lines.replace('line 0\n' if conflicting else 'line 29\n', 'main line\n'))
        (self.primary / 'other.txt').write_text('from main\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Advance main')
        return locations, attempt

    def test_clean_refresh_after_approval_keeps_review_and_lands(self):
        from cardine.integration import merge
        from cardine.tasks.identity import resolve_task_identity
        locations, attempt = self.approved_with_main_advanced()
        refreshed = engine.run_validation_step(locations)
        self.assertEqual(refreshed['action'], 'refresh-from-main')
        head = self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip()
        identity = resolve_task_identity(self.primary, '056', 'existing')
        merge._integration_task_state(self.primary, identity, head, self.worker)
        actions = []
        for _ in range(12):
            result = engine.run_validation_step(locations)
            actions.append(result['action'])
            self.assertNotEqual(result['step'], 'review', result)
            if result['action'] == 'poll-ci':
                self.checks(self.head())
            if result['action'] == 'validate-candidate':
                break
        self.assertIn('ci-passed', actions)
        self.assertIn('validate-candidate', actions)
        self.assertEqual(self.state()['review']['attempt'], attempt)
        self.assertNotEqual(self.head(), self.state()['review']['reviewed_commit'])
        self.assertEqual(self.remote_tip(), self.head())
        for _ in range(12):
            result = engine.run_integration_step(locations)
            if result['outcome'] == 'done':
                break
        self.assertEqual(result['outcome'], 'done', result)

    def test_conflicting_refresh_after_approval_stops_without_consuming_review(self):
        locations, attempt = self.approved_with_main_advanced(conflicting=True)
        head = self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip()
        with self.assertRaises(CardineStop) as raised:
            engine.run_validation_step(locations)
        self.assertEqual(raised.exception.code, 'INTEGRATION_CONFLICT')
        self.assertEqual(self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip(), head)
        self.assertEqual(self.state()['review']['attempt'], attempt)

    def test_resolved_refresh_conflict_requires_another_review(self):
        from cardine.integration import refresh, merge
        from cardine.review.progress import review_progress
        from cardine.tasks.identity import resolve_task_identity
        locations, _ = self.approved_with_main_advanced(conflicting=True)
        main = self.git('rev-parse', 'main').stdout.strip()
        conflict = self.git('merge', '--no-ff', main, cwd=self.worker, check=False)
        self.assertNotEqual(conflict.returncode, 0)
        (self.worker / 'README.md').write_text('Resolved by implementer\n')
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'Resolve refresh conflict', cwd=self.worker)
        refresh.record_base(locations, main)
        self.assertFalse(review_progress(self.worker, '056', self.state())[0])
        identity = resolve_task_identity(self.primary, '056', 'existing')
        head = self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip()
        with self.assertRaises(CardineStop) as raised:
            merge._integration_task_state(self.primary, identity, head, self.worker)
        self.assertEqual(raised.exception.code, 'REVIEW_NOT_APPROVED')
        self.assertIn('README.md', raised.exception.detail)

    def test_refresh_does_not_cover_later_implementation_changes(self):
        from cardine.integration import merge
        from cardine.review.progress import review_progress
        from cardine.tasks.identity import resolve_task_identity
        locations, _ = self.approved_with_main_advanced()
        self.assertEqual(engine.run_validation_step(locations)['action'], 'refresh-from-main')
        (self.worker / 'feature.txt').write_text('unreviewed change')
        self.assertFalse(review_progress(self.worker, '056', self.state())[0])
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'Unreviewed implementation', cwd=self.worker)
        head = self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip()
        identity = resolve_task_identity(self.primary, '056', 'existing')
        with self.assertRaises(CardineStop) as raised:
            merge._integration_task_state(self.primary, identity, head, self.worker)
        self.assertEqual(raised.exception.code, 'REVIEW_NOT_APPROVED')
        self.assertIn('feature.txt', raised.exception.detail)
        self.assertFalse(review_progress(self.worker, '056', self.state())[0])

    def test_required_review_waits_for_ci_and_failure_does_not_consume_attempt(self):
        locations = self.ready(review=True)
        before = self.state().get('review', {}).get('attempt', 0)
        from cardine.lifecycle.preview import preview_run
        with self.no_writes():
            preview = preview_run(locations)
        self.assertEqual((preview['step'], preview['outcome']), ('candidate', 'waiting'))
        waiting = engine.run_validation_step(locations)
        self.assertEqual((waiting['step'], waiting['action']), ('candidate', 'poll-ci'))
        self.assertNotEqual(self.state()['status'], 'in_review')
        self.checks(self.head(), conclusion='failure')
        failed = engine.run_validation_step(locations)
        self.assertEqual((failed['outcome'], failed['action']), ('iterate', 'ci-failed'))
        self.assertEqual(self.state().get('review', {}).get('attempt', 0), before)
        self.assertFalse(self.state().get('review_history'))
        self.checks(self.head())
        passed = engine.run_validation_step(locations)
        self.assertEqual((passed['step'], passed['action']), ('review', 'ci-passed'))
        self.assertIn('--owner', passed['next']['argv'])
        self.assertEqual(self.state()['status'], 'in_review')
        with self.no_writes():
            self.assertEqual(preview_run(locations)['step'], 'review')
        self.assertEqual(self.push_count(), 1)

    def test_approval_needs_receipt_covered_ci_but_changes_requested_does_not(self):
        from cardine.review.progress import prepare_review
        from cardine.review.verdict import record_review_verdict
        from control_support import adapter
        self.ready(review=True)
        prepare_review(self.worker, '056')
        with self.assertRaises(CardineStop) as raised:
            record_review_verdict(self.worker, '056', 'APPROVE', owner=True, adapter=adapter())
        self.assertEqual(raised.exception.code, 'REVIEW_NOT_APPROVED')
        self.assertIn('cause: missing', raised.exception.detail)
        self.assertIn(self.git('rev-parse', 'HEAD', cwd=self.worker).stdout.strip(), raised.exception.detail)
        self.assertIn('lint, validate', raised.exception.detail)
        state = record_review_verdict(self.worker, '056', 'CHANGES_REQUESTED', owner=True, adapter=adapter())
        self.assertEqual(state['review']['verdict'], 'CHANGES_REQUESTED')
        self.assertEqual(self.gh_calls(), 0)

    def test_changes_requested_needs_ci_on_the_next_delivery(self):
        from control_support import issued_verdict
        locations = self.ready(review=True)
        old = self.head()
        self.checks(old)
        self.assertEqual(engine.run_validation_step(locations)['step'], 'review')
        issued_verdict(self.worker, '056', 'CHANGES_REQUESTED', owner=True)
        self.git('add', '.', cwd=self.worker)
        self.git('commit', '-m', 'Record requested changes', cwd=self.worker)
        self.implement('remediated')
        self.assertNotEqual(self.head(), old)
        attempt = self.state()['review']['attempt']
        waiting = engine.run_validation_step(locations)
        self.assertEqual((waiting['step'], waiting['action']), ('candidate', 'poll-ci'))
        self.assertEqual(self.state()['review']['attempt'], attempt)
        self.checks(self.head())
        self.assertEqual(engine.run_validation_step(locations)['step'], 'review')
        self.assertEqual(self.push_count(), 2)

    def interrupted_ci_approval(self, point):
        from cardine.review.progress import prepare_review
        from cardine.review.verdict import record_review_verdict
        from control_support import adapter
        locations = self.ready(review=True)
        self.checks(self.head())
        self.gate(locations)
        prepare_review(self.worker, '056')
        def interrupt(name):
            if name == point:
                raise RuntimeError('interrupted approval')
        with mock.patch.object(receipts, 'boundary', side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, 'interrupted approval'):
                record_review_verdict(self.worker, '056', 'APPROVE', owner=True, adapter=adapter())
        self.assertIsNotNone(engine_state(self.worker)[1])
        state = record_review_verdict(self.worker, '056', 'APPROVE', owner=True, adapter=adapter())
        self.assertEqual(state['review']['verdict'], 'APPROVE')
        self.assertEqual(len(state['review_history']), 1)
        self.assertIsNone(engine_state(self.worker)[1])
        self.assertEqual(self.push_count(), 1)

    def test_ci_approval_replays_after_intent(self):
        self.interrupted_ci_approval('after_intent')

    def test_ci_approval_replays_after_result_receipt(self):
        self.interrupted_ci_approval('after_result_receipt')

    def test_approval_reuses_ci_pass_across_review_attempt_change(self):
        locations = self.ready(review=True)
        self.checks(self.head())
        self.gate(locations)
        self.approve()
        calls = self.gh_calls()
        self.assertFalse(self.gate(locations)['changed'])
        self.assertEqual(self.gh_calls(), calls)
        self.assertNotIn('attempt', self.state()['run']['ci']['binding'])

    def test_disabled_ci_runs_no_gh_and_no_git(self):
        locations = self.ready(enabled=False)
        with mock.patch.dict(os.environ, {'FAKE_GH_FORBID': '1'}), \
                mock.patch.object(ci, '_run_git', side_effect=AssertionError('git ran')), \
                mock.patch.object(ci.shutil, 'which', side_effect=AssertionError('gh looked up')):
            self.assertIsNone(self.gate(locations))
        with mock.patch('cardine.shared.git.subprocess.run', side_effect=AssertionError('process ran')):
            self.assertIsNone(engine.run_ci_step(locations, None, None, self.state()))
        self.assertEqual((self.gh_calls(), self.push_count()), (0, 0))

    def test_wait_polls_to_pass_or_failure_without_another_push(self):
        locations = self.ready()
        head = self.head()
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
            self.checks(head)
        result = ci.ci_gate(locations, wait_seconds=20, clock=lambda: now[0], sleep=sleep)
        self.assertEqual(result['phase'], 'passed')
        self.assertEqual(self.push_count(), 1)

    def test_wait_detects_failure_and_interruption_does_not_repush(self):
        locations = self.ready()
        head = self.head()
        def interrupted(seconds):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            ci.ci_gate(locations, wait_seconds=20, sleep=interrupted)
        now = [0.0]
        def fail(seconds):
            now[0] += seconds
            self.checks(head, conclusion='failure')
        result = ci.ci_gate(locations, wait_seconds=20, clock=lambda: now[0], sleep=fail)
        self.assertEqual(result['phase'], 'failed')
        self.assertEqual(self.push_count(), 1)
        self.assertNotIn('ci-result', self.kinds())

    def test_changed_delivery_during_wait_cannot_publish_old_result(self):
        locations = self.ready()
        old = self.head()
        def replace_delivery(seconds):
            self.implement('changed while waiting')
            self.checks(old)
        with self.assertRaisesRegex(CardineError, 'CI inputs changed'):
            ci.ci_gate(locations, wait_seconds=30, sleep=replace_delivery)
        self.assertNotEqual(self.head(), old)
        self.assertNotIn('ci-result', self.kinds())

    def test_wait_timeout_reuses_published_head(self):
        locations = self.ready()
        head = self.head()
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        result = ci.ci_gate(locations, wait_seconds=3, clock=lambda: now[0], sleep=sleep)
        self.assertEqual(result['phase'], 'waiting')
        self.assertIn(head, result['detail'])
        self.assertIn('lint', result['detail'])
        self.assertEqual(result['diagnostic'], 'CI_NOT_STARTED')
        self.assertEqual(ci.ci_gate(locations)['head'], head)
        self.assertEqual(self.push_count(), 1)

    def run_with_fake_wait(self, locations, seconds):
        now = [0.0]
        gate = ci.ci_gate
        def sleep(duration):
            now[0] += duration
        def timed_gate(locations, *, wait_seconds=0):
            return gate(locations, wait_seconds=wait_seconds, clock=lambda: now[0], sleep=sleep)
        with mock.patch.object(ci, 'ci_gate', side_effect=timed_gate):
            return engine.dispatch_run(locations, ci_wait_seconds=seconds)

    def test_missing_ci_stops_after_300_seconds(self):
        locations = self.ready()
        result = self.run_with_fake_wait(locations, 300)
        engine.validate_output(result)
        self.assertEqual(result['outcome'], 'blocked')
        self.assertEqual(result['stop']['code'], 'CI_NOT_STARTED')
        self.assertTrue(result['stop']['human_decision'])
        from cardine.stops.render import format_stop
        self.assertTrue(format_stop('CI_NOT_STARTED', result['stop']['detail'],
                                    resume=result['stop']['resume']).startswith('BLOCKED CI_NOT_STARTED:'))
        self.assertEqual(result['stop']['resume'],
                         f'cardine run 056 --project {self.primary} --ci-wait-seconds 300')
        self.assertIn(self.head(), result['stop']['detail'])
        self.assertIn('refs/heads/task-056', result['stop']['detail'])
        self.assertIn('lint, validate', result['stop']['detail'])
        self.assertIn(f'git push origin {self.head()}:refs/heads/task-056-ci', result['stop']['detail'])

    def test_missing_ci_waits_below_threshold(self):
        locations = self.ready()
        for seconds in (0, 30, 299):
            with self.subTest(seconds=seconds):
                result = self.run_with_fake_wait(locations, seconds)
                self.assertEqual(result['outcome'], 'waiting')
                self.assertEqual(result['diagnostics'][0]['code'], 'CI_NOT_STARTED')
                self.assertIn('provider has not started CI', result['diagnostics'][0]['message'])
        self.assertEqual(self.push_count(), 1)

    def test_queued_ci_still_waits_after_300_seconds(self):
        locations = self.ready()
        self.checks(self.head(), status='queued', conclusion=None, names=('validate',))
        result = self.run_with_fake_wait(locations, 300)
        self.assertEqual(result['outcome'], 'waiting')
        self.assertEqual(result['diagnostics'][0]['code'], 'CI_PENDING')
        self.assertIn('300 seconds', result['diagnostics'][0]['message'])

    def test_unanswered_provider_does_not_prove_ci_never_started(self):
        locations = self.ready()
        now = [0.0]
        def sleep(seconds):
            now[0] += seconds
        with mock.patch.object(ci, '_provider', return_value=None):
            result = ci.ci_gate(locations, wait_seconds=300, clock=lambda: now[0], sleep=sleep)
        self.assertEqual(result['phase'], 'waiting')
        self.assertNotIn('diagnostic', result)

    def test_successful_checks_on_another_ref_pass(self):
        locations = self.ready()
        head = self.head()
        self.checks(head)
        state = json.loads(self.gh_state.read_text())
        for run in state['runs'][head]:
            run['check_suite'] = dict(head_branch='task-056-ci')
        self.gh_state.write_text(json.dumps(state))
        self.assertEqual(self.gate(locations)['phase'], 'passed')

    def test_pagination_uses_remaining_deadline(self):
        now = [0.0]
        binding = dict(repository='github.com/a/b', head='a' * 40, checks=['check'])
        def provider(binding, endpoint, timeout):
            self.assertLessEqual(timeout, 2 - now[0])
            now[0] += 1
            return dict(total_count=500, check_runs=[{}])
        with mock.patch.object(ci, '_provider', side_effect=provider):
            result = ci.query_checks(binding, deadline=2, clock=lambda: now[0])
        self.assertEqual(result['phase'], 'waiting')
        self.assertEqual(now[0], 2)

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
        command = [sys.executable, '-m', 'cardine.cli', 'run', '056', '--project', str(self.primary), '--ci-wait-seconds', '0']
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


# Keep every CI effect and a writer seam for both the push and result writes.
POINTS = [(name, 1) for name in ('before_ci_push', 'after_ci_push', 'before_ci_query', 'after_ci_query')]
POINTS += [('after_intent', occurrence) for occurrence in (1, 2)]
for _name, _occurrence in POINTS:
    setattr(CiTest, f'test_kill_at_{_name}_{_occurrence}_converges',
            lambda self, n=_name, o=_occurrence: self.converges_after_kill(n, o))


def engine_state(worker):
    from cardine.lifecycle.control import operation_state
    return operation_state(worker, '056')


if __name__ == '__main__':
    unittest.main()
