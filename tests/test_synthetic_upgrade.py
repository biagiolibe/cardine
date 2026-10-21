"""Upgrade behavior independent of the framework's release history."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cardine_cli_support import CLI
from synthetic_upgrade_support import SyntheticFramework


class SyntheticMigrationUpgradeTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.project = root / "project"
        self.project.mkdir()
        files = ("PROJECT_WORKFLOW.md", "AGENTS.md", "CLAUDE.md", "LANGUAGE_POLICY.md",
                 "tasks/TASK_BLUEPRINT.md", "docs/CONTEXT_READING_POLICY.md",
                 "docs/EXECUTION_EVIDENCE_PROFILE.md", ".codex/rules/meridian.rules",
                 ".codex/hooks.json")
        self.fixture = SyntheticFramework(root / "framework", "2.0.0", templates={
            path: "# Synthetic policy\n" for path in files
        })

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "--framework-root", str(self.fixture.root),
             *arguments, "--project", str(self.project)],
            text=True, capture_output=True, check=False,
        )

    def lock(self) -> None:
        shutil.copytree(self.fixture.root / "templates/single", self.project,
                        dirs_exist_ok=True)
        result = self.run_cli("lock", "--mode", "single")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def tree(self) -> dict[str, bytes]:
        return {path.relative_to(self.project).as_posix(): path.read_bytes()
                for path in self.project.rglob("*") if path.is_file()}

    def test_empty_chain_upgrade_is_current_and_changes_nothing(self) -> None:
        self.lock()
        before = self.tree()
        for action in ("--check", "--apply"):
            with self.subTest(action=action):
                result = self.run_cli("upgrade", action)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Cardine 2.0.0 -> 2.0.0", result.stdout)
                self.assertIn("Framework: 2.0.0 -> 2.0.0", result.stdout)
                self.assertNotIn("MIGRATION", result.stdout)
                self.assertNotIn("CONFLICT", result.stdout)
                self.assertEqual(self.tree(), before)

    def test_insertion_supersession_and_retirement_keep_consumer_text(self) -> None:
        paths = ("PROJECT_WORKFLOW.md",)
        self.fixture.migration("001-synthetic-rule", "2.1.0", capability="rule", version=1,
                               operation="insert", content="Original rule.", paths=paths, mode="single")
        self.fixture.migration("002-synthetic-old", "2.2.0", capability="old-rule", version=1,
                               operation="insert", content="Retire this rule.", paths=paths, mode="single")
        self.lock()
        local = self.project / paths[0]
        local.write_text(local.read_text() + "\n## Consumer notes\n\nKeep this text.\n")
        self.fixture.migration("003-synthetic-new", "2.3.0", capability="new-rule", version=1,
                               operation="insert", content="New rule.", paths=paths, mode="single")
        self.fixture.migration("004-synthetic-supersede", "2.4.0", capability="rule", version=2,
                               operation="supersede", content="Updated rule.", paths=paths, mode="single")
        self.fixture.migration("005-synthetic-retire", "2.5.0", capability="old-rule", version=1,
                               operation="retire", paths=paths, mode="single")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("005-synthetic-retire", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        text = local.read_text()
        self.assertIn("capability=rule v2", text)
        self.assertIn("New rule.", text)
        self.assertNotIn("capability=rule v1", text)
        self.assertNotIn("capability=old-rule", text)
        self.assertIn("## Consumer notes\n\nKeep this text.\n", text)
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text())
        self.assertEqual(manifest["workflowBaselineVersion"], "2.5.0")
        self.assertEqual(manifest["appliedMigrations"], [
            "001-synthetic-rule", "002-synthetic-old", "003-synthetic-new",
            "004-synthetic-supersede", "005-synthetic-retire",
        ])
