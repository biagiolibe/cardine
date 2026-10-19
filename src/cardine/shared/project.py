"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import MeridianError
from cardine.shared.git import primary_project_root
from pathlib import Path
import json


_LEGACY_LOCATION_WARNING_PROJECTS: set[Path] = set()


def _safe_project_path(value: object, key: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise MeridianError(f"project declaration key {key!r} must be a safe project-relative path")
    return Path(value)


def parse_project_declaration(declaration: object) -> dict[str, object]:
    """Validate the closed, consumer-owned project declaration v1."""
    if not isinstance(declaration, dict):
        raise MeridianError("project declaration must be a JSON object")
    allowed = {"version", "project", "locations", "validationScoping", "ci"}
    unknown = sorted(set(declaration) - allowed)
    if unknown:
        raise MeridianError(f"project declaration unknown key: {unknown[0]}")
    if type(declaration.get("version")) is not int or declaration["version"] != 1:
        raise MeridianError("project declaration key 'version' must be 1")
    project = declaration.get("project")
    if project is not None:
        if not isinstance(project, dict) or set(project) != {"name", "slug"} or not all(
            isinstance(project.get(key), str) and project[key] for key in ("name", "slug")
        ):
            raise MeridianError("project declaration key 'project' must contain non-empty name and slug")
    locations = declaration.get("locations")
    if locations is not None:
        if not isinstance(locations, dict):
            raise MeridianError("project declaration key 'locations' must be an object")
        allowed_locations = {"queue", "taskRoots", "reviewRoot", "handoffRoot", "adrLog", "plan"}
        unknown_locations = sorted(set(locations) - allowed_locations)
        if unknown_locations:
            raise MeridianError(f"project declaration key 'locations.{unknown_locations[0]}' is unknown")
        for key in ("queue", "reviewRoot", "handoffRoot", "adrLog", "plan"):
            if key in locations:
                _safe_project_path(locations[key], f"locations.{key}")
        if "taskRoots" in locations:
            roots = locations["taskRoots"]
            if not isinstance(roots, list) or not roots:
                raise MeridianError("project declaration key 'locations.taskRoots' must be a non-empty array")
            for index, root in enumerate(roots):
                _safe_project_path(root, f"locations.taskRoots[{index}]")
    scoping = declaration.get("validationScoping")
    if scoping is not None:
        if not isinstance(scoping, list):
            raise MeridianError("project declaration key 'validationScoping' must be an array")
        for index, item in enumerate(scoping):
            if not isinstance(item, dict) or set(item) != {"paths", "commands"}:
                raise MeridianError(f"project declaration key 'validationScoping[{index}]' must contain paths and commands")
            if not all(isinstance(value, list) and value and all(isinstance(entry, str) and entry for entry in value)
                       for value in (item["paths"], item["commands"])):
                raise MeridianError(f"project declaration key 'validationScoping[{index}]' has invalid paths or commands")
    ci = declaration.get("ci")
    if ci is not None and ci != "none":
        if not isinstance(ci, dict) or set(ci) != {"provider", "requiredChecks"} or not isinstance(ci["provider"], str) or not ci["provider"] or not isinstance(ci["requiredChecks"], list) or not all(isinstance(item, str) and item for item in ci["requiredChecks"]):
            raise MeridianError("project declaration key 'ci' must be 'none' or contain provider and requiredChecks")
    return declaration


def read_project_declaration(project_root: Path) -> dict[str, object] | None:
    path = primary_project_root(project_root) / names().project_declaration_path
    if not path.exists():
        return None
    if not path.is_file():
        raise MeridianError(f"invalid project declaration: {path}")
    try:
        return parse_project_declaration(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MeridianError(f"invalid project declaration: {path}") from error
