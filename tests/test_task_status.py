"""State-first status regressions and incomplete snapshot diagnostics."""
from task_contract_support import freeze_record
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.tasks.status import load_task_status, render_task_status

ROOT = Path(__file__).resolve().parents[1]


class TaskStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.cardine/tasks').mkdir(parents=True)
        (self.root / 'tasks').mkdir()
        self.configure('lean')

    def configure(self, preset):
        (self.root / '.cardine/project.json').write_text(json.dumps({'version': 1, 'preset': preset}))

    def task(self, task_id, status='queued', dependencies='none', outcome=None):
        steps = {'queued': [], 'in_progress': ['in_progress'], 'in_review': ['in_progress', 'in_review'],
                 'done': ['in_progress', 'done'], 'cancelled': ['cancelled']}[status]
        current = 'queued'
        transitions = []
        for destination in steps:
            transitions.append({'from': current, 'to': destination, 'commit': 'a' * 40,
                                'at': '2026-10-22T00:00:00Z', **({'authority': 'owner', 'reason': 'obsolete'} if destination == 'cancelled' else {})})
            current = destination
        state = {'version': 1, 'task_id': task_id, 'workflow': 'single', 'status': status, 'transitions': transitions}
        if outcome:
            state['outcome'] = outcome
        (self.root / f'.cardine/tasks/{task_id}.json').write_text(json.dumps(state))
        (self.root / f'tasks/{task_id}.md').write_text(f'# Task {task_id}\n\n> **ID**: `{task_id}`\n> **Priority**: P1\n> **Phase**: Build\n\n## Dependencies\n- **Depends on**: {dependencies}\n')
        freeze_record(self.root, task_id, spike=bool(outcome))

    def test_queued_row_with_met_dependencies_and_in_progress_state_is_not_startable(self):
        self.task('001', 'done')
        self.task('002', 'in_progress', '001')
        (self.root / 'tasks/QUEUE.md').write_text('| 002 | queued | 001 |')
        row = load_task_status(self.root)['tasks'][0]
        self.assertFalse(row['startable'])
        self.assertEqual(row['blocked_by'], [])

    def test_queued_row_with_met_dependencies_and_in_review_state_is_not_startable(self):
        self.task('001', 'done')
        self.task('002', 'in_review', '001')
        (self.root / 'tasks/QUEUE.md').write_text('| 002 | queued | 001 |')
        self.assertFalse(load_task_status(self.root)['tasks'][0]['startable'])

    def test_empty_queue_with_done_states_preserves_totals(self):
        self.task('001', 'done')
        (self.root / 'tasks/QUEUE.md').write_text('')
        model = load_task_status(self.root)
        self.assertEqual(model['totals']['done'], 1)
        self.assertEqual(model['tasks'], [])
        self.assertEqual(load_task_status(self.root, all_tasks=True)['tasks'][0]['status'], 'done')

    def test_no_queue_removed_phase_both_presets_and_cancellation(self):
        self.task('001', 'done')
        self.task('002', 'cancelled')
        self.task('003', dependencies='001, 002')
        for preset in ('lean', 'governed'):
            self.configure(preset)
            model = load_task_status(self.root)
            self.assertEqual(model['preset'], preset)
            self.assertEqual(model['totals']['total'], 3)
            self.assertEqual(model['tasks'][0]['blocked_by'], ['002'])
            self.assertFalse(model['tasks'][0]['startable'])
            self.assertEqual(model['diagnostics'], [])

    def test_unborn_main_marks_registration_missing_without_diagnostics(self):
        subprocess.run(['git', '-C', str(self.root), 'init', '-b', 'main'], check=True, capture_output=True)
        self.task('001')
        model = load_task_status(self.root)
        self.assertEqual(model['diagnostics'], [])
        self.assertFalse(model['tasks'][0]['startable'])
        self.assertEqual(set(model['tasks'][0]['registration_missing']),
                         {'tasks/001.md', '.cardine/tasks/001.json'})

    def test_spike_dependencies(self):
        self.task('001', 'done', outcome='ANSWERED')
        self.task('002', 'done', outcome='INCONCLUSIVE')
        self.task('003', dependencies='001')
        self.task('004', dependencies='002')
        rows = load_task_status(self.root)['tasks']
        self.assertTrue(rows[0]['startable'])
        self.assertFalse(rows[1]['startable'])

    def test_invalid_missing_states_and_dependencies(self):
        self.task('001')
        self.task('002', dependencies='001, 999')
        (self.root / '.cardine/tasks/001.json').write_text('{}')
        self.task('003')
        (self.root / '.cardine/tasks/003.json').unlink()
        model = load_task_status(self.root)
        self.assertEqual(model['totals']['queued'], 1)
        self.assertEqual(model['tasks'][0]['blocked_by'], ['001', '999'])
        self.assertGreaterEqual(len(model['diagnostics']), 2)
        self.assertNotIn('003', [row['id'] for row in model['tasks']])  # No registered snapshot.

    def test_cycles_and_duplicate_records(self):
        self.task('001', dependencies='002')
        self.task('002', dependencies='001')
        (self.root / 'tasks/duplicate.md').write_bytes((self.root / 'tasks/001.md').read_bytes())
        model = load_task_status(self.root)
        self.assertTrue(all(not row['startable'] for row in model['tasks']))
        self.assertFalse(any('duplicate' in item['error'] for item in model['diagnostics']))  # Prose duplicates are not identity.
        self.assertTrue(any('cycle' in item['error'] for item in model['diagnostics']))

    def test_cli_counts_filters_and_no_writes(self):
        for number, status in enumerate(('queued', 'in_progress', 'in_review', 'done', 'cancelled'), 1):
            self.task(f'{number:03}', status)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        command = [sys.executable, str(ROOT / 'scripts/cardine_cli.py'), 'status', '--project', str(self.root)]
        text = subprocess.run(command, capture_output=True, text=True, check=True).stdout
        report = json.loads(subprocess.run(command + ['--format', 'json'], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(text.strip(), render_task_status(report))
        for key, value in report['totals'].items():
            self.assertIn(f'{key}={value}', text)
        self.assertEqual(len(report['tasks']), 3)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        (self.root / '.cardine/tasks/001.json').write_text('invalid')
        result = subprocess.run(command + ['--format', 'json'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(json.loads(result.stdout)['diagnostics'])

    def test_changing_snapshot_and_creation_lock(self):
        from cardine.tasks import status
        original = status._inputs
        calls = 0
        def changing(*args):
            nonlocal calls
            calls += 1
            return {**original(*args), self.root / 'volatile': str(calls).encode()}
        with patch.object(status, '_inputs', changing):
            self.assertIn('changed', load_task_status(self.root)['diagnostics'][0]['error'])
        (self.root / '.cardine/task-creation.lock').touch()
        self.assertIn('creation', load_task_status(self.root)['diagnostics'][0]['error'])

    def test_missing_record_priority_and_review_metadata(self):
        self.task('001')
        self.task('002')
        record = self.root / 'tasks/002.md'
        record.write_text(record.read_text().replace('P1', 'P0'))
        state_path = self.root / '.cardine/tasks/002.json'
        state = json.loads(state_path.read_text())
        state['contract']['priority'] = 'P0'
        state['contract']['options']['review'] = 'required'
        state['review'] = {'required': True, 'verdict': 'APPROVE', 'attempt': 1,
                           'reviewed_commit': 'b' * 40, 'approved_by': 'reviewer'}
        state_path.write_text(json.dumps(state))
        rows = load_task_status(self.root)['tasks']
        self.assertEqual(rows[0]['review']['verdict'], 'APPROVE')
        self.assertEqual(rows[0]['review']['reviewed_commit'], 'b' * 40)
        self.assertEqual([row['id'] for row in rows], ['002', '001'])
        self.assertEqual(rows[0]['phase'], 'Build')
        (self.root / 'tasks/001.md').unlink()
        model = load_task_status(self.root)
        self.assertTrue(model['diagnostics'])
        self.assertFalse(next(row for row in model['tasks'] if row['id'] == '001')['startable'])


class BranchStatusDisplayTests(unittest.TestCase):
    setUp = TaskStatusTests.setUp
    configure = TaskStatusTests.configure
    task = TaskStatusTests.task
    def git_display(self, *args, cwd=None):
        return subprocess.run(['git', '-C', str(cwd or self.root), *args],
                              check=True, capture_output=True, text=True).stdout

    def prepare_display_branch(self, main_status='queued', *, run=False):
        self.task('001', main_status)
        if run:
            from project_config_support import write_project_config
            from task_contract_support import contract_record, VALIDATION
            write_project_config(self.root, 'lean', validation=VALIDATION)
            (self.root / 'tasks/001.md').write_text(contract_record())
            freeze_record(self.root, '001')
        self.git_display('init', '-b', 'main')
        self.git_display('config', 'user.name', 'Cardine Test')
        self.git_display('config', 'user.email', 'cardine@example.invalid')
        if run:
            from task_contract_support import seal_state
            with patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.root / 'worktrees')}):
                seal_state(self.root, '001')
        self.git_display('add', '.')
        self.git_display('commit', '-m', 'Register task')
        if run:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/cardine_cli.py'),
                                     'run', '001', '--project', str(self.root)],
                                    env={**os.environ, 'CARDINE_WORKTREE_ROOT': str(self.root / 'worktrees')},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['action'], 'execution-start', report)
            return Path(report['evidence'][0]['path'])
        worktree = self.root / 'worktree'
        self.git_display('worktree', 'add', '-b', 'task-001', str(worktree))
        return worktree

    def display_report(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/cardine_cli.py'),
                                 'status', '--project', str(self.root), '--format', 'json'],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_branch_display_worktree_then_retained_branch(self):
        worktree = self.prepare_display_branch(run=True)
        (worktree / 'uncommitted.txt').write_text('Work in progress\n')
        report = self.display_report()
        row = report['tasks'][0]
        self.assertEqual(row['status'], 'in_progress')
        self.assertFalse(row['startable'])
        self.assertEqual(row['source'], 'task state in worktree task-001')
        self.assertEqual(report['totals']['queued'], 0)
        self.assertEqual(report['totals']['in_progress'], 1)
        self.assertIn('| source: task state in worktree task-001', render_task_status(report))
        self.assertEqual(load_task_status(self.root)['tasks'][0]['status'], 'queued')
        (worktree / 'uncommitted.txt').unlink()
        self.git_display('worktree', 'remove', str(worktree))
        row = self.display_report()['tasks'][0]
        self.assertEqual(row['status'], 'in_progress')
        self.assertEqual(row['source'], 'task state on branch task-001')

    def test_prepared_worktree_and_write_views_are_independent(self):
        worktree = self.prepare_display_branch()
        command = [sys.executable, str(ROOT / 'scripts/cardine_cli.py'),
                   'status', '--project', str(self.root), '--write']
        subprocess.run(command, check=True, capture_output=True)
        queue = (self.root / 'tasks/QUEUE.md').read_bytes()
        self.assertEqual(self.display_report()['tasks'][0]['status'], 'in_progress')
        self.git_display('worktree', 'remove', str(worktree))
        subprocess.run(command, check=True, capture_output=True)
        self.assertEqual((self.root / 'tasks/QUEUE.md').read_bytes(), queue)
        self.assertNotIn('source', self.display_report()['tasks'][0])

    def test_invalid_branch_state_is_ignored(self):
        worktree = self.prepare_display_branch()
        path = worktree / '.cardine/tasks/001.json'
        for content in ('{', 'null', '{}', '{"status":"in_progress"}', '[]'):
            with self.subTest(content=content):
                path.write_text(content)
                report = self.display_report()
                self.assertEqual(report['tasks'][0]['status'], 'queued')
                self.assertNotIn('source', report['tasks'][0])
                self.assertEqual(report['diagnostics'], [])
        self.git_display('add', '.', cwd=worktree)
        self.git_display('commit', '-m', 'Invalid advisory state', cwd=worktree)
        self.git_display('worktree', 'remove', str(worktree))
        self.assertNotIn('source', self.display_report()['tasks'][0])

    def test_branch_never_regresses_or_cancels_main(self):
        from task_state_support import set_state
        worktree = self.prepare_display_branch('in_review')
        for status in ('queued', 'in_progress', 'cancelled'):
            with self.subTest(status=status):
                set_state(worktree, '001', status, required=False)
                row = self.display_report()['tasks'][0]
                self.assertEqual(row['status'], 'in_review')
                self.assertNotIn('source', row)
