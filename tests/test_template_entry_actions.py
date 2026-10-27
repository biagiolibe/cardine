"""Row TR1a: every inventory entry for the always-read templates has its recorded action.

`docs/RULE_ENFORCEMENT_INVENTORY.md` (task 074) classifies each rule as
enforced and stated in one line, advice, or deleted. This module pins that
classification to the rewritten templates: a deleted rule leaves no phrase
behind, a kept rule is present, and advice carries its label.
"""

from __future__ import annotations

import json
import re
import unittest

from cardine_cli_support import ROOT

TEMPLATES = ROOT / "templates" / "single"
INVENTORY = ROOT / "docs" / "RULE_ENFORCEMENT_INVENTORY.md"
# The files this row rewrote, plus the cookbook whose status prompts it removed.
REWRITTEN = ("AGENTS.md", "CLAUDE.md", "PROJECT_WORKFLOW.md", "docs/workflows/IMPLEMENTATION.md",
             "docs/workflows/REVIEW.md", "docs/workflows/REMEDIATION.md",
             "docs/LIFECYCLE_ORCHESTRATION.md", "docs/CONTEXT_READING_POLICY.md")
WORKFLOW = "PROJECT_WORKFLOW.md"
IMPLEMENTATION = "docs/workflows/IMPLEMENTATION.md"
REVIEW = "docs/workflows/REVIEW.md"
REMEDIATION = "docs/workflows/REMEDIATION.md"
LIFECYCLE = "docs/LIFECYCLE_ORCHESTRATION.md"
CONTEXT = "docs/CONTEXT_READING_POLICY.md"

