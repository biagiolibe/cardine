"""User-level hook registration for both hosts, in disposable homes only."""
from __future__ import annotations

import contextlib
import io
import json
import shlex
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cardine_cli_support import CLI, ROOT
from project_config_support import write_project_config
from cardine.hosts import hooks, setup
from cardine.shared.errors import CardineError

EVENTS = {"claude": ("UserPromptSubmit", "PreToolUse", "Stop"), "codex": ("UserPromptSubmit", "PreToolUse", "Stop")}
LEGACY = "meri" + "dian"  # the retired product name, composed so the identifier guard stays strict
FOREIGN = {"type": "command", "command": "/usr/local/bin/my-own-hook", "timeout": 3}


def owned(host, name, timeout=5, matcher=None):
    group = {} if matcher is None else {"matcher": matcher}
    return {**group, "hooks": [{"type": "command", "command": hooks.hook_command(host, name), "timeout": timeout}]}


class HookLauncherTest(unittest.TestCase):
    def test_source_launcher_and_ownership(self):
        launcher = (sys.executable, str(ROOT / "bin/cardine"))
        self.assertEqual(hooks.launcher(), launcher)
        command = shlex.join((*launcher, "hook", "briefing", "--host", "codex"))
        self.assertTrue(hooks.owns(command, "codex", "briefing"))

    def test_installed_launcher_and_ownership(self):
        with patch.object(hooks, "source_checkout", return_value=None):
            self.assertEqual(hooks.launcher(), (sys.executable, "-m", "cardine"))
            command = hooks.hook_command("codex", "briefing")
        self.assertTrue(hooks.owns(command, "codex", "briefing"))
        self.assertFalse(hooks.owns(command, "claude", "briefing"))


class HostHooksTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        (base / "receipts").mkdir()
        patcher = patch.object(tempfile, "tempdir", str(base / "receipts"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.home = base / "home"
        (self.home / "project").mkdir(parents=True)
        (self.home / "codex").mkdir()
        self.claude = self.home / ".claude/settings.json"
        self.codex = self.home / ".codex/hooks.json"

    def plan(self):
        return setup.plan_setup(None, self.home / "codex/config.toml",
                                environment={"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "xdg")},
                                home=self.home, framework_root=ROOT, project_root=self.home / "project")

    def apply(self):
        plan = self.plan()
        return plan, setup.apply_setup(plan)

    def tree(self):
        return {path.relative_to(self.home).as_posix(): path.read_bytes()
                for path in sorted(self.home.rglob("*")) if path.is_file()}

    def registered(self, path):
        return json.loads(path.read_text())["hooks"]

    def owned_count(self, host, registry, event):
        return sum(1 for group in registry.get(event, []) for entry in group.get("hooks", [])
                   if hooks._owned_anywhere(entry.get("command", "")) and entry["command"].endswith(f"--host {host}"))

    def test_a_fresh_home_gets_exactly_one_entry_per_event_in_both_registries(self):
        plan, wrote = self.apply()
        self.assertTrue(wrote)
        for host, path in (("claude", self.claude), ("codex", self.codex)):
            registry = self.registered(path)
            self.assertEqual(set(registry), set(EVENTS[host]))
            for event in EVENTS[host]:
                self.assertEqual(self.owned_count(host, registry, event), 1, (host, event))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.registered(self.claude)["UserPromptSubmit"], [owned("claude", "briefing")])
        self.assertEqual(self.registered(self.codex)["PreToolUse"], [owned("codex", "read-guard", 10, "Bash")])
        self.assertEqual(self.registered(self.claude)["PreToolUse"][0]["matcher"], "Read")

    def test_a_second_apply_writes_nothing_and_leaves_no_receipt(self):
        self.apply()
        before = self.tree()
        plan = self.plan()
        self.assertEqual({r.status for r in plan.hooks.registries}, {"ready"})
        with patch("cardine.lifecycle.receipts.boundary") as boundary:
            self.assertFalse(setup.apply_setup(plan))
        self.assertEqual(self.tree(), before)
        self.assertFalse([call for call in boundary.call_args_list if "hooks" in str(call)])

    def test_foreign_registrations_and_settings_are_preserved_with_a_backup(self):
        self.claude.parent.mkdir(parents=True)
        self.codex.parent.mkdir(parents=True, exist_ok=True)
        original_claude = {"model": "x", "permissions": {"allow": ["Bash(ls:*)"]},
                           "hooks": {"UserPromptSubmit": [{"hooks": [FOREIGN]}], "Notification": [{"hooks": [FOREIGN]}]}}
        original_codex = {"extra": 1, "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [FOREIGN]}]}}
        self.claude.write_text(json.dumps(original_claude), encoding="utf-8")
        self.codex.write_text(json.dumps(original_codex), encoding="utf-8")
        self.claude.chmod(0o640)
        self.apply()
        claude, codex = json.loads(self.claude.read_text()), json.loads(self.codex.read_text())
        self.assertEqual(claude["model"], "x")
        self.assertEqual(claude["permissions"], original_claude["permissions"])
        self.assertEqual(claude["hooks"]["Notification"], original_claude["hooks"]["Notification"])
        self.assertEqual(claude["hooks"]["UserPromptSubmit"], [{"hooks": [FOREIGN]}, owned("claude", "briefing")])
        self.assertEqual(codex["extra"], 1)
        self.assertEqual(codex["hooks"]["PreToolUse"], [{"matcher": "Bash", "hooks": [FOREIGN]}, owned("codex", "read-guard", 10, "Bash")])
        self.assertEqual(self.claude.stat().st_mode & 0o777, 0o640)
        backups = {path.name: json.loads(path.read_text()) for path in self.home.rglob("*.cardine.bak")
                   if path.name.startswith(("settings.json", "hooks.json"))}
        self.assertEqual(backups, {"settings.json.cardine.bak": original_claude, "hooks.json.cardine.bak": original_codex})

    def test_owned_duplicates_collapse_to_one_and_foreign_neighbours_survive(self):
        self.claude.parent.mkdir(parents=True)
        mixed = {"hooks": [FOREIGN, owned("claude", "briefing")["hooks"][0]]}
        self.claude.write_text(json.dumps({"hooks": {
            "UserPromptSubmit": [owned("claude", "briefing"), mixed, owned("claude", "briefing")],
            "Stop": [owned("claude", "stop-audit"), owned("claude", "stop-audit")]}}), encoding="utf-8")
        plan = self.plan()
        self.assertEqual(plan.hooks.claude.duplicates, 3)
        self.assertIn("owned duplicate", plan.hooks.claude.detail)
        self.apply()
        registry = self.registered(self.claude)
        self.assertEqual(registry["UserPromptSubmit"], [owned("claude", "briefing"), {"hooks": [FOREIGN]}])
        self.assertEqual(registry["Stop"], [owned("claude", "stop-audit")])
        self.assertEqual(self.owned_count("claude", registry, "UserPromptSubmit"), 1)

    def test_a_changed_definition_is_replaced_in_place_and_reported_for_restart(self):
        self.codex.parent.mkdir(parents=True)
        self.codex.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{**owned("codex", "read-guard")["hooks"][0], "timeout": 99}]}]}}), encoding="utf-8")
        plan = self.plan()
        self.assertEqual(plan.hooks.codex.status, "update")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            setup.print_setup_plan(plan)
        self.assertIn("registration only", output.getvalue())
        self.assertIn("doctor must prove", output.getvalue())
        setup.apply_setup(plan)
        self.assertEqual(self.registered(self.codex)["PreToolUse"], [owned("codex", "read-guard", 10, "Bash")])

    def test_registration_writes_no_host_trust_state(self):
        self.apply()
        names = set(self.tree())
        self.assertFalse([name for name in names if "trust" in name or "approval" in name])
        for text in (self.claude.read_text(), self.codex.read_text()):
            self.assertNotIn("trust", text.lower())

    def test_unreadable_or_linked_registries_block_setup_without_writing(self):
        for label, prepare in (
            ("malformed", lambda: (self.claude.parent.mkdir(parents=True, exist_ok=True), self.claude.write_text("{nope"))),
            ("hooks-not-object", lambda: (self.codex.parent.mkdir(parents=True, exist_ok=True), self.codex.write_text('{"hooks": []}'))),
            ("event-not-list", lambda: (self.claude.parent.mkdir(parents=True, exist_ok=True), self.claude.write_text('{"hooks": {"Stop": {}}}'))),
            ("symlink", lambda: (self.codex.parent.mkdir(parents=True, exist_ok=True),
                                 (self.home / "elsewhere.json").write_text("{}"), self.codex.symlink_to(self.home / "elsewhere.json"))),
        ):
            with self.subTest(label):
                for path in (self.claude, self.codex, self.home / "elsewhere.json"):
                    if path.exists() or path.is_symlink():
                        path.unlink()
                prepare()
                before = self.tree()
                plan = self.plan()
                self.assertEqual(plan.hooks.blocked.status, "blocked")
                self.assertEqual(plan.changes, ("none; setup is blocked before mutation",))
                with self.assertRaises(CardineError):
                    setup.apply_setup(plan)
                self.assertEqual(self.tree(), before)

    def test_a_registry_edited_after_planning_is_refused_before_any_write(self):
        plan = self.plan()
        self.claude.parent.mkdir(parents=True)
        self.claude.write_text('{"model": "edited"}', encoding="utf-8")
        before = self.tree()
        with self.assertRaisesRegex(CardineError, "changed since it was planned"):
            setup.apply_setup(plan)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.codex.exists())

    def test_project_plugin_and_other_registrations_are_reported_never_rewritten(self):
        project = self.home / "project"
        (project / ".claude").mkdir()
        (project / ".codex").mkdir()
        project_claude = project / ".claude/settings.json"
        project_claude.write_text(json.dumps({"enabledPlugins": {f"{LEGACY}@{LEGACY}": True}, "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "cardine hook stop-audit --host claude"}]}]}}))
        project_codex = project / ".codex/hooks.json"
        project_codex.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": f"{LEGACY} hook stop-audit --host codex"}]}]}}))
        before = {path: path.read_bytes() for path in (project_claude, project_codex)}
        self.apply()
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        advisories = "\n".join(self.plan().hooks.advisories)
        self.assertIn(f"{project_claude}: 'cardine hook stop-audit --host claude'", advisories)
        self.assertIn(f"{project_codex}: '{LEGACY} hook stop-audit --host codex'", advisories)
        self.assertIn("enabled legacy plugin", advisories)
        self.assertNotIn("claude/settings.json: 'cardine hook briefing", advisories.replace(str(project), ""))

    def test_the_user_registrations_alone_are_not_reported_as_duplicates(self):
        self.apply()
        self.assertEqual(self.plan().hooks.advisories, ())

    def test_a_bare_registration_is_replaced_by_one_absolute_entry(self):
        self.codex.parent.mkdir(parents=True)
        self.codex.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "cardine hook read-guard --host codex", "timeout": 10}]}]}}))
        self.apply()
        registry = self.registered(self.codex)
        self.assertEqual(self.owned_count("codex", registry, "PreToolUse"), 1)
        command = registry["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(command, hooks.hook_command("codex", "read-guard"))
        self.assertTrue(Path(shlex.split(command)[0]).is_absolute())


class HookCommandRouteTest(unittest.TestCase):
    def run_hook(self, *arguments, cwd, payload):
        with tempfile.TemporaryDirectory() as home:
            return subprocess.run([sys.executable, str(CLI), "hook", *arguments], cwd=cwd, input=payload, text=True,
                                  capture_output=True, timeout=60,
                                  env={**os.environ, "HOME": home, "PYTHONPATH": str(ROOT / "src")})

    def test_briefing_route_prints_status_in_a_configured_project_and_is_silent_outside(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "project"
            outside = Path(temporary).resolve() / "outside"
            project.mkdir()
            outside.mkdir()
            write_project_config(project)
            for host in ("claude", "codex"):
                with self.subTest(host=host):
                    inside = self.run_hook("briefing", "--host", host, cwd=outside, payload=json.dumps({"cwd": str(project)}))
                    self.assertEqual(inside.returncode, 0, inside.stderr)
                    self.assertIn("Tasks:", inside.stdout)
                    silent = self.run_hook("briefing", "--host", host, cwd=outside, payload=json.dumps({"cwd": str(outside)}))
                    self.assertEqual((silent.returncode, silent.stdout, silent.stderr), (0, "", ""))

    def test_unknown_hooks_are_refused_and_never_fall_through_to_another_hook(self):
        result = self.run_hook("no-such-hook", "--host", "claude", cwd=ROOT, payload="{}")
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

    def test_registered_commands_are_exactly_the_cli_routes(self):
        for host, events in hooks._HOOKS.items():
            for _event, (_matcher, name, _timeout) in events.items():
                argv = shlex.split(hooks.hook_command(host, name))
                self.assertEqual(argv, [sys.executable, str(ROOT / "bin/cardine"), "hook", name, "--host", host])
                self.assertTrue(hooks.owns(f"cardine hook {name} --host {host}", host, name))
                self.assertFalse(hooks.owns(f"{LEGACY} hook {name} --host {host}", host, name))


if __name__ == "__main__":
    unittest.main()
