"""Regression tests for `cardine context size`."""

from __future__ import annotations

from task_contract_support import freeze_record
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from project_config_support import write_project_config


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "cardine_cli.py"
sys.path.insert(0, str(ROOT / "scripts"))
import check_repository as cr  # noqa: E402
from cardine.shared import context as shared_context  # noqa: E402


class ContextSizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        (self.project / "docs/workflows").mkdir(parents=True)
        (self.project / "tasks").mkdir()
        (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n", encoding="utf-8")
        write_project_config(self.project, "lean")
        (self.project / "LANGUAGE_POLICY.md").write_text("English\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md`.\n- `Proceed with <TASK-ID>` — read `docs/workflows/IMPLEMENTATION.md`.\n- `Review <TASK-ID>` — read `docs/workflows/REVIEW.md`.\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(CLI), "context", "size", *arguments, "--project", str(self.project)], text=True, capture_output=True, check=False)

    def governed(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text("GOVERNED_SDD\n", encoding="utf-8")
        write_project_config(self.project, "governed")
        (self.project / "AGENTS.md").write_text(
            "\n".join((
                "Status, project question, or tech-design alignment — use `docs/workflows/STATUS.md`.",
                "- `Proceed with <TASK-ID>` — read `docs/workflows/IMPLEMENTATION.md`.",
                "- `Review <TASK-ID>` — read `docs/workflows/REVIEW.md`.",
                "- `Address review <TASK-ID>` — read `docs/workflows/REMEDIATION.md`.",
                "- `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` — read `docs/LIFECYCLE_ORCHESTRATION.md`.",
            )), encoding="utf-8"
        )
        for name in ("STATUS.md", "IMPLEMENTATION.md", "REVIEW.md", "REMEDIATION.md", "LIFECYCLE.md"):
            (self.project / "docs/workflows" / name).write_text(f"# {name}\n", encoding="utf-8")

    def test_skill_routes_do_not_consume_later_entries(self) -> None:
        router = self.project / "AGENTS.md"
        router.write_text(
            "- `Proceed with <TASK-ID>` or `Address review <TASK-ID>` — use `cardine-delivery`.\n"
            "- `Review <TASK-ID>` — use `cardine-delivery`.\n"
            "- `Run lifecycle <TASK-ID>` — read `docs/LIFECYCLE_ORCHESTRATION.md`.\n"
        )
        for role in ("implementation", "review", "remediation"):
            with self.subTest(role=role):
                self.assertEqual(shared_context._context_routed_workflow(self.project, "single", role, Path("AGENTS.md")), Path("PROJECT_WORKFLOW.md"))
        self.assertEqual(shared_context._context_routed_workflow(self.project, "single", "lifecycle", Path("AGENTS.md")), Path("docs/LIFECYCLE_ORCHESTRATION.md"))
        self.governed()
        for role, target in (("status", "STATUS.md"), ("implementation", "IMPLEMENTATION.md"), ("review", "REVIEW.md"), ("remediation", "REMEDIATION.md")):
            self.assertEqual(shared_context._context_routed_workflow(self.project, "single", role, Path("AGENTS.md")), Path("docs/workflows") / target)

    def test_lean_roles_report_estimated_ranges(self) -> None:
        for role in ("implementation", "review"):
            result = self.run_cli("--role", role, "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["mode"], "single")
            self.assertIn("not tokenizer-accurate", report["estimate"])
            self.assertGreater(report["total"]["bytes"], 0)

    def test_governed_roles_and_missing_citation(self) -> None:
        self.governed()
        (self.project / "docs/workflows/IMPLEMENTATION.md").write_text("Read `docs/MISSING.md`.\n", encoding="utf-8")
        for role in ("status", "design", "implementation", "review", "remediation", "lifecycle"):
            result = self.run_cli("--role", role, "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["mode"], "single")
        report = json.loads(self.run_cli("--role", "implementation", "--format", "json").stdout)
        self.assertIn("docs/MISSING.md", [item["path"] for item in report["files"] if item["status"] == "missing"])

    def test_task_authority_milestone_threshold_and_no_writes(self) -> None:
        self.governed()
        (self.project / ".cardine").mkdir(exist_ok=True)
        (self.project / ".cardine/task-identity.json").write_text('{"version": 1, "mode": "milestone"}\n', encoding="utf-8")
        (self.project / "docs/ARCHITECTURE_DECISIONS.md").write_text("## ADR-0001 — Test\n\nBody.\n", encoding="utf-8")
        task = self.project / "tasks/M1-CORE-001.md"
        task.write_text("# Task\n\n## Authority\n\n- ADR-0001\n", encoding="utf-8")
        freeze_record(self.project, "M1-CORE-001", task)
        before = {path.relative_to(self.project): path.stat().st_mtime_ns for path in self.project.rglob("*") if path.is_file()}
        result = self.run_cli("--role", "implementation", "--task", "M1-CORE-001", "--threshold-bytes", "1", "--format", "text")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("authority-excerpt", result.stdout)
        self.assertIn("Threshold exceeded", result.stdout)
        after = {path.relative_to(self.project): path.stat().st_mtime_ns for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_router_file_ceiling_is_reported_and_fails(self) -> None:
        (self.project / "PROJECT_WORKFLOW.md").write_text("LEAN_DELIVERY\n" * 3, encoding="utf-8")
        (self.project / ".cardine").mkdir(exist_ok=True)
        (self.project / ".cardine/context-size.json").write_text(
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
                "<!-- CARDINE:BEGIN capability=phase-reads v1 -->",
                "- At start: `docs/START.md`.",
                "- At first plan: `docs/CODE_ORGANIZATION.md`.",
                "- At completion: `docs/COMPLETION_REPORT_TEMPLATE.md`.",
                "<!-- CARDINE:END -->",
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


class ReferenceResolutionTest(unittest.TestCase):
    """Task 074 defect 1: inline-code citations are project-relative, links are document-relative."""

    def test_inline_citations_resolve_from_the_project_root(self) -> None:
        document = Path("docs/workflows/IMPLEMENTATION.md")
        self.assertEqual(
            shared_context._context_relative_references(document, "Read `PROJECT_WORKFLOW.md`, `AGENTS.md`, and `docs/CODE_ORGANIZATION.md`."),
            [Path("PROJECT_WORKFLOW.md"), Path("AGENTS.md"), Path("docs/CODE_ORGANIZATION.md")],
        )

    def test_links_resolve_from_the_citing_document_with_dots_normalized(self) -> None:
        document = Path("docs/workflows/IMPLEMENTATION.md")
        text = "[a](../CODE_ORGANIZATION.md) [b](REVIEW.md#top) [c](../../README.md) [d](../../../outside.md) [e](/etc/x.md)"
        self.assertEqual(
            shared_context._context_relative_references(document, text),
            [Path("docs/CODE_ORGANIZATION.md"), Path("docs/workflows/REVIEW.md"), Path("README.md")],
        )

    def test_a_citation_of_a_missing_file_is_still_reported_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            shutil.copytree(ROOT / "templates/single", project)
            write_project_config(project, "lean")
            (project / "AGENTS.md").write_text("- `Proceed with <TASK-ID>` — read `docs/workflows/IMPLEMENTATION.md`.\n")
            implementation = project / "docs/workflows/IMPLEMENTATION.md"
            implementation.write_text(implementation.read_text(encoding="utf-8") + "\nAlso read `docs/MISSING.md`.\n", encoding="utf-8")
            report = shared_context.context_size_report(project, "implementation", workflow_mode="single")
        self.assertEqual([item["path"] for item in report["files"] if item["status"] == "missing"], ["docs/MISSING.md"])

    def test_the_shipped_read_sets_report_nothing_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            shutil.copytree(ROOT / "templates/single", project)
            write_project_config(project, "lean")
            for role in shared_context.CONTEXT_SIZE_ROLES["single"]:
                with self.subTest(role=role):
                    report = shared_context.context_size_report(project, role, workflow_mode="single")
                    self.assertEqual([item["path"] for item in report["files"] if item["status"] == "missing"], [])


class CeilingTest(unittest.TestCase):
    """Task 074 defect 2: the shipped ceilings are the role-start byte budget, and cannot be raised past it."""

    def project(self, directory: str, ceiling: str | None = None) -> Path:
        project = Path(directory) / "project"
        shutil.copytree(ROOT / "templates/single", project)
        write_project_config(project, "lean")
        if ceiling is not None:
            policy = project / "docs/CONTEXT_READING_POLICY.md"
            policy.write_text(policy.read_text(encoding="utf-8").replace("| 10000 |", f"| {ceiling} |"), encoding="utf-8")
        return project

    def test_every_shipped_ceiling_is_the_role_start_byte_budget(self) -> None:
        text = (ROOT / "templates/single/docs/CONTEXT_READING_POLICY.md").read_text(encoding="utf-8")
        rows = dict(re.findall(r"^\| All presets \| ([a-z]+) \| ([0-9]+) \|$", text, re.MULTILINE))
        self.assertEqual(set(rows), set(shared_context.CONTEXT_SIZE_ROLES["single"]))
        self.assertEqual({int(value) for value in rows.values()}, {shared_context.ROLE_START_BUDGET[1]})

    def test_the_shipped_ceilings_pass_and_a_ceiling_above_the_budget_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cr._check_template_context_sizes(self.project(directory))
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(SystemExit):
            cr._check_template_context_sizes(self.project(directory, "100000"))

    def test_a_read_set_over_its_ceiling_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(SystemExit):
            cr._check_template_context_sizes(self.project(directory, "5000"))
