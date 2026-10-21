from __future__ import annotations

from cardine.shared.constants import AUDIT_STATES
from cardine.shared.models import AuditResult
from cardine.shared.constants import CAPABILITY_DECLARATION_REQUIRED_PROTOCOL
from cardine.shared.constants import CAPABILITY_MARKER
from cardine.shared.constants import MARKER_BEGIN, MARKER_END
from cardine.shared.constants import CONTEXT_SIZE_ROLES
from cardine.shared.models import CapabilityDeclaration
from cardine.shared.models import CatalogProfile
from cardine.shared.models import EvidenceSnapshot
from cardine.shared.errors import CardineError
from cardine.shared.constants import PROJECT_EDITABLE_MANAGED_PATHS
from cardine.shared.constants import PROTOCOL_VERSION
from pathlib import Path
from cardine.shared.constants import STRICT_DIGEST_PROFILES
from cardine.shared.validation import _repository_relative_path
from cardine.shared.validation import _required_object
from cardine.shared.validation import _required_string
from cardine.shared.validation import _required_string_list
from cardine.templates.marker_audit import audit_capability_markers
from cardine.templates.marker_audit import audit_capability_moves
from cardine.templates.marker_audit import audit_duplicate_headings
from cardine.templates.router import audit_entry_router
from cardine.tasks.audit import audit_task_state_projections
from cardine.integration.evidence import candidate_validation_declaration
from cardine.templates.protocol import check_protocol_compatibility
from cardine.shared.context import context_size_report
from cardine.templates.mode import detect_mode
import json
from cardine.templates.catalog import load_capability_catalog
from cardine.templates.manifest import load_manifest
from cardine.templates.catalog import manifest_workflow_mode
from cardine.templates.catalog import parse_capability_profiles
import re
from cardine.shared.project import read_project_declaration
from cardine.release.version import read_version
from cardine.shared.hashing import sha256
from cardine.release.version import version_key


def _audit_evidence_reference(
    project_root: Path, reference: str, surface_digests: set[str]
) -> str | None:
    """Return a diagnostic when a persisted evidence reference is not current."""
    if reference.startswith("sha256:"):
        digest = reference.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return f"invalid digest evidence {reference!r}"
        if digest not in surface_digests:
            return f"stale digest evidence {reference}"
        return None
    if reference.startswith("path:"):
        raw_path = reference.removeprefix("path:")
        try:
            relative_path = _repository_relative_path(raw_path, "audit evidence path")
        except CardineError as error:
            return str(error)
        if not (project_root / relative_path).is_file():
            return f"missing evidence artifact {relative_path}"
        return None
    return f"unresolvable evidence reference {reference!r}; expected path:<path> or sha256:<digest>"


def _audit_snapshot_evidence(
    project_root: Path, snapshot: EvidenceSnapshot, surface_digests: set[str]
) -> list[str]:
    return [
        diagnostic
        for reference in snapshot.evidence
        if (diagnostic := _audit_evidence_reference(project_root, reference, surface_digests))
        is not None
    ]


def _digest_exempt(relative: str, path: Path) -> bool:
    """Whether a consumer profile verifies this managed copy without its digest."""
    return relative in PROJECT_EDITABLE_MANAGED_PATHS or (
        CAPABILITY_MARKER.search(path.read_text(encoding="utf-8")) is not None
    )


def installation_surface_diagnostics(
    project_root: Path,
    declaration: CapabilityDeclaration,
    managed_files: dict[str, object],
    *,
    marker_files_exempt: bool = False,
) -> tuple[list[str], list[str]]:
    """Compare declared installation surfaces without resolving host probes.

    Repository validation and the profile doctor share this comparison so a
    managed-copy edit receives the same verdict before either command examines
    host-specific evidence.
    """
    failures: list[str] = []
    surface_digests: set[str] = set()
    identities: list[str] = []
    for surface in declaration.managed_surface:
        identities.append(f"{surface.form}:{surface.path}")
        path = project_root / surface.path
        if surface.form == "declaration-only":
            continue
        if not path.is_file():
            failures.append(f"missing {surface.form} surface {surface.path}")
            continue
        if (
            marker_files_exempt
            and surface.form == "managed-copy"
            and _digest_exempt(surface.path, path)
        ):
            # Verified by the marker-integrity rows, or configured by the project
            # by design; neither is drift.
            continue
        digest = sha256(path)
        surface_digests.add(digest)
        if f"sha256:{digest}" not in declaration.installation.evidence:
            failures.append(f"{surface.form} surface {surface.path} lacks matching digest evidence")
        if surface.form == "managed-copy":
            expected_digest = managed_files.get(surface.path)
            if expected_digest is None:
                failures.append(f"managed-copy surface {surface.path} has no managedFiles digest")
            elif expected_digest != digest:
                failures.append(
                    f"drifted managed-copy surface {surface.path}: expected {expected_digest}, got {digest}"
                )
    failures.extend(_audit_snapshot_evidence(project_root, declaration.installation, surface_digests))
    return identities, failures


