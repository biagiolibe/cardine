"""Tests for the adoption writer and managed-copy release."""
import sys
import os
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from cardine.adopt.release import strip_managed_blocks
from cardine.adopt.apply import apply_adopt
from cardine.adopt.plan import AdoptPlan
from cardine.lifecycle import receipts
from cardine.shared.errors import CardineError


class ReleaseMarkersTest(unittest.TestCase):
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
