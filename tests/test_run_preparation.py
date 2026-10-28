"""Receipt-gated readers and killed preparation/start convergence (RE1c)."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.stops.render import stop_error
from cardine.tasks.creation import create_task
from cardine.tasks.state import read_task_state
from cardine.tasks.transitions import transition_task_state
from cardine.worktree.checkout import prepare_task_worktree, inspect_task_worktree
from fixture_restore_support import RestorableFixture
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION

ROOT = Path(__file__).resolve().parents[1]
PREPARATION = ('before_preparation_intent', 'after_preparation_intent',
               'before_branch_create', 'after_branch_create',
               'before_worktree_registration', 'after_worktree_registration',
               'before_lifecycle_json', 'after_lifecycle_json')
TRANSITION = ('before_intent', 'after_intent', 'before_staged_pair', 'after_staged_pair',
              'before_state_replace', 'after_state_replace', 'before_result_receipt', 'after_result_receipt')


def build_preparation_fixture(directory):
    """Build the repository with its frozen task under a directory; return nothing to remember."""
    from unittest.mock import patch
    root = directory / 'project'
    root.mkdir()
    with patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(directory / 'worktrees')}):
        test = RunPreparationTest()
        test.attach(directory)
        test.git('init', '-b', 'main')
        test.git('config', 'user.name', 'Preparation Test')
        test.git('config', 'user.email', 'preparation@example.test')
        write_project_config(root, 'lean', validation=deepcopy(VALIDATION))
        test.git('add', '.')
        test.git('commit', '-m', 'Initial policy')
        create_task(root, '001', contract_record())
        test.git('add', '.')
        test.git('commit', '-m', 'Create task')
    return {}


PREPARATION_FIXTURE_BUILD = build_preparation_fixture
PREPARATION_FIXTURE = RestorableFixture('preparation', build_preparation_fixture)


class RunPreparationTest(unittest.TestCase):
    def attach(self, directory):
        self.root = directory / 'project'
        self.worktrees = directory / 'worktrees'
        self.state_path = self.root / '.cardine/tasks/001.json'

    def setUp(self):
        # The fixture is restored into the same path; the environment and the
        # working directory stay per case.
        directory, _ = PREPARATION_FIXTURE.restore()
        self.attach(directory)
        from unittest.mock import patch
        environment = patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.worktrees)})
        environment.start()
        self.addCleanup(environment.stop)
        previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)

    def git(self, *args, root=None):
        return subprocess.check_output(['git', '-C', str(root or self.root), *args],
                                       text=True, stderr=subprocess.DEVNULL).strip()

    def prepare(self, **kwargs):
        return prepare_task_worktree('001', self.worktrees, self.root, **kwargs)

    def read(self, task_id='001'):
        return read_task_state(self.root, task_id, 'single', stop_factory=stop_error, require_contract=True)

    def kill(self, point, command='prepare'):
        script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.tasks.transitions import transition_task_state
from cardine.worktree.checkout import prepare_task_worktree
def stop(name):
    if name == sys.argv[2]: os._exit(77)
receipts.boundary = stop
root = Path(sys.argv[1])
if sys.argv[3] == 'prepare': prepare_task_worktree('001', root.parent / 'worktrees', root)
elif sys.argv[3] == 'resume': prepare_task_worktree('001', root.parent / 'worktrees', root, resume=True)
else: transition_task_state(root, '001', 'in_progress')
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), point, command],
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_preparation_all_effect_boundaries_converge_without_state_transition(self):
        for point in PREPARATION:
            with self.subTest(point=point):
                # Each killed process receives a fresh independent project.
                if point != PREPARATION[0]:
                    self.tearDown()
                    self.doCleanups()
                    self.setUp()
                original = self.state_path.read_bytes()
                self.kill(point)
                result = self.prepare()
                again = self.prepare()
                self.assertEqual(result['base_commit'], again['base_commit'])
                self.assertEqual(result['started_at'], again['started_at'])
                self.assertEqual(self.state_path.read_bytes(), original)
                self.assertEqual(len(self.git('worktree', 'list', '--porcelain').split('worktree ')) - 1, 2)
                self.assertEqual(self.read()['status'], 'queued')

    def test_start_all_receipt_boundaries_converge_once(self):
        for point in TRANSITION:
            with self.subTest(point=point):
                if point != TRANSITION[0]:
                    self.doCleanups()
                    self.setUp()
                self.kill(point, 'transition')
                state = transition_task_state(self.root, '001', 'in_progress')
                repeated = transition_task_state(self.root, '001', 'in_progress')
                self.assertEqual(state, repeated)
                self.assertEqual(len(state['transitions']), 1)
                self.assertEqual(len(state['run']['receipts']), 2)
                receipts.verify_receipts(self.root, state)

    def test_execution_start_replays_its_exact_interrupted_transition(self):
        from cardine.lifecycle.commands import execution_start
        prepared = self.prepare()
        worktree = Path(prepared['worktree'])
        os.chdir(worktree)
        script = """
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.lifecycle.commands import execution_start
def stop(name):
    if name == 'after_state_replace': os._exit(77)