def _audit_probe_evidence(project_root: Path, snapshot: EvidenceSnapshot) -> list[str]:
    """Require runtime/behavior claims to name concrete probe artifacts."""
    diagnostics: list[str] = []
    for reference in snapshot.evidence:
        if not reference.startswith("probe:"):
            diagnostics.append(
                f"invalid positive evidence {reference!r}; expected probe:<path>"
            )
            continue
        raw_path = reference.removeprefix("probe:")
        try:
            relative_path = _repository_relative_path(raw_path, "audit probe path")
        except CardineError as error:
            diagnostics.append(str(error))
            continue
        if not (project_root / relative_path).is_file():
            diagnostics.append(f"missing probe artifact {relative_path}")
    return diagnostics


def managed_copy_drift(
    project_root: Path,
    managed_files: dict[str, object],
    *,
    skip_paths: tuple[str, ...] | set[str] = (),
    skip_marker_files: bool = False,
) -> list[tuple[str, str]]:
    """(path, diagnostic) for each recorded managed copy that is missing or whose
    digest differs from `managedFiles`. The repository check and the project audit share
    this comparison. `skip_marker_files` leaves out files carrying capability
    markers, which the marker-integrity audit verifies region by region."""
    skipped = set(skip_paths)
    diagnostics: list[tuple[str, str]] = []
    for relative, expected in sorted(managed_files.items()):
        if relative in skipped:
            continue
        path = project_root / relative
        if not path.is_file():
            diagnostics.append((relative, f"missing managed-copy surface {relative}"))
            continue
        if skip_marker_files and CAPABILITY_MARKER.search(path.read_text(encoding="utf-8")):
            continue
        current = sha256(path)
        if expected != current:
            diagnostics.append(
                (relative, f"drifted managed-copy surface {relative}: expected {expected}, got {current}")
            )
    return diagnostics


def declared_managed_copy_paths(
    manifest: dict[str, object], framework_root: Path
) -> set[str]:
    """Return managed-copy surfaces a capability profile audits independently."""
    if int(manifest.get("protocolVersion", 0)) < PROTOCOL_VERSION:
        return set()
    return {
        surface.path
        for declared in parse_capability_profiles(
            manifest, load_capability_catalog(framework_root), []
        )
        for declaration in declared.capabilities
        for surface in declaration.managed_surface
        if surface.form == "managed-copy"
    }


def is_markerless_managed_copy_digest_audited(
    project_root: Path, relative: str, declared_paths: set[str]
) -> bool:
    """Whether the managed-copy digest audit checks this local file."""
    path = project_root / relative
    return (
        relative not in PROJECT_EDITABLE_MANAGED_PATHS
        and relative not in declared_paths
        and path.is_file()
        and CAPABILITY_MARKER.search(path.read_text(encoding="utf-8")) is None
    )


