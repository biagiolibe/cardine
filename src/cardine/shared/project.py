"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import CardineError
from cardine.shared.git import primary_project_root
from pathlib import Path
import json


_LEGACY_LOCATION_WARNING_PROJECTS: set[Path] = set()


def preset_task_defaults(preset: str) -> dict[str, object]:
    """Return fresh defaults; explicit false values remain valid overrides."""
    if preset not in ("lean", "governed"):
        raise CardineError("project declaration key 'preset' must be lean or governed")
    governed = preset == "governed"
    return {
        "review": "required" if governed else "not_required",
        "authorityRequired": governed,
        "expectedCodeSurfaceRequired": governed,
        "validationRetryLimit": 3,
        "landingMode": "direct",
        "ciBeforeLanding": False,
    }


def _validate_task_defaults(value: object) -> None:
    if not isinstance(value, dict):
        raise CardineError("project declaration key 'taskDefaults' must be an object")
    defaults = preset_task_defaults("lean")
    for key, option in value.items():
        if key not in defaults:
            raise CardineError(f"project declaration key 'taskDefaults.{key}' is unknown")
        if key == "review":
            valid = option in ("required", "not_required")
        elif key == "landingMode":
            valid = option == "direct"
        elif key == "validationRetryLimit":
            valid = type(option) is int and option >= 1
        else:
            valid = type(option) is bool
        if not valid:
            detail = "; only direct is supported in 1.0" if key == "landingMode" else ""
            raise CardineError(f"project declaration key 'taskDefaults.{key}' has an invalid value{detail}")


def _validate_validation(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"commands", "baseline", "candidate"}:
        raise CardineError("project declaration key 'validation' must contain commands, baseline and candidate")
    commands = value["commands"]
    if not isinstance(commands, dict) or not all(
        isinstance(key, str) and key.strip() and isinstance(command, str) and command.strip()
        for key, command in commands.items()
    ):
        raise CardineError("validation.commands must map nonempty IDs to nonempty literal commands")
    candidate = value["candidate"]
    if not isinstance(candidate, dict) or set(candidate) != {"REUSE", "BOUNDED", "FULL"}:
        raise CardineError("validation.candidate must declare REUSE, BOUNDED and FULL")
    for key, references in [("baseline", value["baseline"]), *candidate.items()]:
        if (not isinstance(references, list)
                or not all(isinstance(item, str) and item in commands for item in references)
                or len(references) != len(set(references))):
            raise CardineError(f"validation.{key} must contain unique known command IDs")


def resolve_project_configuration(project_root: Path) -> dict[str, object]:
    """Resolve project policy without inferring anything from workflow prose."""
    declaration = read_project_declaration(project_root)
    if declaration is None:
        raise CardineError("missing project configuration: .cardine/project.json")
    return {
        **declaration,
        "taskDefaults": {**preset_task_defaults(declaration["preset"]), **declaration.get("taskDefaults", {})},
        "taskIdentity": {"mode": "opaque", **declaration.get("taskIdentity", {})},
    }


def project_validation_commands(configuration: dict[str, object], outcome: str | None = None) -> tuple[str, ...]:
    """Compose the baseline and candidate commands, retaining declaration order."""
    validation = configuration.get("validation")
    if validation is None:
        raise CardineError("project configuration requires validation before task execution")
    _validate_validation(validation)
    references = list(validation["baseline"])
    if outcome is not None:
        if outcome not in ("REUSE", "BOUNDED", "FULL"):
            raise CardineError(f"unknown candidate validation outcome: {outcome}")
        references.extend(validation["candidate"][outcome])
    commands = [validation["commands"][key] for key in references]
    if outcome is not None:
        commands.append("git diff --check")
    return tuple(dict.fromkeys(commands))


