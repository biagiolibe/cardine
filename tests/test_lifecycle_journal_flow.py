"""Framework CLI regression tests for lifecycle journal flow."""

from __future__ import annotations

from cardine_cli_support import CLI, ROOT
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cardine.shared import journal as owner_shared_journal
from cardine.stops import registry as stops_registry
import cardine.shared.errors as shared_errors
from cardine.shared import flow as owner_shared_flow


class LifecycleJournalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Cardine Test"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.email", "cardine@example.invalid"], cwd=self.project, check=True)
        (self.project / "tasks").mkdir()
        (self.project / "tasks/056-lifecycle.md").write_text("# Task 056\n\n> **ID**: `056`\n", encoding="utf-8")
        (self.project / "tasks/QUEUE.md").write_text(
            "| Status | ID | Title |\n|---|---|---|\n| `[ ]` | 056 | Lifecycle |\n", encoding="utf-8"
        )
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.project, check=True, capture_output=True)
        self.worktree_root = self.root / "worktrees"
        self.worktree_root.mkdir()
        self.journal = self.project / ".git" / "cardine-journal.jsonl"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def lifecycle(
        self, command: str, *extra: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        root = () if command in ("integrate finalize", "integrate abort") else ("--worktree-root", str(self.worktree_root))
        return subprocess.run(
            [
                sys.executable, str(CLI), "--framework-root", str(ROOT), "worktree", *command.split(), "056",
                "--project", str(self.project), *root, *extra,
            ],
            cwd=cwd or self.project, text=True, capture_output=True, check=False,
        )

    def prepare_with_commit(self) -> Path:
        worktree = Path(json.loads(self.lifecycle("prepare", "--format", "json").stdout)["worktree"])
        (worktree / "implementation.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "implementation.txt"], cwd=worktree, check=True)
        subprocess.run(["git", "commit", "-m", "complete task"], cwd=worktree, check=True, capture_output=True)
        return worktree

    def lines(self) -> list[dict[str, object]]:
        if not self.journal.exists():
            return []
        return [json.loads(line) for line in self.journal.read_text(encoding="utf-8").splitlines()]

    def test_prepare_resume_is_marked_in_the_journal(self) -> None:
        self.assertEqual(self.lifecycle("prepare", "--format", "json").returncode, 0)
        self.assertEqual(self.lifecycle("prepare", "--resume", "--format", "json").returncode, 0)
        first, second = self.lines()
        self.assertNotIn("resume", first)
        self.assertIs(second["resume"], True)

    def test_resume_survives_a_failed_journal_write(self) -> None:
        self.assertEqual(self.lifecycle("prepare", "--format", "json").returncode, 0)
        self.journal.unlink()
        self.journal.mkdir()
        resumed = self.lifecycle("prepare", "--resume", "--format", "json")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIs(json.loads(resumed.stdout)["resumed"], True)
        self.assertIn("lifecycle journal not written", resumed.stderr)

    def test_each_journaled_lifecycle_command_appends_one_line(self) -> None:
        evidence = self.root / "evidence.json"
        evidence.write_text("{}", encoding="utf-8")
        commands = (
            ("prepare", "--format", "json"),
            ("check", "--format", "json"),
            ("evidence", "--validation-command", "true", "--validation-exit-code", "0", "--format", "json"),
            ("integrate stage", "--evidence", str(evidence), "--format", "json"),
            ("integrate finalize", "--evidence", str(evidence), "--format", "json"),
            ("integrate abort", "--format", "json"),
            ("cleanup", "--format", "json"),
        )
        for index, (command, *extra) in enumerate(commands, start=1):
            self.lifecycle(command, *extra)
            recorded = self.lines()
            self.assertEqual(len(recorded), index, command)
            line = recorded[-1]
            self.assertEqual(line["command"], command)
            self.assertEqual(line["task"], "056")
            self.assertEqual(line["version"], 1)
            self.assertRegex(str(line["ts"]), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertIn(line["result"], {"ok", "blocked", "error"})
        first = self.lines()[0]
        self.assertEqual((first["result"], first["exit"], first["step"]), ("ok", 0, "check"))
        recorded = self.lines()
        self.lifecycle("closure-status", "--format", "json")
        self.assertEqual(self.lines(), recorded)

    def test_blocked_result_records_its_registered_code(self) -> None:
        self.prepare_with_commit()
        result = self.lifecycle("cleanup", "--format", "json")
        self.assertEqual(result.returncode, 2)
        line = self.lines()[-1]
        self.assertEqual(
            (line["command"], line["result"], line["exit"], line["stop_code"]),
            ("cleanup", "blocked", 2, "CLEANUP_BLOCKED"),
        )
        self.assertEqual(line["resolution"], "guardrail")
        self.assertNotIn(str(self.root), self.journal.read_text(encoding="utf-8"))

    def test_lines_hold_no_absolute_path_or_agent_supplied_text(self) -> None:
        self.lifecycle("prepare", "--format", "json")
        self.lifecycle(
            "evidence", "--validation-command", "SECRET-COMMAND-TEXT", "--validation-exit-code", "0",
            "--format", "json",
        )
        text = self.journal.read_text(encoding="utf-8")
        self.assertNotIn("SECRET-COMMAND-TEXT", text)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn(str(Path.home()), text)
        for line in self.lines():
            self.assertLessEqual(
                set(line), {"version", "ts", "command", "task", "step", "result", "stop_code", "resolution", "exit"}
            )

    def test_journal_is_untracked_and_shared_by_every_worktree(self) -> None:
        prepared = json.loads(self.lifecycle("prepare", "--format", "json").stdout)
        worktree = Path(prepared["worktree"])
        self.lifecycle("check", "--format", "json", cwd=worktree)
        self.assertEqual([line["command"] for line in self.lines()], ["prepare", "check"])
        status = subprocess.run(
            ["git", "status", "--short"], cwd=self.project, text=True, capture_output=True, check=True
        )
        self.assertEqual(status.stdout.strip(), "")
        self.assertFalse((worktree / "cardine-journal.jsonl").exists())

    def test_rotation_keeps_one_previous_file(self) -> None:
        directory = self.project / ".git"
        self.journal.write_text("x" * (owner_shared_journal.JOURNAL_MAX_BYTES + 1), encoding="utf-8")
        (directory / "cardine-journal.1.jsonl").write_text("older\n", encoding="utf-8")
        owner_shared_journal.append_journal_line(self.project, {"version": 1, "command": "check"})
        rotated = directory / "cardine-journal.1.jsonl"
        self.assertEqual(rotated.stat().st_size, owner_shared_journal.JOURNAL_MAX_BYTES + 1)
        self.assertEqual(self.lines(), [{"command": "check", "version": 1}])
        self.assertEqual(
            sorted(path.name for path in directory.glob("cardine-journal*")),
            ["cardine-journal.1.jsonl", "cardine-journal.jsonl"],
        )

    def test_write_failure_warns_once_and_keeps_the_result(self) -> None:
        worktree = self.prepare_with_commit()
        self.journal.unlink()
        self.journal.mkdir()
        checked = self.lifecycle("check", "--format", "json", cwd=worktree)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["status"], "ready")
        self.assertEqual(checked.stderr.count("warning: lifecycle journal not written"), 1)

    def test_concurrent_appends_from_two_worktrees_produce_whole_lines(self) -> None:
        other = self.root / "other"
        subprocess.run(
            ["git", "worktree", "add", "-b", "other", str(other)], cwd=self.project, check=True, capture_output=True
        )
        script = (
            "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import cardine_cli; "
            "[cardine_cli.append_journal_line(Path(sys.argv[2]), "
            "{'version': 1, 'command': 'check', 'pad': 'p' * 3000, 'n': i}) for i in range(150)]"
        )
        processes = [
            subprocess.Popen([sys.executable, "-c", script, str(ROOT / "scripts"), str(location)])
            for location in (self.project, other, self.project, other)
        ]
        for process in processes:
            self.assertEqual(process.wait(), 0)
        recorded = self.lines()
        self.assertEqual(len(recorded), 600)
        self.assertTrue(all(len(str(line["pad"])) == 3000 for line in recorded))


class FlowReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.project, check=True, capture_output=True)
        (self.project / "tasks" / "done").mkdir(parents=True)
        (self.project / ".cardine").mkdir()
        self.journal = self.project / ".git" / "cardine-journal.jsonl"
        self.records: list[str] = []
        self.now = datetime(2026, 10, 5, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def stamp(self, day: int, hour: int = 0) -> str:
        moment = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day, hours=hour)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def add(self, day: int, command: str, task: str, result: str = "ok", hour: int = 0, **extra: object) -> None:
        line = {"version": 1, "ts": self.stamp(day, hour), "command": command, "task": task, "result": result,
                "exit": 0 if result == "ok" else 2, **extra}
        self.records.append(json.dumps(line))

    def flush(self) -> None:
        self.journal.write_text("\n".join(self.records) + ("\n" if self.records else ""), encoding="utf-8")

    def task_record(self, task: str, origin: str | None, archived: bool = False) -> None:
        header = f"> **Origin**: {origin}\n" if origin else ""
        folder = self.project / "tasks" / ("done" if archived else "")
        (folder / f"{task}-work.md").write_text(f"# Task {task}\n\n> **ID**: `{task}`\n{header}", encoding="utf-8")

    def targets(self) -> None:
        (self.project / ".cardine" / "flow-targets.json").write_text(json.dumps({
            "version": 1,
            "unbacked_blocks": {"window": 20, "max": 0},
            "lead_time_regression": {"window": 20, "max_percent": 10},
            "friction_share": {"window": 20, "max_percent": 30},
        }), encoding="utf-8")

    def integrated(self, count: int, lead_hours: int = 10, origins: list[str | None] | None = None) -> None:
        for index in range(count):
            task = f"{100 + index}"
            self.add(index, "prepare", task)
            self.add(index, "integrate finalize", task, hour=lead_hours)
            self.task_record(task, origins[index] if origins else None)

    def report(self, since: str | None = None) -> dict[str, object]:
        self.flush()
        return owner_shared_flow.flow_report(self.project, since, self.now)

    def target_states(self, report: dict[str, object]) -> dict[str, str]:
        return {target["target"]: target["state"] for target in report["targets"]}  # type: ignore[index]

    def test_lead_time_runs_from_first_prepare_to_finalize(self) -> None:
        self.add(0, "prepare", "056")
        self.add(1, "prepare", "056", resume=True)
        self.add(1, "integrate finalize", "056", hour=2)
        self.add(2, "prepare", "057")
        self.task_record("056", None)
        report = self.report()
        by_task = {task["task"]: task for task in report["tasks"]}  # type: ignore[index]
        self.assertEqual(by_task["056"]["lead_time_seconds"], 26 * 3600)
        self.assertIsNone(by_task["057"]["lead_time_seconds"])
        self.assertEqual(report["totals"]["median_lead_time_seconds"], 26 * 3600)  # type: ignore[index]
        self.assertEqual(report["totals"]["integrated"], 1)  # type: ignore[index]

    def test_median_lead_time_across_tasks(self) -> None:
        for task, hours in (("101", 2), ("102", 4), ("103", 100)):
            self.add(0, "prepare", task)
            self.add(0, "integrate finalize", task, hour=hours)
        self.assertEqual(self.report()["totals"]["median_lead_time_seconds"], 4 * 3600)  # type: ignore[index]

    def test_stops_group_by_code_and_registered_class(self) -> None:
        self.add(0, "integrate stage", "056", "blocked", stop_code="PRIMARY_DIRTY")
        self.add(0, "integrate stage", "056", "blocked", stop_code="PRIMARY_DIRTY")
        self.add(1, "check", "056", "blocked")
        self.add(1, "cleanup", "057", "blocked", stop_code="NOT_A_REGISTERED_CODE")
        self.add(1, "check", "057", "error")
        report = self.report()
        self.assertEqual(report["stops_by_code"], {"NOT_A_REGISTERED_CODE": 1, "PRIMARY_DIRTY": 2, "uncoded": 1})
        self.assertEqual(report["stops_by_class"], {"tool": 2, "uncoded": 1, "unknown": 1})
        by_task = {task["task"]: task for task in report["tasks"]}  # type: ignore[index]
        self.assertEqual(by_task["056"]["stops"], {"PRIMARY_DIRTY": 2, "uncoded": 1})
        self.assertEqual(report["totals"]["stops"], 4)  # type: ignore[index]

    def test_resolution_counts_preserve_history_and_infer_legacy_lines(self) -> None:
        self.add(0, "check", "056", "blocked", stop_code="STALE_WORKTREE_BASE")
        self.add(1, "check", "056", "blocked", stop_code="PRIMARY_DIRTY", resolution="failing-work")
        self.add(2, "cleanup", "057", "blocked", stop_code="CLEANUP_BLOCKED", resolution="guardrail")
        self.add(2, "check", "057", "blocked", stop_code="NOT_A_REGISTERED_CODE")
        report = self.report()
        self.assertEqual(report["stops_by_resolution"],
                         {"recoverable": 1, "failing-work": 1, "guardrail": 1, "unknown": 1})
        self.assertEqual(report["tasks"][0]["stops_by_resolution"], {"recoverable": 1, "failing-work": 1})
        recent = self.report("2026-01-03")
        self.assertEqual(recent["stops_by_resolution"], {"guardrail": 1, "unknown": 1})
        self.assertIn("Stops by resolution:", owner_shared_flow.format_flow_report(report))
        self.assertIn("resolutions failing-work=1, recoverable=1", owner_shared_flow.format_flow_report(report))

    def test_aborts_and_resumes_are_counted_per_task(self) -> None:
        self.add(0, "prepare", "056")
        self.add(0, "prepare", "056", resume=True)
        self.add(1, "prepare", "056", resume=True)
        self.add(1, "prepare", "056", "error", resume=True)
        self.add(1, "integrate abort", "056")
        self.add(1, "integrate abort", "056", "blocked")
        task = self.report()["tasks"][0]  # type: ignore[index]
        self.assertEqual((task["resumes"], task["aborts"]), (2, 1))

    def test_since_filters_records_but_keeps_lead_time_history(self) -> None:
        self.add(0, "prepare", "056")
        self.add(5, "integrate stage", "056", "blocked", stop_code="PRIMARY_DIRTY")
        self.add(10, "integrate finalize", "056")
        self.add(1, "integrate stage", "057", "blocked", stop_code="LEASE_HELD")
        report = self.report(since="2026-01-05")
        self.assertEqual([task["task"] for task in report["tasks"]], ["056"])  # type: ignore[index]
        self.assertEqual(report["tasks"][0]["lead_time_seconds"], 10 * 86400)  # type: ignore[index]
        self.assertEqual(report["stops_by_code"], {"PRIMARY_DIRTY": 1})
        with self.assertRaises(shared_errors.CardineError):
            owner_shared_flow.flow_report(self.project, "yesterday", self.now)

    def test_origin_shares_with_archive_and_unknown(self) -> None:
        for task, origin, archived in (("101", "friction", False), ("102", "capability", True), ("103", None, False),
                                       ("104", "bogus", False), ("105", "Friction", True)):
            self.add(0, "check", task)
            self.task_record(task, origin, archived)
        self.add(0, "check", "106")
        report = self.report()
        self.assertEqual(report["origin_counts"], {"capability": 1, "friction": 2, "maintenance": 0, "release": 0, "unknown": 3})
        self.assertEqual(report["origin_share_percent"]["friction"], 33.3)  # type: ignore[index]
        self.assertEqual(report["origin_share_percent"]["unknown"], 50.0)  # type: ignore[index]

    def test_targets_report_insufficient_data(self) -> None:
        self.targets()
        self.integrated(5)
        self.assertEqual(self.target_states(self.report()), {
            "unbacked_blocks": "insufficient data", "lead_time_regression": "insufficient data",
            "friction_share": "insufficient data",
        })

    def test_targets_met(self) -> None:
        self.targets()
        self.integrated(40, origins=["capability"] * 30 + ["friction"] * 5 + ["maintenance"] * 5)
        report = self.report()
        self.assertEqual(self.target_states(report), {
            "unbacked_blocks": "met", "lead_time_regression": "met", "friction_share": "met",
        })
        measured = {target["target"]: target["measured"] for target in report["targets"]}  # type: ignore[index]
        self.assertEqual(measured, {"unbacked_blocks": 0, "lead_time_regression": 0.0, "friction_share": 25.0})

    def test_targets_missed(self) -> None:
        self.targets()
        self.integrated(40, origins=["capability"] * 30 + ["friction"] * 7 + ["maintenance"] * 3)
        for index in range(20, 40):  # the last 20 take 12h against 10h before them: +20%
            self.records[index * 2 + 1] = self.records[index * 2 + 1].replace('T10:00:00Z', 'T12:00:00Z')
        self.add(39, "unbacked", "139", "unbacked_block", hour=13, stop_code="PRIMARY_DIRTY")
        report = self.report()
        self.assertEqual(self.target_states(report), {
            "unbacked_blocks": "missed", "lead_time_regression": "missed", "friction_share": "missed",
        })
        self.assertEqual(report["unbacked_blocks"], 1)

    def test_target_window_ignores_older_unbacked_blocks_and_since(self) -> None:
        self.targets()
        self.add(-5, "unbacked", "099", "unbacked_block", stop_code="PRIMARY_DIRTY")
        self.integrated(20, origins=["capability"] * 20)
        report = self.report(since="2026-01-15")
        self.assertEqual(self.target_states(report)["unbacked_blocks"], "met")
        self.assertEqual(self.target_states(report)["friction_share"], "met")

    def test_missing_targets_file_shows_measurements_only(self) -> None:
        self.integrated(3)
        self.assertEqual(self.report()["targets"], [])

    def test_unreadable_targets_file_is_an_error(self) -> None:
        (self.project / ".cardine" / "flow-targets.json").write_text('{"version": 2}', encoding="utf-8")
        self.integrated(1)
        with self.assertRaises(shared_errors.CardineError):
            self.report()

    def test_removal_candidates_are_unemitted_tool_codes(self) -> None:
        tool_codes = {code for code, entry in stops_registry.load_stop_registry().items() if entry["class"] == "tool"}
        self.add(0, "integrate stage", "056", "blocked", stop_code="PRIMARY_DIRTY")
        self.add(0, "integrate stage", "056", "blocked", stop_code="VALIDATION_FAILED")
        self.add(30, "check", "056")
        report = self.report()
        self.assertEqual(set(report["removal_candidates"]), tool_codes - {"PRIMARY_DIRTY"})  # type: ignore[arg-type]
        self.assertEqual(report["period_days"], (self.now - datetime(2026, 1, 1, tzinfo=timezone.utc)).days)
        self.assertEqual(self.report(since="2026-01-20")["period_days"], (self.now - datetime(2026, 1, 20, tzinfo=timezone.utc)).days)

    def test_malformed_lines_are_counted_and_never_fatal(self) -> None:
        self.add(0, "prepare", "056")
        self.records += ["not json", "[1, 2]", '{"version": 2, "ts": "2026-01-01T00:00:00Z", "command": "x", "result": "ok"}',
                         '{"version": 1, "ts": "yesterday", "command": "x", "result": "ok"}', "", '{"version": 1}']
        self.add(0, "integrate finalize", "056", hour=3)
        report = self.report()
        self.assertEqual(report["malformed_lines"], 5)
        self.assertEqual(report["tasks"][0]["lead_time_seconds"], 3 * 3600)  # type: ignore[index]

    def test_rotated_journal_is_read_before_the_current_one(self) -> None:
        self.add(0, "prepare", "056")
        (self.project / ".git" / "cardine-journal.1.jsonl").write_text(self.records.pop() + "\n", encoding="utf-8")
        self.add(1, "integrate finalize", "056")
        self.assertEqual(self.report()["tasks"][0]["lead_time_seconds"], 86400)  # type: ignore[index]

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/dev.py"), "--framework-root", str(ROOT), "report", "flow", "--project", str(self.project), *arguments],
            cwd=self.project, text=True, capture_output=True, check=False,
        )

    def test_empty_or_missing_journal_gives_an_empty_report_with_exit_zero(self) -> None:
        for prepare in (lambda: None, self.flush):
            prepare()
            result = self.run_cli("--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual((report["tasks"], report["stops_by_code"], report["removal_candidates"], report["malformed_lines"]), ([], {}, [], 0))
            self.assertEqual(self.run_cli().returncode, 0)

    def test_cli_is_read_only_and_a_missed_target_keeps_exit_zero(self) -> None:
        self.targets()
        self.integrated(2)
        self.add(1, "unbacked", "101", "unbacked_block", hour=11)
        self.flush()
        before = self.journal.read_bytes()
        text = self.run_cli()
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn("Target unbacked_blocks: insufficient data", text.stdout)
        self.assertEqual(json.loads(self.run_cli("--format", "json", "--since", "2026-01-01").stdout)["since"], "2026-01-01")
        self.assertEqual(self.run_cli("--since", "nope").returncode, 2)
        self.assertEqual(self.journal.read_bytes(), before)