def audit_managed_copy_digests(
    project_root: Path, managed_files: dict[str, object], declared_paths: set[str]
) -> list[AuditResult]:
    """One row per markerless managed copy: PASS when its digest is the recorded
    one, FAIL when it drifted. Files that carry markers, project-owned files, and
    copies a declared profile already verifies are not repeated here."""
    candidates = {
        relative: expected
        for relative, expected in managed_files.items()
        if is_markerless_managed_copy_digest_audited(project_root, relative, declared_paths)
    }
    drifted = {
        relative
        for relative, _diagnostic in managed_copy_drift(
            project_root, candidates, skip_paths=declared_paths, skip_marker_files=True
        )
    }
    results: list[AuditResult] = []
    for relative in sorted(candidates):
        path = project_root / relative
        if relative in drifted:
            results.append(
                AuditResult(
                    "FAIL",
                    "managed-copy-digest",
                    f"{relative}: differs from the digest `cardine upgrade` recorded; restore the released "
                    "text and put project-specific content in the project's own files",
                )
            )
        else:
            results.append(
                AuditResult("PASS", "managed-copy-digest", f"{relative}: matches the recorded digest")
            )
    return results


def audit_declared_capabilities(
    project_root: Path, framework_root: Path, requested_mode: str
) -> tuple[list[AuditResult], str]:
    """Audit effective declarations without projecting migration provenance."""
    try:
        manifest = load_manifest(project_root, framework_root)
    except CardineError as error:
        # Preserve the CLI's protocol-compatibility diagnostic: callers must
        # update the framework before this version can interpret the manifest.
        if "newer than this Cardine CLI supports" in str(error):
            raise
        return [AuditResult("FAIL", "declaration/manifest", str(error))], requested_mode

    workflow_mode = manifest_workflow_mode(manifest)
    if requested_mode != workflow_mode:
        return [
            AuditResult(
                "FAIL",
                "declaration/workflow-mode",
                f"requested {requested_mode}, but the locked manifest declares {workflow_mode}",
            )
        ], workflow_mode

    protocol_version = check_protocol_compatibility(manifest)
    if "capabilityProfiles" not in manifest or not manifest.get("capabilityProfiles"):
        status = (
            "FAIL"
            if protocol_version >= CAPABILITY_DECLARATION_REQUIRED_PROTOCOL
            else "UNVERIFIED"
        )
        rationale = (
            f"protocol v{protocol_version} requires explicit capabilityProfiles"
            if status == "FAIL"
            else f"legacy protocol v{protocol_version} manifest has no capabilityProfiles; "
            "migration history is provenance only"
        )
        return [AuditResult(status, "declaration/legacy-compatibility", rationale)], workflow_mode

    catalog = load_capability_catalog(framework_root)
    try:
        profiles = parse_capability_profiles(manifest, catalog)
    except CardineError as error:
        return [AuditResult("FAIL", "declaration/capabilityProfiles", str(error))], workflow_mode

    managed_files = manifest.get("managedFiles", {})
    assert isinstance(managed_files, dict)
    framework_version = read_version(framework_root)
    results: list[AuditResult] = []
    for profile in profiles:
        for declaration in profile.capabilities:
            capability = catalog.capability(declaration.capability_id)
            assert capability is not None
            prefix = f"{profile.profile_id}/{declaration.capability_id}"
            exclusions: list[str] = []
            if profile.profile_id == "cardine-self-hosting" and not capability.self_hosting_eligible:
                exclusions.append("self-hosting-ineligible")
            if exclusions:
                rationale = ", ".join(exclusions)
                results.append(
                    AuditResult(
                        "NOT_APPLICABLE",
                        f"{prefix}/installation",
                        f"catalog exclusion: {rationale}",
                    )
                )
                for host_id, _snapshot in declaration.host_activation:
                    host_rationale = (
                        "host-profile-unsupported"
                        if host_id not in dict(capability.host_profiles)
                        else rationale
                    )
                    results.append(
                        AuditResult(
                            "NOT_APPLICABLE",
                            f"{prefix}/host/{host_id}",
                            f"catalog exclusion: {host_rationale}",
                        )
                    )
                results.append(
                    AuditResult(
                        "NOT_APPLICABLE",
                        f"{prefix}/verification",
                        f"catalog exclusion: {rationale}",
                    )
                )
                continue

            surface_identities, surface_failures = installation_surface_diagnostics(
                project_root,
                declaration,
                managed_files,
                marker_files_exempt=profile.profile_id not in STRICT_DIGEST_PROFILES,
            )
            if declaration.installation.state != "INSTALLED":
                surface_failures.append(
                    f"declared installation state is {declaration.installation.state}"
                )
            installation_status = "FAIL" if surface_failures else "PASS"
            results.append(
                AuditResult(
                    installation_status,
                    f"{prefix}/installation",
                    "verified surfaces: "
                    + ", ".join(surface_identities)
                    + "; "
                    + "; ".join(surface_failures)
                    if surface_failures
                    else "verified surfaces: " + ", ".join(surface_identities),
                )
            )

            supported_hosts = dict(capability.host_profiles)
            for host_id, snapshot in declaration.host_activation:
                identity = f"{prefix}/host/{host_id}"
                if host_id not in supported_hosts:
                    results.append(
                        AuditResult(
                            "NOT_APPLICABLE",
                            identity,
                            "catalog exclusion: host-profile-unsupported",
                        )
                    )
                    continue
                evidence_failures = _audit_probe_evidence(project_root, snapshot)
                if snapshot.state == "NOT_APPLICABLE":
                    results.append(
                        AuditResult(
                            "FAIL",
                            identity,
                            "host is catalog-supported, so NOT_APPLICABLE is contradictory",
                        )
                    )
                elif snapshot.state in {"ENFORCED", "ADVISORY"}:
                    failures = list(evidence_failures)
                    if installation_status != "PASS":
                        failures.append("positive activation claim depends on failed installation")
                    results.append(
                        AuditResult(
                            "FAIL" if failures else ("PASS" if snapshot.state == "ENFORCED" else "ADVISORY"),
                            identity,
                            "; ".join(failures)
                            if failures
                            else f"{snapshot.state.lower()} with {supported_hosts[host_id]} evidence",
                        )
                    )
                elif snapshot.state == "UNSUPPORTED":
                    results.append(
                        AuditResult(
                            "ADVISORY",
                            identity,
                            "declared UNSUPPORTED for a catalog-supported host",
                        )
                    )
                else:
                    results.append(
                        AuditResult(
                            "UNVERIFIED",
                            identity,
                            "applicable host activation has no effective probe evidence",
                        )
                    )

            verification = declaration.verification
            verification_failures = _audit_probe_evidence(project_root, verification)
            if verification.state in {"PASS", "ADVISORY"}:
                if verification.verified_at is None:
                    verification_failures.append("positive verification has no verifiedAt value")
                if verification.verifier_version != framework_version:
                    verification_failures.append(
                        "stale verifierVersion "
                        f"{verification.verifier_version!r}; expected {framework_version!r}"
                    )
                if installation_status != "PASS":
                    verification_failures.append("positive verification depends on failed installation")
                verification_status = (
                    "FAIL" if verification_failures else verification.state
                )
                detail = (
                    "; ".join(verification_failures)
                    if verification_failures
                    else f"verified at {verification.verified_at} by Cardine {verification.verifier_version}"
                )
            elif verification.state == "NOT_APPLICABLE":
                verification_status = "FAIL"
                detail = "capability is catalog-applicable, so NOT_APPLICABLE is contradictory"
            elif verification.state == "FAIL":
                verification_status = "FAIL"
                detail = "persisted verification state is FAIL"
            else:
                verification_status = "UNVERIFIED"
                detail = "applicable capability lacks current verification evidence"
            results.append(
                AuditResult(verification_status, f"{prefix}/verification", detail)
            )
    return results, workflow_mode


