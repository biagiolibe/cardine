"""Exercise the twelve ADR parity rows through the same product for both presets."""

from copy import deepcopy
import json
from itertools import product
import os
from pathlib import Path
import re
import shutil
import unittest

import test_execution_boundaries as boundaries
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION, freeze_record, seal_state
from cardine.integration import merge
from cardine.integration.evidence import candidate_validation_declaration
from cardine.shared.constants import WORKFLOW_MODES
from cardine.legacy.console_workflow import PROFILES
from cardine.lifecycle import commands, execution
from control_support import issued_verdict as record_review_verdict
from cardine.shared.authority import adr_list, adr_show
from cardine.shared.errors import CardineError, CardineStop
from cardine.shared.project import resolve_project_configuration
from cardine.tasks.contract import resolve_task_contract
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.preflight import check_dependencies
from cardine.tasks.state import dependency_satisfied, machine
from cardine.tasks.transitions import transition_task_state, close_task, record_spike_outcome
from cardine.templates.mode import detect_mode
from cardine.templates.merge import lock_project

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ('lean', 'governed')


class SingleWorkflowParityTest(unittest.TestCase):
    def project(self, preset, *, review='required', spike=False, surface=False):
        # Reuse the real-Git execution fixture, without importing its test class
        # into this module's discovery namespace or mocking a lifecycle gate.
        fixture = boundaries.ExecutionBoundariesTest()
        fixture.preset = preset
        fixture.setUp()
        fixture.primary = fixture.primary.resolve()
        self.addCleanup(fixture.doCleanups)
        write_project_config(fixture.worker, preset, validation=deepcopy(VALIDATION))
        record = fixture.worker / fixture.record
        text = record.read_text().replace('Review: REQUIRED', f'Review: {review}')
        if spike:
            text = text.replace('Class: standard', 'Class: spike\nQuestion: Is this feasible?\n'
                                'Timebox: 1h\nDeliverable: docs/result.md')
        if surface:
            text = text.replace('Change the documented deliverable only.', '- `**`')
        record.write_text(text)
        state_path = fixture.worker / '.cardine/tasks/001.json'
        state = json.loads(state_path.read_text())
        state['contract'] = resolve_task_contract(fixture.worker, '001')
        state_path.write_text(json.dumps(state))
        seal_state(fixture.worker, '001')
        fixture.commit('Configure parity fixture')
        return fixture

    def stop(self, code, action):
        with self.assertRaises(CardineStop) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_required_review_for_both_presets(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                f.implemented()
                self.assertEqual(f.state()['contract']['preset'], preset)
                self.assertEqual(f.state()['contract']['options']['review'], 'required')
                self.assertEqual(commands.execution_deliver(f.worker, '001')['status'], 'in_review')
                self.assertEqual(f.state()['status'], 'in_review')

    def test_per_task_waiver_is_frozen_for_both_presets(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset, review='not_required')
                commands.execution_start(f.worker, '001')
                before = f.state()['contract']
                write_project_config(f.primary, preset, validation=VALIDATION,
                                     taskDefaults={'review': 'required'})
                self.stop('TASK_STATE_INVALID', lambda: transition_task_state(f.worker, '001', 'in_review'))
                self.assertEqual(f.state()['contract'], before)
                (f.worker / '.cardine/candidate-validation.json').write_text('{invalid')
                declaration, commands_by_outcome = candidate_validation_declaration(f.worker, '001')
                self.assertEqual(declaration, 'declared')
                self.assertEqual(commands_by_outcome['REUSE'], ('true',))
                self.assertNotIn('in_review', machine(review_required=False)['in_progress'])

    def test_verdict_is_bound_to_the_approved_commit(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                identity = f.implemented()
                commands.execution_deliver(f.worker, '001')
                head = f.git('rev-parse', 'HEAD')
                state = record_review_verdict(f.worker, '001', 'APPROVE')
                self.assertEqual(state['review']['reviewed_commit'], head)
                self.assertEqual(state['status'], 'in_progress')
                f.commit('Record approval')
                (f.worker / 'feature.txt').write_text('changed after approval\n')
                f.commit('Change implementation')
                self.stop('REVIEW_NOT_APPROVED', lambda: merge._integration_task_state(
                    f.primary, resolve_task_identity(f.primary, '001', 'existing'),
                    f.git('rev-parse', 'HEAD'), f.worker, require_tracked=True))

    def test_changes_requested_preserves_history_and_starts_new_attempt(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                f.implemented()
                commands.execution_deliver(f.worker, '001')
                rejected = record_review_verdict(f.worker, '001', 'CHANGES_REQUESTED')
                self.assertEqual(rejected['status'], 'in_progress')
                f.commit('Record findings')
                (f.worker / 'feature.txt').write_text('fixed implementation\n')
                boundaries.owner_tasks_recording.run_validation(f.worker, '001', 'check')
                f.commit('Implement requested fix and validate')
                commands.execution_deliver(f.worker, '001')
                approved = record_review_verdict(f.worker, '001', 'APPROVE')
                self.assertEqual([item['verdict'] for item in approved['review_history']],
                                 ['CHANGES_REQUESTED', 'APPROVE'])
                self.assertEqual(approved['review']['attempt'], 2)

    def test_spike_outcomes_do_not_complete_or_unblock_before_landing(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset, review='not_required', spike=True)
                commands.execution_start(f.worker, '001')
                (f.worker / 'docs/result.md').write_text('Research result.\n')
                f.commit('Commit spike deliverable')
                for outcome in ('ANSWERED', 'INCONCLUSIVE'):
                    state = record_spike_outcome(f.worker, '001', outcome)
                    self.assertEqual(state['status'], 'in_progress')
                    self.assertFalse(dependency_satisfied(state))
                    state = dict(state, status='done')
                    self.assertEqual(dependency_satisfied(state), outcome == 'ANSWERED')
                self.stop('TASK_STATE_INVALID', lambda: transition_task_state(f.worker, '001', 'done'))

    def required_field(self, heading, option):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                record = f.worker / f.record
                text = re.sub(rf'## {heading}\n.*?(?=## |\Z)', '', record.read_text(), flags=re.DOTALL)
                record.write_text(text + '\nOptions: ' + json.dumps({option: True}) + '\n')
                with self.assertRaisesRegex(CardineError, heading):
                    resolve_task_contract(f.worker, '001')
                record.write_text(text + '\nOptions: ' + json.dumps({option: False}) + '\n')
                self.assertFalse(resolve_task_contract(f.worker, '001')['options'][option])

    def test_authority_citations_can_be_required_or_waived(self):
        self.required_field('Authority', 'authorityRequired')

    def test_expected_code_surface_can_be_required_or_waived(self):
        self.required_field('Expected code surface', 'expectedCodeSurfaceRequired')

    def test_adr_log_list_and_show_are_shared(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                (f.worker / 'docs/ARCHITECTURE_DECISIONS.md').write_text(
                    '# Decisions\n\n## ADR-0001 — Parity\n\nStatus: Accepted\n\nRetain one lifecycle.\n')
                entries, warnings = adr_list(f.worker)
                self.assertEqual([entry['id'] for entry in entries], ['ADR-0001'])
                self.assertEqual(warnings, [])
                self.assertIn('Retain one lifecycle.', adr_show(f.worker, 'ADR-0001'))

    def test_dependencies_require_landed_state(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                record = (f.worker / f.record).read_text().replace('## Dependencies\nnone', '## Dependencies\n002')
                task_path = f.worker / '.cardine/tasks/001.json'
                snapshot = json.loads(task_path.read_text())
                snapshot['contract']['dependencies'] = ['002']
                task_path.write_text(json.dumps(snapshot))
                seal_state(f.worker, '001')
                self.stop('DEPENDENCY_PENDING', lambda: check_dependencies(f.worker, '001', record))
                state = {'version': 1, 'task_id': '002', 'workflow': 'single', 'status': 'done',
                         'transitions': [
                             {'from': 'queued', 'to': 'in_progress', 'commit': f.git('rev-parse', 'HEAD'),
                              'at': '2026-10-20T00:00:00Z'},
                             {'from': 'in_progress', 'to': 'done', 'commit': f.git('rev-parse', 'HEAD'),
                              'at': '2026-10-20T00:00:01Z'}],
                         'review': {'required': False, 'verdict': None, 'attempt': 1,
                                    'reviewed_commit': None, 'approved_by': None}}
                path = f.primary / '.cardine/tasks/002.json'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(state))
                dependency = f.primary / 'tasks/002.md'
                dependency.write_text(contract_record('002', extra='Review: not_required\n'))
                freeze_record(f.primary, '002', dependency)
                # A file on disk is insufficient until main commits it.
                self.stop('DEPENDENCY_PENDING', lambda: check_dependencies(f.worker, '001', record))
                f.git('add', '.', cwd=f.primary)
                f.git('commit', '-qm', 'Land dependency', cwd=f.primary)
                check_dependencies(f.worker, '001', record)

    def test_milestone_identity_for_both_presets(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                write_project_config(f.primary, preset, validation=VALIDATION, taskIdentity={'mode': 'milestone'})
                task_id = 'M1-CORE-001'
                (f.worker / f'tasks/{task_id}.md').write_text(contract_record(task_id))
                identity = resolve_task_identity(f.worker, task_id, 'existing')
                self.assertEqual(identity.canonical_id, task_id)
                self.assertEqual(identity.branch_name, 'm1-core-001')
                self.assertEqual(identity.mode, 'milestone')

    def test_execution_evidence_rejects_a_changed_source(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                f.implemented()
                (f.worker / 'feature.txt').write_text('unvalidated change\n')
                f.commit('Invalidate source evidence')
                self.stop('EVIDENCE_INCOMPLETE', lambda: execution.delivery_readiness(f.worker, '001'))
                self.assertEqual(f.state()['status'], 'in_progress')

    def test_retry_policy_replaces_spend_counters_and_retains_read_guard(self):
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                self.assertEqual(resolve_project_configuration(f.worker)['taskDefaults']['validationRetryLimit'], 3)
                self.assertEqual(resolve_task_contract(f.worker, '001')['options']['validationRetryLimit'], 3)
                policy = (ROOT / 'templates/single/docs/CONTEXT_READING_POLICY.md').read_text()
                self.assertIn('Read-guard threshold', policy)
                self.assertIn('Evidence tiers', policy)
                self.assertNotIn('budget spend', policy)
                self.assertNotIn('Budget usage:', policy)

    def test_init_contract_state_review_and_landing_chain_for_both_presets(self):
        for preset, review in product(PRESETS, ('required', 'not_required')):
            with self.subTest(preset=preset, review=review):
                f = self.project(preset, review=review, surface=True)
                # Init's copy/config/lock sequence, preserving the fixture's
                # owner-selected commands and bounded execution profile.
                for source in (ROOT / 'templates/single').rglob('*'):
                    target = f.worker / source.relative_to(ROOT / 'templates/single')
                    if source.is_file() and not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                lock_project(f.worker, ROOT, detect_mode(f.worker))
                self.assertEqual(json.loads((f.worker / '.cardine/manifest.json').read_text())['workflowMode'], 'single')
                f.commit('Initialize single distribution')
                # Landing consumes the engine's measured attempt, not recorded results.
                from cardine.lifecycle.engine import deliver_run_implementation, resolve_run_locations
                from cardine.lifecycle.validation import run_task_validation
                commands.execution_start(f.worker, '001')
                (f.worker / 'feature.txt').write_text('implementation\n')
                f.commit('Implement feature')
                deliver_run_implementation(resolve_run_locations('001', f.worker))
                run_task_validation(f.worker, '001')
                f.commit('Record measured validation')
                identity = resolve_task_identity(f.worker, '001', 'existing')
                identity.handoff_path.parent.mkdir(parents=True, exist_ok=True)
                identity.handoff_path.write_text('## Completion Report — 001\n\n- Files changed: feature.txt\n')
                f.commit('Finalize handoff')
                if review == 'required':
                    transition_task_state(f.worker, '001', 'in_review')
                    f.commit('Request review')
                    record_review_verdict(f.worker, '001', 'APPROVE')
                    f.commit('Record approved review')
                closed = close_task(f.worker, '001')
                self.assertEqual(closed['record'], 'tasks/001.md')
                self.assertEqual(f.git('status', '--porcelain'), '')
                os.chdir(f.primary)
                staged = merge.stage_task_integration('001', None, None, f.primary)
                candidate = Path(f.temp.name) / 'candidate.json'
                candidate.write_text(json.dumps({'candidate_tree': staged['candidate_tree'], 'passed': True,
                                                'scope': 'bounded', 'commands': ['true', 'git diff --check']}))
                f.git('diff', '--check', cwd=f.primary)
                merge.finalize_task_integration('001', candidate, f.primary)
                landed = json.loads((f.primary / '.cardine/tasks/001.json').read_text())
                self.assertEqual(landed['status'], 'done')
                self.assertEqual(landed['contract']['preset'], preset)
                self.assertEqual(landed['contract']['options']['review'], review)
                if review == 'required':
                    self.assertEqual(landed['review']['verdict'], 'APPROVE')
                else:
                    self.assertFalse(any(t['to'] == 'in_review' for t in landed['transitions']))
                self.assertTrue((f.primary / 'tasks/001.md').is_file())
                self.assertFalse((f.primary / 'tasks/done/001.md').exists())
                self.assertTrue(dependency_satisfied(landed))

    def test_one_distribution_machine_and_template_root(self):
        self.assertEqual(WORKFLOW_MODES, ('single',))
        self.assertEqual(tuple(PROFILES), ('single',))
        self.assertEqual(json.loads((ROOT / 'schemas/task-state-v1.schema.json').read_text())
                         ['properties']['workflow']['enum'], ['single'])
        self.assertEqual({path.name for path in (ROOT / 'templates').iterdir() if path.is_dir()}, {'single'})
        for preset in PRESETS:
            with self.subTest(preset=preset):
                f = self.project(preset)
                self.assertEqual(detect_mode(f.primary), 'single')
                self.assertEqual(resolve_project_configuration(f.primary)['preset'], preset)
