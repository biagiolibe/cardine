"""Terminal tasks stay in the generated views; no queue archive; terminal state import."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION, freeze_record

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cardine_cli
from cardine.tasks import status_render
import cardine.shared.errors as shared_errors
from cardine.tasks import identity as owner_tasks_identity
from cardine.tasks import importer as owner_tasks_importer

SHA = "a" * 40
AT = "2026-10-14T12:00:00Z"
GOVERNED_HEADER = "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n|---|---|---|---|---|---|---|\n"


class TerminalTasksStayInViewsTest(unittest.TestCase):
    """The queue is a generated view: a closed phase is never moved out of the state."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tasks").mkdir()
        write_project_config(self.root, "lean")
        self.queue = self.root / "tasks/QUEUE.md"
        self.archive = self.root / "tasks/QUEUE_ARCHIVE.md"
        self.plan = self.root / "PROJECT_PLAN.md"
        self.plan.write_text(f"Narrative.\n{status_render.REGION_BEGIN}\n{status_render.REGION_END}\n", encoding="utf-8")

    def task(self, task_id: str, status: str, dependencies: str = "none") -> None:
        steps = {"queued": (), "in_progress": ("in_progress",), "done": ("in_progress", "done"),
                 "cancelled": ("cancelled",)}[status]
        current, transitions = "queued", []
        for target in steps:
            transitions.append({"from": current, "to": target, "commit": SHA, "at": AT,
                                **({"authority": "owner", "reason": "dropped"} if target == "cancelled" else {})})
            current = target
        path = self.root / ".cardine/tasks" / f"{task_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "task_id": task_id, "workflow": "single",
                                    "status": current, "transitions": transitions}), encoding="utf-8")
        (self.root / "tasks" / f"{task_id}.md").write_text(
            f"# Task {task_id}\n\n> **ID**: `{task_id}`\n> **Priority**: P1\n> **Phase**: Build\n\n"
            f"## Dependencies\n- **Depends on**: {dependencies}\n", encoding="utf-8")
        freeze_record(self.root, task_id)

    def test_closed_phase_is_never_archived_and_totals_keep_it(self) -> None:
        self.task("A", "done")
        self.task("B", "queued")
        status_render.write_views(self.root)
        self.assertFalse(self.archive.exists())
        self.assertNotIn("| A |", self.queue.read_text())
        self.assertIn("total=2", self.queue.read_text())
        self.assertIn("| done | A |", self.plan.read_text())

    def test_queue_of_only_terminal_tasks_still_renders_without_an_archive(self) -> None:
        self.task("A", "done")
        self.task("B", "cancelled")
        status_render.write_views(self.root)
        self.assertFalse(self.archive.exists())
        self.assertIn("done=1, cancelled=1, total=2", self.queue.read_text())
        self.assertIn("| cancelled | B |", self.plan.read_text())

    def test_landing_a_task_never_writes_an_archive_file(self) -> None:
        self.task("A", "in_progress")
        status_render.write_views(self.root)
        self.task("A", "done")
        status_render.write_views(self.root)
        self.assertFalse(self.archive.exists())
        self.assertEqual(status_render.stale_views(self.root), [])

    def test_dependency_results_do_not_depend_on_the_open_view(self) -> None:
        from cardine.tasks.status import load_task_snapshot

        self.task("A", "done")
        self.task("B", "cancelled")
        self.task("C", "queued", dependencies="A")
        self.task("D", "queued", dependencies="B")
        before, _inputs, _config = load_task_snapshot(self.root, all_tasks=True)
        status_render.write_views(self.root)
        after, _inputs, _config = load_task_snapshot(self.root, all_tasks=True)
        self.assertEqual(before["totals"], after["totals"])
        startable = {row["id"]: row["startable"] for row in after["tasks"]}
        self.assertEqual(startable["C"], True)
        self.assertEqual(startable["D"], False)
        self.assertEqual({row["id"]: row["startable"] for row in before["tasks"]}, startable)


class IncludeTerminalImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tasks/done").mkdir(parents=True)
        write_project_config(self.root, "lean", validation=VALIDATION)
        (self.root / "tasks/QUEUE.md").write_text(
            "### Phase\n\n| Status | ID | Title |\n|---|---|---|\n"
            "| `[x]` | 001 | Closed |\n| `[ ]` | 002 | Open |\n", encoding="utf-8")
        (self.root / "tasks/done/001.md").write_text(contract_record("001", extra="Status: done\n"), encoding="utf-8")
        (self.root / "tasks/002.md").write_text(contract_record("002", extra="Status: queued\n"), encoding="utf-8")
        for args in (("init", "-q", "-b", "main"), ("add", "."),
                     ("-c", "user.name=T", "-c", "user.email=t@example.test", "commit", "-qm", "init")):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def actions(self, result: dict[str, object]) -> dict[str, str]:
        return {item["task_id"]: item["action"] for item in result["tasks"]}

    def test_terminal_tasks_are_skipped_without_the_flag(self) -> None:
        result = owner_tasks_importer.import_task_states(self.root, [])
        self.assertEqual(self.actions(result), {"001": "skip-terminal", "002": "write"})

    def test_dry_run_prints_and_apply_writes_without_overwriting(self) -> None:
        preview = owner_tasks_importer.import_task_states(self.root, [], include_terminal=True)
        self.assertEqual(self.actions(preview), {"001": "write", "002": "write"})
        done = next(item for item in preview["tasks"] if item["task_id"] == "001")
        self.assertEqual(done["state"]["status"], "done")
        self.assertFalse((self.root / ".cardine/tasks/001.json").exists())
        applied = owner_tasks_importer.import_task_states(self.root, [], apply=True, include_terminal=True)
        self.assertEqual(self.actions(applied), {"001": "write", "002": "write"})
        written = json.loads((self.root / ".cardine/tasks/001.json").read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "done")
        marker = (self.root / ".cardine/tasks/001.json").read_bytes()
        again = owner_tasks_importer.import_task_states(self.root, [], apply=True, include_terminal=True)
        self.assertEqual(self.actions(again), {"001": "skip-existing", "002": "skip-existing"})
        self.assertEqual((self.root / ".cardine/tasks/001.json").read_bytes(), marker)

    def test_disagreeing_texts_stop_before_writing_anything(self) -> None:
        (self.root / "tasks/done/001.md").write_text(
            contract_record("001", extra="Status: queued\n"), encoding="utf-8")
        with self.assertRaises(shared_errors.CardineStop) as raised:
            owner_tasks_importer.import_task_states(self.root, [], apply=True, include_terminal=True)
        self.assertEqual(raised.exception.code, "TASK_STATE_INVALID")
        self.assertFalse((self.root / ".cardine/tasks").exists())

    def test_governed_terminal_requires_a_consistent_recorded_verdict(self) -> None:
        write_project_config(self.root, "governed", validation=VALIDATION)
        (self.root / "tasks/QUEUE.md").write_text(
            "### Phase\n\n" + GOVERNED_HEADER + "| 1 | 001 | P0 | done | REQUIRED | — | [001](done/001.md) |\n",
            encoding="utf-8")
        (self.root / "tasks/done/001.md").write_text(
            contract_record("001", extra="Status: done\nReview: REQUIRED\n"), encoding="utf-8")
        reviews = self.root / "tasks/reviews"
        reviews.mkdir()
        review = owner_tasks_identity.resolve_task_identity(self.root, "001", "existing").review_path
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text("# Review\n\n## Attempt 1 — CHANGES_REQUESTED\n\n## Attempt 2 — Remediation\n", encoding="utf-8")
        with self.assertRaises(shared_errors.CardineStop) as raised:
            owner_tasks_importer.import_task_states(self.root, [], include_terminal=True)
        self.assertEqual(raised.exception.code, "TASK_STATE_INVALID")
        review.write_text("# Review\n\n## Attempt 1 — CHANGES_REQUESTED\n\n## Attempt 2 — APPROVE\n", encoding="utf-8")
        result = owner_tasks_importer.import_task_states(self.root, [], include_terminal=True)
        state = result["tasks"][0]["state"]
        self.assertEqual((state["status"], state["review"]["verdict"]), ("done", "APPROVE"))
        self.assertIsNone(state["review"]["reviewed_commit"])


if __name__ == "__main__":
    unittest.main()