def load_retired_text_registry(framework_root: Path) -> list[dict[str, object]]:
    """Read the versioned advisory registry; older framework fixtures lack it."""
    path = framework_root / "capabilities/retired-text-v1.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "retirements"}
            or type(data["version"]) is not int
            or data["version"] != 1
        ):
            raise ValueError("expected version 1 and retirements")
        entries = data["retirements"]
        if not isinstance(entries, list):
            raise ValueError("retirements must be an array")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "capability", "retiredIn", "phrases", "files", "remedy"
            }:
                raise ValueError("invalid retirement fields")
            for field, pattern in (
                ("capability", r"[a-z0-9]+(?:-[a-z0-9]+)*"),
                ("retiredIn", r"[0-9]+\.[0-9]+\.[0-9]+"),
            ):
                if not isinstance(entry[field], str) or not re.fullmatch(pattern, entry[field]):
                    raise ValueError(f"invalid {field}")
            if not isinstance(entry["remedy"], str) or not entry["remedy"].strip():
                raise ValueError("missing remedy")
            for field in ("phrases", "files"):
                values = entry[field]
                if (
                    not isinstance(values, list) or not values
                    or any(not isinstance(value, str) or not value for value in values)
                    or len(set(values)) != len(values)
                ):
                    raise ValueError(f"invalid {field}")
            for value in entry["files"]:
                path_value = Path(value)
                if (
                    not path_value.parts or path_value.is_absolute()
                    or ".." in path_value.parts or path_value.parts[0] == "tasks"
                    or "\\" in value
                ):
                    raise ValueError("retired text files must be safe project paths outside tasks")
        return entries
    except (OSError, ValueError) as error:
        raise CardineError(f"invalid retired-text registry: {error}") from error