# Entries deleted from the rewritten files: no phrase of the rule remains.
DELETED = {
    "PW-02": "home-directory",
    "PW-03": "update the queue",
    "PW-04": "WORKFLOW_UNREADABLE",
    "PW-13": "integrate stage",
    "PW-14": "Execution assets",
    "PW-17": "taskIdentity.mode",
    "PW-18": "Reviewer-integrator",
    "PW-19": "records task status in the task record",
    "PW-27": "command location table",
    "PW-28": "worktree prepare",
    "PW-29": "execution start",
    "PW-31": "handoff_worktree",
    "PW-37": "REVIEW_REQUIRED",
    "PW-40": "completion handoff",
    "PW-47": "forge approval",
    "PW-54": "Rule discrepancies",
    "PW-55": "--validation-command",
    "PW-56": "Validation skips",
    "IM-05": "execution reconcile",
    "IM-08": "execution deliver",
    "IM-11": "HOST_IMPACT_DECLARATION_INVALID",
    "IM-14": "ready-check",
    "IM-15": "phase-reads",
    "RV-04": "git worktree list",
    "RV-17": "--author=",
    "IP-05": "git merge --no-ff",
    "IP-09": "push origin --delete",
    "LO-10": "same dedicated task worktree",
    "LO-12": "archive/rejected",
    "CR-01": "This policy reduces context",
    "CR-07": "execution investigate",
    "CR-08": "Minimal read-only status",
    "WL-01": "--worktree-root",
}
# Entries kept as one line, advice, or an enforced statement: (file, phrase, action).
KEPT = {
    "PW-01": (WORKFLOW, "before any edit, Git mutation, or completion claim", "one line"),
    "PW-05": (WORKFLOW, "review (`not_required` or `required`)", "one line"),
    "PW-06": (WORKFLOW, "An omitted optional section grants nothing", "one line"),
    "PW-07": (WORKFLOW, "When documents conflict, the first wins", "advice"),
    "PW-08": (WORKFLOW, "review required:      queued -> in_progress -> in_review", "one line"),
    "PW-09": (WORKFLOW, "a new commit invalidates an approval", "one line"),
    "PW-10": (WORKFLOW, "only status and verdict authority", "enforce"),
    "PW-16": (WORKFLOW, "`cardine locations`", "one line"),
    "PW-20": (WORKFLOW, "never in the primary checkout", "one line"),
    "PW-21": (WORKFLOW, "nobody approves their own work", "enforce"),
    "PW-23": (WORKFLOW, "`Proceed with <TASK-ID>` means: run `cardine run <TASK-ID>", "one line"),
    "PW-24": (WORKFLOW, "task, project default, preset", "one line"),
    "PW-25": (WORKFLOW, "`ANSWERED` only when", "enforce"),
    "PW-33": (WORKFLOW, "Do not ask for confirmation", "one line"),
    "PW-36a": (WORKFLOW, "creating, moving, or pushing a tag", "enforce"),
    "PW-36b": (WORKFLOW, "a force, deleting, or mirroring push", "enforce"),
    "PW-36c": (WORKFLOW, "a history rewrite", "one line"),
    "PW-36d": (WORKFLOW, "deleting an unmerged branch", "one line"),
    "PW-36e": (WORKFLOW, "bypassing a required independent review", "enforce"),
    "PW-36f": (WORKFLOW, "resolving a textual conflict", "one line"),
    "PW-36g": (WORKFLOW, "work outside the expected code surface", "enforce"),
    "PW-48": (WORKFLOW, "`stop.human_decision: true`", "one line"),
    "PW-49": (WORKFLOW, "`RULE_CONFLICT` and `VALIDATION_RETRY_LIMIT` are guardrails", "enforce"),
    "PW-51": (WORKFLOW, "`validationRetryLimit` counted failures", "enforce"),
    "PW-52": (WORKFLOW, "Guidance that no command backs is advice", "one line"),
    "PW-53": (WORKFLOW, "Never satisfy a gate by writing false state", "enforce"),
    "PW-57": (WORKFLOW, "`validationScoping`", "enforce"),
    "PW-58": (WORKFLOW, "verify each criterion before delivery", "advice"),
    "RT-01": ("AGENTS.md", "return `BLOCKED RULE_CONFLICT`", "one line"),
    "RT-02": ("AGENTS.md", "preserve unrelated changes", "enforce"),
    "RT-03": ("AGENTS.md", "read `docs/workflows/IMPLEMENTATION.md`", "one line"),
    "RT-04": ("AGENTS.md", "`docs/CODE_ORGANIZATION.md`", "advice"),
    "RT-05": ("CLAUDE.md", "generated from `AGENTS.md`", "one line"),
    "IM-10": (IMPLEMENTATION, "prove the evidence channel", "advice"),
    "IM-12": (IMPLEMENTATION, "without discovering an unknown", "advice"),
    "IM-08-kept": (IMPLEMENTATION, "clean committed HEAD", "one line"),
    "RV-06": (REVIEW, "committed `in_review` delivery with a clean worktree", "one line"),
    "RV-14": (REVIEW, "Edit no implementation file", "one line"),
    "RV-17-kept": (REVIEW, "--request-id <launch-request-id>", "enforce"),
    "IP-08": (REVIEW, "completed CI run for this exact commit", "enforce"),
    "CP-04": (REVIEW, "actionable findings", "advice"),
    "CP-05": (REVIEW, "## Project review checklist", "advice"),
    "CP-07": (REVIEW, "final report within ten lines", "advice"),
    "RR-03": (REVIEW, "`P0` and `P1` block approval", "advice"),
    "RM-02": (REMEDIATION, "reinterpret no finding", "advice"),
    "RM-04": (REMEDIATION, "needs new authority or scope", "advice"),
    "LO-02": (LIFECYCLE, "does not see the implementer's reasoning", "advice"),
    "LO-06": (LIFECYCLE, "`REVIEW_LOOP_EXHAUSTED`", "enforce"),
    "PW-46": (LIFECYCLE, "APPROVE --owner", "enforce"),
    "CR-02": (CONTEXT, "`Expected code surface`", "advice"),
    "CR-03": (CONTEXT, "Expand only when blocked", "advice"),
    "CR-05": (CONTEXT, "`cardine context authority <TASK-ID>`", "advice"),
    "CR-06": (CONTEXT, "Read large files by range", "advice"),
    "CR-07-kept": (CONTEXT, "explore in isolation", "advice"),
    "CR-13": (CONTEXT, "three bullets or fewer", "advice"),
}
# Entries whose destination is another row, with the reason this row leaves them.
DEFERRED = {
    "CR-14": "TR1b fixes the ceilings; this row keeps the parseable table",
}
# Removed from the cookbook, which TR2b condenses.
COOKBOOK_DELETED = {"OP-02": ("docs/OPERATOR_PROMPTS.md", "Report project status (read-only)")}


