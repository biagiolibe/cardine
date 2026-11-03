"""A fresh task from `task new` starts and `run` continues without a hand edit."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CARDINE = ROOT / "bin" / "cardine"

RECORD = """# Task 001 — Add the sentence

> **ID**: `001`
Priority: P1
Estimate: 15m

## Objective

Add the sentence to README.md.

## Acceptance Criteria

- [ ] README.md contains the sentence.

## Relevant Files

- README.md — introduction.

## Out of scope

Everything else.

## Expected code surface

- `README.md`

## Validation

- `whitespace`: `git diff --check`

## Dependencies

None.
"""


class FreshTaskStartTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.home = base / "home"
        self.home.mkdir()
        self.project = base / "project"
        self.project.mkdir()
        self.environment = {
            **os.environ, "HOME": str(self.home), "CARDINE_ROOT": str(ROOT),
            "CARDINE_WORKTREE_ROOT": str(base / "worktrees"),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Cardine Test", "GIT_AUTHOR_EMAIL": "cardine@example.invalid",
            "GIT_COMMITTER_NAME": "Cardine Test", "GIT_COMMITTER_EMAIL": "cardine@example.invalid",
        }
        self.git("init", "-q", "-b", "main")
        shutil.copytree(ROOT / "templates" / "single", self.project, dirs_exist_ok=True)
        for path in self.project.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                text = path.read_text(encoding="utf-8")
                for old, new in (("[Project Name]", "Fresh"), ("[Data]", "2026-11-03"),
                                 ("[Date]", "2026-11-03"), ("[Conversation language]", "English")):
                    text = text.replace(old, new)
                path.write_text(text, encoding="utf-8")
        (self.project / "tasks" / "done").mkdir(exist_ok=True)
        (self.project / "README.md").write_text("# Fresh\n", encoding="utf-8")
        self.cardine("lock", "--project", ".", "--mode", "single")
        (self.project / ".cardine" / "project.json").write_text(json.dumps({
            "version": 1, "preset": "lean", "taskIdentity": {"mode": "opaque"},
            "validation": {"commands": {"whitespace": "git diff --check"}, "baseline": ["whitespace"],
                           "candidate": {name: [] for name in ("REUSE", "BOUNDED", "FULL")}},
        }) + "\n", encoding="utf-8")
        (self.project / "TECH_DESIGN.md").write_text("# Technical design\n\nMarkdown.\n", encoding="utf-8")
        record = base / "record.md"
        record.write_text(RECORD, encoding="utf-8")
        self.cardine("task", "new", "001", "--record", str(record), "--project", ".")
        self.cardine("status", "--write", "--project", ".")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "Initialize the project and task 001")

    def git(self, *arguments, cwd=None):
        return subprocess.run(["git", *arguments], cwd=cwd or self.project, env=self.environment,
                              text=True, capture_output=True, check=True)

    def cardine(self, *arguments, cwd=None, check=True):
        result = subprocess.run([str(CARDINE), *arguments], cwd=cwd or self.project, env=self.environment,
                                text=True, capture_output=True, timeout=120)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_reconciled_record_starts_and_run_continues(self):
        prepared = json.loads(self.cardine("worktree", "prepare", "001", "--project", str(self.project),
                                           "--format", "json").stdout)
        worktree = Path(prepared["worktree"])
        refused = self.cardine("execution", "start", "001", "--project", ".", cwd=worktree, check=False)
        self.assertIn("EXECUTION_CONTRACT_UNRESOLVED", refused.stdout + refused.stderr)
        self.assertNotIn('"started": true', refused.stdout)

        self.cardine("execution", "reconcile", "001", "--apply", "--project", ".", cwd=worktree)
        self.assertIn("- Profile revision:", (worktree / "tasks" / "001.md").read_text(encoding="utf-8"))
        self.git("add", "-A", cwd=worktree)
        self.git("commit", "-q", "-m", "Reconcile the execution contract", cwd=worktree)

        started = self.cardine("execution", "start", "001", "--project", ".", cwd=worktree)
        self.assertTrue(json.loads(started.stdout)["started"])

        run = self.cardine("run", "001", "--project", ".", cwd=worktree, check=False)
        self.assertNotIn("changed or missing receipt artifact", run.stdout + run.stderr)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(run.stdout)["diagnostics"], [])

    def test_reconcile_is_idempotent_after_the_receipt_covers_it(self):
        prepared = json.loads(self.cardine("worktree", "prepare", "001", "--project", str(self.project),
                                           "--format", "json").stdout)
        worktree = Path(prepared["worktree"])
        self.cardine("execution", "reconcile", "001", "--apply", "--project", ".", cwd=worktree)
        again = self.cardine("execution", "reconcile", "001", "--apply", "--project", ".", cwd=worktree)
        self.assertIn("already current", again.stdout)

    def test_interrupted_reconcile_converges_on_rerun(self):
        prepared = json.loads(self.cardine("worktree", "prepare", "001", "--project", str(self.project),
                                           "--format", "json").stdout)
        worktree = Path(prepared["worktree"])
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from pathlib import Path; from cardine.lifecycle import receipts;"
            "from cardine.tasks.preflight import reconcile_execution_contract as r;"
            "receipts.boundary = lambda name=None: (_ for _ in ()).throw(SystemExit(7)) if name == 'after_intent' else None;"
            "r(Path(sys.argv[2]).resolve(), '001', True)"
        )
        killed = subprocess.run([sys.executable, "-c", script, str(ROOT / "src"), str(worktree)], cwd=worktree,
                                env=self.environment, text=True, capture_output=True)
        self.assertEqual(killed.returncode, 7, killed.stdout + killed.stderr)
        self.cardine("execution", "reconcile", "001", "--apply", "--project", ".", cwd=worktree)
        self.git("add", "-A", cwd=worktree)
        self.git("commit", "-q", "-m", "Reconcile the execution contract", cwd=worktree)
        self.cardine("execution", "start", "001", "--project", ".", cwd=worktree)
        run = self.cardine("run", "001", "--project", ".", cwd=worktree, check=False)
        self.assertEqual(json.loads(run.stdout)["diagnostics"], [], run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
