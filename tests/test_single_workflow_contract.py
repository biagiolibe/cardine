"""Creation contracts resolve explicit policy once and preserve it in state."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine_cli_support import CLI
from cardine.tasks.contract import resolve_task_contract
from cardine.tasks.importer import import_task_states
from cardine.tasks.state import TaskStateInvalid, validate_task_state
from cardine.shared.errors import CardineError
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION

ROOT = Path(__file__).resolve().parents[1]


class SingleWorkflowContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'tasks').mkdir()
        self.configure()
        self.record()

    def configure(self, preset='lean', **overrides):
        write_project_config(self.root, preset, validation=deepcopy(VALIDATION), **overrides)

    def record(self, extra='', *, spike=False, text=None, task_id='001'):
        self.path = self.root / f'tasks/{task_id}.md'
        self.path.write_text(text if text is not None else contract_record(task_id, extra='Status: QUEUED\n' + extra, spike=spike))
        (self.root / 'tasks/QUEUE.md').write_text(
            '| ID | Status | Task file |\n|---|---|---|\n'
            f'| {task_id} | QUEUED | [{task_id}]({task_id}.md) |\n')

    def resolve(self):
        return resolve_task_contract(self.root, '001')

    def test_lean_can_require_review_and_governed_can_waive_it(self):
        for preset, override in (('lean', 'required'), ('governed', 'not_required')):
            with self.subTest(preset=preset):
                self.configure(preset)
                self.record(f'Review: {override}\n')
                snapshot = self.resolve()
                self.assertEqual(snapshot['preset'], preset)
                self.assertEqual(snapshot['options']['review'], override)
                state = import_task_states(self.root, ['001'])['tasks'][0]['state']
                self.assertEqual(state['contract'], snapshot)

    def test_project_then_task_options_preserve_false_and_not_required(self):
        self.configure('governed', taskDefaults={'review': 'not_required', 'validationRetryLimit': 5})
        self.record('Options: {"authorityRequired": false, "expectedCodeSurfaceRequired": false, "validationRetryLimit": 2}\n')
        self.path.write_text(self.path.read_text().replace('## Authority\nADR example, decision 1.\n', '')
                             .replace('## Expected code surface\nChange the documented deliverable only.\n', ''))
        options = self.resolve()['options']
        self.assertEqual(options, {'review': 'not_required', 'authorityRequired': False,
                                  'expectedCodeSurfaceRequired': False, 'validationRetryLimit': 2,
                                  'landingMode': 'direct', 'ciBeforeLanding': False})

    def test_required_fields_can_be_raised_or_lowered(self):
        for preset, value in (('lean', True), ('governed', False)):
            for option, heading in (('authorityRequired', 'Authority'),
                                    ('expectedCodeSurfaceRequired', 'Expected code surface')):
                with self.subTest(preset=preset, option=option):
                    self.configure(preset)
                    self.record('Options: ' + json.dumps({option: value}) + '\n')
                    text = self.path.read_text()
                    import re
                    text = re.sub(rf'## {heading}\n.*?(?=## |\Z)', '', text, flags=re.DOTALL)
                    self.path.write_text(text)
                    if value:
                        with self.assertRaisesRegex(CardineError, heading):
                            self.resolve()
                    else:
                        self.assertFalse(self.resolve()['options'][option])

    def test_spike_requires_question_timebox_deliverable_and_inherits_review(self):
        self.configure('governed')
        self.record(spike=True)
        self.assertEqual(self.resolve()['class'], 'spike')
        self.assertEqual(self.resolve()['options']['review'], 'required')
        inherited = import_task_states(self.root, ['001'])['tasks'][0]['state']['contract']
        self.assertEqual(inherited['options']['review'], 'required')
        for field, content in (('Question', 'Is it feasible?'), ('Timebox', '1h'), ('Deliverable', 'docs/result.md')):
            with self.subTest(field=field):
                self.record(spike=True)
                self.path.write_text(self.path.read_text().replace(f'{field}: {content}\n', ''))
                with self.assertRaisesRegex(CardineError, field):
                    self.resolve()
        self.record('Review: not_required\n', spike=True)
        self.assertEqual(self.resolve()['options']['review'], 'not_required')
        state = import_task_states(self.root, ['001'])['tasks'][0]['state']
        self.assertFalse(state['review']['required'])

    def test_spike_replaces_feature_acceptance_shape(self):
        self.record(spike=True)
        import re
        self.path.write_text(re.sub(r'## (Objective|Acceptance Criteria)\n.*?(?=## |\Z)',
                                   '', self.path.read_text(), flags=re.DOTALL))
        self.assertEqual(self.resolve()['class'], 'spike')

    def test_quick_is_minimal_but_requires_registered_identity_and_validation(self):
        quick = ('> **ID**: `001`\nCategory: Quick\n## Objective\nDo the small change.\n'
                 '## Acceptance Criteria\nVerified.\n## Validation\nnone\n## Dependencies\nnone\n')
        self.record(text=quick)
        self.assertEqual(self.resolve()['class'], 'standard')
        state = import_task_states(self.root, ['001'], apply=True)['tasks'][0]['state']
        self.assertIn('contract', state)
        self.assertTrue((self.root / '.cardine/tasks/001.json').is_file())
        with self.assertRaises(CardineError):
            resolve_task_contract(self.root, 'unregistered')
        self.path.write_text(quick.replace('## Validation\nnone\n', ''))
        with self.assertRaisesRegex(CardineError, 'Validation'):
            self.resolve()

    def test_standard_missing_fields_fail_closed(self):
        import re
        for field in ('Objective', 'Acceptance Criteria', 'Dependencies', 'Out of scope', 'Relevant Files'):
            with self.subTest(field=field):
                self.record()
                self.path.write_text(re.sub(rf'## {field}\n.*?(?=## |\Z)', '',
                                           self.path.read_text(), flags=re.DOTALL))
                with self.assertRaisesRegex(CardineError, field):
                    self.resolve()
        self.record()
        with self.assertRaisesRegex(CardineError, 'ID'):
            resolve_task_contract(self.root, '001', text=self.path.read_text().replace('`001`', '`002`'))

    def test_invalid_options_and_conflicting_review_fail_without_forge_probe(self):
        invalid = ({'review': False}, {'validationRetryLimit': True}, {'validationRetryLimit': 0},
                   {'authorityRequired': 'false'}, {'expectedCodeSurfaceRequired': 1},
                   {'ciBeforeLanding': True}, {'landingMode': 'pull-request'},
                   {'taskIdentity': {'mode': 'milestone'}}, {'unknown': True}, [])
        original_run = subprocess.run
        def no_forge(command, *args, **kwargs):
            self.assertEqual(command[0], 'git', 'unexpected forge probe')
            return original_run(command, *args, **kwargs)
        for options in invalid:
            with self.subTest(options=options), patch('subprocess.run', side_effect=no_forge):
                self.record('Options: ' + json.dumps(options) + '\n')
                with self.assertRaises(CardineError):
                    self.resolve()
        self.record('Review: required\nOptions: {"review": "not_required"}\n')
        with self.assertRaisesRegex(CardineError, 'conflicts'):
            self.resolve()
        self.record('Options: {\n')
        with self.assertRaisesRegex(CardineError, 'JSON'):
            self.resolve()

    def test_options_section_and_historical_review_spelling(self):
        self.record('Review: REQUIRED\n')
        self.path.write_text(self.path.read_text() + '\n## Options\n```json\n{"validationRetryLimit": 4}\n```\n')
        options = self.resolve()['options']
        self.assertEqual(options['review'], 'required')
        self.assertEqual(options['validationRetryLimit'], 4)

    def test_ci_override_and_snapshot_do_not_share_mutable_configuration(self):
        self.configure('governed', taskDefaults={'ciBeforeLanding': True},
                       ci={'provider': 'github', 'requiredChecks': ['tests']},
                       validationScoping=[{'paths': ['src/**'], 'commands': ['source-check']}])
        self.record('Options: {"ciBeforeLanding": false}\n')
        snapshot = self.resolve()
        self.assertFalse(snapshot['options']['ciBeforeLanding'])
        self.assertEqual(snapshot['ci']['requiredChecks'], ['tests'])
        self.assertEqual(snapshot['validationScoping'][0]['paths'], ['src/**'])
        snapshot['ci']['requiredChecks'].clear()
        snapshot['validationScoping'].clear()
        self.assertEqual(self.resolve()['ci']['requiredChecks'], ['tests'])
        self.assertEqual(len(self.resolve()['validationScoping']), 1)

    def test_queue_review_checks_resolved_options_without_selecting_them(self):
        self.configure('governed')
        self.record()
        queue = self.root / 'tasks/QUEUE.md'
        queue.write_text('| ID | Status | Review | Task file |\n|---|---|---|---|\n'
                         '| 001 | QUEUED | REQUIRED | [001](001.md) |\n')
        self.assertEqual(import_task_states(self.root, ['001'])['tasks'][0]['state']['contract']['options']['review'],
                         'required')
        self.record('Options: {"review": "not_required"}\n')
        queue.write_text('| ID | Status | Review | Task file |\n|---|---|---|---|\n'
                         '| 001 | QUEUED | NOT_REQUIRED | [001](001.md) |\n')
        self.assertFalse(import_task_states(self.root, ['001'])['tasks'][0]['state']['review']['required'])

    def test_validation_snapshot_composes_baseline_task_and_candidate_commands(self):
        validation = {'commands': {'repo': 'check-repository', 'full': 'full-suite'}, 'baseline': ['repo'],
                      'candidate': {'REUSE': [], 'BOUNDED': [], 'FULL': ['full']}}
        write_project_config(self.root, 'lean', validation=validation)
        contract = self.resolve()
        self.assertEqual(contract['validation']['baseline'], ['repo', 'task-check'])
        self.assertEqual(contract['validation']['commands']['task-check'], "python3 -c 'pass'")
        self.assertEqual(contract['validation']['candidate']['FULL'], ['full', 'candidate-diff-check'])
        self.assertEqual(contract['validation']['commands']['candidate-diff-check'], 'git diff --check')
        self.assertEqual(json.loads((self.root / '.cardine/project.json').read_text())['validation'], validation)
        self.path.write_text(self.path.read_text().replace('`task-check`', '`repo`'))
        with self.assertRaisesRegex(CardineError, 'conflicts'):
            self.resolve()

    def test_absent_validation_is_not_empty_and_unnamed_commands_are_rejected(self):
        write_project_config(self.root, 'lean')
        with self.assertRaisesRegex(CardineError, 'requires validation'):
            self.resolve()
        self.configure()
        self.path.write_text(self.path.read_text().replace("- `task-check`: `python3 -c 'pass'`", '- `unnamed-command`'))
        with self.assertRaises(CardineError):
            self.resolve()

    def test_import_cli_preserves_snapshot_after_preset_defaults_and_record_change(self):
        command = [sys.executable, str(ROOT / 'scripts/cardine_cli.py'), 'task', 'state', 'import',
                   '001', '--project', str(self.root), '--format', 'json', '--apply']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.root / '.cardine/tasks/001.json'
        before = path.read_bytes()
        digest = json.loads(before)['contract']['projectDigest']
        self.configure('governed', taskDefaults={'validationRetryLimit': 7})
        self.record('Review: required\n')
        again = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)['tasks'][0]['action'], 'skip-existing')
        self.assertEqual(path.read_bytes(), before)
        self.assertNotEqual(self.resolve()['projectDigest'], digest)
        self.record(task_id='002')
        created = import_task_states(self.root, ['002'], apply=True)['tasks'][0]['state']
        self.assertEqual(created['contract']['preset'], 'governed')
        self.assertEqual(created['contract']['options']['validationRetryLimit'], 7)

    def test_schema_rejects_invalid_snapshot_types_unknown_keys_and_references(self):
        state = import_task_states(self.root, ['001'])['tasks'][0]['state']
        validate_task_state(state, '001', 'lean-delivery')
        for mutate in (
            lambda c: c.update(unowned=True),
            lambda c: c['options'].update(validationRetryLimit=True),
            lambda c: c['options'].pop('review'),
            lambda c: c.update(projectDigest='bad'),
            lambda c: c['validation']['baseline'].append('unknown'),
            lambda c: c['validation']['baseline'].append('task-check'),
            lambda c: c['validation']['commands'].update(bad=False),
        ):
            broken = deepcopy(state)
            mutate(broken['contract'])
            with self.assertRaises(TaskStateInvalid):
                validate_task_state(broken, '001', 'lean-delivery')
        # Historical state remains readable; imports never rewrite it.
        state.pop('contract')
        validate_task_state(state, '001', 'lean-delivery')

    def test_invalid_second_contract_prevents_all_writes(self):
        self.record(task_id='002', extra='Options: {"review": true}\n')
        (self.root / 'tasks/QUEUE.md').write_text(
            '| ID | Status | Task file |\n|---|---|---|\n'
            '| 001 | QUEUED | [001](001.md) |\n| 002 | QUEUED | [002](002.md) |\n')
        with self.assertRaises(CardineError):
            import_task_states(self.root, [], apply=True)
        self.assertFalse((self.root / '.cardine/tasks').exists())


if __name__ == '__main__':
    unittest.main()
