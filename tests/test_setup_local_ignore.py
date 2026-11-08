"""Setup keeps the Claude settings file it writes out of Git, through the repository's own exclude."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cardine_cli_support  # noqa: F401  (puts src/ on sys.path)
from cardine.hosts import setup as owner_hosts_setup


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                               "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}).stdout


class SetupLocalIgnoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.project = base / "project"
        self.project.mkdir()
        git(self.project, "init", "-q", "-b", "main")
        self.environment = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "xdg")}
        # Git reads the user's global excludes from HOME; a developer's own rule must not hide the case.
        patch = mock.patch.dict(os.environ, {**self.environment, "GIT_CONFIG_GLOBAL": "/dev/null"})
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def plan(self):
        return owner_hosts_setup.plan_setup(
            None, self.home / "codex/config.toml", environment=self.environment, home=self.home,
            project_root=self.project)

    def status(self) -> str:
        return git(self.project, "status", "--porcelain", "--untracked-files=all")

    def test_apply_excludes_the_settings_file_once_and_check_writes_nothing(self) -> None:
        exclude = self.project / ".git/info/exclude"
        before = exclude.read_text(encoding="utf-8")
        plan = self.plan()
        self.assertEqual(exclude.read_text(encoding="utf-8"), before)
        self.assertIn(f"exclude .claude/settings.local.json from Git in {exclude}", plan.changes)
        self.assertTrue(owner_hosts_setup.apply_setup(plan))
        self.assertTrue((self.project / ".claude/settings.local.json").is_file())
        self.assertNotIn(".claude", self.status())
        self.assertEqual(exclude.read_text(encoding="utf-8"), before + "/.claude/settings.local.json\n")
        again = self.plan()
        self.assertIsNone(again.local_ignore.proposed_text)
        self.assertNotIn(f"exclude .claude/settings.local.json from Git in {exclude}", again.changes)
        owner_hosts_setup.apply_setup(again)
        self.assertEqual(exclude.read_text(encoding="utf-8").count("settings.local.json"), 1)

    def test_an_existing_ignore_rule_or_a_tracked_file_is_left_alone(self) -> None:
        (self.project / ".gitignore").write_text(".claude/settings.local.json\n", encoding="utf-8")
        self.assertIsNone(self.plan().local_ignore.proposed_text)
        (self.project / ".gitignore").unlink()
        (self.project / ".claude").mkdir()
        (self.project / ".claude/settings.local.json").write_text("{}\n", encoding="utf-8")
        git(self.project, "add", ".claude/settings.local.json")
        self.assertIsNone(self.plan().local_ignore)

    def test_a_changed_exclude_file_refuses_the_apply(self) -> None:
        plan = self.plan()
        with (self.project / ".git/info/exclude").open("a", encoding="utf-8") as handle:
            handle.write("build/\n")
        with self.assertRaises(Exception):
            owner_hosts_setup.apply_setup(plan)
        self.assertFalse((self.project / ".claude/settings.local.json").exists())


if __name__ == "__main__":
    unittest.main()
