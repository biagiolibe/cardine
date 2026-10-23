"""Frozen human intent, explicit revision, diagnostics and publication failure."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine.shared.errors import CardineError
from cardine.tasks.audit import audit_task_state_projections
from cardine.tasks.contract import HUMAN_CONTRACT_FIELDS, frozen_human_fields
from cardine.tasks.contract_update import contract_hash, update_task_contract
from cardine.tasks.creation import create_task
from cardine.tasks.state import TaskStateInvalid, review_is_required, validate_task_state
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION

ROOT = Path(__file__).resolve().parents[1]


class HumanContractSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
        self.record = self.root / 'tasks/001.md'
        self.path = self.root / '.cardine/tasks/001.json'

    def create(self, text=None):
        create_task(self.root, '001', text or contract_record())
        return self.read()

    def read(self):
        return json.loads(self.path.read_text())

    def audit(self):
        before = self.path.read_bytes()
        rows = audit_task_state_projections(self.root, 'single')
        self.assertEqual(self.path.read_bytes(), before)
        return '\n'.join(row.detail for row in rows if row.identity == 'task-contract' or row.status == 'FAIL')

    def test_creation_freezes_every_field_and_registered_dependency(self):
        create_task(self.root, '002', contract_record('002'))
        text = contract_record(extra='Phase: N1\nOrigin: maintenance\n', spike=True)
        text = text.replace('## Dependencies\nnone', '## Dependencies\n- **Depends on**: `002`')
        text = text.replace('ADR example, decision 1.', '- ADR-0013, decision 1.\n  Continued citation.\n- `docs/spec.md`#Heading')
        state = self.create(text)
        self.assertEqual(frozen_human_fields(state), {
            'dependencies': ['002'], 'title': 'Task 001 — Contract fixture',
            'priority': 'P1', 'phase': 'N1', 'origin': 'maintenance',
            'deliverables': ['docs/result.md'], 'recordPath': 'tasks/001.md',
            'authority': ['ADR-0013, decision 1. Continued citation.', '`docs/spec.md`#Heading'],
        })
        self.assertEqual(self.audit(), '')

    def test_unknown_self_and_noncanonical_dependencies_publish_neither(self):
        create_task(self.root, '002', contract_record('002'))
        for dependency in ('999', '001', 'task-002'):
            with self.subTest(dependency=dependency), self.assertRaises(CardineError):
                self.create(contract_record().replace('## Dependencies\nnone', f'## Dependencies\n{dependency}'))
            self.assertFalse(self.path.exists())
            self.assertFalse(self.record.exists())

    def test_edit_preserves_frozen_values_and_review_gate_until_explicit_update(self):
        before = self.create()
        self.record.write_text(self.record.read_text().replace('Priority: P1', 'Priority: P0')
                               .replace('## Objective', 'Review: required\n## Objective'))
        self.assertFalse(review_is_required(self.read()))
        self.assertEqual(self.read(), before)
        diagnostic = self.audit()
        self.assertIn('priority', diagnostic)
        self.assertIn('cardine task contract update 001', diagnostic)
        result = update_task_contract(self.root, '001')
        self.assertTrue(result['updated'])
        after = self.read()
        self.assertTrue(review_is_required(after))
        self.assertEqual(after['contract']['priority'], 'P0')
        self.assertEqual(after['transitions'], before['transitions'])
        self.assertEqual(after['status'], before['status'])
        history = after['contract_history'][0]
        self.assertEqual(history['before'], contract_hash(before['contract']))
        self.assertEqual(history['after'], contract_hash(after['contract']))
        self.assertEqual(history['changedFields'], ['options', 'priority'])
        self.assertEqual(self.audit(), '')
        self.assertFalse(update_task_contract(self.root, '001')['updated'])
        self.assertEqual(len(self.read()['contract_history']), 1)

    def test_older_snapshot_diagnoses_missing_fields_and_cli_completes_it(self):
        state = self.create()
        state.pop('run')  # Explicitly simulate a pre-receipt legacy snapshot.
        for field in HUMAN_CONTRACT_FIELDS:
            del state['contract'][field]
        self.path.write_text(json.dumps(state))
        validate_task_state(state, '001', 'single')
        with self.assertRaisesRegex(CardineError, 'cardine task contract update 001'):
            frozen_human_fields(state)
        self.assertIn('missing completed operation receipt', self.audit())
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/cardine_cli.py'),
                                 'task', 'contract', 'update', '001', '--project', str(self.root)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('missing completed operation receipt', result.stderr)
        self.assertEqual(json.loads(self.path.read_text()), state)

    def test_sparse_state_upgrade_is_explicit(self):
        state = self.create()
        state.pop('run')  # Explicit legacy-upgrade fixture, not a forged current receipt.
        del state['contract']
        self.path.write_text(json.dumps(state))
        self.assertIn('missing completed operation receipt', self.audit())
        with self.assertRaisesRegex(CardineError, 'missing completed operation receipt'):
            update_task_contract(self.root, '001')
        self.assertEqual(json.loads(self.path.read_text()), state)

    def test_invalid_record_or_unknown_dependency_update_preserves_snapshot_and_history(self):
        self.create()
        original = self.record.read_text()
        before = self.path.read_bytes()
        for text in (original.replace('## Objective', '## Missing'),
                     original.replace('## Dependencies\nnone', '## Dependencies\n999')):
            self.record.write_text(text)
            with self.assertRaises(CardineError):
                update_task_contract(self.root, '001')
            self.assertEqual(self.path.read_bytes(), before)

    def test_cli_rejects_inconsistent_revision_without_traceback_or_state_write(self):
        state = self.create()
        state.pop('run')  # Exercise legacy schema policy checks independently of receipts.
        state['review'] = {'required': False, 'verdict': None, 'attempt': 1,
                           'reviewed_commit': None, 'approved_by': None}
        self.path.write_text(json.dumps(state))
        before = self.path.read_bytes()
        self.record.write_text(self.record.read_text().replace('## Objective', 'Review: required\n## Objective'))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/cardine_cli.py'),
                                 'task', 'contract', 'update', '001', '--project', str(self.root)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('missing completed operation receipt', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(self.path.read_bytes(), before)

    def test_atomic_replacement_failure_keeps_snapshot_and_history_together(self):
        self.create()
        before = self.path.read_bytes()
        self.record.write_text(self.record.read_text().replace('Priority: P1', 'Priority: P0'))
        with patch('cardine.shared.jsonio.os.replace', side_effect=OSError('injected')):
            with self.assertRaisesRegex(OSError, 'injected'):
                update_task_contract(self.root, '001')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('.*.json.*')), [])

    def test_schema_rejects_bad_human_fields_and_partial_snapshots(self):
        state = self.create()
        for field, value in (('dependencies', '002'), ('authority', [False]), ('origin', 3),
                             ('recordPath', '../outside.md'), ('deliverables', ['/etc/passwd']),
                             ('recordPath', 'tasks/../001.md'), ('dependencies', ['001'])):
            bad = deepcopy(state)
            bad['contract'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(TaskStateInvalid):
                validate_task_state(bad, '001', 'single')
        del state['contract']['title']
        with self.assertRaisesRegex(TaskStateInvalid, 'contract update 001'):
            validate_task_state(state, '001', 'single')

    def test_revision_history_is_connected_and_bound_to_current_snapshot(self):
        self.create()
        for priority in ('P0', 'P2'):
            self.record.write_text(self.record.read_text().replace(
                self.read()['contract']['priority'], priority))
            update_task_contract(self.root, '001')
        state = self.read()
        self.assertEqual(state['contract_history'][0]['after'], state['contract_history'][1]['before'])
        for mutate in (lambda s: s['contract'].update(origin='tampered'),
                       lambda s: s['contract_history'][1].update(before='sha256:' + '0' * 64),
                       lambda s: s['contract_history'][1].update(at='2000-01-01T00:00:00Z')):
            bad = deepcopy(state)
            mutate(bad)
            with self.assertRaises(TaskStateInvalid):
                validate_task_state(bad, '001', 'single')

    def test_quick_defaults_and_explicit_title(self):
        text = ('ID: 001\nCategory: Quick\nTitle: Small fix\n## Objective\nFix.\n'
                '## Acceptance Criteria\nVerified.\n## Validation\nnone\n## Dependencies\nnone\n')
        human = frozen_human_fields(self.create(text))
        self.assertEqual(human['title'], 'Small fix')
        for key in ('priority', 'origin', 'phase'):
            self.assertEqual(human[key], '')
        self.assertEqual(human['deliverables'], [])
        self.assertEqual(human['authority'], [])


if __name__ == '__main__':
    unittest.main()
