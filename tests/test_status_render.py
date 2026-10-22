"""Generated queue and plan status region: read-only default, atomic explicit write."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.shared.errors import CardineError
from cardine.tasks import status_render
from cardine.tasks.status_render import REGION_BEGIN, REGION_END, splice_region, stale_views, write_views

ROOT = Path(__file__).resolve().parents[1]


class StatusRenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / ".cardine/tasks").mkdir(parents=True)
        (self.root / "tasks").mkdir()
        (self.root / ".cardine/project.json").write_text(json.dumps({"version": 1, "preset": "lean"}))
        self.queue = self.root / "tasks/QUEUE.md"
        self.plan = self.root / "PROJECT_PLAN.md"

    def task(self, task_id, status="queued", title=None, dependencies="none"):
        steps = {"queued": [], "in_progress": ["in_progress"], "done": ["in_progress", "done"]}[status]
        current, transitions = "queued", []
        for destination in steps:
            transitions.append({"from": current, "to": destination, "commit": "a" * 40, "at": "2026-10-22T00:00:00Z"})
            current = destination
        state = {"version": 1, "task_id": task_id, "workflow": "single", "status": status, "transitions": transitions}
        (self.root / f".cardine/tasks/{task_id}.json").write_text(json.dumps(state))
        (self.root / f"tasks/{task_id}.md").write_text(
            f"# {title or 'Task ' + task_id}\n\n> **ID**: `{task_id}`\n> **Priority**: P1\n> **Phase**: Build\n\n"
            f"## Dependencies\n- **Depends on**: {dependencies}\n")

    def region_plan(self, before=b"Intro\n", after=b"\nOutro\n"):
        return before + REGION_BEGIN.encode() + b"\nold\n" + REGION_END.encode() + after

    def test_default_status_reads_without_writing_views(self):
        self.task("001")
        self.plan.write_bytes(self.region_plan())
        subprocess.run([sys.executable, str(ROOT / "bin/cardine"), "status", "--project", str(self.root)],
                       capture_output=True, text=True, check=False)
        self.assertFalse(self.queue.exists())
        self.assertEqual(self.plan.read_bytes(), self.region_plan())

    def test_write_renders_queue_and_plan_region_with_totals_and_all_tasks(self):
        self.task("001", "done")
        self.task("002", "queued", dependencies="001")
        self.plan.write_bytes(self.region_plan())
        write_views(self.root)
        queue = self.queue.read_text()
        self.assertIn("cardine status --write", queue)
        self.assertIn("Totals: queued=1, in_progress=0, in_review=0, done=1, cancelled=0, total=2", queue)
        self.assertIn("| queued | 002 |", queue)
        self.assertNotIn("| done | 001 |", queue)
        plan = self.plan.read_text()
        self.assertIn("| done | 001 |", plan)
        self.assertIn("| queued | 002 |", plan)

    def test_second_write_is_byte_identical_and_changes_nothing(self):
        self.task("001")
        self.plan.write_bytes(self.region_plan())
        write_views(self.root)
        first = (self.queue.read_bytes(), self.plan.read_bytes())
        self.assertEqual(write_views(self.root), [])
        self.assertEqual((self.queue.read_bytes(), self.plan.read_bytes()), first)
        self.assertNotRegex(first[0].decode(), r"\d{4}-\d{2}-\d{2}")

    def test_header_digest_ignores_views_and_changes_with_inputs(self):
        self.task("001")
        write_views(self.root)
        first = self.queue.read_text().splitlines()[2]
        self.queue.write_text("edited")
        write_views(self.root)
        self.assertEqual(self.queue.read_text().splitlines()[2], first)
        self.task("002")
        write_views(self.root)
        self.assertNotEqual(self.queue.read_text().splitlines()[2], first)

    def test_stale_or_hand_edited_view_is_reported_then_regenerated(self):
        self.task("001")
        write_views(self.root)
        self.assertEqual(stale_views(self.root), [])
        self.queue.write_text("| `[x]` | 001 | stale |\n")
        self.assertEqual(stale_views(self.root), [self.queue])
        write_views(self.root)
        self.assertIn("| queued | 001 |", self.queue.read_text())

    def test_plan_bytes_outside_the_region_are_preserved_including_crlf(self):
        self.task("001")
        plan = self.region_plan(b"Line one\r\nsecond \xe2\x9c\x93\r\n", b"\r\ntail without newline")
        self.plan.write_bytes(plan)
        write_views(self.root)
        result = self.plan.read_bytes()
        self.assertTrue(result.startswith(b"Line one\r\nsecond \xe2\x9c\x93\r\n" + REGION_BEGIN.encode()))
        self.assertTrue(result.endswith(REGION_END.encode() + b"\r\ntail without newline"))

    def test_missing_or_malformed_region_is_diagnosed_without_touching_either_file(self):
        self.task("001")
        self.queue.write_text("hand queue\n")
        for plan in (b"Narrative only\n",
                     REGION_BEGIN.encode() + b"\nonly begin\n",
                     REGION_END.encode() + b"\n" + REGION_BEGIN.encode() + b"\n",
                     self.region_plan() + self.region_plan()):
            with self.subTest(plan=plan):
                self.plan.write_bytes(plan)
                with self.assertRaisesRegex(CardineError, "generated region"):
                    write_views(self.root)
                self.assertEqual(self.plan.read_bytes(), plan)
                self.assertEqual(self.queue.read_text(), "hand queue\n")

    def test_empty_and_missing_plans_receive_only_the_region(self):
        self.task("001")
        self.plan.write_bytes(b"")
        write_views(self.root)
        text = self.plan.read_text()
        self.assertTrue(text.startswith(REGION_BEGIN) and text.rstrip().endswith(REGION_END))
        self.plan.unlink()
        write_views(self.root)
        self.assertIn(REGION_BEGIN, self.plan.read_text())

    def test_zero_task_snapshot_renders_empty_views(self):
        write_views(self.root)
        self.assertIn("total=0", self.queue.read_text())
        self.assertIn("total=0", self.plan.read_text())

    def test_incomplete_snapshot_writes_nothing(self):
        self.task("001")
        (self.root / ".cardine/tasks/001.json").write_text("{not json")
        self.queue.write_text("keep\n")
        with self.assertRaisesRegex(CardineError, "incomplete status snapshot"):
            write_views(self.root)
        self.assertEqual(self.queue.read_text(), "keep\n")
        self.assertFalse(self.plan.exists())

    def test_failed_second_replace_restores_the_first_view(self):
        self.task("001")
        self.queue.write_text("old queue\n")
        self.plan.write_bytes(self.region_plan())
        real = os.replace
        calls = []

        def failing(source, target):
            calls.append(target)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(source, target)

        with patch.object(status_render, "_replace", side_effect=failing):
            with self.assertRaisesRegex(CardineError, "previous content restored"):
                write_views(self.root)
        self.assertEqual(self.queue.read_text(), "old queue\n")
        self.assertEqual(self.plan.read_bytes(), self.region_plan())
        self.assertEqual([path.name for path in (self.root).glob(".*") if path.is_file()], [])
        self.assertEqual([path.name for path in (self.root / "tasks").glob(".*")], [])

    def test_failed_staging_leaves_no_partial_views(self):
        self.task("001")
        self.plan.write_bytes(self.region_plan())
        with patch.object(status_render, "_stage", side_effect=OSError("no space")):
            with self.assertRaises(CardineError):
                write_views(self.root)
        self.assertFalse(self.queue.exists())

    def test_declared_locations_and_escaping_paths(self):
        self.task("001", title="Pipe | title")
        (self.root / ".cardine/project.json").write_text(json.dumps(
            {"version": 1, "preset": "lean", "locations": {"queue": "docs/Q.md", "plan": "docs/P.md"}}))
        write_views(self.root)
        self.assertIn("Pipe \\| title", (self.root / "docs/Q.md").read_text())
        self.assertTrue((self.root / "docs/P.md").is_file())
        self.assertFalse(self.queue.exists())

    def test_splice_requires_exactly_one_ordered_pair(self):
        with self.assertRaises(CardineError):
            splice_region(b"nothing here", "x")

    def test_cli_write_round_trip(self):
        self.task("001")
        self.plan.write_bytes(self.region_plan())
        result = subprocess.run([sys.executable, str(ROOT / "bin/cardine"), "status", "--write", "--project", str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("updated tasks/QUEUE.md", result.stdout)
        again = subprocess.run([sys.executable, str(ROOT / "bin/cardine"), "status", "--write", "--project", str(self.root)],
                               capture_output=True, text=True)
        self.assertIn("already up to date", again.stdout)

    def test_templates_carry_the_region_and_no_hand_maintained_status(self):
        plan = (ROOT / "templates/single/PROJECT_PLAN.md").read_text()
        queue = (ROOT / "templates/single/tasks/QUEUE.md").read_text()
        self.assertEqual((plan.count(REGION_BEGIN), plan.count(REGION_END)), (1, 1))
        self.assertIn("cardine status --write", queue)
        for text in (plan, queue):
            self.assertNotRegex(text, r"`\[[ /x?-]\]`")


if __name__ == "__main__":
    unittest.main()
