"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.constants import CAPABILITY_CATALOG_PATH
from cardine.shared.constants import CAPABILITY_CATALOG_VERSION
from cardine.shared.constants import HOST_ACTIVATION_STATES
from cardine.shared.constants import INSTALLATION_FORMS
from cardine.shared.constants import INSTALLATION_STATES
from cardine.shared.constants import VERIFICATION_STATES
from cardine.shared.constants import WORKFLOW_MODES
from cardine.shared.errors import MeridianError
from cardine.shared.models import CapabilityCatalog
from cardine.shared.models import CapabilityDeclaration
from cardine.shared.models import CapabilityProfileDeclaration
from cardine.shared.models import CatalogCapability
from cardine.shared.models import CatalogProfile
from cardine.shared.models import CatalogSurface
from cardine.shared.models import DeclaredSurface
from cardine.shared.models import EvidenceSnapshot
from cardine.shared.models import SAFE_PATH_COMPONENT
from cardine.shared.validation import _repository_relative_path
from cardine.shared.validation import _required_object
from cardine.shared.validation import _required_positive_integer
from cardine.shared.validation import _required_string
from cardine.shared.validation import _required_string_list
from cardine.templates.protocol import check_protocol_compatibility
from pathlib import Path
import json


def manifest_workflow_mode(manifest: dict[str, object]) -> str:
    """Return the canonical workflow mode without mutating a legacy manifest."""
    protocol_version = check_protocol_compatibility(manifest)
    legacy_mode = manifest.get("mode")
    workflow_mode = manifest.get("workflowMode")
    if legacy_mode is not None and workflow_mode is not None and legacy_mode != workflow_mode:
        raise MeridianError("manifest mode and workflowMode conflict")
    selected = workflow_mode if workflow_mode is not None else legacy_mode
    if selected is None:
        raise MeridianError("manifest must declare workflowMode (or legacy mode)")
    if not isinstance(selected, str) or selected not in WORKFLOW_MODES:
        raise MeridianError(
            "manifest workflowMode must be one of: " + ", ".join(WORKFLOW_MODES)
        )
    if protocol_version >= 2 and workflow_mode is None:
        raise MeridianError("manifest protocolVersion 2 requires workflowMode")
    return selected


def _parse_catalog_surface(value: object, label: str) -> CatalogSurface:
    data = _required_object(value, label)
    forms = _required_string_list(data.get("forms"), f"{label}.forms", non_empty=True)
    unsupported = sorted(set(forms) - set(INSTALLATION_FORMS))
    if unsupported:
        raise MeridianError(f"{label}.forms contains unsupported form: {unsupported[0]}")
    return CatalogSurface(
        path=_repository_relative_path(data.get("path"), f"{label}.path"),
        forms=forms,
    )