def read(relative: str) -> str:
    return (TEMPLATES / relative).read_text(encoding="utf-8")


def corpus(files=REWRITTEN) -> str:
    return "\n".join(read(path) for path in files)


def inventory_entries() -> dict[str, dict[str, str]]:
    entries = {}
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if line.startswith("| ") and len(cells) == 8 and re.match(r"^[A-Z]{2}-\d+[a-z]?$", cells[0]):
            entries[cells[0]] = dict(action=cells[5], destination=cells[7])
    return entries


def paragraph_containing(text: str, phrase: str) -> str:
    return next(paragraph for paragraph in text.split("\n\n") if phrase in paragraph)


class TemplateEntryActionTest(unittest.TestCase):
    def test_every_entry_destined_for_tr1_has_a_recorded_disposition(self) -> None:
        recorded = {key.split("-kept")[0] for key in (*DELETED, *KEPT, *DEFERRED, *COOKBOOK_DELETED)}
        destined = {entry for entry, row in inventory_entries().items()
                    if re.search(r"\bTR1\b", row["destination"]) and entry not in {"PW-18", "PW-54"}}
        self.assertEqual(sorted(destined - recorded), [])
        # PW-18 and PW-54 name another row first and are recorded as deleted.
        self.assertIn("PW-18", recorded)
        self.assertIn("PW-54", recorded)

    def test_recorded_actions_match_the_inventory(self) -> None:
        inventory = inventory_entries()
        for entry in (*DELETED, *DEFERRED, *COOKBOOK_DELETED):
            with self.subTest(entry=entry):
                self.assertIn(entry, inventory)
        for key, (_, _, action) in KEPT.items():
            entry = key.split("-kept")[0]
            with self.subTest(entry=entry):
                self.assertEqual(inventory[entry]["action"], action)

    def test_deleted_rules_leave_no_phrase_in_the_rewritten_files(self) -> None:
        text = corpus()
        for entry, phrase in DELETED.items():
            with self.subTest(entry=entry):
                self.assertNotIn(phrase, text)
        for entry, (path, phrase) in COOKBOOK_DELETED.items():
            with self.subTest(entry=entry):
                self.assertNotIn(phrase, read(path))

    def test_kept_rules_are_stated_and_advice_is_labelled(self) -> None:
        for key, (path, phrase, action) in KEPT.items():
            with self.subTest(entry=key):
                text = read(path)
                self.assertIn(phrase, text)
                if action == "advice":
                    self.assertRegex(paragraph_containing(text, phrase), r"(?i)\badvice\b")
                else:
                    # Enforced and one-line rules are statements, never labelled as advice.
                    self.assertNotRegex(paragraph_containing(text, phrase)[: len(phrase) + 12].lower(), r"^advice")

    def test_deferred_entries_keep_the_structure_their_row_needs(self) -> None:
        rows = re.findall(r"^\| All presets \| ([a-z]+) \| ([0-9]+) \|$", read(CONTEXT), re.MULTILINE)
        self.assertEqual([role for role, _ in rows],
                         ["status", "design", "implementation", "review", "remediation", "lifecycle"])