def _safe_project_path(value: object, key: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise CardineError(f"project declaration key {key!r} must be a safe project-relative path")
    return Path(value)


def parse_project_declaration(declaration: object) -> dict[str, object]:
    """Validate the closed, consumer-owned project declaration v1."""
    if not isinstance(declaration, dict):
        raise CardineError("project declaration must be a JSON object")
    allowed = {"version", "preset", "taskDefaults", "taskIdentity", "validation", "project", "locations", "validationScoping", "ci"}
    unknown = sorted(set(declaration) - allowed)
    if unknown:
        raise CardineError(f"project declaration unknown key: {unknown[0]}")
    if type(declaration.get("version")) is not int or declaration["version"] != 1:
        raise CardineError("project declaration key 'version' must be 1")
    defaults = preset_task_defaults(declaration.get("preset"))
    if "taskDefaults" in declaration:
        _validate_task_defaults(declaration["taskDefaults"])
        defaults.update(declaration["taskDefaults"])
    if "taskIdentity" in declaration:
        identity = declaration["taskIdentity"]
        if (not isinstance(identity, dict) or set(identity) - {"mode"}
                or identity.get("mode", "opaque") not in ("opaque", "milestone")):
            raise CardineError("project declaration key 'taskIdentity.mode' must be opaque or milestone")
    if "validation" in declaration:
        _validate_validation(declaration["validation"])
    project = declaration.get("project")
    if project is not None:
        if not isinstance(project, dict) or set(project) != {"name", "slug"} or not all(
            isinstance(project.get(key), str) and project[key] for key in ("name", "slug")
        ):
            raise CardineError("project declaration key 'project' must contain non-empty name and slug")
    locations = declaration.get("locations")
    if locations is not None:
        if not isinstance(locations, dict):
            raise CardineError("project declaration key 'locations' must be an object")
        allowed_locations = {"queue", "taskRoots", "reviewRoot", "handoffRoot", "adrLog", "plan"}
        unknown_locations = sorted(set(locations) - allowed_locations)
        if unknown_locations:
            raise CardineError(f"project declaration key 'locations.{unknown_locations[0]}' is unknown")
        for key in ("queue", "reviewRoot", "handoffRoot", "adrLog", "plan"):
            if key in locations:
                _safe_project_path(locations[key], f"locations.{key}")
        if "taskRoots" in locations:
            roots = locations["taskRoots"]
            if not isinstance(roots, list) or not roots:
                raise CardineError("project declaration key 'locations.taskRoots' must be a non-empty array")
            for index, root in enumerate(roots):
                _safe_project_path(root, f"locations.taskRoots[{index}]")
    scoping = declaration.get("validationScoping")
    if scoping is not None:
        if not isinstance(scoping, list):
            raise CardineError("project declaration key 'validationScoping' must be an array")
        for index, item in enumerate(scoping):
            if not isinstance(item, dict) or set(item) != {"paths", "commands"}:
                raise CardineError(f"project declaration key 'validationScoping[{index}]' must contain paths and commands")
            if not all(isinstance(value, list) and value and all(isinstance(entry, str) and entry for entry in value)
                       for value in (item["paths"], item["commands"])):
                raise CardineError(f"project declaration key 'validationScoping[{index}]' has invalid paths or commands")
    ci = declaration.get("ci")
    if "ci" in declaration and ci != "none":
        if not isinstance(ci, dict) or set(ci) != {"provider", "requiredChecks"} or not isinstance(ci["provider"], str) or not ci["provider"] or not isinstance(ci["requiredChecks"], list) or not all(isinstance(item, str) and item for item in ci["requiredChecks"]):
            raise CardineError("project declaration key 'ci' must be 'none' or contain provider and requiredChecks")
    if defaults["ciBeforeLanding"] and (
        not isinstance(ci, dict) or ci["provider"] != "github" or not ci["requiredChecks"]
    ):
        raise CardineError("ciBeforeLanding requires supported provider github and nonempty requiredChecks")
    return declaration


def read_project_declaration(project_root: Path) -> dict[str, object] | None:
    path = primary_project_root(project_root) / names().project_declaration_path
    if not path.exists():
        return None
    if not path.is_file():
        raise CardineError(f"invalid project declaration: {path}")
    try:
        return parse_project_declaration(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CardineError(f"invalid project declaration: {path}") from error
