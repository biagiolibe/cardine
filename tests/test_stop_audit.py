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
import cardine_cli  # noqa: E402
from cardine.hosts import stop_audit
from cardine.shared import journal as owner_shared_journal
from cardine.shared import flow as owner_shared_flow

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


class StopAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name).resolve()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.project)], check=True)
        (self.project / "PROJECT_WORKFLOW.md").write_text("workflow\n", encoding="utf-8")
        self.journal = self.project / ".git" / owner_shared_journal.JOURNAL_NAME

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

    def test_non_cardine_directory_and_missing_journal_do_nothing(self) -> None:
        self.assertEqual(self.run_audit("BLOCKED WRONG_WORKTREE"), [])
        self.assertFalse(self.journal.exists())
        with tempfile.TemporaryDirectory() as other:
            self.assertEqual(stop_audit.audit({"cwd": other, "last_assistant_message": "BLOCKED WRONG_WORKTREE"}, NOW), [])

    def test_malformed_input_exits_zero(self) -> None:
        for raw in ("not json", "[]", '{"cwd": 3}', ""):
            with mock.patch("sys.stdin", io.StringIO(raw)):
                self.assertEqual(stop_audit.stop_audit_main(), 0)

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
        report = owner_shared_flow.flow_report(self.project, None, NOW)
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
                self.assertEqual(stop_audit.stop_audit_main("codex"), 0)
        self.assertEqual(len(self.journal.read_text().splitlines()), 1)

    def test_cli_host_option_defaults_to_claude_and_rejects_others(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        command = [sys.executable, str(ROOT / "scripts" / "cardine_cli.py"), "hook", "stop-audit"]
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
        report = owner_shared_flow.flow_report(self.project, None, NOW)
        self.assertEqual(report["unbacked_blocks"], 3)
        self.assertEqual(report["blocks_by_host"], {"claude": {"unbacked": 2, "declared": 1}, "codex": {"unbacked": 1, "declared": 0}})
        text = owner_shared_flow.format_flow_report(report)
        self.assertIn("Unbacked stop reports: claude=2, codex=1", text)
        self.assertIn("Declared stop reports: claude=1, codex=0", text)

    def snapshot(self) -> tuple[bytes, int]:
        return self.journal.read_bytes(), self.journal.stat().st_mtime_ns

    def test_duplicate_invocation_records_one_line_per_event(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        payload = self.codex_input("BLOCKED WRONG_WORKTREE\nBLOCKED ACCEPTANCE_UNMET")
        first = stop_audit.audit(payload, NOW, host="codex")
        before = self.snapshot()
        self.assertEqual(len(first), 2)
        self.assertEqual(stop_audit.audit(payload, NOW, host="codex"), [])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.journal.read_text().splitlines()), 3)
        again = stop_audit.audit({**payload, "turn_id": "t2"}, NOW, host="codex")
        self.assertEqual(len(again), 2)
        self.assertEqual(len({line["event"] for line in first + again}), 2)

    def test_event_identity_holds_no_message_text_and_names_the_host(self) -> None:
        payload = self.codex_input("BLOCKED WRONG_WORKTREE: private reasoning")
        self.assertNotEqual(stop_audit.event_identity(payload, "codex", "m"), stop_audit.event_identity(payload, "claude", "m"))
        self.assertNotIn("private", stop_audit.event_identity(payload, "codex", "private reasoning"))

    def test_claude_transcript_event_records_once_and_a_new_entry_records_again(self) -> None:
        transcript = self.project / "t.jsonl"
        entry = {"type": "assistant", "uuid": "u1", "timestamp": "2026-10-05T10:05:00.000Z", "message": {"content": [{"type": "text", "text": "BLOCKED WRONG_WORKTREE"}]}}
        transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        self.seed(self.blocked("PRIMARY_DIRTY"))
        payload = {"cwd": str(self.project), "session_id": "s", "transcript_path": str(transcript)}
        self.assertEqual(len(stop_audit.audit(payload, NOW)), 1)
        before = self.snapshot()
        self.assertEqual(stop_audit.audit(payload, NOW), [])
        self.assertEqual(self.snapshot(), before)
        transcript.write_text(json.dumps({**entry, "uuid": "u2"}) + "\n", encoding="utf-8")
        self.assertEqual(len(stop_audit.audit(payload, NOW)), 1)

    def test_backed_codeless_and_non_project_payloads_leave_the_journal_untouched(self) -> None:
        self.seed(self.blocked("WRONG_WORKTREE"))
        before = self.snapshot()
        for message in ("BLOCKED WRONG_WORKTREE", "nothing to report", None):
            for host, payload in (("claude", {"cwd": str(self.project), "last_assistant_message": message}), ("codex", self.codex_input(message))):
                for _ in range(2):
                    self.assertEqual(stop_audit.audit(payload, NOW, host=host), [])
        with tempfile.TemporaryDirectory() as other:
            self.assertEqual(stop_audit.audit({"cwd": other, "last_assistant_message": "BLOCKED WRONG_WORKTREE"}, NOW), [])
        self.assertEqual(self.snapshot(), before)

    def test_audit_never_writes_task_state(self) -> None:
        self.seed(self.blocked("PRIMARY_DIRTY"))
        payload = self.codex_input("BLOCKED WRONG_WORKTREE")
        for _ in range(2):
            stop_audit.audit(payload, NOW, host="codex")
        self.assertFalse((self.project / ".meridian").exists())
        self.assertEqual(sorted(path.name for path in self.project.iterdir() if path.name != ".git"), ["PROJECT_WORKFLOW.md"])

    def test_compatibility_script_delegates_to_the_host_module(self) -> None:
        import runpy
        namespace = runpy.run_path(str(ROOT / "scripts" / "stop_audit.py"), run_name="not_main")
        self.assertIs(namespace["main"], stop_audit.stop_audit_main)
        self.assertIs(namespace["audit"], stop_audit.audit)

    def test_codex_templates_register_the_stop_hook_beside_the_read_guard(self) -> None:
        hooks = json.loads((ROOT / "templates" / "single" / ".codex" / "hooks.json").read_text())["hooks"]
        stop = hooks["Stop"][0]["hooks"][0]
        self.assertEqual(stop["command"], "cardine hook stop-audit --host codex")
        self.assertLessEqual(stop["timeout"], 5)
        self.assertEqual(hooks["PreToolUse"][0]["hooks"][0]["command"], "cardine hook read-guard --host codex")


if __name__ == "__main__":
    unittest.main()
