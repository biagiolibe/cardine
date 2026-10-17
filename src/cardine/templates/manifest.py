"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.constants import MANIFEST_PATH
from cardine.shared.constants import PROTOCOL_VERSION
from cardine.shared.errors import MeridianError
from cardine.shared.models import CapabilityCatalog
from cardine.shared.models import CapabilityProfileDeclaration
from cardine.shared.validation import _repository_relative_path
from cardine.shared.validation import _required_object
from cardine.shared.validation import _required_string_list
from cardine.templates.catalog import load_capability_catalog
from cardine.templates.catalog import manifest_workflow_mode
from cardine.templates.catalog import parse_capability_profiles
from pathlib import Path
import json
import re


def validate_manifest(
    manifest: dict[str, object],
    catalog: CapabilityCatalog | None = None,
    surface_gaps: list[tuple[str, str, tuple[str, ...]]] | None = None,
) -> tuple[CapabilityProfileDeclaration, ...]:
    manifest_workflow_mode(manifest)
    applied_migrations = manifest.get("appliedMigrations", [])
    _required_string_list(applied_migrations, "manifest appliedMigrations")
    managed_files = _required_object(manifest.get("managedFiles", {}), "manifest managedFiles")
    for path, digest in managed_files.items():
        _repository_relative_path(path, "manifest managedFiles path")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise MeridianError(f"manifest managedFiles.{path} must be a SHA-256 digest")
    if "capabilityProfiles" not in manifest:
        return ()
    if catalog is None:
        raise MeridianError("manifest capabilityProfiles require a capability catalog")
    return parse_capability_profiles(manifest, catalog, surface_gaps)


def load_manifest(
    project_root: Path,
    framework_root: Path | None = None,
    *,
    defer_surface_gaps: bool = False,
) -> dict[str, object]:
    manifest_path = project_root / MANIFEST_PATH
    if not manifest_path.is_file():
        raise MeridianError(
            "project is not locked; run `meridian lock --project <path> --mode <mode>` first"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MeridianError(f"invalid manifest: {manifest_path}") from error
    if not isinstance(manifest, dict):
        raise MeridianError(f"invalid manifest: {manifest_path} must contain a JSON object")
    catalog = load_capability_catalog(framework_root) if framework_root is not None else None
    validate_manifest(manifest, catalog, [] if defer_surface_gaps else None)
    return manifest


def canonical_manifest(manifest: dict[str, object]) -> dict[str, object]:
    """Return the current-protocol representation without changing effective state."""
    result = dict(manifest)
    result["protocolVersion"] = PROTOCOL_VERSION
    result["workflowMode"] = manifest_workflow_mode(manifest)
    result.pop("mode", None)
    return result


def write_manifest(
    project_root: Path,
    manifest: dict[str, object],
    framework_root: Path | None = None,
) -> None:
    manifest = canonical_manifest(manifest)
    catalog = load_capability_catalog(framework_root) if framework_root is not None else None
    validate_manifest(manifest, catalog)
    destination = project_root / MANIFEST_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
