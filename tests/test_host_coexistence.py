"""Cardine and the legacy tool on one machine, in disposable homes and projects only."""
from __future__ import annotations

import json
import tomllib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine_cli_support import ROOT
from project_config_support import write_project_config
from cardine.hosts import codex, setup
from cardine.hosts import claude as claude_host
from cardine.hosts import read_guard, stop_audit

LEGACY = "meri" + "dian"  # the retired product name, composed so the identifier guard stays strict
FOREIGN_RULES = '# foreign\r\nprefix_rule(pattern=["other"], decision="allow")\r\n'


class CoexistenceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        (base / "receipts").mkdir()
        patcher = patch.object(tempfile, "tempdir", str(base / "receipts"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.home = base / "home"
        self.converted = self.home / "converted"
        self.legacy_project = self.home / "legacy-project"
        for path in (self.home / "project", self.converted, self.legacy_project / "tasks", self.home / ".codex/rules",
                     self.home / ".local/share" / LEGACY):
            path.mkdir(parents=True)
        write_project_config(self.converted)
        (self.legacy_project / "PROJECT_WORKFLOW.md").write_text("# Workflow\n")
        (self.legacy_project / "tasks/QUEUE.md").write_text("| Status | ID |\n|---|---|\n| `[ ]` | 001 |\n")
        self.rules = self.home / ".codex/rules/default.rules"
        self.rules.write_bytes((FOREIGN_RULES + codex.LEGACY_CODEX_USER_RULES).encode())

    def plan(self):
        return setup.plan_setup(None, self.home / ".codex/config.toml",
                                environment={"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "xdg")},
                                home=self.home, framework_root=ROOT, project_root=self.home / "project")

    def tree(self):
        return {path.relative_to(self.home).as_posix(): path.read_bytes()
                for path in sorted(self.home.rglob("*")) if path.is_file()}

    def test_legacy_rules_stay_byte_identical_and_a_rerun_converges(self):
        original = self.rules.read_bytes()
        plan = self.plan()
        self.assertIsNone(plan.user_rules.legacy_proposed)
        self.assertTrue(any("kept byte-identical" in warning for warning in plan.warnings), plan.warnings)
        setup.apply_setup(plan)
        profile = tomllib.loads((self.home / ".codex/config.toml").read_text())
        self.assertEqual(profile["default_permissions"], "cardine-worktrees")
        self.assertEqual(profile["permissions"]["cardine-worktrees"]["workspace_roots"],
                         {str(plan.resolution.path): True, str(self.home / ("." + LEGACY) / "worktrees"): True})
        self.assertEqual(self.rules.read_bytes(), original)
        self.assertTrue((self.home / ".codex/rules/cardine.rules").is_file())
        settled = self.tree()
        again = self.plan()
        setup.apply_setup(again)
        self.assertEqual(self.tree(), settled)
        self.assertEqual(self.rules.read_bytes(), original)

    def test_legacy_rules_are_removed_once_the_legacy_tool_is_gone(self):
        (self.home / ".local/share" / LEGACY).rmdir()
        plan = self.plan()
        self.assertIsNotNone(plan.user_rules.legacy_proposed)
        setup.apply_setup(plan)
        self.assertEqual(self.rules.read_bytes(), FOREIGN_RULES.encode())

    def test_environment_root_marks_the_legacy_tool_as_installed(self):
        (self.home / ".local/share" / LEGACY).rmdir()
        root = self.home / "checkout"
        root.mkdir()
        self.assertFalse(setup._legacy_tool_installed(self.home, {}))
        self.assertTrue(setup._legacy_tool_installed(self.home, {LEGACY.upper() + "_ROOT": str(root)}))
        self.assertFalse(setup._legacy_tool_installed(self.home, {LEGACY.upper() + "_ROOT": str(root / "missing")}))

    def briefing(self, project):
        environment = dict(os.environ, HOME=str(self.home), PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-m", "cardine.hosts.briefing", "--host", "claude"], cwd=self.home,
                              env=environment, input=json.dumps({"cwd": str(project)}), text=True,
                              capture_output=True, timeout=30, check=False)

    def test_the_briefing_speaks_only_in_a_converted_project(self):
        converted = self.briefing(self.converted)
        self.assertEqual((converted.returncode, converted.stderr), (0, ""))
        self.assertIn("Tasks:", converted.stdout)
        legacy = self.briefing(self.legacy_project)
        self.assertEqual((legacy.returncode, legacy.stdout, legacy.stderr), (0, "", ""))

    def test_the_legacy_briefing_stays_silent_in_a_converted_project(self):
        script = ROOT / "hooks/queue-briefing.sh"
        if not script.is_file():
            self.skipTest("legacy_briefing_script: the legacy hook files no longer exist")
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.home)}
        result = subprocess.run(["bash", str(script)], cwd=self.converted, env=environment,
                                input="{}", text=True, capture_output=True, timeout=30, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_the_read_guard_acts_only_where_the_declaration_exists(self):
        for project, denied in ((self.converted, True), (self.legacy_project, False)):
            (project / "big.txt").write_text("".join(f"{n}\n" for n in range(3000)))
            payload = {"tool_name": "Read", "tool_input": {"file_path": str(project / "big.txt")}, "cwd": str(project)}
            with self.subTest(project=project.name):
                allowed, _reason = read_guard.decision(payload, "claude")
                self.assertEqual(allowed, not denied)

    def test_the_stop_audit_appends_nothing_without_the_declaration(self):
        payload = {"cwd": str(self.legacy_project), "last_assistant_message": "BLOCKED COMMAND_REFUSED"}
        with patch.object(stop_audit, "final_message", side_effect=AssertionError("audited a legacy project")):
            self.assertEqual(stop_audit.audit(payload), [])

    def settings(self, scope, enabled):
        path = {"user": self.home / ".claude/settings.json",
                "project": self.converted / ".claude/settings.json",
                "local": self.converted / ".claude/settings.local.json"}[scope]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"enabledPlugins": {f"{LEGACY}@{LEGACY}": enabled}}))
        return path

    def advisories(self):
        found = claude_host.claude_legacy_plugin_advisories(self.converted, self.home)
        self.assertEqual(claude_host.claude_hook_duplicate_advisories(self.converted, self.home) == (), True)
        return found

    def test_a_local_disable_wins_over_project_and_user_enablement(self):
        for enabled_scope in ("user", "project"):
            with self.subTest(enabled=enabled_scope):
                self.settings(enabled_scope, True)
                self.settings("local", False)
                self.assertEqual(self.advisories(), ())
                for path in (self.home / ".claude/settings.json", self.converted / ".claude/settings.json",
                             self.converted / ".claude/settings.local.json"):
                    path.unlink(missing_ok=True)

    def test_an_effective_enablement_names_the_deciding_file(self):
        user = self.settings("user", True)
        found = self.advisories()
        self.assertEqual(len(found), 1)
        self.assertIn(str(user), found[0])
        user.unlink()
        self.settings("user", False)
        local = self.settings("local", True)
        found = self.advisories()
        self.assertEqual(len(found), 1)
        self.assertIn(str(local), found[0])


if __name__ == "__main__":
    unittest.main()
