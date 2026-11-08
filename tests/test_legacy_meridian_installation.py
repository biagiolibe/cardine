"""The explicit installation reader stays isolated and read-only."""

from __future__ import annotations

import ast
import builtins
import re
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
from cardine.shared.snapshot_adapters import execution_assets_adapter
from cardine.legacy.meridian_locations import resolve_meridian_locations as resolve_project_locations
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

    def test_standalone_identity_requires_explicit_installation_context(self):
        from cardine.tasks.identity import read_task_identity_policy
        self.write(self.project, ".meridian/task-identity.json", '{"version": 1, "mode": "milestone"}')
        self.assertEqual(read_task_identity_policy(self.project).mode, "opaque")
        with use(installation.MERIDIAN_INSTALLATION_NAMES):
            self.assertTrue(names().legacy_identity_policy)
            self.assertEqual(read_task_identity_policy(self.project).mode, "milestone")
        self.assertFalse(names().legacy_identity_policy)
        self.assertEqual(read_task_identity_policy(self.project).mode, "opaque")




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
        # The product reads validated task state only: queue prose enumerates nothing.
        self.assertEqual(snapshot.done_count, 0)
        self.assertEqual(snapshot.tasks, ())

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

    def test_execution_assets_are_read_only_through_the_injected_reader(self):
        self.write(self.project, "PROJECT_WORKFLOW.md", (
            "LEAN_DELIVERY\n\n<!-- MERIDIAN:BEGIN capability=execution-assets v5 -->\n## Execution assets\n"
            "<!-- MERIDIAN:END -->\nThe queue is `docs/TASK_QUEUE.md`.\n\n## Roles\n"
        ))
        self.assertEqual(resolve_project_locations(self.project).queue, Path("tasks/QUEUE.md"))
        token = execution_assets_adapter.set(installation.read_meridian_execution_assets)
        try:
            self.assertEqual(resolve_project_locations(self.project).queue, Path("docs/TASK_QUEUE.md"))
        finally:
            execution_assets_adapter.reset(token)
        self.assertEqual(resolve_project_locations(self.project).queue, Path("tasks/QUEUE.md"))





class MarkerAndIsolationTest(unittest.TestCase):
    def test_marker_blocks_return_names_versions_and_complete_text(self):
        block = "<!-- MERIDIAN:BEGIN capability=sample v12 -->\nbody\n<!-- MERIDIAN:END -->"
        other = "<!-- CARDINE:BEGIN capability=other v1 -->ignored<!-- CARDINE:END -->"
        self.assertEqual(installation.meridian_marker_blocks("prefix" + block + other), (("sample", 12, block),))
        self.assertEqual(installation.meridian_marker_blocks("<!-- MERIDIAN:BEGIN capability=sample v1 -->"), ())

    def test_marker_patterns_read_the_meridian_rendering_of_current_templates(self):
        begin = re.compile(r"<!-- MERIDIAN:BEGIN capability=([a-z0-9-]+) v(\d+) -->\n?.*?<!-- MERIDIAN:END -->", re.DOTALL)
        count = 0
        for path in (ROOT / "templates").rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").replace("CARDINE:", "MERIDIAN:")
            expected = tuple((m.group(1), int(m.group(2)), m.group(0)) for m in begin.finditer(text))
            self.assertEqual(installation.meridian_marker_blocks(text), expected, str(path))
            self.assertEqual(
                installation._CAPABILITY_MARKER.findall(text),
                [(m.group(1), m.group(2)) for m in begin.finditer(text)],
            )
            self.assertEqual(CAPABILITY_MARKER.findall(text), [], str(path))
            self.assertEqual(MARKED_BLOCK.findall(text), [], str(path))
            count += len(expected)
        self.assertGreater(count, 0)

    @staticmethod
    def legacy_import_violations(root):
        """Return `path:line` of every product import of `cardine.legacy` outside the allowed packages."""
        violations = []
        for directory in ("src/cardine", "scripts", "hooks"):
            for path in (root / directory).rglob("*.py"):
                if path.is_relative_to(root / "src/cardine/legacy") or path.is_relative_to(root / "src/cardine/adopt"):
                    continue
                module = ".".join(path.relative_to(root / "src").with_suffix("").parts) if directory == "src/cardine" else ""
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
                        violations.append(str(path.relative_to(root)) + f":{node.lineno}")
        return violations

    def test_import_graph_limits_legacy_consumers_to_adopt(self):
        self.assertTrue((ROOT / "src/cardine/adopt/__init__.py").is_file())
        self.assertEqual(self.legacy_import_violations(ROOT), [])

    def test_import_graph_rejects_other_product_module_importing_legacy(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text in {
                "src/cardine/legacy/reader.py": "VALUE = 1\n",
                "src/cardine/adopt/convert.py": "from cardine.legacy import reader\n",
                "src/cardine/tasks/ok.py": "import cardine.shared\n",
                "src/cardine/tasks/bad_absolute.py": "from cardine.legacy.reader import VALUE\n",
                "src/cardine/tasks/bad_relative.py": "from ..legacy import reader\n",
                "scripts/bad_script.py": "import cardine.legacy.reader\n",
            }.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            self.assertEqual(
                sorted(self.legacy_import_violations(root)),
                ["scripts/bad_script.py:1", "src/cardine/tasks/bad_absolute.py:1", "src/cardine/tasks/bad_relative.py:1"],
            )


if __name__ == "__main__":
    unittest.main()
