"""Runtime decisions ignore record edits after the creation snapshot."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine.tasks.creation import create_task
from cardine.tasks.status import load_task_status
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.preflight import check_dependencies
from cardine.tasks.contract_snapshot import read_human_contract
from cardine.shared.errors import CardineStop
from cardine.shared.authority import context_authority
from cardine.shared.flow import _flow_origin
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_read_guard


class ContractSnapshotReadersTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        write_project_config(self.root, validation=deepcopy(VALIDATION))
        create_task(self.root, '002', contract_record('002').replace('P1', 'P2'))
        text = contract_record(extra='Phase: N1\nOrigin: maintenance\n', spike=True)
        text = text.replace('## Dependencies\nnone', '## Dependencies\n002')
        text = text.replace('ADR example, decision 1.', '- `docs/original.md`#Source')
        create_task(self.root, '001', text)
        (self.root / 'docs').mkdir()
        for filename in ('original', 'edited'):
            (self.root / f'docs/{filename}.md').write_text('## Source\n' + 'body\n' * 500)
        self.record = self.root / 'tasks/001.md'
        self.before = self.record.read_text()
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.root)], check=True)
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', 'Fixture')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def edit(self):
        self.record.write_text(self.before.replace('Task 001 — Contract fixture', 'Changed title')
                               .replace('`001`', '`999`').replace('Priority: P1', 'Priority: P9')
                               .replace('Phase: N1', 'Phase: changed').replace('Origin: maintenance', 'Origin: release')
                               .replace('## Dependencies\n002', '## Dependencies\nnone')
                               .replace('docs/original.md', 'docs/edited.md')
                               .replace('docs/result.md', 'docs/edited.md'))

    def test_status_order_identity_labels_and_deliverables_are_frozen(self):
        before = load_task_status(self.root)
        identity = resolve_task_identity(self.root, '001', 'existing')
        self.edit()
        (self.root / 'tasks/duplicate.md').write_text(self.before)
        self.assertEqual(load_task_status(self.root), before)
        self.assertEqual(resolve_task_identity(self.root, '001', 'existing'), identity)
        self.assertEqual([row['id'] for row in before['tasks']], ['001', '002'])
        row = before['tasks'][0]
        self.assertEqual((row['phase'], row['dependencies'], row['startable']), ('N1', ['002'], False))
        self.assertEqual(_flow_origin(self.root, '001'), 'maintenance')
        state = json.loads((self.root / '.cardine/tasks/001.json').read_text())
        self.assertEqual(state['contract']['title'], 'Task 001 — Contract fixture')
        self.assertEqual(row['title'], state['contract']['title'])
        self.assertEqual(read_human_contract(self.root, '001')['deliverables'], ['docs/result.md'])
        self.assertEqual(read_human_contract(self.root, 'task-001')['deliverables'], ['docs/result.md'])
        self.assertEqual(self.root / row['record'], self.record)

    def test_start_dependency_check_ignores_added_and_removed_prose_dependencies(self):
        self.edit()
        with self.assertRaises(CardineStop) as caught:
            check_dependencies(self.root, '001', self.record.read_text())
        self.assertEqual(caught.exception.code, 'TASK_STATUS_REJECTED')
        self.assertIn('002', str(caught.exception))
        check_dependencies(self.root, '002', '## Dependencies\n999\n')

    def test_authority_excerpts_and_guard_decision_are_frozen(self):
        before = context_authority(self.root, '001')
        self.edit()
        self.assertEqual(context_authority(self.root, '001'), before)
        active = {'task_id': '001', 'exempt_paths': []}
        with patch.object(codex_read_guard, 'active_worktree_task', return_value=active), \
             patch.object(codex_read_guard, 'context_router_files', return_value=()):
            self.assertTrue(codex_read_guard.is_exempt(self.root / 'docs/original.md', self.root))
            self.assertFalse(codex_read_guard.is_exempt(self.root / 'docs/edited.md', self.root))
        self.record.unlink()
        self.assertEqual(context_authority(self.root, '001'), before)
