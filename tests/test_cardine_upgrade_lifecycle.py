"""Framework CLI regression tests for upgrade and lifecycle."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cardine_cli  # noqa: E402
from cardine.templates import markers as owner_templates_markers
from cardine.templates import migrations as owner_templates_migrations

from cardine_cli_support import CLI, ROOT
from synthetic_upgrade_support import SyntheticUpgradeFixtureMixin, SyntheticFramework


class UpgradeLifecycleTest(SyntheticUpgradeFixtureMixin, unittest.TestCase):
    def baseline_version(self, mode: str, relative: str, capability: str) -> int:
        """The marker version the single template set ships; `mode` is a legacy key."""
        text = (ROOT / "templates/single" / relative).read_text(encoding="utf-8")
        version = owner_templates_markers.find_capability_marker_version(text, capability)
        self.assertIsNotNone(version, f"{relative} ships no {capability} marker")
        return version

    def test_spike_blueprint_upgrade_preserves_consumer_text_and_task_records(self) -> None:
        blueprint = self.framework / "templates/single/tasks/TASK_BLUEPRINT.md"
        current = blueprint.read_text(encoding="utf-8")
        previous = (ROOT / "tests/fixtures/task-blueprint-v15.md").read_text(encoding="utf-8")
        self.assertIn("capability=task-blueprint v15", previous)
        blueprint.write_text(previous, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.11\n", encoding="utf-8")
        self.copy_governed_templates()
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        installed = self.project / "tasks/TASK_BLUEPRINT.md"
        installed.write_text(previous + "\nConsumer-owned task note.\n", encoding="utf-8")
        records = {}
        for status in ("IN_PROGRESS", "ANSWERED", "INCONCLUSIVE"):
            record = self.project / "tasks" / f"probe-{status}.md"
            records[record] = f"Class: SPIKE\nStatus: {status}\n" + previous
            record.write_text(records[record], encoding="utf-8")
        blueprint.write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.12\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 027-synthetic-blueprint", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded = installed.read_text(encoding="utf-8")
        self.assertEqual(upgraded, current + "\nConsumer-owned task note.\n")
        self.assertNotIn("committed directly to `main`", upgraded)
        self.assertNotIn("Branch:      throwaway, never merged", upgraded)
        self.assertIn("probe code is never merged or pushed", upgraded)
        self.assertIn("ordinary worktree closure and integration", upgraded)
        for record, content in records.items():
            self.assertEqual(record.read_text(encoding="utf-8"), content)
        audit = self.run_cli("audit")
        # This legacy lock fixture has no capabilityProfiles; audit reports
        # UNVERIFIED for that declaration independently of marker integrity.
        self.assertIn("tasks/TASK_BLUEPRINT.md: capability=task-blueprint v10 matches the released text", audit.stdout)
        self.assertNotIn("FAIL           marker-integrity", audit.stdout)
        self.assertNotIn("DRIFT", audit.stdout)
        repeated = self.run_cli("upgrade", "--check")
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertNotIn("CONFLICT", repeated.stdout)

    def test_clean_upgrade_installs_host_impact_declarations_and_preserves_consumer_text(self) -> None:
        """Migration 043 upgrades the two managed host-impact files without
        replacing consumer-owned text outside their protected regions."""
        (self.framework / "VERSION").write_text("1.1.39\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)

        blueprint = self.framework / "templates/single/tasks/TASK_BLUEPRINT.md"
        current = blueprint.read_text(encoding="utf-8")
        declaration = current.split("\n## Host impact\n", 1)[1].split("\n## Expected code surface\n", 1)[0]
        previous = current.replace("capability=task-blueprint v9", "capability=task-blueprint v8", 1)
        previous = previous.replace("\n## Host impact\n" + declaration, "", 1)

        installed_baseline = self.project / ".cardine/baselines/1.1.39"
        for root in (self.project, installed_baseline):
            path = root / "tasks/TASK_BLUEPRINT.md"
            path.write_text(previous, encoding="utf-8")
        (self.project / "tasks/TASK_BLUEPRINT.md").write_text(
            previous + "\nProject-owned task note.\n", encoding="utf-8"
        )

        implementation = self.framework / "templates/single/docs/workflows/IMPLEMENTATION.md"
        routed = implementation.read_text(encoding="utf-8")
        routing = routed.split(
            "<!-- CARDINE:BEGIN capability=spike-routing v2 -->", 1
        )[1].split("<!-- CARDINE:END -->", 1)[0]
        previous_routed = routed.replace(
            "<!-- CARDINE:BEGIN capability=spike-routing v2 -->" + routing + "<!-- CARDINE:END -->\n",
            "",
            1,
        )
        self.assertNotEqual(previous_routed, routed)
        for root in (self.project, installed_baseline):
            path = root / "docs/workflows/IMPLEMENTATION.md"
            path.write_text(previous_routed, encoding="utf-8")

        (self.framework / "VERSION").write_text("1.1.40\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 007-synthetic-host", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded_blueprint = (self.project / "tasks/TASK_BLUEPRINT.md").read_text(encoding="utf-8")
        self.assertIn("capability=task-blueprint v10", upgraded_blueprint)
        self.assertIn("Classification: NOT_APPLICABLE", upgraded_blueprint)
        self.assertIn("Classification: REQUIRED", upgraded_blueprint)
        self.assertIn("Project-owned task note.", upgraded_blueprint)
        upgraded_routing = (self.project / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8")
        self.assertIn("capability=spike-routing v2", upgraded_routing)
        self.assertIn("is a scope change: name the spike task", upgraded_routing)
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.40")
        self.assertEqual(manifest["appliedMigrations"][-1], "007-synthetic-host")

    def test_clean_upgrade_installs_isolated_task_worktree_contract(self) -> None:
        """Migration 045 delivers the worktree contract to an existing adopter."""
        workflow = self.framework / "templates/single"
        relative_paths = (
            "PROJECT_WORKFLOW.md",
            "docs/AUDIT_PROMPT_READ_ONLY.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/INTEGRATION_POLICY.md",
            "docs/workflows/IMPLEMENTATION.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/workflows/REMEDIATION.md",
            "docs/workflows/REVIEW.md",
        )
        current = {
            relative: (workflow / relative).read_text(encoding="utf-8")
            for relative in relative_paths
        }
        new_capabilities = (
            "task-worktree-boundary",
            "task-worktree-remediation",
            "task-worktree-review",
            "task-worktree-integration",
            "task-worktree-review-procedure",
            "task-worktree-lifecycle",
        )

        for relative, text in current.items():
            previous = text
            for capability in new_capabilities:
                previous = re.sub(
                    rf"<!-- CARDINE:BEGIN capability={capability} v[123] -->.*?<!-- CARDINE:END -->\n?",
                    "",
                    previous,
                    flags=re.DOTALL,
                )
            previous = previous.replace("capability=roles v3", "capability=roles v1")
            previous = previous.replace("capability=git-workflow v5", "capability=git-workflow v1")
            previous = previous.replace("capability=audit-prompt v3", "capability=audit-prompt v1")
            previous = previous.replace(
                "capability=lifecycle-orchestration v6",
                "capability=lifecycle-orchestration v3",
            )
            previous = re.sub(
                r"<!-- CARDINE:BEGIN capability=task-worktree-handoff v3 -->.*?<!-- CARDINE:END -->",
                "- Branch: `<task-branch>`\n"
                "- Implementation commit: `<commit SHA>`\n"
                "- Base `main` commit: `<commit SHA>`",
                previous,
                flags=re.DOTALL,
            )
            for root in (workflow, self.project):
                (root / relative).write_text(previous, encoding="utf-8")

        (self.framework / "VERSION").write_text("1.1.41\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        project_workflow = self.project / "PROJECT_WORKFLOW.md"
        project_workflow.write_text(
            project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned note.\n",
            encoding="utf-8",
        )

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.48\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 009-synthetic-worktree", checked.stdout)
        self.assertIn("MIGRATION 010-synthetic-evidence", checked.stdout)
        self.assertIn("MIGRATION 011-synthetic-access", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn(f"capability=git-workflow v{self.baseline_version('single', 'PROJECT_WORKFLOW.md', 'git-workflow')}", project_workflow.read_text(encoding="utf-8"))
        self.assertIn("Consumer-owned note.", project_workflow.read_text(encoding="utf-8"))
        self.assertIn(
            "capability=task-worktree-boundary v3",
            (self.project / "docs/workflows/IMPLEMENTATION.md").read_text(encoding="utf-8"),
        )
        report = (self.project / "docs/COMPLETION_REPORT_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertIn("free-form and optional", report)
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.48")
        self.assertEqual(manifest["appliedMigrations"][-1], "013-synthetic-bounded")
        audited = self.run_cli("audit", "--mode", "single")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("declaration/legacy-compatibility", audited.stdout)

    def test_clean_upgrade_installs_integration_evidence_reuse_contract(self) -> None:
        """Migration 046 upgrades every changed integration capability."""
        workflow = self.framework / "templates/single"
        changed_paths = (
            "PROJECT_WORKFLOW.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/INTEGRATION_POLICY.md",
            "docs/workflows/REVIEW.md",
        )
        current = {
            relative: (workflow / relative).read_text(encoding="utf-8")
            for relative in changed_paths
        }
        previous_versions = {
            "git-workflow": (8, 3),
            "lifecycle-orchestration": (7, 4),
            "task-worktree-review": (4, 1),
            "task-worktree-integration": (3, 1),
            "task-worktree-review-procedure": (5, 1),
            "task-worktree-handoff": (3, 1),
        }
        for relative, text in current.items():
            previous = text
            previous = re.sub(
                r"<!-- CARDINE:BEGIN capability=codex-worktree-access v\d+ -->.*?<!-- CARDINE:END -->\n?",
                "",
                previous,
                flags=re.DOTALL,
            )
            for capability, (new, old) in previous_versions.items():
                previous = previous.replace(
                    f"capability={capability} v{new}",
                    f"capability={capability} v{old}",
                )
            for root in (workflow, self.project):
                (root / relative).write_text(previous, encoding="utf-8")

        (self.framework / "VERSION").write_text("1.1.42\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        project_workflow = self.project / "PROJECT_WORKFLOW.md"
        project_workflow.write_text(
            project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned note.\n",
            encoding="utf-8",
        )

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.48\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 010-synthetic-evidence", checked.stdout)
        self.assertIn("MIGRATION 011-synthetic-access", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn(f"capability=git-workflow v{self.baseline_version('single', 'PROJECT_WORKFLOW.md', 'git-workflow')}", project_workflow.read_text(encoding="utf-8"))
        self.assertIn("Consumer-owned note.", project_workflow.read_text(encoding="utf-8"))
        self.assertIn(
            "capability=manual-verification-record v2",
            (self.project / "docs/COMPLETION_REPORT_TEMPLATE.md").read_text(encoding="utf-8"),
        )
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.48")
        self.assertEqual(manifest["appliedMigrations"][-1], "013-synthetic-bounded")

    def test_upgrade_replaces_conflicting_review_blocks_and_preserves_consumer_text(self) -> None:
        """Migration 050 replaces the distributed checkout conflict in place."""
        workflow = self.framework / "templates/single"
        paths = (
            "PROJECT_WORKFLOW.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/workflows/REVIEW.md",
        )
        current = {
            relative: (workflow / relative).read_text(encoding="utf-8")
            for relative in paths
        }
        legacy_handoff = """<!-- CARDINE:BEGIN capability=implementer-reviewer-handoff v1 -->
