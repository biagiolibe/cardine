"""Row TR2a: every inventory entry for the five reference templates has its recorded action.

`docs/RULE_ENFORCEMENT_INVENTORY.md` (task 074) classifies each rule of the task blueprint, completion
report, execution profile, review record, and worktree lifecycle reference. This module pins that
classification to the condensed templates (a deleted rule leaves no phrase, a kept rule is present,
advice carries its label) and resolves the creation skeleton through the real contract reader.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from cardine.shared.context import TEMPLATE_CONDENSED
from cardine.tasks.contract import resolve_task_contract
from cardine_cli_support import ROOT
from project_config_support import write_project_config
from task_contract_support import VALIDATION
from test_template_entry_actions import INVENTORY, TEMPLATES, inventory_entries, paragraph_containing, read

BLUEPRINT = "tasks/TASK_BLUEPRINT.md"
REPORT = "docs/COMPLETION_REPORT_TEMPLATE.md"
PROFILE = "docs/EXECUTION_EVIDENCE_PROFILE.md"
RECORD = "docs/REVIEW_RECORD_TEMPLATE.md"
LIFECYCLE = "docs/WORKTREE_LIFECYCLE.md"
REFERENCE = (BLUEPRINT, REPORT, PROFILE, RECORD, LIFECYCLE)
ENTRY_PREFIXES = ("TB-", "CT-", "EE-", "RR-", "WL-")

# Entries deleted from the reference files: no phrase of the rule remains.
DELETED = {
    "TB-02": (BLUEPRINT, "SCOPE_CHANGE_REQUIRED"),
    "TB-10": (BLUEPRINT, "execution investigate"),
    "TB-12": (BLUEPRINT, "Research handoff"),
    "TB-13": (BLUEPRINT, "ready-check"),
    "CT-02": (REPORT, "Validation skips"),
    "CT-03": (REPORT, "Integration requirement"),
    "CT-04": (REPORT, "Deliver <TASK-ID> for review"),
    "CT-06": (REPORT, "sandbox skip"),
    "CT-08": (REPORT, "INTEGRATION_POLICY"),
    "EE-01": (PROFILE, "default threshold"),
    "EE-02": (PROFILE, "execution investigate"),
    "EE-03": (PROFILE, "tail -n 200"),
    "WL-01": (LIFECYCLE, "every emitted stop line"),
    "WL-06": (LIFECYCLE, "archive"),
    "WL-10": (LIFECYCLE, "worktree-path"),
    "WL-11": (LIFECYCLE, "handoff_worktree"),
}
# Entries kept as one line, advice, or an enforced statement: (file, phrase, action).
KEPT = {
    "TB-01": (BLUEPRINT, "An omitted option inherits the project default", "one line"),
    "TB-03": (BLUEPRINT, "probe code is never merged or pushed", "advice"),
    "TB-04": (BLUEPRINT, "required when `authorityRequired` is true", "one line"),
    "TB-06": (BLUEPRINT, "the engine refuses work outside them", "enforce"),
    "TB-07": (BLUEPRINT, "[Measurable observable outcome.]", "advice"),
    "TB-08": (BLUEPRINT, "## Technical Context", "one line"),
    "TB-09": (BLUEPRINT, "one per ID", "one line"),
    "CT-01": (REPORT, "make every deviation explicit", "advice"),
    "CT-05": (REPORT, "Do not claim completion while validation fails", "advice"),
    "CT-07": (REPORT, "name the screenshot path", "advice"),
    "EE-04": (PROFILE, "the full suite once after the last code change", "advice"),
    "EE-05": (PROFILE, "diagnose progressively", "advice"),
    "RR-01": (RECORD, "one durable review record per required-review task", "one line"),
    "RR-02": (RECORD, "## Attempt <N>", "one line"),
    "RR-04": (RECORD, "Manual verification observed:", "advice"),
}
# Entries moved to this file in condensed form, or to another row.
MOVED = {
    "TB-05": (BLUEPRINT, "Classification: REQUIRED"),
    "WL-02": (LIFECYCLE, "| Command | Runs in | `--project` |"),
    "WL-03": (LIFECYCLE, "Exit `0` is success, `2` blocked, `64` usage"),
    "WL-04": (LIFECYCLE, "`--worktree-root <old-root>`"),
    "WL-05": (LIFECYCLE, "worktree repair-base"),
    "WL-08": (LIFECYCLE, "`REUSE` proves"),
    "WL-09": (BLUEPRINT, "the task diff may add only its record"),
}
# Destined to a later work item, so the reference no longer states them.
DEFERRED = {"WL-07": (LIFECYCLE, "task state import"), "TB-11": None}
# Entries in the inventory that other rows own.
OTHER_ROW = {"RR-03": "REVIEW.md holds the severity rule (TR1a)"}


def entries() -> dict[str, dict[str, str]]:
    return {key: row for key, row in inventory_entries().items() if key.startswith(ENTRY_PREFIXES)}


class ReferenceEntryActionTest(unittest.TestCase):
    def test_every_inventory_entry_of_the_reference_files_has_a_recorded_disposition(self) -> None:
        recorded = {*DELETED, *KEPT, *MOVED, *DEFERRED, *OTHER_ROW}
        self.assertEqual(sorted(set(entries()) - recorded), [])
        self.assertEqual(sorted(recorded - set(entries())), [])

    def test_recorded_actions_match_the_inventory(self) -> None:
        inventory = entries()
        for entry in DELETED:
            with self.subTest(entry=entry):
                self.assertEqual(inventory[entry]["action"], "delete")
        for entry, (_, _, action) in KEPT.items():
            with self.subTest(entry=entry):
                self.assertEqual(inventory[entry]["action"], action)
        for entry in MOVED:
            with self.subTest(entry=entry):
                self.assertIn(inventory[entry]["action"], {"moved", "one line"})

    def test_deleted_rules_leave_no_phrase(self) -> None:
        for entry, (path, phrase) in DELETED.items():
            with self.subTest(entry=entry):
                self.assertNotIn(phrase, read(path))
        path, phrase = DEFERRED["WL-07"]
        self.assertNotIn(phrase, read(path))

    def test_kept_rules_are_stated_and_advice_is_labelled(self) -> None:
        for entry, (path, phrase, action) in KEPT.items():
            with self.subTest(entry=entry):
                text = read(path)
                self.assertIn(phrase, text)
                if action == "advice" and entry != "TB-07":
                    self.assertRegex(paragraph_containing(text, phrase), r"(?i)\badvice\b")
                elif action != "advice":
                    self.assertNotRegex(paragraph_containing(text, phrase)[: len(phrase) + 12].lower(), r"^advice")

    def test_moved_rules_survive_in_their_destination(self) -> None:
        for entry, (path, phrase) in MOVED.items():
            with self.subTest(entry=entry):
                self.assertIn(phrase, read(path))

    def test_the_inventory_records_the_one_discrepancy_the_blueprint_keeps(self) -> None:
        # TB-11 says delete, yet the preflight still demands the generated block, so the template keeps it.
        self.assertEqual(entries()["TB-11"]["action"], "delete")
        self.assertIn("## Execution contract — resolved", read(BLUEPRINT))
        self.assertIn("- Profile revision: `sha256:<generated profile digest>`", read(BLUEPRINT))
        self.assertIn("- Execution commands: `required via cardine execution`", read(BLUEPRINT))


class FreeFormReportTest(unittest.TestCase):
    LABELS = ("Files changed:", "Validation:", "Validation skips:", "Manual verification:", "Acceptance criteria:",
              "Isolated exploration:", "Blockers/deviations:", "Rule discrepancies:", "Branch:", "Worktree:")

    def test_no_report_label_or_fill_in_block_is_required(self) -> None:
        text = read(REPORT)
        self.assertNotIn("```", text)
        self.assertNotIn("## Completion Report", text)
        for label in self.LABELS:
            with self.subTest(label=label):
                self.assertNotRegex(text, rf"(?m)^- {re.escape(label)}")
        self.assertIn("free-form and optional", text)
        self.assertIn("no heading or label is required", text)

    def test_the_report_claims_no_authority(self) -> None:
        self.assertIn("nothing in it grants completion, validation, or review authority", read(REPORT))
        self.assertNotRegex(read(REPORT).lower(), r"\b(?:signature|signed|authentic\w*|cryptograph\w*)\b")

    def test_the_record_template_has_no_gating_field(self) -> None:
        text = read(RECORD)
        self.assertIn("machine state and the issued review operation decide the verdict", text)
        self.assertIn("never edit either by hand", text)


class CreationSkeletonTest(unittest.TestCase):
    """The condensed blueprint still resolves through the real contract reader, for every shape."""

    def filled(self, required_host: bool) -> str:
        text = read(BLUEPRINT)
        if not required_host:
            text = re.sub(r"```text\nClassification: REQUIRED\n.*?```\n", "", text, flags=re.DOTALL)
        else:
            text = re.sub(r"```text\nClassification: NOT_APPLICABLE\n.*?```\n", "", text, flags=re.DOTALL)
        for old, new in (
            ("# Task [ID] — [Title]", "# Task 001 — Shape fixture"),
            ("> **ID**: `[NNN]`", "> **ID**: `001`"),
            ("> **Priority**: [P0 / P1 / P2]", "> **Priority**: P1"),
            ("> **Estimate**: [~1h / ~2h / etc.]", "> **Estimate**: ~1h"),
            ("- **Depends on**: [none / TASK-ID, ...]", "- **Depends on**: none"),
            ("- `<validation-id>`: `<complete literal command, including its output bound and exit-status handling>`",
             "- `task-check`: `python3 -c 'pass'`"),
            ("Rationale: [why this change cannot alter any host-facing surface]", "Rationale: documentation only"),
            ("Policy outcome: [host-independent behavior protected]", "Policy outcome: hosts keep one behavior"),
            ("| [host/version/invocation/config layer] | [state] | [state] | [facts] | [safe behavior] |",
             "| codex 1 / exec / user | unverified | enforced | trust | advisory |"),
            ("- Static: [fixture or deterministic check]", "- Static: fixture"),
            ("- Host execution: [command/tool fixture and expected outcome]", "- Host execution: fixture run"),
            ("- Manual activation: [trust, install, or UI observation when needed]", "- Manual activation: none"),
            ("- [profile]: [source, observed result, or explicitly retained `unverified` state]",
             "- codex 1 / exec / user: unverified"),
        ):
            if old in text:
                text = text.replace(old, new)
        text = re.sub(r"^(?:Class|Review|Options|Manual verification(?: rationale)?): \[.*\]\n", "", text, flags=re.MULTILINE)
        text = text.replace("- [Path to the governing ADR or specification; required when `authorityRequired` is true.]",
                            "- docs/ADR.md")
        return text

    def resolve(self, text: str, preset: str = "lean") -> dict:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            (project / "tasks").mkdir()
            write_project_config(project, preset, validation=json.loads(json.dumps(VALIDATION)))
            (project / "tasks/001.md").write_text(text, encoding="utf-8")
            (project / "tasks/QUEUE.md").write_text(
                "| ID | Status | Task file |\n|---|---|---|\n| 001 | queued | [001](001.md) |\n", encoding="utf-8")
            return resolve_task_contract(project, "001")

    def test_a_standard_task_resolves_dependencies_validation_and_host_impact(self) -> None:
        for required in (False, True):
            with self.subTest(required_host=required):
                contract = self.resolve(self.filled(required))
                self.assertEqual(contract["dependencies"], [])
                self.assertEqual(contract["title"], "Task 001 — Shape fixture")
                self.assertEqual(contract["priority"], "P1")
                self.assertEqual(contract["hostImpact"]["classification"], "REQUIRED" if required else "NOT_APPLICABLE")
                self.assertEqual(contract["validation"]["commands"]["task-check"], "python3 -c 'pass'")
                self.assertEqual(contract["expectedCodeSurface"], ["src/example/**", "tests/test_example.py"])
                self.assertEqual(contract["authority"], ["docs/ADR.md"])

    def test_both_presets_resolve_the_same_options_shape(self) -> None:
        lean, governed = (self.resolve(self.filled(False), preset) for preset in ("lean", "governed"))
        self.assertEqual(lean["options"]["review"], "not_required")
        self.assertEqual(governed["options"]["review"], "required")

    def test_the_spike_fields_stay_readable(self) -> None:
        text = read(BLUEPRINT)
        for field in ("Class:       SPIKE", "Question:    [", "Timebox:     [", "Deliverable: an ADR"):
            self.assertIn(field, text)


class ReferenceBudgetTest(unittest.TestCase):
    def test_every_reference_file_is_in_the_enforced_budget_list(self) -> None:
        for path in REFERENCE:
            with self.subTest(path=path):
                self.assertIn(path, TEMPLATE_CONDENSED)

    def test_the_removed_blocks_are_retired_and_absent(self) -> None:
        catalog = json.loads((ROOT / "capabilities/markers-v1.json").read_text(encoding="utf-8"))["capabilities"]
        corpus = "\n".join(read(path) for path in REFERENCE)
        for name in ("task-worktree-handoff", "handoff-correction-redelivery", "investigation-scope"):
            with self.subTest(name=name):
                self.assertTrue(catalog[name]["retired"])
                self.assertFalse(catalog[name]["required"])
                self.assertNotIn(f"capability={name} ", corpus)

    def test_the_ci_block_leaves_the_report_but_stays_catalogued_for_the_integration_policy(self) -> None:
        # INTEGRATION_POLICY.md still carries the block until TR2b folds it into REVIEW.md.
        catalog = json.loads((ROOT / "capabilities/markers-v1.json").read_text(encoding="utf-8"))["capabilities"]
        self.assertFalse(catalog["ci-verified-validation"]["retired"])
        self.assertNotIn("capability=ci-verified-validation ", read(REPORT))
        self.assertIn("capability=ci-verified-validation ", read("docs/INTEGRATION_POLICY.md"))

    def test_every_remaining_block_is_catalogued_at_its_template_version(self) -> None:
        catalog = json.loads((ROOT / "capabilities/markers-v1.json").read_text(encoding="utf-8"))["capabilities"]
        for path in REFERENCE:
            for name, version in re.findall(r"capability=([a-z-]+) v(\d+)", read(path)):
                with self.subTest(path=path, capability=name):
                    self.assertEqual(catalog[name]["requiredVersion"], int(version))

    def test_the_inventory_still_lists_the_budget_the_files_were_condensed_to(self) -> None:
        self.assertIn("`docs/WORKTREE_LIFECYCLE.md` (reference)", INVENTORY.read_text(encoding="utf-8"))
        self.assertTrue(all((TEMPLATES / path).is_file() for path in REFERENCE))


if __name__ == "__main__":
    unittest.main()
