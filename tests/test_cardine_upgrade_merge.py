"""Framework CLI regression tests for upgrade and merge."""

from __future__ import annotations

import sys
from pathlib import Path

import json
import re
import shutil
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cardine_cli  # noqa: E402
from cardine.templates import audit as owner_templates_audit
from cardine.templates import markers as templates_markers

from cardine_cli_support import ROOT
from synthetic_upgrade_support import SyntheticUpgradeFixtureMixin


class UpgradeMergeTest(SyntheticUpgradeFixtureMixin, unittest.TestCase):
    def test_upgrade_check_reports_retired_text_without_writes_or_exit_change(self) -> None:
        (self.framework / "VERSION").write_text(cardine_cli.read_version(ROOT) + "\n", encoding="utf-8")
        locked = self.run_cli("lock", "--mode", "single")
        self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
        baseline = self.run_cli("upgrade", "--check")
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        self.assertNotIn("retired-text", baseline.stdout)
        for relative_path in owner_templates_audit.load_retired_text_registry(ROOT)[0]["files"]:
            path = self.project / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\nFresh SESSION at the declared VALUE\n")
        before = {path.relative_to(self.project): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, baseline.returncode, checked.stdout + checked.stderr)
        self.assertEqual(checked.stdout.count("ADVISORY       retired-text"), 2)
        self.assertIn("retired capability=reasoning-budget-contract", checked.stdout)
        after = {path.relative_to(self.project): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_upgrade_crosses_a_long_lag_capability_move_and_preserves_entry_points(self) -> None:
        moved, target = self.configure_long_lag_move_fixture()
        agents = self.project / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "\nProject-owned agent text.\n", encoding="utf-8")
        pointer = self.project / "CLAUDE.md"
        pointer.write_text(
            "<!-- CARDINE:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("APPEND-RETIRE-MARKERS AGENTS.md", checked.stdout)
        self.assertIn("POINTER-VERIFIED CLAUDE.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertIn("Project-owned agent text.", agents.read_text(encoding="utf-8"))
        self.assertNotIn("capability=route-rule", agents.read_text(encoding="utf-8"))
        self.assertEqual(pointer.read_text(encoding="utf-8"), "<!-- CARDINE:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "# Implementation\n\n" + moved + "\n")

    def test_upgrade_blocks_a_long_lag_move_with_a_modified_or_duplicated_source_marker(self) -> None:
        moved, _target = self.configure_long_lag_move_fixture()
        agents = self.project / "AGENTS.md"
        original = agents.read_text(encoding="utf-8")
        agents.write_text(original + "\n" + moved + "\n" + moved + "\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("CONFLICT AGENTS.md", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertEqual(agents.read_text(encoding="utf-8"), original + "\n" + moved + "\n" + moved + "\n")

        modified = moved.replace("Run the managed route rule.", "Run the locally modified route rule.")
        agents.write_text(original + "\n" + modified + "\n", encoding="utf-8")
        checked_modified = self.run_cli("upgrade", "--check")
        self.assertEqual(checked_modified.returncode, 2, checked_modified.stdout + checked_modified.stderr)
        applied_modified = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied_modified.returncode, 2, applied_modified.stdout + applied_modified.stderr)
        self.assertEqual(agents.read_text(encoding="utf-8"), original + "\n" + modified + "\n")

    def test_lock_and_apply_clean_template_upgrade(self) -> None:
        locked = self.run_cli("lock", "--mode", "single")
        self.assertEqual(locked.returncode, 0, locked.stderr)

        workflow = self.framework / "templates/single/PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8") + "\nUpgrade marker.\n", encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("REPLACE  PROJECT_WORKFLOW.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Upgrade marker.", (self.project / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8"))
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(
            manifest["appliedMigrations"],
            [
                "001-synthetic-baseline",
                "002-synthetic-merge",
            ],
        )
        baselines = sorted(path.name for path in (self.project / ".cardine/baselines").iterdir())
        self.assertEqual(baselines, ["1.1.1"], "stale 1.1.0 baseline should be pruned after upgrade")

        workflow.write_text(workflow.read_text(encoding="utf-8") + "\nSecond upgrade marker.\n", encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.2\n", encoding="utf-8")
        second_apply = self.run_cli("upgrade", "--apply")
        self.assertEqual(second_apply.returncode, 0, second_apply.stderr)
        baselines_after_second = sorted(
            path.name for path in (self.project / ".cardine/baselines").iterdir()
        )
        self.assertEqual(
            baselines_after_second,
            ["1.1.2"],
            "only the current workflowBaselineVersion's baseline should remain after a second upgrade",
        )

    def test_owner_reconciled_upgrade_does_not_adopt_or_back_up_a_managed_file(self) -> None:
        workflow = self.framework / "templates/single"
        template = workflow / "docs/WORKTREE_LIFECYCLE.md"
        current = template.read_text(encoding="utf-8")
        previous = current + "\nConsumer-owned lifecycle note.\n"
        self.assertNotEqual(previous, current)
        template.write_text(previous, encoding="utf-8")
        shutil.rmtree(self.project)
        self.project.mkdir()
        for path in workflow.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(workflow)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        (self.framework / "VERSION").write_text("1.2.5\n", encoding="utf-8")
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        lifecycle = self.project / "docs/WORKTREE_LIFECYCLE.md"
        (self.project / ".cardine/baselines/1.2.5/docs/WORKTREE_LIFECYCLE.md").unlink()
        template.write_text(current, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.2.6\n", encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply", "--owner-reconciled")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertEqual(lifecycle.read_text(encoding="utf-8"), previous)
        self.assertFalse(lifecycle.with_name(lifecycle.name + ".cardine-pre-adoption.bak").exists())
        template.write_text(current, encoding="utf-8")

    def test_upgrade_downgrades_cosmetic_conflict_to_verified(self) -> None:
        """A conflict outside a
        satisfied capability marker is cosmetic and should be left untouched,
        not treated the same as a real, unverifiable conflict."""
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        agents = self.framework / "templates/single/docs/workflows/REMEDIATION.md"
        agents.write_text(
            agents.read_text(encoding="utf-8").replace("# Remediation Procedure", "# Remediation Procedure Rules"),
            encoding="utf-8",
        )
        local = self.project / "docs/workflows/REMEDIATION.md"
        local_text = local.read_text(encoding="utf-8")
        self.assertIn("CARDINE:BEGIN capability=task-worktree-remediation", local_text)
        local.write_text(
            local_text.replace("# Remediation Procedure", "# Our Remediation Procedure"), encoding="utf-8"
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("VERIFIED docs/workflows/REMEDIATION.md", checked.stdout)
        self.assertIn("capability marker(s)", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn(
            "# Our Remediation Procedure",
            (self.project / "docs/workflows/REMEDIATION.md").read_text(encoding="utf-8"),
            "a verified (cosmetic-only) conflict must leave the local file untouched",
        )

    def test_upgrade_appends_new_marker_when_existing_marker_was_moved(self) -> None:
        """A new protected capability must not conflict solely because a project
        relocated an unchanged older protected block."""
        policy = self.framework / "templates/single/PROJECT_WORKFLOW.md"
        incoming_policy = policy.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- CARDINE:BEGIN capability=review-policy v2 -->\n?.*?"
            r"<!-- CARDINE:END -->\n?",
            incoming_policy,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        policy.write_text(incoming_policy[: marker.start()] + incoming_policy[marker.end() :], encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.14\n", encoding="utf-8")
        shutil.rmtree(self.project)
        self.project.mkdir()
        self.copy_governed_templates()
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)

        local_policy = self.project / "PROJECT_WORKFLOW.md"
        local_text = local_policy.read_text(encoding="utf-8")
        validation = re.search(
            r"<!-- CARDINE:BEGIN capability=validation-scoping v2 -->\n?.*?"
            r"<!-- CARDINE:END -->\n?",
            local_text,
            re.DOTALL,
        )
        self.assertIsNotNone(validation)
        moved_validation = validation.group(0)
        local_text = (
            local_text[: validation.start()]
            + "Project-local validation procedure remains at this location.\n"
            + local_text[validation.end() :]
        )
        local_policy.write_text(
            local_text.rstrip() + "\n\n## Project validation baseline\n\n" + moved_validation,
            encoding="utf-8",
        )

        policy.write_text(incoming_policy, encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.15\n", encoding="utf-8")

        appended = templates_markers.append_only_new_markers(
            local_policy.read_text(encoding="utf-8"),
            (self.project / ".cardine/baselines/1.1.14/PROJECT_WORKFLOW.md").read_text(encoding="utf-8"),
            incoming_policy,
        )
        self.assertIsNotNone(appended)
        self.assertIn("## Project validation baseline", appended)
        self.assertIn("capability=review-policy v2", appended)

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MERGE    PROJECT_WORKFLOW.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        upgraded = local_policy.read_text(encoding="utf-8")
        self.assertIn("## Project validation baseline", upgraded)
        self.assertIn("capability=validation-scoping v2", upgraded)
        self.assertIn("capability=review-policy v2", upgraded)

    def test_marker_insertion_promotes_an_identical_unmarked_local_rule(self) -> None:
        template = (
            "# Profile\n\n<!-- CARDINE:BEGIN capability=investigation-scope v2 -->\n"
            "- Investigation scope: 2 per task.\n<!-- CARDINE:END -->\n"
        )
        content = templates_markers.extract_marker_block(template, "investigation-scope", 2)
        self.assertIsNotNone(content)
        local = "# Profile\n\n" + content
        upgraded = templates_markers.append_only_new_markers(local, "# Profile\n", template)
        self.assertIsNotNone(upgraded)
        self.assertEqual(upgraded.count("Investigation scope: 2 per task."), 1)
        self.assertIn("capability=investigation-scope v2", upgraded)

    def test_long_command_waits_block_is_added_once_to_a_customized_profile(self) -> None:
        template = (ROOT / "templates" / "single" / "docs" / "EXECUTION_EVIDENCE_PROFILE.md").read_text(encoding="utf-8")
        self.assertIsNotNone(templates_markers.extract_marker_block(template, "long-command-waits", 1))
        local = "# Project profile\n\nProject-owned rule.\n"
        upgraded = templates_markers.append_only_new_markers(local, "# Project profile\n", template)
        self.assertIsNotNone(upgraded)
        self.assertEqual(upgraded.count("capability=long-command-waits v1"), 1)
        self.assertIn("Project-owned rule.", upgraded)

    def test_marker_normalization_accepts_prose_reflow_but_not_fenced_content(self) -> None:
        template = (
            "<!-- CARDINE:BEGIN capability=example v1 -->\n"
            "One long policy sentence wraps here.\n\n```text\nexact value\n```\n"
            "<!-- CARDINE:END -->\n"
        )
        reflowed = template.replace("One long policy sentence wraps here.", "One long policy\nsentence wraps here.")
        normalized = templates_markers.reflowed_marker_normalization(reflowed, template)
        self.assertEqual(normalized, template)
        changed_fence = reflowed.replace("exact value", "different value")
        self.assertIsNone(templates_markers.reflowed_marker_normalization(changed_fence, template))

    def test_marker_deduplication_removes_only_identical_template_copies(self) -> None:
        block = "<!-- CARDINE:BEGIN capability=example v1 -->\nRule.\n<!-- CARDINE:END -->\n"
        duplicated = "# Policy\n\n" + block + "\n" + block
        normalized = templates_markers.deduplicate_identical_template_markers(duplicated, block)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized.count("capability=example v1"), 1)
        divergent = duplicated.replace("Rule.\n<!-- CARDINE:END -->\n\n<!--", "Different.\n<!-- CARDINE:END -->\n\n<!--", 1)
        self.assertIsNone(templates_markers.deduplicate_identical_template_markers(divergent, block))

    def test_upgrade_does_not_require_a_capability_not_marked_in_this_file(self) -> None:
        """A migration's `managedPaths` lists every file its diff touches, which
        is not the same as every file that must carry its capability marker:
        migration 002 lists `docs/CONTEXT_READING_POLICY.md` because it mentions
        lifecycle orchestration in prose, but only `validation-scoping` is
        actually marked in that file's template. The per-file cosmetic-conflict
        check must derive required capabilities from the template's own marker
        set, not from `managedPaths`, or this file can never be verified."""
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        policy = self.framework / "templates/single/docs/CONTEXT_READING_POLICY.md"
        policy.write_text(
            policy.read_text(encoding="utf-8").replace("## Context-size ceilings", "## Task-First Loading Rules"),
            encoding="utf-8",
        )
        local = self.project / "docs/CONTEXT_READING_POLICY.md"
        local_text = local.read_text(encoding="utf-8")
        self.assertIn("CARDINE:BEGIN capability=bounded-context-readers", local_text)
        local.write_text(
            local_text.replace("## Context-size ceilings", "## Our Task-First Loading"), encoding="utf-8"
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("VERIFIED docs/CONTEXT_READING_POLICY.md", checked.stdout)

    def test_apply_refuses_conflicting_local_change(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        workflow = self.framework / "templates/single/PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8").replace("## Review policy", "## Updated Review policy"), encoding="utf-8")
        local = self.project / "PROJECT_WORKFLOW.md"
        local.write_text(local.read_text(encoding="utf-8").replace("## Review policy", "## Local Review policy"), encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 2)
        self.assertIn("BLOCKED", applied.stderr)
        self.assertIn("## Local Review policy", local.read_text(encoding="utf-8"))

    def test_owner_reconciled_upgrade_registers_baseline_despite_conflicts(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        workflow = self.framework / "templates/single/PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8").replace("## Review policy", "## Updated Review policy"), encoding="utf-8")
        local = self.project / "PROJECT_WORKFLOW.md"
        local.write_text(local.read_text(encoding="utf-8").replace("## Review policy", "## Local Review policy"), encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        rejected = self.run_cli("upgrade", "--check", "--owner-reconciled")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("only applies to --apply", rejected.stderr)

        applied = self.run_cli("upgrade", "--apply", "--owner-reconciled")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn("Owner-reconciled upgrade", applied.stdout)
        self.assertIn("## Local Review policy", local.read_text(encoding="utf-8"))
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        baselines = sorted(path.name for path in (self.project / ".cardine/baselines").iterdir())
        self.assertEqual(baselines, ["1.1.1"])
        baseline_workflow = self.project / ".cardine/baselines/1.1.1/PROJECT_WORKFLOW.md"
        self.assertIn("## Updated Review policy", baseline_workflow.read_text(encoding="utf-8"))

    def test_check_reports_multiple_merge_conflicts(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "single").returncode, 0)
        workflow = self.framework / "templates/single/PROJECT_WORKFLOW.md"
        workflow.write_text(
            workflow.read_text(encoding="utf-8")
            .replace("## Review policy", "## Updated Review policy")
            .replace("## Running a task", "## Updated Running a task"),
            encoding="utf-8",
        )
        local = self.project / "PROJECT_WORKFLOW.md"
        local.write_text(
            local.read_text(encoding="utf-8")
            .replace("## Review policy", "## Local Review policy")
            .replace("## Running a task", "## Local Running a task"),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2)
        self.assertIn("CONFLICT PROJECT_WORKFLOW.md", checked.stdout)
        self.assertIn(
            "BLOCKED UPGRADE_BLOCKED: 1 conflict(s); no files were changed; resume: resolve each conflict or router "
            "requirement that the plan lists, then rerun cardine upgrade --check",
            checked.stdout,
        )
