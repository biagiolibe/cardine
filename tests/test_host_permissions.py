"""Protected-path and role-action matrix, receipt-path inventory, and Claude policy installation."""
from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cardine.hosts import claude, codex, permissions
from cardine.lifecycle import delivery, receipts, validation
from cardine.integration import candidate
from cardine.shared.errors import CardineError
from cardine.tasks.state_core import state_path

ROOT = Path(__file__).resolve().parents[1]
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.test"]
STATE, EVIDENCE = ".cardine/tasks/001.json", ".cardine/evidence/001.json"

CHILD = '''
import os, sys, tempfile
from pathlib import Path
from cardine.hosts import claude
from cardine.lifecycle import receipts
project, seam = Path(sys.argv[1]), sys.argv[2]
tempfile.tempdir = sys.argv[3]
def boundary(name):
    if name == seam:
        os._exit(93)
receipts.boundary = boundary
claude.apply_claude_project_allowlist(claude.plan_claude_project_allowlist(project))
'''


CODEX_CHILD = '''
import os, sys, tempfile
from pathlib import Path
from cardine.hosts import codex
from cardine.lifecycle import receipts
home, seam = Path(sys.argv[1]), sys.argv[2]
tempfile.tempdir = sys.argv[3]
def boundary(name):
    if name == seam:
        os._exit(93)
receipts.boundary = boundary
plan = codex.plan_codex_role_policies(home / ".codex/config.toml", home / ".codex", home / "worktrees")
codex.apply_codex_role_policies(plan)
'''


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.project / "src").mkdir()
        (self.project / "src/module.py").write_text("x = 1\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "init")
        self.external = self.base / "elsewhere/task-001"
        self.git("worktree", "add", "-q", "-b", "task-001", str(self.external))
        self.common = (self.project / ".git").resolve()
        self.roots = permissions.protected_roots((self.project, self.external), self.common)

    def git(self, *args: str) -> None:
        subprocess.run([*GIT, *args], cwd=self.project, check=True, capture_output=True)

    def decide(self, role: str, command: str, cwd: Path | None = None) -> bool:
        return permissions.evaluate_command(command, role=role, roots=self.roots, cwd=cwd or self.external).allowed

    def native(self, role: str, tool: str, **tool_input: str) -> bool:
        return permissions.evaluate_tool(tool, tool_input, role=role, roots=self.roots, cwd=self.external).allowed


class PathActionMatrixTest(Fixture):
    def test_native_tools_cannot_write_protected_paths_in_any_checkout(self) -> None:
        for tool in permissions.NATIVE_WRITE_TOOLS:
            for checkout in (self.project, self.external):
                for relative in (STATE, EVIDENCE, ".cardine/tasks/.001.intent.json", ".cardine/project.json",
                                 ".cardine/tasks/001.json.stage", ".cardine/.project.json.op.0.stage"):
                    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
                    with self.subTest(tool=tool, path=str(checkout / relative)):
                        self.assertFalse(self.native("implementer", tool, **{key: str(checkout / relative)}))
            self.assertFalse(self.native("implementer", tool, file_path=str(self.common / "cardine-operations/001.guard")))
            self.assertFalse(self.native("implementer", tool, file_path=str(Path(tempfile.gettempdir()) / "cardine-operations/x.json")))

    def test_task_source_edits_and_reads_are_not_falsely_denied(self) -> None:
        self.assertTrue(self.native("implementer", "Edit", file_path=str(self.external / "src/module.py")))
        self.assertTrue(self.native("implementer", "Write", file_path=str(self.external / "tasks/001-name.md")))
        self.assertTrue(self.native("implementer", "Read", file_path=str(self.external / STATE)))
        self.assertTrue(self.native("reviewer", "Grep", pattern="x"))
        self.assertFalse(self.native("reviewer", "Edit", file_path=str(self.external / "src/module.py")))

    def test_aliases_symlinks_and_dot_dot_resolve_to_the_protected_destination(self) -> None:
        tasks = self.external / ".cardine/tasks"
        tasks.mkdir(parents=True)
        (self.external / "alias").symlink_to(tasks)
        (self.external / "src/link.json").symlink_to(tasks / "001.json")
        for path in (self.external / "alias/001.json", self.external / "src/../.cardine/tasks/001.json",
                     self.external / "src/link.json"):
            with self.subTest(path=str(path)):
                self.assertFalse(self.native("implementer", "Edit", file_path=str(path)))
                self.assertFalse(self.decide("implementer", f"echo x > {path}"))
        real = str(self.external)
        bare = real.removeprefix("/private") if real.startswith(("/private/var/", "/private/tmp/")) else real
        # Check only the spellings that this platform resolves to the same directory:
        # /tmp aliases /private/tmp on macOS, while on Linux /private/tmp is another path.
        for spelling in {real, bare, "/private" + bare}:
            if Path(spelling).resolve() == Path(real).resolve():
                self.assertFalse(self.native("implementer", "Edit", file_path=f"{spelling}/{STATE}"), spelling)
        self.assertFalse(self.decide("implementer", "ln -s .cardine/tasks/001.json src/alias2"))

    def test_shell_writers_chains_pipes_and_redirects(self) -> None:
        for command in (
            f"echo {{}} > {STATE}", f"echo {{}} >> {STATE}", f"echo x >| {STATE}", f"echo x &> {EVIDENCE}",
            f"echo x 2> {STATE}", f"true && echo x > {STATE}", f"false || echo x >> {STATE}",
            f"ls; echo x > {STATE}", f"ls\necho x > {STATE}", f"echo x | tee {STATE}", f"echo x | tee -a {STATE}",
            f"cp /tmp/a {STATE}", f"cp -t .cardine/tasks /tmp/a", f"mv /tmp/a {EVIDENCE}", f"mv {STATE} /tmp/a",
            f"rm {STATE}", f"rm -f .cardine/tasks/*", f"touch {STATE}", f"truncate -s 0 {STATE}",
            f"sed -i s/a/b/ {STATE}", f"sed -i.bak s/a/b/ {STATE}", f"sed -ni p {STATE}",
            f"perl -pi -e 's/a/b/' {STATE}", f"dd if=/dev/zero of={STATE}", f"install /tmp/a {STATE}",
            f"git checkout -- {STATE}", f"git restore {STATE}", f"git -C .cardine/tasks status",
            f"cat <<EOF > {STATE}\nx\nEOF", f"cat $(echo {STATE}) > {STATE}", f"echo `echo x > {STATE}`",
            f"echo x > $TARGET", f"echo x > \"{STATE}\"", f"(echo x > {STATE})",
        ):
            with self.subTest(command=command):
                self.assertFalse(self.decide("implementer", command))

    def test_wrappers_interpreters_and_xargs_are_followed(self) -> None:
        for command in (
            f"env FOO=1 sh -c 'echo x > {STATE}'", f"bash -c 'echo x > {STATE}'", f"zsh -lc \"rm {STATE}\"",
            f"command rm {STATE}", f"nohup rm {STATE}", f"time cp /tmp/a {STATE}", f"timeout 5 rm {STATE}",
            f"env -i rm {STATE}", f"sudo rm {STATE}", f"eval 'rm {STATE}'", "xargs rm", f"ls | xargs rm -f",
            f"python3 -c \"open('{STATE}','w').write('x')\"", f"python3 -c \"import os; os.unlink('.cardine/tasks/001.json')\"",
            "node -e \"require('fs').writeFileSync('.cardine/tasks/001.json','')\"",
            "ruby -e \"File.write('.cardine/tasks/001.json','')\"", "perl -e 'unlink q(.cardine/tasks/001.json)'",
            "python3 -c \"exec(__import__('base64').b64decode('eA=='))\"", "bash script.sh",
            f"python3 tools/fix.py {STATE}", f"echo $(rm {STATE})", f"git -c core.x=y -C . checkout -- {STATE}",
            "sh", "bash < script.sh", "echo 'unterminated",
        ):
            with self.subTest(command=command):
                self.assertFalse(self.decide("implementer", command))

    def test_developer_integration_and_review_actions_by_role(self) -> None:
        for command in (
            "cardine review verdict 001 APPROVE --owner", "cardine review verdict 001 APPROVE --body x",
            "cardine --project . review verdict 001 CHANGES_REQUESTED --owner --request-id r",
            "cardine cancel 001 --reason x", "cardine --project . abort 001", "cardine task contract update 001",
            "cardine task transition 001 done", "cardine worktree integrate stage 001",
            "cardine --format json worktree --project . cleanup 001", "cardine worktree advance 001 --format json",
            "python3 scripts/cardine_cli.py cancel 001 --reason x", "python3 -m cardine abort 001",
            "env cardine cancel 001 --reason x", "cardine setup --apply",
        ):
            for role in permissions.ROLES:
                with self.subTest(role=role, command=command):
                    self.assertFalse(self.decide(role, command))
        implementer_only = "cardine review verdict 001 APPROVE --request-id r"
        self.assertFalse(self.decide("implementer", implementer_only))
        self.assertTrue(self.decide("reviewer", implementer_only))
        self.assertTrue(self.decide("reviewer", "cardine --project . review verdict 001 BLOCKED --request-id=r --body ok"))
        self.assertFalse(self.decide("reviewer", "cardine task close 001"))
        self.assertFalse(self.decide("reviewer", "cardine execution deliver 001"))

    def test_push_variants(self) -> None:
        for command in (
            "git push origin main", "git push origin HEAD:main", "git push origin +main", "git push origin :main",
            "git push origin HEAD:refs/heads/main", "git push origin refs/heads/main", "git push origin master",
            "git push --force origin task-1", "git push -f origin task-1", "git push origin task-1 --force-with-lease",
            "git push --delete origin task-1", "git push -d origin task-1", "git push --mirror", "git push --all",
            "git push --tags origin", "git push", "git push origin", "git push origin HEAD",
            "git -C . push origin main", "git -c push.default=matching push origin main", "git --no-pager push origin main",
            "git push main origin main", "cd .. && git push origin main", "echo x | git push origin main",
        ):
            with self.subTest(command=command):
                self.assertFalse(self.decide("implementer", command))
        self.assertTrue(self.decide("implementer", "git push origin task-001"))
        self.assertTrue(self.decide("implementer", "git push -u origin task-001"))
        self.assertTrue(self.decide("implementer", "git -C . push origin HEAD:task-001"))
        self.assertFalse(self.decide("reviewer", "git push origin task-001"))

    def test_false_deny_controls(self) -> None:
        for command in (
            "git status", "git diff --stat", "git log -1", "git add -A", "git commit -m 'message'",
            "git commit -m \"$(cat <<'EOF'\nSubject\n\nBody mentions .cardine/tasks/001.json\nEOF\n)\"",
            f"cat {STATE}", f"grep -n version {STATE}", f"ls {STATE}", f"head -5 {EVIDENCE}", f"git show HEAD:{STATE}",
            "sed -i s/a/b/ src/module.py", "echo x > src/new.txt", "cp src/module.py src/copy.py", "mv src/copy.py src/c2.py",
            "rm src/c2.py", "touch tasks/001-name.md", "cardine task close 001", "cardine execution start 001",
            "cardine worktree prepare 001 --format json", "cardine status", "python3 scripts/run_tests.py --parallel",
            "python3 -c \"print(1 + 1)\"", "ls | wc -l", "cat src/module.py | grep x > /dev/null", "echo x 2>&1",
            "git push origin task-001", "cd src && ls", "env FOO=1 ls", "xargs echo",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.decide("implementer", command))
        for command in ("git status", f"cat {STATE}", "git diff", "ls | wc -l", "grep -rn x src", "git log --oneline",
                        "python3 -c \"print(1)\"", "cat src/module.py > /dev/null"):
            with self.subTest(role="reviewer", command=command):
                self.assertTrue(self.decide("reviewer", command))
        for command in ("echo x > src/new.txt", "git commit -m x", "git add .", "rm src/module.py", "sed -i s/a/b/ src/module.py",
                        "cp a b", "python3 -c \"open('x','w')\"", "git checkout main", "git worktree add ../x"):
            with self.subTest(role="reviewer", command=command):
                self.assertFalse(self.decide("reviewer", command))

    def test_unknown_roles_and_unparsable_input_are_refused(self) -> None:
        self.assertFalse(permissions.evaluate_command("ls", role="coordinator", roots=self.roots, cwd=self.external).allowed)
        for bad in ("", "  ", None, "ls\0"):
            self.assertFalse(permissions.evaluate_command(bad, role="implementer", roots=self.roots, cwd=self.external).allowed)
        self.assertFalse(permissions.evaluate_tool("Bash", "ls", role="implementer", roots=self.roots, cwd=self.external).allowed)
        self.assertFalse(permissions.evaluate_tool("Edit", {}, role="implementer", roots=self.roots, cwd=self.external).allowed)
        self.assertFalse(permissions.evaluate_tool("Mystery", {"path": str(self.external / STATE)}, role="implementer",
                                                   roots=self.roots, cwd=self.external).allowed)

    def test_the_probe_matrix_agrees_with_the_guard_for_both_roles(self) -> None:
        for role in permissions.ROLES:
            probes = permissions.probe_matrix(role)
            self.assertGreaterEqual(len(probes), 20)
            self.assertIn("allow", {expected for _t, _i, expected in probes.values()})
            for name, (tool, tool_input, expected) in probes.items():
                with self.subTest(role=role, probe=name):
                    decision = permissions.evaluate_tool(tool, tool_input, role=role, roots=self.roots, cwd=self.external)
                    self.assertEqual("allow" if decision.allowed else "deny", expected, decision.reason)


class ReceiptPathInventoryTest(Fixture):
    def inside(self, path: Path) -> bool:
        return permissions.is_protected(str(path), self.roots, self.external)

    def test_every_actual_receipt_and_operation_path_is_protected(self) -> None:
        for checkout in (self.project, self.external):
            (checkout / ".cardine/tasks").mkdir(parents=True, exist_ok=True)
            paths = [state_path(checkout, "001"), receipts._intent_path(checkout, "001"),
                     checkout / ".cardine/tasks/.001.json.op.0.stage",
                     checkout / permissions.names().execution_evidence_path("001"),
                     checkout / permissions.names().project_declaration_path,
                     checkout / permissions.names().candidate_validation_path,
                     receipts.guard_path(checkout, "001"), delivery._operation_path(checkout, "001"),
                     validation.operation_path(checkout, "001"), receipts.nonrun_path(checkout, "init"),
                     receipts.operation_path(checkout, "setup")]
            for path in paths:
                with self.subTest(path=str(path)):
                    self.assertTrue(self.inside(path))
        located = SimpleNamespace(common_dir=self.common, task_id="001")
        for path in (candidate.operation_path(located), candidate.operation_path(located, "residue"),
                     receipts.host_path("setup", self.base), receipts.host_path("init", self.project)):
            with self.subTest(path=str(path)):
                self.assertTrue(self.inside(path))

    def test_ordinary_project_files_stay_writable(self) -> None:
        for path in (self.external / "src/module.py", self.external / "tasks/001-name.md", self.project / "README.md",
                     self.external / ".claude/settings.local.json"):
            self.assertFalse(self.inside(path), path)

    def test_every_source_site_that_builds_a_receipt_location_is_inventoried(self) -> None:
        """A new resolver fails here until its location is covered above and listed."""
        known = {"hosts/permissions.py", "lifecycle/receipts.py", "lifecycle/delivery.py", "lifecycle/validation.py",
                 "integration/candidate.py", "integration/residue.py", "lifecycle/control_abort.py",
                 "console/snapshot.py"}  # snapshot only reads the cleanup record
        found = set()
        for path in sorted((ROOT / "src/cardine").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and "cardine-operations" in node.value:
                    found.add(path.relative_to(ROOT / "src/cardine").as_posix())
        self.assertEqual(found, known)
        users = {path.relative_to(ROOT / "src/cardine").as_posix() for path in (ROOT / "src/cardine").rglob("*.py")
                 if any(isinstance(n, ast.Attribute) and n.attr in ("tasks_path", "execution_evidence_path",
                                                                     "project_declaration_path", "task_identity_path",
                                                                     "candidate_validation_path", "flow_targets_path")
                        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))))}
        self.assertTrue({"hosts/permissions.py", "lifecycle/receipts.py"} <= users)

    def test_the_inventory_is_deterministic_and_never_writes(self) -> None:
        before = snapshot(self.base)
        again = permissions.protected_roots((self.project, self.external), self.common)
        self.assertEqual(again, self.roots)
        self.assertEqual(snapshot(self.base), before)
        self.assertFalse((self.project / ".cardine").exists())


