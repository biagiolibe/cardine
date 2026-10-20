"""Capability profile declarations shared by profile bootstrap and upgrades."""

from __future__ import annotations

from cardine.shared.constants import STRICT_DIGEST_PROFILES
from cardine.shared.errors import CardineError
from cardine.shared.hashing import sha256
from cardine.shared.models import CatalogCapability
from cardine.templates.audit import _digest_exempt
from cardine.templates.catalog import load_capability_catalog
from cardine.templates.catalog import manifest_workflow_mode
from cardine.templates.manifest import canonical_manifest
from cardine.templates.manifest import load_manifest
from cardine.templates.manifest import validate_manifest
from cardine.templates.manifest import write_manifest
from pathlib import Path


def _capability_declaration(
    project_root: Path,
    capability: CatalogCapability,
    required_version: int,
    managed_files: dict[str, object],
    strict: bool,
) -> dict[str, object]:
    """One profile capability declaration built from the catalog surface and the
    files on disk; records managed-copy digests into `managed_files`."""
    surfaces: list[dict[str, str]] = []
    evidence: list[str] = []
    complete = True
    for surface in capability.managed_surfaces:
        form = surface.forms[0]
        surfaces.append({"path": surface.path, "form": form})
        path = project_root / surface.path
        if form != "declaration-only" and not path.is_file():
            complete = False
            continue
        if form != "declaration-only":
            digest = sha256(path)
            digest_exempt = (
                form == "managed-copy"
                and not strict
                and _digest_exempt(surface.path, path)
            )
            if form == "managed-copy":
                recorded = managed_files.get(surface.path)
                # Recording the current digest over a different recorded one
                # would launder a drifted copy. A marker-bearing consumer file is
                # verified region by region, so its recorded digest is left alone.
                if recorded is not None and recorded != digest and not digest_exempt:
                    raise CardineError(
                        f"managed copy {surface.path} differs from the digest recorded at install; "
                        "restore the released text before bootstrapping"
                    )
                if not digest_exempt:
                    managed_files[surface.path] = digest
            evidence.append(f"path:{surface.path}" if digest_exempt else f"sha256:{digest}")
    return {
        "requiredVersion": required_version,
        "managedSurface": surfaces,
        "installation": {
            "state": "INSTALLED" if complete else "MISSING",
            "evidence": sorted(set(evidence)),
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



def bootstrap_capability_profile(
    project_root: Path, framework_root: Path, profile_id: str, *, apply: bool
) -> dict[str, object]:
    """Observe catalog surfaces and conservatively declare one profile.

    Static files can establish installation only. Host activation and
    capability verification remain UNVERIFIED until a versioned probe records
    stronger evidence.
    """
    manifest = load_manifest(project_root, framework_root)
    catalog = load_capability_catalog(framework_root)
    profile = catalog.profile(profile_id)
    if profile is None:
        raise CardineError(f"capability profile is not present in the catalog: {profile_id}")
    manifest_workflow_mode(manifest)
    strict = profile_id in STRICT_DIGEST_PROFILES
    declarations: dict[str, object] = {}
    managed_files = dict(manifest.get("managedFiles", {}))
    for capability_id, required_version in profile.capabilities:
        capability = catalog.capability(capability_id)
        assert capability is not None
        declarations[capability_id] = _capability_declaration(
            project_root, capability, required_version, managed_files, strict
        )
    updated = canonical_manifest(manifest)
    profiles = dict(updated.get("capabilityProfiles", {}))
    profiles[profile_id] = {
        "profileVersion": profile.version,
        "capabilities": declarations,
    }
    updated["capabilityProfiles"] = profiles
    updated["managedFiles"] = dict(sorted(managed_files.items()))
    validate_manifest(updated, catalog)
    if apply:
        write_manifest(project_root, updated, framework_root)
    return updated
