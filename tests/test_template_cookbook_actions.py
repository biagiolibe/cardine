"""Row TR2b: the audit prompt, cookbook, and code organization policy keep their recorded actions.

`docs/RULE_ENFORCEMENT_INVENTORY.md` (task 074) classifies each rule of the three files, assigns the
`moved` entries a destination, and folds `CODE_REVIEW_PROMPT.md` and `INTEGRATION_POLICY.md` into
`REVIEW.md`. This module pins that classification, the deletion of the folded files, and every
relative reference of the shipped templates.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from cardine.shared.context import TEMPLATE_CONDENSED, _context_relative_references, template_budget_findings
from cardine.templates.files import single_managed_files
from cardine_cli_support import ROOT
from test_template_entry_actions import INVENTORY, TEMPLATES, inventory_entries, read
from test_template_reference_actions import DEFERRED, MOVED as REFERENCE_MOVED

AUDIT = "docs/AUDIT_PROMPT_READ_ONLY.md"
COOKBOOK = "docs/OPERATOR_PROMPTS.md"
ORGANIZATION = "docs/CODE_ORGANIZATION.md"
CONDENSED = (AUDIT, COOKBOOK, ORGANIZATION)
FOLDED = ("docs/CODE_REVIEW_PROMPT.md", "docs/INTEGRATION_POLICY.md")
RETIRED_WITH_FOLDED = ("code-review-prompt", "task-worktree-integration", "ci-verified-validation",
                       "remote-branch-cleanup")
ENTRY_PREFIXES = ("AP-", "OP-", "CO-")

# Entries deleted from the three files: no phrase of the rule remains.
DELETED = {
    "OP-02": (COOKBOOK, "Report project status"),
    "OP-04": (COOKBOOK, "Analyze the accepted result"),
    "OP-05": (COOKBOOK, "Address review"),
    "OP-06": (COOKBOOK, "read-only workflow audit"),
    "OP-07": (COOKBOOK, "finalize-adoption"),
    "OP-09": (COOKBOOK, "SDD handoff"),
}
# Entries kept as advice or one line: (file, phrase).
KEPT = {
    "AP-01": (AUDIT, "The audit modifies nothing"),
    "OP-01": (COOKBOOK, "Advice: this cookbook is non-normative"),
    "OP-10": (COOKBOOK, "A task starts only when its dependencies are done"),
    "CO-01": (ORGANIZATION, "never widens scope"),
    "CO-02": (ORGANIZATION, "No `utils`, `common`, or `misc` modules"),
    "CO-03": (ORGANIZATION, "`## Project module map` section after this block"),
    "CO-04": (ORGANIZATION, "A root re-export is public API"),
    "CO-05": (ORGANIZATION, "Shared fixtures have one owner"),
    "CO-06": (ORGANIZATION, "stop and report the missing architectural decision"),
}
# Entries moved into the condensed files.
MOVED = {
    "AP-02": (AUDIT, "Run `cardine audit --project .` first"),
    "OP-03": (COOKBOOK, "## Design a change or decompose a milestone"),
    "OP-08": (COOKBOOK, "## Correct a documentation inconsistency"),
}
# Moved entries whose destination is a later work item, so no template states them.
LATER_ITEM = {"PW-12": "W10", "PW-26": "H9", "WL-07": "W10"}
# Moved entries that earlier rows condensed into another file.
EARLIER_ROW = {
    "CR-10": ("tasks/TASK_BLUEPRINT.md", "tier-3"),
    "CR-11": ("docs/EXECUTION_EVIDENCE_PROFILE.md", "Advice: diagnose progressively"),
}
# AP-02 drops queue-based items 6, 10, and 12; none of their machinery survives in the audit prompt.
AUDIT_REMOVED = ("INTEGRATION_POLICY", "CODE_REVIEW_PROMPT", "cardine task transition", "cardine review verdict",
                 "integrate stage", "reviewer author", "contract snapshot")


def entries() -> dict[str, dict[str, str]]:
    return {key: row for key, row in inventory_entries().items() if key.startswith(ENTRY_PREFIXES)}


class CookbookEntryActionTest(unittest.TestCase):
    def test_every_inventory_entry_of_the_three_files_has_a_recorded_disposition(self) -> None:
        recorded = {*DELETED, *KEPT, *MOVED}
        self.assertEqual(sorted(set(entries()) - recorded), [])
        self.assertEqual(sorted(recorded - set(entries())), [])

    def test_recorded_actions_match_the_inventory(self) -> None:
        inventory = entries()
        for entry in DELETED:
            with self.subTest(entry=entry):
                self.assertEqual(inventory[entry]["action"], "delete")
        for entry in KEPT:
            with self.subTest(entry=entry):
                self.assertIn(inventory[entry]["action"], {"advice", "one line"})
        for entry in MOVED:
            with self.subTest(entry=entry):
                self.assertEqual(inventory[entry]["action"], "moved")

    def test_deleted_rules_leave_no_phrase(self) -> None:
        for entry, (path, phrase) in DELETED.items():
            with self.subTest(entry=entry):
                self.assertNotIn(phrase, read(path))

    def test_kept_rules_are_stated(self) -> None:
        for entry, (path, phrase) in KEPT.items():
            with self.subTest(entry=entry):
                self.assertIn(phrase, read(path))

    def test_moved_rules_survive_in_their_destination(self) -> None:
        for entry, (path, phrase) in MOVED.items():
            with self.subTest(entry=entry):
                self.assertIn(phrase, read(path))

    def test_the_audit_prompt_drops_the_queue_machinery_it_no_longer_checks(self) -> None:
        for phrase in AUDIT_REMOVED:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, read(AUDIT))
        self.assertIn("## Project-specific checks", read(AUDIT))

    def test_the_organization_policy_labels_itself_advice_and_keeps_its_convention(self) -> None:
        text = read(ORGANIZATION)
        self.assertRegex(text, r"(?i)\bThis is advice\b")
        self.assertIn("## Module map", text)

    def test_no_condensed_file_describes_the_rejected_archive_or_retry_ref_ritual(self) -> None:
        for path in CONDENSED:
            for phrase in ("archive/rejected", "retry ref", "retry-ref", "rejected attempt"):
                with self.subTest(path=path, phrase=phrase):
                    self.assertNotIn(phrase, read(path).lower())


class MovedEntryDestinationTest(unittest.TestCase):
    """Every `moved` entry of the 074 inventory has a destination that exists today."""

    def destinations(self) -> dict[str, tuple[str, str]]:
        found = {key: value for key, value in REFERENCE_MOVED.items()}
        found.update(MOVED)
        found.update(EARLIER_ROW)
        return found

    def test_all_moved_entries_resolve_to_a_phrase_or_a_named_later_item(self) -> None:
        moved = sorted(key for key, row in inventory_entries().items() if row["action"] == "moved")
        self.assertEqual(len(moved), 14)
        found = self.destinations()
        for entry in moved:
            with self.subTest(entry=entry):
                if entry in LATER_ITEM:
                    self.assertIn(LATER_ITEM[entry], inventory_entries()[entry]["destination"])
                else:
                    path, phrase = found[entry]
                    self.assertIn(phrase, read(path))

    def test_a_later_item_entry_is_not_restated_in_any_template(self) -> None:
        self.assertNotIn("task state import", "\n".join(read(str(path.relative_to(TEMPLATES)))
                                                        for path in sorted(TEMPLATES.rglob("*.md"))))
        self.assertIsNone(DEFERRED["TB-11"])

    def test_no_destination_table_row_is_unassigned(self) -> None:
        for entry, row in inventory_entries().items():
            with self.subTest(entry=entry):
                self.assertTrue(row["destination"].strip())


class FoldedDocumentTest(unittest.TestCase):
    def test_the_folded_files_are_deleted_and_no_longer_managed(self) -> None:
        managed = {item.target.as_posix() for item in single_managed_files(TEMPLATES)}
        for path in FOLDED:
            with self.subTest(path=path):
                self.assertFalse((TEMPLATES / path).exists())
                self.assertNotIn(path, managed)

    def test_every_capability_that_lived_only_in_the_folded_files_is_retired_and_absent(self) -> None:
        catalog = json.loads((ROOT / "capabilities/markers-v1.json").read_text(encoding="utf-8"))["capabilities"]
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in sorted(TEMPLATES.rglob("*.md")))
        baselines = json.loads((ROOT / "capabilities/marker-baselines.json").read_text(encoding="utf-8"))
        for name in RETIRED_WITH_FOLDED:
            with self.subTest(name=name):
                self.assertTrue(catalog[name]["retired"])
                self.assertFalse(catalog[name]["required"])
                self.assertIsNone(catalog[name]["adoptionRecord"])
                self.assertNotIn(f"capability={name} ", corpus)
                self.assertFalse(any(name in markers for markers in baselines.values()))

    def test_no_shipped_template_still_names_a_folded_file(self) -> None:
        for path in sorted(TEMPLATES.rglob("*")):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for folded in FOLDED:
                    with self.subTest(path=path.relative_to(TEMPLATES).as_posix(), folded=folded):
                        self.assertNotIn(Path(folded).name, text)

    def test_the_review_procedure_holds_what_the_folded_files_carried(self) -> None:
        text = read("docs/workflows/REVIEW.md")
        for phrase in ("P0", "completed CI run", "Project review checklist"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


class TemplateReferenceTest(unittest.TestCase):
    def test_every_relative_reference_in_the_shipped_templates_resolves(self) -> None:
        missing = []
        for path in sorted(TEMPLATES.rglob("*.md")):
            relative = path.relative_to(TEMPLATES)
            for cited in _context_relative_references(relative, path.read_text(encoding="utf-8")):
                if not cited.suffix == ".md":
                    continue
                if not (TEMPLATES / cited).exists():
                    missing.append(f"{relative}: {cited}")
        self.assertEqual(missing, [])

    def test_the_resolver_would_catch_a_reference_to_a_deleted_file(self) -> None:
        cited = _context_relative_references(Path("docs/EXAMPLE.md"), "See `docs/CODE_REVIEW_PROMPT.md` and [x](INTEGRATION_POLICY.md).")
        self.assertEqual(cited, [Path("docs/CODE_REVIEW_PROMPT.md"), Path("docs/INTEGRATION_POLICY.md")])
        self.assertFalse(any((TEMPLATES / path).exists() for path in cited))


class CondensedBudgetTest(unittest.TestCase):
    def test_the_three_files_are_in_the_enforced_budget_list(self) -> None:
        for path in CONDENSED:
            with self.subTest(path=path):
                self.assertIn(path, TEMPLATE_CONDENSED)

    def test_the_whole_template_set_meets_its_budget(self) -> None:
        self.assertEqual(template_budget_findings(TEMPLATES), [])

    def test_the_condensed_files_stay_under_the_074_estimate_plus_margin(self) -> None:
        for path, ceiling in ((AUDIT, 315), (COOKBOOK, 295), (ORGANIZATION, 380)):
            with self.subTest(path=path):
                self.assertLessEqual(len(read(path).split()), ceiling)

    def test_the_catalog_requires_the_versions_the_templates_ship(self) -> None:
        catalog = json.loads((ROOT / "capabilities/markers-v1.json").read_text(encoding="utf-8"))["capabilities"]
        for path in (AUDIT, ORGANIZATION):
            for name, version in re.findall(r"capability=([a-z-]+) v(\d+)", read(path)):
                with self.subTest(path=path, capability=name):
                    self.assertEqual(catalog[name]["requiredVersion"], int(version))
                    self.assertGreaterEqual(int(version), 2)

    def test_the_inventory_records_the_row_disposition(self) -> None:
        self.assertIn("### TR2b disposition (task 113)", INVENTORY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
