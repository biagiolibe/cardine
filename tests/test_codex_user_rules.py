"""User-level setup ownership and real Codex decision coverage."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cardine_cli
from cardine.hosts import setup as owner_hosts_setup
import cardine.shared.errors as shared_errors
from cardine.hosts import codex as owner_hosts_codex


class CodexUserRulesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.rules = self.home / ".codex/rules/cardine.rules"

    def write(self, text):
        self.rules.parent.mkdir(parents=True, exist_ok=True)
        self.rules.write_bytes(text.encode())

    def test_plan_apply_preserves_foreign_bytes_and_is_idempotent(self):
        for foreign in ("", '# foreign\r\nprefix_rule(pattern=["other"], decision="allow")'):
            with self.subTest(foreign=foreign):
                if self.rules.exists():
                    self.rules.unlink()
                if foreign:
                    self.write(foreign)
                plan = owner_hosts_codex.plan_codex_user_rules(self.rules)
                self.assertEqual(plan.status, "missing")
                self.assertEqual(self.rules.read_bytes().decode() if self.rules.exists() else "", foreign)
                self.assertTrue(owner_hosts_codex.apply_codex_user_rules(plan))
                self.assertTrue(self.rules.read_bytes().startswith(foreign.encode()))
                ready = owner_hosts_codex.plan_codex_user_rules(self.rules)
                self.assertEqual(ready.status, "ready")
                self.assertFalse(owner_hosts_codex.apply_codex_user_rules(ready))

    def test_changed_block_is_preserved(self):
        before, after = "# foreign before\r\n", "# foreign after\r\n"
        self.write(before + "# CARDINE:BEGIN codex-user-rules v0\n# old\n# CARDINE:END codex-user-rules\n" + after)
        original = self.rules.read_bytes()
        with self.assertRaisesRegex(shared_errors.CardineError, "has changed"):
            owner_hosts_codex.plan_codex_user_rules(self.rules)
        self.assertEqual(self.rules.read_bytes(), original)

    def test_damaged_markers_stop_before_any_setup_mutation(self):
        for text in (
            "# CARDINE:BEGIN codex-user-rules v1\n",
            "# CARDINE:END codex-user-rules\n",
            owner_hosts_codex.CODEX_USER_RULES * 2,
            "# CARDINE:END codex-user-rules\n# CARDINE:BEGIN codex-user-rules v1\n",
            "# CARDINE:BEGIN codex-user-rules broken\n# CARDINE:END codex-user-rules\n",
        ):
            self.write(text)
            with self.assertRaisesRegex(shared_errors.CardineStop, "BLOCKED COMMAND_REFUSED.*damaged"):
                owner_hosts_setup.plan_setup(None, self.home / "config.toml", home=self.home, environment={}, project_root=self.home)
            self.assertFalse((self.home / ".cardine/worktrees").exists())
            self.assertEqual(self.rules.read_bytes().decode(), text)

    def test_foreign_broad_allow_warning_names_original_line(self):
        text = '# foreign\nprefix_rule(pattern=["cardine"], decision="allow")\n' + owner_hosts_codex.CODEX_USER_RULES + 'prefix_rule(pattern = [\'git\', \'push\'], decision = \'allow\')\n'
        self.write(text)
        warnings = owner_hosts_codex.plan_codex_user_rules(self.rules).warnings
        self.assertEqual(len(warnings), 2)
        self.assertIn(f"{self.rules}:2:", warnings[0])
        self.assertIn(f"{self.rules}:{len(text.splitlines())}:", warnings[1])
        self.assertEqual(self.rules.read_bytes().decode(), text)

    def test_apply_refuses_changed_foreign_rules(self):
        plan = owner_hosts_codex.plan_codex_user_rules(self.rules)
        self.write("# appeared later\n")
        with self.assertRaisesRegex(shared_errors.CardineError, "changed since planning"):
            owner_hosts_codex.apply_codex_user_rules(plan)
        self.assertEqual(self.rules.read_text(), "# appeared later\n")

    def test_multiline_warning_ignores_comments_and_prompt_rules(self):
        self.write('# prefix_rule(pattern=["cardine"], decision="allow")\n'
                   'prefix_rule(\n decision="allow",\n pattern=["git", "push"],\n)\n'
                   'prefix_rule(pattern=["cardine"], decision="prompt")\n')
        warnings = owner_hosts_codex.plan_codex_user_rules(self.rules).warnings
        self.assertEqual(len(warnings), 1)
        self.assertIn(f"{self.rules}:2:", warnings[0])

    def test_setup_diff_apply_and_doctor_states(self):
        config = self.home / "config.toml"
        def setup():
            return owner_hosts_setup.plan_setup(None, config, home=self.home, environment={}, framework_root=ROOT, project_root=self.home)
        def doctor():
            with mock.patch.object(cardine_cli.shutil, "which", return_value=None):
                return owner_hosts_setup.codex_doctor(self.home, config, self.home / ".cardine/worktrees", home=self.home)["user-command-policy"]
        self.assertEqual(doctor(), "missing")
        plan = setup()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            owner_hosts_setup.print_setup_plan(plan)
        self.assertIn("+# CARDINE:BEGIN codex-user-rules v1", output.getvalue())
        self.assertFalse(self.rules.exists())
        owner_hosts_setup.apply_setup(plan)
        self.assertEqual(doctor(), "ready")
        self.write(owner_hosts_codex.CODEX_USER_RULES.replace('"git", "fetch"', '"git", "old"'))
        self.assertEqual(doctor(), "stale")
        changed = self.rules.read_bytes()
        with self.assertRaisesRegex(shared_errors.CardineError, "has changed"):
            setup()
        self.assertEqual(self.rules.read_bytes(), changed)

    def test_legacy_rules_migrate_only_the_exact_owned_block(self):
        legacy = self.rules.with_name("default.rules")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        foreign = "# before\r\n"
        suffix = "# after\r\n"
        legacy.write_bytes((foreign + owner_hosts_codex.LEGACY_CODEX_USER_RULES + suffix).encode())
        original = legacy.read_bytes()
        plan = owner_hosts_codex.plan_codex_user_rules(self.rules)
        self.assertEqual(legacy.read_bytes(), original)
        self.assertEqual(owner_hosts_codex.plan_codex_user_rules(self.rules), plan)
        owner_hosts_codex.apply_codex_user_rules(plan)
        self.assertEqual(legacy.read_bytes(), (foreign + suffix).encode())
        self.assertEqual(self.rules.read_text(), owner_hosts_codex.CODEX_USER_RULES)
        self.rules.unlink()
        modified = original.replace(b'"git", "fetch"', b'"git", "other"')
        legacy.write_bytes(modified)
        plan = owner_hosts_codex.plan_codex_user_rules(self.rules)
        self.assertTrue(plan.warnings)
        owner_hosts_codex.apply_codex_user_rules(plan)
        self.assertEqual(legacy.read_bytes(), modified)

    def test_legacy_rules_are_kept_and_reported_while_the_legacy_tool_is_installed(self):
        legacy = self.rules.with_name("default.rules")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        original = ("# before\r\n" + owner_hosts_codex.LEGACY_CODEX_USER_RULES + "# after\r\n").encode()
        legacy.write_bytes(original)
        plan = owner_hosts_codex.plan_codex_user_rules(self.rules, legacy_tool_installed=True)
        self.assertIsNone(plan.legacy_proposed)
        self.assertEqual([w for w in plan.warnings if "kept byte-identical" in w and str(legacy) in w], list(plan.warnings))
        self.assertTrue(owner_hosts_codex.apply_codex_user_rules(plan))
        self.assertEqual(legacy.read_bytes(), original)
        self.assertEqual(self.rules.read_text(), owner_hosts_codex.CODEX_USER_RULES)
        again = owner_hosts_codex.plan_codex_user_rules(self.rules, legacy_tool_installed=True)
        self.assertFalse(owner_hosts_codex.apply_codex_user_rules(again))
        self.assertEqual(legacy.read_bytes(), original)

    def test_setup_refuses_symlinked_codex_directory_before_host_writes(self):
        outside = self.home / 'outside'
        outside.mkdir()
        (self.home / '.codex').symlink_to(outside, target_is_directory=True)
        config = self.home / 'config.toml'
        plan = owner_hosts_setup.plan_setup(None, config, home=self.home, environment={},
                                            framework_root=ROOT, project_root=self.home)
        with self.assertRaisesRegex(shared_errors.CardineError, "symlink"):
            owner_hosts_setup.apply_setup(plan)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(config.exists())
        self.assertFalse((self.home / '.cardine').exists())

    def test_setup_migration_replays_all_durable_boundaries(self):
        script = r"""
