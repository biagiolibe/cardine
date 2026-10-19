"""Synthetic product installations and isolated frozen-hook fixtures."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import meridian

from cardine.shared import constants as shared_constants
from cardine.shared import hashing as shared_hashing
from cardine.shared.layout import names
from cardine.templates import catalog as owner_templates_catalog
from cardine.templates import manifest as owner_templates_manifest


class InstallationFixture:
    def __init__(self, framework: Path = ROOT):
        self.framework = framework
        self.catalog = owner_templates_catalog.load_capability_catalog(framework)

    def manifest(self, mode: str = "lean-delivery") -> dict[str, object]:
        profile = self.catalog.profile("meridian-self-hosting")
        assert profile is not None
        capabilities: dict[str, object] = {}
        for capability_id, version in profile.capabilities:
            capability = self.catalog.capability(capability_id)
            assert capability is not None
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
                probe_path = f"{names().project_directory}/evidence/{capability_id}-{host_id}.json"
                probe = project / probe_path
                probe.parent.mkdir(parents=True, exist_ok=True)
                probe.write_text("{}\n", encoding="utf-8")
                host_activation[host_id] = {
                    "state": "ENFORCED",
                    "evidence": [f"probe:{probe_path}"],
                    "notApplicableRationale": None,
                }
            declaration["hostActivation"] = host_activation
            verification_path = f"{names().project_directory}/evidence/{capability_id}-verification.json"
            verification_probe = project / verification_path
            verification_probe.parent.mkdir(parents=True, exist_ok=True)
            verification_probe.write_text("{}\n", encoding="utf-8")
            declaration["verification"] = {
                "state": "PASS",
                "evidence": [f"probe:{verification_path}"],
                "verifiedAt": "2026-09-28T00:00:00Z",
                "verifierVersion": meridian.read_version(self.framework),
                "notApplicableRationale": None,
            }
        manifest["managedFiles"] = managed_files
        owner_templates_manifest.write_manifest(project, manifest, self.framework)
        return manifest

    def write_probes(self, project: Path) -> None:
        """Build probe records from the product catalog, never the checkout installation."""
        profile = self.catalog.profile("meridian-self-hosting")
        for host, relative in (("host-neutral-ci", profile.verification_probe), *profile.host_probes):
            capabilities = [
                capability_id for capability_id, _version in profile.capabilities
                if host == "host-neutral-ci" or host in dict(self.catalog.capability(capability_id).host_profiles)
            ]
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "schemaVersion": 1, "profileId": profile.profile_id,
                "profileVersion": profile.version, "hostProfile": host,
                "host": "synthetic test host", "hostVersion": "fixture",
                "invocationMode": "fixture", "configurationLayer": "fixture",
                "fallback": "Keep host activation unverified.",
                "state": "UNVERIFIED", "observationTime": None, "evidenceArtifact": None,
                "checks": [{"capability": capability, "behavior": "fixture observation",
                            "dimensions": ["fixture"]} for capability in capabilities],
            }), encoding="utf-8")


def hook_environment(environment: dict[str, str] | None = None) -> dict[str, str]:
    result = dict(os.environ if environment is None else environment)
    # Host plugin settings must not redirect the copied hook to another installation.
    result.pop("PLUGIN_ROOT", None)
    result.pop("CLAUDE_PLUGIN_ROOT", None)
    return result


def copy_hook(root: Path, filename: str) -> Path:
    # MERIDIAN-INSTALLATION-CHECK: copy the frozen hook as installation data.
    source = ROOT / "hooks" / filename
    hook = root / "hooks" / filename
    hook.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, hook)
    # MERIDIAN-INSTALLATION-CHECK: fixture shim for the frozen hook's executable name.
    runner = root / "bin/meridian"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text(
        "#!/bin/sh\nexec " + shlex.quote(str(ROOT / "bin/meridian")) + ' "$@"\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)
    return hook
