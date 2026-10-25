"""Evidence from concurrent tasks integrates without a shared JSON conflict."""

import json
from pathlib import Path
import unittest

import worktree_support as support
from task_contract_support import contract_record, write_state
from cardine.tasks.recording import record_validation
from cardine.worktree.checkout import prepare_task_worktree
from cardine.integration.merge import stage_task_integration, finalize_task_integration
from cardine.shared.errors import CardineError


class PerTaskEvidenceIntegrationTest(support.BoundedWorktreeLifecycleFixture):
    def prepare_pair(self, *, conflict=False):
        record = self.primary / 'tasks/057-lifecycle.md'
        record.write_text(contract_record('057').replace('Change the documented deliverable only.', '- `**`'))
        write_state(self.primary, '057', 'in_progress', review_required=False)
        queue = self.primary / 'tasks/QUEUE.md'
        queue.write_text(queue.read_text() + '| `[ ]` | 057 | Second task |\n')
        plan = self.primary / 'PROJECT_PLAN.md'
        plan.write_text(plan.read_text() + '- `[ ]` 057 — Second task\n')
        self.git('add', '.')
        self.git('commit', '-m', 'declare concurrent task')
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()
        workers = {}
        for task_id in ('056', '057'):
            prepared = prepare_task_worktree(task_id, self.worktree_root, self.primary)
            worker = Path(prepared['worktree'])
            other_id = '057' if task_id == '056' else '056'
            with self.assertRaisesRegex(CardineError, 'WRONG_WORKTREE'):
                record_validation(worker, other_id, 'foreign', 'false', 1)
            self.assertFalse((worker / f'.cardine/evidence/{other_id}.json').exists())
            (worker / f'feature-{task_id}.txt').write_text(f'task {task_id}\n')
            if conflict:
                (worker / 'README.md').write_text(f'Changed by {task_id}\n')
            self.git('add', '.', cwd=worker)
            self.git('commit', '-m', f'implement {task_id}', cwd=worker)
            self.measure(worker, task_id)
            workers[task_id] = worker
        return workers

    def stage(self, task_id, worker):
        return stage_task_integration(task_id, self.worktree_root, None, self.primary)

    def finalize(self, task_id, staged):
        self.git('diff', '--check')
        candidate = self.root / f'candidate-{task_id}.json'
        candidate.write_text(json.dumps({
            'candidate_tree': staged['candidate_tree'], 'passed': True,
            'scope': 'full' if staged['decision'] == 'FULL' else 'bounded', 'commands': ['git diff --check',
                                        'python3 scripts/check_repository.py',
                                        'python3 -m unittest discover', "python3 -c 'pass'"],
        }))
        finalize_task_integration(task_id, candidate, self.primary)

    def test_two_branches_record_and_integrate_evidence_without_conflict(self):
        workers = self.prepare_pair()
        first = (workers['056'] / '.cardine/evidence/056.json').read_bytes()
        second = (workers['057'] / '.cardine/evidence/057.json').read_bytes()
        for task_id in ('056', '057'):
            self.finalize(task_id, self.stage(task_id, workers[task_id]))
        self.assertEqual((self.primary / '.cardine/evidence/056.json').read_bytes(), first)
        self.assertEqual((self.primary / '.cardine/evidence/057.json').read_bytes(), second)
        for task_id in ('056', '057'):
            ledger = json.loads((self.primary / f'.cardine/evidence/{task_id}.json').read_text())
            self.assertEqual(list(ledger), [task_id])
        self.assertFalse((self.primary / '.cardine/execution-evidence.json').exists())

    def test_conflict_in_another_file_still_stops_integration(self):
        workers = self.prepare_pair(conflict=True)
        self.finalize('056', self.stage('056', workers['056']))
        with self.assertRaisesRegex(CardineError, 'INTEGRATION_CONFLICT'):
            self.stage('057', workers['057'])
        self.assertFalse((self.primary / '.git/MERGE_HEAD').exists())
        self.assertEqual((self.primary / 'README.md').read_text(), 'Changed by 056\n')
