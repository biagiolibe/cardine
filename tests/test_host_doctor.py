"""Unified doctor: host-evaluated decisions, live disposable hook invocation, read-only probes."""

from __future__ import annotations

from cardine_cli_support import CLI, ROOT
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cardine.hosts import claude as owner_hosts_claude
from cardine.hosts import codex as owner_hosts_codex
from cardine.hosts import hooks as owner_hosts_hooks
from cardine.hosts import setup as owner_hosts_setup


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {str(path.relative_to(root)): (path.read_bytes() if path.is_file() else None) for path in sorted(root.rglob("*"))}


class HostDoctorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.project = self.root / "project"
        self.bin = self.root / "bin"
        for path in (self.home, self.project, self.bin):
            path.mkdir()
        self.config = self.home / ".codex/config.toml"
        self.worktrees = self.root / "worktrees"
        self.worktrees.mkdir()
        shim = self.bin / "cardine"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{CLI}" "$@"\n', encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
        patcher = mock.patch.dict(os.environ, {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def register(self, host: str, *, names: tuple[str, ...] = ("read-guard",)) -> Path:
        path = owner_hosts_hooks.registry_path(self.home, host)
        path.parent.mkdir(parents=True, exist_ok=True)
        groups = [{"hooks": [{"type": "command", "command": owner_hosts_hooks.hook_command(host, name)}]} for name in names]
        path.write_text(json.dumps({"hooks": {"PreToolUse": groups}}), encoding="utf-8")
        return path

    def test_live_invocation_observes_the_hook_deny_a_sentinel_on_both_hosts(self) -> None:
        for host in ("claude", "codex"):
            self.register(host)
            with self.subTest(host=host):
                self.assertEqual(owner_hosts_setup.probe_hook_invocation(host, self.home), "ready")

    def test_missing_registration_and_missing_command_are_never_ready(self) -> None:
        self.assertEqual(owner_hosts_setup.probe_hook_invocation("claude", self.home), "missing")
        self.register("claude")
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertTrue(owner_hosts_setup.probe_hook_invocation("claude", self.home).startswith("unverified"))

    def test_a_hook_that_does_not_deny_is_not_effective(self) -> None:
        self.register("codex")
        (self.bin / "cardine").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.assertTrue(owner_hosts_setup.probe_hook_invocation("codex", self.home).startswith("unverified"))

    def test_registration_text_alone_never_proves_the_hook_runs(self) -> None:
        self.register("claude")
        with mock.patch.object(owner_hosts_setup.subprocess, "run", side_effect=subprocess.TimeoutExpired("cardine", 1)):
            self.assertEqual(
                owner_hosts_setup.probe_hook_invocation("claude", self.home), "unverified: probe interrupted"
            )

    def test_an_interrupted_probe_leaves_no_fixture_and_no_success(self) -> None:
        self.register("claude")
        scratch = self.root / "scratch"
        scratch.mkdir()
        with mock.patch.object(tempfile, "tempdir", str(scratch)), mock.patch.object(
            owner_hosts_setup.subprocess, "run", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                owner_hosts_setup.probe_hook_invocation("claude", self.home)
        self.assertEqual(list(scratch.iterdir()), [])

    def test_claude_never_reports_enforcement_from_settings_text(self) -> None:
        plan = owner_hosts_claude.plan_claude_project_allowlist(self.project)
        self.assertTrue(owner_hosts_claude.apply_claude_project_allowlist(plan))
        report = owner_hosts_setup.host_doctor("claude", self.project, self.config, self.worktrees, home=self.home)
        self.assertEqual(report["claude-project-allowlist"], "installed")
        self.assertEqual(report["claude-command-policy"], "unverified")

    def test_doctor_probes_repeat_without_any_write(self) -> None:
        self.register("claude")
        self.register("codex")
        for host in ("claude", "codex"):
            before = snapshot(self.root)
            first = owner_hosts_setup.host_doctor(host, self.project, self.config, self.worktrees, home=self.home)
            second = owner_hosts_setup.host_doctor(host, self.project, self.config, self.worktrees, home=self.home)
            with self.subTest(host=host):
                self.assertEqual(first, second)
                self.assertEqual(snapshot(self.root), before)

    def test_adopter_test_commands_are_neither_allowed_nor_probed(self) -> None:
        for text in (*owner_hosts_claude.CLAUDE_PROJECT_ALLOWLIST, owner_hosts_codex.CODEX_USER_RULES):
            for fragment in ("scripts/", "unittest", "run_tests", "pytest"):
                self.assertNotIn(fragment, text)
        probed = [" ".join(command) for _key, group in owner_hosts_setup.CODEX_CLOSURE_POLICY_PROBES for command, _ in group]
        self.assertFalse([item for item in probed if "scripts/" in item or "unittest" in item])
        report = owner_hosts_setup.host_doctor("codex", self.project, self.config, self.worktrees, home=self.home)
        self.assertNotIn("validation-command-policy", report)

    @unittest.skipUnless(shutil.which("codex"), "codex is not on PATH; cannot evaluate execpolicy decisions")
    def test_host_evaluates_the_installed_user_policy_and_adopter_tests_are_undecided(self) -> None:
        rules = self.home / ".codex/rules/cardine.rules"
        rules.parent.mkdir(parents=True)
        rules.write_text(owner_hosts_codex.CODEX_USER_RULES, encoding="utf-8")

        def decision(*command: str) -> str | None:
            checked = subprocess.run(
                owner_hosts_setup._execpolicy_argv(shutil.which("codex"), (rules,), command),
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            return json.loads(checked.stdout).get("decision")

        self.assertEqual(decision("cardine", "worktree", "prepare", "TASK-1"), "allow")
        self.assertEqual(decision("git", "push", "--force", "origin", "main"), "forbidden")
        self.assertIsNone(decision("python3", "scripts/check_repository.py"))
        self.assertIsNone(decision("python3", "scripts/run_tests.py", "--parallel"))

    @unittest.skipUnless(shutil.which("codex"), "codex is not on PATH; cannot evaluate execpolicy decisions")
    def test_codex_doctor_evaluates_the_combined_installed_policy(self) -> None:
        rules = self.home / ".codex/rules/cardine.rules"
        rules.parent.mkdir(parents=True)
        rules.write_text(owner_hosts_codex.CODEX_USER_RULES, encoding="utf-8")
        self.config.write_text(f'[projects."{self.project}"]\ntrust_level = "trusted"\n', encoding="utf-8")
        report = owner_hosts_setup.host_doctor("codex", self.project, self.config, self.worktrees, home=self.home)
        self.assertEqual(report["command-policy"], "ready")
        self.assertEqual(report["lifecycle-command-policy"], "ready")
        self.assertEqual(report["user-command-policy"], "ready")
        self.assertEqual(report["archive-rename-policy"], "gap: git mv")  # no project layer: reported, not assumed

    def test_removed_codex_commands_fail_with_the_migration_and_no_alias(self) -> None:
        for removed, replacement in (("configure", "cardine setup"), ("doctor", "cardine doctor")):
            checked = subprocess.run(
                [sys.executable, str(CLI), "codex", removed, "--check", "--home", str(self.home)],
                text=True, capture_output=True, check=False,
            )
            with self.subTest(command=removed):
                self.assertEqual(checked.returncode, 2)
                self.assertIn("was removed", checked.stderr)
                self.assertIn(replacement, checked.stderr)
                self.assertIn("`cardine setup` and `cardine doctor`", checked.stderr)
        self.assertEqual(snapshot(self.home), {})

    def test_unified_doctor_command_runs_against_a_disposable_home(self) -> None:
        self.register("claude")
        before = snapshot(self.root)
        done = subprocess.run(
            [sys.executable, str(CLI), "doctor", "--host", "claude", "--project", str(self.project),
             "--home", str(self.home), "--config", str(self.config), "--worktree-root", str(self.worktrees)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("claude-command-policy: unverified", done.stdout)
        self.assertIn("hook-invocation: ready", done.stdout)
        self.assertEqual(snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
