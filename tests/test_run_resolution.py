"""Pure next-step precedence and read-only location discovery."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cardine.lifecycle.engine import resolve_run, render_output, resolve_run_locations
from cardine.lifecycle.model import Guardrail, RunFacts
from cardine.shared.errors import CardineError
from task_contract_support import contract_record, write_state


class RunResolutionTests(unittest.TestCase):
    def test_all_steps_both_presets_and_explicit_review_skip(self):
        for preset in ('lean', 'governed'):
            facts = RunFacts('001', Path('/tmp/project'), 'queued', review_required=preset == 'governed')
            stages = [('contract', {}), ('worktree', {'contract_ready': True}),
                      ('implementation', {'worktree_ready': True, 'status': 'in_progress'}),
                      ('validation', {'implementation_delivered': True}),
                      ('review' if preset == 'governed' else 'candidate', {'validation_passed': True}),
                      ('candidate', {'review_approved': True}),
                      ('landing', {'candidate_validated': True})]
            for expected, changes in stages:
                facts = replace(facts, **changes)
                self.assertEqual(resolve_run(facts)['step'], expected)
            self.assertEqual(resolve_run(replace(facts, status='done', landing_complete=True))['outcome'], 'done')

    def test_precedence_reconciliation_guardrail_and_terminal(self):
        base = RunFacts('001', Path('/tmp/project'), 'in_progress', guardrail=Guardrail('SCOPE_CHANGE_REQUIRED', 'Outside surface'))
        self.assertEqual(resolve_run(base)['outcome'], 'blocked')
        interrupted = replace(base, pending_step='candidate')
        self.assertEqual(resolve_run(interrupted)['step'], 'candidate')
        terminal = replace(interrupted, status='done', cleanup_pending=True)
        self.assertEqual(resolve_run(terminal)['step'], 'landing')
        self.assertEqual(resolve_run(replace(terminal, status='cancelled'))['outcome'], 'done')

    def test_waiting_remediation_and_identity_invalidation(self):
        base = RunFacts('001', Path('/tmp/project'), 'in_progress', contract_ready=True,
                        worktree_ready=True, implementation_delivered=True, validation_passed=True)
        for change in ({'validation_failed': True}, {'review_changes_requested': True}):
            result = resolve_run(replace(base, **change))
            self.assertEqual((result['outcome'], result['step']), ('iterate', 'implementation'))
        for changes, step in (({'review_pending': True}, 'review'),
                              ({'review_approved': True, 'ci_pending': True}, 'candidate')):
            result = resolve_run(replace(base, **changes))
            self.assertEqual((result['outcome'], result['step']), ('waiting', step))
            self.assertGreater(result['retry_after_seconds'], 0)
        self.assertEqual(resolve_run(replace(base, implementation_delivered=False))['step'], 'implementation')
        self.assertEqual(resolve_run(replace(base, validation_passed=False))['step'], 'validation')
        self.assertEqual(resolve_run(replace(base, review_approved=True, candidate_validated=False))['step'], 'candidate')

    def test_pure_preview_has_no_subprocess_or_write_boundary(self):
        facts = RunFacts('001', Path('/tmp/project'), 'queued')
        with patch('subprocess.run', side_effect=AssertionError('subprocess effect')), \
             patch.object(Path, 'write_text', side_effect=AssertionError('write')), \
             patch.object(Path, 'write_bytes', side_effect=AssertionError('write')):
            before = repr(facts)
            first = render_output(resolve_run(facts))
            for _ in range(10):
                self.assertEqual(render_output(resolve_run(facts)), first)
            self.assertEqual(repr(facts), before)


class RunLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'consumer ; $(touch SENTINEL)'
        self.make_project(self.root)

    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)

    def make_project(self, root, preset='lean'):
        root.mkdir()
        self.git(root, 'init', '-b', 'main')
        self.git(root, 'config', 'user.name', 'Fixture')
        self.git(root, 'config', 'user.email', 'fixture@example.invalid')
        (root / '.cardine').mkdir()
        (root / '.cardine/project.json').write_text(json.dumps({'version': 1, 'preset': preset}))
        (root / 'tasks').mkdir()
        (root / 'tasks/001.md').write_text(contract_record())
        write_state(root)
        self.git(root, 'add', '.')
        self.git(root, 'commit', '-m', 'Fixture')

    def test_primary_linked_nested_and_unrelated_cwd(self):
        linked = self.base / 'linked checkout'
        self.git(self.root, 'worktree', 'add', '-b', 'task-001', str(linked))
        for preset in ('lean', 'governed'):
            (self.root / '.cardine/project.json').write_text(json.dumps({'version': 1, 'preset': preset}))
            for project in (self.root, linked, linked / 'tasks'):
                locations = resolve_run_locations('001', project, cwd=self.base,
                                                  worktree_root=self.base / 'worktrees')
                self.assertEqual(locations.primary, self.root.resolve())
                self.assertEqual(locations.common_dir, self.root / '.git')
                self.assertEqual(locations.root, self.base / 'worktrees')
                self.assertEqual(locations.worktree.name, 'task-001')
            self.assertEqual(resolve_run_locations('001', cwd=linked / 'tasks',
                             worktree_root=self.base / 'worktrees').primary, self.root)

    def test_registry_unique_dedup_missing_and_ambiguous(self):
        kw = dict(cwd=self.base, worktree_root=self.base / 'worktrees')
        self.assertEqual(resolve_run_locations('001', registered_projects=[self.root, self.root], **kw).primary, self.root)
        with self.assertRaisesRegex(CardineError, 'supply --project'):
            resolve_run_locations('001', **kw)
        other = self.base / 'second'
        self.make_project(other)
        with self.assertRaisesRegex(CardineError, 'ambiguous'):
            resolve_run_locations('001', registered_projects=[self.root, other], **kw)
        with self.assertRaises(CardineError):
            resolve_run_locations('999', self.root, **kw)
        # A known enclosing repository with a missing task cannot redirect to another.
        with self.assertRaises(CardineError):
            resolve_run_locations('999', cwd=self.root, registered_projects=[other], worktree_root=self.base / 'worktrees')

    def test_reads_do_not_change_consumer_bytes_or_create_worktree(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for _ in range(2):
            resolve_run_locations('001', self.root, worktree_root=self.base / 'worktrees')
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.base / 'worktrees').exists())


if __name__ == '__main__':
    unittest.main()
