"""Tests for the Stop-hook audit of unbacked BLOCKED reports (task 173)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian  # noqa: E402
import stop_audit  # noqa: E402

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


class StopAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name).resolve()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.project)], check=True)
        (self.project / "PROJECT_WORKFLOW.md").write_text("workflow\n", encoding="utf-8")
        self.journal = self.project / ".git" / meridian.JOURNAL_NAME

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def seed(self, *lines: dict) -> None:
        self.journal.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")

    def blocked(self, code: str, task: str | None = None, ts: str = "2026-10-05T11:00:00Z") -> dict:
        return {"version": 1, "ts": ts, "command": "worktree check", "task": task, "result": "blocked", "stop_code": code, "exit": 2}

    def run_audit(self, message: str, **extra: object) -> list[dict]:
        payload = {"cwd": str(self.project), "last_assistant_message": message, **extra}
        return stop_audit.audit(payload, NOW)

    def test_backed_code_is_not_recorded(self) -> None:
        self.seed(self.blocked("WRONG_WORKTREE"))
        self.assertEqual(self.run_audit("BLOCKED WRONG_WORKTREE: mismatch"), [])
        self.assertEqual(len(self.journal.read_text().splitlines()), 1)

    def test_unbacked_tool_code_is_recorded_with_code_only(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        written = self.run_audit("Stopping.\nBLOCKED WRONG_WORKTREE: my own reading of the text")
        self.assertEqual([(line["result"], line["stop_code"]) for line in written], [("unbacked_block", "WRONG_WORKTREE")])
        stored = self.journal.read_text()
        self.assertNotIn("my own reading", stored)
        self.assertEqual(json.loads(stored.splitlines()[-1])["result"], "unbacked_block")

    def test_code_older_than_the_session_window_is_unbacked(self) -> None:
        self.seed(self.blocked("WRONG_WORKTREE", ts="2026-10-01T00:00:00Z"))
        self.assertEqual(self.run_audit("BLOCKED WRONG_WORKTREE")[0]["result"], "unbacked_block")

    def test_active_task_scopes_the_backing_line(self) -> None:
        self.seed(self.blocked("WRONG_WORKTREE", task="172"))
        with mock.patch.object(stop_audit, "active_task", return_value="173"):
            written = self.run_audit("BLOCKED WRONG_WORKTREE")
        self.assertEqual([(line["result"], line["task"]) for line in written], [("unbacked_block", "173")])
        self.seed(self.blocked("WRONG_WORKTREE", task="173"))
        with mock.patch.object(stop_audit, "active_task", return_value="173"):
            self.assertEqual(self.run_audit("BLOCKED WRONG_WORKTREE"), [])

    def test_judgment_code_is_declared(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        written = self.run_audit("BLOCKED ACCEPTANCE_UNMET: criterion 3")
        self.assertEqual([line["result"] for line in written], ["declared_block"])

    def test_no_code_writes_nothing(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        self.assertEqual(self.run_audit("All done. This was not BLOCKED by anything."), [])
        self.assertEqual(len(self.journal.read_text().splitlines()), 1)

    def test_non_meridian_directory_and_missing_journal_do_nothing(self) -> None:
        self.assertEqual(self.run_audit("BLOCKED WRONG_WORKTREE"), [])
        self.assertFalse(self.journal.exists())
        with tempfile.TemporaryDirectory() as other:
            self.assertEqual(stop_audit.audit({"cwd": other, "last_assistant_message": "BLOCKED WRONG_WORKTREE"}, NOW), [])

    def test_malformed_input_exits_zero(self) -> None:
        for raw in ("not json", "[]", '{"cwd": 3}', ""):
            with mock.patch("sys.stdin", io.StringIO(raw)):
                self.assertEqual(stop_audit.main(), 0)

    def test_final_message_falls_back_to_the_transcript(self) -> None:
        transcript = self.project / "t.jsonl"
        entries = [
            {"type": "assistant", "timestamp": "2026-10-05T10:00:00.123Z", "message": {"content": [{"type": "text", "text": "BLOCKED PRIMARY_DIRTY"}]}},
            {"type": "assistant", "timestamp": "2026-10-05T10:05:00.000Z", "message": {"content": [{"type": "tool_use", "name": "Bash"}, {"type": "text", "text": "BLOCKED WRONG_WORKTREE"}]}},
        ]
        transcript.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        self.seed(self.blocked("WRONG_WORKTREE", ts="2026-10-05T09:00:00Z"))
        written = stop_audit.audit({"cwd": str(self.project), "transcript_path": str(transcript)}, NOW)
        self.assertEqual([line["stop_code"] for line in written], ["WRONG_WORKTREE"])
        self.assertEqual(written[0]["result"], "unbacked_block")

    def test_flow_report_counts_unbacked_without_inventing_a_task(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        self.run_audit("BLOCKED WRONG_WORKTREE")
        report = meridian.flow_report(self.project, None, NOW)
        self.assertEqual(report["unbacked_blocks"], 1)
        self.assertEqual(report["totals"]["stops"], 1)
        self.assertEqual(report["totals"]["tasks"], 0)

    def codex_input(self, message: object, **extra: object) -> dict:
        return {
            "cwd": str(self.project),
            "hook_event_name": "Stop",
            "session_id": "s",
            "turn_id": "t",
            "model": "m",
            "permission_mode": "default",
            "stop_hook_active": False,
            "transcript_path": None,
            "last_assistant_message": message,
            **extra,
        }

    def test_codex_input_backed_code_is_not_recorded(self) -> None:
        self.seed(self.blocked("WRONG_WORKTREE"))
        self.assertEqual(stop_audit.audit(self.codex_input("BLOCKED WRONG_WORKTREE: x"), NOW, host="codex"), [])
        self.assertEqual(len(self.journal.read_text().splitlines()), 1)

    def test_codex_input_unbacked_code_records_the_host_and_no_text(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        written = stop_audit.audit(self.codex_input("BLOCKED WRONG_WORKTREE: private reasoning"), NOW, host="codex")
        self.assertEqual([(line["result"], line["host"]) for line in written], [("unbacked_block", "codex")])
        self.assertNotIn("private reasoning", self.journal.read_text())

    def test_every_written_line_names_its_host(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        self.run_audit("BLOCKED WRONG_WORKTREE\nBLOCKED ACCEPTANCE_UNMET")
        stop_audit.audit(self.codex_input("BLOCKED WRONG_WORKTREE\nBLOCKED ACCEPTANCE_UNMET"), NOW, host="codex")
        lines = [json.loads(raw) for raw in self.journal.read_text().splitlines()[1:]]
        self.assertEqual(
            [(line["result"], line["host"]) for line in lines],
            [("unbacked_block", "claude"), ("declared_block", "claude"), ("unbacked_block", "codex"), ("declared_block", "codex")],
        )

    def test_codex_null_message_and_malformed_input_exit_zero(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        self.assertEqual(stop_audit.audit(self.codex_input(None), NOW, host="codex"), [])
        for raw in ("not json", "[]", '{"cwd": 3}', ""):
            with mock.patch("sys.stdin", io.StringIO(raw)):
                self.assertEqual(stop_audit.main("codex"), 0)
        self.assertEqual(len(self.journal.read_text().splitlines()), 1)

    def test_cli_host_option_defaults_to_claude_and_rejects_others(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        command = [sys.executable, str(ROOT / "scripts" / "meridian.py"), "hook", "stop-audit"]
        payload = json.dumps(self.codex_input("BLOCKED WRONG_WORKTREE"))
        for extra, expected in (([], "claude"), (["--host", "codex"], "codex")):
            done = subprocess.run([*command, *extra], input=payload, text=True, capture_output=True)
            self.assertEqual(done.returncode, 0)
            self.assertEqual(json.loads(self.journal.read_text().splitlines()[-1])["host"], expected)
        bad = subprocess.run([*command, "--host", "other"], input=payload, text=True, capture_output=True)
        self.assertNotEqual(bad.returncode, 0)

    def test_flow_report_totals_blocks_per_host_and_reads_old_lines_as_claude(self) -> None:
        old = {"version": 1, "ts": "2026-10-05T11:30:00Z", "command": "stop-audit", "task": None, "result": "unbacked_block", "stop_code": "WRONG_WORKTREE", "exit": 0}
        self.seed(self.blocked("PRIMARY_DIRTY"), old)
        self.run_audit("BLOCKED WRONG_WORKTREE\nBLOCKED ACCEPTANCE_UNMET")
        stop_audit.audit(self.codex_input("BLOCKED WRONG_WORKTREE"), NOW, host="codex")
        report = meridian.flow_report(self.project, None, NOW)
        self.assertEqual(report["unbacked_blocks"], 3)
        self.assertEqual(report["blocks_by_host"], {"claude": {"unbacked": 2, "declared": 1}, "codex": {"unbacked": 1, "declared": 0}})
        text = meridian.format_flow_report(report)
        self.assertIn("Unbacked stop reports: claude=2, codex=1", text)
        self.assertIn("Declared stop reports: claude=1, codex=0", text)

    def test_codex_templates_register_the_stop_hook_beside_the_read_guard(self) -> None:
        for mode in ("lean-delivery", "governed-sdd"):
            hooks = json.loads((ROOT / "templates" / "workflows" / mode / ".codex" / "hooks.json").read_text())["hooks"]
            stop = hooks["Stop"][0]["hooks"][0]
            self.assertEqual(stop["command"], "meridian hook stop-audit --host codex")
            self.assertLessEqual(stop["timeout"], 5)
            self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["command"], "meridian hook read-guard --host codex")


if __name__ == "__main__":
    unittest.main()
