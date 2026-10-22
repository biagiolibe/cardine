"""Paired task creation, publication boundaries, reader barriers and recovery."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from cardine.tasks.creation import create_task
from cardine.tasks.contract import resolve_task_contract
from cardine.tasks.state import read_task_state, validate_task_state
from cardine.tasks.status import load_task_status
from cardine.shared.errors import CardineError
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION

ROOT = Path(__file__).resolve().parents[1]


class TaskCreationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
        self.record = self.root / 'tasks/001.md'
        self.state = self.root / '.cardine/tasks/001.json'
        self.lock = self.root / '.cardine/task-creation.lock'
        self.text = contract_record()

    def create(self, **kwargs):
        return create_task(self.root, '001', self.text, **kwargs)

    def assert_no_pair(self):
        self.assertFalse(self.record.exists())
        self.assertFalse(self.state.exists())
        self.assertFalse(self.lock.exists())
        self.assertEqual(list(self.root.rglob('.task-new-*')), [])

    def test_creates_valid_pair_resolves_once_and_freezes_overrides(self):
        self.text = contract_record(extra='Review: required\nOptions: {"validationRetryLimit": 4}\n')
        with patch('cardine.tasks.creation.resolve_task_contract', wraps=resolve_task_contract) as resolve:
            result = self.create()
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(result['record'], 'tasks/001.md')
        state = json.loads(self.state.read_text())
        validate_task_state(state, '001', 'single')
        self.assertEqual(state['status'], 'queued')
        self.assertEqual(state['transitions'], [])
        self.assertEqual(state['contract']['options']['review'], 'required')
        self.assertEqual(state['contract']['options']['validationRetryLimit'], 4)
        before = self.state.read_bytes()
        write_project_config(self.root, 'governed', validation=deepcopy(VALIDATION))
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(self.record.read_text(), self.text)
        self.assertNotIn('Status:', self.record.read_text())
        self.assertEqual(load_task_status(self.root)['totals']['queued'], 1)

    def test_quick_cli_uses_same_schema_with_minimal_record(self):
        proposal = self.root / 'proposal.txt'
        proposal.write_text('ID: 001\n## Objective\nSmall change.\n'
                            '## Acceptance Criteria\nVerified.\n## Validation\nnone\n## Dependencies\nnone\n')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/cardine_cli.py'), 'task', 'new',
                                 '001', '--record', str(proposal), '--quick', '--project', str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.state.read_text())
        validate_task_state(state, '001', 'single')
        self.assertEqual(state['contract']['class'], 'standard')
        self.assertIn('Category: Quick', self.record.read_text())

    def test_invalid_contract_and_state_publish_neither(self):
        self.text = self.text.replace('## Objective', '## Missing')
        with self.assertRaisesRegex(CardineError, 'Objective'):
            self.create()
        self.assert_no_pair()
        self.text = contract_record()
        with patch('cardine.tasks.creation.validate_task_state', side_effect=ValueError('invalid state')):
            with self.assertRaisesRegex(CardineError, 'invalid state'):
                self.create()
        self.assert_no_pair()

    def test_duplicate_records_states_and_aliases_never_overwrite(self):
        self.create()
        before = (self.record.read_bytes(), self.state.read_bytes())
        for task_id in ('001', 'task-001'):
            with self.subTest(task_id=task_id), self.assertRaises(CardineError):
                create_task(self.root, task_id, self.text)
        self.assertEqual((self.record.read_bytes(), self.state.read_bytes()), before)
        self.record.unlink()
        with self.assertRaisesRegex(CardineError, 'already exists'):
            self.create()
        self.assertEqual(self.state.read_bytes(), before[1])

    def test_ambiguous_id_and_unsafe_paths_rejected(self):
        self.record.parent.mkdir()
        self.record.write_text(self.text)
        (self.record.parent / 'duplicate.md').write_text(self.text)
        with self.assertRaisesRegex(CardineError, 'ambiguous'):
            self.create()
        for task_id in ('../outside', '/absolute', 'a/b', '..'):
            with self.subTest(task_id=task_id), self.assertRaises(CardineError):
                create_task(self.root, task_id, self.text)
        self.assertFalse(self.state.exists())

    def test_symlinked_task_root_and_state_directory_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / 'tasks').symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(CardineError, 'symlink'):
                self.create()
            (self.root / 'tasks').unlink()
            self.state.parent.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(CardineError, 'symlink'):
                self.create()
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_dangling_record_symlink_is_existing_identity(self):
        self.record.parent.mkdir()
        target = self.record.parent / 'target.txt'
        self.record.symlink_to(target)
        with self.assertRaisesRegex(CardineError, 'already exists'):
            self.create()
        self.assertFalse(target.exists())
        self.assertTrue(self.record.is_symlink())
        self.assertFalse(self.state.exists())

    def test_failure_at_each_publication_boundary_rolls_back(self):
        link = os.link
        for failed_path in (self.lock, self.record, self.state):
            def fail(source, target):
                if Path(target) == failed_path:
                    raise OSError('injected publication failure')
                return link(source, target)
            with self.subTest(path=failed_path), patch('cardine.tasks.creation.os.link', side_effect=fail):
                with self.assertRaisesRegex(OSError, 'injected'):
                    self.create()
            self.assert_no_pair()

    def test_second_publication_conflict_preserves_unrelated_file(self):
        link = os.link
        def conflict(source, target):
            if Path(target) == self.state:
                self.state.write_text('unrelated')
            return link(source, target)
        with patch('cardine.tasks.creation.os.link', side_effect=conflict):
            with self.assertRaises(FileExistsError):
                self.create()
        self.assertFalse(self.record.exists())
        self.assertEqual(self.state.read_text(), 'unrelated')
        self.assertFalse(self.lock.exists())

    def test_failed_rollback_keeps_journal_for_explicit_recovery(self):
        link, unlink = os.link, Path.unlink
        def fail_publish(source, target):
            if Path(target) == self.state:
                raise OSError('second publication failed')
            return link(source, target)
        def fail_rollback(path, *args, **kwargs):
            if path == self.record:
                raise OSError('rollback failed')
            return unlink(path, *args, **kwargs)
        with patch('cardine.tasks.creation.os.link', side_effect=fail_publish), patch.object(Path, 'unlink', fail_rollback):
            with self.assertRaisesRegex(OSError, 'rollback failed'):
                self.create()
        self.assertTrue(self.lock.exists())
        self.create(recover=True)
        self.assertFalse(self.lock.exists())
        self.assertEqual(load_task_status(self.root)['totals']['queued'], 1)

    def test_concurrent_creation_same_id_has_one_writer(self):
        entered, release = threading.Event(), threading.Event()
        link = os.link
        def pause(source, target):
            if Path(target) == self.record:
                entered.set()
                self.assertTrue(release.wait(10))
            return link(source, target)
        with patch('cardine.tasks.creation.os.link', side_effect=pause), ThreadPoolExecutor() as pool:
            first = pool.submit(self.create)
            try:
                self.assertTrue(entered.wait(10))
                with self.assertRaisesRegex(CardineError, 'in progress'):
                    self.create()
                self.assertTrue(load_task_status(self.root)['diagnostics'])
                with self.assertRaisesRegex(CardineError, 'creation'):
                    read_task_state(self.root, '001', 'single', stop_factory=lambda code, detail, **kw: CardineError(detail))
            finally:
                release.set()
            self.assertEqual(first.result()['id'], '001')
        self.assertEqual(load_task_status(self.root)['totals']['total'], 1)

    def interrupt(self, complete=False):
        # Simulate a process exit, bypassing Python rollback/finally handlers.
        script = '''
import os, sys
from pathlib import Path
from cardine.tasks.creation import create_task
link = os.link
root = Path(sys.argv[1])
def interrupt(source, target):
    target = Path(target)
    if target == root / '.cardine/tasks/001.json':
        if sys.argv[2] == 'complete':
            link(source, target)
        os._exit(77)
    return link(source, target)
os.link = interrupt
create_task(root, '001', Path(sys.argv[3]).read_text())
'''
        proposal = self.root / 'proposal.txt'
        proposal.write_text(self.text)
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        result = subprocess.run([sys.executable, '-c', script, str(self.root),
                                 'complete' if complete else 'partial', str(proposal)], env=environment)
        self.assertEqual(result.returncode, 77)
        self.assertTrue(self.lock.exists())

    def test_interrupted_partial_pair_requires_safe_explicit_recovery(self):
        self.interrupt()
        self.assertTrue(self.record.exists())
        self.assertFalse(self.state.exists())
        with self.assertRaisesRegex(CardineError, '--recover'):
            self.create()
        self.assertTrue(load_task_status(self.root)['diagnostics'])
        self.create(recover=True)
        self.assertFalse(self.lock.exists())
        self.assertEqual(load_task_status(self.root)['totals']['queued'], 1)

    def test_recovery_preserves_complete_pair_and_refuses_changed_partial(self):
        self.interrupt(complete=True)
        before = self.state.read_bytes()
        self.assertTrue(self.create(recover=True)['recovered'])
        self.assertEqual(self.state.read_bytes(), before)
        self.record.unlink()
        self.state.unlink()
        self.interrupt()
        self.record.write_text('changed')
        with self.assertRaisesRegex(CardineError, 'changed file'):
            self.create(recover=True)
        self.assertEqual(self.record.read_text(), 'changed')
        self.assertTrue(self.lock.exists())

    def test_blueprint_loses_status_only_in_product(self):
        self.assertNotIn('Status:', (ROOT / 'templates/single/tasks/TASK_BLUEPRINT.md').read_text())
        original = subprocess.check_output(['git', 'show', 'HEAD:tasks/TASK_BLUEPRINT.md'], cwd=ROOT)
        self.assertEqual((ROOT / 'tasks/TASK_BLUEPRINT.md').read_bytes(), original)

    def test_governed_quick_can_explicitly_lower_required_options(self):
        write_project_config(self.root, 'governed', validation=deepcopy(VALIDATION))
        self.text = ('ID: 001\nCategory: Quick\nOptions: {"authorityRequired": false, '
                     '"expectedCodeSurfaceRequired": false, "review": "not_required"}\n'
                     '## Objective\nSmall.\n## Acceptance Criteria\nVerified.\n'
                     '## Validation\nnone\n## Dependencies\nnone\n')
        self.create()
        state = json.loads(self.state.read_text())
        self.assertEqual(state['contract']['preset'], 'governed')
        self.assertEqual(state['contract']['options']['review'], 'not_required')
        self.assertFalse(state['contract']['options']['authorityRequired'])

    def test_custom_roots_and_milestone_identity(self):
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION),
                             taskIdentity={'mode': 'milestone'}, locations={'taskRoots': ['work/items']})
        text = contract_record('M1-CORE-001')
        result = create_task(self.root, 'm1-core-001', text)
        self.assertEqual(result['id'], 'M1-CORE-001')
        self.assertTrue((self.root / result['record']).is_relative_to(self.root / 'work/items'))
        self.assertEqual((self.root / result['record']).read_text(), text)
        self.assertTrue((self.root / result['state']).exists())


if __name__ == '__main__':
    unittest.main()
