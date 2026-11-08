"""Rehearsal isolates the source and gates application on verification."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cardine.adopt.plan import plan_adopt
from cardine.adopt.rehearsal import rehearse_adoption, apply_rehearsed_adoption
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError
from task_contract_support import VALIDATION
from test_conversion_reader import tree_digest


class RehearsalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.root = base / 'project'
        self.root.mkdir()
        home = base / 'home'
        home.mkdir()
        environment = patch.dict(os.environ, HOME=str(home), CARDINE_WORKTREE_ROOT=str(home / 'worktrees'),
                                 XDG_CONFIG_HOME=str(home / 'config'))
        environment.start()
        self.addCleanup(environment.stop)
        self.receipt = base / 'receipt.json'
        self.scratch_root = home / 'worktrees'
        original_host_path = receipts.host_path
        self.original_host_path = original_host_path
        self.host_path = lambda kind, target: self.receipt if kind == 'adopt-rehearsal' else base / (kind + '.json')
        self.git('init', '-q', '-b', 'main')
        (self.root / 'README').write_text('source\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Fixture')
        self.plan = plan_adopt(self.root, ROOT, name='Example', slug='example', preset='lean',
                               language='English', task_identity='opaque', validation=VALIDATION)

    def git(self, *args):
        subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def test_clone_preserves_source_and_rebuilds_after_interruptions(self):
        before = tree_digest(self.root)
        seen = []
        def verify(root, framework, expected, *, env):
            self.assertTrue(str(root).startswith(str(self.scratch_root)))
            self.assertTrue(Path(env['HOME']).is_dir())
            self.assertEqual(expected, 0)
            scratch = root.parent
            name = 'adopt-' + receipts.digest(str(root.resolve()).encode()) + '.json'
            self.assertTrue((scratch / 'tmp/cardine-operations' / name).is_file())
            self.assertFalse(self.original_host_path('adopt', root).exists())
            seen.append(root)
            return {'tasks': 0}
        with patch.object(receipts, 'host_path', side_effect=self.host_path), \
             patch('cardine.adopt.rehearsal.verify_adoption', side_effect=verify):
            for boundary in ('before_rehearsal_clone', 'after_rehearsal_clone',
                             'before_rehearsal_verify', 'before_rehearsal_receipt'):
                def interrupt(name):
                    if name == boundary:
                        raise RuntimeError(name)
                environment_before = dict(os.environ)
                with patch.object(receipts, 'boundary', interrupt), self.assertRaises(RuntimeError):
                    rehearse_adoption(self.root, self.plan, ROOT)
                self.assertEqual(dict(os.environ), environment_before)
                self.assertFalse(self.receipt.exists())
                rehearse_adoption(self.root, self.plan, ROOT)
                self.assertEqual(dict(os.environ), environment_before)
                self.assertTrue(self.receipt.exists())
            self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(tree_digest(self.root), before)

    def test_real_verifier_on_initialized_copy(self):
        with patch.object(receipts, 'host_path', side_effect=self.host_path):
            result = rehearse_adoption(self.root, self.plan, ROOT)
        self.assertEqual(result['tasks'], 0)
        self.assertTrue(self.receipt.is_file())
        evidence = json.loads(self.receipt.read_text())['verification']['audit']
        self.assertIn('SUMMARY', evidence['copy']['summary'])
        self.assertIn('SUMMARY', evidence['reference']['summary'])
        self.assertTrue(evidence['copy']['pairs'])

    def test_tampered_copy_blocks_apply(self):
        from cardine.adopt.verify import verify_adoption
        def tamper(root, framework, expected, *, env):
            (root / '.codex/rules/meridian.rules').write_text('tampered')
            return verify_adoption(root, framework, expected, env=env)
        before = tree_digest(self.root)
        with patch.object(receipts, 'host_path', side_effect=self.host_path), \
             patch('cardine.adopt.rehearsal.verify_adoption', side_effect=tamper):
            with self.assertRaisesRegex(CardineError, 'audit failed'):
                apply_rehearsed_adoption(self.root, self.plan, ROOT)
        self.assertEqual(tree_digest(self.root), before)
        self.assertFalse(self.receipt.exists())

    def test_extra_nonpass_audit_result_blocks_apply(self):
        from cardine.adopt import verify
        original = verify._audit
        def inject(root, command, env):
            result = original(root, command, env)
            if root.name == 'project':
                result['pairs'].append(('UNVERIFIED', 'injected-check'))
            return result
        before = tree_digest(self.root)
        with patch.object(receipts, 'host_path', side_effect=self.host_path), \
             patch.object(verify, '_audit', side_effect=inject):
            with self.assertRaisesRegex(CardineError, 'injected-check'):
                apply_rehearsed_adoption(self.root, self.plan, ROOT)
        self.assertEqual(tree_digest(self.root), before)
        self.assertFalse(self.receipt.exists())

    def test_failure_blocks_apply_and_changed_head_invalidates_receipt(self):
        before = tree_digest(self.root)
        with patch.object(receipts, 'host_path', side_effect=self.host_path), \
             patch('cardine.adopt.rehearsal.verify_adoption', side_effect=CardineError('failed')):
            with self.assertRaisesRegex(CardineError, 'failed'):
                apply_rehearsed_adoption(self.root, self.plan, ROOT)
            self.assertFalse(self.receipt.exists())
        self.assertEqual(tree_digest(self.root), before)
        with patch.object(receipts, 'host_path', side_effect=self.host_path), \
             patch('cardine.adopt.rehearsal.verify_adoption', return_value={'tasks': 0}) as verify:
            rehearse_adoption(self.root, self.plan, ROOT)
            (self.root / 'README').write_text('changed\n')
            self.git('add', '.')
            self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Change')
            apply_rehearsed_adoption(self.root, self.plan, ROOT)
            self.assertEqual(verify.call_count, 2)
            self.assertTrue((self.root / '.cardine/project.json').is_file())


class MeridianRehearsalTest(unittest.TestCase):
    def setUp(self):
        import test_adopt_interruption
        test_adopt_interruption.ConversionTest.setUp(self)

    def test_real_verifier_on_meridian_conversion(self):
        before = tree_digest(self.root)
        result = rehearse_adoption(self.root, self.plan, ROOT)
        self.assertEqual(result['tasks'], 2)
        self.assertEqual(tree_digest(self.root), before)
