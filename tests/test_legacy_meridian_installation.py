"""The explicit installation reader stays isolated and read-only."""

from __future__ import annotations

import ast
import builtins
from dataclasses import FrozenInstanceError
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from cardine.legacy import meridian_installation as installation
from cardine.console.snapshot import load_snapshot
from cardine.shared.constants import CAPABILITY_MARKER, MARKED_BLOCK
from cardine.shared.layout import ProjectNames, names, use
from cardine.tasks.state import read_task_state
from cardine.templates.catalog import load_capability_catalog
from cardine.templates.audit import profile_doctor
from console_support import LeanEffectiveStateFixture, MachineStateConsoleFixture, RepoCase


class InstallationTest(RepoCase):
    setup_project = LeanEffectiveStateFixture.setup_project
    queue = LeanEffectiveStateFixture.queue
    state = MachineStateConsoleFixture.state

    def setUp(self):
        super().setUp()
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.project)
        self.setup_project({"001": " ", "002": " "})
        self.write(self.project, "PROJECT_WORKFLOW.md", "LEAN_DELIVERY\n")
        self.write(self.project, ".meridian/manifest.json", json.dumps({"workflowMode": "lean-delivery"}))
        self.write(self.project, ".meridian/task-identity.json", '{"version": 1, "mode": "opaque"}')
        with use(installation.MERIDIAN_INSTALLATION_NAMES):
            self.state(self.project, "001", "DONE", workflow="lean-delivery")
        self.commit(self.project, "installation")
        self.worktree("task-002")
        self.write(self.project, ".git/meridian-worktrees/002.json", json.dumps({
            "task_id": "002", "branch": "task-002", "worktree": str(self.root / "wt-task-002"),
            "started_at": "2026-10-19T12:00:00Z",
        }))

    def test_snapshot_equals_current_builder_on_synthetic_installation(self):
        (self.project / ".cardine/project.json").unlink()
        expected = installation.load_meridian_snapshot(self.project)
        with use(installation.MERIDIAN_INSTALLATION_NAMES):
            from cardine.shared.errors import CardineStop
            from cardine.stops.render import stop_error
            with self.assertRaisesRegex(CardineStop, "TASK_STATE_INVALID"):
                read_task_state(self.project, "001", "lean-delivery", stop_factory=stop_error)
        self.assertEqual(installation.load_meridian_snapshot(self.project), expected)
        self.assertEqual(expected.done_count, 1)
        self.assertEqual(expected.tasks[0].task_id, "002")
        self.assertIsNotNone(expected.tasks[0].worktree)
        self.assertEqual(expected.tasks[0].started_at, "2026-10-19T12:00:00Z")
        with use(ProjectNames(project_directory=".other")):
            self.assertEqual(installation.load_meridian_snapshot(self.project), expected)
            self.assertEqual(names().project_directory, ".other")

    def test_all_meridian_statuses_map_only_in_the_read_only_adapter(self):
        from cardine.shared.errors import CardineStop
        from cardine.stops.render import stop_error
        path = self.project / ".meridian/tasks/001.json"
        for old, new in installation.MERIDIAN_STATUSES.items():
            value = {"version": 1, "task_id": "001", "workflow": "lean-delivery",
                     "status": old, "transitions": []}
            path.write_text(json.dumps(value))
            before = path.read_bytes()
            with self.subTest(old=old):
                mapped = installation.snapshot_task_state(value)
                self.assertEqual(mapped["status"], new)
                if old in ("ANSWERED", "INCONCLUSIVE"):
                    self.assertEqual(mapped["outcome"], old)
                snapshot = installation.load_meridian_snapshot(self.project)
                task = next((task for task in snapshot.tasks if task.task_id == "001"), None)
                if old == "DONE":
                    self.assertIsNone(task)
                else:
                    self.assertEqual(task.status, new)
                with use(installation.MERIDIAN_INSTALLATION_NAMES):
                    with self.assertRaisesRegex(CardineStop, "TASK_STATE_INVALID"):
                        read_task_state(self.project, "001", "lean-delivery", stop_factory=stop_error)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(value["status"], old)

    def test_snapshot_opens_only_declared_meridian_paths_and_never_writes(self):
        opened = []
        commands = []
        real_io_open, real_open = io.open, builtins.open
        import subprocess
        real_run = subprocess.run

        def observing_open(original):
            def observe(file, mode="r", *args, **kwargs):
                self.assertFalse(any(flag in mode for flag in "wax+"), (file, mode))
                if not isinstance(file, int):
                    opened.append(Path(file).resolve())
                return original(file, mode, *args, **kwargs)
            return observe

        def observing_run(command, *args, **kwargs):
            commands.append(command)
            return real_run(command, *args, **kwargs)

        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(io, "open", side_effect=observing_open(real_io_open)), \
             patch.object(builtins, "open", side_effect=observing_open(real_open)), \
             patch.object(subprocess, "run", side_effect=observing_run), \
             patch.object(Path, "mkdir", side_effect=AssertionError("reader created a directory")):
            installation.load_meridian_snapshot(self.project)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        layout = installation.MERIDIAN_INSTALLATION_NAMES
        declared = {
            layout.manifest_path, layout.task_identity_path, layout.project_declaration_path,
            layout.context_size_config_path, layout.candidate_validation_path,
            layout.execution_evidence_path, layout.flow_targets_path,
            Path(".git") / layout.integration_lease_name,
            Path(".git") / layout.integration_state_name,
            Path(".git") / layout.journal_name, Path(".git") / layout.journal_rotated_name,
        }
        directories = {layout.tasks_path, layout.baselines_path,
                       Path(layout.project_directory) / "probes",
                       Path(".git") / layout.worktree_state_directory}
        meridian_paths = []
        for path in opened:
            for root in (self.project, self.root / "wt-task-002"):
                if not path.is_relative_to(root):
                    continue
                relative = path.relative_to(root)
                if any("meridian" in part for part in relative.parts):
                    meridian_paths.append(relative)
                    self.assertTrue(relative in declared or relative.parent in directories, relative)
        self.assertIn(layout.tasks_path / "001.json", meridian_paths)
        self.assertIn(layout.task_identity_path, meridian_paths)
        self.assertIn(Path(".git") / layout.worktree_state_directory / "002.json", meridian_paths)
        self.assertTrue(commands)
        for command in commands:
            self.assertEqual(command[0], "git")
            self.assertTrue(any(word in command for word in (
                "worktree", "status", "rev-parse", "rev-list", "show", "diff", "check-ref-format", "log", "config")), command)
            if "config" in command:
                self.assertIn("--get", command)
                self.assertFalse(any(flag in command for flag in (
                    "--add", "--unset", "--unset-all", "--replace-all", "--edit")), command)
            if "worktree" in command:
                self.assertIn("list", command)

    # MERIDIAN-OLD-NAME-TEST
    def test_product_snapshot_never_opens_meridian_project_paths(self):
        opened = []
        real_io_open, real_open = io.open, builtins.open

        def observing_open(original):
            def observe(file, mode="r", *args, **kwargs):
                if not isinstance(file, int):
                    path = Path(file).resolve()
                    if path.is_relative_to(self.root):
                        relative = path.relative_to(self.root)
                        self.assertNotIn(".meridian", relative.parts, relative)
                        self.assertFalse(any(part.startswith("meridian-") for part in relative.parts), relative)
                        opened.append(relative)
                return original(file, mode, *args, **kwargs)
            return observe

        with patch.object(io, "open", side_effect=observing_open(real_io_open)), \
             patch.object(builtins, "open", side_effect=observing_open(real_open)):
            snapshot = load_snapshot(self.project)
        self.assertTrue(opened)
        self.assertEqual(snapshot.done_count, 0)
        self.assertEqual({task.task_id for task in snapshot.tasks}, {"001", "002"})

    # MERIDIAN-OLD-NAME-TEST
    def test_old_task_state_is_missing_to_product(self):
        self.assertTrue((self.project / ".meridian/tasks/001.json").is_file())

        class Stopped(Exception):
            pass

        def stop(code, detail, **kwargs):
            return Stopped(f"{code}: {detail}")

        with self.assertRaisesRegex(Stopped, "TASK_STATE_MISSING.*cardine/tasks/001.json"):
            read_task_state(self.project, "001", "lean-delivery", stop_factory=stop)

    # MERIDIAN-OLD-NAME-TEST
    def test_old_profile_id_is_not_a_product_alias(self):
        catalog = load_capability_catalog(ROOT)
        self.assertIsNone(catalog.profile("meridian-self-hosting"))
        self.assertIsNotNone(catalog.profile("cardine-self-hosting"))
        from installation_fixture import InstallationFixture
        InstallationFixture().installed_project(self.project)
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = profile_doctor(self.project, ROOT, "meridian-self-hosting")
        self.assertEqual(result, 2)
        self.assertIn("capability profile is not present in the catalog", output.getvalue())

    def test_explicit_reader_still_reads_checkout_installation(self):
        snapshot = installation.load_meridian_snapshot(ROOT)
        self.assertGreater(snapshot.done_count, 0)
        self.assertTrue(installation.is_meridian_installation(ROOT))
        self.assertEqual(installation.read_task_state_file(ROOT, "048")["status"], "DONE")

    def test_literal_names_and_json_readers_ignore_product_context(self):
        layout = installation.MERIDIAN_INSTALLATION_NAMES
        with self.assertRaises(FrozenInstanceError):
            layout.project_directory = ".changed"
        with use(ProjectNames(project_directory=".other")):
            self.assertTrue(installation.is_meridian_installation(self.project))
            self.assertEqual(installation.read_manifest(self.project), {"workflowMode": "lean-delivery"})
            self.assertEqual(installation.read_task_state_file(self.project, "001")["status"], "DONE")
        for task_id in ("../001", "/001", "a/b", "a\\b", "", "."):
            with self.subTest(task_id=task_id), self.assertRaises(ValueError):
                installation.read_task_state_file(self.project, task_id)
        with self.assertRaises(FileNotFoundError):
            installation.read_task_state_file(self.project, "999")
        self.assertFalse(installation.is_meridian_installation(self.root))

    def test_invalid_json_is_not_repaired_or_defaulted(self):
        path = self.project / installation.MERIDIAN_INSTALLATION_NAMES.manifest_path
        for text, error in (("{", json.JSONDecodeError), ("[]", ValueError)):
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(error):
                installation.read_manifest(self.project)
            self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_snapshot_restores_context_after_failure(self):
        selected = ProjectNames(project_directory=".other")
        with use(selected), patch.object(installation, "load_snapshot", side_effect=RuntimeError("test")):
            with self.assertRaisesRegex(RuntimeError, "test"):
                installation.load_meridian_snapshot(self.project)
            self.assertIs(names(), selected)


