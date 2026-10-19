"""Tests for exact-commit GitHub Actions validation evidence."""

from __future__ import annotations

import contextlib
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ci_evidence  # noqa: E402
import cardine_cli  # noqa: E402
from cardine.integration import evidence as owner_integration_evidence
import cardine.shared.constants as shared_constants


class CiEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        (self.project / "tasks").mkdir()
        (self.project / "tasks/114-evidence.md").write_text(
            "> **ID**: `114`\n", encoding="utf-8"
        )
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Evidence Test")
        self.git("config", "user.email", "evidence@example.invalid")
        self.git("add", "tasks")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "Add evidence task fixture")
        self.commit = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")
        self.output = Path(self.temporary.name) / "evidence.json"

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.project, text=True, capture_output=True, check=True
        ).stdout.strip()

    def run_script(self, responses: list[tuple[object | None, str | None]], *extra: str, clock=None, wall_clock=None) -> tuple[int, dict[str, str]]:
        with mock.patch.object(ci_evidence.shutil, "which", return_value="gh"), \
             mock.patch.object(ci_evidence, "gh_json", side_effect=responses), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = ci_evidence.run(["--commit", self.commit, "--task", "114", "--output", str(self.output), *extra],
                                   clock=clock or (lambda: 0), wall_clock=wall_clock or (lambda: 1792195200.875), sleep=lambda _: None)
        return code, json.loads(stdout.getvalue())

    def run_data(self, status="completed", conclusion="success", commit=None) -> dict[str, object]:
        return {"databaseId": 42, "headSha": commit or self.commit, "event": "push", "status": status,
                "conclusion": conclusion, "url": "https://github.com/example/meridian/actions/runs/42", "workflowName": "Validate repository"}

    def test_success_writes_a_verifier_compatible_t1_record(self) -> None:
        run = self.run_data()
        code, outcome = self.run_script([([run], None), (run, None), ({"tree": {"sha": self.tree}}, None)])
        self.assertEqual((code, outcome), (0, {"status": "passed"}))
        record = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(record["produced_at"], "2026-10-17T00:00:00Z")
        self.assertEqual(record["command"], ci_evidence.CI_TEST_COMMAND)
        self.assertIsNone(record["tests_run"])
        self.assertEqual(record["ci"], {"run_id": "42", "run_url": run["url"], "workflow": "Validate repository", "conclusion": "success", "head_sha": self.commit})
        report, verified = owner_integration_evidence.check_validation_evidence(self.output, self.project, self.commit)
        self.assertEqual((verified, report["status"]), (shared_constants.VALIDATION_EXIT_PASSED, "VALIDATION_PASSED"))

    def test_command_constant_matches_workflow(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
        commands = [shlex.split(line.strip().removeprefix("- run: "))
                    for line in workflow.splitlines() if line.strip().startswith("- run: ")]
        self.assertIn(ci_evidence.CI_TEST_COMMAND, commands)

    def test_in_progress_then_success_polls_without_real_sleep(self) -> None:
        running, passed = self.run_data(status="in_progress", conclusion=None), self.run_data()
        clock_values = iter((0, 0, 0, 0))
        code, outcome = self.run_script([([running], None), (running, None), ([passed], None), (passed, None), ({"tree": {"sha": self.tree}}, None)], "--wait", "5", clock=lambda: next(clock_values))
        self.assertEqual((code, outcome), (0, {"status": "passed"}))

    def test_no_run_is_unavailable(self) -> None:
        code, outcome = self.run_script([([], None)])
        self.assertEqual((code, outcome), (1, {"reason": "no_ci_run", "status": "unavailable"}))
        self.assertFalse(self.output.exists())

    def test_in_progress_run_is_running_without_waiting(self) -> None:
        run = self.run_data(status="in_progress", conclusion=None)
        code, outcome = self.run_script([([run], None), (run, None)])
        self.assertEqual((code, outcome), (1, {"status": "running"}))
        self.assertFalse(self.output.exists())

    def test_run_for_another_commit_is_ignored(self) -> None:
        code, outcome = self.run_script([([self.run_data(commit="other")], None)])
        self.assertEqual((code, outcome), (1, {"reason": "no_ci_run", "status": "unavailable"}))

    def test_failure_and_cancellation_are_failed(self) -> None:
        for conclusion in ("failure", "cancelled"):
            with self.subTest(conclusion=conclusion):
                run = self.run_data(conclusion=conclusion)
                code, outcome = self.run_script([([run], None), (run, None)])
                self.assertEqual((code, outcome), (2, {"status": "failed"}))

    def test_transient_error_is_retried_inside_wait_window(self) -> None:
        run = self.run_data()
        clock_values = iter((0, 0, 0))
        code, outcome = self.run_script([(None, "temporary gh error"), ([run], None), (run, None), ({"tree": {"sha": self.tree}}, None)], "--wait", "5", clock=lambda: next(clock_values))
        self.assertEqual((code, outcome), (0, {"status": "passed"}))

    def test_missing_gh_is_unavailable(self) -> None:
        with mock.patch.object(ci_evidence.shutil, "which", return_value=None), contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = ci_evidence.run(["--commit", self.commit, "--task", "114", "--output", str(self.output)])
        self.assertEqual((code, json.loads(stdout.getvalue())), (1, {"reason": "gh_missing", "status": "unavailable"}))


if __name__ == "__main__":
    unittest.main()
