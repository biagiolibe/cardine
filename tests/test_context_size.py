"""Regression tests for `meridian context size`."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "meridian.py"


class ContextSizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        (self.project / "docs/workflows").mkdir(parents=True)
        (self.project / "tasks").mkdir()
        (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n", encoding="utf-8")
        (self.project / "LANGUAGE_POLICY.md").write_text("English\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md`.\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(CLI), "context", "size", *arguments, "--project", str(self.project)], text=True, capture_output=True, check=False)

    def governed(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text(
            "\n".join((
                "Status, project question, or tech-design alignment — use `docs/workflows/STATUS.md`.",
                "- `Proceed with <TASK-ID>` — read `docs/workflows/IMPLEMENTATION.md`.",
                "- `Review <TASK-ID>` — read `docs/workflows/REVIEW.md`.",
                "- `Address review <TASK-ID>` — read `docs/workflows/REMEDIATION.md`.",
                "- `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` — read `docs/workflows/LIFECYCLE.md`.",
            )), encoding="utf-8"
        )
        for name in ("STATUS.md", "IMPLEMENTATION.md", "REVIEW.md", "REMEDIATION.md", "LIFECYCLE.md"):
            (self.project / "docs/workflows" / name).write_text(f"# {name}\n", encoding="utf-8")

    def test_lean_roles_report_estimated_ranges(self) -> None:
        for role in ("implementation", "review"):
            result = self.run_cli("--role", role, "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["mode"], "lean-delivery")
            self.assertIn("not tokenizer-accurate", report["estimate"])
            self.assertGreater(report["total"]["bytes"], 0)

    def test_governed_roles_and_missing_citation(self) -> None:
        self.governed()
        (self.project / "docs/workflows/IMPLEMENTATION.md").write_text("Read `docs/MISSING.md`.\n", encoding="utf-8")
        for role in ("status", "design", "implementation", "review", "remediation", "lifecycle"):
            result = self.run_cli("--role", role, "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["mode"], "governed-sdd")
        report = json.loads(self.run_cli("--role", "implementation", "--format", "json").stdout)
        self.assertIn("docs/MISSING.md", [item["path"] for item in report["files"] if item["status"] == "missing"])

    def test_task_authority_milestone_threshold_and_no_writes(self) -> None:
        self.governed()
        (self.project / ".meridian").mkdir()
        (self.project / ".meridian/task-identity.json").write_text('{"version": 1, "mode": "milestone"}\n', encoding="utf-8")
        (self.project / "docs/ARCHITECTURE_DECISIONS.md").write_text("## ADR-0001 — Test\n\nBody.\n", encoding="utf-8")
        task = self.project / "tasks/M1-CORE-001.md"
        task.write_text("# Task\n\n## Authority\n\n- ADR-0001\n", encoding="utf-8")
        before = {path.relative_to(self.project): path.stat().st_mtime_ns for path in self.project.rglob("*") if path.is_file()}
        result = self.run_cli("--role", "implementation", "--task", "M1-CORE-001", "--threshold-bytes", "1", "--format", "text")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("authority-excerpt", result.stdout)
        self.assertIn("Threshold exceeded", result.stdout)
        after = {path.relative_to(self.project): path.stat().st_mtime_ns for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_router_file_ceiling_is_reported_and_fails(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n" * 3, encoding="utf-8")
        (self.project / ".meridian").mkdir()
        (self.project / ".meridian/context-size.json").write_text(
            '{"version": 1, "routerFileLinesCeiling": 1}\n', encoding="utf-8"
        )
        result = self.run_cli("--role", "implementation", "--format", "json")
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["router_file_lines_ceiling"], 1)
        self.assertIn("PROJECT_WORKFLOW.md", report["exceeded"])


    def test_phase_reads_defer_documents_outside_the_startup_total(self) -> None:
        self.governed()
        (self.project / "AGENTS.md").write_text(
            "\n".join((
                "- `Proceed with <TASK-ID>` — read `docs/workflows/IMPLEMENTATION.md`.",
                "Follow `docs/CODE_ORGANIZATION.md` for production-source changes.",
            )), encoding="utf-8"
        )
        (self.project / "docs/CODE_ORGANIZATION.md").write_text("organization\n" * 10, encoding="utf-8")
        (self.project / "docs/COMPLETION_REPORT_TEMPLATE.md").write_text("report\n" * 10, encoding="utf-8")
        (self.project / "docs/START.md").write_text("start\n", encoding="utf-8")
        (self.project / "docs/workflows/IMPLEMENTATION.md").write_text(
            "\n".join((
                "Also see `docs/CODE_ORGANIZATION.md` and `docs/COMPLETION_REPORT_TEMPLATE.md`.",
                "- At first plan: `docs/CODE_ORGANIZATION.md`.",
                "<!-- MERIDIAN:BEGIN capability=phase-reads v1 -->",
                "- At start: `docs/START.md`.",
                "- At first plan: `docs/CODE_ORGANIZATION.md`.",
                "- At completion: `docs/COMPLETION_REPORT_TEMPLATE.md`.",
                "<!-- MERIDIAN:END -->",
            )), encoding="utf-8"
        )
        report = json.loads(self.run_cli("--role", "implementation", "--format", "json").stdout)
        startup = [item["path"] for item in report["files"]]
        self.assertIn("docs/START.md", startup)
        self.assertNotIn("docs/CODE_ORGANIZATION.md", startup)
        self.assertNotIn("docs/COMPLETION_REPORT_TEMPLATE.md", startup)
        deferred = {item["path"]: item["phase"] for item in report["deferred_documents"]}
        self.assertEqual(deferred, {"docs/CODE_ORGANIZATION.md": "first plan", "docs/COMPLETION_REPORT_TEMPLATE.md": "completion"})
        self.assertEqual(report["total"]["bytes"], sum(item["bytes"] for item in report["files"] if item["status"] == "present"))
        text = self.run_cli("--role", "implementation", "--format", "text").stdout
        self.assertIn("DEFERRED docs/CODE_ORGANIZATION.md", text)
        self.assertIn("Read at: completion.", text)

    def test_phase_reads_outside_a_managed_block_stay_startup_reads(self) -> None:
        self.governed()
        (self.project / "docs/CODE_ORGANIZATION.md").write_text("organization\n", encoding="utf-8")
        (self.project / "docs/workflows/IMPLEMENTATION.md").write_text("- At completion: `docs/CODE_ORGANIZATION.md`.\n", encoding="utf-8")
        report = json.loads(self.run_cli("--role", "implementation", "--format", "json").stdout)
        self.assertIn("docs/CODE_ORGANIZATION.md", [item["path"] for item in report["files"]])
        self.assertEqual(report["deferred_documents"], [])
