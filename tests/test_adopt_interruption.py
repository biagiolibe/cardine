"""Conversion interruption tests use disposable projects and home directories."""
import os
import contextlib
import io
import hashlib
import json
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
from cardine.templates.adoption import bootstrap_capability_profile
from cardine.templates.audit import audit_declared_capabilities, run_audit
from cardine.templates.manifest import load_manifest
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
        self.env = patch.dict(os.environ, HOME=str(home), CARDINE_ROOT=str(ROOT),
                              CARDINE_WORKTREE_ROOT=str(base / 'worktrees'))
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
        manifest_path = self.root / '.meridian/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['managedFiles'] = {
            name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
            for name in ('LANGUAGE_POLICY.md', 'PROJECT_WORKFLOW.md', 'docs/EXECUTION_EVIDENCE_PROFILE.md')
        }
        manifest_path.write_text(json.dumps(manifest))
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
        manifest = load_manifest(self.root, ROOT)
        profile_id = 'lean-delivery-consumer'
        self.assertEqual(set(manifest['capabilityProfiles']), {profile_id})
        self.assertEqual(manifest, bootstrap_capability_profile(self.root, ROOT, profile_id, apply=False))
        results, _ = audit_declared_capabilities(self.root, ROOT, 'single')
        self.assertNotIn('FAIL', {result.status for result in results})
        self.assertNotIn('declaration/legacy-compatibility', {result.identity for result in results})
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run_audit(self.root, ROOT, 'single'), 1)
        identities = [line.split(' — ', 1)[0].split() for line in output.getvalue().splitlines() if ' — ' in line]
        self.assertNotIn('FAIL', {item[0] for item in identities})
        self.assertNotIn('declaration/legacy-compatibility', {item[1] for item in identities})
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

    def test_conversion_redone_on_a_new_commit_after_reset(self):
        def git(*args):
            subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)
        (self.root / '.gitignore').write_text('.cardine/receipt-authority.json\n')
        git('add', '.gitignore')
        git('commit', '-qm', 'Ignore local authority')
        plan = plan_adopt(self.root, ROOT, name='Example', slug='example', language='English', validation=VALIDATION)
        self.assertTrue(apply_adopt(self.root, plan, ROOT))
        git('switch', '-qc', 'first-switch')
        git('add', '-A')
        git('commit', '-qm', 'First switch')
        git('switch', '-q', 'main')
        (self.root / 'NOTES.md').write_text('A later commit on main.\n')
        git('add', 'NOTES.md')
        git('commit', '-qm', 'Later work')
        stale = json.loads((self.root / '.cardine/receipt-authority.json').read_text())
        again = plan_adopt(self.root, ROOT, name='Example', slug='example', language='English', validation=VALIDATION)
        self.assertEqual(again.refusals, ())
        self.assertTrue(apply_adopt(self.root, again, ROOT))
        self.assertTrue((self.root / '.cardine/tasks/001.json').is_file())
        accepted = json.loads((self.root / '.cardine/receipt-authority.json').read_text())
        self.assertNotEqual(accepted['accepted_main'], stale['accepted_main'])
        self.assertFalse(apply_adopt(self.root, again, ROOT))

    def test_missing_completed_state_is_not_recreated(self):
        apply_adopt(self.root, self.plan, ROOT)
        state = self.root / '.cardine/tasks/001.json'
        state.unlink()
        with self.assertRaises(CardineError):
            apply_adopt(self.root, self.plan, ROOT)
        self.assertFalse(state.exists())

    def test_converted_task_starts_without_reconcile(self):
        apply_adopt(self.root, self.plan, ROOT)
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-qm', 'Adopt'], cwd=self.root, check=True, capture_output=True)
        command = [str(ROOT / 'bin/cardine')]
        prepared = subprocess.run(command + ['worktree', 'prepare', '001', '--project', str(self.root),
                                             '--format', 'json'], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        worktree = Path(json.loads(prepared.stdout)['worktree'])
        started = subprocess.run(command + ['execution', 'start', '001', '--project', '.', '--format', 'json'],
                                 cwd=worktree, capture_output=True, text=True)
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        self.assertTrue(json.loads(started.stdout)['started'])

    def test_preserves_custom_project_locations(self):
        work = self.root / 'work'
        work.mkdir()
        (self.root / 'tasks/QUEUE.md').rename(work / 'QUEUE.md')
        (self.root / 'tasks/001.md').rename(work / '001.md')
        (self.root / 'tasks/002.md').rename(work / '002.md')
        (self.root / 'PROJECT_PLAN.md').rename(work / 'PLAN.md')
        declaration = {'version': 1, 'preset': 'lean', 'locations': {
            'queue': 'work/QUEUE.md', 'plan': 'work/PLAN.md', 'taskRoots': ['work']}}
        (self.root / '.meridian/project.json').write_text(json.dumps(declaration))
        subprocess.run(['git', 'add', '-A'], cwd=self.root, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-qm', 'Customize locations'], cwd=self.root, check=True, capture_output=True)
        plan = plan_adopt(self.root, ROOT, name='Example', slug='example',
                          language='English', validation=VALIDATION)
        self.assertEqual(plan.refusals, ())
        apply_adopt(self.root, plan, ROOT)
        config = json.loads((self.root / '.cardine/project.json').read_text())
        self.assertEqual(config['locations']['taskRoots'], ['work'])
        self.assertIn('002', (work / 'QUEUE.md').read_text())
        self.assertIn('Keep this narrative.', (work / 'PLAN.md').read_text())

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