def parse_capability_catalog(value: object) -> CapabilityCatalog:
    data = _required_object(value, "capability catalog")
    catalog_version = _required_positive_integer(data.get("catalogVersion"), "catalogVersion")
    if catalog_version != CAPABILITY_CATALOG_VERSION:
        raise MeridianError(
            f"capability catalog version {catalog_version} is unsupported; "
            f"expected {CAPABILITY_CATALOG_VERSION}"
        )
    raw_capabilities = _required_object(data.get("capabilities"), "capabilities")
    raw_profiles = _required_object(data.get("profiles"), "profiles")
    capabilities: list[CatalogCapability] = []
    for capability_id, raw_capability in sorted(raw_capabilities.items()):
        if not SAFE_PATH_COMPONENT.fullmatch(capability_id):
            raise MeridianError(f"invalid capability ID: {capability_id!r}")
        label = f"capabilities.{capability_id}"
        item = _required_object(raw_capability, label)
        workflow_modes = _required_string_list(
            item.get("workflowModes"), f"{label}.workflowModes", non_empty=True
        )
        unsupported_modes = sorted(set(workflow_modes) - set(WORKFLOW_MODES))
        if unsupported_modes:
            raise MeridianError(
                f"{label}.workflowModes contains unsupported mode: {unsupported_modes[0]}"
            )
        eligible = item.get("selfHostingEligible")
        if type(eligible) is not bool:
            raise MeridianError(f"{label}.selfHostingEligible must be a boolean")
        forms = _required_string_list(
            item.get("installationForms"), f"{label}.installationForms", non_empty=True
        )
        unsupported_forms = sorted(set(forms) - set(INSTALLATION_FORMS))
        if unsupported_forms:
            raise MeridianError(
                f"{label}.installationForms contains unsupported form: {unsupported_forms[0]}"
            )
        surfaces_value = item.get("managedSurfaces")
        if not isinstance(surfaces_value, list) or not surfaces_value:
            raise MeridianError(f"{label}.managedSurfaces must be a non-empty list")
        surfaces = tuple(
            _parse_catalog_surface(surface, f"{label}.managedSurfaces[{index}]")
            for index, surface in enumerate(surfaces_value)
        )
        surface_paths = [surface.path for surface in surfaces]
        if len(set(surface_paths)) != len(surface_paths):
            raise MeridianError(f"{label}.managedSurfaces contains duplicate paths")
        for surface in surfaces:
            if not set(surface.forms) <= set(forms):
                raise MeridianError(
                    f"{label} surface {surface.path} uses a form absent from installationForms"
                )
        host_profiles = _required_object(item.get("hostProfiles"), f"{label}.hostProfiles")
        parsed_hosts = tuple(
            (
                host_id,
                _required_string(
                    _required_object(host, f"{label}.hostProfiles.{host_id}").get("evidenceKind"),
                    f"{label}.hostProfiles.{host_id}.evidenceKind",
                ),
            )
            for host_id, host in sorted(host_profiles.items())
        )
        requirements = _required_object(
            item.get("evidenceRequirements"), f"{label}.evidenceRequirements"
        )
        required_dimensions = {"installation", "hostActivation", "verification"}
        if set(requirements) != required_dimensions:
            raise MeridianError(
                f"{label}.evidenceRequirements must declare installation, hostActivation, and verification"
            )
        evidence_requirements = tuple(
            (
                dimension,
                _required_string_list(
                    requirements[dimension],
                    f"{label}.evidenceRequirements.{dimension}",
                ),
            )
            for dimension in sorted(required_dimensions)
        )
        dependencies_value = item.get("dependencies")
        if not isinstance(dependencies_value, list):
            raise MeridianError(f"{label}.dependencies must be a list")
        dependencies = tuple(
            (
                _required_string(
                    _required_object(dependency, f"{label}.dependencies[{index}]").get("id"),
                    f"{label}.dependencies[{index}].id",
                ),
                _required_positive_integer(
                    _required_object(dependency, f"{label}.dependencies[{index}]").get("version"),
                    f"{label}.dependencies[{index}].version",
                ),
            )
            for index, dependency in enumerate(dependencies_value)
        )
        capabilities.append(
            CatalogCapability(
                capability_id=capability_id,
                version=_required_positive_integer(item.get("version"), f"{label}.version"),
                workflow_modes=workflow_modes,
                self_hosting_eligible=eligible,
                host_profiles=parsed_hosts,
                installation_forms=forms,
                managed_surfaces=surfaces,
                evidence_requirements=evidence_requirements,
                dependencies=dependencies,
            )
        )
    catalog = CapabilityCatalog(catalog_version, tuple(capabilities), ())
    for capability in catalog.capabilities:
        for dependency_id, dependency_version in capability.dependencies:
            dependency = catalog.capability(dependency_id)
            if dependency is None or dependency.version != dependency_version:
                raise MeridianError(
                    f"capability {capability.capability_id} has an unresolved dependency "
                    f"{dependency_id} v{dependency_version}"
                )
    profiles: list[CatalogProfile] = []
    for profile_id, raw_profile in sorted(raw_profiles.items()):
        if not SAFE_PATH_COMPONENT.fullmatch(profile_id):
            raise MeridianError(f"invalid profile ID: {profile_id!r}")
        label = f"profiles.{profile_id}"
        profile = _required_object(raw_profile, label)
        raw_required = _required_object(profile.get("capabilities"), f"{label}.capabilities")
        required = tuple(
            (capability_id, _required_positive_integer(version, f"{label}.capabilities.{capability_id}"))
            for capability_id, version in sorted(raw_required.items())
        )
        for capability_id, version in required:
            capability = catalog.capability(capability_id)
            if capability is None or capability.version != version:
                raise MeridianError(
                    f"{label} requires unknown capability version {capability_id} v{version}"
                )
            for dependency_id, dependency_version in capability.dependencies:
                if dict(required).get(dependency_id) != dependency_version:
                    raise MeridianError(
                        f"{label} omits dependency {dependency_id} v{dependency_version} "
                        f"required by {capability_id}"
                    )
        profile_modes = (
            _required_string_list(profile["workflowModes"], f"{label}.workflowModes", non_empty=True)
            if "workflowModes" in profile
            else ()
        )
        unsupported_profile_modes = sorted(set(profile_modes) - set(WORKFLOW_MODES))
        if unsupported_profile_modes:
            raise MeridianError(
                f"{label}.workflowModes contains unsupported mode: {unsupported_profile_modes[0]}"
            )
        profiles.append(
            CatalogProfile(
                workflow_modes=profile_modes,
                profile_id=profile_id,
                version=_required_positive_integer(profile.get("version"), f"{label}.version"),
                capabilities=required,
                verification_probe=_repository_relative_path(
                    profile.get("verificationProbe"), f"{label}.verificationProbe"
                ),
                host_probes=tuple(
                    (
                        host_id,
                        _repository_relative_path(path, f"{label}.hostProbes.{host_id}"),
                    )
                    for host_id, path in sorted(
                        _required_object(profile.get("hostProbes"), f"{label}.hostProbes").items()
                    )
                ),
            )
        )
        declared_hosts = {
            host_id
            for capability_id, _version in required
            for host_id, _kind in catalog.capability(capability_id).host_profiles
        }
        if set(dict(profiles[-1].host_probes)) != declared_hosts:
            raise MeridianError(
                f"{label}.hostProbes must declare exactly: {', '.join(sorted(declared_hosts))}"
            )
    return CapabilityCatalog(catalog_version, catalog.capabilities, tuple(profiles))


