"""Word and byte budgets for the always-read product templates (docs/RULE_ENFORCEMENT_INVENTORY.md, "Word budget").

The budgets are measured from the shared file lists and cross-checked against what
`cardine context size` reports, so the lists cannot drift from the real read set on
either host route.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cardine_cli_support import ROOT
from cardine.shared.context import (
    ALWAYS_READ_BUDGET, ROLE_START_BUDGET, SINGLE_DOCUMENT_BUDGET, TEMPLATE_ALWAYS_READ, TEMPLATE_CONDENSED,
    TEMPLATE_ROLE_DOCUMENTS, TEMPLATE_ROUTERS, WORKFLOW_BUDGET, context_size_report, template_budget_findings,
)

TEMPLATES = ROOT / "templates" / "single"
# The role procedure each router sends a role to, written out here so the shared lists cannot drift.
ROUTED = {
    "status": "docs/CONTEXT_READING_POLICY.md", "design": "docs/CONTEXT_READING_POLICY.md",
    "implementation": "docs/workflows/IMPLEMENTATION.md", "review": "docs/workflows/REVIEW.md",
    "remediation": "docs/workflows/REMEDIATION.md", "lifecycle": "docs/LIFECYCLE_ORCHESTRATION.md",
}


def measure(root: Path, paths) -> tuple[int, int]:
    texts = [(root / path).read_text(encoding="utf-8") for path in paths]
    return sum(len(text.split()) for text in texts), sum(len(text.encode("utf-8")) for text in texts)


def project_for(route: str, directory: str) -> Path:
    """A disposable project holding the shipped templates for one host route."""
    project = Path(directory) / route
    shutil.copytree(TEMPLATES, project)
    if route == "claude":
        (project / "AGENTS.md").unlink()  # the tool picks AGENTS.md first when it exists
    (project / ".cardine").mkdir()
    (project / ".cardine/project.json").write_text('{"version": 1, "preset": "lean"}\n', encoding="utf-8")
    return project


class TemplateWordBudgetTest(unittest.TestCase):
    def test_shipped_templates_hold_every_budget_on_both_routes(self) -> None:
        self.assertEqual(template_budget_findings(TEMPLATES), [])

    def test_the_budget_numbers_are_the_inventory_budget(self) -> None:
        self.assertEqual((ALWAYS_READ_BUDGET, WORKFLOW_BUDGET, ROLE_START_BUDGET, SINGLE_DOCUMENT_BUDGET),
                         ((1100, 8000), (750, 5400), (1400, 10000), (650, 4700)))

    def test_the_language_policy_is_still_counted_in_the_always_read_set(self) -> None:
        for route, router in TEMPLATE_ROUTERS.items():
            with self.subTest(route=route):
                self.assertIn("LANGUAGE_POLICY.md", (TEMPLATES / router).read_text(encoding="utf-8"))
        words, _ = measure(TEMPLATES, ("LANGUAGE_POLICY.md",))
        self.assertGreater(words, 150)

    def test_every_role_has_a_route_and_its_documents_exist(self) -> None:
        self.assertEqual(set(TEMPLATE_ROLE_DOCUMENTS), set(ROUTED))
        for role, documents in TEMPLATE_ROLE_DOCUMENTS.items():
            self.assertIn(ROUTED[role], documents)
            for document in documents:
                self.assertTrue((TEMPLATES / document).is_file(), document)

    def test_the_reported_read_set_of_every_role_is_the_measured_one_on_both_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for route, router in TEMPLATE_ROUTERS.items():
                project = project_for(route, directory)
                for role, documents in TEMPLATE_ROLE_DOCUMENTS.items():
                    with self.subTest(route=route, role=role):
                        report = context_size_report(project, role, workflow_mode="single")
                        present = [item for item in report["files"] if item["status"] == "present"]
                        self.assertEqual(sorted(item["path"] for item in present),
                                         sorted({router, *TEMPLATE_ALWAYS_READ, *documents}))
                        # The router must send the role to its own procedure, not the workflow fallback.
                        routed = [item["path"] for item in report["files"] if item["category"] == "routed-workflow"]
                        self.assertEqual(routed, [ROUTED[role]])
                        # Only the Claude router cites the deleted AGENTS.md; nothing else is missing.
                        missing = [item["path"] for item in report["files"] if item["status"] == "missing"]
                        self.assertEqual(missing, ["AGENTS.md"] if route == "claude" else [])
                        words, size = measure(project, [item["path"] for item in present])
                        self.assertLessEqual(words, ROLE_START_BUDGET[0])
                        self.assertLessEqual(size, ROLE_START_BUDGET[1])
                        self.assertEqual(report["total"]["bytes"], size)
                        self.assertEqual(report["exceeded"], [])

    def test_the_source_organization_rule_is_deferred_for_every_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = project_for("codex", directory)
            for role in TEMPLATE_ROLE_DOCUMENTS:
                with self.subTest(role=role):
                    report = context_size_report(project, role, workflow_mode="single")
                    self.assertNotIn("docs/CODE_ORGANIZATION.md", [item["path"] for item in report["files"]])
                    self.assertEqual({item["path"]: item["phase"] for item in report["deferred_documents"]},
                                     {"docs/CODE_ORGANIZATION.md": "production-source change"})

    def test_an_over_budget_fixture_is_reported_and_the_check_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "single"
            shutil.copytree(TEMPLATES, fixture)
            before = {path: path.read_bytes() for path in fixture.rglob("*") if path.is_file()}
            self.assertEqual(template_budget_findings(fixture), [])
            self.assertEqual(before, {path: path.read_bytes() for path in fixture.rglob("*") if path.is_file()})
            workflow = fixture / "PROJECT_WORKFLOW.md"
            workflow.write_text(workflow.read_text(encoding="utf-8") + "extra " * 400, encoding="utf-8")
            findings = template_budget_findings(fixture)
        self.assertTrue(any(finding.startswith("PROJECT_WORKFLOW.md") for finding in findings), findings)
        self.assertTrue(any(finding.startswith("always-read (codex)") for finding in findings), findings)
        self.assertTrue(any(finding.startswith("implementation start (claude)") for finding in findings), findings)

    def test_bytes_alone_fail_a_budget_when_the_words_fit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "single"
            shutil.copytree(TEMPLATES, fixture)
            review = fixture / "docs/workflows/REVIEW.md"
            # Few words, many bytes: one long token.
            review.write_text(review.read_text(encoding="utf-8") + "x" * 6000, encoding="utf-8")
            findings = template_budget_findings(fixture)
        self.assertTrue(any(finding.startswith("review start (codex)") for finding in findings), findings)
        self.assertTrue(any(finding.startswith("docs/workflows/REVIEW.md") for finding in findings), findings)

    def test_a_missing_budgeted_document_is_a_finding_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "single"
            shutil.copytree(TEMPLATES, fixture)
            (fixture / "docs/workflows/REMEDIATION.md").unlink()
            findings = template_budget_findings(fixture)
        self.assertTrue(any(finding.startswith("remediation start (codex): cannot read") for finding in findings), findings)

    def test_every_condensed_document_is_budgeted_individually(self) -> None:
        for path in TEMPLATE_CONDENSED:
            with self.subTest(path=path):
                words, size = measure(TEMPLATES, (path,))
                self.assertLessEqual(words, SINGLE_DOCUMENT_BUDGET[0])
                self.assertLessEqual(size, SINGLE_DOCUMENT_BUDGET[1])

    def test_the_check_repeats_identically_from_an_unrelated_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = {path: path.read_bytes() for path in TEMPLATES.rglob("*") if path.is_file()}
            previous = Path.cwd()
            os.chdir(directory)
            try:
                first, second = template_budget_findings(TEMPLATES), template_budget_findings(TEMPLATES)
            finally:
                os.chdir(previous)
            self.assertEqual((first, second), ([], []))
            self.assertEqual(os.listdir(directory), [])
            self.assertEqual(snapshot, {path: path.read_bytes() for path in TEMPLATES.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
