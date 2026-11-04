"""Adoption planning observes disposable projects without writing them."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cardine.adopt.plan import plan_adopt
from cardine.lifecycle import receipts
from conversion_fixture import queue_text, write_meridian_project
from task_contract_support import contract_record, VALIDATION
from test_conversion_reader import tree_digest


class AdoptPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'CARDINE_WORKTREE_ROOT': str(self.base / 'worktrees')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True, text=True).stdout

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'Fixture')

    def choices(self):
        return dict(name='Example', slug='example', language='English', validation=VALIDATION)

    def legacy(self, status='[ ]'):
        write_meridian_project(self.root, queue=queue_text([(status, '001', 'Task')]))
        (self.root / 'tasks/001.md').write_text(contract_record('001').replace(
            '## Expected code surface\nChange the documented deliverable only.\n', ''))
        self.commit()

    def test_case_a_and_repeat(self):
        choices = {**self.choices(), 'preset': 'lean', 'task_identity': 'opaque'}
        before = tree_digest(self.base)
        first = plan_adopt(self.root, ROOT, **choices)
        second = plan_adopt(self.root, ROOT, **choices)
        self.assertEqual(first.case, 'A')
        self.assertEqual(first.bytes(), second.bytes())
        self.assertIn('.cardine/project.json', first.outputs)
        self.assertEqual(tree_digest(self.base), before)
        self.assertIn('validation', plan_adopt(self.root, ROOT).missing)

    def test_case_b_and_mapping_repeat(self):
        self.legacy()
        before = tree_digest(self.base)
        first = plan_adopt(self.root, ROOT, **self.choices())
        self.assertEqual(first.case, 'B')
        self.assertEqual(first.refusals, ())
        self.assertEqual(first.bytes(), plan_adopt(self.root, ROOT, **self.choices()).bytes())
        config = json.loads(first.outputs['.cardine/project.json'])
        self.assertEqual(config['ci'], 'none')
        self.assertEqual(config['taskIdentity']['mode'], 'opaque')
        self.assertEqual(tree_digest(self.base), before)

    def test_candidate_and_defaults_mapping(self):
        candidate = {'version': 1, 'state': 'declared', 'outcomes': {
            'REUSE': ['check'], 'BOUNDED': ['check'], 'FULL': ['check', 'test']}}
        write_meridian_project(self.root, queue=queue_text([]),
            candidate=candidate, identity={'version': 1, 'mode': 'milestone'},
            declaration={'version': 1, 'preset': 'governed',
                         'taskDefaults': {'review': 'required'}}, governed=True)
        self.commit()
        plan = plan_adopt(self.root, ROOT, **self.choices())
        config = json.loads(plan.outputs['.cardine/project.json'])
        self.assertEqual(config['preset'], 'governed')
        self.assertEqual(config['taskDefaults']['review'], 'required')
        self.assertEqual(config['taskIdentity']['mode'], 'milestone')
        ids = config['validation']['candidate']
        self.assertEqual([config['validation']['commands'][key] for key in ids['FULL']], ['check', 'test'])
        self.assertEqual(ids['REUSE'], ids['BOUNDED'])

    def test_dirty_refusal(self):
        self.legacy()
        (self.root / 'untracked').write_text('change')
        self.assertIn('ADOPT_DIRTY', plan_adopt(self.root, ROOT, **self.choices()).refusals)

    def test_in_progress_refusal(self):
        self.legacy('[/]')
        self.assertIn('ADOPT_IN_PROGRESS', plan_adopt(self.root, ROOT, **self.choices()).refusals)

    def test_worktree_refusal(self):
        self.legacy()
        self.git('worktree', 'add', '-qb', 'task-002', str(self.base / 'worker'))
        self.assertIn('ADOPT_WORKTREE', plan_adopt(self.root, ROOT, **self.choices()).refusals)

    def test_lease_refusal(self):
        self.legacy()
        (self.root / '.git/meridian-integration.lock').write_text('{}')
        self.assertIn('ADOPT_LEASE', plan_adopt(self.root, ROOT, **self.choices()).refusals)

    def test_record_refusal(self):
        self.legacy()
        (self.root / 'tasks/001.md').write_text('incomplete')
        self.assertIn('ADOPT_RECORD', plan_adopt(self.root, ROOT, **self.choices()).refusals)

    def test_before_plan_interruption_writes_nothing(self):
        self.legacy()
        before = tree_digest(self.base)
        def interrupt(name):
            if name == 'before_adopt_plan':
                raise RuntimeError(name)
        with patch.object(receipts, 'boundary', interrupt), self.assertRaisesRegex(RuntimeError, 'before_adopt_plan'):
            plan_adopt(self.root, ROOT, **self.choices())
        self.assertEqual(tree_digest(self.base), before)
