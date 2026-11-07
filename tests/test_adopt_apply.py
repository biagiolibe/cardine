"""Tests for the adoption writer and managed-copy release."""
import sys
import os
from pathlib import Path
import unittest
import tempfile
import hashlib
import json
import re
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from cardine.adopt.release import conversion_outputs, strip_managed_blocks
from cardine.tasks.status_render import render_queue
from cardine.tasks.state import STATUSES
from cardine.adopt.apply import apply_adopt
from cardine.adopt.plan import AdoptPlan
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError


class ReleaseMarkersTest(unittest.TestCase):
    def test_conversion_preserves_only_project_owned_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, value):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
            marker = '<!-- MERIDIAN:BEGIN capability=x v1 -->\nmanaged\n<!-- MERIDIAN:END -->'
            unchanged = 'old release\n' + marker + '\n'
            baseline = 'Hello [Project Name]\n\n' + marker + '\n'
            edited = 'Hello Example\n\n' + marker + '\n\nMy own block.\n'
            write('AGENTS.md', unchanged)
            write('CLAUDE.md', edited)
            write('README.md', 'Project README\n')
            write('LANGUAGE_POLICY.md', '**Conversation language:** `Italian`\n')
            write('tasks/QUEUE.md', '# Queue\n')
            write('.meridian/baselines/1/CLAUDE.md', baseline)
            manifest = {'workflowBaselineVersion': '1', 'managedFiles': {
                'AGENTS.md': hashlib.sha256(unchanged.encode()).hexdigest(),
                'CLAUDE.md': hashlib.sha256(b'original').hexdigest()}}
            write('.meridian/manifest.json', json.dumps(manifest))
            config = {'project': {'name': 'Example', 'slug': 'example'}, 'preset': 'lean',
                      'taskIdentity': {'mode': 'opaque'}, 'validation': {}}
            plan = SimpleNamespace(outputs={'.cardine/project.json': json.dumps(config).encode()})
            initial = SimpleNamespace(outputs={'AGENTS.md': b'Cardine agent\n', 'CLAUDE.md': b'Cardine agent\n',
                'README.md': b'template\n', '.cardine/manifest.json': json.dumps({'managedFiles': {
                    'AGENTS.md': 'a', 'CLAUDE.md': 'b', 'README.md': 'c'}}).encode()})
            locations = SimpleNamespace(queue=Path('tasks/QUEUE.md'), task_roots=[Path('tasks')],
                adr_log=Path('docs/ADR.md'), handoff_root=Path('tasks/handoffs'),
                review_root=Path('tasks/reviews'), plan=Path('PROJECT_PLAN.md'))
            legacy = SimpleNamespace(locations=locations, rows=[], open_rows=[])
            with patch('cardine.adopt.release.plan_init', return_value=initial), \
                 patch('cardine.adopt.release.read_legacy_project', return_value=legacy):
                outputs, _, _, _ = conversion_outputs(root, root, plan)
            self.assertEqual(outputs['AGENTS.md'], b'Cardine agent\n')
            self.assertEqual(outputs['CLAUDE.md'], b'Cardine agent\n\nMy own block.\n')
            self.assertNotIn('README.md', outputs)
            self.assertNotIn('README.md', json.loads(outputs['.cardine/manifest.json'])['managedFiles'])
            self.assertFalse(any(b'MERIDIAN' in content or b'BLOCKED ' in content for content in outputs.values()))

    def test_queue_links_resolve_from_queue_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / 'tasks/1-example.md'
            record.parent.mkdir()
            record.touch()
            model = {'preset': 'lean', 'totals': dict.fromkeys((*STATUSES, 'total'), 0),
                     'tasks': [{'status': 'queued', 'record': 'tasks/1-example.md', 'id': '1', 'title': 'Example',
                                'dependencies': [], 'blocked_by': [], 'startable': True}]}
            queue = render_queue(model, 'digest', 'tasks/QUEUE.md')
            for link in re.findall(r'\]\(([^)]+)\)', queue):
                self.assertTrue((root / 'tasks' / link).is_file())

    def test_preserves_unmarked_text_exactly(self):
        source = ('before\n<!-- MERIDIAN:BEGIN capability=example v1 -->\n'
                  'managed\n<!-- MERIDIAN:END -->\nafter\n')
        self.assertEqual(strip_managed_blocks(source), 'before\n\nafter\n')

    def test_rejects_unbalanced_and_nested_markers(self):
        begin = '<!-- MERIDIAN:BEGIN capability=example v1 -->'
        end = '<!-- MERIDIAN:END -->'
        for value in (begin, end, begin + begin + end + end):
            with self.subTest(value=value), self.assertRaises(CardineError):
                strip_managed_blocks(value)


class ApplyInitTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        environment = patch.dict(os.environ, {'HOME': home.name})
        environment.start()
        self.addCleanup(environment.stop)

    def test_replay_after_each_boundary(self):
        plan = AdoptPlan('A', {'a.txt': b'one', 'dir/b.txt': b'two'}, (), (), (), {})
        boundaries = ['before_adopt_declare', 'before_adopt_write:a.txt',
                      'before_adopt_write:dir/b.txt', 'before_adopt_result', 'after_adopt_result']
        for boundary in boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'project'
                root.mkdir()
                def interrupt(name):
                    if name == boundary:
                        raise RuntimeError(name)
                with patch.object(receipts, 'boundary', interrupt), self.assertRaises(RuntimeError):
                    apply_adopt(root, plan)
                apply_adopt(root, plan)
                self.assertEqual((root / 'a.txt').read_bytes(), b'one')
                self.assertEqual((root / 'dir/b.txt').read_bytes(), b'two')
                self.assertFalse(apply_adopt(root, plan))

    def test_writes_over_an_existing_file_only_as_planned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a.txt').write_text('ours')
            digest = hashlib.sha256(b'ours').hexdigest()
            plan = AdoptPlan('A', {'a.txt': b'template\n\nours'}, (), (), (), {}, existing={'a.txt': digest})
            (root / 'a.txt').write_text('changed after planning')
            with self.assertRaises(CardineError):
                apply_adopt(root, plan)
            (root / 'a.txt').write_text('ours')
            self.assertTrue(apply_adopt(root, plan))
            self.assertEqual((root / 'a.txt').read_bytes(), b'template\n\nours')

    def test_refuses_existing_file_and_changed_output(self):
        plan = AdoptPlan('A', {'a.txt': b'one'}, (), (), (), {})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a.txt').write_text('foreign')
            with self.assertRaises(CardineError):
                apply_adopt(root, plan)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apply_adopt(root, plan)
            (root / 'a.txt').write_text('changed')
            with self.assertRaises(CardineError):
                apply_adopt(root, plan)
