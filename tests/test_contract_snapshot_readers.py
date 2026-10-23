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

    def test_class_and_review_edits_do_not_change_start_or_review_policy(self):
        from cardine.tasks.transitions import transition_task_state
        from cardine.review.verdict import record_review_verdict
        from cardine.tasks.preflight import execution_contract, execution_preflight
        record = self.root / 'tasks/002.md'
        (self.root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_text('profile\n')
        record.write_text(record.read_text() + execution_contract(self.root, '002') + '\n')
        execution_preflight(self.root, '002')
        record.write_text(record.read_text() + '\nClass: spike\nReview: required\nDeliverable: docs/edited.md\n')
        execution_preflight(self.root, '002')
        self.git('switch', '-qc', 'task-002')
        state = transition_task_state(self.root, '002', 'in_progress')
        self.assertEqual(state['contract']['class'], 'standard')
        self.assertEqual(state['contract']['options']['review'], 'not_required')
        with self.assertRaises(CardineStop) as caught:
            record_review_verdict(self.root, '002', 'APPROVE')
        self.assertIn('required-review task', str(caught.exception))

    def test_answered_requires_every_committed_frozen_deliverable(self):
        from cardine.tasks.transitions import transition_task_state, record_spike_outcome
        text = contract_record('003', spike=True).replace('docs/result.md', 'docs/a.md, docs/b.md')
        create_task(self.root, '003', text)
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', 'Create spike')
        self.git('switch', '-qc', 'task-003')
        transition_task_state(self.root, '003', 'in_progress')
        record = self.root / 'tasks/003.md'
        record.write_text(text.replace('Class: spike', 'Class: standard').replace('docs/b.md', 'docs/edited.md'))
        path = self.root / '.cardine/tasks/003.json'
        self.assertEqual(json.loads(path.read_text())['contract']['deliverables'], ['docs/a.md', 'docs/b.md'])
        before = path.read_bytes()
        (self.root / 'docs/a.md').write_text('First answer\n')
        (self.root / 'docs/b.md').write_text('Second answer\n')
        with self.assertRaises(CardineStop):
            record_spike_outcome(self.root, '003', 'ANSWERED')
        self.assertEqual(path.read_bytes(), before)
        self.git('add', 'docs/a.md')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', 'First deliverable')
        with self.assertRaises(CardineStop) as caught:
            record_spike_outcome(self.root, '003', 'ANSWERED')
        self.assertIn('docs/b.md', str(caught.exception))
        self.assertEqual(path.read_bytes(), before)
        self.git('add', 'docs/b.md')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', 'Second deliverable')
        self.assertEqual(record_spike_outcome(self.root, '003', 'ANSWERED')['outcome'], 'ANSWERED')
        self.git('switch', 'main')
        with self.assertRaises(CardineStop) as caught:
            record_spike_outcome(self.root, '003', 'ANSWERED')
        self.assertIn('task branch', str(caught.exception))
        self.assertEqual(record_spike_outcome(self.root, '003', 'INCONCLUSIVE')['outcome'], 'INCONCLUSIVE')

    def test_spike_landing_paths_use_snapshot_even_after_class_and_deliverable_edits(self):
        from cardine.integration.merge import _spike_disallowed_paths
        identity = resolve_task_identity(self.root, '001', 'existing')
        state = json.loads((self.root / '.cardine/tasks/001.json').read_text())
        base = self.git('rev-parse', 'HEAD').stdout.decode().strip()
        self.record.write_text(self.before.replace('Class: spike', 'Class: standard')
                               .replace('docs/result.md', 'docs/edited.md'))
        (self.root / 'docs/result.md').write_text('Frozen deliverable\n')
        (self.root / 'docs/edited.md').write_text('Undeclared deliverable\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', 'Deliver spike')
        self.assertEqual(_spike_disallowed_paths(self.root, identity, base, 'HEAD', state), ('docs/edited.md',))

    def test_missing_snapshot_stops_without_backfill_or_record_resolution(self):
        from cardine.tasks.transitions import transition_task_state
        from cardine.lifecycle.commands import execution_start
        from cardine.lifecycle.execution import _execution_state
        from cardine.tasks.preflight import execution_preflight
        path = self.root / '.cardine/tasks/002.json'
        state = json.loads(path.read_text())
        del state['contract']
        path.write_text(json.dumps(state))
        before = path.read_bytes()
        with patch('cardine.lifecycle.commands._execution_location', return_value={}), \
             patch('cardine.tasks.contract.resolve_task_contract', side_effect=AssertionError('record resolution')):
            for action in (lambda: transition_task_state(self.root, '002', 'in_progress'),
                           lambda: execution_start(self.root, '002'),
                           lambda: _execution_state(self.root, '002'),
                           lambda: execution_preflight(self.root, '002')):
                with self.subTest(action=action), self.assertRaises(CardineStop) as caught:
                    action()
                self.assertEqual(caught.exception.code, 'TASK_STATE_MISSING')
                self.assertIn('resume: cardine task contract update 002', str(caught.exception))
                self.assertEqual(path.read_bytes(), before)

    def test_validation_and_heading_edits_cannot_change_runtime_gates(self):
        from cardine.tasks.preflight import execution_contract, execution_preflight
        from cardine.tasks.evidence import frozen_validation_commands
        from cardine.tasks.contract import verify_execution_evidence
        from cardine.tasks.recording import run_validation
        (self.root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_text('profile\n')
        record = self.root / 'tasks/002.md'
        record.write_text(record.read_text() + execution_contract(self.root, '002') + '\n')
        before = frozen_validation_commands(self.root, '002')
        self.assertEqual(frozen_validation_commands(self.root, 'task-002'), before)
        self.assertEqual(execution_contract(self.root, 'task-002'), execution_contract(self.root, '002'))
        record.write_text(record.read_text().replace('## Validation', '## Removed validation')
                          .replace('## Authority', '## Removed authority')
                          .replace('## Expected code surface', '## Removed surface')
                          + '\n## Validation\n- `injected`: `exit 99`\n')
        execution_preflight(self.root, '002')
        self.assertEqual(frozen_validation_commands(self.root, '002'), before)
        with self.assertRaises(CardineStop) as caught:
            verify_execution_evidence(self.root, '002', '')
        self.assertIn('task-check', str(caught.exception))
        with self.assertRaises(CardineStop) as caught:
            run_validation(self.root, '002', 'injected')
        self.assertEqual(caught.exception.code, 'VALIDATION_ID_UNDECLARED')
        self.assertEqual(run_validation(self.root, '002', 'task-check'), 0)
        verify_execution_evidence(self.root, '002', '')

    def test_host_declaration_is_frozen_and_missing_snapshot_never_backfills(self):
        from cardine.tasks.preflight import execution_contract, execution_preflight
        from cardine.tasks.evidence import frozen_execution_contract
        from cardine.shared.errors import CardineError
        text = contract_record('003') + "\n## Host impact\nClassification: NOT_APPLICABLE\nRationale: No host changes.\n"
        create_task(self.root, '003', text)
        (self.root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_text('profile\n')
        record = self.root / 'tasks/003.md'
        record.write_text(text + execution_contract(self.root, '003') + '\n')
        record.write_text(record.read_text().replace('NOT_APPLICABLE', 'INVALID').replace('Rationale:', 'Removed:'))
        execution_preflight(self.root, '003')
        self.assertEqual(frozen_execution_contract(self.root, '003')['hostImpact'],
                         {'classification': 'NOT_APPLICABLE', 'profiles': {}})
        path = self.root / '.cardine/tasks/003.json'
        state = json.loads(path.read_text())
        del state['contract']['hostImpact']
        path.write_text(json.dumps(state))
        before = path.read_bytes()
        with self.assertRaisesRegex(CardineError, 'cardine task contract update 003'):
            execution_preflight(self.root, '003')
        self.assertEqual(path.read_bytes(), before)

    def test_creation_rejects_invalid_execution_inputs_atomically(self):
        from cardine.shared.errors import CardineError
        invalid = [contract_record('003').replace('## Validation', '## Missing'),
                   contract_record('003', spike=True).replace('## Validation', '## Missing'),
                   contract_record('003').replace("- `task-check`: `python3 -c 'pass'`", '- `unnamed`'),
                   contract_record('003') + '\n## Host impact\nClassification: REQUIRED\n']
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(CardineError):
                create_task(self.root, '003', text)
            self.assertFalse((self.root / 'tasks/003.md').exists())
            self.assertFalse((self.root / '.cardine/tasks/003.json').exists())

    def test_host_profile_table_edits_cannot_remove_required_evidence(self):
        from cardine.tasks.preflight import execution_contract, execution_preflight, readiness_check
        from cardine.tasks.evidence import frozen_execution_contract
        text = contract_record('003') + """
## Host impact
Classification: REQUIRED
Policy outcome: Require evidence for the enforced profile.

| Profile | Before | Intended after | Activation preconditions | Fallback |
|---|---|---|---|---|
| Test host | advisory | enforced | Activate explicitly. | Report unavailable. |
| Test host | advisory | advisory | Alternate invocation. | Report unavailable. |

- Static: parser checks
- Host execution: fixture invocation
- Manual activation: explicit activation
"""
        create_task(self.root, '003', text)
        (self.root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_text('profile\n')
        record = self.root / 'tasks/003.md'
        record.write_text(text + execution_contract(self.root, '003') + '\n')
        record.write_text(record.read_text().replace('| enforced |', '| advisory |'))
        execution_preflight(self.root, '003')
        self.assertEqual(frozen_execution_contract(self.root, '003')['hostImpact']['profiles'],
                         {'Test host': 'enforced'})
        with self.assertRaises(CardineStop) as caught:
            readiness_check(self.root, '003', self.root / 'missing-report.md')
        self.assertEqual(caught.exception.code, 'HOST_IMPACT_EVIDENCE_MISSING')
        record.write_text(record.read_text().replace('## Host impact', '## Removed host impact'))
        with self.assertRaises(CardineStop) as caught:
            readiness_check(self.root, '003', self.root / 'missing-report.md')
        self.assertEqual(caught.exception.code, 'HOST_IMPACT_EVIDENCE_MISSING')