def retired_text_advisories(
    project_root: Path, framework_root: Path, manifest: dict[str, object]
) -> list[AuditResult]:
    """Match literal phrases only in explicitly listed, project-owned text."""
    results = []
    installed = version_key(str(manifest["frameworkVersion"]))
    for entry in load_retired_text_registry(framework_root):
        if installed < version_key(entry["retiredIn"]):
            continue
        for relative_path in entry["files"]:
            path = project_root / relative_path
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            # Blank managed regions without changing line numbers. An unfinished
            # region remains managed through EOF; marker audit handles corruption.
            text = re.sub(
                rf"<!-- {MARKER_BEGIN}\b.*?(?:{re.escape(MARKER_END)}|\Z)",
                lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
                text, flags=re.DOTALL,
            )
            for line_number, line in enumerate(text.splitlines(), 1):
                for phrase in entry["phrases"]:
                    if phrase.casefold() in line.casefold():
                        results.append(AuditResult(
                            "ADVISORY", "retired-text",
                            f"{relative_path}:{line_number}: retired capability={entry['capability']}; "
                            f"phrase={phrase!r}; {entry['remedy']}",
                        ))
    return results


def run_audit(
    project_root: Path,
    framework_root: Path,
    mode: str,
    ci_profile: str | None = None,
) -> int:
    results, locked_mode = audit_declared_capabilities(project_root, framework_root, mode)
    try:
        results.extend(audit_task_state_projections(project_root, locked_mode))
    except (CardineError, OSError, UnicodeError) as error:
        results.append(AuditResult("FAIL", "task-state", str(error)))
    legacy_checks = (
        ("marker-integrity", audit_capability_markers),
        ("duplicate-heading", audit_duplicate_headings),
        ("capability-move", audit_capability_moves),
    )
    for check_name, check in legacy_checks:
        try:
            check_results = check(project_root, framework_root, locked_mode)
        except CardineError as error:
            results.append(AuditResult("FAIL", check_name, str(error)))
            continue
        for status, detail in check_results:
            normalized_status = "UNVERIFIED" if status == "SKIP" else status
            results.append(AuditResult(normalized_status, check_name, detail))
    for status, detail in audit_entry_router(project_root):
        results.append(AuditResult(status, "entry-router", detail))
    try:
        digest_manifest = load_manifest(project_root, framework_root)
        results.extend(retired_text_advisories(project_root, framework_root, digest_manifest))
        recorded_digests = digest_manifest.get("managedFiles", {})
        declared_copy_paths = declared_managed_copy_paths(digest_manifest, framework_root)
        if isinstance(recorded_digests, dict):
            results.extend(
                audit_managed_copy_digests(project_root, recorded_digests, declared_copy_paths)
            )
    except (CardineError, ValueError):
        # Projects without a readable manifest have no recorded digests to compare.
        pass
    try:
        detect_mode(project_root)
    except CardineError as error:
        # Fixture and legacy projects may have a valid manifest but no local
        # workflow-mode lock, so their router read set is not available.
        results.append(AuditResult("NOT_APPLICABLE", "context-size", str(error)))
    else:
        try:
            for role in CONTEXT_SIZE_ROLES[locked_mode]:
                report = context_size_report(project_root, role, workflow_mode=locked_mode)
                for path in report["exceeded"]:
                    results.append(AuditResult("FAIL", "context-size", f"{role}: {path} exceeds its configured ceiling"))
        except CardineError as error:
            results.append(AuditResult("FAIL", "context-size", str(error)))
    try:
        validation_state, _fragments = candidate_validation_declaration(project_root)
        if validation_state == "undeclared":
            results.append(AuditResult(
                "ADVISORY", "candidate-validation-commands",
                "undeclared; choose declared fragments or none before the first integration",
            ))
    except CardineError as error:
        results.append(AuditResult("FAIL", "candidate-validation-commands", str(error)))
    try:
        declaration = read_project_declaration(project_root)
        if declaration is not None and "project" not in declaration:
            results.append(AuditResult("ADVISORY", "project-declaration", "advisory-incomplete; missing project identity"))
    except CardineError as error:
        results.append(AuditResult("FAIL", "project-declaration", str(error)))

    results.sort(key=lambda result: (result.identity, result.detail))
    for result in results:
        print(f"{result.status:14} {result.identity} — {result.detail}")

    counts = {state: 0 for state in AUDIT_STATES}
    for result in results:
        counts[result.status] += 1
    if counts["FAIL"]:
        aggregate = "FAIL"
        exit_code = 2
    elif counts["ADVISORY"] or counts["UNVERIFIED"]:
        aggregate = "UNVERIFIED" if counts["UNVERIFIED"] else "ADVISORY"
        exit_code = int(bool(counts["UNVERIFIED"] or any(
            result.status == "ADVISORY" and result.identity != "retired-text"
            for result in results
        )))
    else:
        aggregate = "PASS"
        exit_code = 0
    summary = " ".join(f"{state}={counts[state]}" for state in AUDIT_STATES)
    print(f"SUMMARY worst={aggregate} {summary}")
    if ci_profile is not None:
        required = [
            result
            for result in results
            if result.status == "FAIL"
            or (
                result.identity.startswith(f"{ci_profile}/")
                and result.identity.endswith("/installation")
            )
        ]
        profile_installations = [
            result
            for result in required
            if result.identity.startswith(f"{ci_profile}/")
            and result.identity.endswith("/installation")
        ]
        required_failures = [result for result in required if result.status != "PASS"]
        if not profile_installations:
            required_failures.append(
                AuditResult(
                    "FAIL",
                    f"{ci_profile}/ci-gate",
                    "profile has no declared installation results",
                )
            )
        ci_status = "FAIL" if required_failures else "PASS"
        print(
            f"CI_GATE profile={ci_profile} worst={ci_status} "
            f"required={len(required)} failures={len(required_failures)}"
        )
        return 2 if required_failures else 0
    return exit_code