import os, sys, tempfile
from pathlib import Path
from cardine.hosts import setup
from cardine.lifecycle import receipts
home, seam, framework, temp = map(Path, sys.argv[1:])
tempfile.tempdir = str(temp)
def boundary(name):
    if name == str(seam):
        os._exit(93)
receipts.boundary = boundary
plan = setup.plan_setup(home / 'worktrees', home / '.codex/config.toml', home=home,
                        environment={'HOME': str(home)}, framework_root=framework, project_root=home / 'project')
setup.apply_setup(plan)
"""
        base = self.home / 'cases'
        base.mkdir()
        receipt_dir = self.home / 'receipts'
        receipt_dir.mkdir()
        def fixture(name):
            home = base / name
            (home / '.codex/rules').mkdir(parents=True)
            (home / 'project').mkdir()
            root = home / 'worktrees'
            block = (owner_hosts_codex._codex_managed_block(root)
                     .replace('CARDINE:', 'MERIDIAN:')
                     .replace('cardine-worktrees', 'meridian-worktrees')
                     .replace('Cardine-managed', 'Meridian-managed'))
            (home / '.codex/config.toml').write_text('# foreign\nmodel = "test"\n\n' + block + '\n')
            (home / '.codex/rules/default.rules').write_text('# foreign\n' + owner_hosts_codex.LEGACY_CODEX_USER_RULES)
            return home
        def run(home, seam=''):
            return subprocess.run([sys.executable, '-c', script, str(home), seam, str(ROOT), str(receipt_dir)],
                                  env={**os.environ, 'HOME': str(home), 'PYTHONPATH': str(ROOT / 'src')},
                                  capture_output=True, text=True)
        def tree(home):
            return {p.relative_to(home).as_posix(): p.read_bytes().replace(str(home).encode(), b'<home>')
                    for p in home.rglob('*') if p.is_file() and not p.is_symlink()}
        reference = fixture('reference')
        done = run(reference)
        self.assertEqual(done.returncode, 0, done.stderr)
        expected = tree(reference)
        for effect in ('backup:codex-config', 'file:codex-config', 'file:codex-rules',
                       'file:codex-legacy-rules', 'setup_result'):
            for when in ('before', 'after'):
                seam = f'{when}_{effect}'
                with self.subTest(seam=seam):
                    home = fixture(seam.replace(':', '-'))
                    interrupted = run(home, seam)
                    self.assertEqual(interrupted.returncode, 93, interrupted.stderr)
                    replay = run(home)
                    self.assertEqual(replay.returncode, 0, replay.stderr)
                    self.assertEqual(tree(home), expected)
                    self.assertEqual(run(home).returncode, 0)
                    self.assertEqual(tree(home), expected)

    @unittest.skipUnless(shutil.which("codex"), "codex_user_rules_decisions: codex binary unavailable")
    def test_codex_user_rules_decisions(self):
        self.write(owner_hosts_codex.CODEX_USER_RULES)
        cases = [
            (["git", "push", "origin", "task-221"], "allow"),
            (["git", "push", "other", "main"], None),
            (["git", "push", "origin", "main", "--force"], "allow"),
            (["git", "fetch", "origin"], "allow"),
            (["git", "write-tree"], "allow"),
            (["git", "restore", "--staged", "x"], "allow"),
            (["git", "restore", "x"], None),
            (["git", "rm", "x"], "allow"),
            (["git", "rm", "-f", "x"], "prompt"),
            (["git", "rm", "--force", "x"], "prompt"),
            (["gh", "api", "repos/x"], None),
            (["gh", "issue", "close", "1"], None),
            (["cardine", "worktree", "advance", "221"], "allow"),
        ]
        for flag in ("--force", "-f", "--force-with-lease", "--delete", "-d", "--mirror"):
            for prefix in (["git", "push"], ["git", "push", "origin"]):
                cases.append((prefix + [flag, "main"], "forbidden"))
        for command in (["cardine", "setup"], ["cardine", "upgrade"], ["cardine", "codex", "configure"]):
            cases.extend([(command + ["--check"], "allow"), (command + ["--apply"], None)])
        for group, verbs in (("release", ["list", "view"]), ("run", ["list", "view", "watch"]), ("pr", ["list", "view", "checks", "diff"]), ("issue", ["list", "view"]), ("repo", ["view"]), ("auth", ["status"])):
            cases.extend((["gh", group, verb], "allow") for verb in verbs)
        for command, decision in cases:
            with self.subTest(command=command):
                result = subprocess.run(["codex", "execpolicy", "check", "--rules", str(self.rules), "--", *command], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout).get("decision"), decision)
