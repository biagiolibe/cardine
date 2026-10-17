"""Queue archival decided from task state, its report, and terminal state import."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian

SHA = "a" * 40
AT = "2026-10-14T12:00:00Z"
ROUTES = {
    "DONE": ("DONE",), "QUEUED": (), "ACCEPTED": ("IN_PROGRESS", "READY_FOR_REVIEW", "ACCEPTED"),
    "IN_PROGRESS": ("IN_PROGRESS",), "ANSWERED": ("IN_PROGRESS", "ANSWERED"),
    "INCONCLUSIVE": ("IN_PROGRESS", "INCONCLUSIVE"),
}
LEAN_HEADER = "| Status | ID | Title |\n|---|---|---|\n"
GOVERNED_HEADER = "| Order | ID | Priority | Status | Review | Dependencies | Task file |\n|---|---|---|---|---|---|---|\n"


class StateArchivalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tasks").mkdir()
        (self.root / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n", encoding="utf-8")
        self.queue = self.root / "tasks/QUEUE.md"
        self.archive = self.root / "tasks/QUEUE_ARCHIVE.md"

    def state(self, task_id: str, status: str, workflow: str = "lean-delivery", spike: bool = False) -> None:
        current, transitions = "QUEUED", []
        for target in ROUTES[status]:
            transitions.append({"from": current, "to": target, "commit": SHA, "at": AT})
            current = target
        path = self.root / ".meridian/tasks" / f"{task_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "task_id": task_id, "workflow": workflow,
                                    "status": current, "transitions": transitions}), encoding="utf-8")
        if spike:
            (self.root / "tasks" / f"{task_id}.md").write_text(
                f"# Task\n\n> **ID**: `{task_id}`\n\nClass: SPIKE\n", encoding="utf-8")

    def archive_queue(self, contents: str, mode: str = "lean-delivery", *, with_state: bool = True):
        report: list[dict[str, object]] = []
        resolver = meridian._queue_state_resolver(self.root, mode) if with_state else None
        retained, archived = meridian._archive_completed_queue_sections(
            contents, self.queue, self.archive, mode, resolve_state=resolver, report=report)
        return retained, archived, {str(item["section"]): item for item in report}

    def test_section_at_any_heading_level_closes_when_every_state_is_terminal(self) -> None:
        for task in ("A", "B"):
            self.state(task, "DONE")
        # Column order and status wording are not read: the cell may say anything.
        contents = ("# Queue\n\n## Phase — Bootstrap\n\n| Title | ID | Priority | Status |\n|---|---|---|---|\n"
                    "| One | A | P1 | shipped |\n| Two | `B` | P1 | whatever |\n\n## Phase — Next\nPlanned.\n")
        retained, archived, report = self.archive_queue(contents)
        self.assertEqual(retained, "# Queue\n\n## Phase — Next\nPlanned.\n")
        self.assertIn("| One | A | P1 | shipped |", archived or "")
        entry = report["## Phase — Bootstrap"]
        self.assertTrue(entry["archive"])
        self.assertEqual(entry["rule"], "state")
        self.assertIn("terminal by task state", str(entry["reason"]))

    def test_governed_inconclusive_spike_closes_its_section(self) -> None:
        (self.root / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n", encoding="utf-8")
        self.state("056", "INCONCLUSIVE", "governed-sdd", spike=True)
        self.state("057", "ACCEPTED", "governed-sdd")
        contents = ("## Spikes\n\n" + GOVERNED_HEADER
                    + "| 1 | 056 | P0 | INCONCLUSIVE | SPIKE | — | [056](056.md) |\n"
                    + "| 2 | 057 | P0 | ACCEPTED | NOT_REQUIRED | — | [057](057.md) |\n")
        retained, archived, report = self.archive_queue(contents, "governed-sdd")
        self.assertEqual(retained, "\n")
        self.assertIn("| 1 | 056 | P0 | INCONCLUSIVE |", archived or "")
        self.assertTrue(report["## Spikes"]["archive"])
        # Without state the conservative table rule still holds the INCONCLUSIVE row open.
        held, none_archived, held_report = self.archive_queue(
            contents.replace("## Spikes", "### Spikes"), "governed-sdd", with_state=False)
        self.assertEqual(held, contents.replace("## Spikes", "### Spikes"))
        self.assertIsNone(none_archived)
        self.assertFalse(held_report["### Spikes"]["archive"])

    def test_section_with_one_open_state_is_retained_and_names_it(self) -> None:
        self.state("A", "DONE")
        self.state("B", "QUEUED")
        contents = "## Phase\n\n" + LEAN_HEADER + "| `[x]` | A | Done |\n| `[x]` | B | Claimed done |\n"
        retained, archived, report = self.archive_queue(contents)
        self.assertEqual(retained, contents)
        self.assertIsNone(archived)
        entry = report["## Phase"]
        self.assertFalse(entry["archive"])
        self.assertEqual(entry["open"], ["B"])
        self.assertIn("open by task state: B", str(entry["reason"]))

    def test_invalid_state_retains_the_section_with_its_reason(self) -> None:
        self.state("A", "DONE")
        path = self.root / ".meridian/tasks/A.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"lean-delivery"', '"governed-sdd"'), encoding="utf-8")
        contents = "## Phase\n\n" + LEAN_HEADER + "| `[x]` | A | Done |\n"
        retained, _archived, report = self.archive_queue(contents)
        self.assertEqual(retained, contents)
        self.assertIn("invalid task state: A", str(report["## Phase"]["reason"]))

    def test_legacy_only_queue_behaves_as_before(self) -> None:
        contents = ("## Level two\n\n" + LEAN_HEADER + "| `[x]` | A | Done |\n\n"
                    "### Level three\n\n" + LEAN_HEADER + "| `[x]` | B | Done |\n\n"
                    "### Open\n\n" + LEAN_HEADER + "| `[/]` | C | Working |\n")
        for with_state in (False, True):
            with self.subTest(with_state=with_state):
                retained, archived, report = self.archive_queue(contents, with_state=with_state)
                self.assertEqual(
                    (retained, archived),
                    meridian._archive_completed_queue_sections(contents, self.queue, self.archive))
                self.assertIn("| `[x]` | B | Done |", archived or "")
                self.assertNotIn("| `[x]` | A | Done |", archived or "")
                self.assertTrue(report["### Level three"]["archive"])
                self.assertFalse(report["## Level two"]["archive"])
                self.assertIn("heading level 2", str(report["## Level two"]["reason"]))
                self.assertEqual(report["### Open"]["legacy"], ["C"] if with_state else [])

    def test_mixed_section_needs_both_rules_to_agree(self) -> None:
        self.state("A", "DONE")
        table = LEAN_HEADER + "| `[x]` | A | By state |\n| `[x]` | B | By table |\n"
        closed = "### Mixed\n\n" + table
        retained, archived, report = self.archive_queue(closed)
        self.assertEqual(retained, "\n")
        self.assertIn("terminal by task state and by the table rule", str(report["### Mixed"]["reason"]))
        self.assertIn("By table", archived or "")
        # The table rule does not read `##` sections, so the legacy row keeps it open.
        retained, archived, report = self.archive_queue("## Mixed\n\n" + table)
        self.assertEqual(retained, "## Mixed\n\n" + table)
        self.assertIsNone(archived)
        self.assertEqual(report["## Mixed"]["legacy"], ["B"])
        self.assertIn("rows without a state file", str(report["## Mixed"]["reason"]))
        # An open legacy row keeps even a `###` section.
        retained, _archived, _report = self.archive_queue(closed.replace("`[x]` | B", "`[ ]` | B"))
        self.assertIn("`[ ]` | B", retained)

    def test_containers_never_archive_the_queue_around_a_closed_phase(self) -> None:
        for task in ("205", "206"):
            self.state(task, "DONE")
        contents = (
            "# Task Execution Queue\n\nIntro.\n\n## Priorities\n\n| Code | Meaning |\n|---|---|\n| P1 | Critical |\n\n"
            "## 🏃 Active Queue\n\nOrdered by return.\n\n### Phase 64 — Issues\n\n"
            "| Status | ID | Title | Priority |\n|--------|----|-------|----------|\n"
            "| `[x]` | 205 | First | P1 |\n| `[x]` | 206 | Second | P2 |\n"
        )
        retained, archived, report = self.archive_queue(contents)
        self.assertIn("# Task Execution Queue", retained)
        self.assertIn("## 🏃 Active Queue", retained)
        self.assertIn("| P1 | Critical |", retained)
        self.assertNotIn("Phase 64", retained)
        self.assertIn("### Phase 64 — Issues", archived or "")
        self.assertNotIn("Priorities", archived or "")
        self.assertEqual([title for title, item in report.items() if item["archive"]], ["### Phase 64 — Issues"])
        self.assertIn("container", str(report["## 🏃 Active Queue"]["reason"]))

    def test_outermost_section_wins_and_nested_sections_are_not_duplicated(self) -> None:
        for task in ("A", "B"):
            self.state(task, "DONE")
        contents = ("## Outer\n\n" + LEAN_HEADER + "| `[x]` | A | Done |\n\n### Inner\n\n"
                    + LEAN_HEADER + "| `[x]` | B | Done |\n\n## After\nKeep.\n")
        retained, archived, report = self.archive_queue(contents)
        self.assertEqual(retained, "## After\nKeep.\n")
        self.assertEqual((archived or "").count("### Inner"), 1)
        self.assertNotIn("### Inner", report)

    def test_dependency_satisfaction_is_unchanged_by_archival_from_state(self) -> None:
        from console_workflow import PROFILES, parse_queue

        (self.root / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n", encoding="utf-8")
        self.state("056", "INCONCLUSIVE", "governed-sdd", spike=True)
        self.state("057", "ACCEPTED", "governed-sdd")
        contents = ("## Closed\n\n" + GOVERNED_HEADER
                    + "| 1 | 056 | P0 | INCONCLUSIVE | SPIKE | — | [056](056.md) |\n"
                    + "| 2 | 057 | P0 | ACCEPTED | NOT_REQUIRED | — | [057](057.md) |\n\n"
                    "## Next\n\n" + GOVERNED_HEADER
                    + "| 3 | 058 | P1 | QUEUED | NOT_REQUIRED | 056 | [058](058.md) |\n"
                    + "| 4 | 059 | P1 | QUEUED | NOT_REQUIRED | 057 | [059](059.md) |\n")
        retained, archived, _report = self.archive_queue(contents, "governed-sdd")
        self.assertNotIn("| 1 | 056 |", retained)
        self.assertIn("| 1 | 056 |", archived or "")
        profile = PROFILES["governed-sdd"]
        rows = (*parse_queue(retained, "QUEUE.md", profile), *parse_queue(archived or "", "QUEUE_ARCHIVE.md", profile))
        by_id = {row.task_id: row.status for row in rows}
        waiting = {row.task_id for row in rows for dependency in row.dependencies.split(",")
                   if dependency.strip() in by_id and by_id[dependency.strip()] not in profile.satisfying}
        self.assertEqual(waiting, {"058"})

    def test_stage_report_and_warnings_cover_state_sections(self) -> None:
        self.state("A", "DONE")
        self.state("B", "QUEUED")
        contents = ("## Closed\n\n" + LEAN_HEADER + "| `[x]` | A | Done |\n\n"
                    "## Open\n\n" + LEAN_HEADER + "| `[ ]` | B | Waiting |\n")
        resolver = meridian._queue_state_resolver(self.root, "lean-delivery")
        self.assertEqual(meridian._queue_archival_warnings(contents, "lean-delivery", resolver), [])
        self.assertEqual(len(meridian._queue_archival_warnings(contents, "lean-delivery")), 2)


class IncludeTerminalImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tasks/done").mkdir(parents=True)
        (self.root / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n", encoding="utf-8")
        (self.root / "tasks/QUEUE.md").write_text(
            "### Phase\n\n| Status | ID | Title |\n|---|---|---|\n"
            "| `[x]` | 001 | Closed |\n| `[ ]` | 002 | Open |\n", encoding="utf-8")
        (self.root / "tasks/done/001.md").write_text("# Task\n\n> **ID**: `001`\n\nStatus: DONE\n", encoding="utf-8")
        (self.root / "tasks/002.md").write_text("# Task\n\n> **ID**: `002`\n\nStatus: QUEUED\n", encoding="utf-8")
        for args in (("init", "-q", "-b", "main"), ("add", "."),
                     ("-c", "user.name=T", "-c", "user.email=t@example.test", "commit", "-qm", "init")):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def actions(self, result: dict[str, object]) -> dict[str, str]:
        return {item["task_id"]: item["action"] for item in result["tasks"]}

    def test_terminal_tasks_are_skipped_without_the_flag(self) -> None:
        result = meridian.import_task_states(self.root, [])
        self.assertEqual(self.actions(result), {"001": "skip-terminal", "002": "write"})

    def test_dry_run_prints_and_apply_writes_without_overwriting(self) -> None:
        preview = meridian.import_task_states(self.root, [], include_terminal=True)
        self.assertEqual(self.actions(preview), {"001": "write", "002": "write"})
        done = next(item for item in preview["tasks"] if item["task_id"] == "001")
        self.assertEqual(done["state"]["status"], "DONE")
        self.assertFalse((self.root / ".meridian/tasks/001.json").exists())
        applied = meridian.import_task_states(self.root, [], apply=True, include_terminal=True)
        self.assertEqual(self.actions(applied), {"001": "write", "002": "write"})
        written = json.loads((self.root / ".meridian/tasks/001.json").read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "DONE")
        marker = (self.root / ".meridian/tasks/001.json").read_bytes()
        again = meridian.import_task_states(self.root, [], apply=True, include_terminal=True)
        self.assertEqual(self.actions(again), {"001": "skip-existing", "002": "skip-existing"})
        self.assertEqual((self.root / ".meridian/tasks/001.json").read_bytes(), marker)

    def test_disagreeing_texts_stop_before_writing_anything(self) -> None:
        (self.root / "tasks/done/001.md").write_text(
            "# Task\n\n> **ID**: `001`\n\nStatus: QUEUED\n", encoding="utf-8")
        with self.assertRaises(meridian.MeridianStop) as raised:
            meridian.import_task_states(self.root, [], apply=True, include_terminal=True)
        self.assertEqual(raised.exception.code, "TASK_STATE_INVALID")
        self.assertFalse((self.root / ".meridian/tasks").exists())

    def test_governed_terminal_requires_a_consistent_recorded_verdict(self) -> None:
        (self.root / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n", encoding="utf-8")
        (self.root / "tasks/QUEUE.md").write_text(
            "### Phase\n\n" + GOVERNED_HEADER + "| 1 | 001 | P0 | ACCEPTED | REQUIRED | — | [001](done/001.md) |\n",
            encoding="utf-8")
        (self.root / "tasks/done/001.md").write_text(
            "# Task\n\n> **ID**: `001`\n\nStatus: ACCEPTED\nReview: REQUIRED\n", encoding="utf-8")
        reviews = self.root / "tasks/reviews"
        reviews.mkdir()
        review = meridian.resolve_task_identity(self.root, "001", "existing").review_path
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text("# Review\n\n## Attempt 1 — CHANGES_REQUESTED\n\n## Attempt 2 — Remediation\n", encoding="utf-8")
        with self.assertRaises(meridian.MeridianStop) as raised:
            meridian.import_task_states(self.root, [], include_terminal=True)
        self.assertEqual(raised.exception.code, "TASK_STATE_INVALID")
        review.write_text("# Review\n\n## Attempt 1 — CHANGES_REQUESTED\n\n## Attempt 2 — APPROVE\n", encoding="utf-8")
        result = meridian.import_task_states(self.root, [], include_terminal=True)
        state = result["tasks"][0]["state"]
        self.assertEqual((state["status"], state["review"]["verdict"]), ("ACCEPTED", "APPROVE"))
        self.assertIsNone(state["review"]["reviewed_commit"])


if __name__ == "__main__":
    unittest.main()
