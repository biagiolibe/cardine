"""Developer re-acceptance of the local receipt authority (decision 14, amended 2026-11-07)."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cardine.lifecycle import authorization, receipts
from cardine.shared.errors import CardineError
from cardine.tasks.creation import create_task
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION


def accept(_plan):
    return None


class RuntimeIdentityTest(unittest.TestCase):
    def test_source_runtime_measures_the_existing_file_set(self):
        checkout = Path(__file__).resolve().parent.parent
        patterns = ('src/cardine/**/*.py', 'schemas/*.json', 'capabilities/*.json',
                    'migrations/**/*', 'templates/**/*', 'scripts/*.py')
        expected = {
            str(path.relative_to(checkout)): receipts.digest(path.read_bytes())
            for pattern in patterns for path in checkout.glob(pattern)
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'
        }
        receipts._runtime_identity.cache_clear()
        self.addCleanup(receipts._runtime_identity.cache_clear)
        with patch.dict(os.environ):
            os.environ.pop('CARDINE_ROOT', None)
            runtime, measured = receipts._runtime_identity()

        self.assertEqual(runtime, checkout / 'src/cardine')
        self.assertEqual(measured, receipts.digest(receipts.encoded(expected)))


class AuthorizationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'project'
        self.root.mkdir()
        write_project_config(self.root, 'lean', validation=deepcopy(VALIDATION))
        (self.root / '.gitignore').write_text('.cardine/receipt-authority.json\n.cardine/task-creation.guard\n')
        self.git(self.root, 'init', '-b', 'main')
        self.git(self.root, 'config', 'user.name', 'Authority Test')
        self.git(self.root, 'config', 'user.email', 'authority@example.test')
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-m', 'Policy')
        create_task(self.root, '001', contract_record('001'))
        self.git(self.root, 'add', '.')
        self.git(self.root, 'commit', '-m', 'Task 001')
        self.clone = self.base / 'clone'
        subprocess.run(['git', 'clone', '-q', str(self.root), str(self.clone)], check=True)

    def git(self, root, *args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def state(self, root):
        return json.loads((root / '.cardine/tasks/001.json').read_bytes())

    def test_tracked_receipts_hold_no_machine_identity(self):
        authority = self.state(self.root)['run']['receipts'][-1]['authority']
        self.assertEqual(set(authority), {'policy', 'accepted_main'})
        self.assertNotIn(str(self.base), (self.root / '.cardine/tasks/001.json').read_text())

    def test_clone_is_refused_until_the_developer_accepts_it(self):
        with self.assertRaisesRegex(CardineError, 'cardine authorize'):
            create_task(self.clone, '002', contract_record('002'))
        plan = authorization.plan_authorization(self.clone)
        self.assertEqual(plan.status, 'approval-required')
        self.assertIn('root', plan.changes)
        with self.assertRaisesRegex(CardineError, 'developer terminal'):
            authorization.apply_authorization(plan)
        self.assertFalse((self.clone / '.cardine/receipt-authority.json').exists())
        with self.assertRaisesRegex(CardineError, 'did not match'):
            authorization.apply_authorization(plan, confirm=lambda _plan: 'confirmation did not match')
        self.assertTrue(authorization.apply_authorization(plan, confirm=accept))
        self.assertEqual(authorization.plan_authorization(self.clone).status, 'ready')
        receipts.verify_receipts(self.clone, self.state(self.clone))
        create_task(self.clone, '002', contract_record('002'))
        self.assertFalse(authorization.apply_authorization(authorization.plan_authorization(self.clone)))

    def test_changed_runtime_is_reaccepted_and_existing_states_stay_valid(self):
        with patch.object(receipts, 'runtime_digest_once', return_value='f' * 64):
            with self.assertRaisesRegex(CardineError, 'cardine authorize'):
                receipts.verify_receipts(self.root, self.state(self.root))
            plan = authorization.plan_authorization(self.root)
            self.assertEqual(plan.status, 'approval-required')
            self.assertIn('runtime', plan.changes)
            self.assertFalse({'project', 'root', 'common', 'policy'} & set(plan.changes))
            self.assertTrue(authorization.apply_authorization(plan, confirm=accept))
            receipts.verify_receipts(self.root, self.state(self.root))

    def test_bindings_survive_an_accepted_runtime_update(self):
        bound = receipts.require_authority(self.root)
        self.assertNotIn('runtime', bound)
        (self.root / 'NOTES.md').write_text('later work\n')
        self.git(self.root, 'add', 'NOTES.md')
        self.git(self.root, 'commit', '-m', 'Later work')
        with patch.object(receipts, 'runtime_digest_once', return_value='f' * 64):
            with self.assertRaisesRegex(CardineError, 'cardine authorize'):
                receipts.require_authority(self.root)
            plan = authorization.plan_authorization(self.root)
            self.assertEqual(plan.changes, ('runtime',))
            self.assertTrue(authorization.apply_authorization(plan, confirm=accept))
            # An operation bound before the update still matches after it.
            self.assertEqual(receipts.require_authority(self.root), bound)

    def test_pending_operation_and_tampered_state_block_acceptance(self):
        intent = self.clone / '.cardine/tasks/.001.intent.json'
        intent.write_text(json.dumps({'task_id': '001'}))
        plan = authorization.plan_authorization(self.clone)
        self.assertEqual(plan.status, 'blocked')
        self.assertIn('pending operation', plan.detail)
        with self.assertRaisesRegex(CardineError, 'blocked'):
            authorization.apply_authorization(plan, confirm=accept)
        intent.unlink()
        path = self.clone / '.cardine/tasks/001.json'
        state = self.state(self.clone)
        state['status'] = 'done'
        path.write_text(json.dumps(state))
        plan = authorization.plan_authorization(self.clone)
        self.assertEqual(plan.status, 'blocked')
        self.assertIn('task 001', plan.detail)
        self.assertFalse((self.clone / '.cardine/receipt-authority.json').exists())

    def changed_policy(self):
        path = self.root / '.cardine/project.json'
        path.write_bytes(path.read_bytes() + b'\n')
        self.git(self.root, 'add', '.cardine/project.json')
        self.git(self.root, 'commit', '-m', 'Change policy')
        return receipts.digest(path.read_bytes())

    def test_policy_committed_on_main_is_accepted_beside_earlier_receipts(self):
        policy = self.changed_policy()
        plan = authorization.plan_authorization(self.root)
        self.assertEqual(plan.status, 'approval-required', plan.detail)
        self.assertIn('policy', plan.changes)
        self.assertTrue(authorization.apply_authorization(plan, confirm=accept))
        self.assertEqual(receipts.require_authority(self.root)['policy'], policy)
        receipts.verify_receipts(self.root, self.state(self.root))

    def test_policy_held_only_by_a_branch_does_not_validate_a_receipt(self):
        self.git(self.root, 'switch', '-q', '-c', 'task-999')
        policy = self.changed_policy()
        self.git(self.root, 'switch', '-q', 'main')
        state = self.state(self.root)
        previous = None
        for receipt in state['run']['receipts']:
            receipt['authority']['policy'] = policy
            receipt['predecessor'] = previous
            receipt['digest'] = previous = receipts._receipt_hash(receipt)
        with self.assertRaisesRegex(CardineError, 'differs from accepted policy'):
            receipts.verify_receipts(self.root, state)

    def test_linked_worktree_is_refused(self):
        worktree = self.base / 'linked'
        self.git(self.root, 'worktree', 'add', '-q', str(worktree), '-b', 'other')
        self.assertEqual(authorization.plan_authorization(worktree).status, 'blocked')

    def test_check_lists_a_task_worktree_whose_policy_predates_main(self):
        worktree = self.base / 'task-001'
        self.git(self.root, 'worktree', 'add', '-q', str(worktree), '-b', 'task-001')
        self.assertEqual(authorization.plan_authorization(self.root).task_policies, ())
        self.changed_policy()
        plan = authorization.plan_authorization(self.root)
        self.assertEqual(plan.task_policies,
                         ('task-policy: 001 predates main; cardine run 001 will merge main',))
        self.assertTrue(authorization.apply_authorization(plan, confirm=accept))
        ready = authorization.plan_authorization(self.root)
        self.assertEqual((ready.status, ready.task_policies), ('ready', plan.task_policies))

    def test_a_recorded_policy_is_covered_only_by_main_history(self):
        earlier = receipts.require_authority(self.root)
        self.changed_policy()
        plan = authorization.plan_authorization(self.root)
        authorization.apply_authorization(plan, confirm=accept)
        current = receipts.require_authority(self.root)
        self.assertTrue(receipts.authority_covers(earlier, current, self.root))
        self.git(self.root, 'switch', '-q', '-c', 'task-999')
        path = self.root / '.cardine/project.json'
        path.write_bytes(path.read_bytes() + b'\n')
        self.git(self.root, 'commit', '-q', '-am', 'Branch-only policy')
        branch_policy = receipts.digest(path.read_bytes())
        self.git(self.root, 'switch', '-q', 'main')
        branch_only = dict(earlier, policy=branch_policy)
        self.assertFalse(receipts.authority_covers(branch_only, current, self.root))


if __name__ == '__main__':
    unittest.main()