## Implementer-to-reviewer handoff

After validation, create the task commit and push the task branch once for each
review attempt. The completion handoff must record the branch name,
implementation commit, and base `main` commit. Leave the primary checkout
clean and on the task branch; do not switch back to `main`.

The reviewer-integrator uses that same primary checkout in a fresh agent session that did not write the implementation. If the reviewer session starts on clean `main`, run `git switch <task-branch>`. If the branch is missing locally, or a dirty checkout prevents switching, return `BLOCKED` with the exact condition.

For `Review: REQUIRED`, the reviewer must never push the task branch. On
`CHANGES_REQUESTED`, it commits only the review record and matching task/queue
transition to `IN_PROGRESS`; the implementer then resolves and pushes the next
review attempt. Before accepting, run `git merge-base --is-ancestor main
<task-branch>`. If it fails, do not mark the task `ACCEPTED`; return `BLOCKED`
with no fetch, rebase, non-fast-forward merge, or force-push recovery. If it
passes, create the local review-and-status `ACCEPTED` commit, switch to `main`,
fast-forward merge the task branch, push `main` exactly once, and delete the
local task branch. For `Review: NOT_REQUIRED`, the implementer performs the
same acceptance commit and main integration after validation. Owner acceptance
is status-only and does not automatically integrate the branch.
<!-- CARDINE:END -->"""
        legacy_preflight = """<!-- CARDINE:BEGIN capability=task-worktree-review-procedure v2 -->
