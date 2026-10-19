"""Framework CLI regression tests for capability audit."""

from __future__ import annotations

import json
import re
import unittest

from cardine_cli_support import CardineCliFixtureMixin


class CapabilityAuditTest(CardineCliFixtureMixin, unittest.TestCase):


    def test_audit_passes_on_unmodified_markers(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("PASS", audited.stdout)
        self.assertNotRegex(audited.stdout, r"(?m)^FAIL\s")
        self.assertIn("declaration/legacy-compatibility", audited.stdout)

    def test_audit_fails_on_edited_protected_region(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        agents = self.project / "docs/workflows/LIFECYCLE.md"
        text = agents.read_text(encoding="utf-8")
        self.assertIn("MERIDIAN:BEGIN capability=lifecycle-orchestration v3", text)
        edited = text.replace(
            "Act only as the coordinator", "Act only as the coordinator (edited without an upgrade)"
        )
        self.assertNotEqual(text, edited, "the replacement should have matched something inside the marker")
        agents.write_text(edited, encoding="utf-8")

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 2)
        self.assertIn(
            "FAIL           marker-integrity — docs/workflows/LIFECYCLE.md: "
            "capability=lifecycle-orchestration v3",
            audited.stdout,
        )
        self.assertIn("SUMMARY worst=FAIL", audited.stdout)

    def test_audit_fails_when_a_file_carries_two_versions_of_one_capability(self) -> None:
        """Task 012: a version bump that was appended instead of replacing the
        version it supersedes leaves a contradictory pair behind — the audit
        must surface that, not just per-version drift."""
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        agents = self.project / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        self.assertIn("MERIDIAN:BEGIN capability=command-triggers v3", text)
        relabeled = text.replace(
            "MERIDIAN:BEGIN capability=command-triggers v3",
            "MERIDIAN:BEGIN capability=command-triggers v4",
            1,
        )
        duplicate_block = re.search(
            r"<!-- MERIDIAN:BEGIN capability=command-triggers v4 -->.*?<!-- MERIDIAN:END -->",
            relabeled,
            re.DOTALL,
        )
        self.assertIsNotNone(duplicate_block)
        agents.write_text(text.rstrip() + "\n\n" + duplicate_block.group(0) + "\n", encoding="utf-8")

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 2)
        self.assertIn(
            "FAIL           marker-integrity — AGENTS.md: capability=command-triggers "
            "carries 2 versions (v3, v4)",
            audited.stdout,
        )

    def test_audit_skips_a_version_the_current_template_no_longer_carries(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        for name in ("docs/workflows/LIFECYCLE.md",):
            local = self.project / name
            local.write_text(
                local.read_text(encoding="utf-8").replace(
                    "MERIDIAN:BEGIN capability=lifecycle-orchestration v3",
                    "MERIDIAN:BEGIN capability=lifecycle-orchestration v99",
                ),
                encoding="utf-8",
            )

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 1, audited.stdout + audited.stderr)
        self.assertIn("UNVERIFIED", audited.stdout)
        self.assertIn("lifecycle-orchestration v99", audited.stdout)
        self.assertNotRegex(audited.stdout, r"(?m)^FAIL\s")

    def test_audit_fails_a_catalog_retired_marker_without_migration_records(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        self.assertEqual(list((self.framework / "migrations").glob("*.json")), [])
        policy = self.project / "docs/CONTEXT_BUDGET_POLICY.md"
        policy.write_text(
            policy.read_text(encoding="utf-8")
            + "\n<!-- MERIDIAN:BEGIN capability=reasoning-budget-contract v1 -->\nRetired.\n<!-- MERIDIAN:END -->\n",
            encoding="utf-8",
        )

        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 2, audited.stdout + audited.stderr)
        self.assertIn("reasoning-budget-contract v1 is retired but still present", audited.stdout)

    def test_audit_fails_a_retired_marker_still_present_outside_managed_paths(self) -> None:
        """Task 007: a marker whose exact (capability, version) some migration
        declared `removes` must be reported FAIL, not the generic stale SKIP —
        `cardine upgrade` only touches the files a retiring migration's
        `managedPaths` names, so a marker left in an unlisted file would
        otherwise sit as an invisible SKIP forever."""
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        (self.framework / "migrations/999-retire-validation-scoping.json").write_text(
            json.dumps(
                {
                    "id": "999-retire-validation-scoping",
                    "from": "1.1.0",
                    "to": "1.1.1",
                    "description": "test-only retirement",
                    "removes": [{"capability": "validation-scoping", "capabilityVersion": 2}],
                    "managedPaths": ["docs/CONTEXT_BUDGET_POLICY.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        policy = self.framework / "templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md"
        policy_text = policy.read_text(encoding="utf-8")
        marker = re.search(
            r"<!-- MERIDIAN:BEGIN capability=validation-scoping v2 -->\n?.*?"
            r"<!-- MERIDIAN:END -->\n?",
            policy_text,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        policy.write_text(policy_text[: marker.start()] + policy_text[marker.end() :], encoding="utf-8")
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        # The project's local copy still carries the marker (upgrade has not
        # run yet), so the audit must catch it as retired-but-present, not
        # a generic "stale, run upgrade" SKIP.
        audited = self.run_cli("audit", "--mode", "governed-sdd")
        self.assertEqual(audited.returncode, 2, audited.stdout + audited.stderr)
        self.assertIn("FAIL", audited.stdout)
        self.assertIn("validation-scoping v2 is retired but still present", audited.stdout)