class TemplateClassificationTest(unittest.TestCase):
    def test_no_rewritten_file_tells_the_agent_to_stop_on_a_non_guardrail_code(self) -> None:
        stops = json.loads((ROOT / "capabilities/stop-codes-v1.json").read_text(encoding="utf-8"))["stops"]
        recoverable = {stop["code"] for stop in stops if not stop["human_decision"]}
        text = corpus()
        for code in sorted(recoverable):
            with self.subTest(code=code):
                self.assertNotRegex(text, rf"\bBLOCKED `?{code}\b")
                self.assertNotIn(f"`{code}`", text)

    def test_stop_codes_named_in_the_rewritten_files_are_registered_guardrails(self) -> None:
        stops = json.loads((ROOT / "capabilities/stop-codes-v1.json").read_text(encoding="utf-8"))["stops"]
        guardrails = {stop["code"] for stop in stops if stop["human_decision"]}
        registered = {stop["code"] for stop in stops}
        named = set(re.findall(r"\b([A-Z]{3,}(?:_[A-Z]+)+)\b", corpus())) & registered
        self.assertTrue(named)
        for code in sorted(named):
            with self.subTest(code=code):
                self.assertIn(code, guardrails)

    def test_no_stop_sits_inside_an_advice_clause(self) -> None:
        # The scope-change stop is the workflow's; only the judgment around it is advice.
        for path in REWRITTEN:
            for clause in re.findall(r"Advice:[^.\n]*(?:\.|$)", read(path), re.MULTILINE):
                with self.subTest(file=path, clause=clause[:60]):
                    self.assertNotIn("BLOCKED", clause)
                    self.assertNotIn("scope change", clause)

    def test_nothing_claims_authenticity_beyond_the_trust_boundary(self) -> None:
        text = corpus().lower()
        for claim in (r"signatures?", r"signed", r"tamper-proof", r"authentic\w*", r"cryptograph\w*"):
            with self.subTest(claim=claim):
                self.assertNotRegex(text, rf"\b{claim}\b")


class NoOrphanInstructionTest(unittest.TestCase):
    def test_every_cited_document_exists_in_the_template_set(self) -> None:
        for path in REWRITTEN:
            text = read(path)
            cited = set(re.findall(r"`([A-Za-z_./]+\.md)`", text)) | set(re.findall(r"\]\(([^)#]+\.md)", text))
            for document in sorted(cited):
                with self.subTest(file=path, cited=document):
                    self.assertTrue((TEMPLATES / document).is_file(), document)

    def test_every_route_resolves_and_every_rewritten_procedure_is_routed(self) -> None:
        for router in ("AGENTS.md", "CLAUDE.md"):
            block = re.search(r"capability=command-triggers v\d+ -->(.*?)<!-- CARDINE:END", read(router), re.DOTALL).group(1)
            routed = set(re.findall(r"(?:read|use) `([^`]+\.md)`", block))
            with self.subTest(router=router):
                self.assertTrue(all((TEMPLATES / target).is_file() for target in routed))
                self.assertTrue({IMPLEMENTATION, REVIEW, REMEDIATION, LIFECYCLE, CONTEXT} <= routed)
        self.assertNotIn("Restart rejected", corpus())

    def test_no_template_carries_a_retired_capability_marker(self) -> None:
        catalog = json.loads((ROOT / "capabilities/markers-v1.json").read_text(encoding="utf-8"))["capabilities"]
        retired = {name for name, entry in catalog.items() if entry["retired"]}
        for path in sorted(TEMPLATES.rglob("*.md")):
            used = set(re.findall(r"capability=([a-z-]+) v\d+", path.read_text(encoding="utf-8")))
            with self.subTest(file=path.relative_to(TEMPLATES).as_posix()):
                self.assertEqual(sorted(used & retired), [])


if __name__ == "__main__":
    unittest.main()
