"""Disposable Codex/Claude channels, effective denials and killed-session replay."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine.hosts.launch import RoleProfile, CodexProfileAdapter, ClaudeProfileAdapter
from cardine.lifecycle import receipts
from cardine.lifecycle.engine import launch_run_work, resolve_run_locations
from cardine.lifecycle.model import WorkRequest
from cardine.shared.errors import CardineError, CardineStop
import test_run_delivery
from fixture_restore_support import RestorableFixture

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {'codex': CodexProfileAdapter, 'claude': ClaudeProfileAdapter}
HOST_POINTS = tuple(prefix + 'host_' + name for name in
    ('request', 'spawn', 'session', 'response', 'response_receipt')
    for prefix in ('before_', 'after_'))


class FakeHost:
    """Durable fake external service; credentials are checked by the host.

    This fixture implements permissions; it does not claim a real installation.
    Session creation uses an atomic request-keyed file with retained responses.
    """
    def __init__(self, directory, host):
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=True)
        self.host = host
        self.missing = None
        self.enforced = True
        self.ready = True

    def profile(self, role):
        if role == self.missing:
            return None
        return RoleProfile(self.host + ':' + role, role, self.enforced)

    def authorize(self, credential, action):
        if credential == 'coordinator-channel':
            return action == 'launch'
        if credential == 'developer-channel':
            return action == 'developer'
        if credential == 'reviewer-channel':
            return action == 'verdict'
        return credential == 'implementer-channel' and action == 'implementation'

    def lookup(self, request):
        path = self.directory / request['request_id']
        if not path.exists():
            return None
        saved = json.loads(path.read_bytes())
        if saved['request'] != request:
            raise CardineError('foreign host request')
        return saved['session']

    def spawn(self, request):
        current = self.lookup(request)
        if current:
            return current
        session = {key: request[key] for key in ('request_id', 'role', 'profile', 'host')}
        session['session_id'] = self.host + ':' + request['request_id']
        path = self.directory / request['request_id']
        with path.open('x') as stream:
            json.dump(dict(request=request, session=session), stream)
            stream.flush()
            os.fsync(stream.fileno())
        return session

    def poll(self, session):
        return dict(session=session, result='completed') if self.ready else None


def request(root, role):
    from cardine.tasks.state_core import state_path
    state = json.loads(state_path(root, '001').read_bytes())
    # A killed receipt writer may have temporarily published pending state.
    if receipts.pending_operation(root, '001'):
        state = receipts._load_intent(receipts._intent_path(root, '001'))['state']
    return WorkRequest(role, root, receipts.digest(receipts.encoded(state['contract'])),
                       ('src/**',), ('acceptance',), ('validation',), ('delivery',))


class RunHostRolesTest(unittest.TestCase):
    delivery_source = test_run_delivery.DELIVERY_FIXTURE

    def setUp(self):
        self.fixture = test_run_delivery.RunDeliveryTest()
        self.fixture.fixture_source = self.delivery_source
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.worker = self.fixture.worker
        self.host_root = self.worker.parent / 'fake-host'
        self.host = FakeHost(self.host_root, 'codex')

    def launch(self, role='reviewer', attempt='attempt-1', host=None, credential='coordinator-channel'):
        host = host or self.host
        return launch_run_work(resolve_run_locations('001', self.worker), request(self.worker, role),
                               attempt=attempt, adapter=ADAPTERS[host.host](host, credential))

    def kill(self, point, host, phase=1):
        script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.hosts.launch import launch_work
from test_run_host_roles import FakeHost, ADAPTERS, request
root = Path(sys.argv[1])
seen = 0
def kill(name):
    global seen
    if name == sys.argv[3]:
        seen += 1
        if seen == int(sys.argv[5]): os._exit(77)
receipts.boundary = kill
host = FakeHost(sys.argv[2], sys.argv[4])
launch_work(root, '001', request(root, 'reviewer'), attempt='attempt-1',
            adapter=ADAPTERS[host.host](host, 'coordinator-channel'))
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.worker), str(self.host_root),
            point, host, str(phase)], cwd=self.worker, capture_output=True, text=True,
            env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT / 'src'), str(ROOT / 'tests')])})
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_both_hosts_issue_distinct_roles_and_repeated_results_write_nothing(self):
        for name in ADAPTERS:
            host = FakeHost(self.host_root, name)
            implementer = self.launch('implementer', attempt=name, host=host)
            reviewer = self.launch(attempt=name, host=host)
            self.assertNotEqual(implementer['session'], reviewer['session'])
            self.assertNotEqual(implementer['request']['profile'], reviewer['request']['profile'])
            before = self.fixture.state()
            self.assertEqual(self.launch(attempt=name, host=host), reviewer)
            self.assertEqual(self.fixture.state(), before)
            self.assertEqual(before['status'], 'in_progress')
            self.assertNotIn('review', before.get('run', {}))

    def test_shared_host_keeps_same_task_and_attempt_in_two_projects_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            host = FakeHost(Path(directory) / 'shared-host', 'codex')
            first = self.launch(host=host)
            self.doCleanups()
            # A second project needs its own path, so it gets its own build.
            self.delivery_source = RestorableFixture('delivery-second', test_run_delivery.build_delivery_fixture)
            self.setUp()
            second = self.launch(host=host)
            self.assertNotEqual(first['request']['root'], second['request']['root'])
            self.assertNotEqual(first['request']['request_id'], second['request']['request_id'])
            self.assertNotEqual(first['session']['session_id'], second['session']['session_id'])
            self.assertEqual(len(list(host.directory.iterdir())), 2)

    def test_every_host_and_receipt_boundary_restarts_same_session(self):
        first = True
        for host_name in ADAPTERS:
            cases = [(point, 1) for point in HOST_POINTS]
            # One writer seam per publication phase; generic seams are proved
            # for host-launch in test_run_receipts, independently of the host.
            if host_name == 'codex':
                cases += [('after_intent', phase) for phase in (1, 2, 3)]
            for point, phase in cases:
                with self.subTest(host=host_name, point=point, phase=phase):
                    if not first:
                        self.doCleanups()
                        self.setUp()
                    first = False
                    head = self.fixture.git('rev-parse', 'HEAD')
                    foreign = self.host_root / 'foreign'
                    foreign.write_text('preserve')
                    self.kill(point, host_name, phase)
                    host = FakeHost(self.host_root, host_name)
                    result = self.launch(host=host)
                    self.assertEqual(self.launch(host=host), result)
                    self.assertEqual(len(list(self.host_root.iterdir())), 2)
                    self.assertEqual(foreign.read_text(), 'preserve')
                    state = self.fixture.state()
                    receipts.verify_receipts(self.worker, state)
                    launches = [r for r in state['run']['receipts'] if r['kind'].startswith('host-launch:')]
                    self.assertEqual(len(launches), 3)
                    self.assertEqual(len(state['run']['hostLaunches']), 1)
                    self.assertEqual(self.fixture.git('rev-parse', 'HEAD'), head)
                    self.assertFalse(receipts.pending_operation(self.worker, '001'))

    def test_missing_shared_or_unenforced_profile_refuses_fallback_without_writes(self):
        for name in ADAPTERS:
            host = FakeHost(self.host_root, name)
            for missing, enforced in [('reviewer', True), (None, False)]:
                host.missing, host.enforced = missing, enforced
                before = self.fixture.state()
                with self.assertRaises(CardineStop) as caught:
                    self.launch(host=host)
                self.assertEqual(caught.exception.code, 'COMMAND_REFUSED')
                self.assertIn('boundary unavailable', caught.exception.detail)
                self.assertEqual(self.fixture.state(), before)
            host.enforced = True
            with patch.object(host, 'profile', side_effect=lambda role: RoleProfile('shared', role, True)):
                with self.assertRaises(CardineStop):
                    self.launch(host=host)
        self.assertEqual(list(self.host_root.iterdir()), [])

    def test_implementer_credentials_denied_reviewer_developer_and_push_paths(self):
        for name in ADAPTERS:
            host = FakeHost(self.host_root, name)
            agent = ADAPTERS[name](host, 'implementer-channel')
            agent.require('implementation')
            for action in ('launch', 'verdict', 'developer', '--owner', 'push', 'git push origin main',
                           'state-write', 'receipt-write', 'reviewer'):
                with self.assertRaisesRegex(CardineError, 'host denied'):
                    agent.require(action)
            with self.assertRaisesRegex(CardineError, 'host denied'):
                self.launch(host=host, credential='implementer-channel')

    def test_waiting_polls_same_session_and_never_reissues_request(self):
        self.host.ready = False
        pending = self.launch()
        self.assertIsNone(pending['response'])
        before = self.fixture.state()
        self.assertEqual(self.launch(), pending)
        self.assertEqual(self.fixture.state(), before)
        self.host.ready = True
        complete = self.launch()
        self.assertEqual(complete['session'], pending['session'])
        self.assertEqual(len(list(self.host_root.iterdir())), 1)

    def test_active_implementer_or_reviewer_prevents_a_second_session(self):
        self.host.ready = False
        self.launch('implementer')
        for role, attempt in [('reviewer', 'attempt-1'), ('implementer', 'attempt-2')]:
            with self.assertRaisesRegex(CardineError, 'must stop before launching'):
                self.launch(role, attempt=attempt)
        self.host.ready = True
        self.launch('implementer')
        self.host.ready = False
        self.launch()
        with self.assertRaisesRegex(CardineError, 'must stop before launching'):
            self.launch(attempt='attempt-2')

    def test_source_commit_changed_inside_host_callback_is_observed(self):
        spawn = self.host.spawn
        def changed(request):
            session = spawn(request)
            self.fixture.git('commit', '--allow-empty', '-m', 'Concurrent source commit')
            return session
        with patch.object(self.host, 'spawn', side_effect=changed):
            with self.assertRaisesRegex(CardineError, 'inputs changed during'):
                self.launch()

    def test_changed_inputs_and_foreign_owners_refuse_without_host_effects(self):
        self.launch()
        before = self.fixture.state()
        self.host.host = 'claude'
        with self.assertRaisesRegex(CardineError, 'foreign owner or changed inputs'):
            self.launch()
        self.host.host = 'codex'
        source = self.worker / 'src/result.py'
        source.write_text(source.read_text() + '# changed\n')
        with self.assertRaisesRegex(CardineError, 'changed inputs'):
            self.launch()
        self.assertEqual(self.fixture.state(), before)
        self.assertEqual(len(list(self.host_root.iterdir())), 1)

    def test_pending_changed_source_or_foreign_operation_is_preserved(self):
        self.kill('after_intent', 'codex')
        path = receipts._intent_path(self.worker, '001')
        original = path.read_bytes()
        (self.worker / 'src/result.py').write_text('foreign source\n')
        with self.assertRaisesRegex(CardineError, 'foreign owner or changed inputs'):
            self.launch()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.host_root.iterdir()), [])

    def test_each_external_effect_rejects_changed_inputs_and_foreign_owner(self):
        first = True
        for point in ('after_host_request', 'after_host_spawn', 'after_host_session',
                      'after_host_response', 'after_host_response_receipt'):
            for change in ('source', 'profile', 'contract', 'foreign-pending'):
                with self.subTest(point=point, change=change):
                    if not first:
                        self.doCleanups()
                        self.setUp()
                    first = False
                    self.kill(point, 'codex')
                    original = self.fixture.state()
                    if change == 'source':
                        (self.worker / 'src/result.py').write_text('foreign source\n')
                    elif change == 'contract':
                        # Explicitly receipted revision still cannot reuse an old attempt.
                        from copy import deepcopy
                        updated = deepcopy(original)
                        updated['contract']['options']['validationRetryLimit'] += 1
                        with receipts.task_lock(self.worker, '001'):
                            receipts.write_operation(self.worker, '001', updated,
                                previous=original, kind='fixture-contract-revision')
                    elif change == 'foreign-pending':
                        # An intact intent for a different task must never be replayed.
                        with patch.object(receipts, 'boundary', side_effect=lambda name:
                                (_ for _ in ()).throw(RuntimeError('interrupt'))
                                if name == 'after_intent' else None):
                            with receipts.task_lock(self.worker, '001'):
                                with self.assertRaises(RuntimeError):
                                    receipts.write_operation(self.worker, '001', original,
                                        previous=original, kind='foreign-command')
                    else:
                        self.host.host = 'claude'
                    files = {p.name: p.read_bytes() for p in self.host_root.iterdir()}
                    state_bytes = (self.worker / '.cardine/tasks/001.json').read_bytes()
                    with self.assertRaises(CardineError):
                        self.launch()
                    self.assertEqual((self.worker / '.cardine/tasks/001.json').read_bytes(), state_bytes)
                    self.assertEqual({p.name: p.read_bytes() for p in self.host_root.iterdir()}, files)

    def test_foreign_session_and_response_cannot_exchange_role_tokens(self):
        original = self.host.spawn
        def wrong(request):
            return dict(original(request), role='implementer')
        with patch.object(self.host, 'spawn', side_effect=wrong):
            with self.assertRaisesRegex(CardineError, 'foreign role/session'):
                self.launch()
        with patch.object(self.host, 'poll', return_value={'session': {}, 'result': 'approved'}):
            with self.assertRaisesRegex(CardineError, 'foreign session response'):
                self.launch()
        self.assertEqual(self.launch()['response']['result'], 'completed')

    def test_host_source_mutation_during_spawn_refuses_publication(self):
        spawn = self.host.spawn
        def changed(request):
            session = spawn(request)
            (self.worker / 'src/result.py').write_text('changed during spawn\n')
            return session
        with patch.object(self.host, 'spawn', side_effect=changed):
            with self.assertRaisesRegex(CardineError, 'inputs changed during'):
                self.launch()
        record = next(iter(self.fixture.state()['run']['hostLaunches'].values()))
        self.assertIsNone(record['session'])


if __name__ == '__main__':
    unittest.main()
