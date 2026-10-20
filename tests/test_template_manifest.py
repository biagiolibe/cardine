"""Framework CLI regression tests for template manifest."""

from __future__ import annotations

from cardine_cli_support import CLI, ROOT
from installation_fixture import InstallationFixture
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
import cardine_cli
from cardine.tasks.contract import resolve_task_contract
from project_config_support import write_project_config
from task_contract_support import VALIDATION
import re


class CapabilityVersionDetectionTest(unittest.TestCase):
    """Version-aware detection uses the current marker catalog."""

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
        # Legacy adoption labels remain stable; requirements come only from the catalog.
        directory = self.framework / "capabilities"
        directory.mkdir(exist_ok=True)
        (directory / "markers-v1.json").write_text(json.dumps({
            "catalogVersion": 1,
            "capabilities": {capability: {
                "requiredVersion": version, "required": True, "retired": False,
                "adoptionRecord": filename.removesuffix(".json"),
            }},
        }), encoding="utf-8")

    def test_requirement_uses_the_current_catalog_version(self) -> None:
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
        # MERIDIAN-INSTALLATION-CHECK
        agents = self.project / "AGENTS.md"
        # MERIDIAN-INSTALLATION-CHECK
        claude = self.project / "CLAUDE.md"
        for path in (agents, claude):
            path.write_text("", encoding="utf-8")

        import cardine_cli as m

        # MERIDIAN-INSTALLATION-CHECK
        managed = [m.ManagedFile(source=Path("unused"), target=Path("AGENTS.md"))]
        original_managed_files = owner_templates_marker_history.managed_files
        owner_templates_marker_history.managed_files = lambda framework_root, mode: managed
        try:
            absent = owner_templates_marker_history.capability_presence_map(self.project, "governed-sdd", self.framework)
            self.assertEqual(len(absent), 1)
            self.assertFalse(absent["widget"][0])
            self.assertIn("no MERIDIAN:BEGIN", absent["widget"][1])

            agents.write_text(
                "<!-- MERIDIAN:BEGIN capability=widget v1 -->text<!-- MERIDIAN:END -->",
                encoding="utf-8",
            )
            stale = owner_templates_marker_history.capability_presence_map(self.project, "governed-sdd", self.framework)
            self.assertFalse(stale["widget"][0])
            self.assertEqual(stale["widget"][1], "marker present at v1, but v2 is required")

            agents.write_text(
                "<!-- MERIDIAN:BEGIN capability=widget v2 -->text<!-- MERIDIAN:END -->",
                encoding="utf-8",
            )
            satisfied = owner_templates_marker_history.capability_presence_map(self.project, "governed-sdd", self.framework)
            self.assertTrue(satisfied["widget"][0])
        finally:
            owner_templates_marker_history.managed_files = original_managed_files


class MarkerCatalogTest(unittest.TestCase):
    def test_catalog_readers_work_without_migration_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            framework = Path(temporary)
            shutil.copytree(ROOT / "capabilities", framework / "capabilities")
            self.assertEqual(
                owner_templates_migrations.capability_requirements(framework),
                owner_templates_catalog.marker_requirements(ROOT),
            )
            self.assertEqual(
                owner_templates_migrations.retired_capability_ids(framework),
                owner_templates_migrations.retired_capability_ids(ROOT),
            )
            # MERIDIAN-INSTALLATION-CHECK
            managed = mock.Mock(target=Path("AGENTS.md"))
            with mock.patch.object(owner_templates_marker_history, "managed_files", return_value=[managed]):
                self.assertEqual(
                    owner_templates_marker_history.capability_presence_map(framework, "governed-sdd", framework),
                    owner_templates_marker_history.capability_presence_map(framework, "governed-sdd", ROOT),
                )

    def test_invalid_marker_catalog_fields_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            framework = Path(temporary)
            directory = framework / "capabilities"
            directory.mkdir()
            for field, value in (("requiredVersion", 0), ("required", "true"), ("retired", 0)):
                with self.subTest(field=field):
                    entry = {"requiredVersion": 1, "required": True, "retired": False, "adoptionRecord": "rule"}
                    entry[field] = value
                    (directory / "markers-v1.json").write_text(json.dumps({
                        "catalogVersion": 1, "capabilities": {"rule": entry},
                    }), encoding="utf-8")
                    with self.assertRaises(shared_errors.CardineError):
                        owner_templates_catalog.marker_requirements(framework)


class CapabilityProfileManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = owner_templates_catalog.load_capability_catalog(ROOT)

    def manifest(self, mode: str = "lean-delivery") -> dict[str, object]:
        return InstallationFixture().manifest(mode)

    def installed_project(self, project: Path, mode: str = "lean-delivery") -> dict[str, object]:
        return InstallationFixture().installed_project(project, mode)

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
        self.assertEqual(read_guard.distribution, "single")
        self.assertTrue(read_guard.self_hosting_eligible)
        self.assertIn(("codex-project", "hook-invocation-observation"), read_guard.host_profiles)
        self.assertIn("shared-source", read_guard.installation_forms)
        self.assertTrue(read_guard.managed_surfaces)
        self.assertEqual(read_guard.dependencies, (("context-reading", 1),))
        profile = self.catalog.profile("cardine-self-hosting")
        self.assertEqual(
            profile.verification_probe,
            # MERIDIAN-INSTALLATION-CHECK
            ".cardine/probes/cardine-self-hosting/host-neutral-ci-v1.json",
        )
        self.assertEqual(
            set(dict(profile.host_probes)), {"claude-project", "codex-project"}
        )

    def test_profile_doctor_is_read_only_and_resolves_required_probes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            InstallationFixture().write_probes(project)
            before = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.profile_doctor(
                    project, ROOT, "cardine-self-hosting"
                )
            after = {
                path.relative_to(project): path.read_bytes()
                for path in project.rglob("*")
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
                InstallationFixture().write_probes(project)
                self.installed_project(project)
                probe = project / dict(self.catalog.profile("cardine-self-hosting").host_probes)["codex-project"]
                if mutation == "missing":
                    probe.unlink()
                else:
                    data = json.loads(probe.read_text(encoding="utf-8"))
                    data["checks"] = data["checks"][:-1]
                    probe.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    return_code = owner_templates_audit.profile_doctor(
                        project, ROOT, "cardine-self-hosting"
                    )
                self.assertEqual(return_code, 2, output.getvalue())
                self.assertIn(diagnostic, output.getvalue())

    def test_ci_profile_gate_accepts_host_unverified_but_rejects_static_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            capabilities = manifest["capabilityProfiles"]["cardine-self-hosting"]["capabilities"]
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
                    project, ROOT, "lean-delivery", "cardine-self-hosting"
                )
            self.assertEqual(return_code, 0, output.getvalue())
            self.assertIn("SUMMARY worst=UNVERIFIED", output.getvalue())
            self.assertIn("CI_GATE profile=cardine-self-hosting worst=PASS", output.getvalue())

            # MERIDIAN-INSTALLATION-CHECK
            (project / ".codex/hooks.json").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(
                    project, ROOT, "lean-delivery", "cardine-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            # MERIDIAN-INSTALLATION-CHECK
            self.assertIn("missing managed-copy surface .codex/hooks.json", output.getvalue())

    def test_ci_profile_gate_rejects_missing_managed_policy_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            # MERIDIAN-INSTALLATION-CHECK
            (project / "docs/CONTEXT_READING_POLICY.md").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(
                    project, ROOT, "lean-delivery", "cardine-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn(
                # MERIDIAN-INSTALLATION-CHECK
                "missing managed-copy surface docs/CONTEXT_READING_POLICY.md",
                output.getvalue(),
            )

    def test_ci_profile_gate_rejects_missing_shared_hook_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            # MERIDIAN-INSTALLATION-CHECK
            (project / "hooks/queue-briefing.sh").unlink()
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(
                    project, ROOT, "lean-delivery", "cardine-self-hosting"
                )
            self.assertEqual(return_code, 2, output.getvalue())
            self.assertIn(
                # MERIDIAN-INSTALLATION-CHECK
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
        # MERIDIAN-INSTALLATION-CHECK
        manifest_text = (ROOT / ".meridian/manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        capabilities = manifest["capabilityProfiles"]["meridian-self-hosting"]["capabilities"]  # MERIDIAN-INSTALLATION-CHECK
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
        with self.assertRaisesRegex(shared_errors.CardineError, "mode and workflowMode conflict"):
            owner_templates_manifest.validate_manifest(manifest, self.catalog)

    def test_invalid_state_empty_surface_and_missing_positive_evidence_are_rejected(self) -> None:
        cases = []
        unsupported = self.manifest()
        unsupported["capabilityProfiles"]["cardine-self-hosting"]["capabilities"]["language-policy"]["installation"]["state"] = "UNKNOWN"
        cases.append((unsupported, "state is unsupported"))
        empty_surface = self.manifest()
        empty_surface["capabilityProfiles"]["cardine-self-hosting"]["capabilities"]["language-policy"]["managedSurface"] = []
        cases.append((empty_surface, "managedSurface must be a non-empty list"))
        no_evidence = self.manifest()
        no_evidence["capabilityProfiles"]["cardine-self-hosting"]["capabilities"]["language-policy"]["installation"]["state"] = "INSTALLED"
        cases.append((no_evidence, "INSTALLED requires evidence"))
        for manifest, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(shared_errors.CardineError, message):
                owner_templates_manifest.validate_manifest(manifest, self.catalog)

    def test_not_applicable_requires_a_catalog_backed_rationale(self) -> None:
        manifest = self.manifest()
        hosts = manifest["capabilityProfiles"]["cardine-self-hosting"]["capabilities"]["queue-briefing"]["hostActivation"]
        hosts["codex-project"] = {
            "state": "NOT_APPLICABLE",
            "evidence": [],
            "notApplicableRationale": "host-profile-unsupported",
        }
        owner_templates_manifest.validate_manifest(manifest, self.catalog)
        hosts["codex-project"]["notApplicableRationale"] = None
        with self.assertRaisesRegex(shared_errors.CardineError, "catalog-backed rationale"):
            owner_templates_manifest.validate_manifest(manifest, self.catalog)

    def test_upgrade_check_reads_profile_without_writing_or_promoting_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            framework = root / "framework"
            project = root / "project"
            for source in ("templates", "migrations", "capabilities"):
                shutil.copytree(ROOT / source, framework / source)
            (framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
            source = framework / "templates/single"
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
            installation = persisted["capabilityProfiles"]["cardine-self-hosting"]["capabilities"]["language-policy"]["installation"]
            self.assertEqual(installation["state"], "MISSING")

    def test_retired_text_audit_advisories_preserve_exit_status_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.installed_project(project)
            # MERIDIAN-INSTALLATION-CHECK
            (project / ".cardine/candidate-validation.json").write_text('{"version": 1, "state": "none"}\n', encoding="utf-8")
            baseline_code, _ = self.audit(project)
            self.assertEqual(baseline_code, 0)
            for relative_path in owner_templates_audit.load_retired_text_registry(ROOT)[0]["files"]:
                path = project / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative_path + "\n## Reasoning profile\n", encoding="utf-8")
            manifest = self.installed_project(project)
            manifest["frameworkVersion"] = cardine_cli.read_version(ROOT)
            owner_templates_manifest.write_manifest(project, manifest, ROOT)
            with mock.patch.object(owner_templates_audit, "retired_text_advisories", return_value=[]):
                baseline_code, _ = self.audit(project)
            self.assertEqual(baseline_code, 0)
            before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            code, output = self.audit(project)
            self.assertEqual(code, baseline_code, output)
            self.assertIn("SUMMARY worst=ADVISORY", output)
            self.assertEqual(output.count("ADVISORY       retired-text"), 2)
            # MERIDIAN-INSTALLATION-CHECK
            self.assertIn("docs/CONTEXT_READING_POLICY.md:2:", output)
            after = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
            self.assertEqual(after, before)

    def test_cross_mode_audit_accepts_complete_declarations_and_reports_counts(self) -> None:
        for mode in shared_constants.WORKFLOW_MODES:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.installed_project(project, mode)
                # MERIDIAN-INSTALLATION-CHECK
                (project / ".cardine/candidate-validation.json").write_text(
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
            # MERIDIAN-INSTALLATION-CHECK
            ("LANGUAGE_POLICY.md", "missing managed-copy surface LANGUAGE_POLICY.md"),
            # MERIDIAN-INSTALLATION-CHECK
            (".codex/hooks.json", "missing managed-copy surface .codex/hooks.json"),
            # MERIDIAN-INSTALLATION-CHECK
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
            # MERIDIAN-INSTALLATION-CHECK
            hook = project / "hooks/read-guard.sh"
            hook.write_text("drifted\n", encoding="utf-8")

            return_code, output = self.audit(project)

            self.assertEqual(return_code, 2, output)
            self.assertIn("stale digest evidence", output)
            # MERIDIAN-INSTALLATION-CHECK
            self.assertIn("shared-source:hooks/read-guard.sh", output)

    def test_audit_rejects_empty_surfaces_and_invalid_positive_claims(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manifest = self.installed_project(project)
            declaration = manifest["capabilityProfiles"]["cardine-self-hosting"][
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
            activation = manifest["capabilityProfiles"]["cardine-self-hosting"][
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
            capabilities = manifest["capabilityProfiles"]["cardine-self-hosting"][
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
            capabilities = manifest["capabilityProfiles"]["cardine-self-hosting"][
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
            catalog["capabilities"]["language-policy"]["selfHostingEligible"] = False
            catalog_path.write_text(
                json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            custom_catalog = owner_templates_catalog.load_capability_catalog(framework)
            self.catalog = custom_catalog
            manifest = self.installed_project(project)
            declaration = manifest["capabilityProfiles"]["cardine-self-hosting"][
                "capabilities"
            ]["language-policy"]
            declaration["installation"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "notApplicableRationale": "self-hosting-ineligible",
            }
            for activation in declaration["hostActivation"].values():
                activation.update(
                    state="NOT_APPLICABLE",
                    evidence=[],
                    notApplicableRationale="self-hosting-ineligible",
                )
            declaration["verification"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "verifiedAt": None,
                "verifierVersion": None,
                "notApplicableRationale": "self-hosting-ineligible",
            }
            manifest["capabilityProfiles"]["cardine-self-hosting"]["capabilities"][
                "queue-briefing"
            ]["hostActivation"]["codex-project"] = {
                "state": "NOT_APPLICABLE",
                "evidence": [],
                "notApplicableRationale": "host-profile-unsupported",
            }
            owner_templates_manifest.write_manifest(project, manifest, framework)
            # MERIDIAN-INSTALLATION-CHECK
            (project / ".cardine/candidate-validation.json").write_text(
                '{"version": 1, "state": "none"}\n', encoding="utf-8"
            )
            output = io.StringIO()

            with redirect_stdout(output):
                return_code = owner_templates_audit.run_audit(project, framework, "lean-delivery")

            self.assertEqual(return_code, 0, output.getvalue())
            self.assertIn("NOT_APPLICABLE", output.getvalue())
            self.assertIn("catalog exclusion: self-hosting-ineligible", output.getvalue())
            self.assertIn(
                "cardine-self-hosting/queue-briefing/host/codex-project",
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
                    "frameworkVersion": cardine_cli.read_version(ROOT),
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
                # MERIDIAN-INSTALLATION-CHECK
                "LANGUAGE_POLICY.md",
                # MERIDIAN-INSTALLATION-CHECK
                "docs/CONTEXT_READING_POLICY.md",
                # MERIDIAN-INSTALLATION-CHECK
                "docs/EXECUTION_EVIDENCE_PROFILE.md",
                # MERIDIAN-INSTALLATION-CHECK
                ".codex/hooks.json",
                # MERIDIAN-INSTALLATION-CHECK
                ".codex/rules/meridian.rules",
            }
            <= lean_paths
        )
        policy = (
            ROOT / "templates/single/docs/CONTEXT_READING_POLICY.md"
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
                "frameworkVersion": cardine_cli.read_version(ROOT),
                "workflowMode": "lean-delivery",
                "managedFiles": {},
                "appliedMigrations": [],
            }
            owner_templates_manifest.write_manifest(project, manifest, ROOT)
            profile = self.catalog.profile("cardine-self-hosting")
            self.assertIsNotNone(profile)
            for capability_id, _version in profile.capabilities:
                capability = self.catalog.capability(capability_id)
                self.assertIsNotNone(capability)
                for surface in capability.managed_surfaces:
                    # Managed copies come from the template set; this checkout's own
                    # copies stay frozen until work item 10.
                    source = ROOT / "templates/single" / surface.path
                    if not source.is_file():
                        source = ROOT / surface.path
                    destination = project / surface.path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)

            observed = owner_templates_adoption.bootstrap_capability_profile(
                project, ROOT, "cardine-self-hosting", apply=True
            )
            declarations = observed["capabilityProfiles"]["cardine-self-hosting"][
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
        # MERIDIAN-INSTALLATION-CHECK
        profile = (ROOT / "docs/EXECUTION_EVIDENCE_PROFILE.md").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(profile, r"\[[^]]*(?:describe|command|method|bound|policy|tool)[^]]*\]")
        self.assertIn("python3 scripts/check_repository.py", profile)
        self.assertIn("python3 -m unittest discover -s tests -q 2>&1 | tail -n 40", profile)


LEGACY_TEMPLATE_ROOTS = ("base", "workflows/lean-delivery", "workflows/governed-sdd")
# Old source files that the single set renames or merges into another destination.
MERGED_DESTINATIONS = {
    "workflows/governed-sdd/docs/workflows/LIFECYCLE.md": "docs/LIFECYCLE_ORCHESTRATION.md",
    "workflows/governed-sdd/docs/PULL_REQUEST_POLICY.md": "docs/INTEGRATION_POLICY.md",
}
HIDDEN_DESTINATIONS = {
    "base/.gitignore": ".gitignore",
    "base/.claudeignore": ".claudeignore",
    "workflows/lean-delivery/.codex/hooks.json": ".codex/hooks.json",
    "workflows/lean-delivery/.codex/rules/meridian.rules": ".codex/rules/meridian.rules",
    "workflows/governed-sdd/.codex/hooks.json": ".codex/hooks.json",
    "workflows/governed-sdd/.codex/rules/meridian.rules": ".codex/rules/meridian.rules",
}


def legacy_template_sources() -> list[str]:
    """Every file under the three old source roots, relative to `templates/`."""
    return [
        'base/.claudeignore',
        'base/.gitignore',
        'base/CLAUDE.md',
        'base/LANGUAGE_POLICY.md',
        'base/PROJECT_PLAN.md',
        'base/README.md',
        'base/TECH_DESIGN.md',
        'base/tasks/QUEUE.md',
        'base/tasks/TASK_BLUEPRINT.md',
        'workflows/governed-sdd/.codex/hooks.json',
        'workflows/governed-sdd/.codex/rules/meridian.rules',
        'workflows/governed-sdd/AGENTS.md',
        'workflows/governed-sdd/CLAUDE.md',
        'workflows/governed-sdd/LANGUAGE_POLICY.md',
        'workflows/governed-sdd/PROJECT_WORKFLOW.md',
        'workflows/governed-sdd/docs/ARCHITECTURE_DECISIONS.md',
        'workflows/governed-sdd/docs/AUDIT_PROMPT_READ_ONLY.md',
        'workflows/governed-sdd/docs/CODE_ORGANIZATION.md',
        'workflows/governed-sdd/docs/CODE_REVIEW_PROMPT.md',
        'workflows/governed-sdd/docs/COMPLETION_REPORT_TEMPLATE.md',
        'workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md',
        'workflows/governed-sdd/docs/EXECUTION_EVIDENCE_PROFILE.md',
        'workflows/governed-sdd/docs/LIFECYCLE_ORCHESTRATION.md',
        'workflows/governed-sdd/docs/OPERATOR_PROMPTS.md',
        'workflows/governed-sdd/docs/PULL_REQUEST_POLICY.md',
        'workflows/governed-sdd/docs/REVIEW_RECORD_TEMPLATE.md',
        'workflows/governed-sdd/docs/WORKTREE_LIFECYCLE.md',
        'workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md',
        'workflows/governed-sdd/docs/workflows/LIFECYCLE.md',
        'workflows/governed-sdd/docs/workflows/REMEDIATION.md',
        'workflows/governed-sdd/docs/workflows/REVIEW.md',
        'workflows/governed-sdd/tasks/QUEUE.md',
        'workflows/governed-sdd/tasks/TASK_BLUEPRINT.md',
        'workflows/lean-delivery/.codex/hooks.json',
        'workflows/lean-delivery/.codex/rules/meridian.rules',
        'workflows/lean-delivery/AGENTS.md',
        'workflows/lean-delivery/CLAUDE.md',
        'workflows/lean-delivery/LANGUAGE_POLICY.md',
        'workflows/lean-delivery/PROJECT_WORKFLOW.md',
        'workflows/lean-delivery/docs/COMPLETION_REPORT_TEMPLATE.md',
        'workflows/lean-delivery/docs/CONTEXT_BUDGET_POLICY.md',
        'workflows/lean-delivery/docs/EXECUTION_EVIDENCE_PROFILE.md',
        'workflows/lean-delivery/docs/WORKTREE_LIFECYCLE.md',
    ]



def single_destination(source: str) -> str:
    """The destination under `templates/single/` for one old source file."""
    if source.endswith("/docs/CONTEXT_BUDGET_POLICY.md"):
        return "docs/CONTEXT_READING_POLICY.md"
    if source in MERGED_DESTINATIONS:
        return MERGED_DESTINATIONS[source]
    for root in LEGACY_TEMPLATE_ROOTS:
        if source.startswith(root + "/"):
            return source.removeprefix(root + "/")
    raise AssertionError(source)


class SingleTemplateSetTest(unittest.TestCase):
    """Both presets install one template set, and no code falls back to the old roots."""

    SINGLE = ROOT / "templates" / "single"

    def framework_copy(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        framework = Path(temporary.name) / "framework"
        shutil.copytree(ROOT / "templates", framework / "templates")
        return framework

    def test_both_presets_install_the_same_file_list(self) -> None:
        lean = [item.target for item in owner_templates_files.managed_files(ROOT, "lean-delivery")]
        governed = [item.target for item in owner_templates_files.managed_files(ROOT, "governed-sdd")]
        self.assertEqual(lean, governed)
        self.assertTrue(all(item.source.is_relative_to(self.SINGLE) for item in owner_templates_files.managed_files(ROOT, "lean-delivery")))
        locked = {}
        for preset, mode in (("lean", "lean-delivery"), ("governed", "governed-sdd")):
            with tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                shutil.copytree(self.SINGLE, project, dirs_exist_ok=True)
                (project / ".cardine").mkdir(exist_ok=True)
                (project / ".cardine/project.json").write_text(
                    json.dumps({"version": 1, "preset": preset}), encoding="utf-8"
                )
                result = subprocess.run(
                    [sys.executable, str(CLI), "--framework-root", str(ROOT), "lock", "--mode", mode,
                     "--project", str(project)],
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                manifest = json.loads((project / ".cardine/manifest.json").read_text(encoding="utf-8"))
                locked[preset] = sorted(manifest["managedFiles"])
        self.assertEqual(locked["lean"], locked["governed"])
        self.assertEqual(locked["lean"], sorted(target.as_posix() for target in lean))

    def test_no_old_root_fallback(self) -> None:
        framework = self.framework_copy()
        expected = [item.target for item in owner_templates_files.managed_files(ROOT)]
        self.assertFalse((framework / "templates/workflows").exists())
        self.assertFalse((framework / "templates/base").exists())
        self.assertEqual([item.target for item in owner_templates_files.managed_files(framework)], expected)
        (framework / "templates/single/tasks/TASK_BLUEPRINT.md").unlink()
        with self.assertRaises(shared_errors.CardineError):
            owner_templates_files.managed_files(framework)
        shutil.rmtree(framework / "templates/single")
        with self.assertRaisesRegex(shared_errors.CardineError, "single template set is missing"):
            owner_templates_files.managed_files(framework, "governed-sdd")

    def test_no_product_code_reads_the_old_roots(self) -> None:
        allowed = set()
        offenders = []
        for path in sorted((ROOT / "src/cardine").rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            if relative not in allowed and re.search(r"templates/(?:base|workflows)|LEGACY_WORKFLOW_ROOT|legacy_managed_files", text):
                offenders.append(relative)
        self.assertEqual(offenders, [])
        files_text = (ROOT / "src/cardine/templates/files.py").read_text(encoding="utf-8")
        self.assertNotIn("legacy_managed_files", files_text)

    def test_every_old_source_file_has_a_destination_and_nothing_else_is_shipped(self) -> None:
        destinations = set()
        for source in legacy_template_sources():
            destination = single_destination(source)
            with self.subTest(source=source):
                self.assertTrue((self.SINGLE / destination).is_file(), destination)
            destinations.add(destination)
        shipped = {path.relative_to(self.SINGLE).as_posix() for path in self.SINGLE.rglob("*") if path.is_file()}
        self.assertEqual(shipped - destinations, set(), "a shipped file has no inventory source")

    def test_the_six_hidden_files_have_destinations(self) -> None:
        self.assertEqual(len(HIDDEN_DESTINATIONS), 6)
        for source, destination in HIDDEN_DESTINATIONS.items():
            with self.subTest(source=source):
                self.assertFalse((ROOT / "templates" / source).exists())
                self.assertEqual(single_destination(source), destination)
                self.assertTrue((self.SINGLE / destination).is_file())

    def test_context_policy_uses_the_reading_path(self) -> None:
        self.assertTrue((self.SINGLE / "docs/CONTEXT_READING_POLICY.md").is_file())
        self.assertFalse((self.SINGLE / "docs/CONTEXT_BUDGET_POLICY.md").exists())

    def test_template_links_and_document_paths_resolve_inside_the_set(self) -> None:
        link = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
        path = re.compile(r"`((?:docs|tasks)/[A-Za-z0-9_./-]+\.md)(?:#[^`]*)?`")
        # Queue rows and task examples are placeholders for files a project creates.
        placeholders = {"tasks/QUEUE.md"}
        for document in sorted(self.SINGLE.rglob("*.md")):
            relative = document.relative_to(self.SINGLE).as_posix()
            if relative in placeholders:
                continue
            text = document.read_text(encoding="utf-8")
            for target in link.findall(text):
                if re.match(r"[a-z]+:|#", target):
                    continue
                with self.subTest(document=relative, link=target):
                    resolved = (document.parent / target.split("#")[0]).resolve()
                    self.assertTrue(resolved.is_file() or (self.SINGLE / target.split("#")[0]).is_file(), target)
            for target in path.findall(text):
                if target.startswith(("tasks/<", "tasks/handoffs", "tasks/reviews", "tasks/done")) or "<" in target or "NNN" in target:
                    continue
                with self.subTest(document=relative, path=target):
                    self.assertTrue((self.SINGLE / target).is_file(), target)

    def test_one_task_shape_resolves_for_both_presets(self) -> None:
        blueprint = (self.SINGLE / "tasks/TASK_BLUEPRINT.md").read_text(encoding="utf-8")
        for heading in ("Spike shape", "Host impact"):
            blueprint = re.sub(rf"^## {heading}\n.*?(?=^## )", "", blueprint, flags=re.MULTILINE | re.DOTALL)
        for old, new in (
            ("# Task [ID] — [Title]", "# Task 001 — Shape fixture"),
            ("> **ID**: `[NNN]`", "> **ID**: `001`"),
            ("> **Priority**: [P0 / P1 / P2]", "> **Priority**: P1"),
            ("> **Estimate**: [~1h / ~2h / etc.]", "> **Estimate**: ~1h"),
            ("- **Depends on**: [none / TASK-ID, ...]", "- **Depends on**: none"),
            ("- `<validation-id>`: `<complete literal command, including its output bound and exit-status handling>`",
             "- `task-check`: `python3 -c 'pass'`"),
        ):
            self.assertIn(old, blueprint)
            blueprint = blueprint.replace(old, new)
        blueprint = re.sub(r"^(?:Class|Review|Options|Manual verification(?: rationale)?): \[.*\]\n", "", blueprint, flags=re.MULTILINE)
        self.assertNotIn("Budget usage", blueprint)
        snapshots = {}
        for preset in ("lean", "governed"):
            with tempfile.TemporaryDirectory() as directory:
                project = Path(directory).resolve()
                (project / "tasks").mkdir()
                write_project_config(project, preset, validation=json.loads(json.dumps(VALIDATION)))
                (project / "tasks/001.md").write_text(blueprint, encoding="utf-8")
                (project / "tasks/QUEUE.md").write_text(
                    "| ID | Status | Task file |\n|---|---|---|\n| 001 | queued | [001](001.md) |\n", encoding="utf-8"
                )
                snapshots[preset] = resolve_task_contract(project, "001")
        self.assertEqual(snapshots["lean"]["options"]["review"], "not_required")
        self.assertEqual(snapshots["governed"]["options"]["review"], "required")
        lean, governed = (dict(snapshots[name], preset=None, options=None, projectDigest=None) for name in ("lean", "governed"))
        self.assertEqual(lean, governed, "the presets may differ only in their option defaults")

    def test_local_prose_survives_a_template_update(self) -> None:
        framework = self.framework_copy()
        shutil.copytree(ROOT / "migrations", framework / "migrations")
        shutil.copytree(ROOT / "capabilities", framework / "capabilities")
        (framework / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        project = framework.parent / "project"
        shutil.copytree(framework / "templates/single", project)
        write_project_config(project, "lean")

        def cli(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(CLI), "--framework-root", str(framework), *arguments, "--project", str(project)],
                text=True, capture_output=True, check=False,
            )

        self.assertEqual(cli("lock", "--mode", "lean-delivery").returncode, 0)
        local_note = "\n## Project conventions\n\nProject-owned prose that no update may drop.\n"
        for name in ("PROJECT_WORKFLOW.md", "tasks/TASK_BLUEPRINT.md"):
            installed = project / name
            installed.write_text(installed.read_text(encoding="utf-8") + local_note, encoding="utf-8")
        template = framework / "templates/single/PROJECT_WORKFLOW.md"
        text = template.read_text(encoding="utf-8")
        self.assertIn("## Preset and options", text)
        template.write_text(text.replace("## Preset and options", "## Presets and task options", 1), encoding="utf-8")
        (framework / "VERSION").write_text("1.1.1\n", encoding="utf-8")
        applied = cli("upgrade", "--apply")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        upgraded = (project / "PROJECT_WORKFLOW.md").read_text(encoding="utf-8")
        self.assertIn("## Presets and task options", upgraded)
        for name in ("PROJECT_WORKFLOW.md", "tasks/TASK_BLUEPRINT.md"):
            self.assertIn("Project-owned prose that no update may drop.", (project / name).read_text(encoding="utf-8"))
