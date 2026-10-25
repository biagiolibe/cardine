"""Tracked state schema, machine, CLI, and bounded-read regressions."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from project_config_support import write_project_config
from task_contract_support import contract_record, VALIDATION, freeze_record, seal_state
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cardine_cli
from stop_recovery_support import run_recovery, resume_from
from cardine.tasks import transitions as owner_tasks_transitions
from cardine.shared import context as owner_shared_context
import cardine.shared.errors as shared_errors
import cardine.tasks.state as task_state
from cardine.shared import authority as owner_shared_authority
from cardine.stops import render as owner_stops_render

SHA = "a" * 40
AT = "2026-10-11T12:00:00Z"


class MachineTaskStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "tasks").mkdir()
        self.git("init", "-q", "-b", "main")
        write_project_config(self.root, "lean", validation=VALIDATION)
        (self.root / "LANGUAGE_POLICY.md").write_text("English\n")
        (self.root / "AGENTS.md").write_text("Read `PROJECT_WORKFLOW.md`.\n")
        self.record = self.root / "tasks/001.md"
        self.record.write_text(contract_record(extra="Status: queued\n"))
        self.path = task_state.state_path(self.root, "001")
        self.write(self.state())
        freeze_record(self.root, "001", self.record)
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "Initial")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True, text=True).stdout.strip()

    def cli(self, status, *options):
        return subprocess.run([sys.executable, str(ROOT / "scripts/cardine_cli.py"), "task", "transition", "001", status, *options,
                               "--project", str(self.root), "--format", "json"], capture_output=True, text=True)

    def state(self, workflow="single", steps=()):
        current = "queued"
        transitions = []
        for destination in steps:
            transitions.append({"from": current, "to": destination, "commit": SHA, "at": AT})
            current = destination
        return {"version": 1, "task_id": "001", "workflow": workflow,
                "status": current, "transitions": transitions}

    def write(self, state):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state))

    def read(self, workflow="single", spike=False):
        return task_state.read_task_state(self.root, "001", workflow, spike=spike, stop_factory=owner_stops_render.stop_error)

    def test_every_machine_edge_and_terminal_refusals(self):
        expected = {"queued": {"in_progress", "cancelled"},
                    "in_progress": {"in_review", "done", "cancelled"},
                    "in_review": {"in_progress", "cancelled"}, "done": set(), "cancelled": set()}
        prefixes = {"queued": (), "in_progress": ("in_progress",),
                    "in_review": ("in_progress", "in_review"),
                    "done": ("in_progress", "done"), "cancelled": ("cancelled",)}
        for workflow in ("single", "single"):
            for spike in (False, True):
                for required in (False, True):
                    graph = task_state.machine(workflow, spike, required)
                    for source, prefix in prefixes.items():
                        if source == "in_review" and not required:
                            continue
                        for target in expected:
                            state = self.state(workflow, (*prefix, target))
                            for edge in state["transitions"]:
                                if edge["to"] == "cancelled":
                                    edge.update(authority="owner directive", reason="No longer needed")
                            allowed = target in expected[source] and (target != "in_review" or required)
                            self.assertEqual(target in graph[source], allowed)
                            with self.subTest(workflow=workflow, spike=spike, review=required, source=source, target=target):
                                if allowed:
                                    self.assertEqual(task_state.validate_task_state(state, "001", workflow,
                                        spike=spike, review_required=required), state)
                                else:
                                    with self.assertRaises(task_state.TaskStateInvalid):
                                        task_state.validate_task_state(state, "001", workflow,
                                            spike=spike, review_required=required)

    def test_archived_record_transition_preserves_location_and_queue(self):
        queue = self.root / "tasks/QUEUE.md"
        queue.write_text("| ID | Status | Task file |\n|---|---|---|\n| 001 | queued | [001](001.md) |\n")
        archived = self.root / "tasks/done/001.md"
        archived.parent.mkdir()
        self.record.rename(archived)
        before = queue.read_bytes()
        result = self.cli("in_progress")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read()["status"], "in_progress")
        self.assertIn("Status: queued", archived.read_text())
        self.assertFalse(self.record.exists())
        self.assertEqual(queue.read_bytes(), before)

    def test_missing_resume_without_worktree_uses_primary(self):
        import shlex
        resume = owner_stops_render.stop_resume("TASK_STATE_MISSING", task_id="001", project=self.root)
        self.assertEqual(shlex.split(resume)[shlex.split(resume).index("--project") + 1], str(self.root))

    def test_first_creation_head_timestamp_and_projection(self):
        result = self.cli("in_progress")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state, self.read())
        self.assertEqual(state["transitions"][0]["commit"], self.git("rev-parse", "HEAD"))
        self.assertTrue(state["transitions"][0]["at"].endswith("Z"))
        self.assertIn("Status: queued\n", self.record.read_text())
        self.assertEqual(len(state["transitions"]), 1)

    def test_governed_cli_requires_delivery_and_preserves_spike(self):
        write_project_config(self.root, "governed", validation=VALIDATION)
        freeze_record(self.root, "001", self.record)
        self.assertEqual(self.cli("in_progress").returncode, 0)
        before = self.path.read_bytes()
        refused = self.cli("in_review")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("BLOCKED WRONG_WORKTREE", refused.stderr)
        self.assertEqual(self.path.read_bytes(), before)
        self.write(self.state())
        self.record.write_text(contract_record(spike=True, extra="Review: NOT_REQUIRED\nStatus: queued\n"))
        freeze_record(self.root, "001", self.record)
        self.assertEqual(self.cli("in_progress").returncode, 0)
        self.git("switch", "-qc", "task-001")
        (self.root / "docs").mkdir()
        (self.root / "docs/result.md").write_text("Answer to the research question.\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "Deliver spike result")
        for outcome in ("ANSWERED", "INCONCLUSIVE"):
            state = owner_tasks_transitions.record_spike_outcome(self.root, "001", outcome)
            self.assertEqual(state["status"], "in_progress")
            self.assertEqual(state["outcome"], outcome)
            self.assertEqual(self.cli("done").returncode, 2)

    def test_review_not_required_goes_directly_to_accepted(self):
        write_project_config(self.root, "governed", validation=VALIDATION)
        self.record.write_text(self.record.read_text() + "Review: NOT_REQUIRED\n")
        freeze_record(self.root, "001", self.record)
        self.assertEqual(self.cli("in_progress").returncode, 0)
        before = self.path.read_bytes()
        for status in ("in_review", "done", "ACCEPTED"):
            self.assertEqual(self.cli(status).returncode, 2)
            self.assertEqual(self.path.read_bytes(), before)
        state = self.read("single")
        self.assertEqual(state["status"], "in_progress")
        self.assertEqual(state["contract"]["options"]["review"], "not_required")

    def test_no_projection_field_is_added(self):
        self.record.write_text(contract_record())
        original = self.record.read_bytes()
        self.assertEqual(self.cli("in_progress").returncode, 0)
        self.assertEqual(self.record.read_bytes(), original)

    def test_atomic_replace_and_write_failure_preserves_files(self):
        self.write(self.state())
        freeze_record(self.root, "001", self.record)
        before = self.path.read_bytes(), self.record.read_bytes()
        from cardine.lifecycle import receipts
        write = receipts._durable
        def fail_state(path, content):
            if path == self.path:
                raise OSError("replacement failed")
            return write(path, content)
        with mock.patch.object(receipts, "_durable", side_effect=fail_state):
            with self.assertRaises(OSError):
                owner_tasks_transitions.transition_task_state(self.root, "001", "in_progress")
        self.assertEqual((self.path.read_bytes(), self.record.read_bytes()), before)
        self.assertTrue(receipts.pending_operation(self.root, "001"))
        state = owner_tasks_transitions.transition_task_state(self.root, "001", "in_progress")
        receipts.verify_receipts(self.root, state)
        self.assertEqual(len(state["transitions"]), 1)
        self.assertFalse(receipts.pending_operation(self.root, "001"))
        self.assertEqual(list(self.path.parent.glob("*.stage")), [])

    def test_missing_stop(self):
        self.path.unlink()
        write_project_config(self.root, "lean", validation=VALIDATION)
        self.record.write_text(contract_record(extra="Status: queued\n"))
        (self.root / "tasks/QUEUE.md").write_text(
            "| ID | Status | Task file |\n|---|---|---|\n| 001 | queued | [001](001.md) |\n")
        with self.assertRaises(shared_errors.CardineStop) as caught:
            self.read()
        self.assertTrue(str(caught.exception).startswith("NEXT TASK_STATE_MISSING:"))
        self.assertIn("cardine task state import 001", str(caught.exception))
        self.assertFalse(self.path.exists())
        recovered = run_recovery(resume_from(str(caught.exception)), self.root)
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        with self.assertRaisesRegex(shared_errors.CardineStop, "missing completed operation receipt"):
            self.read()  # Legacy import is diagnostic, never operation authority.

    def test_invalid_stop(self):
        self.write(self.state())
        freeze_record(self.root, "001", self.record)
        before = self.path.read_bytes(), self.record.read_bytes()
        result = self.cli("UNKNOWN")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stderr.startswith("BLOCKED TASK_STATE_INVALID:"), result.stderr)
        self.assertIn("found 'UNKNOWN'", result.stderr)
        self.assertEqual((self.path.read_bytes(), self.record.read_bytes()), before)
        self.path.unlink()
        result = self.cli("in_progress")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TASK_STATE_MISSING", result.stderr)
        self.assertFalse(self.path.exists())

    def test_invalid_existing_schema_history_and_identity_write_nothing(self):
        good = self.state(steps=("in_progress", "done"))
        good["contract"] = self.read()["contract"]
        cases = []
        for field, value in (("version", True), ("task_id", "002"), ("workflow", "unknown"), ("status", "UNKNOWN"), ("extra", 1)):
            changed = copy.deepcopy(good)
            changed[field] = value
            cases.append(changed)
        for field, value in (("commit", "abc"), ("at", "2026-02-30T00:00:00Z"), ("at", "2026-10-11T12:00:00+01:00"), ("from", "done"), ("to", "queued")):
            changed = copy.deepcopy(good)
            changed["transitions"][0][field] = value
            cases.append(changed)
        changed = copy.deepcopy(good)
        changed["status"] = "queued"
        cases += [changed, {"version": 1}, [], None]
        for state in cases:
            with self.subTest(state=state):
                self.write(state)
                before = self.path.read_bytes(), self.record.read_bytes()
                result = self.cli("done")
                self.assertEqual(result.returncode, 2)
                self.assertIn("BLOCKED TASK_STATE_INVALID:", result.stderr)
                self.assertIn("allowed", result.stderr)
                self.assertIn("found", result.stderr)
                self.assertEqual((self.path.read_bytes(), self.record.read_bytes()), before)
        self.path.write_text("{")
        self.assertIn("BLOCKED TASK_STATE_INVALID:", self.cli("done").stderr)

    def test_optional_review_schema(self):
        state = self.state()
        state["review"] = {"required": True, "verdict": None, "attempt": 1,
                           "reviewed_commit": None, "approved_by": None}
        task_state.validate_task_state(state, "001", "single")
        state["review"].update(verdict="APPROVE", reviewed_commit=SHA, approved_by="owner")
        task_state.validate_task_state(state, "001", "single")
        state["review"]["attempt"] = 0
        with self.assertRaisesRegex(task_state.TaskStateInvalid, "review.attempt"):
            task_state.validate_task_state(state, "001", "single")

    def test_reader_never_enumerates_state_directory(self):
        from functools import wraps
        methods = {name: getattr(Path, name) for name in ("iterdir", "glob", "rglob")}
        def bounded(name):
            @wraps(methods[name])
            def call(path, *args, **kwargs):
                if path == self.path.parent:
                    raise AssertionError("state directory scan")
                return methods[name](path, *args, **kwargs)
            return call
        with mock.patch.object(Path, "iterdir", bounded("iterdir")), \
             mock.patch.object(Path, "glob", bounded("glob")), \
             mock.patch.object(Path, "rglob", bounded("rglob")):
            self.assertEqual(self.read()["status"], "queued")

    def test_cancellation_requires_authority_and_reason_from_each_open_state(self):
        for prefix in ((), ("in_progress",), ("in_progress", "in_review")):
            with self.subTest(prefix=prefix):
                state = self.state(steps=prefix)
                state["review"] = {"required": True, "verdict": None, "attempt": 1,
                                   "reviewed_commit": None, "approved_by": None}
                self.record.write_text(contract_record(extra="Review: REQUIRED\n"))
                self.write(state)
                freeze_record(self.root, "001", self.record)
                before = self.path.read_bytes()
                denied = self.cli("cancelled")
                self.assertEqual(denied.returncode, 2, denied.stderr)
                self.assertEqual(self.path.read_bytes(), before)
                cancelled = self.cli("cancelled", "--cancellation-authority", "Owner directive 054",
                                     "--reason", "Superseded by another task")
                self.assertEqual(cancelled.returncode, 2, cancelled.stderr)
                self.assertEqual(self.path.read_bytes(), before)
                from control_support import adapter
                owner_tasks_transitions.transition_task_state(self.root, '001', 'cancelled',
                    adapter=adapter(), cancellation_authority='Owner directive 054',
                    reason='Superseded by another task')
                result = self.read()
                self.assertEqual(result["status"], "cancelled")
                self.assertEqual(result["transitions"][-1]["authority"], "developer-channel")
                self.assertEqual(result["transitions"][-1]["reason"], "Superseded by another task")
                for target in task_state.STATUSES:
                    self.assertEqual(self.cli(target).returncode, 2)

    def test_dependencies_use_landed_results_for_both_presets(self):
        from cardine.tasks.preflight import check_dependencies
        from cardine.tasks.contract import resolve_task_contract
        contract = resolve_task_contract(self.root, "001")
        dependency_path = task_state.state_path(self.root, "002")
        dependency_path.parent.mkdir(parents=True, exist_ok=True)
        record = "## Dependencies\n- **Depends on**: 002\n- **Blocks**: 003\n"
        current = self.state()
        current["contract"] = copy.deepcopy(contract)
        current["contract"]["dependencies"] = ["002"]
        self.write(current)
        for preset in ("lean", "governed"):
            write_project_config(self.root, preset, validation=VALIDATION)
            seal_state(self.root, "001")
            for task_class, status, outcome, satisfied in (
                    ("standard", "queued", None, False),
                    ("standard", "in_progress", None, False),
                    ("standard", "in_review", None, False),
                    ("standard", "done", None, True),
                    ("standard", "cancelled", None, False),
                    ("spike", "done", "ANSWERED", True),
                    ("spike", "done", "INCONCLUSIVE", False),
                    ("spike", "in_progress", "ANSWERED", False)):
                steps = () if status == "queued" else ("in_progress",) if status == "in_progress" else ("in_progress", status)
                state = self.state(steps=steps)
                state["task_id"] = "002"
                state["contract"] = copy.deepcopy(contract)
                state["contract"]["class"] = task_class
                state["contract"]["options"]["review"] = "required" if status == "in_review" else "not_required"
                if outcome:
                    state["outcome"] = outcome
                if status == "cancelled":
                    state["transitions"][-1].update(authority="owner", reason="Cancelled")
                dependency_path.write_text(json.dumps(state))
                seal_state(self.root, "002")
                self.git("add", ".")
                self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "--allow-empty", "-qm", "Dependency result")
                with self.subTest(preset=preset, task_class=task_class, status=status, outcome=outcome):
                    if satisfied:
                        check_dependencies(self.root, "001", record)
                    else:
                        with self.assertRaises(shared_errors.CardineStop):
                            check_dependencies(self.root, "001", record)
            # A branch's done result must not unblock its dependent on main.
            self.git("switch", "-qc", "unlanded-" + preset)
            state = self.state(steps=("in_progress", "done"))
            state["task_id"] = "002"
            dependency_path.write_text(json.dumps(state))
            self.git("add", ".")
            self.git("-c", "user.name=Test", "-c", "user.email=test@example.test", "commit", "-qm", "Unlanded result")
            with self.assertRaises(shared_errors.CardineStop):
                check_dependencies(self.root, "001", record)
            self.git("switch", "main")

    def test_transition_timestamps_must_be_chronological(self):
        state = self.state(steps=("in_progress", "done"))
        state["transitions"][0]["at"] = "2026-10-12T12:00:00Z"
        with self.assertRaisesRegex(task_state.TaskStateInvalid, "chronological"):
            task_state.validate_task_state(state, "001", "single")

    def test_context_size_and_read_guard_sets_exclude_state_files(self):
        before = owner_shared_context.context_size_report(self.root, "implementation")
        self.write(self.state())
        self.record.write_text(self.record.read_text() + "\n## Authority\n\n- `.cardine/tasks/001.json`#State\n")
        freeze_record(self.root, "001", self.record)
        with mock.patch.object(owner_shared_authority, "extract_spec_heading", side_effect=AssertionError("state startup read")):
            report = owner_shared_context.context_size_report(self.root, "implementation", task_id="001")
        self.assertNotIn(".cardine/tasks/001.json", [item["path"] for item in report["files"]])
        for role in ("implementation", "review"):
            after = owner_shared_context.context_size_report(self.root, role)
            self.assertEqual(before["total"], after["total"])
            self.assertNotIn(".cardine/tasks/001.json", [item["path"] for item in after["files"]])
        # Even accidental routed Markdown citations into the state directory are excluded.
        fake = self.path.with_suffix(".md")
        fake.write_text("large state payload\n" * 1000)
        (self.root / "AGENTS.md").write_text("Read `.cardine/tasks/001.md`.\n")
        report = owner_shared_context.context_size_report(self.root, "implementation")
        self.assertNotIn(".cardine/tasks/001.md", [item["path"] for item in report["files"]])
        self.assertNotIn(Path(".cardine/tasks/001.md"), owner_shared_context.context_router_files(self.root))
        for unsafe in ("../001", "/001", "..", "bad id"):
            with self.assertRaises(task_state.TaskStateInvalid):
                task_state.state_path(self.root, unsafe)


if __name__ == "__main__":
    unittest.main()
