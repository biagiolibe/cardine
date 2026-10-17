"""Commit-bound review verdicts, refusal safety, and retry regressions."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian


class ReviewVerdictTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tasks").mkdir()
        (self.root / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n")
        (self.root / "LANGUAGE_POLICY.md").write_text("English\n")
        (self.root / "AGENTS.md").write_text("Read `PROJECT_WORKFLOW.md`.\n")
        self.record = self.root / "tasks/001.md"
        self.record.write_text("# Task\n\n> **ID**: `001`\n\nStatus: QUEUED\n")
        self.path = self.root / ".meridian/tasks/001.json"
        self.review = self.root / "tasks/reviews/001.md"
        self.git("init", "-q", "-b", "main")
        self.commit()
        self.git("switch", "-qc", "task-001")
        for status in ("IN_PROGRESS", "READY_FOR_REVIEW"):
            # This fixture isolates verdict authority; delivery gates have real-Git coverage elsewhere.
            with mock.patch.object(meridian, "delivery_readiness"):
                meridian.transition_task_state(self.root, "001", status)
        self.commit()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "Fixture")

    def cli(self, verdict, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/meridian.py"), "review", "verdict", "001", verdict,
                               "--project", str(self.root), "--format", "json", *args],
                              cwd=self.root, capture_output=True, text=True)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in (self.path, self.record, self.review) if p.exists()}

    def test_each_verdict_commit_binding_body_and_projection(self):
        for verdict, status in (("APPROVE", "ACCEPTED"), ("CHANGES_REQUESTED", "CHANGES_REQUESTED"),
                                ("BLOCKED", "READY_FOR_REVIEW")):
            with self.subTest(verdict=verdict):
                # Restore the fixture by constructing a fresh test environment.
                if verdict != "APPROVE":
                    self.setUp()
                head = self.git("rev-parse", "HEAD")
                result = self.cli(verdict, "--body", "Free-form findings.\n\n- Evidence")
                self.assertEqual(result.returncode, 0, result.stderr)
                state = json.loads(result.stdout)
                self.assertEqual(state, json.loads(self.path.read_text()))
                self.assertEqual(state["status"], status)
                self.assertEqual(state["review"], {"required": True, "verdict": verdict, "attempt": 1,
                                                 "reviewed_commit": head, "approved_by": "reviewer"})
                self.assertEqual(len(state["transitions"]), 2 if verdict == "BLOCKED" else 3)
                self.assertIn(f"Status: {status}", self.record.read_text())
                self.assertIn(f"## Attempt 1 — {verdict}\n\nFree-form findings.", self.review.read_text())

    def test_owner(self):
        result = self.cli("APPROVE", "--owner")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["review"]["approved_by"], "owner")

    def test_attempts_and_existing_prose_are_preserved(self):
        self.assertEqual(self.cli("CHANGES_REQUESTED", "--body", "First findings").returncode, 0)
        self.commit()
        for status in ("IN_PROGRESS", "READY_FOR_REVIEW"):
            # This fixture isolates verdict authority; delivery gates have real-Git coverage elsewhere.
            with mock.patch.object(meridian, "delivery_readiness"):
                meridian.transition_task_state(self.root, "001", status)
        self.commit()
        result = self.cli("APPROVE", "--body", "Fixed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["review"]["attempt"], 2)
        self.assertEqual(self.review.read_text(), "## Attempt 1 — CHANGES_REQUESTED\n\nFirst findings\n\n## Attempt 2 — APPROVE\n\nFixed\n")

    def test_same_commit_rerun_is_noop_for_every_verdict(self):
        for verdict in ("APPROVE", "CHANGES_REQUESTED", "BLOCKED"):
            with self.subTest(verdict=verdict):
                if verdict != "APPROVE":
                    self.setUp()
                result = self.cli(verdict, "--body", "Review body")
                before = self.snapshot()
                repeated = self.cli(verdict, "--body", "Review body")
                self.assertEqual(repeated.returncode, 0, repeated.stderr)
                self.assertEqual(repeated.stdout, result.stdout)
                self.assertEqual(self.snapshot(), before)

    def test_wrong_status_and_wrong_branch_and_detached_head_write_nothing(self):
        for branch in ("main", "--detach"):
            with self.subTest(branch=branch):
                self.git("switch", branch)
                before = self.snapshot()
                result = self.cli("APPROVE")
                self.assertEqual(result.returncode, 2)
                self.assertIn("BLOCKED TASK_STATE_INVALID:", result.stderr)
                self.assertEqual(self.snapshot(), before)
                self.git("switch", "task-001")
        self.assertEqual(self.cli("APPROVE").returncode, 0)
        self.commit()
        before = self.snapshot()
        for verdict in ("APPROVE", "CHANGES_REQUESTED", "BLOCKED"):
            result = self.cli(verdict)
            self.assertEqual(result.returncode, 2)
            self.assertIn("review status", result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_dirty_tracked_untracked_and_staged_refuse_without_writes(self):
        for kind in ("tracked", "untracked", "staged"):
            with self.subTest(kind=kind):
                if kind != "tracked":
                    self.setUp()
                if kind == "tracked":
                    self.record.write_text(self.record.read_text() + "Changed\n")
                else:
                    (self.root / "extra.txt").write_text("Unrelated")
                if kind == "staged":
                    self.git("add", "extra.txt")
                before = self.snapshot()
                result = self.cli("APPROVE")
                self.assertEqual(result.returncode, 2)
                self.assertIn("worktree", result.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_noop_does_not_hide_modified_outputs_or_unrelated_dirt(self):
        self.assertEqual(self.cli("APPROVE").returncode, 0)
        self.review.write_text(self.review.read_text() + "Edited\n")
        before = self.snapshot()
        self.assertEqual(self.cli("APPROVE").returncode, 2)
        self.assertEqual(self.snapshot(), before)
        self.setUp()
        self.assertEqual(self.cli("BLOCKED").returncode, 0)
        (self.root / "extra.txt").write_text("Unrelated")
        before = self.snapshot()
        self.assertEqual(self.cli("BLOCKED").returncode, 2)
        self.assertEqual(self.snapshot(), before)

    def test_atomic_write_contains_review_and_transition_and_failure_changes_nothing(self):
        before = self.snapshot()
        real_replace = meridian.os.replace
        replacements = []

        def replace(source, destination):
            self.assertEqual(self.snapshot(), before)
            state = json.loads(Path(source).read_text())
            self.assertEqual(state["status"], "ACCEPTED")
            self.assertEqual(state["review"]["verdict"], "APPROVE")
            self.assertEqual(state["transitions"][-1]["to"], "ACCEPTED")
            replacements.append(destination)
            real_replace(source, destination)

        with mock.patch.object(meridian.os, "replace", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                meridian.record_review_verdict(self.root, "001", "APPROVE")
        self.assertEqual(self.snapshot(), before)
        with mock.patch.object(meridian.os, "replace", side_effect=replace):
            meridian.record_review_verdict(self.root, "001", "APPROVE")
        self.assertEqual(replacements, [self.path])


if __name__ == "__main__":
    unittest.main()
