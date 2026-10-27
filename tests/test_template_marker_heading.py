"""Framework CLI regression tests for template marker heading."""

from __future__ import annotations

from cardine_cli_support import ROOT
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from cardine.templates import files as owner_templates_files
from cardine.templates import migrations as owner_templates_migrations
from cardine.templates import marker_audit as owner_templates_marker_audit
MARKER_BEGIN = re.compile(r"<!-- CARDINE:BEGIN capability=([a-z0-9-]+) v(\d+) -->")
MARKER_END = "<!-- CARDINE:END -->"


class CapabilityMarkerTest(unittest.TestCase):
    """Markers exist and are well-formed.

    No detection or verification code reads these yet (that's phase 2+); this
    only guards the markers themselves against silent drift or malformed
    nesting as the templates keep changing.
    """

    WORKFLOW = ROOT / "templates" / "single"

    def marker_pairs(self, text: str) -> list[tuple[str, str]]:
        begins = MARKER_BEGIN.findall(text)
        end_count = text.count(MARKER_END)
        self.assertEqual(
            len(begins), end_count, "mismatched CARDINE:BEGIN/END marker count"
        )
        return begins

    def test_agents_and_claude_carry_expected_marker_versions(self) -> None:
        for name in ("AGENTS.md", "CLAUDE.md"):
            self.assertEqual(self.marker_pairs((self.WORKFLOW / name).read_text(encoding="utf-8")), [("command-triggers", "2")])
        self.assertEqual(self.marker_pairs((self.WORKFLOW / "docs/workflows/REMEDIATION.md").read_text(encoding="utf-8")), [("task-worktree-remediation", "2")])
        self.assertEqual(self.marker_pairs((self.WORKFLOW / "docs/LIFECYCLE_ORCHESTRATION.md").read_text(encoding="utf-8")),
                         [("lifecycle-orchestration", "3"), ("owner-acceptance-workflow", "2")])
        self.assertEqual(self.marker_pairs((self.WORKFLOW / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8")),
                         [("task-worktree-boundary", "3"), ("manual-verification-precondition", "2"), ("spike-routing", "2")])
    def test_host_impact_declaration_has_both_governed_shapes_and_evidence_routing(self) -> None:
        blueprint = (self.WORKFLOW / "tasks/TASK_BLUEPRINT.md").read_text(encoding="utf-8")
        implementation = (self.WORKFLOW / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8")
        self.assertIn(("task-blueprint", "9"), self.marker_pairs(blueprint))
        self.assertIn("Classification: NOT_APPLICABLE", blueprint)
        self.assertIn("Rationale:", blueprint)
        self.assertIn("Classification: REQUIRED", blueprint)
        self.assertIn("| Profile | Before | Intended after | Activation preconditions | Fallback |", blueprint)
        self.assertIn("- Static:", blueprint)
        self.assertIn("- Host execution:", blueprint)
        self.assertIn("- Manual activation:", blueprint)
        self.assertIn("Completion evidence:", blueprint)
        # The routing prose left the implementation procedure: the engine measures host observations.
        self.assertNotIn("host-impact-routing", dict(self.marker_pairs(implementation)))
        self.assertNotIn("HOST_IMPACT_DECLARATION_INVALID", implementation)
    def test_review_record_template_carries_its_own_marker(self) -> None:
        text = (self.WORKFLOW / "docs/REVIEW_RECORD_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(text),
            [("review-remediation-record", "2"), ("manual-verification-record", "1")],
        )

    def test_lifecycle_orchestration_carries_its_own_marker(self) -> None:
        text = (self.WORKFLOW / "docs/LIFECYCLE_ORCHESTRATION.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(text),
            [("lifecycle-orchestration", "3"), ("owner-acceptance-workflow", "2")],
        )
    def test_context_budget_policy_carries_its_capability_markers(self) -> None:
        text = (self.WORKFLOW / "docs/CONTEXT_READING_POLICY.md").read_text(encoding="utf-8")
        self.assertEqual(self.marker_pairs(text), [("bounded-context-readers", "2")])
    def test_execution_evidence_profile_is_stack_agnostic_and_configurable(self) -> None:
        policy = (self.WORKFLOW / "docs/CONTEXT_READING_POLICY.md").read_text(encoding="utf-8")
        profile = (self.WORKFLOW / "docs/EXECUTION_EVIDENCE_PROFILE.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("execution-evidence-profile", dict(self.marker_pairs(policy)))
        self.assertIn("Successful validation output", profile)
        self.assertIn("Failure diagnostics", profile)
        self.assertIn("Manual evidence", profile)
        self.assertNotIn("cargo", profile.lower())
    def test_reasoning_budget_contract_was_retired_from_governed_templates(self) -> None:
        """Migration 063 retires `reasoning-budget-contract` through `removes`;
        no managed Governed SDD text may require choosing, recording, matching,
        confirming, or escalating a reasoning level."""
        paths = [
            "tasks/TASK_BLUEPRINT.md",
            "docs/CONTEXT_READING_POLICY.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/OPERATOR_PROMPTS.md",
            "docs/INTEGRATION_POLICY.md",
            "docs/EXECUTION_EVIDENCE_PROFILE.md",
        ]
        texts = {path: (self.WORKFLOW / path).read_text(encoding="utf-8") for path in paths}

        self.assertIn(("task-blueprint", "9"), self.marker_pairs(texts["tasks/TASK_BLUEPRINT.md"]))
        self.assertIn(
            ("lifecycle-orchestration", "3"), self.marker_pairs(texts["docs/LIFECYCLE_ORCHESTRATION.md"])
        )
        self.assertNotIn(
            "reasoning-budget-contract", dict(self.marker_pairs(texts["docs/CONTEXT_READING_POLICY.md"]))
        )
        for path, text in texts.items():
            self.assertNotIn("reasoning-budget-contract", text, path)
            self.assertNotIn("`Reasoning`", text, path)
            self.assertNotIn("Reasoning justification", text, path)
            self.assertNotIn("reasoning level", text, path)
            self.assertNotIn("reasoning cap", text, path)
        self.assertIn("reasoning-budget-contract", owner_templates_migrations.retired_capability_ids(ROOT))
        self.assertNotIn("reasoning-budget-contract", owner_templates_migrations.capability_requirements(ROOT))

    def test_status_requests_use_the_status_command_not_a_reading_profile(self) -> None:
        policy = (self.WORKFLOW / "docs/CONTEXT_READING_POLICY.md").read_text(encoding="utf-8")
        prompts = (self.WORKFLOW / "docs/OPERATOR_PROMPTS.md").read_text(encoding="utf-8")
        self.assertIn("run `cardine status`", policy)
        self.assertIn("it is not an audit", policy)
        self.assertNotIn("minimal read-only status", policy.lower())
        self.assertNotIn("Use the minimal read-only status profile", prompts)
        self.assertNotIn("## 1. Report project status", prompts)
    def test_operator_prompts_resolve_locations_and_bound_framework_maintenance(self) -> None:
        prompts = (self.WORKFLOW / "docs/OPERATOR_PROMPTS.md").read_text(encoding="utf-8")
        self.assertIn("Resolve the canonical queue, task, and review-record locations", prompts)
        self.assertIn("cardine locations --project .", prompts)
        self.assertIn("Do not substitute a template path", prompts)
        self.assertIn("Class:\nSPIKE", prompts)
        self.assertIn("cardine upgrade --project . --check", prompts)
        self.assertIn("Do not run\n`cardine upgrade --apply`, `cardine adopt`, or `finalize-adoption`", prompts)
        self.assertNotIn("## 3. Design the next milestone or phase", prompts)
        # Prompts 1 and 1a (status and design alignment) left the cookbook: `cardine status` is the report.
        self.assertNotIn("## 1a. Align tech design for questions and future work (read-only)", prompts)
        self.assertIn("## 2. Design a change, decompose a milestone, or select the next phase", prompts)
    def test_ci_verified_validation_marker_in_each_of_its_three_docs(self) -> None:
        pull_request_policy = (self.WORKFLOW / "docs/INTEGRATION_POLICY.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(pull_request_policy),
            [
                ("task-worktree-integration", "2"),
                ("ci-verified-validation", "1"),
                ("remote-branch-cleanup", "1"),
            ],
        )

        code_review_prompt = (self.WORKFLOW / "docs/CODE_REVIEW_PROMPT.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(code_review_prompt),
            [("code-review-prompt", "2")],
        )

        completion_report = (self.WORKFLOW / "docs/COMPLETION_REPORT_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertEqual(
            self.marker_pairs(completion_report),
            [
                ("task-worktree-handoff", "2"),
                ("handoff-correction-redelivery", "2"),
                ("manual-verification-record", "1"),
                ("ci-verified-validation", "1"),
            ],
        )

    def test_manual_verification_precondition_gates_implementation_start(self) -> None:
        agents = (self.WORKFLOW / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8")
        self.assertIn(("manual-verification-precondition", "2"), self.marker_pairs(agents))
        self.assertIn("Manual verification: required", agents)
        self.assertIn("is `BLOCKED SCOPE_CHANGE_REQUIRED`", agents)
        self.assertIn("check its rationale first", agents)
        self.assertIn("readable as a value in the program", agents)
        self.assertIn("prove the evidence channel with a successful probe before implementing", agents)
        self.assertIn("Report a failed probe; do not search for an alternative", agents)
    def test_manual_verification_record_fields_in_completion_and_review_records(self) -> None:
        completion_report = (self.WORKFLOW / "docs/COMPLETION_REPORT_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertIn("Manual verification: `<none | screenshot path", completion_report)
        review_record = (self.WORKFLOW / "docs/REVIEW_RECORD_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertIn(("manual-verification-record", "1"), self.marker_pairs(review_record))
        self.assertIn("Manual verification observed:", review_record)
        self.assertIn("independently confirms", review_record)

    def test_project_workflow_carries_all_declared_baseline_capabilities(self) -> None:
        text = (ROOT / "templates/single/PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        pairs = self.marker_pairs(text)
        baselines = json.loads((ROOT / "capabilities/marker-baselines.json").read_text(encoding="utf-8"))
        expected = {
            capability: str(entry["version"])
            for capability, entry in baselines[
                "templates/single/PROJECT_WORKFLOW.md"
            ].items()
        }
        self.assertEqual(sorted(pairs), sorted(expected.items()))

    def test_git_workflow_block_drives_the_task_through_run(self) -> None:
        text = (self.WORKFLOW / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        start = text.index("capability=git-workflow")
        block = " ".join(text[start : text.index("<!-- CARDINE:END -->", start)].split())
        self.assertIn("cardine run <TASK-ID> --project <primary-checkout>", block)
        self.assertIn("`next.command`", block)
        self.assertIn("`stop.human_decision: true`", block)
        for retired in ("worktree advance", "closure-status", "action_required", "Validation skips"):
            self.assertNotIn(retired, block)
    def test_whole_file_baseline_capabilities_each_carry_one_marker(self) -> None:
        expectations = {
            "LANGUAGE_POLICY.md": ("language-policy", "1"),
            "tasks/TASK_BLUEPRINT.md": ("task-blueprint", "9"),
            "docs/CODE_ORGANIZATION.md": ("code-organization", "1"),
            "docs/AUDIT_PROMPT_READ_ONLY.md": ("audit-prompt", "1"),
        }
        for name, pair in expectations.items():
            text = (self.WORKFLOW / name).read_text(encoding="utf-8")
            self.assertEqual(self.marker_pairs(text), [pair], name)

    def test_language_policy_marker_excludes_the_per_project_language_line(self) -> None:
        """Corrective migration 013: meridian-init.md replaces
        [Conversation language] with the project's actual choice, so that
        line must sit outside the protected region or every correctly
        initialized project would fail meridian audit on day one."""
        text = (self.WORKFLOW / "LANGUAGE_POLICY.md").read_text(encoding="utf-8")
        match = re.search(
            r"<!-- CARDINE:BEGIN capability=language-policy v1 -->\n?(.*?)"
            r"<!-- CARDINE:END -->",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertNotIn("[Conversation language]", match.group(1))

    def test_agents_and_claude_carry_the_five_residual_capabilities(self) -> None:
        self.assertIn(("command-triggers", "2"), self.marker_pairs((self.WORKFLOW / "AGENTS.md").read_text(encoding="utf-8")))
        review = self.marker_pairs((self.WORKFLOW / "docs/workflows/REVIEW.md").read_text(encoding="utf-8"))
        self.assertEqual(review, [("task-worktree-review-procedure", "4")])
    def test_review_hands_off_through_the_command_before_substantive_inspection(self) -> None:
        review = (self.WORKFLOW / "docs/workflows/REVIEW.md").read_text(encoding="utf-8")
        handoff = review.index("Run `cardine review <TASK-ID> --project <primary-checkout>`")
        substantive = review.index("Read the task contract")
        self.assertLess(handoff, substantive)
        normalized = " ".join(review.split())
        self.assertIn("hands off only a committed `in_review` delivery with a clean worktree", normalized)
        self.assertIn("in the `work.worktree` it names", normalized)
        self.assertNotIn("uses that same primary checkout", review)
        self.assertNotIn("git switch <task-branch>", review)
        self.assertNotRegex(
            review,
            r"(?is)leave the primary checkout.{0,80}on the task branch",
        )
    def test_review_procedure_has_no_hardcoded_review_record_path(self) -> None:
        text = (self.WORKFLOW / "docs/workflows/REVIEW.md").read_text(encoding="utf-8")
        self.assertNotIn("tasks/reviews/<TASK-ID>.md", text)
        self.assertNotIn("review-mode-boundary", text)

class DuplicateHeadingAuditTest(unittest.TestCase):
    """`audit_duplicate_headings` (task 007's duplication-detection half):
    flags a capability whose marker sits under more than one distinct
    heading within the same managed file -- the mechanical signature of an
    accidental duplicate paste. Scoped to one file at a time: the same
    capability legitimately appears under different heading names across
    different consuming documents by design.
    """

    def test_real_templates_have_no_within_file_duplicate_headings(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        source = ROOT / "templates" / "single"
        for path in source.rglob("*"):
            if path.is_file():
                destination = project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        results = owner_templates_marker_audit.audit_duplicate_headings(project, ROOT, "single")
        self.assertEqual(results, [])

    def test_flags_a_capability_duplicated_under_two_headings_in_one_file(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        project.mkdir(parents=True)
        (project / "PROJECT_WORKFLOW.md").write_text(
            "## First section\n\n"
            "<!-- CARDINE:BEGIN capability=dup-rule v1 -->\ntext.\n<!-- CARDINE:END -->\n\n"
            "## Second section\n\n"
            "<!-- CARDINE:BEGIN capability=dup-rule v1 -->\ntext.\n<!-- CARDINE:END -->\n",
            encoding="utf-8",
        )

        class FakeManagedFile:
            def __init__(self, target: Path) -> None:
                self.target = target
                self.source = project / target

        original = owner_templates_files.managed_files
        owner_templates_files.managed_files = lambda framework_root, mode: [FakeManagedFile(Path("PROJECT_WORKFLOW.md"))]
        try:
            results = owner_templates_marker_audit.audit_duplicate_headings(project, ROOT, "single")
        finally:
            owner_templates_files.managed_files = original
        self.assertEqual(len(results), 1)
        status, message = results[0]
        self.assertEqual(status, "FAIL")
        self.assertIn("dup-rule", message)
        self.assertIn("First section", message)
        self.assertIn("Second section", message)

    def test_does_not_flag_the_same_capability_under_the_same_heading_name_across_files(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        project.mkdir(parents=True)
        for name in ("AGENTS.md", "CLAUDE.md"):
            (project / name).write_text(
                "## Command triggers\n\n"
                "<!-- CARDINE:BEGIN capability=command-triggers v1 -->\ntext.\n<!-- CARDINE:END -->\n",
                encoding="utf-8",
            )

        class FakeManagedFile:
            def __init__(self, target: Path) -> None:
                self.target = target
                self.source = project / target

        original = owner_templates_files.managed_files
        owner_templates_files.managed_files = lambda framework_root, mode: [
            FakeManagedFile(Path("AGENTS.md")),
            FakeManagedFile(Path("CLAUDE.md")),
        ]
        try:
            results = owner_templates_marker_audit.audit_duplicate_headings(project, ROOT, "single")
        finally:
            owner_templates_files.managed_files = original
        self.assertEqual(results, [])