This block supersedes the checkout, ancestry, integration, and cleanup steps in
the legacy handoff block above. The completion handoff also records the
absolute task-worktree path and current task commit. Stop the implementer and
leave that worktree clean before a fresh reviewer session uses it. Verify its
registered path, branch, HEAD, cleanliness, and handoff commits. Never switch
the primary checkout to the task branch or review concurrently with an
implementer. After approval, commit the review and `ACCEPTED` state on the task
branch, then use the serialized integration transaction in
`PROJECT_WORKFLOW.md`. The validated task commit must be an ancestor of task
HEAD, with only permitted lifecycle records in the intervening diff, and the
validated base must be an ancestor of the validated commit. Current `main` may have advanced; reuse
evidence, run the bounded gate, select full validation, or return `BLOCKED`
only through that transaction's deterministic decision. Independent review,
acceptance evidence, and forge gates remain mandatory. Cleanup removes the
worktree before the branch only after validated integration succeeds.
<!-- CARDINE:END -->"""

        previous = current.copy()
        previous["docs/workflows/REVIEW.md"] = re.sub(
            r"<!-- CARDINE:BEGIN capability=task-worktree-review-procedure v9 -->.*?<!-- CARDINE:END -->",
            legacy_preflight,
            previous["docs/workflows/REVIEW.md"],
            count=1,
            flags=re.DOTALL,
        )
        previous["docs/workflows/REVIEW.md"] = re.sub(
            r"<!-- CARDINE:BEGIN capability=implementer-reviewer-handoff v2 -->.*?<!-- CARDINE:END -->",
            legacy_handoff,
            previous["docs/workflows/REVIEW.md"],
            count=1,
            flags=re.DOTALL,
        )
        previous["docs/CODE_REVIEW_PROMPT.md"] = previous["docs/CODE_REVIEW_PROMPT.md"].replace(
            "capability=task-worktree-review v4", "capability=task-worktree-review v2"
        )
        previous["PROJECT_WORKFLOW.md"] = previous["PROJECT_WORKFLOW.md"].replace(
            "capability=git-workflow v9", "capability=git-workflow v4"
        )
        previous["docs/LIFECYCLE_ORCHESTRATION.md"] = previous[
            "docs/LIFECYCLE_ORCHESTRATION.md"
        ].replace("capability=lifecycle-orchestration v10", "capability=lifecycle-orchestration v5")

        for relative, text in previous.items():
            (workflow / relative).write_text(text, encoding="utf-8")
            (self.project / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.46\n", encoding="utf-8")
        locked = self.run_cli("lock", "--mode", "single")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)

        review = self.project / "docs/workflows/REVIEW.md"
        review.write_text(
            review.read_text(encoding="utf-8") + "\nConsumer-owned review note.\n",
            encoding="utf-8",
        )
        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.48\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 012-synthetic-review", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded = review.read_text(encoding="utf-8")
        self.assertNotIn("capability=implementer-reviewer-handoff", upgraded)
        self.assertIn("capability=task-worktree-review-procedure v4", upgraded)
        self.assertIn("Consumer-owned review note.", upgraded)
        self.assertNotIn("uses that same primary checkout", upgraded)
        self.assertNotIn("git switch <task-branch>", upgraded)
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.48")
        self.assertEqual(manifest["appliedMigrations"][-1], "013-synthetic-bounded")

    def test_upgrade_installs_codex_profile_recovery_across_a_cli_only_release(self) -> None:
        """Migration 053 reaches a baseline-1.1.49 project locked under CLI-only release 1.1.50."""
        recovery = re.compile(
            r"\n\nThe reviewer is a separate session from the implementer.*?(?=<!-- CARDINE:END -->)",
            re.DOTALL,
        )
        for mode in ("single", "single"):
            with self.subTest(mode):
                shutil.rmtree(self.project)
                self.project.mkdir()
                workflow = self.framework / "templates/single"
                for path in workflow.rglob("*"):
                    if path.is_file():
                        destination = self.project / path.relative_to(workflow)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, destination)
                template = workflow / "PROJECT_WORKFLOW.md"
                current = template.read_text(encoding="utf-8")
                previous = recovery.sub("\n", current, count=1).replace(
                    "capability=review-policy v2", "capability=review-policy v1"
                )
                self.assertNotEqual(previous, current)
                template.write_text(previous, encoding="utf-8")
                (self.project / "PROJECT_WORKFLOW.md").write_text(previous, encoding="utf-8")
                (self.framework / "VERSION").write_text("1.1.50\n", encoding="utf-8")
                locked = self.run_cli("lock", "--mode", mode)
                self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
                manifest_path = self.project / ".cardine/manifest.json"
                locked_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(locked_manifest["frameworkVersion"], "1.1.50")
                self.assertEqual(locked_manifest["workflowBaselineVersion"], "1.1.49")
                project_workflow = self.project / "PROJECT_WORKFLOW.md"
                project_workflow.write_text(
                    project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned note.\n", encoding="utf-8"
                )

                template.write_text(current, encoding="utf-8")
                (self.framework / "VERSION").write_text("1.1.51\n", encoding="utf-8")
                checked = self.run_cli("upgrade", "--check")
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                self.assertIn("MIGRATION 015-synthetic-repair", checked.stdout)
                applied = self.run_cli("upgrade", "--apply")
                self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
                upgraded = project_workflow.read_text(encoding="utf-8")
                self.assertIn("capability=review-policy v2", upgraded)
                self.assertIn("nobody approves their own work", upgraded)
                self.assertIn("Consumer-owned note.", upgraded)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["frameworkVersion"], "1.1.51")
                self.assertEqual(manifest["workflowBaselineVersion"], "1.1.51")
                self.assertEqual(manifest["appliedMigrations"][-1], "015-synthetic-repair")

    def test_upgrade_installs_manual_proceed_worktree_rule_and_preserves_consumer_text(self) -> None:
        implementation, project_workflow = self.configure_1_1_53_to_1_1_54_manual_proceed_upgrade()
        project_workflow.write_text(
            project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned worktree note.\n",
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 017-synthetic-manual", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        self.assertIn("capability=task-worktree-boundary v3", implementation.read_text(encoding="utf-8"))
        self.assertIn("Run `cardine run <TASK-ID> --project <primary-checkout>`", implementation.read_text(encoding="utf-8"))
        upgraded_workflow = project_workflow.read_text(encoding="utf-8")
        self.assertIn(f"capability=workflow-mode-lock v{self.baseline_version('single', 'PROJECT_WORKFLOW.md', 'workflow-mode-lock')}", upgraded_workflow)
        self.assertIn("Consumer-owned worktree note.", upgraded_workflow)
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.54")
        self.assertEqual(manifest["appliedMigrations"][-1], "017-synthetic-manual")

    def test_upgrade_reports_bounded_conflict_for_custom_implementation_procedure(self) -> None:
        implementation, _ = self.configure_1_1_53_to_1_1_54_manual_proceed_upgrade()
        customized = implementation.read_text(encoding="utf-8").replace(
            "The coordinator runs `meridian worktree prepare`",
            "Our coordinator runs `meridian worktree prepare`",
            1,
        )
        implementation.write_text(customized, encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertIn("CONFLICT docs/workflows/IMPLEMENTATION.md", applied.stdout)
        self.assertEqual(implementation.read_text(encoding="utf-8"), customized)

    def test_upgrade_installs_self_referential_handoff_rules_and_preserves_consumer_text(self) -> None:
        workflow = self.framework / "templates/single"
        paths = (
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "docs/workflows/REVIEW.md",
        )
        current = {relative: (workflow / relative).read_text(encoding="utf-8") for relative in paths}
        previous = {
            relative: text.replace("task-worktree-handoff v5", "task-worktree-handoff v3").replace(
                "task-worktree-review-procedure v4", "task-worktree-review-procedure v3"
            )
            for relative, text in current.items()
        }
        for relative, text in previous.items():
            (workflow / relative).write_text(text, encoding="utf-8")
            destination = self.project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.54\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        report = self.project / "docs/COMPLETION_REPORT_TEMPLATE.md"
        report.write_text(report.read_text(encoding="utf-8") + "\nConsumer-owned handoff note.\n", encoding="utf-8")

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 018-synthetic-handoff", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded_report = report.read_text(encoding="utf-8")
        self.assertIn("capability=manual-verification-record v2", upgraded_report)
        self.assertNotIn("Current task commit", upgraded_report)
        self.assertIn("Consumer-owned handoff note.", upgraded_report)
        upgraded_review = (self.project / "docs/workflows/REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("capability=task-worktree-review-procedure v4", upgraded_review)
        self.assertIn("hands off only a committed `in_review` delivery with a clean worktree", " ".join(upgraded_review.split()))
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.55")
        self.assertEqual(manifest["appliedMigrations"][-1], "018-synthetic-handoff")

    def test_1_4_0_template_capabilities_are_required(self) -> None:
        requirements = owner_templates_migrations.capability_requirements(self.framework)
        self.assertNotIn("worktree-budget-retirement", requirements)
        for capability, version in (("worktree-command-locations", 3),):
            with self.subTest(capability=capability):
                self.assertEqual(requirements[capability], (version, "030-synthetic-delivery"))
        self.assertNotIn("handoff-correction-redelivery", requirements)

    def test_pristine_1_2_15_lean_upgrade_installs_task_close(self) -> None:
        workflow = self.framework / "templates/single"
        paths = ("PROJECT_WORKFLOW.md",)
        current = {name: (workflow / name).read_text() for name in paths}
        old_closure = "When closure requires machine task state, run `meridian task transition <TASK-ID> DONE` in the task worktree after validation and before archiving the record, then commit the state file with the completion records. Never edit status or verdict fields by hand."
        for name in paths:
            text = current[name].replace("capability=git-workflow v4", "capability=git-workflow v3")
            text = re.sub(r"After validation, commit the completed task record and handoff, then run.*?with the validation evidence\.", old_closure, text)
            text = text.replace("capability=bounded-worktree-lifecycle v7", "capability=bounded-worktree-lifecycle v6").replace(
                "writer confirmation, except when the record is already archived:\nskip execution start, commit staged closure records, then run worktree advance.",
                "writer confirmation.")
            (workflow / name).write_text(text)
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.15\n")
        locked = self.run_cli("lock", "--mode", "single")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        for name, text in current.items():
            (workflow / name).write_text(text)
        (self.framework / "VERSION").write_text("1.3.0\n")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 029-synthetic-close", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        for name, text in current.items():
            self.assertEqual((self.project / name).read_text(), text)
            self.assertIn("cardine run <TASK-ID> --project <primary-checkout>", text)
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text())
        self.assertEqual(manifest["workflowBaselineVersion"], "1.3.0")
        self.assertEqual(manifest["appliedMigrations"][-1], "029-synthetic-close")

    def test_upgrade_installs_lean_closure_procedure_and_preserves_consumer_text(self) -> None:
        workflow = self.framework / "templates/single"
        paths = ("PROJECT_WORKFLOW.md",)
        current = {relative: (workflow / relative).read_text(encoding="utf-8") for relative in paths}
        previous = {
            relative: re.sub(
                r"\n<!-- CARDINE:BEGIN capability=git-workflow v4 -->.*?<!-- CARDINE:END -->\n",
                "\n",
                text,
                flags=re.DOTALL,
            )
            for relative, text in current.items()
        }
        for relative, text in previous.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)

        for relative, text in previous.items():
            self.assertEqual((self.project / relative).read_text(encoding="utf-8"), text)
        agents = self.project / "PROJECT_WORKFLOW.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "\nConsumer-owned closure note.\n", encoding="utf-8")

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.4\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 020-synthetic-lean-closure", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        for relative in paths:
            upgraded = (self.project / relative).read_text(encoding="utf-8")
            self.assertIn(f"CARDINE:BEGIN capability=git-workflow v{self.baseline_version('single', relative, 'git-workflow')}", upgraded)
            self.assertIn("Stop only for a denied action, a scope change", upgraded)
        self.assertIn("Consumer-owned closure note.", agents.read_text(encoding="utf-8"))
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.2.4")
        self.assertEqual(manifest["appliedMigrations"][-1], "020-synthetic-lean-closure")

    def test_upgrade_installs_governed_closure_procedure_and_preserves_consumer_text(self) -> None:
        workflow = self.framework / "templates/single"
        paths = (
            "PROJECT_WORKFLOW.md",
            "docs/workflows/IMPLEMENTATION.md",
            "docs/workflows/REVIEW.md",
        )
        current = {relative: (workflow / relative).read_text(encoding="utf-8") for relative in paths}
        previous = {
            "PROJECT_WORKFLOW.md": re.sub(
                r"\n<!-- CARDINE:BEGIN capability=git-workflow v4 -->.*?<!-- CARDINE:END -->\n",
                "\n",
                current["PROJECT_WORKFLOW.md"],
                flags=re.DOTALL,
            ),
            "docs/workflows/IMPLEMENTATION.md": re.sub(
                r"\n<!-- CARDINE:BEGIN capability=task-worktree-boundary v3 -->.*?<!-- CARDINE:END -->\n",
                "\n",
                current["docs/workflows/IMPLEMENTATION.md"],
                flags=re.DOTALL,
            ),
            "docs/workflows/REVIEW.md": re.sub(
                r"\n<!-- CARDINE:BEGIN capability=task-worktree-review-procedure v4 -->.*?<!-- CARDINE:END -->\n",
                "\n",
                current["docs/workflows/REVIEW.md"],
                flags=re.DOTALL,
            ),
        }
        for relative, text in previous.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.4\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)

        implementation = self.project / "docs/workflows/IMPLEMENTATION.md"
        implementation.write_text(
            implementation.read_text(encoding="utf-8") + "\nConsumer-owned closure note.\n",
            encoding="utf-8",
        )

        for relative, text in current.items():
            (workflow / relative).write_text(text, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.5\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 021-synthetic-governed-closure", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded_workflow = (self.project / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        upgraded_implementation = implementation.read_text(encoding="utf-8")
        upgraded_review = (self.project / "docs/workflows/REVIEW.md").read_text(encoding="utf-8")
        self.assertIn(f"capability=git-workflow v{self.baseline_version('single', 'PROJECT_WORKFLOW.md', 'git-workflow')}", upgraded_workflow)
        self.assertIn("`Proceed with <TASK-ID>` means: run `cardine run <TASK-ID>", upgraded_workflow)
        self.assertIn("capability=task-worktree-boundary v3", upgraded_implementation)
        self.assertIn("Stop writing once it asks for review", upgraded_implementation)
        self.assertIn("capability=task-worktree-review-procedure v4", upgraded_review)
        self.assertIn("`cardine run` lands the task", upgraded_review)
        self.assertIn("Consumer-owned closure note.", upgraded_implementation)
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflowBaselineVersion"], "1.2.5")
        self.assertEqual(manifest["appliedMigrations"][-1], "021-synthetic-governed-closure")

    def test_upgrade_installs_code_organization_v2_and_preserves_the_project_module_map(self) -> None:
        workflow = self.framework / "templates/single"
        relative = "docs/CODE_ORGANIZATION.md"
        current = (workflow / relative).read_text(encoding="utf-8")
        new_sentence = re.search(r"^The project records its layered module map.*$", current, re.MULTILINE)
        self.assertNotIn("\n## Project module map", current)
        self.assertIsNotNone(new_sentence)
        previous = current.replace("capability=code-organization v1", "capability=code-organization v1").replace(
            new_sentence.group(0),
            "Record this project's actual layered module map in its own architecture documentation, not in this file.",
        )
        self.assertNotEqual(previous, current)
        (workflow / relative).write_text(previous, encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)

        module_map = "\n## Project module map\n\nThe `core` module owns domain rules; `app` depends on `core`.\n"
        organization = self.project / relative
        organization.write_text(organization.read_text(encoding="utf-8") + module_map, encoding="utf-8")

        (workflow / relative).write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded = organization.read_text(encoding="utf-8")
        self.assertIn("capability=code-organization v1", upgraded)
        self.assertIn(new_sentence.group(0), upgraded)
        self.assertTrue(upgraded.endswith(module_map))
        self.assertEqual(len(re.findall(r"^## Project module map$", upgraded, re.MULTILINE)), 1)

    def test_upgrade_removes_an_untouched_smoke_line_and_never_drops_a_customized_one(self) -> None:
        workflow = self.framework / "templates/single"
        relative = "PROJECT_WORKFLOW.md"
        current = (workflow / relative).read_text(encoding="utf-8")
        anchor = "<!-- CARDINE:BEGIN capability=validation-scoping v2 -->"
        self.assertIn(anchor, current)
        smoke = "Project integration smoke command: `none`.\n\n"
        (workflow / relative).write_text(current.replace(anchor, smoke + anchor, 1), encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        project_workflow = self.project / relative
        locked = project_workflow.read_text(encoding="utf-8")

        (workflow / relative).write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertNotIn("Project integration smoke command", project_workflow.read_text(encoding="utf-8"))

        project_workflow.write_text(locked.replace("`none`", "`make smoke`"), encoding="utf-8")
        shutil.rmtree(self.project / ".cardine")
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        (workflow / relative).write_text(current.replace(anchor, smoke + anchor, 1), encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        project_workflow.write_text(locked.replace("`none`", "`make smoke`"), encoding="utf-8")
        (workflow / relative).write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        applied = self.run_cli("upgrade", "--apply")
        self.assertIn(applied.returncode, (0, 2), applied.stdout + applied.stderr)
        self.assertIn("Project integration smoke command: `make smoke`", project_workflow.read_text(encoding="utf-8"))

    def test_upgrade_installs_closure_command_policy_for_governed_and_keeps_local_rules(self) -> None:
        self._assert_upgrade_installs_closure_command_policy("single")

    def test_upgrade_installs_resume_guidance_for_lean_from_1_2_6(self) -> None:
        workflow = self.framework / "templates/single"
        paths = ("PROJECT_WORKFLOW.md", "docs/WORKTREE_LIFECYCLE.md")
        current = {relative: (workflow / relative).read_text(encoding="utf-8") for relative in paths}
        resume_paragraph = re.compile(r"\nGuidance that no command backs is advice.*?(?=<!-- CARDINE:END -->)", re.DOTALL)
        resume_bullet = re.compile(r" Only a Resume directive adds `prepare --resume`.*?changes nothing\.", re.DOTALL)
        previous = {
            "PROJECT_WORKFLOW.md": resume_paragraph.sub(
                "\n", current["PROJECT_WORKFLOW.md"].replace(
                    "capability=git-workflow v4", "capability=git-workflow v3"
                ), count=1,
            ),
            "docs/WORKTREE_LIFECYCLE.md": resume_bullet.sub(
                "", re.sub(
                    r"; Resume adds `--resume` after reading status and diff",
                    "", current["docs/WORKTREE_LIFECYCLE.md"], flags=re.DOTALL,
                ).replace(
                    "capability=worktree-lifecycle v1", "capability=worktree-lifecycle v1"
                ), count=1,
            ),
        }
        for relative in paths:
            self.assertNotEqual(previous[relative], current[relative], relative)
            previous[relative] = previous[relative].replace(
                "Only explicit Resume passes `--resume` after status/diff inspection and sole\nwriter confirmation, except when `cardine task close` already succeeded:\nskip execution start, then run worktree advance.", ""
            ).replace("Only explicit Resume adds `--resume` after\n  status/diff inspection.", "")
            previous[relative] = re.sub(r" On explicit Resume, if `cardine task close` already succeeded.*?with the validation evidence\.", "", previous[relative])
            self.assertNotIn("--resume", previous[relative])
            (workflow / relative).write_text(previous[relative], encoding="utf-8")
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        project_workflow = self.project / "PROJECT_WORKFLOW.md"
        project_workflow.write_text(
            project_workflow.read_text(encoding="utf-8") + "\nConsumer-owned resume note.\n", encoding="utf-8"
        )

        for relative in paths:
            (workflow / relative).write_text(current[relative], encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.7\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 023-synthetic-wrapping", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        upgraded = project_workflow.read_text(encoding="utf-8")
        self.assertIn(f"capability=git-workflow v{self.baseline_version('single', 'PROJECT_WORKFLOW.md', 'git-workflow')}", upgraded)
        self.assertIn("Guidance that no command backs is advice", upgraded)
        self.assertIn("Consumer-owned resume note.", upgraded)
        lifecycle = (self.project / "docs/WORKTREE_LIFECYCLE.md").read_text(encoding="utf-8")
        self.assertIn(f"capability=worktree-lifecycle v{self.baseline_version('single', 'docs/WORKTREE_LIFECYCLE.md', 'worktree-lifecycle')}", lifecycle)
        self.assertIn("Only a Resume directive adds `prepare --resume`", lifecycle)

    def test_upgrade_installs_closure_command_policy_for_lean_and_keeps_local_rules(self) -> None:
        self._assert_upgrade_installs_closure_command_policy("single")

    def test_upgrade_installs_lean_lifecycle_document_from_1_2_5(self) -> None:
        workflow = self.framework / "templates/single"
        template = workflow / "docs/WORKTREE_LIFECYCLE.md"
        current = template.read_text(encoding="utf-8")
        previous = re.sub(
            r"\n## Candidate validation\n.*?(?=<!-- CARDINE:END -->)",
            "",
            current,
            count=1,
            flags=re.DOTALL,
        )
        self.assertNotEqual(previous, current)

        for state in (
            "missing",
            "baseline",
            "local-edit",
            "adopt-identical",
            "adopt-different",
            "adopt-collision",
            "adopt-blocked",
        ):
            with self.subTest(state=state):
                shutil.rmtree(self.project)
                self.project.mkdir()
                template.write_text(previous, encoding="utf-8")
                for path in workflow.rglob("*"):
                    if path.is_file():
                        destination = self.project / path.relative_to(workflow)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, destination)
                (self.framework / "VERSION").write_text("1.2.5\n", encoding="utf-8")
                locked = self.run_cli("lock", "--mode", "single")
                self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)

                lifecycle = self.project / "docs/WORKTREE_LIFECYCLE.md"
                if state == "missing":
                    lifecycle.unlink()
                    baseline_lifecycle = (
                        self.project / ".cardine/baselines/1.2.5/docs/WORKTREE_LIFECYCLE.md"
                    )
                    baseline_lifecycle.unlink()
                    manifest_path = self.project / ".cardine/manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["managedFiles"].pop("docs/WORKTREE_LIFECYCLE.md")
                    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                elif state == "local-edit":
                    lifecycle.write_text(previous + "\nConsumer-owned lifecycle note.\n", encoding="utf-8")
                elif state.startswith("adopt-"):
                    baseline_lifecycle = (
                        self.project / ".cardine/baselines/1.2.5/docs/WORKTREE_LIFECYCLE.md"
                    )
                    baseline_lifecycle.unlink()
                    manifest_path = self.project / ".cardine/manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["managedFiles"].pop("docs/WORKTREE_LIFECYCLE.md")
                    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                    if state == "adopt-identical":
                        lifecycle.write_text(current, encoding="utf-8")
                    else:
                        lifecycle.write_text(previous + "\nPre-adoption project copy.\n", encoding="utf-8")
                        if state == "adopt-collision":
                            lifecycle.with_name(
                                lifecycle.name + ".cardine-pre-adoption.bak"
                            ).write_text("earlier backup\n", encoding="utf-8")
                        elif state == "adopt-blocked":
                            agents = self.project / "AGENTS.md"
                            agents.write_text(
                                agents.read_text(encoding="utf-8") + "\nUndeclared local edit.\n",
                                encoding="utf-8",
                            )
                            (self.project / ".cardine/baselines/1.2.5/AGENTS.md").unlink()

                template.write_text(current, encoding="utf-8")
                (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")
                checked = self.run_cli("upgrade", "--check")
                if state == "adopt-blocked":
                    self.assertNotEqual(checked.returncode, 0)
                    self.assertIn("CONFLICT AGENTS.md — managed baseline is missing", checked.stdout)
                else:
                    self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
                expected_action = {
                    "missing": "ADD",
                    "baseline": "REPLACE",
                    "local-edit": "MERGE",
                    "adopt-identical": "ADOPT",
                    "adopt-different": "ADOPT-REPLACE",
                    "adopt-collision": "ADOPT-REPLACE",
                    "adopt-blocked": "ADOPT-REPLACE",
                }[state]
                lifecycle_plan = next(
                    line
                    for line in checked.stdout.splitlines()
                    if "docs/WORKTREE_LIFECYCLE.md" in line
                )
                self.assertEqual(lifecycle_plan.split()[0], expected_action)
                if state == "adopt-different":
                    self.assertIn(
                        "docs/WORKTREE_LIFECYCLE.md.cardine-pre-adoption.bak",
                        lifecycle_plan,
                    )
                elif state == "adopt-collision":
                    self.assertIn(
                        "docs/WORKTREE_LIFECYCLE.md.cardine-pre-adoption.bak.1",
                        lifecycle_plan,
                    )

                if state == "adopt-blocked":
                    before = lifecycle.read_text(encoding="utf-8")
                    applied = self.run_cli("upgrade", "--apply")
                    self.assertNotEqual(applied.returncode, 0)
                    self.assertEqual(lifecycle.read_text(encoding="utf-8"), before)
                    self.assertFalse(
                        lifecycle.with_name(
                            lifecycle.name + ".cardine-pre-adoption.bak"
                        ).exists()
                    )
                    continue

                applied = self.run_cli("upgrade", "--apply")
                self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
                self.assertIn(lifecycle_plan, applied.stdout)
                upgraded = lifecycle.read_text(encoding="utf-8")
                self.assertIn("## Candidate validation", upgraded)
                if state == "local-edit":
                    self.assertIn("Consumer-owned lifecycle note.", upgraded)
                else:
                    self.assertEqual(upgraded, current)
                if state in ("adopt-different", "adopt-collision"):
                    suffix = ".cardine-pre-adoption.bak.1" if state == "adopt-collision" else ".cardine-pre-adoption.bak"
                    backup = lifecycle.with_name(lifecycle.name + suffix)
                    self.assertEqual(
                        backup.read_text(encoding="utf-8"),
                        previous + "\nPre-adoption project copy.\n",
                    )
                    second = self.run_cli("upgrade", "--check")
                    self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                    second_plan = next(
                        line
                        for line in second.stdout.splitlines()
                        if "docs/WORKTREE_LIFECYCLE.md" in line
                    )
                    self.assertEqual(second_plan.split()[0], "KEEP")

        template.write_text(current, encoding="utf-8")
