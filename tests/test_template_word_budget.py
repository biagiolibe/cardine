"""Word and byte budgets for the always-read product templates (docs/RULE_ENFORCEMENT_INVENTORY.md, "Word budget").

The file lists are explicit: this module measures what an agent is told to read,
not what `cardine context size` reports, so it holds on both host routes.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cardine_cli_support import ROOT

TEMPLATES = ROOT / "templates" / "single"
ROUTES = {"codex": "AGENTS.md", "claude": "CLAUDE.md"}
SHARED = ("PROJECT_WORKFLOW.md", "LANGUAGE_POLICY.md")
# Words, bytes.
ALWAYS_READ = (1100, 8000)
WORKFLOW = (750, 5400)
ROLE_START = (1400, 10000)
SINGLE_DOCUMENT = (650, 4700)
ROLE_DOCUMENTS = {
    "implementation": ("docs/workflows/IMPLEMENTATION.md", "docs/CONTEXT_READING_POLICY.md"),
    "review": ("docs/workflows/REVIEW.md",),
    "remediation": ("docs/workflows/REMEDIATION.md",),
    "lifecycle": ("docs/LIFECYCLE_ORCHESTRATION.md",),
    "status": ("docs/CONTEXT_READING_POLICY.md",),
}
# The documents this row rewrote; the remaining templates meet the single-document
# budget when their own rows condense them.
REWRITTEN = ("AGENTS.md", "CLAUDE.md", "PROJECT_WORKFLOW.md", "docs/workflows/IMPLEMENTATION.md",
             "docs/workflows/REVIEW.md", "docs/workflows/REMEDIATION.md",
             "docs/LIFECYCLE_ORCHESTRATION.md", "docs/CONTEXT_READING_POLICY.md")


def measure(root: Path, paths) -> tuple[int, int]:
    texts = [(root / path).read_text(encoding="utf-8") for path in paths]
    return sum(len(text.split()) for text in texts), sum(len(text.encode("utf-8")) for text in texts)


def over_budget(root: Path) -> list[str]:
    """Return one finding per exceeded budget; empty when every budget holds."""
    findings = []

    def check(label: str, paths, budget) -> None:
        words, size = measure(root, paths)
        if words > budget[0] or size > budget[1]:
            findings.append(f"{label}: {words} words / {size} bytes > {budget[0]} / {budget[1]}")

    check("PROJECT_WORKFLOW.md", ("PROJECT_WORKFLOW.md",), WORKFLOW)
    for route, router in ROUTES.items():
        check(f"always-read ({route})", (router, *SHARED), ALWAYS_READ)
        for role, documents in ROLE_DOCUMENTS.items():
            check(f"{role} start ({route})", (router, *SHARED, *documents), ROLE_START)
    for path in REWRITTEN:
        if path != "PROJECT_WORKFLOW.md":  # the workflow has its own budget
            check(path, (path,), SINGLE_DOCUMENT)
    return findings


class TemplateWordBudgetTest(unittest.TestCase):
    def test_shipped_templates_hold_every_budget_on_both_routes(self) -> None:
        self.assertEqual(over_budget(TEMPLATES), [])

    def test_the_language_policy_is_still_counted_in_the_always_read_set(self) -> None:
        for route, router in ROUTES.items():
            with self.subTest(route=route):
                self.assertIn("LANGUAGE_POLICY.md", (TEMPLATES / router).read_text(encoding="utf-8"))
        words, _ = measure(TEMPLATES, ("LANGUAGE_POLICY.md",))
        self.assertGreater(words, 150)

    def test_every_role_route_names_an_existing_document(self) -> None:
        for documents in ROLE_DOCUMENTS.values():
            for document in documents:
                self.assertTrue((TEMPLATES / document).is_file(), document)

    def test_an_over_budget_fixture_is_reported_and_the_check_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "single"
            shutil.copytree(TEMPLATES, fixture)
            before = {path: path.read_bytes() for path in fixture.rglob("*") if path.is_file()}
            self.assertEqual(over_budget(fixture), [])
            self.assertEqual(before, {path: path.read_bytes() for path in fixture.rglob("*") if path.is_file()})
            workflow = fixture / "PROJECT_WORKFLOW.md"
            workflow.write_text(workflow.read_text(encoding="utf-8") + "extra " * 400, encoding="utf-8")
            findings = over_budget(fixture)
        self.assertTrue(any(finding.startswith("PROJECT_WORKFLOW.md") for finding in findings), findings)
        self.assertTrue(any(finding.startswith("always-read (codex)") for finding in findings), findings)
        self.assertTrue(any(finding.startswith("implementation start (claude)") for finding in findings), findings)


if __name__ == "__main__":
    unittest.main()
