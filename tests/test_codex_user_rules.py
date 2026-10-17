"""User-level setup ownership and real Codex decision coverage."""

import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian


class CodexUserRulesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.rules = self.home / ".codex/rules/default.rules"

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
                plan = meridian.plan_codex_user_rules(self.rules)
                self.assertEqual(plan.status, "missing")
                self.assertEqual(self.rules.read_bytes().decode() if self.rules.exists() else "", foreign)
                self.assertTrue(meridian.apply_codex_user_rules(plan))
                self.assertTrue(self.rules.read_bytes().startswith(foreign.encode()))
                ready = meridian.plan_codex_user_rules(self.rules)
                self.assertEqual(ready.status, "ready")
                self.assertFalse(meridian.apply_codex_user_rules(ready))

    def test_stale_block_replacement_preserves_both_sides(self):
        before, after = "# foreign before\r\n", "# foreign after\r\n"
        self.write(before + "# MERIDIAN:BEGIN codex-user-rules v0\n# old\n# MERIDIAN:END codex-user-rules\n" + after)
        original = self.rules.read_bytes()
        plan = meridian.plan_codex_user_rules(self.rules)
        self.assertEqual(plan.status, "stale")
        self.assertEqual(self.rules.read_bytes(), original)
        meridian.apply_codex_user_rules(plan)
        self.assertEqual(self.rules.read_bytes().decode(), before + meridian.CODEX_USER_RULES + after)

    def test_damaged_markers_stop_before_any_setup_mutation(self):
        for text in (
            "# MERIDIAN:BEGIN codex-user-rules v1\n",
            "# MERIDIAN:END codex-user-rules\n",
            meridian.CODEX_USER_RULES * 2,
            "# MERIDIAN:END codex-user-rules\n# MERIDIAN:BEGIN codex-user-rules v1\n",
            "# MERIDIAN:BEGIN codex-user-rules broken\n# MERIDIAN:END codex-user-rules\n",
        ):
            self.write(text)
            with self.assertRaisesRegex(meridian.MeridianStop, "BLOCKED COMMAND_REFUSED.*damaged"):
                meridian.plan_setup(None, self.home / "config.toml", home=self.home, environment={}, project_root=self.home)
            self.assertFalse((self.home / ".meridian/worktrees").exists())
            self.assertEqual(self.rules.read_bytes().decode(), text)

    def test_foreign_broad_allow_warning_names_original_line(self):
        text = '# foreign\nprefix_rule(pattern=["meridian"], decision="allow")\n' + meridian.CODEX_USER_RULES + 'prefix_rule(pattern = [\'git\', \'push\'], decision = \'allow\')\n'
        self.write(text)
        warnings = meridian.plan_codex_user_rules(self.rules).warnings
        self.assertEqual(len(warnings), 2)
        self.assertIn(f"{self.rules}:2:", warnings[0])
        self.assertIn(f"{self.rules}:{len(text.splitlines())}:", warnings[1])
        self.assertEqual(self.rules.read_bytes().decode(), text)

    def test_apply_refuses_changed_foreign_rules(self):
        plan = meridian.plan_codex_user_rules(self.rules)
        self.write("# appeared later\n")
        with self.assertRaisesRegex(meridian.MeridianError, "changed since planning"):
            meridian.apply_codex_user_rules(plan)
        self.assertEqual(self.rules.read_text(), "# appeared later\n")

    def test_multiline_warning_ignores_comments_and_prompt_rules(self):
        self.write('# prefix_rule(pattern=["meridian"], decision="allow")\n'
                   'prefix_rule(\n decision="allow",\n pattern=["git", "push"],\n)\n'
                   'prefix_rule(pattern=["meridian"], decision="prompt")\n')
        warnings = meridian.plan_codex_user_rules(self.rules).warnings
        self.assertEqual(len(warnings), 1)
        self.assertIn(f"{self.rules}:2:", warnings[0])

    def test_setup_diff_apply_and_doctor_states(self):
        config = self.home / "config.toml"
        def setup():
            return meridian.plan_setup(None, config, home=self.home, environment={}, framework_root=ROOT, project_root=self.home)
        def doctor():
            with mock.patch.object(meridian.shutil, "which", return_value=None):
                return meridian.codex_doctor(self.home, config, self.home / ".meridian/worktrees", home=self.home)["user-command-policy"]
        self.assertEqual(doctor(), "missing")
        plan = setup()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            meridian.print_setup_plan(plan)
        self.assertIn("+# MERIDIAN:BEGIN codex-user-rules v1", output.getvalue())
        self.assertFalse(self.rules.exists())
        meridian.apply_setup(plan)
        self.assertEqual(doctor(), "ready")
        self.write(meridian.CODEX_USER_RULES.replace('"git", "fetch"', '"git", "old"'))
        self.assertEqual(doctor(), "stale")
        stale = setup()
        with contextlib.redirect_stdout(output):
            meridian.print_setup_plan(stale)
        self.assertIn('-prefix_rule(pattern=["git", "old"]', output.getvalue())
        meridian.apply_setup(stale)
        self.assertEqual(doctor(), "ready")

    @unittest.skipUnless(shutil.which("codex"), "codex_user_rules_decisions: codex binary unavailable")
    def test_codex_user_rules_decisions(self):
        self.write(meridian.CODEX_USER_RULES)
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
            (["meridian", "worktree", "advance", "221"], "allow"),
        ]
        for flag in ("--force", "-f", "--force-with-lease", "--delete", "-d", "--mirror"):
            for prefix in (["git", "push"], ["git", "push", "origin"]):
                cases.append((prefix + [flag, "main"], "forbidden"))
        for command in (["meridian", "setup"], ["meridian", "upgrade"], ["meridian", "codex", "configure"]):
            cases.extend([(command + ["--check"], "allow"), (command + ["--apply"], None)])
        for group, verbs in (("release", ["list", "view"]), ("run", ["list", "view", "watch"]), ("pr", ["list", "view", "checks", "diff"]), ("issue", ["list", "view"]), ("repo", ["view"]), ("auth", ["status"])):
            cases.extend((["gh", group, verb], "allow") for verb in verbs)
        for command, decision in cases:
            with self.subTest(command=command):
                result = subprocess.run(["codex", "execpolicy", "check", "--rules", str(self.rules), "--", *command], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout).get("decision"), decision)