receipts.boundary = stop
execution_start(Path(sys.argv[1]), '001')
"""
        result = subprocess.run([sys.executable, '-c', script, str(worktree)], cwd=worktree,
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)
        state = execution_start(worktree, '001')['state']
        self.assertEqual(execution_start(worktree, '001')['state'], state)
        self.assertEqual(len(state['transitions']), 1)
        self.assertEqual(self.read()['status'], 'queued')

    def test_task_lock_is_shared_by_primary_and_linked_checkout(self):
        from concurrent.futures import ThreadPoolExecutor
        prepared = self.prepare()
        worker = Path(prepared['worktree'])
        with receipts.task_lock(self.root, '001'), ThreadPoolExecutor() as pool:
            future = pool.submit(transition_task_state, worker, '001', 'in_progress')
            with self.assertRaisesRegex(CardineError, 'live foreign operation'):
                future.result()
        self.assertEqual(self.read()['status'], 'queued')
        self.assertEqual(read_task_state(worker, '001', 'single', stop_factory=stop_error)['status'], 'queued')

    def test_changed_preparation_input_and_live_foreign_writer_refuse(self):
        from cardine.worktree.preparation import preparation_lock
        from cardine.tasks.identity import resolve_task_identity
        from concurrent.futures import ThreadPoolExecutor
        identity = resolve_task_identity(self.root, '001', 'existing')
        with preparation_lock(self.root, identity), ThreadPoolExecutor() as pool:
            future = pool.submit(self.prepare)
            with self.assertRaisesRegex(CardineError, 'live foreign preparation'):
                future.result()
        self.kill('after_preparation_intent')
        transition_task_state(self.root, '001', 'in_progress')
        with self.assertRaisesRegex(CardineError, 'task input changed'):
            self.prepare()
        self.assertEqual(self.git('branch', '--list', 'task-001'), '')
        self.assertEqual(len(self.git('worktree', 'list', '--porcelain').split('worktree ')) - 1, 1)

    def test_coherent_state_contract_and_dependency_forgery_are_rejected(self):
        original = self.read()
        state = deepcopy(original)
        state['status'] = 'done'
        state['transitions'] = [dict(at='2026-10-23T00:00:00Z', commit='a'*40,
                                     **{'from': 'queued', 'to': 'in_progress'}),
                                dict(at='2026-10-23T00:00:01Z', commit='a'*40,
                                     **{'from': 'in_progress', 'to': 'done'})]
        self.state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(CardineError, 'changed state'):
            self.read()
        proposal = contract_record('002').replace('## Dependencies\nnone', '## Dependencies\n001')
        with self.assertRaisesRegex(CardineError, 'invalid dependency'):
            create_task(self.root, '002', proposal)
        self.assertFalse((self.root / '.cardine/tasks/002.json').exists())
        self.state_path.write_text(json.dumps(original))
        original['contract']['options']['review'] = 'required'
        self.state_path.write_text(json.dumps(original))
        with self.assertRaisesRegex(CardineError, 'changed contract'):
            self.prepare()

    def test_f09_coherent_registration_edit_refuses_without_repair(self):
        self.prepare()
        path = next((self.root / '.git/cardine-worktrees').glob('*.json'))
        # Select the registration, not the separate preparation operation.
        path = self.root / '.git/cardine-worktrees/001.json'
        if not path.exists():
            path = next(p for p in path.parent.glob('*.json') if not p.name.endswith('.preparation.json'))
        state = json.loads(path.read_bytes())
        state['started_at'] = '2000-01-01T00:00:00Z'
        path.write_text(json.dumps(state))
        before = path.read_bytes()
        with self.assertRaisesRegex(CardineError, 'changed worktree preparation'):
            self.prepare(resume=True)
        self.assertEqual(path.read_bytes(), before)
        from cardine.worktree.checkout import active_worktree_task, registered_worktree_task_states
        self.assertEqual(registered_worktree_task_states(self.root), [])
        worker = Path(state['worktree'])
        self.assertIsNone(active_worktree_task(worker))

    def test_dirty_owned_resume_and_changed_root_preserve_foreign_work(self):
        prepared = self.prepare()
        worktree = Path(prepared['worktree'])
        from cardine.worktree.checkout import active_worktree_task, registered_worktree_task_states
        self.assertEqual(registered_worktree_task_states(self.root), [{'task_id': '001', 'status': 'queued'}])
        self.assertEqual(active_worktree_task(worktree)['task_id'], '001')
        foreign = worktree / 'implementation.txt'
        foreign.write_text('unfinished implementation')
        report, ready = inspect_task_worktree('001', self.worktrees, self.root, resume=True,
                                               require_effective_worktree=False)
        self.assertFalse(ready, report)  # The flag cannot invent durable Resume authority.
        self.assertEqual(report['errors'], ['dirty-worktree'])
        result = self.prepare(resume=True)
        self.assertTrue(result['dirty'])
        report, ready = inspect_task_worktree('001', self.worktrees, self.root, resume=True,
                                               require_effective_worktree=False)
        self.assertTrue(ready, report)
        with self.assertRaises(CardineError):
            prepare_task_worktree('001', self.worktrees.parent / 'other', self.root)
        self.assertEqual(foreign.read_text(), 'unfinished implementation')
        self.assertEqual(self.read()['status'], 'queued')

    def test_resume_receipt_survives_both_effect_boundaries(self):
        from cardine.worktree.preparation import _path
        from cardine.tasks.identity import resolve_task_identity
        worker = Path(self.prepare()['worktree'])
        (worker / 'unfinished').write_text('keep')
        path = _path(self.root, resolve_task_identity(self.root, '001', 'existing'))
        original = receipts._load_intent(path)
        for side in ('before', 'after'):
            receipts._save_intent(path, original)
            self.kill(side + '_preparation_resume', 'resume')
            self.prepare(resume=True)
            self.assertTrue(receipts._load_intent(path)['resume'])
            self.assertEqual(receipts._load_intent(path)['operation_id'], original['operation_id'])
            self.assertTrue(inspect_task_worktree('001', self.worktrees, self.root, resume=True,
                                                require_effective_worktree=False)[1])
            self.assertEqual((worker / 'unfinished').read_text(), 'keep')

    def test_foreign_collision_changed_input_and_foreign_owner_refuse(self):
        self.kill('after_branch_create')
        operation = next((self.root / '.git/cardine-worktrees').glob('*.preparation'))
        intent = receipts._load_intent(operation)
        path = Path(intent['binding']['worktree'])
        path.mkdir(parents=True)
        foreign = path / 'foreign'
        foreign.write_text('preserve')
        with self.assertRaisesRegex(CardineError, 'collision'):
            self.prepare()
        self.assertEqual(foreign.read_text(), 'preserve')
        intent['binding']['task_id'] = 'foreign'
        receipts._save_intent(operation, intent)
        with self.assertRaisesRegex(CardineError, 'owner changed'):
            self.prepare()
        self.assertEqual(foreign.read_text(), 'preserve')

    def test_changed_transition_command_does_not_replay_foreign_intent(self):
        self.kill('after_intent', 'transition')
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(CardineError, 'different command'):
            transition_task_state(self.root, '001', 'cancelled', adapter=__import__('control_support').adapter(), cancellation_authority='owner', reason='stop')
        self.assertEqual(self.state_path.read_bytes(), before)
        transition_task_state(self.root, '001', 'in_progress')


if __name__ == '__main__':
    unittest.main()
