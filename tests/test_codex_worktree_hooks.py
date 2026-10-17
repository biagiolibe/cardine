"""Hook process regressions for linked worktrees and session shutdown (task 222)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian  # noqa: E402

CLI = ROOT / "scripts/meridian.py"


class CodexWorktreeHooksTest(unittest.TestCase):
    def run_hook(self, name: str, cwd: Path, payload: dict) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "hook", name, "--host", "codex"],
            cwd=cwd, input=json.dumps(payload), text=True, capture_output=True,
        )

    def test_non_meridian_directory_is_a_silent_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            (cwd / "large.txt").write_text("x\n" * 500)
            payload = {"cwd": directory, "tool_name": "Bash",
                       "tool_input": {"command": "cat large.txt"},
                       "last_assistant_message": "BLOCKED WRONG_WORKTREE"}
            for hook in ("read-guard", "stop-audit"):
                done = self.run_hook(hook, cwd, payload)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
            self.assertEqual([p.name for p in cwd.iterdir()], ["large.txt"])

    @unittest.skipIf(os.name == "nt", "Windows cannot unlink a process working directory")
    def test_inherited_deleted_cwd_is_a_silent_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for hook in ("read-guard", "stop-audit"):
                cwd = Path(directory) / hook
                cwd.mkdir()
                # Delete the actual process cwd, then exec the published hook entry point.
                bootstrap = (
                    "import os,sys; os.chdir(sys.argv[1]); os.rmdir(sys.argv[1]); "
                    "os.execv(sys.executable, [sys.executable, *sys.argv[2:]])"
                )
                done = subprocess.run(
                    [sys.executable, "-c", bootstrap, str(cwd), str(CLI),
                     "hook", hook, "--host", "codex"],
                    input=json.dumps({"cwd": str(cwd)}), text=True, capture_output=True,
                )
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
                self.assertFalse(cwd.exists())

    def test_primary_project_definitions_process_worktree_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            primary = Path(directory) / "primary"
            primary.mkdir()
            def git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=primary, check=True, capture_output=True)
            git("init", "-b", "main")
            git("config", "user.name", "Meridian Test")
            git("config", "user.email", "meridian@example.invalid")
            (primary / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n")
            (primary / ".codex").mkdir()
            (primary / ".codex/hooks.json").write_bytes((ROOT / ".codex/hooks.json").read_bytes())
            (primary / "large.txt").write_text("x\n" * 500)
            git("add", ".")
            git("commit", "-m", "seed hooks")
            worktree = Path(directory) / "task"
            git("worktree", "add", "-b", "task-222", str(worktree))
            journal = primary / ".git" / meridian.JOURNAL_NAME
            journal.write_text("")
            hooks = json.loads((primary / ".codex/hooks.json").read_text())["hooks"]
            payload = {"cwd": str(worktree), "tool_name": "Bash",
                       "tool_input": {"command": "cat large.txt"},
                       "last_assistant_message": "BLOCKED WRONG_WORKTREE"}
            for event, expected in (("PreToolUse", 2), ("Stop", 0)):
                command = shlex.split(hooks[event][0]["hooks"][0]["command"])
                self.assertEqual(command[0], "meridian")
                done = subprocess.run(
                    [sys.executable, str(CLI), *command[1:]], cwd=worktree,
                    input=json.dumps(payload), text=True, capture_output=True,
                )
                self.assertEqual(done.returncode, expected, done.stderr)
                if event == "PreToolUse":
                    self.assertEqual(json.loads(done.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
            written = json.loads(journal.read_text().splitlines()[-1])
            self.assertEqual((written["host"], written["result"]), ("codex", "unbacked_block"))


if __name__ == "__main__":
    unittest.main()
