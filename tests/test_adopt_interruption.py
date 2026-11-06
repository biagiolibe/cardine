"""Conversion interruption tests use disposable projects and home directories."""
import os
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cardine.adopt.apply import apply_adopt
from cardine.adopt.plan import plan_adopt
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from cardine.tasks.contract import contract_digest
from conversion_fixture import queue_text, write_meridian_project
from task_contract_support import contract_record, VALIDATION


class ConversionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.root = base / 'project'
        self.root.mkdir()
        home = base / 'home'
        home.mkdir()
        self.env = patch.dict(os.environ, HOME=str(home), CARDINE_WORKTREE_ROOT=str(base / 'worktrees'))
        self.env.start()
        self.addCleanup(self.env.stop)
        def git(*args):
            subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)
        git('init', '-q', '-b', 'main')
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@example.invalid')
        write_meridian_project(self.root, queue=queue_text([
            ('[ ]', '001', 'Task'), ('[ ]', '002', 'Dependent'), ('[x]', '003', 'Done')]))
        (self.root / 'LANGUAGE_POLICY.md').write_text('# Language\n\n**Conversation language:** `English`\n')
        (self.root / 'AGENTS.md').write_text('# Custom preamble\n\nKeep this instruction.\n\n'
            '<!-- MERIDIAN:BEGIN capability=old v1 -->\nold rule\n<!-- MERIDIAN:END -->\n')
        (self.root / 'docs').mkdir()
        (self.root / 'docs/CONTEXT_BUDGET_POLICY.md').write_text(
            '# Local context\n\nKeep this note.\n<!-- MERIDIAN:BEGIN capability=old v1 -->\n'
            'old budget\n<!-- MERIDIAN:END -->\n')
        (self.root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_text('# Legacy profile\n')
        (self.root / 'PROJECT_PLAN.md').write_text('# Project plan\n\nKeep this narrative.\n')
        (self.root / 'tasks/001.md').write_text(contract_record('001').replace(
            '## Expected code surface\nChange the documented deliverable only.\n', ''))
        (self.root / 'tasks/002.md').write_text(contract_record('002').replace(
            '## Expected code surface\nChange the documented deliverable only.\n', '').replace(
            '## Dependencies\nnone', '## Dependencies\n- Depends on: `001`'))
        git('add', '.')
        git('commit', '-qm', 'Fixture')
        self.plan = plan_adopt(self.root, ROOT, name='Example', slug='example',
                               language='English', validation=VALIDATION)
        self.assertEqual(self.plan.refusals, ())

    def test_conversion_and_repeat(self):
        self.assertTrue(apply_adopt(self.root, self.plan, ROOT))
        self.assertFalse(apply_adopt(self.root, self.plan, ROOT))
        self.assertFalse((self.root / '.meridian').exists())
        self.assertTrue((self.root / '.cardine/tasks/001.json').is_file())
        self.assertIn('Keep this narrative.', (self.root / 'PROJECT_PLAN.md').read_text())
        self.assertIn('003', (self.root / 'tasks/QUEUE_ARCHIVE.md').read_text())
        from cardine.tasks.status import load_task_status
        model = load_task_status(self.root)
        dependent = next(row for row in model['tasks'] if row['id'] == '002')
        self.assertEqual(dependent['blocked_by'], ['001'])
        self.assertIn('Keep this instruction.', (self.root / 'AGENTS.md').read_text())
        self.assertIn('Keep this note.', (self.root / 'docs/CONTEXT_READING_POLICY.md').read_text())
        self.assertFalse((self.root / 'docs/CONTEXT_BUDGET_POLICY.md').exists())
        profile = (self.root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').read_bytes()
        expected = contract_digest((self.root / 'tasks/001.md').read_text())
        self.assertEqual(expected, hashlib.sha256(profile).hexdigest())

    def test_missing_completed_state_is_not_recreated(self):
        apply_adopt(self.root, self.plan, ROOT)
        state = self.root / '.cardine/tasks/001.json'
        state.unlink()
        with self.assertRaises(CardineError):
            apply_adopt(self.root, self.plan, ROOT)
        self.assertFalse(state.exists())

    def test_resume_from_saved_plan(self):
        def interrupt(name):
            if name == 'before_adopt_state:001':
                raise RuntimeError(name)
        with patch.object(receipts, 'boundary', interrupt), self.assertRaises(RuntimeError):
            apply_adopt(self.root, self.plan, ROOT)
        self.assertTrue(apply_adopt(self.root, None))
        self.assertFalse(apply_adopt(self.root, None))

    def test_interrupt_at_each_adoption_boundary(self):
        backup = self.root.parent / 'original'
        shutil.copytree(self.root, backup)
        receipt = self.root.parent / 'adoption-receipt.json'
        def files():
            return {str(path.relative_to(self.root)): path.read_bytes()
                    for path in self.root.rglob('*') if path.is_file()
                    and '.git' not in path.relative_to(self.root).parts}
        with patch.object(receipts, 'host_path', return_value=receipt), \
             patch('uuid.uuid4', return_value=uuid.UUID(int=1)):
            apply_adopt(self.root, self.plan, ROOT)
            expected = files()
            shutil.rmtree(self.root)
            shutil.copytree(backup, self.root)
            receipt.unlink()
            self._interrupt_all_boundaries()
            self.assertEqual(files(), expected)

    def _interrupt_all_boundaries(self):
        seen = set()
        def interrupt(name):
            if (name.startswith('before_adopt_') or name == 'after_adopt_result') and name not in seen:
                seen.add(name)
                raise RuntimeError(name)
        with patch.object(receipts, 'boundary', interrupt):
            for _ in range(300):
                try:
                    apply_adopt(self.root, self.plan, ROOT)
                    break
                except RuntimeError as error:
                    self.assertIn(str(error), seen)
            else:
                self.fail('conversion did not converge')
        self.assertIn('before_adopt_declare', seen)
        self.assertIn('before_adopt_state:001', seen)
        self.assertIn('before_adopt_state:002', seen)
        self.assertIn('before_adopt_release:.meridian/manifest.json', seen)
        self.assertIn('before_adopt_result', seen)
        self.assertIn('after_adopt_result', seen)
        receipt = receipts._load_intent(receipts.host_path('adopt', self.root))
        payload = receipt['adoption']
        self.assertEqual({name.removeprefix('before_adopt_write:') for name in seen
                          if name.startswith('before_adopt_write:')},
                         set(payload['outputs']) | {'.cardine/receipt-authority.json'})
        self.assertEqual({name.removeprefix('before_adopt_release:') for name in seen
                          if name.startswith('before_adopt_release:')},
                         set(payload['removals']) | set(payload['directories']))
        self.assertFalse(apply_adopt(self.root, self.plan, ROOT))
        self.assertFalse((self.root / '.meridian').exists())
