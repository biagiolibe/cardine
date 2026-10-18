"""Framework CLI regression tests for template surface upgrade."""

from __future__ import annotations

from meridian_cli_support import CLI
from synthetic_upgrade_support import SyntheticFramework
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from cardine.templates import catalog as owner_templates_catalog
import cardine.shared.errors as shared_errors
from cardine.templates import manifest as owner_templates_manifest
from cardine.templates import adoption as owner_templates_adoption


class ProfileSurfaceUpgradeTest(unittest.TestCase):
    """`meridian upgrade` completes a profile declaration the catalog has outgrown."""

    PROFILE = "governed-sdd-consumer"
    CAPABILITY = "execution-evidence"
    ADDED = "docs/COMPLETION_REPORT_TEMPLATE.md"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.framework = root / "framework"
        self.project = root / "project"
        self.fixture = SyntheticFramework(self.framework, "2.0.0")
        self.project.mkdir()
        source = self.framework / "templates/workflows/governed-sdd"
        for path in source.rglob("*"):
            if path.is_file():
                destination = self.project / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
        self.assertEqual(self.run_cli("lock", "--mode", "governed-sdd").returncode, 0)
        owner_templates_adoption.bootstrap_capability_profile(self.project, self.framework, self.PROFILE, apply=True)
        self.expected = self.read_manifest()
        self.catalog = owner_templates_catalog.load_capability_catalog(self.framework)
        # A manifest written before the catalog gained the completion report template.
        old = json.loads(json.dumps(self.expected))
        declaration = old["capabilityProfiles"][self.PROFILE]["capabilities"][self.CAPABILITY]
        declaration["managedSurface"] = [
            surface for surface in declaration["managedSurface"] if surface["path"] != self.ADDED
        ]
        declaration["installation"]["evidence"] = [
            item for item in declaration["installation"]["evidence"] if self.ADDED not in item
        ]
        self.old = old
        self.write_manifest(old)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "--framework-root", str(self.framework), *arguments,
             "--project", str(self.project)],
            text=True, capture_output=True, check=False,
        )

    def read_manifest(self) -> dict[str, object]:
        return json.loads((self.project / ".meridian/manifest.json").read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict[str, object]) -> None:
        (self.project / ".meridian/manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def tree(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.project)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.project.rglob("*")) if path.is_file()
        }

    def declaration(self, manifest: dict[str, object]) -> dict[str, object]:
        return manifest["capabilityProfiles"][self.PROFILE]["capabilities"][self.CAPABILITY]

    def test_strict_validation_still_rejects_the_older_surface(self) -> None:
        with self.assertRaisesRegex(shared_errors.MeridianError, "must completely match the catalog surface"):
            owner_templates_manifest.validate_manifest(self.old, self.catalog)

        gaps: list[tuple[str, str, tuple[str, ...]]] = []
        owner_templates_manifest.validate_manifest(self.old, self.catalog, gaps)
        self.assertEqual(gaps, [(self.PROFILE, self.CAPABILITY, (self.ADDED,))])

    def test_check_prints_the_row_and_writes_nothing(self) -> None:
        before = self.tree()

        checked = self.run_cli("upgrade", "--check")

        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertNotIn("BLOCKED", checked.stdout + checked.stderr)
        self.assertIn(
            f"PROFILE-SURFACE {self.PROFILE}/{self.CAPABILITY}: add {self.ADDED}", checked.stdout
        )
        self.assertEqual(self.tree(), before)

    def test_apply_matches_a_fresh_bootstrap(self) -> None:
        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        after = self.read_manifest()
        self.assertEqual(
            after["capabilityProfiles"], self.expected["capabilityProfiles"]
        )
        owner_templates_manifest.validate_manifest(after, self.catalog)
        again = self.run_cli("upgrade", "--check")
        self.assertNotIn("PROFILE-SURFACE", again.stdout)

    def test_apply_keeps_the_verification_snapshot(self) -> None:
        old = json.loads(json.dumps(self.old))
        declaration = self.declaration(old)
        declaration["verification"] = {
            "state": "ADVISORY", "evidence": ["probe:kept"], "verifiedAt": "2026-01-01T00:00:00Z",
            "verifierVersion": "1", "notApplicableRationale": None,
        }
        self.write_manifest(old)

        self.assertEqual(self.run_cli("upgrade", "--apply").returncode, 0)

        rebuilt = self.declaration(self.read_manifest())
        self.assertEqual(rebuilt["hostActivation"], declaration["hostActivation"])
        self.assertEqual(rebuilt["verification"], declaration["verification"])
        self.assertIn(self.ADDED, [surface["path"] for surface in rebuilt["managedSurface"]])

    def test_drifted_managed_copy_blocks_before_any_write(self) -> None:
        (self.project / self.ADDED).write_text("locally edited\n", encoding="utf-8")
        before = self.tree()
        manifest_before = self.read_manifest()

        checked = self.run_cli("upgrade", "--check")
        applied = self.run_cli("upgrade", "--apply")

        self.assertEqual(checked.returncode, 2, checked.stdout + checked.stderr)
        self.assertIn("differs from the digest recorded at install", checked.stdout)
        self.assertNotEqual(applied.returncode, 0)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.read_manifest(), manifest_before)

    def test_every_other_surface_mismatch_still_fails(self) -> None:
        def mutated(change) -> dict[str, object]:
            manifest = json.loads(json.dumps(self.old))
            change(manifest["capabilityProfiles"][self.PROFILE], self.declaration(manifest))
            return manifest

        def unknown_path(_profile, declaration) -> None:
            declaration["managedSurface"].append({"path": "docs/NOT_IN_CATALOG.md", "form": "managed-copy"})

        def unsupported_form(_profile, declaration) -> None:
            declaration["managedSurface"][0]["form"] = "declaration-only"

        def duplicate_path(_profile, declaration) -> None:
            declaration["managedSurface"].append(dict(declaration["managedSurface"][0]))

        def swapped_path(_profile, declaration) -> None:
            declaration["managedSurface"][0]["path"] = "docs/NOT_IN_CATALOG.md"

        def wrong_profile_version(profile, _declaration) -> None:
            profile["profileVersion"] += 1

        def wrong_capability_version(_profile, declaration) -> None:
            declaration["requiredVersion"] += 1

        def missing_capability(profile, _declaration) -> None:
            del profile["capabilities"][self.CAPABILITY]

        for change in (
            unknown_path, unsupported_form, duplicate_path, swapped_path,
            wrong_profile_version, wrong_capability_version, missing_capability,
        ):
            with self.subTest(change=change.__name__), self.assertRaises(shared_errors.MeridianError):
                owner_templates_manifest.validate_manifest(mutated(change), self.catalog, [])
