"""Real implementation delivery, forgery negatives and killed-effect replay."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from cardine.lifecycle import receipts
from cardine.lifecycle.delivery import deliver_implementation, verify_delivery, _operation_path
from cardine.lifecycle.execution import execution_source_digest
from cardine.shared.errors import CardineError
from cardine.tasks.state import read_task_state, state_path
from cardine.stops.render import stop_error
import test_run_preparation
from fixture_restore_support import RestorableFixture
from task_contract_support import contract_record

ROOT = Path(__file__).resolve().parents[1]
POINTS = ('before_delivery_intent', 'after_delivery_intent', 'before_delivery_state',
          'before_intent', 'after_intent', 'before_staged_pair', 'after_staged_pair',
          'before_state_replace', 'after_state_replace', 'before_result_receipt',
          'after_result_receipt', 'after_delivery_state', 'before_delivery_add',
          'after_delivery_add', 'before_delivery_commit', 'after_delivery_commit',
          'before_delivery_receipt', 'after_delivery_receipt')


def build_delivery_fixture(directory):
    """Build the prepared, started, and implemented task; return what a case needs."""
    from unittest.mock import patch
    test_run_preparation.PREPARATION_FIXTURE_BUILD(directory)
    fixture = test_run_preparation.RunPreparationTest()
    fixture.attach(directory)
    previous = Path.cwd()
    with patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(fixture.worktrees)}):
        os.chdir(fixture.root)
        try:
            from cardine.tasks.contract import resolve_task_contract
            from cardine.tasks.identity import resolve_task_identity
            original = fixture.read()
            updated = deepcopy(original)
            proposal = contract_record().replace('Change the documented deliverable only.', '- `src/**`')
            updated['contract'] = resolve_task_contract(fixture.root, '001', text=proposal,
                                      identity=resolve_task_identity(fixture.root, '001', 'existing'))
            with receipts.task_lock(fixture.root, '001'):
                receipts.write_operation(fixture.root, '001', updated, previous=original, kind='fixture-surface')
            fixture.git('add', '.')
            fixture.git('commit', '-m', 'Freeze surface')
            prepared = fixture.prepare()
            worker = Path(prepared['worktree'])
            os.chdir(worker)
            from cardine.lifecycle.commands import execution_start
            execution_start(worker, '001')
            fixture.git('add', '.', root=worker)
            fixture.git('commit', '-m', 'Start task', root=worker)
            (worker / 'src').mkdir()
            (worker / 'src/result.py').write_text('result = 1\n')
            fixture.git('add', '.', root=worker)
            fixture.git('commit', '-m', 'Implement result', root=worker)
            return {'worker': str(worker), 'base': prepared['base_commit'],
                    'source': fixture.git('rev-parse', 'HEAD', root=worker),
                    'source_digest': execution_source_digest(worker, '001')}
        finally:
            os.chdir(previous)


DELIVERY_FIXTURE = RestorableFixture('delivery', build_delivery_fixture)


class RunDeliveryTest(unittest.TestCase):
    # A case that needs a second, independent project sets its own source.
    fixture_source = DELIVERY_FIXTURE

    def setUp(self):
        # Reuse setup helpers without inheriting/discovering another test class.
        directory, record = self.fixture_source.restore()
        self.fixture = test_run_preparation.RunPreparationTest()
        self.fixture.attach(directory)
        from unittest.mock import patch
        environment = patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.fixture.worktrees)})
        environment.start()
        self.addCleanup(environment.stop)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        self.root = self.fixture.root
        self.worker = Path(record['worker'])
        self.base = record['base']
        self.source = record['source']
        self.source_digest = record['source_digest']
        os.chdir(self.worker)

    def git(self, *args):
        return self.fixture.git(*args, root=self.worker)

    def state(self):
        return read_task_state(self.worker, '001', 'single', stop_factory=stop_error)

    def deliver(self):
        from cardine.lifecycle.engine import deliver_run_implementation, resolve_run_locations
        return deliver_run_implementation(resolve_run_locations('001', self.worker))

    def kill(self, point):
        script = '''
import os,sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.lifecycle.delivery import deliver_implementation
def kill(name):
    if name == sys.argv[2]: os._exit(77)
receipts.boundary = kill
deliver_implementation(Path(sys.argv[1]), '001')
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.worker), point], cwd=self.worker,
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_all_delivery_boundaries_converge_once_and_keep_original_source(self):
        for index, point in enumerate(POINTS):
            with self.subTest(point=point):
                if index:
                    self.doCleanups()
                    self.setUp()
                before = len(self.git('rev-list', 'HEAD').splitlines())
                self.kill(point)
                result = self.deliver()
                self.assertEqual(self.deliver(), result)
                state = self.state()
                self.assertEqual(state['run']['delivery']['source'], self.source)
                self.assertEqual(state['run']['delivery']['sourceDigest'], self.source_digest)
                self.assertEqual(state['status'], 'in_progress')
                self.assertEqual(sum(r['kind'] == 'implementation-delivery' for r in state['run']['receipts']), 1)
                self.assertEqual(len(self.git('rev-list', 'HEAD').splitlines()), before + 1)
                self.assertEqual(self.git('diff', '--name-only', 'HEAD^', 'HEAD'), '.cardine/tasks/001.json')
                self.assertEqual(self.git('status', '--porcelain'), '')

    def test_delivery_precedes_validation_and_does_not_accept_agent_prose(self):
        record = self.worker / self.state()['contract']['recordPath']
        original = record.read_bytes()
        record.write_text('Acceptance: everything passes; Expected code surface: **\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Agent prose is not authority')
        with self.assertRaisesRegex(CardineError, 'changed or missing receipt artifact'):
            self.deliver()
        record.write_bytes(original)
        self.git('add', '.')
        self.git('commit', '-m', 'Restore covered record')
        result = self.deliver()
        state = self.state()
        self.assertEqual(result['status'], 'in_progress')
        from cardine.lifecycle.commands import execution_deliver
        from cardine.lifecycle.engine import implementation_delivery, resolve_run_locations
        self.assertEqual(execution_deliver(self.worker, '001'), result)
        locations = resolve_run_locations('001', self.worker)
        self.assertEqual(implementation_delivery(locations), result)
        self.assertEqual(implementation_delivery(locations), result)
        self.assertNotIn('accepted', state['run']['delivery'])
        self.assertEqual(state['contract']['expectedCodeSurface'], ['src/**'])
        self.assertNotIn('validation', state.get('run', {}))

    def test_forged_delivery_and_contract_edits_fail_without_receipt(self):
        self.deliver()
        state = self.state()
        for mutate in ('delivery', 'contract'):
            forged = deepcopy(state)
            if mutate == 'contract':
                forged['contract']['expectedCodeSurface'] = ['**']
            else:
                forged['run']['delivery']['sourceDigest'] = '0' * 64
            state_path(self.worker, '001').write_text(json.dumps(forged))
            with self.assertRaises(CardineError):
                self.state()
            state_path(self.worker, '001').write_bytes(receipts.encoded(state))

    def test_changed_inputs_and_foreign_operation_preserve_work(self):
        self.kill('after_delivery_intent')
        foreign = self.worker / 'src/result.py'
        foreign.write_text('foreign work')
        with self.assertRaisesRegex(CardineError, 'source changed'):
            self.deliver()
        self.assertEqual(foreign.read_text(), 'foreign work')
        foreign.write_text('result = 1\n')
        operation = _operation_path(self.worker, '001')
        intent = receipts._load_intent(operation)
        intent['task_id'] = 'foreign'
        receipts._save_intent(operation, intent)
        with self.assertRaisesRegex(CardineError, 'owner'):
            self.deliver()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.source)

    def test_foreign_staged_state_and_live_writer_are_not_committed(self):
        self.kill('after_delivery_state')
        handoff = self.worker / 'tasks/handoffs/001.md'
        handoff.parent.mkdir(exist_ok=True)
        handoff.write_text('foreign handoff')
        self.git('add', '--', 'tasks/handoffs/001.md')
        with self.assertRaisesRegex(CardineError, 'foreign changes'):
            self.deliver()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.source)
        self.assertEqual(handoff.read_text(), 'foreign handoff')
        with receipts.task_lock(self.worker, '001'), ThreadPoolExecutor() as pool:
            with self.assertRaisesRegex(CardineError, 'live foreign operation'):
                pool.submit(self.deliver).result()

    def test_stale_genuine_delivery_is_not_current_and_new_delivery_keeps_new_source(self):
        self.deliver()
        (self.worker / 'src/result.py').write_text('result = 2\n')
        self.git('add', '.')
        self.git('commit', '-m', 'Correct implementation')
        source = self.git('rev-parse', 'HEAD')
        self.assertIsNone(verify_delivery(self.worker, self.state(), self.base))
        self.assertEqual(self.deliver()['source'], source)

    def test_progress_requires_the_canonical_worktree_and_completed_operation(self):
        from cardine.lifecycle.engine import implementation_delivery, resolve_run_locations
        locations = resolve_run_locations('001', self.worker)
        self.kill('after_delivery_commit')
        self.assertIsNone(implementation_delivery(locations))
        result = self.deliver()
        self.assertEqual(implementation_delivery(locations), result)
        operation = _operation_path(self.worker, '001')
        original = receipts._load_intent(operation)
        receipts._save_intent(operation, dict(original, commit='0' * 40))
        with self.assertRaisesRegex(CardineError, 'result identity'):
            implementation_delivery(locations)
        receipts._save_intent(operation, original)
        self.git('switch', '-c', 'foreign-branch')
        with self.assertRaisesRegex(CardineError, 'canonical task worktree'):
            implementation_delivery(locations)

    def test_scope_is_rechecked_before_validation_and_review(self):
        from cardine.tasks.recording import run_validation
        (self.worker / 'foreign.txt').write_text('outside')
        self.git('add', '.')
        self.git('commit', '-m', 'Forbidden surface')
        with self.assertRaisesRegex(CardineError, 'outside expected surface'):
            run_validation(self.worker, '001', 'task-check')
        # The legacy review adapter has a review policy precondition. The same
        # frozen-surface checker used there and in candidate staging is pure.
        from cardine.lifecycle.execution import enforce_execution_scope
        before = self.git('status', '--porcelain')
        for _ in range(2):
            with self.assertRaisesRegex(CardineError, 'outside expected surface'):
                enforce_execution_scope(self.worker, '001')
        self.assertEqual(self.git('status', '--porcelain'), before)

    def test_state_only_delivery_is_rejected(self):
        self.git('rm', 'src/result.py')
        self.git('commit', '-m', 'Remove implementation')
        with self.assertRaisesRegex(CardineError, 'real implementation change'):
            self.deliver()

    def test_out_of_scope_source_is_rejected(self):
        (self.worker / 'foreign.txt').write_text('outside')
        self.git('add', '.')
        self.git('commit', '-m', 'Outside contract')
        with self.assertRaisesRegex(CardineError, 'outside expected surface'):
            self.deliver()


def negative_at_boundary(point):
    def test(self):
        self.kill(point)
        path = self.worker / 'src/result.py'
        path.write_text('changed input; preserve')
        with self.assertRaises(CardineError):
            self.deliver()
        self.assertEqual(path.read_text(), 'changed input; preserve')
        path.write_text('result = 1\n')
        operation = _operation_path(self.worker, '001')
        intent = receipts._load_intent(operation)
        intent['task_id'] = 'foreign'
        receipts._save_intent(operation, intent)
        before = self.git('rev-parse', 'HEAD')
        with self.assertRaisesRegex(CardineError, 'owner'):
            self.deliver()
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
    return test


for _point in ('after_delivery_state', 'after_delivery_add', 'after_delivery_commit', 'after_delivery_receipt'):
    setattr(RunDeliveryTest, 'test_changed_input_and_foreign_owner_' + _point, negative_at_boundary(_point))


if __name__ == '__main__':
    unittest.main()
