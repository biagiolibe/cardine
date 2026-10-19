"""Framework CLI regression tests for adoption and audit."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest

from meridian_cli_support import MeridianCliFixtureMixin, CLI


class AdoptionAuditTest(MeridianCliFixtureMixin, unittest.TestCase):
    def install_adoption_records(self) -> None:
        """One synthetic record per adoption record the capability catalog names."""
        catalog = json.loads((self.framework / "capabilities/markers-v1.json").read_text(encoding="utf-8"))
        identifiers = sorted({item["adoptionRecord"] for item in catalog["capabilities"].values() if item["adoptionRecord"]})
        for identifier in identifiers:
            (self.framework / "migrations" / f"{identifier}.json").write_text(
                json.dumps({
                    "id": identifier, "from": "1.0.0", "to": "1.1.0",
                    "description": "Synthetic adoption record", "managedPaths": [],
                    "verification": ["fixture assertions"],
                }),
                encoding="utf-8",
            )

    def test_lean_lifecycle_document_is_managed_across_legacy_adoption(self) -> None:
        snapshot = self.framework / "release-baselines/1.0.0/templates/workflows/lean-delivery"
        shutil.copytree(self.framework / "templates/workflows/lean-delivery", snapshot)
        (snapshot / "docs/WORKTREE_LIFECYCLE.md").unlink()
        shutil.rmtree(self.project)
        self.project.mkdir()
        for path in snapshot.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(snapshot)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        applied = self.run_cli("adopt", "--mode", "lean-delivery", "--from", "1.0.0", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        lifecycle = self.project / "docs/WORKTREE_LIFECYCLE.md"
        current = self.framework / "templates/workflows/lean-delivery/docs/WORKTREE_LIFECYCLE.md"
        self.assertEqual(lifecycle.read_text(encoding="utf-8"), current.read_text(encoding="utf-8"))
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertIn("docs/WORKTREE_LIFECYCLE.md", manifest["managedFiles"])

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
        `meridian upgrade` only touches the files a retiring migration's
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

    def test_adopt_writes_independent_framework_and_baseline_versions(self) -> None:
        self.seed_unlocked_project_from_baseline()
        for path in (self.framework / "migrations").glob("*.json"):
            path.unlink()
        (self.framework / "migrations/001-initial-baseline.json").write_text(
            json.dumps(
                {
                    "id": "001-initial-baseline",
                    "from": "1.0.0",
                    "to": "1.1.0",
                    "description": "test-only initial baseline",
                    "managedPaths": ["PROJECT_WORKFLOW.md"],
                    "verification": ["test-only"],
                }
            ),
            encoding="utf-8",
        )
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")

        applied = self.run_cli("adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.0")
        self.assertEqual(
            sorted(path.name for path in (self.project / ".meridian/baselines").iterdir()),
            ["1.1.0"],
        )

    def test_finalize_adoption_writes_independent_framework_and_baseline_versions(self) -> None:
        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        self.install_adoption_records()
        shutil.rmtree(self.project)
        shutil.copytree(self.framework / "templates/workflows/governed-sdd", self.project)

        finalized = self.run_cli("finalize-adoption", "--mode", "governed-sdd", "--owner-accepted")
        self.assertEqual(finalized.returncode, 0, finalized.stdout + finalized.stderr)
        manifest = json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.0")

    def test_address_review_and_retry_limit(self) -> None:
        self.install_adoption_records()
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        review_path = self.project / ".meridian/adoption-review.md"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(
            "Verdict: CHANGES_REQUESTED\nAttempt: 1\n\n- [ ] add lifecycle orchestration\n",
            encoding="utf-8",
        )

        planned = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(planned.returncode, 3)
        self.assertIn("\nNEXT_ACTION ADDRESS_REVIEW\n", planned.stdout)
        self.assertIn("ATTEMPT 1", planned.stdout)

        review_path.write_text(
            "Verdict: CHANGES_REQUESTED\nAttempt: 2\n\n- [ ] still missing lifecycle orchestration\n",
            encoding="utf-8",
        )
        blocked = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(blocked.returncode, 2)
        line = next(line for line in blocked.stderr.splitlines() if line.startswith("BLOCKED "))
        self.assertTrue(
            line.startswith("BLOCKED ADOPTION_BLOCKED: two consecutive CHANGES_REQUESTED verdicts (attempt 2); resolve "),
            line,
        )
        self.assertTrue(
            line.endswith(
                "manually before retrying; resume: resolve the adoption review record that the detail names manually, "
                "then restart the assisted adoption loop"
            ),
            line,
        )

    def test_emit_returns_single_prompt_block(self) -> None:
        self.install_adoption_records()
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        emitted = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check",
            "--emit", "implementer",
        )
        self.assertEqual(emitted.returncode, 3)
        self.assertNotIn("IMPLEMENTER_PROMPT_BEGIN", emitted.stdout)
        self.assertIn("Perform the capability-aware Meridian adoption migration", emitted.stdout)

        rejected = self.run_cli(
            "adopt", "--mode", "governed-sdd", "--from", "1.0.0", "--assisted", "--check",
            "--emit", "reviewer",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("no reviewer prompt applies", rejected.stderr)

    def test_assisted_adoption_refuses_lean_delivery(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        planned = self.run_cli(
            "adopt", "--mode", "lean-delivery", "--from", "1.0.0", "--assisted", "--check"
        )
        self.assertEqual(planned.returncode, 2)
        self.assertIn("tracks capabilities only for governed-sdd", planned.stderr)

    def test_finalize_owner_accepted_bypasses_review_gate(self) -> None:
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        current = self.framework / "templates" / "workflows" / "governed-sdd"
        for name in (
            "AGENTS.md",
            "CLAUDE.md",
            "PROJECT_WORKFLOW.md",
            "LANGUAGE_POLICY.md",
            "tasks/TASK_BLUEPRINT.md",
            "docs/CODE_ORGANIZATION.md",
            "docs/AUDIT_PROMPT_READ_ONLY.md",
            "docs/REVIEW_RECORD_TEMPLATE.md",
            "docs/LIFECYCLE_ORCHESTRATION.md",
            "docs/CONTEXT_BUDGET_POLICY.md",
            "docs/EXECUTION_EVIDENCE_PROFILE.md",
            "docs/PULL_REQUEST_POLICY.md",
            "docs/CODE_REVIEW_PROMPT.md",
            "docs/COMPLETION_REPORT_TEMPLATE.md",
            "docs/workflows/IMPLEMENTATION.md",
            "docs/workflows/REVIEW.md",
            "docs/workflows/REMEDIATION.md",
            "docs/workflows/LIFECYCLE.md",
            "docs/WORKTREE_LIFECYCLE.md",
            ".codex/rules/meridian.rules",
            ".codex/hooks.json",
        ):
            (self.project / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(current / name, self.project / name)

        refused = self.run_cli("finalize-adoption", "--mode", "governed-sdd")
        self.assertEqual(refused.returncode, 2)

        accepted = self.run_cli("finalize-adoption", "--mode", "governed-sdd", "--owner-accepted")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("Owner-accepted finalize", accepted.stdout)
        self.assertTrue((self.project / ".meridian/manifest.json").is_file())

    def test_mode_and_version_autodetect(self) -> None:
        self.install_adoption_records()
        shutil.rmtree(self.project)
        self.project.mkdir()
        source = self.framework / "release-baselines/1.0.0/templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)

        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(self.framework),
                "adopt",
                "--assisted",
                "--check",
                "--project",
                str(self.project),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("Assisted adoption 1.0.0 ->", result.stdout)
