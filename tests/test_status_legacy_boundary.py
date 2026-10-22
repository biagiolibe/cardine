"""Installation discovery remains explicit, read-only, and product-independent."""

from __future__ import annotations

import builtins
import io
import json
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from cardine.console import snapshot as product
from cardine.legacy import meridian_installation as installation
from cardine.legacy import snapshot as legacy
from cardine.shared.snapshot_adapters import execution_assets_adapter, state_adapter, status_adapter
import console_support as support


class LegacyBoundaryTest(support.RepoCase):
    def setUp(self):
        super().setUp()
        support.LeanEffectiveStateFixture.setup_project(self, {"001": "x", "002": " "},
                                                       {"002": "001"})
        (self.project / ".cardine/project.json").unlink()
        self.write(self.project, "PROJECT_WORKFLOW.md", "LEAN_DELIVERY\n")
        self.write(self.project, ".meridian/manifest.json", json.dumps({"workflowMode": "lean-delivery"}))
        self.commit(self.project, "Meridian fixture")

    queue = support.LeanEffectiveStateFixture.queue

    def assert_read_only_snapshot(self, archived):
        if archived:
            self.write(self.project, "tasks/QUEUE.md", self.queue({"002": " "}, {"002": "001"}))
            self.write(self.project, "tasks/QUEUE_ARCHIVE.md", self.queue({"001": "x"}))
            # Discover the fixture's actual record name before moving it.
            record = next((self.project / "tasks").glob("001-*.md"))
            target = self.project / "tasks/done" / record.name
            target.parent.mkdir()
            record.rename(target)
            archive = self.project / "tasks/QUEUE_ARCHIVE.md"
            archive.write_text(archive.read_text().replace(record.name, "done/" + record.name))
        else:
            self.write(self.project, "tasks/QUEUE_ARCHIVE.md", "# Queue archive\n")
        self.commit(self.project, "Archive fixture")
        before = {p.relative_to(self.project): p.read_bytes()
                  for p in self.project.rglob("*") if p.is_file()}
        original_io, original_open = io.open, builtins.open

        def guard(original):
            def read(file, mode="r", *args, **kwargs):
                self.assertFalse(any(flag in mode for flag in "wax+"), (file, mode))
                return original(file, mode, *args, **kwargs)
            return read

        with mock.patch.object(io, "open", side_effect=guard(original_io)), \
             mock.patch.object(builtins, "open", side_effect=guard(original_open)), \
             mock.patch.object(product, "load_snapshot", side_effect=AssertionError("product loader called")):
            snapshot = installation.load_meridian_snapshot(self.project)
        self.assertEqual([(t.task_id, t.status, t.lifecycle, t.readiness) for t in snapshot.tasks],
                         [("002", "queued", "todo", "READY")])
        self.assertEqual(snapshot.done_count, 1)
        self.assertTrue(snapshot.tasks[0].legacy)
        self.assertEqual(before, {p.relative_to(self.project): p.read_bytes()
                                  for p in self.project.rglob("*") if p.is_file()})
        self.assertFalse((self.project / ".cardine").exists() and
                         any((self.project / ".cardine").iterdir()))
        self.assertIsNone(state_adapter.get())
        self.assertIsNone(status_adapter.get())
        self.assertIsNone(execution_assets_adapter.get())

    def test_empty_archive_preserves_record_fallback_without_writes(self):
        self.assert_read_only_snapshot(False)

    def test_populated_archive_preserves_dependency_and_moved_record_without_writes(self):
        self.assert_read_only_snapshot(True)

    def test_product_missing_state_never_selects_installation_reader(self):
        self.write(self.project, ".cardine/project.json", '{"version": 1, "preset": "lean"}')
        with mock.patch.object(legacy, "load_snapshot", side_effect=AssertionError("installation selected")), \
             mock.patch.object(installation, "load_snapshot", side_effect=AssertionError("installation selected")):
            snapshot = product.load_snapshot(self.project)
        # Without task states the product lists nothing; queue rows and records are not a fallback.
        self.assertEqual(snapshot.done_count, 0)
        self.assertEqual(snapshot.tasks, ())
