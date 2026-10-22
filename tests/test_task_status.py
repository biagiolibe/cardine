"""State-first status regressions and incomplete snapshot diagnostics."""
import json
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
        self.assertGreaterEqual(len(model['diagnostics']), 3)

    def test_cycles_and_duplicate_records(self):
        self.task('001', dependencies='002')
        self.task('002', dependencies='001')
        (self.root / 'tasks/duplicate.md').write_bytes((self.root / 'tasks/001.md').read_bytes())
        model = load_task_status(self.root)
        self.assertTrue(all(not row['startable'] for row in model['tasks']))
        self.assertTrue(any('duplicate' in item['error'] for item in model['diagnostics']))
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