def load_capability_catalog(framework_root: Path) -> CapabilityCatalog:
    path = framework_root / CAPABILITY_CATALOG_PATH
    if not path.is_file():
        raise MeridianError(f"capability catalog is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MeridianError(f"invalid capability catalog: {path}") from error
    return parse_capability_catalog(value)


def _parse_evidence_snapshot(
    value: object,
    label: str,
    allowed_states: tuple[str, ...],
    positive_states: tuple[str, ...],
    allowed_not_applicable_rationales: tuple[str, ...],
    *,
    verification: bool = False,
) -> EvidenceSnapshot:
    data = _required_object(value, label)
    state = _required_string(data.get("state"), f"{label}.state")
    if state not in allowed_states:
        raise MeridianError(f"{label}.state is unsupported: {state}")
    evidence = _required_string_list(data.get("evidence"), f"{label}.evidence")
    rationale_value = data.get("notApplicableRationale")
    if rationale_value is not None and not isinstance(rationale_value, str):
        raise MeridianError(f"{label}.notApplicableRationale must be null or a string")
    rationale = rationale_value.strip() if isinstance(rationale_value, str) else None
    if state in positive_states and not evidence:
        raise MeridianError(f"{label} state {state} requires evidence")
    if state == "NOT_APPLICABLE":
        if not rationale or rationale not in allowed_not_applicable_rationales:
            expected = ", ".join(allowed_not_applicable_rationales) or "no catalog exclusion applies"
            raise MeridianError(
                f"{label} NOT_APPLICABLE requires a catalog-backed rationale ({expected})"
            )
    elif rationale:
        raise MeridianError(f"{label}.notApplicableRationale is only valid for NOT_APPLICABLE")
    verified_at = data.get("verifiedAt") if verification else None
    verifier_version = data.get("verifierVersion") if verification else None
    if verification:
        for field, field_value in (("verifiedAt", verified_at), ("verifierVersion", verifier_version)):
            if field_value is not None and (not isinstance(field_value, str) or not field_value.strip()):
                raise MeridianError(f"{label}.{field} must be null or a non-empty string")
    return EvidenceSnapshot(
        state=state,
        evidence=evidence,
        not_applicable_rationale=rationale,
        verified_at=verified_at if isinstance(verified_at, str) else None,
        verifier_version=verifier_version if isinstance(verifier_version, str) else None,
    )


def parse_capability_profiles(
    manifest: dict[str, object],
    catalog: CapabilityCatalog,
    surface_gaps: list[tuple[str, str, tuple[str, ...]]] | None = None,
) -> tuple[CapabilityProfileDeclaration, ...]:
    """Parse declared profiles against `catalog`.

    When `surface_gaps` is given, a declared surface that is a strict subset of
    the catalog surface is recorded there as `(profile, capability, missing
    paths)` instead of failing: `meridian upgrade` completes it. Every other
    mismatch still fails.
    """
    raw_profiles = manifest.get("capabilityProfiles", {})
    profiles = _required_object(raw_profiles, "manifest capabilityProfiles")
    workflow_mode = manifest_workflow_mode(manifest)
    parsed_profiles: list[CapabilityProfileDeclaration] = []
    for profile_id, raw_profile in sorted(profiles.items()):
        label = f"capabilityProfiles.{profile_id}"
        catalog_profile = catalog.profile(profile_id)
        if catalog_profile is None:
            raise MeridianError(f"{label} is absent from capability catalog v{catalog.catalog_version}")
        profile = _required_object(raw_profile, label)
        profile_version = _required_positive_integer(
            profile.get("profileVersion"), f"{label}.profileVersion"
        )
        if profile_version != catalog_profile.version:
            raise MeridianError(
                f"{label}.profileVersion must be {catalog_profile.version}, got {profile_version}"
            )
        raw_capabilities = _required_object(profile.get("capabilities"), f"{label}.capabilities")
        required = dict(catalog_profile.capabilities)
        if set(raw_capabilities) != set(required):
            missing = sorted(set(required) - set(raw_capabilities))
            extra = sorted(set(raw_capabilities) - set(required))
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extra:
                detail.append("unexpected " + ", ".join(extra))
            raise MeridianError(f"{label}.capabilities is incomplete: {'; '.join(detail)}")
        declarations: list[CapabilityDeclaration] = []
        for capability_id, raw_declaration in sorted(raw_capabilities.items()):
            capability_label = f"{label}.capabilities.{capability_id}"
            capability = catalog.capability(capability_id)
            if capability is None:
                raise MeridianError(f"{capability_label} is absent from the capability catalog")
            declaration = _required_object(raw_declaration, capability_label)
            required_version = _required_positive_integer(
                declaration.get("requiredVersion"), f"{capability_label}.requiredVersion"
            )
            if required_version != required[capability_id] or required_version != capability.version:
                raise MeridianError(
                    f"{capability_label}.requiredVersion must be {required[capability_id]}"
                )
            raw_surfaces = declaration.get("managedSurface")
            if not isinstance(raw_surfaces, list) or not raw_surfaces:
                raise MeridianError(f"{capability_label}.managedSurface must be a non-empty list")
            surfaces = tuple(
                DeclaredSurface(
                    path=_repository_relative_path(
                        _required_object(surface, f"{capability_label}.managedSurface[{index}]").get("path"),
                        f"{capability_label}.managedSurface[{index}].path",
                    ),
                    form=_required_string(
                        _required_object(surface, f"{capability_label}.managedSurface[{index}]").get("form"),
                        f"{capability_label}.managedSurface[{index}].form",
                    ),
                )
                for index, surface in enumerate(raw_surfaces)
            )
            if len({surface.path for surface in surfaces}) != len(surfaces):
                raise MeridianError(f"{capability_label}.managedSurface contains duplicate paths")
            catalog_surfaces = {surface.path: surface for surface in capability.managed_surfaces}
            declared_paths = {surface.path for surface in surfaces}
            if surface_gaps is not None and declared_paths < set(catalog_surfaces):
                surface_gaps.append(
                    (
                        profile_id,
                        capability_id,
                        tuple(path for path in catalog_surfaces if path not in declared_paths),
                    )
                )
            elif declared_paths != set(catalog_surfaces):
                raise MeridianError(
                    f"{capability_label}.managedSurface must completely match the catalog surface"
                )
            for surface in surfaces:
                if surface.form not in catalog_surfaces[surface.path].forms:
                    raise MeridianError(
                        f"{capability_label}.managedSurface form {surface.form} is not allowed for {surface.path}"
                    )
            exclusions: list[str] = []
            if workflow_mode not in capability.workflow_modes:
                exclusions.append("workflow-mode-excluded")
            if profile_id == "meridian-self-hosting" and not capability.self_hosting_eligible:
                exclusions.append("self-hosting-ineligible")
            installation = _parse_evidence_snapshot(
                declaration.get("installation"),
                f"{capability_label}.installation",
                INSTALLATION_STATES,
                ("INSTALLED",),
                tuple(exclusions),
            )
            raw_hosts = _required_object(
                declaration.get("hostActivation"), f"{capability_label}.hostActivation"
            )
            host_activation: list[tuple[str, EvidenceSnapshot]] = []
            supported_hosts = dict(capability.host_profiles)
            missing_hosts = sorted(set(supported_hosts) - set(raw_hosts))
            if missing_hosts:
                raise MeridianError(
                    f"{capability_label}.hostActivation is missing supported host profile: "
                    f"{missing_hosts[0]}"
                )
            for host_id, raw_snapshot in sorted(raw_hosts.items()):
                host_exclusions = list(exclusions)
                if host_id not in supported_hosts:
                    host_exclusions.append("host-profile-unsupported")
                host_activation.append(
                    (
                        host_id,
                        _parse_evidence_snapshot(
                            raw_snapshot,
                            f"{capability_label}.hostActivation.{host_id}",
                            HOST_ACTIVATION_STATES,
                            ("ENFORCED", "ADVISORY"),
                            tuple(host_exclusions),
                        ),
                    )
                )
            verification_snapshot = _parse_evidence_snapshot(
                declaration.get("verification"),
                f"{capability_label}.verification",
                VERIFICATION_STATES,
                ("PASS", "ADVISORY"),
                tuple(exclusions),
                verification=True,
            )
            declarations.append(
                CapabilityDeclaration(
                    capability_id=capability_id,
                    required_version=required_version,
                    managed_surface=surfaces,
                    installation=installation,
                    host_activation=tuple(host_activation),
                    verification=verification_snapshot,
                )
            )
        parsed_profiles.append(
            CapabilityProfileDeclaration(profile_id, profile_version, tuple(declarations))
        )
    return tuple(parsed_profiles)


def load_marker_catalog(framework_root: Path) -> dict[str, dict[str, object]]:
    """Read current marker requirements independently of migration history.

    adoptionRecord preserves the historical adoption label while those flows
    still exist. Retired is historical: a reintroduced marker can be required.
    """
    path = framework_root / "capabilities/markers-v1.json"
    try:
        data = _required_object(json.loads(path.read_text(encoding="utf-8")), "marker catalog")
    except (OSError, ValueError) as error:
        raise MeridianError(f"cannot read marker catalog: {path}") from error
    if data.get("catalogVersion") != 1:
        raise MeridianError("unsupported marker catalog version")
    entries = _required_object(data.get("capabilities"), "marker capabilities")
    for capability, value in entries.items():
        label = f"marker capabilities.{capability}"
        item = _required_object(value, label)
        _required_positive_integer(item.get("requiredVersion"), f"{label}.requiredVersion")
        for field in ("required", "retired"):
            if type(item.get(field)) is not bool:
                raise MeridianError(f"{label}.{field} must be a boolean")
        if item["required"]:
            _required_string(item.get("adoptionRecord"), f"{label}.adoptionRecord")
    return entries


def marker_requirements(framework_root: Path) -> dict[str, tuple[int, str]]:
    """Return current required versions and legacy adoption labels."""
    return {
        capability: (item["requiredVersion"], item["adoptionRecord"])
        for capability, item in load_marker_catalog(framework_root).items()
        if item["required"]
    }
