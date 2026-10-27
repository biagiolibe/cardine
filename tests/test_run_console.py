"""Verified console previews, explicit actions and untrusted flow history."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from cardine.console.snapshot import load_snapshot
from cardine.hosts.launch import launch_run_request, CodexProfileAdapter
from cardine.lifecycle import receipts
from cardine.lifecycle.context import resolve_run_locations
from cardine.lifecycle.preview import preview_run
from cardine.shared.errors import CardineError
from cardine.shared.flow import flow_report, format_flow_report
from cardine.tasks.identity import read_task_identity_policy
import test_run_delivery
from test_run_host_roles import FakeHost, HOST_POINTS

ROOT = Path(__file__).resolve().parents[1]


class RunConsoleTest(unittest.TestCase):
    def setUp(self):
        self.fixture = test_run_delivery.RunDeliveryTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.worker = self.fixture.worker
        self.locations = resolve_run_locations('001', self.worker)

    def preview(self):
        return preview_run(self.locations)

    def test_preview_and_render_are_repeatable_without_writes_or_effects(self):
        from cardine.console.state import one_shot
        from cardine.console.render import _detail_lines
        from cardine.console.models import Task
        from types import SimpleNamespace
        before = self.fixture.state()
        with patch.object(receipts, '_durable', side_effect=AssertionError('preview wrote')):
            first = self.preview()
            self.assertEqual(first, self.preview())
            self.assertEqual(first['step'], 'implementation')
            task = Task('001', 'Example', 'in_progress', (), (), None, (), (),
                        legacy=False, run_preview=first)
            palette = dict.fromkeys(('base', 'text', 'title', 'muted', 'blocked', 'working',
                                     'ready', 'review', 'done', 'warning', 'accent', 'unknown', 'action', 'line'), 0)
            _detail_lines(task, 100, palette)
        self.assertEqual(self.fixture.state(), before)
        self.assertTrue(task.launch_command.startswith('cardine run 001 --project '))

    def test_delivery_selects_validation_and_forged_state_never_selects_a_step(self):
        self.fixture.deliver()
        self.assertEqual(self.preview()['step'], 'validation')
        path = self.worker / '.cardine/tasks/001.json'
        state = json.loads(path.read_bytes())
        state['status'] = 'done'
        path.write_text(json.dumps(state))
        self.assertEqual(self.preview()['outcome'], 'blocked')

    def test_journal_and_targets_cannot_change_preview_or_verified_observations(self):
        expected = self.preview()
        journal = self.locations.common_dir / 'cardine-journal.jsonl'
        journal.write_text(json.dumps(dict(version=1, ts='2026-10-01T12:00:00Z',
            task='001', command='integrate finalize', result='ok')) + '\n')
        (self.fixture.root / '.cardine/flow-targets.json').write_text(json.dumps(dict(version=1,
            friction_share=dict(window=1, max_percent=100))))
        self.assertEqual(self.preview(), expected)
        report = flow_report(self.fixture.root, None)
        self.assertEqual(report['telemetry_verification'], 'unverifiable')
        self.assertTrue(all(t['verification'] == 'unverifiable' for t in report['tasks']))
        self.assertTrue(all(t['verification'] == 'unverifiable' for t in report['targets']))
        self.assertIn('Historical telemetry: unverifiable', format_flow_report(report))
        self.assertEqual(report['observations'][0]['verification'], 'receipt-verified')

    def test_product_never_reads_old_identity_policy_without_declaration(self):
        root = self.fixture.root
        (root / '.cardine/project.json').unlink()
        (root / '.cardine/task-identity.json').write_text('{"version":1,"mode":"milestone"}')
        self.assertEqual(read_task_identity_policy(root).mode, 'opaque')

    def test_console_launch_adapter_repeats_the_same_issued_session(self):
        request = self.preview()['work']
        host = FakeHost(self.worker.parent / 'console-host', 'codex')
        adapter = CodexProfileAdapter(host, 'coordinator-channel')
        first = launch_run_request(self.locations, request, adapter=adapter)
        before = self.fixture.state()
        self.assertEqual(launch_run_request(self.locations, request, adapter=adapter), first)
        self.assertEqual(self.fixture.state(), before)
        self.assertEqual(len(list(host.directory.iterdir())), 1)

    def test_launch_interruption_reuses_request_session_and_response(self):
        points = [(point, 1) for point in HOST_POINTS]
        points += [('after_intent', phase) for phase in (1, 2, 3)]
        for index, (point, phase) in enumerate(points):
            if index:
                self.doCleanups()
                self.setUp()
            host_path = self.worker.parent / 'console-host'
            script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.lifecycle.context import resolve_run_locations
from cardine.lifecycle.preview import preview_run
from cardine.hosts.launch import launch_run_request, CodexProfileAdapter
from test_run_host_roles import FakeHost
locations = resolve_run_locations('001', Path(sys.argv[1]))
preview = preview_run(locations)
request = preview['work']
assert request is not None, preview
seen = 0
def kill(name):
    global seen
    if name == sys.argv[3]:
        seen += 1
        if seen == int(sys.argv[4]): os._exit(77)
receipts.boundary = kill
launch_run_request(locations, request,
    adapter=CodexProfileAdapter(FakeHost(sys.argv[2], 'codex'), 'coordinator-channel'))
'''
            with self.subTest(point=point, phase=phase):
                result = subprocess.run([sys.executable, '-c', script, str(self.worker),
                    str(host_path), point, str(phase)], capture_output=True, text=True,
                    env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(ROOT / 'src'), str(ROOT / 'tests')])})
                self.assertEqual(result.returncode, 77, result.stderr)
                request = self.preview()['work']
                self.assertIsNotNone(request, self.preview())
                adapter = CodexProfileAdapter(FakeHost(host_path, 'codex'), 'coordinator-channel')
                resumed = launch_run_request(self.locations, request, adapter=adapter)
                self.assertEqual(launch_run_request(self.locations, request, adapter=adapter), resumed)
                self.assertEqual(len(list(host_path.iterdir())), 1)

    def test_changed_inputs_and_foreign_session_fail_closed(self):
        request = self.preview()['work']
        host = FakeHost(self.worker.parent / 'console-host', 'codex')
        adapter = CodexProfileAdapter(host, 'coordinator-channel')
        launch_run_request(self.locations, request, adapter=adapter)
        foreign = deepcopy(request)
        foreign['worktree'] = str(self.fixture.root)
        with self.assertRaises(CardineError):
            launch_run_request(self.locations, foreign, adapter=adapter)
        host.ready = False
        path = self.worker / 'src/result.py'
        path.write_text(path.read_text() + '# changed\n')
        # A new source cannot consume an old request's completed result.
        updated = launch_run_request(self.locations, request, adapter=adapter)
        self.assertIsNone(updated['response'])
        self.assertEqual(len(list(host.directory.iterdir())), 2)

    def test_stale_genuine_delivery_returns_to_implementation(self):
        self.fixture.deliver()
        self.assertEqual(self.preview()['step'], 'validation')
        path = self.worker / 'src/result.py'
        path.write_text(path.read_text() + '# new source\n')
        self.assertEqual(self.preview()['step'], 'implementation')

    def test_uncovered_terminal_state_cannot_hide_a_task_or_inflate_totals(self):
        from task_state_support import build_state
        path = self.fixture.root / '.cardine/tasks/001.json'
        original = json.loads(path.read_bytes())
        forged = build_state('001', 'done')
        forged.update(contract=original['contract'], run=original['run'])
        path.write_text(json.dumps(forged))
        snapshot = load_snapshot(self.fixture.root)
        self.assertEqual(dict(snapshot.totals)['done'], 0)
        self.assertEqual(snapshot.tasks[0].task_id, '001')
        self.assertIsNotNone(snapshot.tasks[0].state_error)
        self.assertIsNone(snapshot.tasks[0].launch_command)

    def test_forged_policy_invalidates_observations_without_legacy_fallback(self):
        policy = self.fixture.root / '.cardine/project.json'
        value = json.loads(policy.read_bytes())
        value['taskIdentity'] = {'mode': 'milestone'}
        policy.write_text(json.dumps(value))
        self.assertEqual(self.preview()['outcome'], 'blocked')
        report = flow_report(self.fixture.root, None)
        self.assertTrue(all(item['verification'] == 'unverifiable' for item in report['observations']))

    def test_preview_uses_only_read_commands_and_does_not_refresh_indexes(self):
        from cardine.shared import git
        run = subprocess.run
        indexes = [self.locations.common_dir / 'index',
                   Path((self.worker / '.git').read_text().strip().removeprefix('gitdir: ')) / 'index']
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in indexes]
        def inspect(argv, *args, **kwargs):
            if argv[0] == 'git':
                arguments = argv[3:] if argv[1:2] == ['-C'] else argv[1:]
                self.assertTrue(git._read_only(arguments), argv)
                self.assertEqual(kwargs['env']['GIT_OPTIONAL_LOCKS'], '0')
            return run(argv, *args, **kwargs)
        with patch.object(git.subprocess, 'run', side_effect=inspect):
            self.preview()
            load_snapshot(self.fixture.root)
        self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in indexes], before)

    def test_console_actions_use_stable_controls_and_missing_host_has_no_effect(self):
        from cardine.console.launch import _launch_selected
        from types import SimpleNamespace
        task = load_snapshot(self.fixture.root).tasks[0]
        state = SimpleNamespace(project=self.fixture.root)
        before = self.fixture.state()
        with patch('cardine.lifecycle.control.host_adapter', return_value=None):
            self.assertFalse(_launch_selected(state, task, 'codex', True)[0])
        self.assertEqual(self.fixture.state(), before)
        adapter = CodexProfileAdapter(FakeHost(self.worker.parent / 'actions', 'codex'), 'developer-channel')
        with patch('cardine.lifecycle.control.host_adapter', return_value=adapter), \
             patch('cardine.lifecycle.control.cancel_task') as cancel, \
             patch('cardine.lifecycle.control_abort.abort_owned') as abort:
            self.assertTrue(_launch_selected(state, task, 'codex', True, 'cancel')[0])
            cancel.assert_called_once_with('001', self.fixture.root,
                reason='Cancelled from the console', adapter=adapter)
            self.assertTrue(_launch_selected(state, task, 'codex', True, 'abort')[0])
            abort.assert_called_once_with('001', self.fixture.root, adapter=adapter)

    def test_candidate_preview_checks_the_index_without_writing_a_tree(self):
        import test_run_integration
        fixture = test_run_integration.CandidateTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        fixture.ready()
        fixture.run_candidate()
        locations = resolve_run_locations('056', fixture.primary)
        from cardine.shared import git
        run = git._run_git
        def inspect(root, *args, **kwargs):
            self.assertNotIn('write-tree', args)
            return run(root, *args, **kwargs)
        with patch('cardine.integration.candidate._run_git', side_effect=inspect), \
             patch.object(receipts, '_durable', side_effect=AssertionError('preview wrote')):
            result = preview_run(locations)
            self.assertEqual(result['step'], 'landing', result)
            self.assertEqual(preview_run(locations), result)

    def test_finalized_and_cleaned_preview_never_repeats_delivery(self):
        import test_run_cleanup
        fixture = test_run_cleanup.CleanupTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        with patch.object(receipts, '_durable', side_effect=AssertionError('preview wrote')):
            result = preview_run(fixture.locations)
            self.assertEqual((result['step'], result['outcome']), ('landing', 'next'), result)
        fixture.finish()
        with patch.object(receipts, '_durable', side_effect=AssertionError('preview wrote')):
            result = preview_run(fixture.locations)
            self.assertEqual(result['outcome'], 'done', result)
            self.assertEqual(preview_run(fixture.locations), result)

    def test_failed_candidate_previews_implementation_remediation(self):
        import test_run_integration
        fixture = test_run_integration.CandidateTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        fixture.ready('exit 7')
        fixture.run_candidate()
        result = preview_run(resolve_run_locations('056', fixture.primary))
        self.assertEqual((result['step'], result['outcome']), ('implementation', 'iterate'), result)

    def test_cleanup_stays_visible_after_worktree_unregistration_without_rendering_effects(self):
        import test_run_cleanup
        fixture = test_run_cleanup.CleanupTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        def interrupt(name):
            if name == 'after_cleanup_worktree':
                raise RuntimeError('interrupted cleanup')
        with patch.object(receipts, 'boundary', side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, 'interrupted cleanup'):
                fixture.finish()
        with patch.object(receipts, '_durable', side_effect=AssertionError('snapshot wrote')):
            snapshot = load_snapshot(fixture.primary)
            task = next(task for task in snapshot.tasks if task.task_id == '056')
            self.assertEqual(task.run_preview['step'], 'landing')
            self.assertEqual(task.lifecycle, 'closing')
            self.assertEqual(snapshot.done_count, 0)
            self.assertEqual(load_snapshot(fixture.primary), snapshot)
        fixture.finish()
        self.assertNotIn('056', [task.task_id for task in load_snapshot(fixture.primary).tasks])
