"""Framework CLI regression tests for template manifest."""

from __future__ import annotations

from meridian_cli_support import CLI, ROOT
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from cardine.templates import audit as owner_templates_audit
from cardine.templates import catalog as owner_templates_catalog
from cardine.templates import markers as templates_markers
import cardine.shared.constants as shared_constants
import cardine.shared.errors as shared_errors
import cardine.shared.hashing as shared_hashing
from cardine.templates import files as owner_templates_files
from cardine.templates import migrations as owner_templates_migrations
from cardine.templates import manifest as owner_templates_manifest
from cardine.templates import marker_history as owner_templates_marker_history
from cardine.templates import adoption as owner_templates_adoption
import meridian


class CapabilityVersionDetectionTest(unittest.TestCase):
    """Phase 2 of migrations/CAPABILITY_MARKERS.md: version-aware detection.

    No real migration requires v2 of anything yet, so this builds a synthetic
    framework with one to exercise the case Meridian's own shipped migrations
    can't: a marker present but below the version now required.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.framework = root / "framework"
        self.project = root / "project"
        (self.framework / "migrations").mkdir(parents=True)
        self.project.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_migration(self, filename: str, capability: str, version: int) -> None:
        migration_id = filename.removesuffix(".json")
        (self.framework / "migrations" / filename).write_text(
            json.dumps({"id": migration_id, "capability": capability, "capabilityVersion": version}),
            encoding="utf-8",
        )

    def test_requirement_is_the_highest_declared_version(self) -> None:
        self.write_migration("001-widget.json", "widget", 1)
        self.write_migration("002-widget-v2.json", "widget", 2)
        requirements = owner_templates_migrations.capability_requirements(self.framework)
        self.assertEqual(requirements["widget"], (2, "002-widget-v2"))

    def test_marker_absent_is_distinct_from_marker_stale(self) -> None:
        self.write_migration("001-widget.json", "widget", 2)

        absent = templates_markers.find_capability_marker_version("no marker here", "widget")
        self.assertIsNone(absent)

        stale_text = "<!-- MERIDIAN:BEGIN capability=widget v1 -->text<!-- MERIDIAN:END -->"
        self.assertEqual(templates_markers.find_capability_marker_version(stale_text, "widget"), 1)

    def test_detect_capabilities_distinguishes_absent_stale_and_satisfied(self) -> None:
        self.write_migration("001-widget.json", "widget", 2)
        agents = self.project / "AGENTS.md"
        claude = self.project / "CLAUDE.md"
        for path in (agents, claude):
            path.write_text("", encoding="utf-8")

        import meridian as m

        managed = [m.ManagedFile(source=Path("unused"), target=Path("AGENTS.md"))]
        original_managed_files = owner_templates_marker_history.managed_files
        owner_templates_marker_history.managed_files = lambda framework_root, mode: managed
        try:
            absent = m.detect_capabilities(self.project, "governed-sdd", self.framework)
            self.assertEqual(len(absent), 1)
            self.assertFalse(absent[0].present)
            self.assertIn("no MERIDIAN:BEGIN", absent[0].evidence)

            agents.write_text(
                "<!-- MERIDIAN:BEGIN capability=widget v1 -->text<!-- MERIDIAN:END -->",
                encoding="utf-8",
            )
            stale = m.detect_capabilities(self.project, "governed-sdd", self.framework)
            self.assertFalse(stale[0].present)
            self.assertEqual(stale[0].evidence, "marker present at v1, but v2 is required")

            agents.write_text(
                "<!-- MERIDIAN:BEGIN capability=widget v2 -->text<!-- MERIDIAN:END -->",
                encoding="utf-8",
            )
            satisfied = m.detect_capabilities(self.project, "governed-sdd", self.framework)
            self.assertTrue(satisfied[0].present)
        finally:
            owner_templates_marker_history.managed_files = original_managed_files


class CapabilityProfileManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = owner_templates_catalog.load_capability_catalog(ROOT)

    def manifest(self, mode: str = "lean-delivery") -> dict[str, object]:
        profile = self.catalog.profile("meridian-self-hosting")
        self.assertIsNotNone(profile)
        capabilities: dict[str, object] = {}
        for capability_id, version in profile.capabilities:
            capability = self.catalog.capability(capability_id)
            self.assertIsNotNone(capability)
            capabilities[capability_id] = {
                "requiredVersion": version,
                "managedSurface": [
                    {"path": surface.path, "form": surface.forms[0]}
                    for surface in capability.managed_surfaces
                ],
                "installation": {
                    "state": "MISSING",
                    "evidence": [],
                    "notApplicableRationale": None,
                },
                "hostActivation": {
                    host_id: {
                        "state": "UNVERIFIED",
                        "evidence": [],
                        "notApplicableRationale": None,
                    }
                    for host_id, _evidence_kind in capability.host_profiles
                },
                "verification": {
                    "state": "UNVERIFIED",
                    "evidence": [],
                    "verifiedAt": None,
                    "verifierVersion": None,
                    "notApplicableRationale": None,
                },
            }
        return {
            "protocolVersion": shared_constants.PROTOCOL_VERSION,
            "frameworkVersion": "1.1.0",
            "workflowMode": mode,
            "managedFiles": {},
            "appliedMigrations": ["014-minimal-read-only-status", "040-pretooluse-read-guard"],
            "capabilityProfiles": {
                "meridian-self-hosting": {
                    "profileVersion": profile.version,
                    "capabilities": capabilities,
                }
            },
        }

    def installed_project(
        self, project: Path, mode: str = "lean-delivery"
    ) -> dict[str, object]:
        manifest = self.manifest(mode)
        managed_files: dict[str, str] = {}
        for capability_id, declaration in manifest["capabilityProfiles"][
            "meridian-self-hosting"
        ]["capabilities"].items():
            surface_digests = []
            for surface in declaration["managedSurface"]:
                path = project / surface["path"]
                if not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"surface: {surface['path']}\n", encoding="utf-8")
                digest = shared_hashing.sha256(path)
                surface_digests.append(f"sha256:{digest}")
                if surface["form"] == "managed-copy":
                    managed_files[surface["path"]] = digest
            declaration["installation"] = {
                "state": "INSTALLED",
                "evidence": surface_digests,
                "notApplicableRationale": None,
            }
            host_activation = {}
            for host_id in declaration["hostActivation"]:
                probe_path = f".meridian/evidence/{capability_id}-{host_id}.json"
                probe = project / probe_path
                probe.parent.mkdir(parents=True, exist_ok=True)
                probe.write_text("{}\n", encoding="utf-8")
                host_activation[host_id] = {
                    "state": "ENFORCED",
                    "evidence": [f"probe:{probe_path}"],
                    "notApplicableRationale": None,
                }
            declaration["hostActivation"] = host_activation
            verification_path = f".meridian/evidence/{capability_id}-verification.json"
            verification_probe = project / verification_path
            verification_probe.parent.mkdir(parents=True, exist_ok=True)
            verification_probe.write_text("{}\n", encoding="utf-8")
            declaration["verification"] = {
                "state": "PASS",
                "evidence": [f"probe:{verification_path}"],
                "verifiedAt": "2026-09-28T00:00:00Z",
                "verifierVersion": meridian.read_version(ROOT),
                "notApplicableRationale": None,
            }
        manifest["managedFiles"] = managed_files
        owner_templates_manifest.write_manifest(project, manifest, ROOT)
        return manifest

    def audit(self, project: Path, mode: str = "lean-delivery") -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = owner_templates_audit.run_audit(project, ROOT, mode)
        return return_code, output.getvalue()

    def test_catalog_exposes_versioned_profile_metadata_and_dependencies(self) -> None:
        self.assertEqual(self.catalog.catalog_version, 1)
        self.assertEqual(len(self.catalog.capabilities), 8)
        read_guard = self.catalog.capability("read-guard")
        self.assertEqual(read_guard.version, 1)
        self.assertEqual(read_guard.workflow_modes, ("lean-delivery", "governed-sdd"))
        self.assertTrue(read_guard.self_hosting_eligible)
        self.assertIn(("codex-project", "hook-invocation-observation"), read_guard.host_profiles)
        self.assertIn("shared-source", read_guard.installation_forms)
        self.assertTrue(read_guard.managed_surfaces)
        self.assertEqual(read_guard.dependencies, (("context-budgeting", 1),))
        profile = self.catalog.profile("meridian-self-hosting")
        self.assertEqual(
            profile.verification_probe,
            ".meridian/probes/meridian-self-hosting/host-neutral-ci-v1.json",
        )
        self.assertEqual(
            set(dict(profile.host_probes)), {"claude-project", "codex-project"}
        )

    def test_profile_doctor_is_read_only_and_resolves_required_probes(self) -> None:
        before = {
            path.relative_to(ROOT): path.read_bytes()
            for path in ROOT.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        output = io.StringIO()
        with redirect_stdout(output):
            return_code = owner_templates_audit.profile_doctor(
                ROOT, ROOT, "meridian-self-hosting"
            )
        after = {
            path.relative_to(ROOT): path.read_bytes()
            for path in ROOT.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        self.assertEqual(return_code, 0, output.getvalue())
        self.assertEqual(after, before)
        self.assertIn("probe/claude-project", output.getvalue())
        self.assertIn("probe/codex-project", output.getvalue())
        self.assertIn("host state=UNVERIFIED", output.getvalue())

    def test_profile_doctor_fails_missing_or_incomplete_probe(self) -> None:
        for mutation, diagnostic in (("missing", "required probe is missing"), ("incomplete", "missing capability checks")):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                shutil.copytree(ROOT / ".meridian/probes", project / ".meridian/probes")
                self.installed_project(project)
                probe = project / ".meridian/probes/meridian-self-hosting/codex-project-v1.json"
                if mutation == "missing":
                    probe.unlink()
                else:
                    data = json.loads(probe.read_text(encoding="utf-8"))
                    data["checks"] = data["checks"][:-1]
                    probe.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    return_code = owner_templates_audit.profile_doctor(
                        project, ROOT, "meridian-self-hosting"
                    )
                self.assertEqual(return_code, 2, output.getvalue())
                self.assertIn(diagnostic, output.getvalue())

    def test_ci_profile_gate_accepts_host_unverified_but_rejects_static_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]
            for declaration in capabilities.values():
                for activation in declaration["hostActivation"].values():
                    activation.update(state="UNVERIFIED", evidence=[])
                declaration["verification"] = {
                    "state": "UNVERIFIED",
                    "evidence": [],
                    "verifiedAt": None,
                    "verifierVersion": None,
                    "notApplicableRationale": None,
                }
            owner_templates_manifest.write_manifest(project, manifest, ROOT)
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(
                    project, ROOT, "lean-delivery", "meridian-self-hosting"
                )
            self.assertEqual(return_code, 0, output.getvalue())
            self.assertIn("SUMMARY worst=UNVERIFIED", output.getvalue())
            self.assertIn("CI_GATE profile=meridian-self-hosting worst=PASS", output.getvalue())

            (project / ".codex/hooks.json").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(
                    project, ROOT, "lean-delivery", "meridian-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn("missing managed-copy surface .codex/hooks.json", output.getvalue())

    def test_ci_profile_gate_rejects_missing_managed_policy_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            (project / "docs/CONTEXT_BUDGET_POLICY.md").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(
                    project, ROOT, "lean-delivery", "meridian-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn(
                "missing managed-copy surface docs/CONTEXT_BUDGET_POLICY.md",
                output.getvalue(),
            )

    def test_ci_profile_gate_rejects_missing_shared_hook_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            (project / "hooks/queue-briefing.sh").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(
                    project, ROOT, "lean-delivery", "meridian-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn(
                "missing shared-source surface hooks/queue-briefing.sh",
                output.getvalue(),
            )

    def test_ci_profile_gate_rejects_an_unknown_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(
                    project, ROOT, "lean-delivery", "unknown-profile"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn("CI_GATE profile=unknown-profile worst=FAIL", output.getvalue())

    def test_live_manifest_has_no_host_claim_or_machine_specific_path(self) -> None:
        manifest_text = (ROOT / shared_constants.MANIFEST_PATH).read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]
        self.assertNotIn(str(Path.home()), manifest_text)
        for declaration in capabilities.values():
            for activation in declaration["hostActivation"].values():
                self.assertEqual(activation["state"], "UNVERIFIED")
                self.assertEqual(activation["evidence"], [])

    def test_published_schemas_track_protocol_and_state_vocabularies(self) -> None:
        manifest_schema = json.loads(
            (ROOT / "schemas/manifest-v2.schema.json").read_text(encoding="utf-8")
        )
        catalog_schema = json.loads(
            (ROOT / "schemas/capability-catalog-v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest_schema["properties"]["protocolVersion"]["const"], 2)
        self.assertEqual(
            tuple(manifest_schema["properties"]["workflowMode"]["enum"]),
            shared_constants.WORKFLOW_MODES,
        )
        self.assertEqual(
            tuple(
                manifest_schema["$defs"]["installationSnapshot"]["properties"]["state"]["enum"]
            ),
            shared_constants.INSTALLATION_STATES,
        )
        self.assertEqual(catalog_schema["properties"]["catalogVersion"]["const"], 1)

    def test_lean_and_governed_profiles_round_trip_through_the_current_writer(self) -> None:
        for mode in shared_constants.WORKFLOW_MODES:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                manifest = self.manifest(mode)
                owner_templates_manifest.write_manifest(project, manifest, ROOT)
                written = json.loads((project / shared_constants.MANIFEST_PATH).read_text(encoding="utf-8"))
                self.assertEqual(written["protocolVersion"], 2)
                self.assertEqual(written["workflowMode"], mode)
                self.assertNotIn("mode", written)
                loaded = owner_templates_manifest.load_manifest(project, ROOT)
                self.assertEqual(owner_templates_catalog.manifest_workflow_mode(loaded), mode)
                self.assertEqual(len(owner_templates_catalog.parse_capability_profiles(loaded, self.catalog)), 1)

    def test_legacy_mode_and_migration_history_do_not_fabricate_capabilities(self) -> None:
        legacy = {
            "protocolVersion": 1,
            "mode": "lean-delivery",
            "managedFiles": {},
            "appliedMigrations": [
                "014-minimal-read-only-status",
                "018-execution-evidence-profile",
                "040-pretooluse-read-guard",
            ],
        }
        self.assertEqual(owner_templates_manifest.validate_manifest(legacy, self.catalog), ())
        projected = owner_templates_manifest.canonical_manifest(legacy)
        self.assertEqual(projected["workflowMode"], "lean-delivery")
        self.assertNotIn("mode", projected)
        self.assertNotIn("capabilityProfiles", projected)
        self.assertEqual(projected, owner_templates_manifest.canonical_manifest(legacy))

    def test_conflicting_mode_aliases_are_rejected(self) -> None:
        manifest = self.manifest()
        manifest["mode"] = "governed-sdd"
        with self.assertRaisesRegex(shared_errors.MeridianError, "mode and workflowMode conflict"):
            owner_templates_manifest.validate_manifest(manifest, self.catalog)

    def test_invalid_state_empty_surface_and_missing_positive_evidence_are_rejected(self) -> None:
        cases = []
        unsupported = self.manifest()
        unsupported["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["language-policy"]["installation"]["state"] = "UNKNOWN"
        cases.append((unsupported, "state is unsupported"))
        empty_surface = self.manifest()
        empty_surface["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["language-policy"]["managedSurface"] = []
        cases.append((empty_surface, "managedSurface must be a non-empty list"))
        no_evidence = self.manifest()
        no_evidence["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["language-policy"]["installation"]["state"] = "INSTALLED"
        cases.append((no_evidence, "INSTALLED requires evidence"))
        for manifest, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(shared_errors.MeridianError, message):
                owner_templates_manifest.validate_manifest(manifest, self.catalog)

    def test_not_applicable_requires_a_catalog_backed_rationale(self) -> None:
        manifest = self.manifest()
        hosts = manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["queue-briefing"]["hostActivation"]
        hosts["codex-project"] = {
            "state": "NOT_APPLICABLE",
            "evidence": [],
            "notApplicableRationale": "host-profile-unsupported",
        }
        owner_templates_manifest.validate_manifest(manifest, self.catalog)
        hosts["codex-project"]["notApplicableRationale"] = None
        with self.assertRaisesRegex(shared_errors.MeridianError, "catalog-backed rationale"):
            owner_templates_manifest.validate_manifest(manifest, self.catalog)

    def test_upgrade_check_reads_profile_without_writing_or_promoting_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            framework = root / "framework"
            project = root / "project"
            for source in ("templates", "migrations", "release-baselines", "capabilities"):
                shutil.copytree(ROOT / source, framework / source)
            (framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
            source = framework / "templates/workflows/governed-sdd"
            for path in source.rglob("*"):
                if path.is_file():
                    destination = project / path.relative_to(source)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
            command = [
                sys.executable,
                str(CLI),
                "--framework-root",
                str(framework),
                "lock",
                "--mode",
                "governed-sdd",
                "--project",
                str(project),
            ]
            locked = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
            manifest_path = project / shared_constants.MANIFEST_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["capabilityProfiles"] = self.manifest("governed-sdd")["capabilityProfiles"]
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            before = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            checked = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--framework-root",
                    str(framework),
                    "upgrade",
                    "--check",
                    "--project",
                    str(project),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            after = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
            installation = persisted["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]["language-policy"]["installation"]
            self.assertEqual(installation["state"], "MISSING")

    def test_retired_text_audit_advisories_preserve_exit_status_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            (project / ".meridian/candidate-validation.json").write_text('{"version": 1, "state": "none"}\n', encoding="utf-8")
            baseline_code, _ = self.audit(project)
            self.assertEqual(baseline_code, 0)
            for relative_path in owner_templates_audit.load_retired_text_registry(ROOT)[0]["files"]:
                path = project / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative_path + "\n## Reasoning profile\n", encoding="utf-8")
            manifest = self.installed_project(project)
            manifest["frameworkVersion"] = meridian.read_version(ROOT)
            owner_templates_manifest.write_manifest(project, manifest, ROOT)
            with mock.patch.object(owner_templates_audit, "retired_text_advisories", return_value=[]):
                baseline_code, _ = self.audit(project)
            self.assertEqual(baseline_code, 0)
            before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            code, output = self.audit(project)
            self.assertEqual(code, baseline_code, output)
            self.assertIn("SUMMARY worst=ADVISORY", output)
            self.assertEqual(output.count("ADVISORY       retired-text"), 2)
            self.assertIn("docs/CONTEXT_BUDGET_POLICY.md:2:", output)
            after = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_cross_mode_audit_accepts_complete_declarations_and_reports_counts(self) -> None:
        for mode in shared_constants.WORKFLOW_MODES:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.installed_project(project, mode)
                (project / ".meridian/candidate-validation.json").write_text(
                    '{"version": 1, "state": "none"}\n', encoding="utf-8"
                )

                return_code, output = self.audit(project, mode)

                self.assertEqual(return_code, 0, output)
                self.assertIn("PASS", output)
                self.assertIn("SUMMARY worst=PASS", output)
                for state in shared_constants.AUDIT_STATES:
                    self.assertRegex(output, rf"\b{state}=\d+")
                self.assertNotIn("No capability markers found", output)

    def test_audit_fails_missing_and_drifted_managed_surfaces(self) -> None:
        missing_surfaces = (
            ("LANGUAGE_POLICY.md", "missing managed-copy surface LANGUAGE_POLICY.md"),
            (".codex/hooks.json", "missing managed-copy surface .codex/hooks.json"),
            ("hooks/read-guard.sh", "missing shared-source surface hooks/read-guard.sh"),
        )
        for relative_path, diagnostic in missing_surfaces:
            with self.subTest(surface=relative_path), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.installed_project(project)
                (project / relative_path).unlink()

                return_code, output = self.audit(project)

                self.assertEqual(return_code, 2, output)
                self.assertIn(diagnostic, output)
                self.assertIn("SUMMARY worst=FAIL", output)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            hook = project / "hooks/read-guard.sh"
            hook.write_text("drifted\n", encoding="utf-8")

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("stale digest evidence", output)
            self.assertIn("shared-source:hooks/read-guard.sh", output)

    def test_audit_rejects_empty_surfaces_and_invalid_positive_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            declaration = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]["language-policy"]
            declaration["managedSurface"] = []
            (project / shared_constants.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("managedSurface must be a non-empty list", output)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            activation = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]["language-policy"]["hostActivation"]["codex-project"]
            activation["evidence"] = ["positive-claim-without-an-artifact"]
            (project / shared_constants.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("invalid positive evidence", output)
            self.assertIn("expected probe:<path>", output)

    def test_audit_reports_stale_evidence_and_mixed_aggregate_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]
            capabilities["language-policy"]["hostActivation"]["codex-project"] = {
                "state": "UNVERIFIED",
                "evidence": [],
                "notApplicableRationale": None,
            }
            capabilities["read-guard"]["verification"]["verifierVersion"] = "0.0.0"
            (project / shared_constants.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("UNVERIFIED", output)
            self.assertIn("stale verifierVersion", output)
            self.assertIn("SUMMARY worst=FAIL", output)

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]
            advisory = capabilities["language-policy"]["hostActivation"]["codex-project"]
            advisory["state"] = "ADVISORY"
            capabilities["read-guard"]["hostActivation"]["codex-project"] = {
                "state": "UNVERIFIED",
                "evidence": [],
                "notApplicableRationale": None,
            }
            (project / shared_constants.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 1, output)
            self.assertRegex(output, r"ADVISORY=[1-9]\d*")
            self.assertRegex(output, r"UNVERIFIED=[1-9]\d*")
            self.assertIn("SUMMARY worst=UNVERIFIED", output)

    def test_audit_accepts_only_catalog_backed_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            framework = root / "framework"
            project = root / "project"
            shutil.copytree(ROOT, framework)
            catalog_path = framework / shared_constants.CAPABILITY_CATALOG_PATH
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog["capabilities"]["language-policy"]["workflowModes"] = ["governed-sdd"]
            catalog_path.write_text(
                json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            custom_catalog = owner_templates_catalog.load_capability_catalog(framework)
            self.catalog = custom_catalog
            manifest = self.installed_project(project)
            declaration = manifest["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]["language-policy"]
            declaration["installation"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "notApplicableRationale": "workflow-mode-excluded",
            }
            for activation in declaration["hostActivation"].values():
                activation.update(
                    state="NOT_APPLICABLE",
                    evidence=[],
                    notApplicableRationale="workflow-mode-excluded",
                )
            declaration["verification"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "verifiedAt": None,
                "verifierVersion": None,
                "notApplicableRationale": "workflow-mode-excluded",
            }
            manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"][
                "queue-briefing"
            ]["hostActivation"]["codex-project"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "notApplicableRationale": "host-profile-unsupported",
            }
            owner_templates_manifest.write_manifest(project, manifest, framework)
            (project / ".meridian/candidate-validation.json").write_text(
                '{"version": 1, "state": "none"}\n', encoding="utf-8"
            )
            output = io.StringIO()

            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(project, framework, "lean-delivery")

            self.assertEqual(return_code, 0, output.getvalue())
            self.assertIn("NOT_APPLICABLE", output.getvalue())
            self.assertIn("catalog exclusion: workflow-mode-excluded", output.getvalue())
            self.assertIn(
                "meridian-self-hosting/queue-briefing/host/codex-project",
                output.getvalue(),
            )
            self.assertIn("catalog exclusion: host-profile-unsupported", output.getvalue())

    def test_legacy_lean_manifest_is_named_and_migration_history_is_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            owner_templates_manifest.write_manifest(
                project,
                {
                    "protocolVersion": 1,
                    "mode": "lean-delivery",
                    "frameworkVersion": meridian.read_version(ROOT),
                    "managedFiles": {},
                    "appliedMigrations": ["040-pretooluse-read-guard"],
                },
                ROOT,
            )

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 1, output)
            self.assertIn("declaration/legacy-compatibility", output)
            self.assertIn("migration history is provenance only", output)
            self.assertIn("SUMMARY worst=UNVERIFIED", output)

    def test_lean_managed_files_deliver_only_neutral_profile_surfaces(self) -> None:
        lean_paths = {
            item.target.as_posix()
            for item in owner_templates_files.managed_files(ROOT, "lean-delivery")
        }
        self.assertTrue(
            {
                "LANGUAGE_POLICY.md",
                "docs/CONTEXT_BUDGET_POLICY.md",
                "docs/EXECUTION_EVIDENCE_PROFILE.md",
                ".codex/hooks.json",
                ".codex/rules/meridian.rules",
            }
            <= lean_paths
        )
        policy = (
            ROOT / "templates/workflows/lean-delivery/docs/CONTEXT_BUDGET_POLICY.md"
        ).read_text(encoding="utf-8")
        for governed_only in (
            "READY_FOR_REVIEW",
            "ACCEPTED",
            "owner acceptance",
            "reviewer-integrator",
            "Authority entries",
        ):
            self.assertNotIn(governed_only, policy)

    def test_bootstrap_observes_installation_without_promoting_host_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = {
                "protocolVersion": shared_constants.PROTOCOL_VERSION,
                "frameworkVersion": meridian.read_version(ROOT),
                "workflowMode": "lean-delivery",
                "managedFiles": {},
                "appliedMigrations": [],
            }
            owner_templates_manifest.write_manifest(project, manifest, ROOT)
            profile = self.catalog.profile("meridian-self-hosting")
            self.assertIsNotNone(profile)
            for capability_id, _version in profile.capabilities:
                capability = self.catalog.capability(capability_id)
                self.assertIsNotNone(capability)
                for surface in capability.managed_surfaces:
                    source = ROOT / surface.path
                    destination = project / surface.path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)

            observed = owner_templates_adoption.bootstrap_capability_profile(
                project, ROOT, "meridian-self-hosting", apply=True
            )
            declarations = observed["capabilityProfiles"]["meridian-self-hosting"][
                "capabilities"
            ]
            self.assertTrue(declarations)
            for declaration in declarations.values():
                self.assertEqual(declaration["installation"]["state"], "INSTALLED")
                self.assertEqual(declaration["verification"]["state"], "UNVERIFIED")
                self.assertTrue(
                    all(
                        host["state"] == "UNVERIFIED"
                        for host in declaration["hostActivation"].values()
                    )
                )

            return_code, output = self.audit(project)
            self.assertEqual(return_code, 1, output)
            self.assertNotRegex(output, r"(?m)^FAIL\s")
            self.assertIn("SUMMARY worst=UNVERIFIED", output)

    def test_live_execution_profile_has_no_unresolved_configuration_placeholder(self) -> None:
        profile = (ROOT / "docs/EXECUTION_EVIDENCE_PROFILE.md").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(profile, r"\[[^]]*(?:describe|command|method|bound|policy|tool)[^]]*\]")
        self.assertIn("python3 scripts/check_repository.py", profile)
        self.assertIn("python3 -m unittest discover -s tests -q 2>&1 | tail -n 40", profile)
