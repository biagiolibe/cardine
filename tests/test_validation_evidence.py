"""Tests for the read-only external validation evidence verifier."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian  # noqa: E402


class ValidationEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        (self.project / "tasks").mkdir()
        (self.project / "tasks/113-evidence.md").write_text(
            "> **ID**: `113`\n", encoding="utf-8"
        )
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Evidence Test")
        self.git("config", "user.email", "evidence@example.invalid")
        self.git("add", "tasks")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "Add evidence task fixture")
        self.commit = self.git("rev-parse", "HEAD")
        self.tree = self.git("rev-parse", "HEAD^{tree}")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.project, text=True, capture_output=True, check=True
        ).stdout.strip()

    def record(self) -> dict[str, object]:
        return {
            "version": 1, "task_id": "113", "status": "passed", "level": "T2_SHARDED",
            "commit": self.commit, "tree": self.tree, "command": ["python3", "-m", "unittest"],
            "exit_code": 0, "tests_run": 4, "produced_at": "2026-10-02T10:00:00Z",
            "total": 4, "digest": "abc", "shards": [
                {"index": 1, "count": 2, "exit_code": 0, "tests_run": 2, "digest": "abc", "total": 4},
                {"index": 2, "count": 2, "exit_code": 0, "tests_run": 2, "digest": "abc", "total": 4},
            ],
        }

    def write(self, record: dict[str, object]) -> Path:
        temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        with temporary:
            json.dump(record, temporary)
        self.addCleanup(Path(temporary.name).unlink)
        return Path(temporary.name)

    def test_passing_sharded_record_is_bound_to_commit_and_tree(self) -> None:
        report, code = meridian.check_validation_evidence(self.write(self.record()), self.project, self.commit)
        self.assertEqual(code, meridian.VALIDATION_EXIT_PASSED)
        self.assertEqual(report, {"status": "VALIDATION_PASSED", "level": "T2_SHARDED", "reasons": []})

    def test_invalid_proofs_name_the_failing_field(self) -> None:
        cases = (("tree", "wrong-tree"), ("tests_run", 0), ("level", "unknown"))
        for field, value in cases:
            with self.subTest(field=field):
                record = self.record()
                record[field] = value
                report, code = meridian.check_validation_evidence(self.write(record), self.project, self.commit)
                self.assertEqual(code, meridian.VALIDATION_EXIT_FAILED)
                self.assertTrue(any(reason.startswith(field + ":") for reason in report["reasons"]))

    def test_running_record_never_invokes_subprocess(self) -> None:
        record = self.record()
        record.pop("exit_code")
        record.update({"status": "running", "started_at": "2026-10-02T10:00:00Z", "log": "logs/113.txt"})
        with mock.patch.object(meridian.subprocess, "run") as run:
            report, code = meridian.check_validation_evidence(self.write(record), self.project, None)
        self.assertEqual(code, meridian.VALIDATION_EXIT_PENDING)
        self.assertEqual(report["status"], "VALIDATION_RUNNING")
        run.assert_not_called()

    def test_attestation_requires_date(self) -> None:
        record = self.record()
        record.update({"level": "T3_ATTESTED", "attested_by": "developer", "statement": "I ran it."})
        report, code = meridian.check_validation_evidence(self.write(record), self.project, self.commit)
        self.assertEqual(code, meridian.VALIDATION_EXIT_FAILED)
        self.assertIn("attested_on: is required for T3_ATTESTED", report["reasons"])
