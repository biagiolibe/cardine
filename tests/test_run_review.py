"""Issued review decisions, same-user boundary negatives and killed-effect replay."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from cardine.hosts.launch import CodexProfileAdapter, launch_work
from cardine.lifecycle import receipts
from cardine.lifecycle.control import require_review_budget
from cardine.review.verdict import record_review_verdict
from cardine.shared.errors import CardineError, CardineStop
from cardine.tasks.transitions import transition_task_state
import test_run_delivery
from test_run_host_roles import FakeHost, request

ROOT = Path(__file__).resolve().parents[1]
POINTS = tuple(prefix + name for name in ('intent', 'staged_pair', 'state_replace',
    'result_receipt', 'review_state', 'review_projection') for prefix in ('before_', 'after_'))


class BoundHost(FakeHost):
    def authorize(self, credential, action):
        if action == 'verdict':
            return credential.startswith('codex:')
        return super().authorize(credential, action)

    def authorize_operation(self, credential, action, binding, session):
        if session:
            path = self.directory / session['request_id']
            if (credential != session['session_id'] or not path.exists()
                    or json.loads(path.read_bytes())['session'] != session):
                return None
            return {k: session[k] for k in ('host', 'profile', 'session_id', 'role')}
        if credential != 'developer-channel':
            return None
        return dict(host=self.host, profile='developer', role='developer', session_id=credential)


class RunReviewTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_delivery.RunDeliveryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.worker
        self.git = self.fixture.git
        self.state = self.fixture.state
        state = self.state()
        updated = deepcopy(state)
        updated['contract']['options']['review'] = 'required'
        with receipts.task_lock(self.root, '001'):
            receipts.write_operation(self.root, '001', updated, previous=state, kind='fixture-review-policy')
        with patch('cardine.tasks.transitions.delivery_readiness'):
            transition_task_state(self.root, '001', 'in_review')
        self.git('add', '.')
        self.git('commit', '-m', 'Submit review')
        self.host_root = self.root.parent / 'review-host'
        self.host = BoundHost(self.host_root, 'codex')
        self.record = launch_work(self.root, '001', request(self.root, 'reviewer'), attempt='review-1',
                          adapter=CodexProfileAdapter(self.host, 'coordinator-channel'))
        self.key = self.record['request']['request_id']

    def verdict(self, verdict='APPROVE', credential=None, **kwargs):
        return record_review_verdict(self.root, '001', verdict,
            adapter=CodexProfileAdapter(self.host, credential or self.record['session']['session_id']),
            request_id=self.key, **kwargs)

    def kill(self, point, verdict='APPROVE'):
        script = '''
import os,sys,json
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.review.verdict import record_review_verdict
from cardine.hosts.launch import CodexProfileAdapter
from test_run_review import BoundHost
root = Path(sys.argv[1])
def kill(name):
    if name == sys.argv[3]: os._exit(77)
receipts.boundary = kill
record = json.loads(Path(sys.argv[2], sys.argv[4]).read_bytes())
record_review_verdict(root, '001', sys.argv[5], request_id=sys.argv[4],
    adapter=CodexProfileAdapter(BoundHost(sys.argv[2], 'codex'), record['session']['session_id']))
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), str(self.host_root), point,
             self.key, verdict], cwd=self.root, capture_output=True, text=True,
             env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT/'src'), str(ROOT/'tests')])})
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_every_state_projection_and_receipt_boundary_converges_once(self):
        first = True
        for verdict in ('APPROVE', 'CHANGES_REQUESTED', 'BLOCKED'):
            for point in POINTS:
                with self.subTest(verdict=verdict, point=point):
                    if not first:
                        self.doCleanups()
                        self.setUp()
                    first = False
                    head = self.git('rev-parse', 'HEAD')
                    self.kill(point, verdict)
                    saved = (receipts._load_intent(receipts._intent_path(self.root, '001'))['state']
                             if receipts.pending_operation(self.root, '001') else self.state())
                    result = self.verdict(verdict)
                    self.assertEqual(result, self.verdict(verdict))
                    if point != 'before_intent':
                        self.assertEqual(result['review'], saved['review'])
                        self.assertEqual(result['transitions'], saved['transitions'])
                        self.assertEqual(result['run']['reviewRecordedAt'], saved['run']['reviewRecordedAt'])
                    self.assertEqual(len(result['review_history']), 1)
                    self.assertEqual(len([r for r in result['run']['receipts'] if r['kind'].startswith('review_verdict:')]), 1)
                    self.assertEqual((self.root/'tasks/reviews/001.md').read_text().count('## Attempt '), 1)
                    self.assertEqual(self.git('rev-parse', 'HEAD'), head)

    def test_implementer_owner_spoof_and_exchanged_reviewer_session_write_nothing(self):
        before = self.state()
        for credential, owner in [('implementer-channel', False), ('implementer-channel', True),
                                  ('codex:foreign', False), ('coordinator-channel', True)]:
            with self.subTest(credential=credential, owner=owner), self.assertRaises(CardineError):
                self.verdict(credential=credential, owner=owner)
            self.assertEqual(self.state(), before)
        with self.assertRaises(CardineError):
            record_review_verdict(self.root, '001', 'APPROVE', owner=True)
        developer = CodexProfileAdapter(self.host, 'developer-channel')
        result = record_review_verdict(self.root, '001', 'APPROVE', owner=True, adapter=developer)
        self.assertEqual(result['review']['approved_by'], 'owner')

    def test_stale_review_and_pending_changed_inputs_or_owner_preserve_intent(self):
        for point in ('after_intent', 'after_review_state', 'after_review_projection', 'after_result_receipt'):
            for change in ('source', 'owner', 'body'):
                self.doCleanups()
                self.setUp()
                self.kill(point)
                intent = receipts._intent_path(self.root, '001')
                before = intent.read_bytes()
                if change == 'source':
                    (self.root/'src/result.py').write_text('changed\n')
                with self.assertRaises(CardineError):
                    self.verdict(credential='codex:foreign' if change == 'owner' else None,
                                 body='changed' if change == 'body' else '')
                self.assertEqual(intent.read_bytes(), before)
        self.doCleanups()
        self.setUp()
        (self.root/'src/result.py').write_text('changed\n')
        self.git('add', 'src/result.py')
        self.git('commit', '-m', 'Change reviewed source')
        with self.assertRaises(CardineStop) as caught:
            self.verdict()
        self.assertEqual(caught.exception.code, 'REVIEW_NOT_APPROVED')

    def test_two_changes_requested_rounds_exhaust_without_duplicate_count(self):
        self.verdict('CHANGES_REQUESTED')
        self.git('add', '.')
        self.git('commit', '-m', 'First findings')
        with patch('cardine.tasks.transitions.delivery_readiness'):
            transition_task_state(self.root, '001', 'in_review')
        self.git('add', '.')
        self.git('commit', '-m', 'Submit next review')
        self.record = launch_work(self.root, '001', request(self.root, 'reviewer'), attempt='review-2',
                          adapter=CodexProfileAdapter(self.host, 'coordinator-channel'))
        self.key = self.record['request']['request_id']
        second = self.verdict('CHANGES_REQUESTED')
        self.assertEqual(second, self.verdict('CHANGES_REQUESTED'))
        self.assertNotIn('delivery', second['run'])
        self.assertNotIn('validation', second['run'])
        with self.assertRaises(CardineStop) as caught:
            require_review_budget(self.root, '001', second)
        self.assertEqual(caught.exception.code, 'REVIEW_LOOP_EXHAUSTED')
        before = self.state()
        with self.assertRaises(CardineStop):
            transition_task_state(self.root, '001', 'in_review')
        self.assertEqual(self.state(), before)

    def test_unavailable_profile_and_source_change_during_authorization_refuse(self):
        before = self.state()
        self.host.enforced = False
        with self.assertRaises(CardineError):
            self.verdict()
        self.assertEqual(self.state(), before)
        self.host.enforced = True
        authorize = self.host.authorize_operation
        def changed(*args):
            result = authorize(*args)
            self.git('commit', '--allow-empty', '-m', 'Concurrent source commit')
            return result
        with patch.object(self.host, 'authorize_operation', side_effect=changed):
            with self.assertRaisesRegex(CardineError, 'inputs changed'):
                self.verdict()
        self.assertEqual(self.state(), before)

    def test_cli_owner_flag_cannot_create_developer_authority(self):
        before = self.state()
        result = subprocess.run([sys.executable, str(ROOT/'scripts/cardine_cli.py'),
            'review', 'verdict', '001', 'APPROVE', '--owner', '--project', str(self.root)],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('host role boundary unavailable', result.stderr)
        self.assertEqual(self.state(), before)


class RunReviewFlowTest(unittest.TestCase):
    def test_measured_validation_issues_review_and_approval_reaches_candidate(self):
        from cardine.lifecycle.engine import (run_validation_step, resolve_run_locations,
            launch_run_work)
        from cardine.review.progress import review_progress
        fixture = test_run_delivery.RunDeliveryTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.worker
        state = fixture.state()
        updated = deepcopy(state)
        updated['contract']['options']['review'] = 'required'
        updated['contract']['deliverables'] = ['src/result.py']
        with receipts.task_lock(root, '001'):
            receipts.write_operation(root, '001', updated, previous=state, kind='fixture-review-policy')
        fixture.git('add', '.')
        fixture.git('commit', '-m', 'Freeze review contract')
        fixture.deliver()
        locations = resolve_run_locations('001', root)
        result = run_validation_step(locations)
        self.assertEqual(result['step'], 'review')
        self.assertEqual(fixture.state()['status'], 'in_review')
        host = BoundHost(root.parent/'review-host', 'codex')
        record = launch_run_work(locations, request(root, 'reviewer'), attempt='measured-review',
                                 adapter=CodexProfileAdapter(host, 'coordinator-channel'))
        waiting = run_validation_step(locations)
        self.assertEqual(waiting['outcome'], 'waiting')
        state = record_review_verdict(root, '001', 'APPROVE', request_id=record['request']['request_id'],
            adapter=CodexProfileAdapter(host, record['session']['session_id']))
        before = deepcopy(state)
        self.assertTrue(review_progress(root, '001', state)[0])
        candidate = run_validation_step(locations)
        self.assertEqual((candidate['step'], candidate['action']), ('candidate', 'validate-candidate'))
        after = fixture.state()
        self.assertEqual({k: v for k, v in after.items() if k != 'run'},
                         {k: v for k, v in before.items() if k != 'run'})
        self.assertEqual(after['run']['reviewDecision'], before['run']['reviewDecision'])
        self.assertEqual(after['run']['candidateValidation']['phase'], 'passed')
        # The review test continues with a new implementation after disposing
        # only its owned candidate through the authorized fixture channel.
        from cardine.integration.merge import abort_task_integration
        from control_support import adapter
        abort_task_integration('001', locations.primary, adapter=adapter('coordinator'))
        fixture.git('add', '.')
        fixture.git('commit', '-m', 'Commit review evidence')
        self.assertTrue(review_progress(root, '001', fixture.state())[0])
        (root/'src/result.py').write_text('changed after approval\n')
        fixture.git('add', '.')
        fixture.git('commit', '-m', 'Change approved implementation')
        self.assertFalse(review_progress(root, '001', fixture.state())[0])
