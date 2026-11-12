"""Concrete Claude/Codex transports over disposable homes and fake host executables."""
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from cardine.hosts import claude, codex, permissions, setup
from cardine.hosts.launch import host_adapter
from cardine.hosts.transports import ClaudeTransport, CodexTransport
from cardine.lifecycle import receipts
from cardine.lifecycle.engine import concrete_host_adapter, launch_run_work, resolve_run_locations
from cardine.shared.errors import CardineError, CardineStop
import test_run_delivery
from test_run_host_roles import request

FAKE_HOST = '''#!/bin/sh
echo "$@" >> "$FAKE_HOST_LOG"
test -n "$CARDINE_HOST_CREDENTIAL" || exit 3
while [ ! -e "$FAKE_HOST_RELEASE" ]; do sleep 0.05; done
'''
POINTS = tuple(prefix + 'host_' + name for name in ('spawn', 'session', 'response', 'response_receipt')
               for prefix in ('before_', 'after_'))


class HostTransportsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_delivery.RunDeliveryTest()
        self.fixture.fixture_source = test_run_delivery.DELIVERY_FIXTURE
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.worker = self.fixture.worker
        self.base = self.worker.parent / 'transports'
        self.base.mkdir()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.release = self.base / 'release'
        self.log = self.base / 'host.log'
        self.executable = self.base / 'fake-host'
        self.executable.write_text(FAKE_HOST)
        self.executable.chmod(0o755)
        self.addCleanup(self.release.touch)

    def transport(self, host):
        common = Path(self.fixture.git('rev-parse', '--git-common-dir'))
        common = (common if common.is_absolute() else self.worker / common).resolve()
        environment = {'HOME': str(self.home), 'FAKE_HOST_LOG': str(self.log), 'FAKE_HOST_RELEASE': str(self.release)}
        directory = self.base / ('sessions-' + host)
        if host == 'claude':
            policies = {role: claude.claude_role_policy(role, self.worker, self.worker, common)
                        for role in permissions.ROLES}
            return ClaudeTransport(directory, self.executable, policies=policies,
                                   proofs=self.proofs(policies), environment=environment)
        policies = {role: codex.codex_role_policy(role, self.worker, self.base, self.worker, common)
                    for role in permissions.ROLES}
        plan = codex.CodexRolePlan('ready', self.home / 'config.toml', '', '', None, ())
        return CodexTransport(directory, self.executable, policies=policies, plan=plan,
                              proofs=self.proofs(policies), environment=environment)

    @staticmethod
    def proofs(policies):
        """Host-observed decisions injected as data; the transport never derives them."""
        return {role: permissions.HostProof(policy.host, policy.identity, policy.digest,
                    {name: verdict for name, (_t, _i, verdict) in permissions.probe_matrix(role, policy.host).items()})
                for role, policy in policies.items()}

    def launch(self, host, role='reviewer', attempt='attempt-1', credential=None):
        locations = resolve_run_locations('001', self.worker)
        adapter = concrete_host_adapter(host.host, host, credential or self.coordinator(host))
        return launch_run_work(locations, request(self.worker, role), attempt=attempt, adapter=adapter)

    def coordinator(self, host):
        if not hasattr(host, 'coordinator_token'):
            host.coordinator_token = host.issue(('launch',))
        return host.coordinator_token

    def settle(self, host, role='reviewer', attempt='attempt-1'):
        self.release.touch()
        deadline = time.time() + 20
        while time.time() < deadline:
            record = self.launch(host, role, attempt)
            if record['response']:
                return record
            time.sleep(0.05)
        self.fail('host process did not stop')

    def runs(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def snapshot(self, host):
        return {str(p.relative_to(host.directory)): p.read_bytes()
                for p in sorted(host.directory.rglob('*')) if p.is_file()}

    def test_both_hosts_run_each_role_once_with_its_own_profile(self):
        for name, flag in (('claude', '--settings'), ('codex', '--profile')):
            with self.subTest(host=name):
                self.log.unlink(missing_ok=True)
                host = self.transport(name)
                implementer = self.settle(host, 'implementer', name)
                reviewer = self.settle(host, 'reviewer', name)
                self.assertNotEqual(implementer['session'], reviewer['session'])
                self.assertEqual(reviewer['response']['result'], 'completed')
                lines = self.runs()
                self.assertEqual(len(lines), 2)
                self.assertTrue(all(flag in line for line in lines))
                if name == 'codex':
                    self.assertIn('cardine-implementer', lines[0])
                    self.assertIn('cardine-reviewer', lines[1])
                self.assertEqual(self.settle(host, 'reviewer', name), reviewer)
                self.assertEqual(len(self.runs()), 2)

    def test_wrapper_collects_only_json_objects_and_issues_no_verdict_action(self):
        for index, content in enumerate((None, 'invalid', '[]', '{"verdict":"APPROVE","findings":"OK"}')):
            with self.subTest(content=content):
                host = self.transport('claude')
                attempt = 'answer-' + str(index)
                record = self.launch(host, attempt=attempt)
                directory = host.directory / record['request']['request_id']
                if content is not None:
                    (directory / 'output.json').write_text(content)
                record = self.settle(host, attempt=attempt)
                expected = json.loads(content) if index == 3 else None
                self.assertEqual(record['response']['output'], expected)
                token = json.loads((directory / 'launch.json').read_text())['credential']
                self.assertFalse(host.authorize(token, 'verdict'))
                self.release.unlink()

    def test_reviewer_launch_needs_only_its_own_enforced_profile(self):
        from cardine.hosts.launch import RoleProfile
        host = self.transport('claude')
        reviewer = host.profile('reviewer')
        for implementer in (None, RoleProfile('ordinary', 'implementer', False)):
            with patch.object(host, 'profile', side_effect=lambda role: reviewer if role == 'reviewer' else implementer):
                with self.assertRaises(CardineStop):
                    self.launch(host, role='implementer')
                self.assertEqual(self.settle(host)['response']['result'], 'completed')

    def test_old_response_without_output_is_accepted(self):
        host = self.transport('claude')
        original = host.poll
        def old_poll(session):
            value = original(session)
            if value:
                value.pop('output', None)
            return value
        with patch.object(host, 'poll', side_effect=old_poll):
            record = self.settle(host)
        self.assertEqual(set(record['response']), {'session', 'result'})

    def test_credentials_bind_owner_and_action(self):
        for name in ('claude', 'codex'):
            with self.subTest(host=name):
                host = self.transport(name)
                implementer = self.settle(host, 'implementer', name)
                reviewer = self.settle(host, 'reviewer', name)
                token = host.issue(('implementation',), binding=implementer['session'])
                self.assertTrue(host.authorize(token, 'implementation'))
                for action in ('verdict', 'launch', 'developer', 'push', 'state-write', '--owner'):
                    self.assertFalse(host.authorize(token, action))
                for label in ('implementer', 'reviewer', 'coordinator-channel', 'implementer-channel', '', None):
                    self.assertFalse(host.authorize(label, 'implementation'))
                allowed = host.authorize_operation(token, 'implementation', {}, implementer['session'])
                self.assertEqual(allowed['role'], 'implementer')
                self.assertIsNone(host.authorize_operation(token, 'implementation', {}, reviewer['session']))
                self.assertIsNone(host.authorize_operation(token, 'verdict', {}, implementer['session']))
                self.assertIsNone(host.authorize_operation(token, 'implementation', {}, None))
                self.assertFalse(host.authorize(self.coordinator(host), 'implementation'))
                self.assertNotIn(token, json.dumps(self.snapshot(host), default=str))
                with self.assertRaisesRegex(CardineError, 'host denied'):
                    self.launch(host, credential=token)

    def test_missing_or_partial_proof_refuses_without_any_host_effect(self):
        for name in ('claude', 'codex'):
            with self.subTest(host=name):
                host = self.transport(name)
                proofs = dict(host.proofs)
                for dropped in (('implementer', 'reviewer'), ('reviewer',)):
                    host.proofs = {k: v for k, v in proofs.items() if k not in dropped}
                    before = self.fixture.state()
                    with self.assertRaises(CardineStop) as caught:
                        self.launch(host)
                    self.assertEqual(caught.exception.code, 'COMMAND_REFUSED')
                    self.assertEqual(self.fixture.state(), before)
                host.proofs = {role: permissions.HostProof(p.host, p.identity, p.digest, {**p.decisions, 'push-main': 'allow'})
                               for role, p in proofs.items()}
                with self.assertRaises(CardineStop):
                    self.launch(host)
                self.assertEqual([p.name for p in host.directory.iterdir()], ['credentials.json'])
                self.assertEqual(self.runs(), [])

    @staticmethod
    def doctor_proofs(policies, wrong=None, hidden=None):
        """Proofs as doctor produces them from a fake host; a role maps to None when the run is incomplete."""
        proofs = {}
        for role, policy in policies.items():
            def evaluate(tool, tool_input, role=role, policy=policy):
                for name, (probe_tool, probe_input, expected) in permissions.probe_matrix(role, policy.host).items():
                    if (probe_tool, probe_input) == (tool, tool_input):
                        if (role, name) == hidden:
                            return None
                        return ('allow' if expected == 'deny' else 'deny') if (role, name) == wrong else expected
            proofs[role] = setup.prove_role_policy(policy, evaluate).proof
        return {role: proof for role, proof in proofs.items() if proof is not None}

    def test_role_activation_follows_only_the_proof_doctor_produced(self):
        for name in ('claude', 'codex'):
            host = self.transport(name)
            cases = (
                ('complete', self.doctor_proofs(host.policies), {'implementer': True, 'reviewer': True}),
                ('wrong decision', self.doctor_proofs(host.policies, wrong=('reviewer', 'push-main')),
                 {'implementer': name == 'claude', 'reviewer': False}),
                ('unobserved probe', self.doctor_proofs(host.policies, hidden=('implementer', 'edit-state')),
                 {'implementer': False, 'reviewer': name == 'claude'}),
            )
            for label, proofs, expected in cases:
                host.proofs = proofs
                with self.subTest(host=name, case=label):
                    self.assertEqual({role: host.profile(role).enforced for role in permissions.ROLES}, expected)
            host.proofs = self.doctor_proofs(host.policies, wrong=('reviewer', 'push-main'))
            with self.assertRaises(CardineStop) as caught:
                self.launch(host)
            self.assertEqual(caught.exception.code, 'COMMAND_REFUSED')
            self.assertEqual(self.runs(), [])

    def test_running_writer_is_polled_without_writes_and_blocks_a_second_session(self):
        host = self.transport('codex')
        pending = self.launch(host, 'implementer')
        self.assertIsNone(pending['response'])
        before, state = self.snapshot(host), self.fixture.state()
        self.assertEqual(self.launch(host, 'implementer'), pending)
        self.assertEqual(self.snapshot(host), before)
        self.assertEqual(self.fixture.state(), state)
        for role, attempt in (('reviewer', 'attempt-1'), ('implementer', 'attempt-2')):
            with self.assertRaisesRegex(CardineError, 'must stop before launching'):
                self.launch(host, role, attempt)
        done = self.settle(host, 'implementer')
        self.assertEqual(done['session'], pending['session'])
        self.assertEqual(len(self.runs()), 1)

    def test_every_launch_boundary_replays_into_the_same_single_host_run(self):
        first = True
        for name in ('claude', 'codex'):
            for point in POINTS:
                with self.subTest(host=name, point=point):
                    if not first:
                        self.doCleanups()
                        self.setUp()
                    first = False
                    host = self.transport(name)
                    self.coordinator(host)
                    if point.endswith('response_receipt'):
                        # Only a stopped writer has a response to receipt: let it stop first.
                        self.launch(host)
                        self.release.touch()
                        deadline = time.time() + 20
                        while not list(host.directory.glob('*/result.json')) and time.time() < deadline:
                            time.sleep(0.05)

                    def interrupt(seen, point=point):
                        if seen == point:
                            raise RuntimeError('killed')
                    with patch.object(receipts, 'boundary', side_effect=interrupt):
                        with self.assertRaises(RuntimeError):
                            self.launch(host)
                    result = self.settle(host)
                    self.assertEqual(self.settle(host), result)
                    self.assertEqual(len(self.runs()), 1)
                    sessions = [p for p in host.directory.iterdir() if p.is_dir()]
                    self.assertEqual(len(sessions), 1)
                    receipts.verify_receipts(self.worker, self.fixture.state())

    def test_lost_spawn_response_reuses_the_recorded_request_and_starts_nothing_twice(self):
        for name in ('claude', 'codex'):
            with self.subTest(host=name):
                self.log.unlink(missing_ok=True)
                host = self.transport(name)
                self.coordinator(host)
                spawn = host.spawn
                calls = []
                def lose(request):
                    calls.append(spawn(request))
                    raise RuntimeError('response lost')
                with patch.object(host, 'spawn', side_effect=lose):
                    with self.assertRaises(RuntimeError):
                        self.launch(host, attempt=name)
                record = self.settle(host, attempt=name)
                self.assertEqual(record['session'], calls[0])
                self.assertEqual(len(self.runs()), 1)
                # A request directory left half-written by a killed spawn is completed, not duplicated.
                directory = host.directory / record['session']['request_id']
                (directory / 'session.json').unlink()
                (directory / 'launch.json').unlink()
                self.assertIsNone(host.lookup(record['request']))
                self.assertEqual(host.spawn(record['request']), record['session'])
                self.assertEqual(len(self.runs()), 1)

    def test_foreign_request_is_never_adopted(self):
        host = self.transport('claude')
        record = self.settle(host)
        with self.assertRaisesRegex(CardineError, 'foreign host request'):
            host.lookup(dict(record['request'], source='0' * 40))
        with self.assertRaisesRegex(CardineError, 'plain name'):
            host.lookup(dict(record['request'], request_id='../escape'))

    def test_adapter_factory_binds_transport_to_its_own_host(self):
        claude_host, codex_host = self.transport('claude'), self.transport('codex')
        with self.assertRaisesRegex(CardineError, 'does not match'):
            host_adapter('codex', claude_host, 'token')
        with self.assertRaisesRegex(CardineError, 'does not match'):
            host_adapter('unknown', codex_host, 'token')
        self.assertEqual(host_adapter('codex', codex_host, 'token').host, 'codex')


if __name__ == '__main__':
    unittest.main()
