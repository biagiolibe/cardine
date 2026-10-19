"""Framework CLI regression tests for manifest and protocol."""

from __future__ import annotations

import sys
from pathlib import Path

import json
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cardine_cli  # noqa: E402
import cardine.shared.constants as shared_constants
import cardine.shared.errors as shared_errors

from cardine_cli_support import CardineCliFixtureMixin


class ManifestProtocolTest(CardineCliFixtureMixin, unittest.TestCase):
    def test_lock_rejects_a_prerelease_framework_version_without_writing(self) -> None:
        (self.framework / "VERSION").write_text("1.2.0-rc.1\n", encoding="utf-8")

        locked = self.run_cli("lock", "--mode", "governed-sdd")

        self.assertNotEqual(locked.returncode, 0)
        self.assertIn("prerelease", locked.stderr)
        self.assertIn("1.2.0-rc.1", locked.stderr)
        self.assertFalse((self.project / ".cardine").exists())

    def test_upgrade_apply_rejects_a_prerelease_target_before_touching_files(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".cardine/manifest.json"
        manifest_before = manifest_path.read_bytes()
        workflow = self.framework / "templates/workflows/governed-sdd/PROJECT_WORKFLOW.md"
        workflow.write_text(workflow.read_text(encoding="utf-8") + "\nPrerelease marker.\n", encoding="utf-8")
        project_workflow = self.project / "PROJECT_WORKFLOW.md"
        workflow_before = project_workflow.read_bytes()
        (self.framework / "VERSION").write_text("1.2.0-rc.1\n", encoding="utf-8")

        applied = self.run_cli("upgrade", "--apply")

        self.assertNotEqual(applied.returncode, 0)
        self.assertIn("prerelease", applied.stderr)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self.assertEqual(project_workflow.read_bytes(), workflow_before)

    def test_build_metadata_is_accepted_but_never_persisted(self) -> None:
        (self.framework / "VERSION").write_text("1.1.0+dev.5\n", encoding="utf-8")

        locked = self.run_cli("lock", "--mode", "governed-sdd")

        self.assertEqual(locked.returncode, 0, locked.stderr)
        manifest_text = (self.project / ".cardine/manifest.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(manifest_text)["frameworkVersion"], "1.1.0")
        self.assertNotIn("+dev", manifest_text)

    def test_parse_semver_separates_prerelease_and_build(self) -> None:
        parsed = cardine_cli.parse_semver("1.2.3-rc.1+build.9")
        self.assertEqual((parsed.major, parsed.minor, parsed.patch), (1, 2, 3))
        self.assertEqual((parsed.prerelease, parsed.build), ("rc.1", "build.9"))
        for invalid in ("1.2", "1.2.3-", "01.2.3", "v1.2.3", "1.2.3+"):
            with self.assertRaises(shared_errors.CardineError):
                cardine_cli.parse_semver(invalid)

    def test_cli_only_upgrade_advances_framework_without_rekeying_baseline(self) -> None:
        self.configure_version_split_fixture()
        baseline_root = self.project / ".cardine/baselines/1.1.0"
        baseline_before = {
            path.relative_to(baseline_root): path.read_bytes()
            for path in baseline_root.rglob("*")
            if path.is_file()
        }
        manifest_path = self.project / ".cardine/manifest.json"
        manifest_before = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest_before["workflowBaselineVersion"], "1.1.0")

        (self.framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("Meridian 1.1.0 -> 1.1.0", checked.stdout)
        self.assertIn(
            "Framework: 1.1.0 -> 1.1.1 (CLI-only; no baseline change)",
            checked.stdout,
        )
        self.assertNotIn("MIGRATION ", checked.stdout)
        self.assertNotIn("CONFLICT ", checked.stdout)
        self.assertTrue(
            all(line.startswith("KEEP") for line in checked.stdout.splitlines()[2:]),
            checked.stdout,
        )

        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest_after = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest_after["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest_after["workflowBaselineVersion"], "1.1.0")
        self.assertEqual(manifest_after["protocolVersion"], shared_constants.PROTOCOL_VERSION)
        self.assertEqual(
            {
                key: value
                for key, value in manifest_after.items()
                if key not in {"frameworkVersion", "protocolVersion"}
            },
            {
                key: value
                for key, value in manifest_before.items()
                if key not in {"frameworkVersion", "protocolVersion"}
            },
        )
        self.assertEqual(
            {
                path.relative_to(baseline_root): path.read_bytes()
                for path in baseline_root.rglob("*")
                if path.is_file()
            },
            baseline_before,
        )
        self.assertEqual(
            sorted(path.name for path in baseline_root.parent.iterdir()),
            ["1.1.0"],
        )

        current = self.run_cli("upgrade", "--check")
        self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
        self.assertIn("Framework: 1.1.1 -> 1.1.1", current.stdout)
        self.assertNotIn("CLI-only", current.stdout)
        self.assertNotIn("MIGRATION ", current.stdout)
        self.assertNotIn("CONFLICT ", current.stdout)

    def test_manifest_protocol_compatibility_for_upgrade_check_and_audit(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".cardine/manifest.json"
        commands = (
            ("upgrade --check", ("upgrade", "--check")),
            ("audit", ("audit", "--mode", "governed-sdd")),
        )
        cases = (
            ("newer", shared_constants.PROTOCOL_VERSION + 1, 2),
            ("equal", shared_constants.PROTOCOL_VERSION, 0),
            ("lower", shared_constants.PROTOCOL_VERSION - 1, 0),
            ("missing", None, 0),
        )

        for command_name, command in commands:
            for case_name, protocol_version, expected_returncode in cases:
                with self.subTest(command=command_name, protocol=case_name):
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if protocol_version is None:
                        manifest.pop("protocolVersion", None)
                    else:
                        manifest["protocolVersion"] = protocol_version
                    manifest_path.write_text(
                        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                    result = self.run_cli(*command)
                    if command_name == "audit" and case_name != "newer":
                        expected_returncode = 1
                    self.assertEqual(
                        result.returncode,
                        expected_returncode,
                        result.stdout + result.stderr,
                    )
                    if case_name == "newer":
                        self.assertIn("update your Meridian checkout", result.stderr)

    def test_upgrade_apply_rejects_newer_protocol_before_touching_project(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".cardine/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["protocolVersion"] = shared_constants.PROTOCOL_VERSION + 1
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        project_before = {
            path.relative_to(self.project): path.read_bytes()
            for path in self.project.rglob("*")
            if path.is_file()
        }

        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertIn("update your Meridian checkout", applied.stderr)
        self.assertEqual(
            {
                path.relative_to(self.project): path.read_bytes()
                for path in self.project.rglob("*")
                if path.is_file()
            },
            project_before,
        )

    def test_upgrade_apply_rewrites_lower_protocol_to_current(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".cardine/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["protocolVersion"] = shared_constants.PROTOCOL_VERSION - 1
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        rewritten = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(rewritten["protocolVersion"], shared_constants.PROTOCOL_VERSION)

    def test_manifest_protocol_version_must_be_an_integer(self) -> None:
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        manifest_path = self.project / ".cardine/manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["protocolVersion"] = "1"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        checked = self.run_cli("upgrade", "--check")

        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("manifest protocolVersion must be an integer", checked.stderr)

    def test_legacy_manifest_uses_framework_version_as_baseline_fallback(self) -> None:
        self.configure_version_split_fixture()
        manifest_path = self.project / ".cardine/manifest.json"
        legacy_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        del legacy_manifest["workflowBaselineVersion"]
        manifest_path.write_text(
            json.dumps(legacy_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.add_version_split_migration()

        checked = self.run_cli("upgrade", "--check")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("MIGRATION 002-next-baseline", checked.stdout)
        applied = self.run_cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["frameworkVersion"], "1.1.1")
        self.assertEqual(manifest["workflowBaselineVersion"], "1.1.1")
