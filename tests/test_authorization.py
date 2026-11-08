"""Developer re-acceptance of the local receipt authority (decision 14, amended 2026-11-07)."""
from copy import deepcopy
import json
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

    def test_linked_worktree_is_refused(self):
        worktree = self.base / 'linked'
        self.git(self.root, 'worktree', 'add', '-q', str(worktree), '-b', 'other')
        self.assertEqual(authorization.plan_authorization(worktree).status, 'blocked')


if __name__ == '__main__':
    unittest.main()
