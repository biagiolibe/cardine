"""Receipt coverage, explicit clone authority, concurrency and killed-writer replay."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.tasks.contract_update import update_task_contract
from cardine.tasks.creation import create_task
from cardine.tasks.state import validate_task_state
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION

ROOT = Path(__file__).resolve().parents[1]
POINTS = ('before_intent', 'after_intent', 'before_staged_pair', 'after_staged_pair',
          'before_state_replace', 'after_state_replace', 'before_result_receipt', 'after_result_receipt')


class RunReceiptsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
        self.text = contract_record()
        self.record = self.root / 'tasks/001.md'
        self.path = self.root / '.cardine/tasks/001.json'

    def create(self):
        return create_task(self.root, '001', self.text)

    def state(self):
        return json.loads(self.path.read_bytes())

    def revise(self):
        self.record.write_text(self.text.replace('## Objective', 'Review: required\n## Objective'))
        return update_task_contract(self.root, '001')

    def git(self, *args, root=None):
        return subprocess.check_output(['git', '-C', str(root or self.root), *args],
                                       stderr=subprocess.DEVNULL, text=True).strip()

    def init_git(self):
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Receipt Test')
        self.git('config', 'user.email', 'receipt@example.test')
        self.git('add', '.')
        self.git('commit', '-m', 'Initial policy')

    def kill(self, point, *, revision=False):
        proposal = self.root / 'proposal.txt'
        proposal.write_text(self.text)
        script = '''
import os, sys
from pathlib import Path
from cardine.lifecycle import receipts
from cardine.tasks.creation import create_task
from cardine.tasks.contract_update import update_task_contract
def stop(name):
    if name == sys.argv[2]: os._exit(77)
receipts.boundary = stop
root = Path(sys.argv[1])
if sys.argv[3] == 'revision':
    update_task_contract(root, '001')
else:
    create_task(root, '001', (root / 'proposal.txt').read_text())
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), point,
                                 'revision' if revision else 'creation'],
                                env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 77, result.stderr)

    def test_creation_killed_before_and_after_all_four_boundaries(self):
        for point in POINTS:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory).resolve()
                self.record = self.root / 'tasks/001.md'
                self.path = self.root / '.cardine/tasks/001.json'
                write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
                self.kill(point)
                intent = receipts._intent_path(self.root, '001')
                before = receipts._load_intent(intent)['state'] if intent.exists() else None
                self.create()  # Same operation, same input, no recovery switch.
                state = self.state()
                receipts.verify_receipts(self.root, state)
                self.assertEqual(len(state['run']['receipts']), 1)
                self.assertEqual(state['transitions'], [])
                if before is not None:
                    self.assertEqual(state, before)
                self.assertEqual(self.record.read_text(), self.text)
                self.assertFalse(intent.exists())
                self.assertEqual(list(self.root.rglob('*.stage')), [])

    def test_revision_killed_before_and_after_all_four_boundaries(self):
        for point in POINTS:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                self.root = Path(directory).resolve()
                self.record = self.root / 'tasks/001.md'
                self.path = self.root / '.cardine/tasks/001.json'
                write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
                self.create()
                original = self.state()['run']['receipts'][0]
                self.record.write_text(self.text.replace('## Objective', 'Review: required\n## Objective'))
                self.kill(point, revision=True)
                update_task_contract(self.root, '001')
                state = self.state()
                receipts.verify_receipts(self.root, state)
                self.assertEqual(len(state['run']['receipts']), 2)
                self.assertEqual(state['run']['receipts'][0], original)
                self.assertEqual(state['run']['receipts'][1]['predecessor'], original['digest'])
                self.assertEqual(len(state['contract_history']), 1)
                self.assertFalse(update_task_contract(self.root, '001')['updated'])
                self.assertEqual(self.state(), state)

    def test_changed_staged_bytes_fail_closed_and_keep_foreign_files(self):
        self.kill('after_staged_pair')
        intent = receipts._load_intent(receipts._intent_path(self.root, '001'))
        staged = self.root / intent['files']['tasks/001.md']['staged']
        staged.write_text('foreign bytes')
        foreign = self.root / 'unrelated.txt'
        foreign.write_text('keep me')
        with self.assertRaisesRegex(CardineError, 'changed staged bytes'):
            self.create()
        self.assertFalse(self.record.exists())
        self.assertFalse(self.path.exists())
        self.assertEqual(staged.read_text(), 'foreign bytes')
        self.assertEqual(foreign.read_text(), 'keep me')

    def test_changed_proposal_and_changed_published_bytes_refuse_replay(self):
        self.kill('before_state_replace')
        before = self.record.read_bytes()
        with self.assertRaisesRegex(CardineError, 'different command'):
            update_task_contract(self.root, '001')
        self.text += '\nChanged input.\n'
        with self.assertRaisesRegex(CardineError, 'changed creation input'):
            self.create()
        self.assertEqual(self.record.read_bytes(), before)
        self.text = before.decode()
        self.record.write_text('foreign record')
        with self.assertRaisesRegex(CardineError, 'changed (file|staged bytes)'):
            self.create()
        self.assertEqual(self.record.read_text(), 'foreign record')

    def test_changed_source_refuses_replay(self):
        self.init_git()
        self.kill('after_intent')
        (self.root / 'unrelated').write_text('new source')
        self.git('add', 'unrelated')
        self.git('commit', '-m', 'Concurrent source')
        with self.assertRaisesRegex(CardineError, 'source changed'):
            self.create()
        self.assertFalse(self.record.exists())

    def test_state_contract_and_record_edits_are_uncovered(self):
        self.create()
        original = self.state()
        for coherent in (False, True):
            state = deepcopy(original)
            state['contract']['options']['validationRetryLimit'] += 1
            if coherent:
                # Schema-valid, internally coherent changes still lack a writer result.
                state['contract']['options']['review'] = 'required'
            validate_task_state(state, '001', 'single')
            with self.assertRaisesRegex(CardineError, 'changed contract'):
                receipts.verify_receipts(self.root, state)
        self.record.write_text(self.text + '\nforeign\n')
        with self.assertRaisesRegex(CardineError, 'artifact'):
            receipts.verify_receipts(self.root, original)
        self.record.write_text(self.text)
        state = deepcopy(original)
        state['transitions'] = [dict(at='2026-10-23T00:00:00Z', commit='a'*40,
                                     **{'from': 'queued', 'to': 'in_progress'})]
        state['status'] = 'in_progress'
        validate_task_state(state, '001', 'single')
        with self.assertRaisesRegex(CardineError, 'changed state'):
            receipts.verify_receipts(self.root, state)

    def test_chain_tampering_missing_receipts_and_fabricated_result_refuse(self):
        self.create()
        self.revise()
        original = self.state()
        for mutation in ('chain', 'missing', 'result'):
            state = deepcopy(original)
            if mutation == 'chain':
                state['run']['receipts'][1]['predecessor'] = 'f'*64
            elif mutation == 'missing':
                state.pop('run')
            else:
                state['run']['receipts'][0]['result'] = 'invented'
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, CardineError)):
                receipts.verify_receipts(self.root, state)

    def test_policy_and_runtime_override_cannot_authorize_themselves(self):
        self.create()
        authority = receipts.require_authority(self.root)
        policy = self.root / '.cardine/project.json'
        original = policy.read_bytes()
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION),
                             taskDefaults={'review': 'not_required'})
        with self.assertRaisesRegex(CardineError, 'reauthorization'):
            receipts.verify_receipts(self.root, self.state())
        from cardine.tasks.contract import resolve_task_contract
        coherent = self.state()
        coherent['contract'] = resolve_task_contract(self.root, '001', text=self.text)
        validate_task_state(coherent, '001', 'single')
        with self.assertRaisesRegex(CardineError, 'reauthorization'):
            receipts.verify_receipts(self.root, coherent)
        with self.assertRaisesRegex(CardineError, 'reauthorization'):
            create_task(self.root, '002', contract_record('002'))
        policy.write_bytes(original)
        with self.assertRaisesRegex(CardineError, 'changed contract'):
            receipts.verify_receipts(self.root, coherent)
        with patch.object(receipts, 'observed_authority', return_value=dict(authority, runtime='f'*64)):
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.verify_receipts(self.root, self.state())
        with patch.dict(os.environ, {'CARDINE_WORKTREE_ROOT': str(self.root / 'foreign-root')}):
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.verify_receipts(self.root, self.state())
        # Environment runtime labels do not select or bless a different runtime.
        with patch.dict(os.environ, {'CARDINE_RUNTIME': '/foreign/runtime'}):
            self.assertEqual(receipts.require_authority(self.root), authority)
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            module = runtime / 'src/cardine/lifecycle/receipts.py'
            module.parent.mkdir(parents=True)
            module.write_text('foreign runtime')
            with patch.object(receipts, '__file__', str(module)):
                with self.assertRaisesRegex(CardineError, 'reauthorization'):
                    receipts.verify_receipts(self.root, self.state())

    def test_clone_requires_explicit_policy_acceptance_and_never_imports_state(self):
        self.init_git()
        self.create()
        accepted_main = receipts.require_authority(self.root)['accepted_main']
        self.git('add', '.')
        self.git('commit', '-m', 'Portable receipt')
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / 'clone'
            subprocess.run(['git', 'clone', '-q', str(self.root), str(clone)], check=True)
            state = json.loads((clone / '.cardine/tasks/001.json').read_bytes())
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.verify_receipts(clone, state, portable=True)
            observed = dict(receipts.observed_authority(clone), accepted_main=accepted_main)
            receipts.authorize_project(clone, accepted=observed)
            receipts.verify_receipts(clone, state, portable=True)
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                receipts.verify_receipts(clone, state)
            imported = receipts.reauthorize_task(clone, '001')
            receipts.verify_receipts(clone, imported)
            self.assertEqual(len(imported['run']['receipts']), 2)
            self.assertEqual(receipts.reauthorize_task(clone, '001'), imported)
            state.pop('run')
            with self.assertRaisesRegex(CardineError, 'missing completed'):
                receipts.verify_receipts(clone, state, portable=True)
            (clone / '.cardine/receipt-authority.json').unlink()
            with self.assertRaisesRegex(CardineError, 'reauthorization'):
                create_task(clone, '002', contract_record('002'))

    def test_live_foreign_writer_and_unsafe_paths_refuse_without_effects(self):
        self.create()
        before = self.path.read_bytes()
        with receipts.task_lock(self.root, '001'), ThreadPoolExecutor() as pool:
            future = pool.submit(lambda: update_task_contract(self.root, 'task-001'))
            with self.assertRaisesRegex(CardineError, 'live foreign operation'):
                future.result()
        self.assertEqual(self.path.read_bytes(), before)
        from cardine.tasks.state import read_task_state
        read_bytes = Path.read_text
        def start_during_read(path, *args, **kwargs):
            result = read_bytes(path, *args, **kwargs)
            if path == self.path:
                receipts._intent_path(self.root, '001').write_text('reader barrier')
            return result
        with patch.object(Path, 'read_text', start_during_read):
            with self.assertRaisesRegex(CardineError, 'creation changed during read'):
                read_task_state(self.root, '001', 'single',
                                stop_factory=lambda code, detail, **kw: CardineError(detail))
        receipts._intent_path(self.root, '001').unlink()
        for path in ('../outside', '/absolute', '.'):
            with self.assertRaises(CardineError):
                receipts.safe_path(self.root, path)
        with tempfile.TemporaryDirectory() as directory:
            (self.root / 'link').symlink_to(directory)
            with self.assertRaisesRegex(CardineError, 'symlink'):
                receipts.safe_path(self.root, 'link/state')
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_foreign_state_at_result_boundary_is_never_replaced(self):
        self.create()
        self.record.write_text(self.text.replace('Priority: P1', 'Priority: P0'))
        def foreign(name):
            if name == 'before_result_receipt':
                self.path.write_text('foreign state')
        with patch.object(receipts, 'boundary', side_effect=foreign):
            with self.assertRaisesRegex(CardineError, 'state changed before result'):
                update_task_contract(self.root, '001')
        self.assertEqual(self.path.read_text(), 'foreign state')
        self.assertTrue(receipts.pending_operation(self.root, '001'))
        with self.assertRaisesRegex(CardineError, 'changed file'):
            update_task_contract(self.root, '001')
        self.assertEqual(self.path.read_text(), 'foreign state')

    def test_task_branch_policy_cannot_pin_itself_as_accepted_main(self):
        self.init_git()
        self.git('switch', '-c', 'task-001')
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION),
                             taskDefaults={'review': 'not_required'})
        with self.assertRaisesRegex(CardineError, 'policy differs from accepted main'):
            self.create()
        self.assertFalse(self.record.exists())
        self.assertFalse(self.path.exists())
        self.assertFalse((self.root / '.cardine/receipt-authority.json').exists())

    def test_authority_acceptance_and_observation_are_explicit_and_read_only(self):
        observed = receipts.observed_authority(self.root)
        self.assertEqual(receipts.observed_authority(self.root), observed)
        self.assertFalse((self.root / '.cardine/receipt-authority.json').exists())
        with self.assertRaisesRegex(CardineError, 'reauthorization'):
            receipts.require_authority(self.root)
        with self.assertRaisesRegex(CardineError, 'accept'):
            receipts.authorize_project(self.root, accepted=dict(observed, policy='f'*64))
        receipts.authorize_project(self.root, accepted=observed)
        self.assertEqual(receipts.require_authority(self.root), observed)


if __name__ == '__main__':
    unittest.main()
