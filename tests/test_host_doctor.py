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
from cardine.hosts import permissions
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
        # All doctor calls resolve a disposable host; no test invokes the real Codex.
        host = self.bin / 'codex'
        host.write_text("#!/usr/bin/env python3\nimport json, sys\n"
                        "if sys.argv[1] != 'execpolicy': sys.exit(1)\n"
                        "command = sys.argv[sys.argv.index('--') + 1:]\n"
                        "decision = ('forbidden' if command[:2] == ['git', 'push'] and '--force' in command "
                        "else 'allow' if command[:2] == ['cardine', 'worktree'] else None)\n"
                        "print(json.dumps({'decision': decision}))\n", encoding='utf-8')
        host.chmod(0o755)

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
        # A bare command resolves only through the developer's shell PATH; a host started
        # from a desktop app does not have it, so the probe does not use it either.
        path = owner_hosts_hooks.registry_path(self.home, "claude")
        path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": "cardine hook read-guard --host claude"}]}]}}), encoding="utf-8")
        self.assertTrue(shutil.which("cardine"))
        self.assertEqual(owner_hosts_setup.probe_hook_invocation("claude", self.home),
                         "unverified: the registered hook command does not resolve outside an interactive shell; "
                         "rerun setup")

    def test_a_hook_that_does_not_deny_is_not_effective(self) -> None:
        path = self.register("codex")
        path.write_text(json.dumps({"hooks": {"PreToolUse": [{"hooks": [
            {"type": "command", "command": f"{self.bin / 'cardine'} hook read-guard --host codex"}]}]}}), encoding="utf-8")
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

    def test_claude_doctor_compares_the_plugin_with_the_cli(self) -> None:
        def report() -> str:
            return owner_hosts_setup.host_doctor(
                "claude", self.project, self.config, self.worktrees, home=self.home, framework_root=ROOT
            )["claude-plugin"]

        self.assertEqual(report(), "absent")
        registry = self.home / ".claude/plugins/installed_plugins.json"
        registry.parent.mkdir(parents=True)
        for version, expected in (((ROOT / "VERSION").read_text().strip(), "match"), ("0.0.1", "mismatch: plugin 0.0.1")):
            registry.write_text(json.dumps({"version": 2, "plugins": {"cardine@cardine": [
                {"scope": "user", "version": version}]}}), encoding="utf-8")
            self.assertTrue(report().startswith(expected))

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

    # -- runtime role proofs (D3) -------------------------------------------------

    def policy(self, host: str, role: str) -> permissions.RolePolicy:
        common = self.project / ".git"
        if host == "claude":
            return owner_hosts_claude.claude_role_policy(role, self.project, self.project, common)
        return owner_hosts_codex.codex_role_policy(role, self.project, self.worktrees, self.project, common)

    @staticmethod
    def host_table(policy: permissions.RolePolicy, flip: str | None = None, hide: str | None = None):
        """A fake host that reports the expected decision for every probe, optionally wrong or unobservable."""
        table = {}
        for name, (tool, tool_input, expected) in permissions.probe_matrix(policy.role, policy.host).items():
            table[(tool, json.dumps(tool_input, sort_keys=True))] = (
                None if name == hide else ("allow" if expected == "deny" else "deny") if name == flip else expected)
        return lambda tool, tool_input: table[(tool, json.dumps(tool_input, sort_keys=True))]

    def test_a_complete_host_proof_enforces_each_role_on_both_hosts(self) -> None:
        for host in ("claude", "codex"):
            for role in permissions.ROLES:
                policy = self.policy(host, role)
                result = owner_hosts_setup.prove_role_policy(policy, self.host_table(policy))
                with self.subTest(host=host, role=role):
                    self.assertEqual(result.state, "ready")
                    self.assertTrue(permissions.proof_enforces(policy, result.proof))

    def test_one_wrong_decision_never_enforces_a_denial_or_a_false_deny_control(self) -> None:
        for host in ("claude", "codex"):
            for role in permissions.ROLES:
                policy = self.policy(host, role)
                for name, (_tool, _input, expected) in permissions.probe_matrix(role, host).items():
                    result = owner_hosts_setup.prove_role_policy(policy, self.host_table(policy, flip=name))
                    with self.subTest(host=host, role=role, probe=name):
                        self.assertTrue(result.state.startswith("unsupported (D3)"), result.state)
                        self.assertFalse(permissions.proof_enforces(policy, result.proof))
                        self.assertEqual(result.gaps, (("not denied " if expected == "deny" else "false deny ") + name,))

    def test_an_unobservable_probe_leaves_no_proof(self) -> None:
        policy = self.policy("codex", "implementer")
        result = owner_hosts_setup.prove_role_policy(policy, self.host_table(policy, hide="edit-state"))
        self.assertIsNone(result.proof)
        self.assertIn("unobserved edit-state", result.state)

    def test_an_interrupted_proof_promotes_nothing_writes_nothing_and_repeats_identically(self) -> None:
        policy = self.policy("codex", "reviewer")
        complete = self.host_table(policy)
        fresh = owner_hosts_setup.prove_role_policy(policy, complete)
        before = snapshot(self.root)
        total = len(permissions.probe_matrix("reviewer", "codex"))
        for stop in range(total):
            calls = []

            def interrupted(tool, tool_input, stop=stop, calls=calls):
                if len(calls) == stop:
                    raise owner_hosts_setup.ProbeInterrupted("timeout")
                calls.append(1)
                return complete(tool, tool_input)

            result = owner_hosts_setup.prove_role_policy(policy, interrupted)
            with self.subTest(stop=stop):
                self.assertIsNone(result.proof)
                self.assertTrue(result.state.startswith("unverified"))
                self.assertEqual(snapshot(self.root), before)
                self.assertEqual(owner_hosts_setup.prove_role_policy(policy, complete), fresh)

        def killed(tool, tool_input):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            owner_hosts_setup.prove_role_policy(policy, killed)
        self.assertEqual(snapshot(self.root), before)

    def test_a_proof_of_another_policy_digest_does_not_enforce(self) -> None:
        policy = self.policy("codex", "implementer")
        proof = owner_hosts_setup.prove_role_policy(policy, self.host_table(policy)).proof
        other = owner_hosts_codex.codex_role_policy(
            "implementer", self.project, self.worktrees, self.project / "other", self.project / ".git")
        self.assertNotEqual(other.digest, policy.digest)
        self.assertTrue(permissions.proof_enforces(policy, proof))
        self.assertFalse(permissions.proof_enforces(other, proof))

    def test_claude_role_launch_is_unsupported_and_never_inferred_from_settings(self) -> None:
        plan = owner_hosts_claude.plan_claude_project_allowlist(self.project)
        self.assertTrue(owner_hosts_claude.apply_claude_project_allowlist(plan))
        report = owner_hosts_setup.host_doctor("claude", self.project, self.config, self.worktrees, home=self.home)
        for role in permissions.ROLES:
            self.assertEqual(report["role-launch-" + role], "unsupported (D3): no host decision probe")

    def test_review_verdict_fact_names_who_records_verdicts(self) -> None:
        report = owner_hosts_setup.host_doctor("claude", self.project, self.config, self.worktrees, home=self.home)
        self.assertTrue(report["review-verdict"].startswith("owner only; record verdicts with cardine review verdict"))
        self.assertNotIn("required by default", owner_hosts_setup.review_verdict_fact({}, self.root / "missing"))
        self.assertEqual(owner_hosts_setup.review_verdict_fact({"role-launch-reviewer": "ready"}, self.project),
                         "launched reviewer or owner")
        governed = self.root / "governed"
        (governed / ".cardine").mkdir(parents=True)
        (governed / ".cardine/project.json").write_text(json.dumps({"preset": "governed"}), encoding="utf-8")
        with mock.patch("cardine.shared.project.read_project_declaration", return_value={"preset": "governed"}):
            self.assertTrue(owner_hosts_setup.review_verdict_fact({}, governed).endswith("; required by default in this project"))

    def test_codex_without_installed_role_rules_is_not_ready(self) -> None:
        report = owner_hosts_setup.host_doctor("codex", self.project, self.config, self.worktrees, home=self.home)
        self.assertEqual(report["role-launch-implementer"], "approval-required: role rules not installed")
        self.assertEqual(report["role-launch-reviewer"], "unsupported (D3): false deny read-tracked")

    def fake_codex(self, body: str) -> str:
        path = self.bin / "fake-codex"
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def test_codex_evaluator_maps_only_a_forbidden_decision_to_deny(self) -> None:
        rules = (self.root / "x.rules",)
        for output, expected in (('{"decision":"forbidden"}', "deny"), ('{"decision":"allow"}', "allow"),
                                 ('{"matchedRules":[]}', "allow")):
            evaluate = owner_hosts_setup.codex_decision_evaluator(self.fake_codex(f"echo '{output}'\n"), rules)
            with self.subTest(output=output):
                self.assertEqual(evaluate("shell", {"command": "git status"}), expected)
        evaluate = owner_hosts_setup.codex_decision_evaluator(self.fake_codex("echo '{}'\n"), rules)
        self.assertIsNone(evaluate("apply_patch", {"file_path": ".cardine/tasks/001.json"}))
        for body in ("exit 1\n", "echo not-json\n"):
            evaluate = owner_hosts_setup.codex_decision_evaluator(self.fake_codex(body), rules)
            with self.subTest(body=body), self.assertRaises(owner_hosts_setup.ProbeInterrupted):
                evaluate("shell", {"command": "git status"})

    def test_codex_reviewer_sandbox_proof_executes_only_in_temporary_repositories(self):
        for allow_write in (False, True):
            executable = self.root / 'sandbox-host'
            executable.write_text("#!/usr/bin/env python3\n" +
                "import pathlib, subprocess, sys\n" +
                "assert sys.argv[1:4] == ['sandbox', '-P', 'cardine-review-proof']\n" +
                "repo = pathlib.Path(sys.argv[5])\n" +
                "assert repo != pathlib.Path(" + repr(str(self.project)) + ")\n" +
                "assert (repo / '.git').is_dir()\n" +
                "command = sys.argv[-1]\n" +
                ("if command == 'echo changed > tracked.txt':\n"
                 "    sys.exit(subprocess.call(command, shell=True, cwd=repo))\n" if allow_write else "") +
                "if command == 'cat tracked.txt':\n"
                "    sys.exit(subprocess.call(command, shell=True, cwd=repo))\n"
                "sys.exit(1)\n")
            executable.chmod(0o755)
            before = snapshot(self.project)
            result = owner_hosts_setup.role_launch_states('codex', self.project, self.worktrees,
                                                         self.home, executable=str(executable))
            self.assertEqual(snapshot(self.project), before)
            self.assertEqual(result['role-launch-reviewer'],
                             'unsupported (D3): not denied write-worktree' if allow_write else 'ready')



if __name__ == "__main__":
    unittest.main()
