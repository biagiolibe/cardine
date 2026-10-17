"""Execute the published walkthrough and its checked excerpts in order."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import unittest

import test_meridian_cli as lifecycle

ROOT = lifecycle.ROOT


class LeanWalkthroughTest(unittest.TestCase):
    def setUp(self):
        self.fixture = lifecycle.WorktreeLifecycleCliTest()
        self.fixture.setUp(seed=False)
        self.addCleanup(self.fixture.tearDown)
        self.fixture.create_bare_origin()
        self.home = self.fixture.root / "home"
        self.home.mkdir()

    def run_document(self, document):
        blocks = re.findall(r"^```([^\n]*)\n(.*?)^```\s*$", document, re.M | re.S)
        self.assertTrue(blocks, "walkthrough must contain executable blocks")
        script = ["set -euo pipefail"]
        for kind, body in blocks:
            if kind == "bash":
                script.append(body)
            else:
                self.assertTrue(kind.startswith("text checked="), kind)
                path = kind.removeprefix("text checked=")
                excerpt = body.rstrip("\n")
                check = (
                    "import os; from pathlib import Path; "
                    f"p = Path(os.environ['PRIMARY']) / {path!r}; "
                    f"assert {excerpt!r} in p.read_text(), 'Checked excerpt mismatch: ' + str(p)"
                )
                script.append("python3 -c " + shlex.quote(check))
        return subprocess.run(
            ["bash", "-c", "\n".join(script)], cwd=self.fixture.project,
            env={**os.environ, "HOME": str(self.home), "MERIDIAN_ROOT": str(ROOT),
                 "MERIDIAN_WORKTREE_ROOT": str(self.fixture.worktree_root),
                 "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
            text=True, capture_output=True, timeout=120,
        )

    def test_walkthrough_closes_and_pushes_the_first_task(self):
        document = (ROOT / "docs/examples/LEAN_DELIVERY_WALKTHROUGH.md").read_text()
        result = self.run_document(document)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for action in ("run-candidate-validation", "push", "none"):
            self.assertIn(f'"action_required": "{action}"', result.stdout)
        project = self.fixture.project
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=project, text=True).strip()
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertEqual(git("rev-parse", "HEAD"), git("rev-parse", "origin/main"))
        self.assertEqual(git("branch", "--list", "task-001"), "")
        self.assertEqual(git("worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertTrue((project / "tasks/done/001-purpose.md").is_file())

    def test_nonzero_command_stops_execution(self):
        result = self.run_document("```bash\nfalse\nprintf should-not-run\n```\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("should-not-run", result.stdout)

    def test_stale_checked_excerpt_fails(self):
        result = self.run_document(
            "```bash\nexport PRIMARY=\"$PWD\"\nprintf actual > example.txt\n```\n"
            "```text checked=example.txt\nstale\n```\n"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Checked excerpt mismatch", result.stderr)