class MarkerAndIsolationTest(unittest.TestCase):
    def test_marker_blocks_return_names_versions_and_complete_text(self):
        block = "<!-- MERIDIAN:BEGIN capability=sample v12 -->\nbody\n<!-- MERIDIAN:END -->"
        other = "<!-- CARDINE:BEGIN capability=other v1 -->ignored<!-- CARDINE:END -->"
        self.assertEqual(installation.meridian_marker_blocks("prefix" + block + other), (("sample", 12, block),))
        self.assertEqual(installation.meridian_marker_blocks("<!-- MERIDIAN:BEGIN capability=sample v1 -->"), ())

    def test_marker_patterns_match_current_templates(self):
        count = 0
        for path in (ROOT / "templates").rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            expected = tuple((m.group(1), int(m.group(2)), m.group(0)) for m in MARKED_BLOCK.finditer(text))
            self.assertEqual(installation.meridian_marker_blocks(text), expected, str(path))
            self.assertEqual(installation._CAPABILITY_MARKER.findall(text), CAPABILITY_MARKER.findall(text))
            count += len(expected)
        self.assertGreater(count, 0)

    def test_import_graph_has_no_product_consumer_of_legacy(self):
        violations = []
        for directory in ("src/cardine", "scripts", "hooks"):
            for path in (ROOT / directory).rglob("*.py"):
                if path.is_relative_to(ROOT / "src/cardine/legacy"):
                    continue
                module = ".".join(path.relative_to(ROOT / "src").with_suffix("").parts) if directory == "src/cardine" else ""
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                    targets = []
                    if isinstance(node, ast.Import):
                        targets = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        base = node.module or ""
                        if node.level:
                            package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
                            base = ".".join(package[:len(package) - node.level + 1] + ([base] if base else []))
                        targets = [base] + [f"{base}.{alias.name}" for alias in node.names]
                    if any(target == "cardine.legacy" or target.startswith("cardine.legacy.") for target in targets):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
