"""Real Git start/delivery boundaries and read-only console availability."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import meridian
import project_console


class ExecutionBoundariesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.primary = Path(self.temp.name) / 'project'
        self.primary.mkdir()
        self.git('init', '-q', '-b', 'main', cwd=self.primary)
        self.git('config', 'user.name', 'Test', cwd=self.primary)
        self.git('config', 'user.email', 'test@example.invalid', cwd=self.primary)
        (self.primary / 'PROJECT_WORKFLOW.md').write_text('GOVERNED_SDD\n')
        (self.primary / 'tasks').mkdir()
        (self.primary / 'docs').mkdir()
        (self.primary / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_text('profile\n')
        (self.primary / 'tasks/QUEUE.md').write_text('| Status | ID | Title | Priority | Depends on | File |\n|---|---|---|---|---|---|\n| QUEUED | 001 | Example | P2 | — | [task](001.md) |\n')
        self.record = Path('tasks/001.md')
        text = '# Task 001 — Example\n\n> **ID**: `001`\n\nStatus: QUEUED\nClass: NORMAL\nReview: REQUIRED\n\n## Authority\n\n## Expected code surface\n\n## Validation\n\n- `check`: `true`\n'
        (self.primary / self.record).write_text(text)
        text += meridian.execution_contract(self.primary, '001') + '\n'
        (self.primary / self.record).write_text(text)
        self.git('add', '.', cwd=self.primary)
        self.git('commit', '-qm', 'Initial', cwd=self.primary)
        self.oldcwd = Path.cwd()
        os.chdir(self.primary)
        self.addCleanup(os.chdir, self.oldcwd)
        self.env = mock.patch.dict(os.environ, {'MERIDIAN_WORKTREE_ROOT': str(Path(self.temp.name) / 'worktrees')})
        self.env.start()
        self.addCleanup(self.env.stop)
        prepared = meridian.prepare_task_worktree('001', None, self.primary)
        self.worker = Path(prepared['worktree'])
        os.chdir(self.worker)

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.worker, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, subject):
        self.git('add', '.')
        self.git('commit', '-qm', subject)

    def state(self):
        return json.loads((self.worker / '.meridian/tasks/001.json').read_text())

    def assert_stop(self, code, action):
        with self.assertRaises(meridian.MeridianStop) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def implemented(self):
        meridian.execution_start(self.worker, '001')
        (self.worker / 'feature.txt').write_text('implementation\n')
        meridian.run_validation(self.worker, '001', 'check')
        self.commit('Implement feature and validation')
        identity = meridian.resolve_task_identity(self.worker, '001', 'existing')
        identity.handoff_path.parent.mkdir(parents=True, exist_ok=True)
        identity.handoff_path.write_text('## Completion Report — 001\n\n' + '\n'.join(
            '- ' + field + ': ' + ('none' if field in ('Validation skips', 'Isolated exploration') else 'complete')
            for field in meridian.HANDOFF_FIELDS) + '\n')
        with identity.handoff_path.open('a') as report:
            report.write('- Current task commit: `Deliver 001 for review`\n')
        self.commit('Finalize handoff')
        return identity

    def test_first_and_repeated_start_preserve_original_event_and_projections(self):
        before = self.git('rev-parse', 'HEAD')
        result = meridian.execution_start(self.worker, '001')
        state = self.state()
        self.assertEqual(result['status'], 'IN_PROGRESS')
        self.assertEqual(state['transitions'][0]['commit'], before)
        self.assertTrue(state['transitions'][0]['at'].endswith('Z'))
        meridian.execution_start(self.worker, '001')
        self.assertEqual(self.state(), state)
        self.assertIn('Status: IN_PROGRESS', (self.worker / self.record).read_text())
        self.assertIn('| QUEUED |', (self.worker / 'tasks/QUEUE.md').read_text())
        task = project_console.load_snapshot(self.primary).tasks[0]
        self.assertEqual(task.status, 'IN_PROGRESS')
        self.assertEqual(task.started_at, state['transitions'][0]['at'])

    def test_resume_preserves_history_and_requires_explicit_dirty_authorization(self):
        meridian.execution_start(self.worker, '001')
        self.commit('Start')
        original = self.state()
        (self.worker / 'feature.txt').write_text('partial\n')
        self.assert_stop('WRONG_WORKTREE', lambda: meridian.execution_start(self.worker, '001'))
        meridian.execution_start(self.worker, '001', resume=True)
        self.assertEqual(self.state(), original)

    def test_preflight_and_worktree_failures_do_not_write_start(self):
        text = (self.worker / self.record).read_text()
        (self.worker / self.record).write_text(text.replace('Profile revision:', 'Missing revision:'))
        self.commit('Unresolved contract')
        self.assert_stop('EXECUTION_CONTRACT_UNRESOLVED', lambda: meridian.execution_start(self.worker, '001'))
        self.assertFalse((self.worker / '.meridian/tasks/001.json').exists())
        os.chdir(self.primary)
        self.assert_stop('WRONG_WORKTREE', lambda: meridian.execution_start(self.primary, '001'))
        self.assertFalse((self.primary / '.meridian/tasks/001.json').exists())

    def test_lean_start_is_read_only_and_preserves_machine(self):
        (self.worker / 'PROJECT_WORKFLOW.md').write_text('LEAN_DELIVERY\n')
        self.commit('Select Lean')
        before = self.git('status', '--porcelain')
        result = meridian.execution_start(self.worker, '001')
        self.assertEqual(result['status'], 'QUEUED')
        self.assertFalse(result['started'])
        self.assertFalse((self.worker / '.meridian/tasks/001.json').exists())
        self.assertEqual(self.git('status', '--porcelain'), before)

    def test_delivery_commits_only_owned_projections_and_is_idempotent(self):
        identity = self.implemented()
        before = self.git('rev-parse', 'HEAD')
        result = meridian.execution_deliver(self.worker, '001')
        self.assertEqual(result['status'], 'READY_FOR_REVIEW')
        self.assertTrue(result['clean'])
        self.assertEqual(set(self.git('diff', '--name-only', before, 'HEAD').splitlines()),
                         {'.meridian/tasks/001.json', 'tasks/001.md'})
        state = self.state()
        self.assertEqual(state['transitions'][-1]['commit'], before)
        self.assertEqual(meridian.execution_deliver(self.worker, '001'), result)
        self.assertEqual(self.state(), state)
        task = project_console.load_snapshot(self.primary).tasks[0]
        self.assertEqual(task.launch_command, 'Review 001')
        (self.worker / 'feature.txt').write_text('later changes\n')
        task = project_console.load_snapshot(self.primary).tasks[0]
        self.assertEqual(task.status, 'READY_FOR_REVIEW')
        self.assertEqual(task.readiness, 'PENDING DELIVERY/CHANGES')
        self.assertIsNone(task.launch_command)

    def test_handoff_only_corrections_redeliver_twice_without_new_transitions(self):
        identity = self.implemented()
        meridian.execution_deliver(self.worker, '001')
        original = self.state()
        for correction in ('First', 'Second'):
            delivered = self.git('rev-parse', 'HEAD')
            with identity.handoff_path.open('a') as report:
                report.write(f'\n{correction} correction.\n')
            self.commit(f'{correction} handoff correction')
            corrected = self.git('rev-parse', 'HEAD')
            self.assert_stop('EVIDENCE_INCOMPLETE', lambda: meridian.delivery_readiness(self.worker, '001'))
            result = meridian.execution_deliver(self.worker, '001')
            self.assertNotEqual(result['commit'], delivered)
            self.assertNotEqual(result['commit'], corrected)
            self.assertEqual(self.git('rev-parse', 'HEAD^'), corrected)
            self.assertEqual(self.git('log', '-1', '--format=%s'), 'Deliver 001 for review')
            self.assertEqual(self.git('diff', '--name-only', 'HEAD^', 'HEAD'), '')
            self.assertEqual(self.state(), original)
            self.assertEqual(meridian.delivery_readiness(self.worker, '001'), result)
            self.assertEqual(meridian.execution_deliver(self.worker, '001'), result)
            self.assertEqual(self.git('status', '--porcelain'), '')

    def reject_later_change(self, relative):
        self.implemented()
        meridian.execution_deliver(self.worker, '001')
        path = self.worker / relative
        before = path.read_text()
        # Whitespace keeps JSON and task projections valid.
        path.write_text(before + '\n')
        self.commit('Later non-handoff change')
        self.assert_stop('EVIDENCE_INCOMPLETE', lambda: meridian.execution_deliver(self.worker, '001'))
        path.write_text(before)
        self.commit('Restore original contents')
        self.assert_stop('EVIDENCE_INCOMPLETE', lambda: meridian.execution_deliver(self.worker, '001'))

    def test_later_implementation_change_is_rejected_even_if_reverted(self):
        self.reject_later_change('feature.txt')

    def test_later_task_record_change_is_rejected_even_if_reverted(self):
        self.reject_later_change('tasks/001.md')

    def test_later_execution_evidence_change_is_rejected_even_if_reverted(self):
        self.reject_later_change('.meridian/execution-evidence.json')

    def test_later_state_file_change_is_rejected_even_if_reverted(self):
        self.reject_later_change('.meridian/tasks/001.json')

    def test_current_commit_field_is_checked_before_first_delivery(self):
        identity = self.implemented()
        report = identity.handoff_path
        original = report.read_text()
        base = self.git('rev-parse', 'main')
        cases = ('', f'- Current task commit: `{base}`\n',
                 '- Current task commit: the task commit (see git log -1 task-001)\n')
        for field in cases:
            with self.subTest(field=field):
                report.write_text(original.replace('- Current task commit: `Deliver 001 for review`\n', field))
                self.commit('Malformed handoff fixture')
                head = self.git('rev-parse', 'HEAD')
                for action in (meridian.delivery_readiness, meridian.execution_deliver):
                    with self.assertRaises(meridian.MeridianStop) as caught:
                        action(self.worker, '001')
                    self.assertEqual(caught.exception.code, 'EVIDENCE_INCOMPLETE')
                    self.assertIn('Current task commit', str(caught.exception))
                    self.assertIn('subject', str(caught.exception))
                    self.assertEqual(self.git('rev-parse', 'HEAD'), head)
                    self.assertEqual(self.state()['status'], 'IN_PROGRESS')

    def test_dirty_incomplete_stale_and_direct_transition_cannot_deliver(self):
        meridian.execution_start(self.worker, '001')
        self.assert_stop('WRONG_WORKTREE', lambda: meridian.transition_task_state(self.worker, '001', 'READY_FOR_REVIEW'))
        self.assertEqual(self.state()['status'], 'IN_PROGRESS')
        self.commit('Start')
        self.assert_stop('HANDOFF_REPORT_MISSING', lambda: meridian.execution_deliver(self.worker, '001'))
        self.implemented()
        (self.worker / 'feature.txt').write_text('changed after validation\n')
        self.commit('Change code')
        self.assert_stop('EVIDENCE_INCOMPLETE', lambda: meridian.execution_deliver(self.worker, '001'))
        self.assertEqual(self.state()['status'], 'IN_PROGRESS')
        self.assert_stop('EVIDENCE_INCOMPLETE', lambda: meridian.transition_task_state(self.worker, '001', 'READY_FOR_REVIEW'))

    def test_commit_failure_reports_pending_actual_state_and_recovers(self):
        self.implemented()
        run = meridian._run_git
        def fail_commit(root, *args):
            if args[0] == 'commit':
                return subprocess.CompletedProcess(args, 1, '', 'test commit failure')
            return run(root, *args)
        with mock.patch.object(meridian, '_run_git', side_effect=fail_commit):
            self.assert_stop('EVIDENCE_INCOMPLETE', lambda: meridian.execution_deliver(self.worker, '001'))
        self.assertEqual(self.state()['status'], 'READY_FOR_REVIEW')
        task = project_console.load_snapshot(self.primary).tasks[0]
        self.assertIsNone(task.launch_command)
        self.assertEqual(task.readiness, 'PENDING DELIVERY/CHANGES')
        self.commit('Deliver 001 for review')
        self.assertTrue(meridian.execution_deliver(self.worker, '001')['clean'])

    def test_terminal_and_remediation_states_never_restart(self):
        self.implemented()
        meridian.execution_deliver(self.worker, '001')
        original = self.state()
        self.assert_stop('TASK_STATUS_REJECTED', lambda: meridian.execution_start(self.worker, '001'))
        self.assertEqual(self.state(), original)
        meridian.record_review_verdict(self.worker, '001', 'CHANGES_REQUESTED', body='Fix code')
        self.commit('Request changes')
        self.assert_stop('TASK_STATUS_REJECTED', lambda: meridian.execution_start(self.worker, '001'))
        meridian.transition_task_state(self.worker, '001', 'IN_PROGRESS')
        self.commit('Begin remediation')
        meridian.run_validation(self.worker, '001', 'check')
        self.commit('Renew evidence')
        meridian.execution_deliver(self.worker, '001')
        meridian.record_review_verdict(self.worker, '001', 'APPROVE', body='Approved')
        self.commit('Approve')
        self.assert_stop('TASK_STATUS_REJECTED', lambda: meridian.execution_start(self.worker, '001'))

    def test_incomplete_and_uncommitted_handoff_never_publish_ready(self):
        identity = self.implemented()
        identity.handoff_path.write_text('## Completion Report — 001\n')
        self.assert_stop('WRONG_WORKTREE', lambda: meridian.execution_deliver(self.worker, '001'))
        self.commit('Incomplete handoff')
        self.assert_stop('HANDOFF_FIELDS_MISSING', lambda: meridian.execution_deliver(self.worker, '001'))
        self.assertEqual(self.state()['status'], 'IN_PROGRESS')

    def test_cli_boundaries_and_ready_check_are_committed_and_read_only(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/meridian.py'
        def cli(operation):
            return subprocess.run([sys.executable, str(script), 'execution', operation, '001',
                                   '--project', str(self.worker)], cwd=self.worker,
                                  capture_output=True, text=True)
        started = cli('start')
        self.assertEqual(started.returncode, 0, started.stderr)
        self.implemented()
        delivered = cli('deliver')
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        head = self.git('rev-parse', 'HEAD')
        self.assertEqual(json.loads(delivered.stdout)['commit'], head)
        checked = cli('ready-check')
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_invalid_machine_state_stops_without_repair_or_start(self):
        path = self.worker / '.meridian/tasks/001.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{invalid JSON')
        self.commit('Invalid state fixture')
        before = path.read_bytes()
        self.assert_stop('TASK_STATE_INVALID', lambda: meridian.execution_start(self.worker, '001'))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_review_not_required_keeps_its_terminal_path(self):
        record = self.worker / self.record
        record.write_text(record.read_text().replace('Review: REQUIRED', 'Review: NOT_REQUIRED'))
        self.commit('No review policy')
        meridian.execution_start(self.worker, '001')
        meridian.transition_task_state(self.worker, '001', 'ACCEPTED')
        self.assertEqual(self.state()['status'], 'ACCEPTED')
        self.assert_stop('TASK_STATUS_REJECTED', lambda: meridian.execution_deliver(self.worker, '001'))

    def test_spike_start_and_close_never_fabricate_review(self):
        record = self.worker / self.record
        text = record.read_text().replace('Class: NORMAL', 'Class: SPIKE')
        text += '\nQuestion: Does the probe pass?\nBudget: 1 iteration\nDeliverable: `answer.md`\n'
        record.write_text(text)
        self.commit('Spike policy')
        meridian.execution_start(self.worker, '001')
        meridian.transition_task_state(self.worker, '001', 'ANSWERED')
        self.assertEqual(self.state()['status'], 'ANSWERED')
        self.assert_stop('TASK_STATUS_REJECTED', lambda: meridian.execution_start(self.worker, '001', resume=True))

    def external_lifecycle(self, location):
        directory = self.primary if location == 'primary' else Path(self.temp.name)
        if location == 'worker':
            directory = self.worker
        os.chdir(directory)
        before = self.git('rev-parse', 'HEAD')
        started = meridian.execution_start(self.worker, '001')
        self.assertEqual(started['commit'], before)
        self.assertEqual(self.state()['transitions'][0]['commit'], before)
        # Exercise a relative file write in the actual validation subprocess.
        record = self.worker / self.record
        record.write_text(record.read_text().replace('`true`', '`pwd > validation-directory.txt`'))
        self.commit('Declare directory validation')
        self.assertEqual(meridian.run_validation(self.worker, '001', 'check'), 0)
        self.assertEqual((self.worker / 'validation-directory.txt').read_text().strip(), str(self.worker))
        self.commit('Record validation')
        self.implemented()
        before = self.git('rev-parse', 'HEAD')
        delivered = meridian.execution_deliver(self.worker, '001')
        self.assertEqual(delivered['status'], 'READY_FOR_REVIEW')
        self.assertEqual(self.git('rev-parse', 'HEAD^'), before)
        self.assertEqual(self.git('log', '-1', '--format=%s'), 'Deliver 001 for review')
        self.assertEqual(set(self.git('diff', '--name-only', before, 'HEAD').splitlines()),
                         {'.meridian/tasks/001.json', 'tasks/001.md'})
        self.assertEqual(meridian.execution_deliver(self.worker, '001'), delivered)
        self.assertEqual(Path.cwd(), directory.resolve())
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_lifecycle_from_primary(self):
        self.external_lifecycle('primary')

    def test_lifecycle_from_unrelated_directory(self):
        self.external_lifecycle('unrelated')

    def test_lifecycle_from_worker_comparison(self):
        self.external_lifecycle('worker')

    def test_wrong_project_cli_preserves_arguments_and_names_paths(self):
        import shlex
        script = Path(__file__).resolve().parents[1] / 'scripts/meridian.py'
        other = Path(self.temp.name) / 'other task'
        self.git('worktree', 'add', '-qb', 'task-002', str(other), cwd=self.primary)
        stale = self.primary / 'stale-worktree'
        for project in (self.primary, other, stale):
            for command in (['execution', 'start', '001', '--resume', '--format', 'json'],
                            ['execution', 'deliver', '001'],
                            ['task', 'close', '001', '--format', 'json']):
                with self.subTest(project=project, command=command):
                    result = subprocess.run([sys.executable, str(script), *command,
                                             '--project=' + str(project)], cwd=self.worker,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stdout)
                    detail = (f'cwd={self.worker}; --project={project}; '
                              + (f'resolved project={project.resolve()}; ' if project != project.resolve() else '')
                              + f'expected worktree={self.worker}; --project does not name the canonical task worktree')
                    resume = shlex.join(['meridian', *command, '--project', str(self.worker)])
                    self.assertEqual(result.stderr.strip(), f'BLOCKED WRONG_WORKTREE: {detail}; resume: {resume}')
        self.assertFalse((self.worker / '.meridian/tasks/001.json').exists())
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_no_registered_worktree_keeps_prepare_resume(self):
        import shlex
        os.chdir(self.primary)
        self.git('worktree', 'remove', str(self.worker), cwd=self.primary)
        for action in (meridian.execution_start, meridian.close_task):
            with self.assertRaises(meridian.MeridianStop) as caught:
                action(self.primary, '001')
            detail = (f'cwd={self.primary.resolve()}; --project={self.primary.resolve()}; expected worktree={self.worker}; '
                      'no registered task worktree')
            resume = f'meridian worktree prepare 001 --project {shlex.quote(str(self.primary.resolve()))} --format json'
            self.assertEqual(str(caught.exception), f'BLOCKED WRONG_WORKTREE: {detail}; resume: {resume}')

    def test_instruction_ordering_and_skill_parity(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md').read_text()
        self.assertLess(text.index('worktree check'), text.index('execution start'))
        self.assertLess(text.index('execution start'), text.index('advisor consultation'))
        for host in ('meridian-governed-sdd', 'meridian-governed-sdd-claude-code'):
            skill = (root / 'skills' / host / 'SKILL.md').read_text().split('capability=execution-boundaries v1 -->')[1]
            self.assertIn('execution start', skill)
            self.assertIn('execution deliver', skill)
        orchestration = (root / 'templates/workflows/governed-sdd/docs/LIFECYCLE_ORCHESTRATION.md').read_text()
        self.assertIn('execution start', orchestration)
        self.assertIn('execution deliver', orchestration)