class ClaudePolicyInstallationTest(Fixture):
    def settings(self) -> dict:
        return json.loads((self.project / ".claude/settings.local.json").read_text())

    def test_plan_write_and_verification_use_the_existing_operation(self) -> None:
        settings = self.project / ".claude/settings.local.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"keep": 1, "permissions": {"allow": ["Bash(mine:*)"], "deny": ["Bash(rm:*)"]}}))
        plan = claude.plan_claude_project_allowlist(self.project)
        self.assertEqual(plan.status, "approval-required")
        self.assertTrue(claude.apply_claude_project_allowlist(plan))
        written = self.settings()
        self.assertEqual(written["keep"], 1)
        self.assertEqual(written["permissions"]["deny"][0], "Bash(rm:*)")
        self.assertIn("Bash(mine:*)", written["permissions"]["allow"])
        for tool in permissions.NATIVE_WRITE_TOOLS:
            for path in permissions.relative_protected():
                self.assertIn(f"{tool}(/{path})", written["permissions"]["deny"])
        self.assertNotIn("Bash(git push origin main)", written["permissions"]["allow"])
        self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)
        self.assertEqual(claude.plan_claude_project_allowlist(self.project).status, "ready")
        intent = receipts._load_intent(receipts.host_path("claude-allowlist", settings))
        self.assertEqual(set(intent["effects"].values()), {"done"})

    def test_read_only_checks_repeat_without_any_write(self) -> None:
        before = snapshot(self.base)
        first = claude.plan_claude_project_allowlist(self.project)
        second = claude.plan_claude_project_allowlist(self.project)
        self.assertEqual((first.status, first.detail, first.proposed_settings),
                         (second.status, second.detail, second.proposed_settings))
        self.assertEqual(snapshot(self.base), before)
        self.assertFalse((self.project / ".claude").exists())

    def test_a_legacy_main_push_entry_is_kept_and_reported_never_removed(self) -> None:
        settings = self.project / ".claude/settings.local.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"permissions": {"allow": ["Bash(git push origin main)"]}}))
        plan = claude.plan_claude_project_allowlist(self.project)
        self.assertIn("Bash(git push origin main)", plan.detail)
        self.assertIn("unprovable ownership", plan.detail)
        claude.apply_claude_project_allowlist(plan)
        self.assertIn("Bash(git push origin main)", self.settings()["permissions"]["allow"])
        self.assertIn("unprovable ownership", claude.plan_claude_project_allowlist(self.project).detail)

    def test_every_interruption_converges_to_a_fresh_install(self) -> None:
        fresh = self.base / "fresh"
        fresh.mkdir()
        claude.apply_claude_project_allowlist(claude.plan_claude_project_allowlist(fresh))
        expected = (fresh / ".claude/settings.local.json").read_text()
        for seam in ("before_file:claude-allowlist", "after_file:claude-allowlist"):
            with self.subTest(seam=seam):
                victim = self.base / ("victim-" + seam.split(":")[0])
                victim.mkdir()
                run = lambda name: subprocess.run(
                    [sys.executable, "-c", CHILD, str(victim), name, str(self.base / "receipts")],
                    capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
                self.assertEqual(run(seam).returncode, 93)
                finished = run("never")
                self.assertEqual(finished.returncode, 0, finished.stderr)
                self.assertEqual((victim / ".claude/settings.local.json").read_text(), expected)
                self.assertEqual(claude.plan_claude_project_allowlist(victim).status, "ready")

    def test_foreign_symlink_and_malformed_settings_are_never_overwritten(self) -> None:
        settings = self.project / ".claude/settings.local.json"
        settings.parent.mkdir()
        settings.write_text("{not json")
        self.assertEqual(claude.plan_claude_project_allowlist(self.project).status, "blocked")
        self.assertEqual(settings.read_text(), "{not json")


class RolePolicyTest(Fixture):
    def policy(self, role: str, worktree: Path | None = None):
        return claude.claude_role_policy(role, self.project, worktree or self.external, self.common)

    def test_role_policies_are_deterministic_distinct_and_hold_no_credential(self) -> None:
        implementer, reviewer = self.policy("implementer"), self.policy("reviewer")
        self.assertEqual(implementer, self.policy("implementer"))
        self.assertNotEqual((implementer.identity, implementer.digest), (reviewer.identity, reviewer.digest))
        self.assertEqual({implementer.identity, reviewer.identity}, {"cardine-implementer", "cardine-reviewer"})
        for policy in (implementer, reviewer):
            text = json.dumps(policy.settings).lower()
            for secret in ("token", "credential", "secret", "password", "api_key", "env"):
                self.assertNotIn(secret, text)
            self.assertEqual(set(policy.settings), {"permissions"})
            deny = policy.settings["permissions"]["deny"]
            self.assertEqual(len(deny), len(set(deny)))
            self.assertIn("Bash(git push origin main:*)", deny)
            self.assertIn("Bash(cardine cancel:*)", deny)
            self.assertTrue(any(rule.startswith(f"Edit(//{self.external.as_posix().lstrip('/')}") or rule.startswith("Edit(//")
                                for rule in deny))
        self.assertIn("Bash(cardine review verdict:*)", implementer.settings["permissions"]["deny"])
        self.assertNotIn("Bash(cardine review verdict:*)", reviewer.settings["permissions"]["deny"])
        self.assertIn("Edit", reviewer.settings["permissions"]["deny"])
        self.assertNotIn("Edit", implementer.settings["permissions"]["deny"])

    def test_the_policy_changes_with_the_checkout_and_rejects_unknown_roles(self) -> None:
        other = self.base / "elsewhere/task-002"
        self.assertNotEqual(self.policy("implementer").digest, self.policy("implementer", other).digest)
        from cardine.shared.errors import CardineError
        with self.assertRaises(CardineError):
            claude.claude_role_policy("coordinator", self.project, self.external, self.common)

    def host_proof(self, policy, **change):
        """Decisions as a host double reports them: evaluated per probe, never read from settings."""
        decisions = {}
        for name, (tool, tool_input, _expected) in permissions.probe_matrix(policy.role).items():
            observed = permissions.evaluate_tool(tool, tool_input, role=policy.role, roots=self.roots, cwd=self.external)
            decisions[name] = "allow" if observed.allowed else "deny"
        decisions.update(change.pop("decisions", {}))
        fields = dict(host="claude", identity=policy.identity, digest=policy.digest, decisions=decisions)
        return permissions.HostProof(**{**fields, **change})

    def test_only_a_complete_host_proof_of_this_exact_policy_enforces(self) -> None:
        for role in permissions.ROLES:
            policy = self.policy(role)
            self.assertTrue(permissions.proof_enforces(policy, self.host_proof(policy)))
            self.assertFalse(permissions.proof_enforces(policy, None))
            self.assertFalse(permissions.proof_enforces(policy, self.host_proof(policy, digest="0" * 64)))
            self.assertFalse(permissions.proof_enforces(policy, self.host_proof(policy, identity="cardine-other")))
            self.assertFalse(permissions.proof_enforces(policy, self.host_proof(policy, host="codex")))
            self.assertFalse(permissions.proof_enforces(policy, self.host_proof(policy, decisions={"push-main": "allow"})))
            partial = self.host_proof(policy)
            partial.decisions.pop("inspect-status")
            self.assertFalse(permissions.proof_enforces(policy, partial))
            self.assertFalse(permissions.proof_enforces(policy, self.host_proof(policy, decisions={"inspect-status": "deny"})))
            self.assertFalse(permissions.proof_enforces(policy, policy.settings))  # settings text is not a proof
            self.assertFalse(claude.claude_role_profile(policy, None).enforced)
            self.assertTrue(claude.claude_role_profile(policy, self.host_proof(policy)).enforced)


class CodexRolePolicyTest(Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.base / "home"
        (self.home / ".codex").mkdir(parents=True)
        self.worktrees = self.home / "worktrees"
        self.config = self.home / ".codex/config.toml"

    def plan(self, home: Path | None = None):
        home = home or self.home
        return codex.plan_codex_role_policies(home / ".codex/config.toml", home / ".codex", home / "worktrees")

    def policy(self, role: str, worktree: Path | None = None):
        return codex.codex_role_policy(role, self.project, self.worktrees, worktree or self.external, self.common)

    def install(self) -> None:
        self.assertTrue(codex.apply_codex_role_policies(self.plan()))

    def host_proof(self, policy, **change):
        decisions = {}
        for name, (tool, tool_input, _expected) in permissions.probe_matrix(policy.role, "codex").items():
            observed = permissions.evaluate_tool(tool, tool_input, role=policy.role, roots=self.roots, cwd=self.external)
            decisions[name] = "allow" if observed.allowed else "deny"
        decisions.update(change.pop("decisions", {}))
        fields = dict(host="codex", identity=policy.identity, digest=policy.digest, decisions=decisions)
        return permissions.HostProof(**{**fields, **change})

    def test_the_host_decision_table_translates_tools_and_keeps_claude_unchanged(self) -> None:
        for role in permissions.ROLES:
            claude_matrix, codex_matrix = permissions.probe_matrix(role), permissions.probe_matrix(role, "codex")
            self.assertEqual(claude_matrix, permissions.probe_matrix(role, "claude"))
            self.assertEqual(set(claude_matrix), set(codex_matrix))
            self.assertEqual({tool for tool, _i, _v in codex_matrix.values()}, {"shell", "apply_patch"})
            for name, (tool, tool_input, verdict) in claude_matrix.items():
                self.assertEqual((codex_matrix[name][1], codex_matrix[name][2]), (tool_input, verdict))
            for name, (tool, tool_input, verdict) in codex_matrix.items():
                observed = permissions.evaluate_tool(tool, tool_input, role=role, roots=self.roots, cwd=self.external)
                self.assertEqual("allow" if observed.allowed else "deny", verdict, name)
        with self.assertRaises(CardineError):
            permissions.probe_matrix("implementer", "gemini")

    def test_roots_are_bounded_and_the_policy_is_deterministic_without_credentials(self) -> None:
        implementer, reviewer = self.policy("implementer"), self.policy("reviewer")
        self.assertEqual(implementer, self.policy("implementer"))
        self.assertEqual({implementer.identity, reviewer.identity}, {"cardine-implementer", "cardine-reviewer"})
        self.assertNotEqual(implementer.digest, reviewer.digest)
        self.assertNotEqual(implementer.digest, self.policy("implementer", self.base / "elsewhere/task-002").digest)
        for policy in (implementer, reviewer):
            self.assertEqual(policy.settings["profile"]["workspace_roots"], {str(self.worktrees.resolve()): True})
            self.assertEqual(policy.settings["profile"]["extends"], ":workspace")
            text = json.dumps(policy.settings).lower()
            for secret in ("token", "credential", "secret", "password", "api_key"):
                self.assertNotIn(secret, text)
        for unsafe in (Path("/"), Path.home()):
            with self.assertRaises(CardineError):
                codex.codex_role_policy("implementer", self.project, unsafe, self.external, self.common)
            self.assertEqual(codex.plan_codex_role_policies(self.config, self.home / ".codex", unsafe).status, "blocked")
        with self.assertRaises(CardineError):
            codex.codex_role_policy("coordinator", self.project, self.worktrees, self.external, self.common)

    def test_direct_main_push_is_denied_for_both_roles_and_never_in_the_coordinator_rules(self) -> None:
        for role in permissions.ROLES:
            rules = "\n".join(codex.role_rule_lines(role))
            for target in ("main", "+main", "HEAD:main", "HEAD:refs/heads/main", "master"):
                self.assertIn(f'"git", "push", "origin", "{target}"], decision="forbidden"', rules)
            self.assertNotIn('decision="allow"', rules)
            self.assertIn('"cardine", "worktree", "integrate"', rules)
        self.assertIn('"cardine", "review", "verdict"', "\n".join(codex.role_rule_lines("implementer")))
        self.assertNotIn('"cardine", "review", "verdict"', "\n".join(codex.role_rule_lines("reviewer")))
        self.assertNotIn('"main"', codex.CODEX_USER_RULES)  # the coordinator's authorized main push stays unforbidden
        self.assertNotIn("cardine-roles", codex.CODEX_USER_RULES)
        self.assertNotEqual(codex.role_rules_path(self.home / ".codex", "implementer").parent, self.home / ".codex/rules")

    def test_install_replaces_blocks_and_rules_and_preserves_user_text(self) -> None:
        user = '# mine\nmodel = "x"\n\n[tools]\nweb = true # keep\n'
        self.config.write_text(user)
        plan = self.plan()
        self.assertEqual(plan.status, "approval-required")
        self.install()
        text = self.config.read_text()
        self.assertTrue(text.startswith(user))
        parsed = __import__("tomllib").loads(text)
        for role in permissions.ROLES:
            profile = parsed["permissions"][f"cardine-{role}"]
            self.assertEqual(profile["workspace_roots"], {str(self.worktrees.resolve()): True})
            self.assertEqual(profile["extends"], ":workspace")
            rules = codex.role_rules_path(self.home / ".codex", role)
            self.assertEqual(rules.read_text(), codex._role_rules_text(role))
            self.assertEqual(stat.S_IMODE(rules.stat().st_mode), 0o600)
        self.assertNotIn("default_permissions", parsed)
        self.assertEqual(self.config.with_name("config.toml.cardine-backup-1").read_text(), user)
        self.assertEqual(self.plan().status, "ready")
        self.assertFalse(codex.apply_codex_role_policies(self.plan()))
        intent = receipts._load_intent(receipts.host_path("codex-roles", self.config))
        self.assertEqual(set(intent["effects"].values()), {"done"})

    def test_an_owned_older_root_is_replaced_with_a_backup(self) -> None:
        self.install()
        other = self.home / "other-worktrees"
        plan = codex.plan_codex_role_policies(self.config, self.home / ".codex", other)
        self.assertEqual(plan.status, "approval-required")
        old = self.config.read_text()
        codex.apply_codex_role_policies(plan)
        self.assertIn(str(other.resolve()), self.config.read_text())
        self.assertNotIn(str(self.worktrees.resolve()), self.config.read_text())
        self.assertEqual(self.config.with_name("config.toml.cardine-backup-1").read_text(), old)
        self.assertEqual(codex.plan_codex_role_policies(self.config, self.home / ".codex", other).status, "ready")

    def test_read_only_checks_repeat_without_any_write(self) -> None:
        self.config.write_text('model = "x"\n')
        before, mtimes = snapshot(self.base), {p: p.stat().st_mtime_ns for p in self.base.rglob("*")}
        first, second = self.plan(), self.plan()
        self.assertEqual((first.status, first.proposed_config, first.rules), (second.status, second.proposed_config, second.rules))
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual({p: p.stat().st_mtime_ns for p in self.base.rglob("*")}, mtimes)
        self.assertFalse(list(self.base.rglob("*cardine-backup*")))
        self.assertFalse((self.home / ".codex" / codex.ROLE_RULES_DIRECTORY).exists())

    def test_shared_and_foreign_profiles_block_everything_and_are_preserved(self) -> None:
        cases = {
            "foreign profile": '[permissions.cardine-reviewer]\nextends = ":workspace"\n',
            "damaged markers": "# CARDINE:BEGIN role-permissions-implementer v1\n",
            "edited block": None,
            "malformed": "[permissions\n",
        }
        for label, text in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as raw:
                home = Path(raw).resolve()
                (home / ".codex").mkdir()
                config = home / ".codex/config.toml"
                if text is None:
                    config.write_text(codex._role_block("implementer", home / "worktrees").replace("extends", "# x\nextends") + "\n")
                else:
                    config.write_text(text)
                before = snapshot(home)
                plan = self.plan(home)
                self.assertEqual(plan.status, "blocked", plan.detail)
                with self.assertRaises(CardineError):
                    codex.apply_codex_role_policies(plan)
                self.assertEqual(snapshot(home), before)
        with tempfile.TemporaryDirectory() as raw:  # foreign or symlinked role rules
            home = Path(raw).resolve()
            rules = codex.role_rules_path(home / ".codex", "reviewer")
            rules.parent.mkdir(parents=True)
            for make in (lambda: rules.write_text("# mine\n"), lambda: rules.symlink_to(home / "target")):
                make()
                self.assertEqual(self.plan(home).status, "blocked")
                rules.unlink()
        with tempfile.TemporaryDirectory() as raw:  # the shared base profile and its selection are never touched
            home = Path(raw).resolve()
            (home / ".codex").mkdir()
            base = '[permissions.cardine-worktrees]\nextends = ":workspace"\n'
            (home / ".codex/config.toml").write_text('default_permissions = "cardine-worktrees"\n\n' + base)
            plan = self.plan(home)
            codex.apply_codex_role_policies(plan)
            self.assertTrue((home / ".codex/config.toml").read_text().startswith('default_permissions = "cardine-worktrees"\n\n' + base))

    def test_no_broad_fallback_when_either_profile_is_incomplete(self) -> None:
        policies = {role: self.policy(role) for role in permissions.ROLES}
        proofs = {role: self.host_proof(policies[role]) for role in permissions.ROLES}
        self.install()
        ready = self.plan()
        self.assertTrue(all(p.enforced for p in codex.codex_role_profiles(ready, policies, proofs).values()))
        for broken in (self.plan(self.base / "empty-home"), codex.CodexRolePlan("blocked", self.config, "x", "", None, ())):
            self.assertFalse(any(p.enforced for p in codex.codex_role_profiles(broken, policies, proofs).values()))
        for missing in permissions.ROLES:
            partial = {role: proof for role, proof in proofs.items() if role != missing}
            profiles = codex.codex_role_profiles(ready, policies, partial)
            self.assertEqual({role: p.enforced for role, p in profiles.items()}, {"implementer": False, "reviewer": False})
        self.assertFalse(any(p.enforced for p in codex.codex_role_profiles(ready, {"implementer": policies["implementer"]}, proofs).values()))

    def test_only_a_complete_host_proof_enforces_never_the_rendered_text(self) -> None:
        for role in permissions.ROLES:
            policy = self.policy(role)
            self.assertTrue(codex.codex_role_profile(policy, self.host_proof(policy)).enforced)
            self.assertFalse(codex.codex_role_profile(policy, None).enforced)
            self.assertFalse(codex.codex_role_profile(policy, policy.settings).enforced)
            self.assertFalse(codex.codex_role_profile(policy, self.host_proof(policy, host="claude")).enforced)
            self.assertFalse(codex.codex_role_profile(policy, self.host_proof(policy, digest="0" * 64)).enforced)
            self.assertFalse(codex.codex_role_profile(policy, self.host_proof(policy, decisions={"push-main": "allow"})).enforced)
            partial = self.host_proof(policy)
            partial.decisions.pop("push-reordered")
            self.assertFalse(codex.codex_role_profile(policy, partial).enforced)
            self.assertFalse(permissions.proof_enforces(policy, self.host_proof(policy, host="claude")))

    def test_every_interruption_converges_to_a_fresh_install(self) -> None:
        fresh = self.base / "fresh"
        (fresh / ".codex").mkdir(parents=True)
        codex.apply_codex_role_policies(self.plan(fresh))
        tree = lambda home: {p.relative_to(home).as_posix(): p.read_bytes().replace(str(home).encode(), b"<home>")
                             for p in sorted((home / ".codex").rglob("*")) if p.is_file()}
        expected = tree(fresh)
        seams = [f"{when}:{kind}" for kind in ("codex-roles-config", "codex-roles-rules-implementer", "codex-roles-rules-reviewer")
                 for when in ("before_file", "after_file")]
        for seam in seams:
            with self.subTest(seam=seam):
                victim = self.base / ("victim-" + seam.replace(":", "-"))
                (victim / ".codex").mkdir(parents=True)
                run = lambda name: subprocess.run(
                    [sys.executable, "-c", CODEX_CHILD, str(victim), name, str(self.base / "receipts")],
                    capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
                self.assertEqual(run(seam).returncode, 93)
                finished = run("never")
                self.assertEqual(finished.returncode, 0, finished.stderr)
                self.assertEqual(tree(victim), expected)
                self.assertEqual(self.plan(victim).status, "ready")


if __name__ == "__main__":
    unittest.main()
