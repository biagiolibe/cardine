"""Explicit legacy adoption preserves evidence and refuses contradictory texts."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian
import task_state


class TaskStateImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tasks").mkdir()
        (self.root / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n")
        (self.root / "LANGUAGE_POLICY.md").write_text("English\n")
        (self.root / "AGENTS.md").write_text("Read `PROJECT_WORKFLOW.md`.\n")
        self.queue = self.root / "tasks/QUEUE.md"
        self.rows = []
        self.git("init", "-q", "-b", "main")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "Fixture")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def add_task(self, task_id, status="QUEUED", *, record_status=None, policy="REQUIRED", spike=False, review=None):
        record = self.root / f"tasks/{task_id}.md"
        record.write_text(f"> **ID**: `{task_id}`\nStatus: {record_status or status}\nReview: {policy}\n"
                          + ("Class: SPIKE\n" if spike else ""))
        self.rows.append(f"| {task_id} | {status} | {policy} | [{task_id}]({task_id}.md) |")
        self.queue.write_text("| ID | Status | Review | Task file |\n|---|---|---|---|\n" + "\n".join(self.rows) + "\n")
        if review:
            path = self.root / f"tasks/reviews/{task_id}.md"
            path.parent.mkdir(exist_ok=True)
            path.write_text(review)
        return record

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/meridian.py"), "--framework-root", str(ROOT),
                               "task", "state", "import", *args, "--project", str(self.root), "--format", "json"],
                              capture_output=True, text=True)

    def test_preview_apply_repeat_and_subset_preserve_text(self):
        record = self.add_task("001", "IN_PROGRESS")
        self.add_task("002")
        before = record.read_bytes(), self.queue.read_bytes()
        result = self.cli("task-001")
        self.assertEqual(result.returncode, 0, result.stderr)
        proposal = json.loads(result.stdout)["tasks"][0]
        self.assertEqual(proposal["path"], ".meridian/tasks/001.json")
        self.assertEqual(proposal["evidence"]["queue"]["status"], "IN_PROGRESS")
        self.assertEqual(proposal["evidence"]["record"]["path"], "tasks/001.md")
        self.assertFalse(proposal["evidence"]["review"]["exists"])
        self.assertFalse((self.root / ".meridian/tasks").exists())
        self.assertEqual(self.cli("001", "--apply").returncode, 0)
        path = self.root / proposal["path"]
        state = task_state.read_task_state(self.root, "001", "governed-sdd", stop_factory=meridian.stop_error)
        self.assertEqual(state["transitions"][0]["commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(state["status"], "IN_PROGRESS")
        original = path.read_bytes()
        again = self.cli("001", "--apply")
        self.assertEqual(json.loads(again.stdout)["tasks"][0]["action"], "skip-existing")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual((record.read_bytes(), self.queue.read_bytes()), before)
        self.assertFalse((self.root / ".meridian/tasks/002.json").exists())

    def test_archived_record_import_preserves_record_and_stale_queue_link(self):
        record = self.add_task("001", "IN_PROGRESS")
        archived = self.root / "tasks/done/001.md"
        archived.parent.mkdir()
        record.rename(archived)
        before = archived.read_bytes(), self.queue.read_bytes()
        result = self.cli("001", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        proposal = json.loads(result.stdout)["tasks"][0]
        self.assertEqual(proposal["evidence"]["record"]["path"], "tasks/done/001.md")
        self.assertEqual(json.loads((self.root / proposal["path"]).read_text())["status"], "IN_PROGRESS")
        self.assertEqual((archived.read_bytes(), self.queue.read_bytes()), before)
        self.assertFalse(record.exists())

    def test_archived_recovery_refuses_unrelated_missing_queue_link(self):
        record = self.add_task("001", "IN_PROGRESS")
        archived = self.root / "tasks/done/001.md"
        archived.parent.mkdir()
        record.rename(archived)
        self.queue.write_text(self.queue.read_text().replace("(001.md)", "(different.md)"))
        result = self.cli("001", "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / ".meridian/tasks/001.json").exists())

    def test_terminal_tasks_need_no_record_or_state(self):
        for task_id, status in (("001", "ACCEPTED"), ("002", "ANSWERED"), ("003", "INCONCLUSIVE")):
            self.add_task(task_id, status).unlink()
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({item["action"] for item in json.loads(result.stdout)["tasks"]}, {"skip-terminal"})
        self.assertFalse((self.root / ".meridian/tasks").exists())

    def test_all_proposals_validated_before_any_write(self):
        self.add_task("001")
        self.add_task("002", "IN_PROGRESS", record_status="READY_FOR_REVIEW")
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLOCKED TASK_STATE_INVALID:", result.stderr)
        self.assertIn("queue Status='IN_PROGRESS'; record Status='READY_FOR_REVIEW'", result.stderr)
        self.assertFalse((self.root / ".meridian/tasks").exists())

    def test_dated_review_headings_preserved_and_imported(self):
        self.add_task("001", "CHANGES_REQUESTED", review="## Attempt 2 — 2026-10-11 — CHANGES_REQUESTED\nFindings\n")
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((self.root / ".meridian/tasks/001.json").read_text())
        self.assertEqual(state["review"]["verdict"], "CHANGES_REQUESTED")
        self.assertEqual(state["review"]["attempt"], 2)
        task_state.validate_task_state(state, "001", "governed-sdd")
        self.assertIn("2026-10-11", json.loads(result.stdout)["tasks"][0]["evidence"]["review"]["heading"])

    def test_review_disagreement_and_malformed_evidence_refused(self):
        for review in ("## Attempt 1 — 2026-10-11 — APPROVE\n", "## Attempt 1 — unknown\n"):
            with self.subTest(review=review):
                self.rows.clear()
                self.add_task("001", "READY_FOR_REVIEW", review=review)
                result = self.cli("--apply")
                self.assertEqual(result.returncode, 2)
                self.assertIn("TASK_STATE_INVALID", result.stderr)
                self.assertFalse((self.root / ".meridian/tasks/001.json").exists())

    def test_lean_missing_status_and_derived_progress(self):
        (self.root / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n")
        record = self.add_task("001", "`[/]`")
        record.write_text("> **ID**: `001`\n")
        self.add_task("002", "`[x]`").unlink()
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = task_state.read_task_state(self.root, "001", "lean-delivery", stop_factory=meridian.stop_error)
        self.assertEqual(state["status"], "QUEUED")
        self.assertEqual(state["transitions"], [])
        self.assertEqual(json.loads(result.stdout)["tasks"][1]["action"], "skip-terminal")

    def test_spike_and_no_review_use_their_legal_machines(self):
        self.add_task("001", "IN_PROGRESS", spike=True, policy="NOT_REQUIRED")
        self.add_task("002", "IN_PROGRESS", policy="NOT_REQUIRED")
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        for task_id, spike in (("001", True), ("002", False)):
            state = task_state.read_task_state(self.root, task_id, "governed-sdd", spike=spike,
                                               review_required=None, stop_factory=meridian.stop_error)
            self.assertFalse(state["review"]["required"])
            if not spike:
                meridian.transition_task_state(self.root, task_id, "ACCEPTED")
                task_state.read_task_state(self.root, task_id, "governed-sdd", review_required=None,
                                           stop_factory=meridian.stop_error)

    def test_duplicate_rows_and_review_policy_disagreement_refused(self):
        record = self.add_task("001")
        self.rows.append(self.rows[0])
        self.queue.write_text(self.queue.read_text() + self.rows[0] + "\n")
        self.assertIn("found 2", self.cli("--apply").stderr)
        self.queue.write_text("| ID | Status | Review | Task file |\n|---|---|---|---|\n" + self.rows[0] + "\n")
        record.write_text(record.read_text().replace("Review: REQUIRED", "Review: NOT_REQUIRED"))
        result = self.cli("--apply")
        self.assertIn("queue Review='REQUIRED'; record Review='NOT_REQUIRED'", result.stderr)
        self.assertFalse((self.root / ".meridian/tasks").exists())


if __name__ == "__main__":
    unittest.main()
