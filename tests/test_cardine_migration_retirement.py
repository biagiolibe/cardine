"""Framework CLI regression tests for migration and retirement."""

from __future__ import annotations

import sys
from pathlib import Path

import json
import re
import shutil
import subprocess
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cardine_cli  # noqa: E402
from cardine.templates import markers as templates_markers

from cardine_cli_support import CardineCliFixtureMixin, ROOT


class MigrationRetirementTest(CardineCliFixtureMixin, unittest.TestCase):
    def test_stop_before_retirement_caps_the_plan_before_the_retirement_migration(self) -> None:
        self.configure_long_lag_move_fixture()
        self.reset_project_to_installed_baseline()
        agents = self.project / "AGENTS.md"
        original_agents = agents.read_text(encoding="utf-8")
        pointer = self.project / "CLAUDE.md"
        pointer.write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check", "--stop-before-retirement")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Cardine 1.1.0 -> 1.1.2", checked.stdout)
        self.assertIn("MIGRATION 001-establish-route-rule", checked.stdout)
        self.assertIn("MIGRATION 002-add-route-rule", checked.stdout)
        self.assertNotIn("MIGRATION 003-retire-route-rule", checked.stdout)
        self.assertNotIn("APPEND-RETIRE-MARKERS", checked.stdout)
        self.assertNotIn("RETIRE-MARKERS", checked.stdout)

        applied = self.run_cli("upgrade", "--apply", "--stop-before-retirement")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)

        # AGENTS.md must survive byte-for-byte: route-rule is a purely
        # declared, transient capability (never physically present in any
        # template — task 036's exact scenario) that only migration 002
        # additively moves into docs/workflows/IMPLEMENTATION.md, and the
        # undeclared-in-this-migration entry-router bump the live template
        # already carries must not leak in either — it is declared against
        # the excluded, capped-out 003, exactly like the real
        # command-triggers gap this task fixes.
        self.assertEqual(agents.read_text(encoding="utf-8"), original_agents)
        self.assertNotIn("entry-router v2", agents.read_text(encoding="utf-8"))
        self.assertEqual(
            pointer.read_text(encoding="utf-8"),
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
        )

        implementation = self.project / "docs/workflows/IMPLEMENTATION.md"
        self.assertIn("capability=route-rule v1", implementation.read_text(encoding="utf-8"))

        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.2")
        self.assertEqual(
            manifest["appliedMigrations"],
            ["001-establish-route-rule", "002-add-route-rule"],
        )

    def test_stop_before_retirement_upgrade_can_later_complete_in_full(self) -> None:
        moved, target = self.configure_long_lag_move_fixture()
        self.reset_project_to_installed_baseline()
        self.make_route_rule_physically_present(moved)
        (self.project / "CLAUDE.md").write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("upgrade", "--apply", "--stop-before-retirement").returncode, 0)

        # A plain check (no flag) now sees the remaining migration as pending,
        # with no false conflict from the intermediate stopping point.
        resumed_check = self.run_cli("upgrade", "--check")
        self.assertEqual(resumed_check.returncode, 0, resumed_check.stdout + resumed_check.stderr)
        self.assertIn("Cardine 1.1.2 -> 1.1.3", resumed_check.stdout)
        self.assertIn("MIGRATION 003-retire-route-rule", resumed_check.stdout)

        resumed_apply = self.run_cli("upgrade", "--apply")
        self.assertEqual(resumed_apply.returncode, 0, resumed_apply.stdout + resumed_apply.stderr)
        agents = self.project / "AGENTS.md"
        self.assertNotIn("capability=route-rule", agents.read_text(encoding="utf-8"))
        self.assertEqual(target.read_text(encoding="utf-8"), "# Implementation\n\n" + moved + "\n")
        manifest = json.loads((self.project / ".cardine/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.3")
        self.assertEqual(
            manifest["appliedMigrations"],
            ["001-establish-route-rule", "002-add-route-rule", "003-retire-route-rule"],
        )

    def test_stop_before_retirement_is_a_noop_with_no_pending_retirement(self) -> None:
        moved, _target = self.configure_long_lag_move_fixture()
        self.reset_project_to_installed_baseline()
        self.make_route_rule_physically_present(moved)
        (self.project / "CLAUDE.md").write_text(
            "<!-- MERIDIAN:CLAUDE-AGENTS-POINTER v1 -->\n\n# Project Claude entry point\n",
            encoding="utf-8",
        )
        self.assertEqual(self.run_cli("upgrade", "--apply", "--stop-before-retirement").returncode, 0)
        self.assertEqual(self.run_cli("upgrade", "--apply").returncode, 0)

        # Every migration, including the retirement one, is now applied; a
        # further capped run has nothing left to cap and must behave exactly
        # like a plain, already-current check.
        plain = self.run_cli("upgrade", "--check")
        capped = self.run_cli("upgrade", "--check", "--stop-before-retirement")
        self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
        self.assertEqual(plain.stdout, capped.stdout)

    def test_migration_upgrade_advances_and_rekeys_workflow_baseline(self) -> None:
        self.configure_version_split_fixture()
        self.add_version_split_migration()

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Cardine 1.1.0 -> 1.1.1", checked.stdout)
        self.assertIn("Framework: 1.1.0 -> 1.1.1", checked.stdout)
        self.assertIn("MIGRATION 002-next-baseline", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest = json.loads(
            (self.project / ".cardine/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.1")
        self.assertEqual(
            sorted(path.name for path in (self.project / ".cardine/baselines").iterdir()),
            ["1.1.1"],
        )


    def test_upgrade_retires_a_capability_from_a_conflicting_file(self) -> None:
        """Task 007: a migration's `removes` entry deletes a retired capability's
        block during `upgrade`, even when the file also has an unrelated local
        customization that blocks a clean three-way merge -- the retirement
        mirror of `test_upgrade_appends_new_marker_when_existing_marker_was_moved`.
        """
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        policy = self.framework / "templates/single/docs/CONTEXT_READING_POLICY.md"
        incoming_policy = policy.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v3 -->\n?.*?"
            r"<!-- MERIDIAN:END -->\n?",
            incoming_policy,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        incoming_policy = incoming_policy[: marker.start()] + incoming_policy[marker.end() :]
        # An unrelated framework-side edit, on the same line a local
        # customization below also touches, so the three-way merge cannot
        # auto-resolve and the file falls through to the retirement fallback.
        incoming_policy = incoming_policy.replace(
            "## Task-first loading", "## Task-First Loading (framework wording)"
        )
        policy.write_text(incoming_policy, encoding="utf-8")

        (self.framework / "migrations/999-retire-minimal-read-only-status.json").write_text(
            json.dumps(
                {
                    "id": "999-retire-minimal-read-only-status",
                    "from": "1.1.0",
                    "to": "1.1.1",
                    "description": "test-only retirement",
                    "removes": [
                        {
                            "capability": "minimal-read-only-status",
                            "capabilityVersion": 3,
                            "supersededBy": "role-scoped-agent-rules",
                        }
                    ],
                    "managedPaths": ["docs/CONTEXT_READING_POLICY.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        local_policy = self.project / "docs/CONTEXT_READING_POLICY.md"
        local_text = local_policy.read_text(encoding="utf-8")
        self.assertIn("MERIDIAN:BEGIN capability=minimal-read-only-status v3", local_text)
        local_policy.write_text(
            local_text.replace("## Task-first loading", "## Task-First Loading (project wording)"),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("RETIRE-MARKERS docs/CONTEXT_READING_POLICY.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        upgraded = local_policy.read_text(encoding="utf-8")
        self.assertNotIn("capability=minimal-read-only-status", upgraded)
        self.assertNotIn("A status report is not a conformance audit.", upgraded)
        # The unrelated local customization survives untouched.
        self.assertIn("## Task-First Loading (project wording)", upgraded)
        # Every other still-required capability in this file is untouched.
        self.assertIn("capability=validation-scoping v2", upgraded)
        self.assertIn("capability=evidence-tiers v1", upgraded)

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertNotIn("minimal-read-only-status", audited.stdout)

    def test_upgrade_refuses_to_retire_a_locally_modified_block(self) -> None:
        """The same retirement, but the local copy of the retired block itself
        was edited -- must fall through to a blocking conflict rather than
        silently discard the customization along with the block."""
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        policy = self.framework / "templates/single/docs/CONTEXT_READING_POLICY.md"
        incoming_policy = policy.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v3 -->\n?.*?"
            r"<!-- MERIDIAN:END -->\n?",
            incoming_policy,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        incoming_policy = incoming_policy[: marker.start()] + incoming_policy[marker.end() :]
        incoming_policy = incoming_policy.replace(
            "## Task-first loading", "## Task-First Loading (framework wording)"
        )
        policy.write_text(incoming_policy, encoding="utf-8")

        (self.framework / "migrations/999-retire-minimal-read-only-status.json").write_text(
            json.dumps(
                {
                    "id": "999-retire-minimal-read-only-status",
                    "from": "1.1.0",
                    "to": "1.1.1",
                    "description": "test-only retirement",
                    "removes": [{"capability": "minimal-read-only-status", "capabilityVersion": 3}],
                    "managedPaths": ["docs/CONTEXT_READING_POLICY.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        local_policy = self.project / "docs/CONTEXT_READING_POLICY.md"
        local_text = local_policy.read_text(encoding="utf-8")
        local_text = local_text.replace("## Task-first loading", "## Task-First Loading (project wording)")
        # Edit inside the very block that is about to be retired.
        local_text = local_text.replace(
            "A status report is not a conformance audit.",
            "A status report is not a conformance audit, locally customized.",
        )
        local_policy.write_text(local_text, encoding="utf-8")

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("CONFLICT docs/CONTEXT_READING_POLICY.md", checked.stdout)
        self.assertIn("BLOCKED", checked.stdout)

    def test_retirement_move_preserves_project_text_outside_exact_source_marker(self) -> None:
        """A retirement move proves only its protected source marker.

        Project-owned material outside that marker must survive both the move
        and its follow-up audit; otherwise a consumer with a customized agent
        guide can never adopt compact routing safely.
        """
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)

        source = self.framework / "templates/single/docs/CONTEXT_READING_POLICY.md"
        source_text = source.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=minimal-read-only-status v3 -->\n?.*?"
            r"<!-- MERIDIAN:END -->",
            source_text,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        marker_text = marker.group(0)
        digest = templates_markers.marker_block_sha256(marker_text)
        incoming_source = source_text[: marker.start()] + source_text[marker.end() :]
        source.write_text(
            incoming_source.replace(
                "This policy reduces context and reasoning overhead while preserving authority and review quality.",
                "This framework policy reduces context and reasoning overhead while preserving authority and review quality.",
            ),
            encoding="utf-8",
        )

        target = self.framework / "templates/single/docs/ROUTED_STATUS_RULE.md"
        target.write_text(marker_text + "\n", encoding="utf-8")
        (self.framework / "migrations/999-move-minimal-read-only-status.json").write_text(
            json.dumps(
                {
                    "id": "999-move-minimal-read-only-status",
                    "from": "1.1.0",
                    "to": "1.1.1",
                    "description": "test-only retirement move",
                    "capabilityMoves": [
                        {
                            "stage": "retirement",
                            "source": {
                                "path": "docs/CONTEXT_READING_POLICY.md",
                                "capability": "minimal-read-only-status",
                                "capabilityVersion": 3,
                                "markerSha256": digest,
                            },
                            "target": {
                                "path": "docs/ROUTED_STATUS_RULE.md",
                                "capability": "minimal-read-only-status",
                                "capabilityVersion": 3,
                                "markerSha256": digest,
                            },
                        }
                    ],
                    "managedPaths": ["docs/CONTEXT_READING_POLICY.md", "docs/ROUTED_STATUS_RULE.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        local_source = self.project / "docs/CONTEXT_READING_POLICY.md"
        local_source.write_text(
            local_source.read_text(encoding="utf-8").replace(
                "This policy reduces context and reasoning overhead while preserving authority and review quality.",
                "This project policy reduces context and reasoning overhead while preserving governed-SDD authority and review quality.",
            ),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("RETIRE-MARKERS docs/CONTEXT_READING_POLICY.md", checked.stdout)
        self.assertIn("ADD      docs/ROUTED_STATUS_RULE.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded_source = local_source.read_text(encoding="utf-8")
        self.assertIn("This project policy reduces context and reasoning overhead", upgraded_source)
        self.assertNotIn("capability=minimal-read-only-status", upgraded_source)
        self.assertEqual((self.project / "docs/ROUTED_STATUS_RULE.md").read_text(encoding="utf-8"), marker_text + "\n")

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("declaration/legacy-compatibility", audited.stdout)

    def test_upgrade_retires_reasoning_contract_alongside_a_marker_supersession(self) -> None:
        """A migration that both supersedes execution-evidence-profile v3 and
        retires reasoning-budget-contract in one file; when the three-way merge
        conflicts, the retirement must still apply, not be skipped."""
        policy, local_policy = self._lock_project_with_reasoning_contract()
        local_policy.write_text(
            local_policy.read_text(encoding="utf-8").replace(
                "## Task-first loading", "## Task-First Loading (project wording)"
            ),
            encoding="utf-8",
        )
        policy.write_text(
            policy.read_text(encoding="utf-8").replace(
                "## Task-first loading", "## Task-First Loading (framework wording)"
            ),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("APPEND-RETIRE-MARKERS docs/CONTEXT_READING_POLICY.md", checked.stdout)

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded = local_policy.read_text(encoding="utf-8")
        self.assertNotIn("reasoning-budget-contract", upgraded)
        self.assertIn("capability=execution-evidence-profile v6", upgraded)
        self.assertIn("Task-First Loading (project wording)", upgraded)

    def test_upgrade_refuses_to_retire_a_locally_edited_reasoning_contract(self) -> None:
        policy, local_policy = self._lock_project_with_reasoning_contract()
        local_policy.write_text(
            local_policy.read_text(encoding="utf-8")
            .replace("while designing the task.", "while designing the task, locally customized.")
            .replace("## Task-first loading", "## Task-First Loading (project wording)"),
            encoding="utf-8",
        )
        policy.write_text(
            policy.read_text(encoding="utf-8").replace(
                "## Task-first loading", "## Task-First Loading (framework wording)"
            ),
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("CONFLICT docs/CONTEXT_READING_POLICY.md", checked.stdout)
        self.assertIn("locally customized.", local_policy.read_text(encoding="utf-8"))
