"""Tracked state schema, machine, CLI, and bounded-read regressions."""

from __future__ import annotations

import copy
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
import task_state

SHA = "a" * 40
AT = "2026-10-11T12:00:00Z"


class MachineTaskStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tasks").mkdir()
        (self.root / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n")
        (self.root / "LANGUAGE_POLICY.md").write_text("English\n")
        (self.root / "AGENTS.md").write_text("Read `PROJECT_WORKFLOW.md`.\n")
        self.record = self.root / "tasks/001.md"
        self.record.write_text("# Task\n\n> **ID**: `001`\n\nStatus: QUEUED\n")
        self.path = task_state.state_path(self.root, "001")
        self.git("init", "-q", "-b", "main")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "Initial")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def cli(self, status):
        return subprocess.run([sys.executable, str(ROOT / "scripts/meridian.py"), "task", "transition", "001", status,
                               "--project", str(self.root), "--format", "json"], capture_output=True, text=True)

    def state(self, workflow="lean-delivery", steps=()):
        current = "QUEUED"
        transitions = []
        for destination in steps:
            transitions.append({"from": current, "to": destination, "commit": SHA, "at": AT})
            current = destination
        return {"version": 1, "task_id": "001", "workflow": workflow,
                "status": current, "transitions": transitions}

    def write(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state))

    def read(self, workflow="lean-delivery", spike=False):
        return task_state.read_task_state(self.root, "001", workflow, spike=spike, stop_factory=meridian.stop_error)

    def test_every_machine_edge_and_terminal_refusals(self):
        paths = {
            ("lean-delivery", False): [("DONE",)],
            ("governed-sdd", False): [
                ("IN_PROGRESS", "READY_FOR_REVIEW", "ACCEPTED"),
                ("IN_PROGRESS", "READY_FOR_REVIEW", "CHANGES_REQUESTED", "IN_PROGRESS", "READY_FOR_REVIEW", "ACCEPTED"),
            ],
            ("governed-sdd", True): [("IN_PROGRESS", "ANSWERED"), ("IN_PROGRESS", "INCONCLUSIVE")],
        }
        for (workflow, spike), routes in paths.items():
            for route in routes:
                for length in range(len(route) + 1):
                    with self.subTest(workflow=workflow, spike=spike, path=route[:length]):
                        state = self.state(workflow, route[:length])
                        self.assertEqual(task_state.validate_task_state(state, "001", workflow, spike=spike), state)
                with self.assertRaisesRegex(task_state.TaskStateInvalid, "transitions"):
                    task_state.validate_task_state(self.state(workflow, (*route, "QUEUED")), "001", workflow, spike=spike)
        for workflow, target in (("lean-delivery", "IN_PROGRESS"), ("governed-sdd", "ACCEPTED")):
            with self.assertRaises(task_state.TaskStateInvalid):
                task_state.validate_task_state(self.state(workflow, (target,)), "001", workflow)
        with self.assertRaises(task_state.TaskStateInvalid):
            task_state.validate_task_state(self.state("governed-sdd", ("IN_PROGRESS", "ANSWERED")), "001", "governed-sdd")

    def test_archived_record_transition_preserves_location_and_queue(self):
        queue = self.root / "tasks/QUEUE.md"
        queue.write_text("| ID | Status | Task file |\n|---|---|---|\n| 001 | QUEUED | [001](001.md) |\n")
        archived = self.root / "tasks/done/001.md"
        archived.parent.mkdir()
        self.record.rename(archived)
        before = queue.read_bytes()
        result = self.cli("DONE")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read()["status"], "DONE")
        self.assertIn("Status: DONE", archived.read_text())
        self.assertFalse(self.record.exists())
        self.assertEqual(queue.read_bytes(), before)

    def test_missing_resume_without_worktree_uses_primary(self):
        import shlex
        resume = meridian.stop_resume("TASK_STATE_MISSING", task_id="001", project=self.root)
        self.assertEqual(shlex.split(resume)[shlex.split(resume).index("--project") + 1], str(self.root))

    def test_first_creation_head_timestamp_and_projection(self):
        result = self.cli("DONE")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state, self.read())
        self.assertEqual(state["transitions"][0]["commit"], self.git("rev-parse", "HEAD"))
        self.assertTrue(state["transitions"][0]["at"].endswith("Z"))
        self.assertIn("Status: DONE\n", self.record.read_text())
        self.assertEqual(len(state["transitions"]), 1)

    def test_governed_cli_requires_delivery_and_preserves_spike(self):
        (self.root / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n")
        self.assertEqual(self.cli("IN_PROGRESS").returncode, 0)
        before = self.path.read_bytes()
        refused = self.cli("READY_FOR_REVIEW")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("BLOCKED WRONG_WORKTREE", refused.stderr)
        self.assertEqual(self.path.read_bytes(), before)
        self.path.unlink()
        self.record.write_text(self.record.read_text() + "Class: SPIKE\n")
        for status in ("IN_PROGRESS", "ANSWERED"):
            result = self.cli(status)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read("governed-sdd", True)["status"], "ANSWERED")

    def test_review_not_required_goes_directly_to_accepted(self):
        (self.root / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n")
        self.record.write_text(self.record.read_text() + "Review: NOT_REQUIRED\n")
        for status in ("IN_PROGRESS", "ACCEPTED"):
            result = self.cli(status)
            self.assertEqual(result.returncode, 0, result.stderr)
        state = task_state.read_task_state(self.root, "001", "governed-sdd", review_required=False,
                                          stop_factory=meridian.stop_error)
        self.assertEqual(state["status"], "ACCEPTED")
        with self.assertRaises(task_state.TaskStateInvalid):
            task_state.validate_task_state(state, "001", "governed-sdd")

    def test_no_projection_field_is_added(self):
        self.record.write_text("> **ID**: `001`\n")
        original = self.record.read_bytes()
        self.assertEqual(self.cli("DONE").returncode, 0)
        self.assertEqual(self.record.read_bytes(), original)

    def test_atomic_replace_and_write_failure_preserves_files(self):
        self.write(self.state())
        before = self.path.read_bytes(), self.record.read_bytes()
        real_replace = meridian.os.replace
        calls = []

        def replace(source, destination):
            self.assertEqual(self.path.read_bytes(), before[0])
            self.assertEqual(Path(source).parent, self.path.parent)
            self.assertEqual(json.loads(Path(source).read_text())["status"], "DONE")
            calls.append(destination)
            real_replace(source, destination)

        with mock.patch.object(meridian.os, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaises(OSError):
                meridian.transition_task_state(self.root, "001", "DONE")
        self.assertEqual((self.path.read_bytes(), self.record.read_bytes()), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        with mock.patch.object(meridian.os, "replace", side_effect=replace):
            meridian.transition_task_state(self.root, "001", "DONE")
        self.assertEqual(calls, [self.path])

    def test_missing_stop(self):
        with self.assertRaises(meridian.MeridianStop) as caught:
            self.read()
        self.assertTrue(str(caught.exception).startswith("BLOCKED TASK_STATE_MISSING:"))
        self.assertIn("meridian task state import 001", str(caught.exception))
        self.assertFalse(self.path.exists())

    def test_invalid_stop(self):
        self.write(self.state())
        before = self.path.read_bytes(), self.record.read_bytes()
        result = self.cli("UNKNOWN")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("BLOCKED TASK_STATE_INVALID:"), result.stderr)
        self.assertIn("allowed ['DONE']; found 'UNKNOWN'", result.stderr)
        self.assertEqual((self.path.read_bytes(), self.record.read_bytes()), before)
        self.path.unlink()
        result = self.cli("IN_PROGRESS")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.path.exists())

    def test_invalid_existing_schema_history_and_identity_write_nothing(self):
        good = self.state(steps=("DONE",))
        cases = []
        for field, value in (("version", True), ("task_id", "002"), ("workflow", "governed-sdd"), ("status", "UNKNOWN"), ("extra", 1)):
            changed = copy.deepcopy(good)
            changed[field] = value
            cases.append(changed)
        for field, value in (("commit", "abc"), ("at", "2026-02-30T00:00:00Z"), ("at", "2026-10-11T12:00:00+01:00"), ("from", "DONE"), ("to", "QUEUED")):
            changed = copy.deepcopy(good)
            changed["transitions"][0][field] = value
            cases.append(changed)
        changed = copy.deepcopy(good)
        changed["status"] = "QUEUED"
        cases += [changed, {"version": 1}, [], None]
        for state in cases:
            with self.subTest(state=state):
                self.write(state)
                before = self.path.read_bytes(), self.record.read_bytes()
                result = self.cli("DONE")
                self.assertEqual(result.returncode, 2)
                self.assertIn("BLOCKED TASK_STATE_INVALID:", result.stderr)
                self.assertIn("allowed", result.stderr)
                self.assertIn("found", result.stderr)
                self.assertEqual((self.path.read_bytes(), self.record.read_bytes()), before)
        self.path.write_text("{")
        self.assertIn("BLOCKED TASK_STATE_INVALID:", self.cli("DONE").stderr)

    def test_optional_review_schema(self):
        state = self.state()
        state["review"] = {"required": True, "verdict": None, "attempt": 1,
                           "reviewed_commit": None, "approved_by": None}
        task_state.validate_task_state(state, "001", "lean-delivery")
        state["review"].update(verdict="APPROVE", reviewed_commit=SHA, approved_by="owner")
        task_state.validate_task_state(state, "001", "lean-delivery")
        state["review"]["attempt"] = 0
        with self.assertRaisesRegex(task_state.TaskStateInvalid, "review.attempt"):
            task_state.validate_task_state(state, "001", "lean-delivery")

    def test_reader_never_enumerates_state_directory(self):
        self.write(self.state())
        with mock.patch.object(Path, "iterdir", side_effect=AssertionError("scan")), \
             mock.patch.object(Path, "glob", side_effect=AssertionError("scan")), \
             mock.patch.object(Path, "rglob", side_effect=AssertionError("scan")):
            self.assertEqual(self.read()["status"], "QUEUED")

    def test_context_size_and_read_guard_sets_exclude_state_files(self):
        before = meridian.context_size_report(self.root, "implementation")
        self.write(self.state())
        self.record.write_text(self.record.read_text() + "\n## Authority\n\n- `.meridian/tasks/001.json`#State\n")
        with mock.patch.object(meridian, "extract_spec_heading", side_effect=AssertionError("state startup read")):
            report = meridian.context_size_report(self.root, "implementation", task_id="001")
        self.assertNotIn(".meridian/tasks/001.json", [item["path"] for item in report["files"]])
        for role in ("implementation", "review"):
            after = meridian.context_size_report(self.root, role)
            self.assertEqual(before["total"], after["total"])
            self.assertNotIn(".meridian/tasks/001.json", [item["path"] for item in after["files"]])
        # Even accidental routed Markdown citations into the state directory are excluded.
        fake = self.path.with_suffix(".md")
        fake.write_text("large state payload\n" * 1000)
        (self.root / "AGENTS.md").write_text("Read `.meridian/tasks/001.md`.\n")
        report = meridian.context_size_report(self.root, "implementation")
        self.assertNotIn(".meridian/tasks/001.md", [item["path"] for item in report["files"]])
        self.assertNotIn(Path(".meridian/tasks/001.md"), meridian.context_router_files(self.root))
        for unsafe in ("../001", "/001", "..", "bad id"):
            with self.assertRaises(task_state.TaskStateInvalid):
                task_state.state_path(self.root, unsafe)


if __name__ == "__main__":
    unittest.main()