def _load_profile_probe(
    project_root: Path,
    relative_path: str,
    profile: CatalogProfile,
    expected_host: str,
) -> dict[str, object]:
    path = project_root / relative_path
    if not path.is_file():
        raise CardineError(f"required probe is missing: {relative_path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CardineError(f"required probe is invalid JSON: {relative_path}") from error
    data = _required_object(value, f"probe {relative_path}")
    if data.get("schemaVersion") != 1:
        raise CardineError(f"probe {relative_path} must use schemaVersion 1")
    if data.get("profileId") != profile.profile_id or data.get("profileVersion") != profile.version:
        raise CardineError(f"probe {relative_path} targets the wrong profile version")
    if data.get("hostProfile") != expected_host:
        raise CardineError(f"probe {relative_path} must target host profile {expected_host}")
    for field in ("host", "hostVersion", "invocationMode", "configurationLayer", "fallback"):
        _required_string(data.get(field), f"probe {relative_path}.{field}")
    state = _required_string(data.get("state"), f"probe {relative_path}.state")
    if state not in {"PASS", "ADVISORY", "UNSUPPORTED", "UNVERIFIED"}:
        raise CardineError(f"probe {relative_path}.state is unsupported: {state}")
    for field in ("observationTime", "evidenceArtifact"):
        field_value = data.get(field)
        if field_value is not None and (not isinstance(field_value, str) or not field_value.strip()):
            raise CardineError(f"probe {relative_path}.{field} must be null or a non-empty string")
    if state == "PASS" and (data.get("observationTime") is None or data.get("evidenceArtifact") is None):
        raise CardineError(f"probe {relative_path} PASS requires observationTime and evidenceArtifact")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise CardineError(f"probe {relative_path}.checks must be a non-empty list")
    covered: set[str] = set()
    for index, raw_check in enumerate(checks):
        check = _required_object(raw_check, f"probe {relative_path}.checks[{index}]")
        capability_id = _required_string(
            check.get("capability"), f"probe {relative_path}.checks[{index}].capability"
        )
        if capability_id not in dict(profile.capabilities):
            raise CardineError(f"probe {relative_path} names undeclared capability {capability_id}")
        _required_string(check.get("behavior"), f"probe {relative_path}.checks[{index}].behavior")
        dimensions = _required_string_list(
            check.get("dimensions"), f"probe {relative_path}.checks[{index}].dimensions", non_empty=True
        )
        if len(set(dimensions)) != len(dimensions):
            raise CardineError(f"probe {relative_path} has duplicate check dimensions")
        covered.add(capability_id)
    data["_coveredCapabilities"] = sorted(covered)
    return data


def profile_doctor(project_root: Path, framework_root: Path, profile_id: str) -> int:
    """Resolve a profile and all repository-owned evidence without mutation."""
    results: list[AuditResult] = []
    try:
        manifest = load_manifest(project_root, framework_root)
        catalog = load_capability_catalog(framework_root)
        profile = catalog.profile(profile_id)
        if profile is None:
            raise CardineError(f"capability profile is not present in the catalog: {profile_id}")
        declarations = {item.profile_id: item for item in parse_capability_profiles(manifest, catalog)}
        declaration = declarations.get(profile_id)
        if declaration is None:
            raise CardineError(f"manifest does not declare capability profile: {profile_id}")
        audit_results, _mode = audit_declared_capabilities(
            project_root, framework_root, manifest_workflow_mode(manifest)
        )
        for result in audit_results:
            if result.identity.startswith(f"{profile_id}/") and result.identity.endswith("/installation"):
                results.append(result)
        for capability in declaration.capabilities:
            references = list(capability.installation.evidence)
            references.extend(
                reference
                for _host, snapshot in capability.host_activation
                for reference in snapshot.evidence
            )
            references.extend(capability.verification.evidence)
            for reference in references:
                if reference.startswith(("path:", "probe:")):
                    raw_path = reference.split(":", 1)[1]
                    relative = _repository_relative_path(raw_path, "profile evidence path")
                    status = "PASS" if (project_root / relative).is_file() else "FAIL"
                    results.append(AuditResult(status, f"{profile_id}/evidence/{relative}", "resolved" if status == "PASS" else "missing"))
        ci_probe = _load_profile_probe(
            project_root, profile.verification_probe, profile, "host-neutral-ci"
        )
        missing_ci = sorted(set(dict(profile.capabilities)) - set(ci_probe["_coveredCapabilities"]))
        results.append(AuditResult(
            "FAIL" if missing_ci else "PASS",
            f"{profile_id}/probe/host-neutral-ci",
            "missing capability checks: " + ", ".join(missing_ci) if missing_ci else f"resolved {profile.verification_probe}",
        ))
        supported_by_host: dict[str, set[str]] = {}
        for capability_id, _version in profile.capabilities:
            capability = catalog.capability(capability_id)
            assert capability is not None
            for host_id, _kind in capability.host_profiles:
                supported_by_host.setdefault(host_id, set()).add(capability_id)
        for host_id, probe_path in profile.host_probes:
            probe = _load_profile_probe(project_root, probe_path, profile, host_id)
            missing = sorted(supported_by_host[host_id] - set(probe["_coveredCapabilities"]))
            results.append(AuditResult(
                "FAIL" if missing else "PASS",
                f"{profile_id}/probe/{host_id}",
                "missing capability checks: " + ", ".join(missing) if missing else f"resolved {probe_path}; host state={probe['state']}",
            ))
    except CardineError as error:
        results.append(AuditResult("FAIL", f"{profile_id}/doctor", str(error)))
    results.sort(key=lambda result: (result.identity, result.detail))
    for result in results:
        print(f"{result.status:14} {result.identity} — {result.detail}")
    failures = sum(result.status == "FAIL" for result in results)
    print(f"SUMMARY profile={profile_id} PASS={sum(result.status == 'PASS' for result in results)} FAIL={failures}")
    return 2 if failures else 0
