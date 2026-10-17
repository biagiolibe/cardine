"""Decision-table and structural tests for Meridian's Codex rules template."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "templates/workflows/governed-sdd/.codex/rules/meridian.rules"
LEAN_RULES = ROOT / "templates/workflows/lean-delivery/.codex/rules/meridian.rules"
PROJECT_RULES = ROOT / ".codex/rules/meridian.rules"
PREFIX_RULE = re.compile(
    r'^prefix_rule\(pattern=\[[^\n]+\], decision="(allow|prompt|forbidden)"\)$'
)
sys.path.insert(0, str(ROOT / "scripts"))
import meridian  # noqa: E402


class CodexRulesTemplateTest(unittest.TestCase):
    def test_rules_are_managed_for_both_workflows(self) -> None:
        governed = {
            item.target
            for item in meridian.managed_files(ROOT, "governed-sdd")
        }
        lean = {item.target for item in meridian.managed_files(ROOT, "lean-delivery")}
        self.assertIn(Path(".codex/rules/meridian.rules"), governed)
        self.assertIn(Path(".codex/rules/meridian.rules"), lean)

    def test_prefix_rules_are_single_line_and_well_formed(self) -> None:
        for path in (RULES, LEAN_RULES, PROJECT_RULES):
            lines = path.read_text(encoding="utf-8").splitlines()
            rules = [line for line in lines if line.startswith("prefix_rule(")]
            self.assertGreaterEqual(len(rules), 9)
            for line in rules:
                self.assertRegex(line, PREFIX_RULE)
                self.assertNotIn("\n", line)

    def test_only_origin_main_is_allowlisted_for_pushes(self) -> None:
        exact = 'prefix_rule(pattern=["git", "push", "origin", "main"], decision="allow")'
        broad = 'prefix_rule(pattern=["git", "push"], decision="allow")'
        for path in (RULES, LEAN_RULES, PROJECT_RULES):
            text = path.read_text(encoding="utf-8")
            self.assertIn(exact, text)
            self.assertNotIn(broad, text)

    def test_closure_rule_block_is_identical_in_every_shipped_file(self) -> None:
        pattern = re.compile(r"\n# Unattended-closure additions.*?\[\"ls\", [^\n]*\n", re.DOTALL)
        blocks = []
        for path in (RULES, LEAN_RULES, PROJECT_RULES):
            match = pattern.search(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(match, path)
            blocks.append(match.group(0))
        self.assertEqual(len(set(blocks)), 1)
        block = blocks[0]
        for line in (
            'prefix_rule(pattern=["meridian", "worktree", ["evidence", "closure-status", "advance"]], decision="allow")',
            'prefix_rule(pattern=["git", "mv"], decision="allow")',
            'prefix_rule(pattern=["git", "mv", ["-f", "--force"]], decision="prompt")',
            'prefix_rule(pattern=["python3", "scripts/check_repository.py"], decision="allow")',
            'prefix_rule(pattern=["python3", "-m", "unittest", "discover", "-s", "tests"], decision="allow")',
        ):
            self.assertIn(line, block)
        for unsafe in ('["sed"', '["rg"', '["find"', '["mv"'):
            self.assertNotIn(unsafe, block.replace("# ", ""))
        # New rules sit before the unchanged restrictive block, never at end of file.
        for path in (RULES, LEAN_RULES, PROJECT_RULES):
            text = path.read_text(encoding="utf-8")
            self.assertLess(text.index("Unattended-closure additions"), text.index('decision="forbidden"'))
            self.assertTrue(text.rstrip().endswith('decision="forbidden")'))

    @unittest.skipUnless(shutil.which("codex"), "codex is not on PATH; cannot evaluate execpolicy decisions")
    def test_closure_decision_table_in_every_shipped_file(self) -> None:
        cases = [
            (["meridian", "worktree", "evidence", "TASK-1", "--format", "json"], "allow"),
            (["meridian", "worktree", "closure-status", "TASK-1", "--format", "json"], "allow"),
            (["meridian", "worktree", "advance", "TASK-1", "--format", "json"], "allow"),
            (["git", "mv", "tasks/1.md", "tasks/done/1.md"], "allow"),
            (["git", "mv", "-f", "tasks/1.md", "tasks/done/1.md"], "prompt"),
            (["git", "mv", "--force", "a", "b"], "prompt"),
            (["python3", "scripts/check_repository.py"], "allow"),
            (["python3", "-m", "unittest", "discover", "-s", "tests", "-q"], "allow"),
            (["set", "-o", "pipefail"], "allow"),
            (["ls", "tasks"], "allow"),
            (["cat", "tasks/QUEUE.md"], "allow"),
            (["tail", "-n", "40"], "allow"),
            (["grep", "-n", "x", "tasks/QUEUE.md"], "allow"),
            (["sed", "-i", "s/a/b/", "f"], None),
            (["sed", "-n", "1,5p", "f"], None),
            (["rg", "--pre", "cat", "x"], None),
            (["find", ".", "-exec", "rm", "{}", ";"], None),
            (["find", ".", "-delete"], None),
            (["mv", "a", "b"], None),
            (["git", "worktree", "add", "/tmp/x", "main"], "prompt"),
            (["git", "branch", "-D", "x"], "prompt"),
            (["git", "reset", "--hard"], "forbidden"),
            (["git", "push", "--force", "origin", "main"], "forbidden"),
        ]
        for path in (RULES, LEAN_RULES, PROJECT_RULES):
            for command, expected in cases:
                with self.subTest(rules=path.parts[-4], command=command):
                    result = subprocess.run(
                        ["codex", "execpolicy", "check", "--rules", str(path), "--", *command],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout).get("decision"), expected)

    @unittest.skipUnless(shutil.which("codex"), "codex is not on PATH; cannot evaluate execpolicy decisions")
    def test_decision_table_with_codex_execpolicy(self) -> None:
        # Each row is an evidence-table command and its expected final policy.
        # None means an empty matchedRules array: Codex uses its normal prompt.
        cases = [
            (["git", "switch", "m30-present-001"], "allow"),
            (["git", "switch", "-c", "m30-verify"], "allow"),
            (["git", "rev-parse", "main"], "allow"),
            (["git", "rev-parse", "--short", "HEAD"], "allow"),
            (["git", "merge-base", "--is-ancestor", "main", "x"], "allow"),
            (["git", "merge", "--ff-only", "x"], "allow"),
            (["git", "merge", "--no-ff", "x"], None),
            (["git", "commit", "-m", "x"], "allow"),
            (["git", "commit", "--author=override", "-m", "y"], None),
            (["git", "commit", "--amend", "-m", "x"], None),
            (["git", "push", "-u", "origin", "x"], None),
            (["git", "push", "origin", "main"], "allow"),
            (["git", "push", "origin", "feature"], None),
            (["git", "push", "--tags"], None),
            (["git", "push", "--force", "origin", "main"], "forbidden"),
            (["git", "push", "-f", "origin", "main"], "forbidden"),
            (["git", "push", "--force-with-lease", "origin", "main"], "forbidden"),
            (["git", "push", "--delete", "origin", "old"], "forbidden"),
            (["git", "push", "--mirror", "origin"], "forbidden"),
            (["git", "branch", "-d", "x"], "allow"),
            (["git", "branch", "--show-current"], "allow"),
            (["git", "branch", "-D", "x"], "prompt"),
            (["git", "branch", "--delete", "x"], "prompt"),
            (["git", "branch", "--force", "x"], "prompt"),
            (["meridian", "execution", "validate", "TASK-040"], "allow"),
            (["meridian", "context", "authority", "TASK-040"], "allow"),
            (["meridian", "execution", "reconcile"], None),
            (["meridian", "upgrade", "--project", "."], None),
            (["meridian", "worktree", "path", "TASK-056", "--worktree-root", "/tmp/root"], "allow"),
            (["meridian", "worktree", "prepare", "TASK-056", "--worktree-root", "/tmp/root", "--format", "json"], "allow"),
            (["meridian", "worktree", "check", "TASK-056", "--worktree-root", "/tmp/root", "--format", "json"], "allow"),
            (["meridian", "worktree", "integrate", "stage", "TASK-056", "--worktree-root", "/tmp/root", "--evidence", "handoff.json", "--format", "json"], "allow"),
            (["meridian", "worktree", "integrate", "finalize", "TASK-056", "--evidence", "candidate.json", "--format", "json"], "allow"),
            (["meridian", "worktree", "integrate", "abort", "TASK-056", "--format", "json"], "allow"),
            (["meridian", "worktree", "cleanup", "TASK-056", "--worktree-root", "/tmp/root", "--format", "json"], "allow"),
            (["meridian", "worktree", "recover", "TASK-056"], None),
            (["meridian", "worktree"], None),
            (["git", "worktree", "list", "--porcelain"], "allow"),
            (["git", "worktree", "add", "/tmp/x", "main"], "prompt"),
            (["git", "rebase", "main"], "forbidden"),
            (["git", "reset", "--hard", "HEAD~1"], "forbidden"),
            (["git", "cherry-pick", "abc"], "forbidden"),
            (["git", "fetch", "origin"], None),
            (["git", "-C", "/tmp/project", "status"], None),
        ]
        for command, expected in cases:
            with self.subTest(command=command):
                result = subprocess.run(
                    ["codex", "execpolicy", "check", "--rules", str(RULES), "--", *command],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                actual = json.loads(result.stdout).get("decision")
                self.assertEqual(actual, expected)

    @unittest.skipUnless(shutil.which("codex"), "codex is not on PATH; cannot evaluate execpolicy decisions")
    def test_broad_prompt_overrides_the_narrow_push_allow(self) -> None:
        """Observed with Codex CLI: restrictive matching ranks prompt above allow."""
        with tempfile.TemporaryDirectory() as temporary:
            rules = Path(temporary) / "meridian.rules"
            rules.write_text(
                RULES.read_text(encoding="utf-8")
                + '\nprefix_rule(pattern=["git", "push"], decision="prompt")\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                ["codex", "execpolicy", "check", "--rules", str(rules), "--", "git", "push", "origin", "main"],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout).get("decision"), "prompt")


if __name__ == "__main__":
    unittest.main()
