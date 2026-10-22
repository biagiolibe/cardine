"""Schema validation and complete-history state machines for tracked task state.

Consumers use read_task_state, addressing one task directly without directory scans.
This module has no dependency on the CLI; the CLI supplies its registered stop factory.
"""

from __future__ import annotations

from cardine.shared.layout import names

import json
import re
from datetime import datetime
from pathlib import Path


STATUSES = ("queued", "in_progress", "in_review", "done", "cancelled")
STATE_MACHINE = {
    "queued": ("in_progress", "cancelled"),
    "in_progress": ("in_review", "done", "cancelled"),
    "in_review": ("in_progress", "cancelled"),
    "done": (), "cancelled": (),
}
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas/task-state-v1.schema.json"


class TaskStateInvalid(ValueError):
    """An invalid field or transition, including its expected and found values."""


def _invalid(field, allowed, found):
    raise TaskStateInvalid(f"{field}: allowed {allowed}; found {found!r}")


def _validate_schema(value, schema, field="state"):
    """Validate the JSON Schema keywords used by the dependency-free v1 schema."""
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try:
                _validate_schema(value, choice, field)
                return
            except TaskStateInvalid:
                pass
        _invalid(field, schema["anyOf"], value)
    types = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool, "null": type(None)}
    kind = schema.get("type")
    if kind and type(value) is not types[kind]:
        _invalid(field, kind, value)
    if "enum" in schema and value not in schema["enum"]:
        _invalid(field, schema["enum"], value)
    if kind == "object":
        for name in schema.get("required", []):
            if name not in value:
                _invalid(f"{field}.{name}", "required field", "missing")
        properties = schema.get("properties", {})
        for name, item in value.items():
            if "propertyNames" in schema:
                _validate_schema(name, schema["propertyNames"], f"{field} key")
            if name not in properties:
                additional = schema.get("additionalProperties", False)
                if not isinstance(additional, dict):
                    _invalid(f"{field}.{name}", sorted(properties), item)
                _validate_schema(item, additional, f"{field}.{name}")
            else:
                _validate_schema(item, properties[name], f"{field}.{name}")
    elif kind == "array":
        if schema.get("uniqueItems") and any(item in value[:index] for index, item in enumerate(value)):
            _invalid(field, "unique items", value)
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{field}[{index}]")
    elif kind == "string":
        if len(value) < schema.get("minLength", 0):
            _invalid(field, f"length >= {schema['minLength']}", value)
        if len(value) > schema.get("maxLength", len(value)):
            _invalid(field, f"length <= {schema['maxLength']}", value)
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            _invalid(field, schema["pattern"], value)
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                _invalid(field, "ISO-8601 UTC timestamp", value)
    elif kind == "integer" and value < schema.get("minimum", value):
        _invalid(field, f">= {schema['minimum']}", value)


def machine(workflow=None, spike=False, review_required=True):
    """Presets and task classes share one machine; only review policy gates review."""
    return {status: tuple(target for target in targets
                          if target != "in_review" or review_required)
            for status, targets in STATE_MACHINE.items()}


def review_is_required(state):
    """Read frozen task policy; sparse pre-contract snapshots retain their default."""
    options = state.get("contract", {}).get("options", {})
    if "review" in options:
        return options["review"] == "required"
    return state.get("review", {}).get("required", True)


def dependency_satisfied(state):
    """Only landed results unblock dependents; an inconclusive spike never does."""
    task_class = state.get("contract", {}).get("class")
    if task_class is None:
        task_class = "spike" if "outcome" in state else "standard"
    return (state["status"] == "done"
            and (task_class != "spike" or state.get("outcome") == "ANSWERED"))


def validate_task_state(state, task_id, workflow, *, spike=False, review_required=None):
    """Validate history; review_required=None selects the snapshot's review policy."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _validate_schema(state, schema)
    if "contract" in state:
        # Cross-reference checks cannot be expressed by the local JSON Schema.
        from cardine.shared.project import parse_project_declaration
        from cardine.shared.errors import CardineError
        contract = state["contract"]
        try:
            parse_project_declaration({"version": 1, "preset": contract["preset"],
                                       "taskDefaults": contract["options"], "ci": contract["ci"],
                                       "validation": contract["validation"],
                                       "validationScoping": contract["validationScoping"]})
        except CardineError as error:
            raise TaskStateInvalid(f"contract: {error}") from error
    # Integration reads policy from the snapshot, without consulting prose.
    if review_required is None:
        review_required = review_is_required(state)
    if state["task_id"] != task_id:
        _invalid("task_id", [task_id], state["task_id"])
    if "contract" in state:
        review_required = review_is_required(state)
        spike = state["contract"]["class"] == "spike"
        if "review" in state and state["review"]["required"] != review_required:
            _invalid("review.required", [review_required], state["review"]["required"])
    if "outcome" in state and not spike:
        _invalid("outcome", "spike tasks only", state["outcome"])
    states = machine(workflow, spike, review_required)
    current = "queued"
    previous_at = None
    for index, transition in enumerate(state["transitions"]):
        at = datetime.fromisoformat(transition["at"].replace("Z", "+00:00"))
        if previous_at is not None and at < previous_at:
            _invalid(f"transitions[{index}].at", "chronological timestamp", transition["at"])
        previous_at = at
        if transition["from"] != current:
            _invalid(f"transitions[{index}].from", [current], transition["from"])
        if transition["to"] not in states[current]:
            _invalid(f"transitions[{index}].to", list(states[current]), transition["to"])
        if transition["to"] == "cancelled" and not all(
                str(transition.get(field, "")).strip() for field in ("authority", "reason")):
            _invalid(f"transitions[{index}]", "cancellation authority and reason", transition)
        current = transition["to"]
    if state["status"] not in states:
        _invalid("status", list(states), state["status"])
    if state["status"] != current:
        _invalid("status", [current], state["status"])
    return state


def state_path(project_root, task_id):
    if not isinstance(task_id, str) or not task_id or re.search(r"[/\\\s]", task_id) or task_id in {".", ".."}:
        _invalid("task_id", "one safe task ID", task_id)
    return Path(project_root) / names().tasks_path / f"{task_id}.json"


def read_task_state(project_root, task_id, workflow, *, spike=False, review_required=None, stop_factory,
                    text=None):
    """Read one state file (or its Git snapshot), returning state or a registered stop."""
    try:
        path = state_path(project_root, task_id)
        if text is None:
            journal = Path(project_root) / names().project_directory / "task-creation.lock"
            if journal.exists():
                raise stop_factory("TASK_STATE_INVALID",
                                   f"interrupted or active task creation: {journal}; retry or use task new --recover",
                                   task_id=task_id, project=project_root)
            try:
                text = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                raise stop_factory("TASK_STATE_MISSING", f"state file: allowed existing {path}; found missing",
                                   task_id=task_id, project=project_root)
            if journal.exists():
                raise stop_factory("TASK_STATE_INVALID", f"task creation changed during read: {journal}; retry",
                                   task_id=task_id, project=project_root)
        try:
            state = json.loads(text)
        except json.JSONDecodeError as error:
            _invalid("state", "valid JSON", str(error))
        return validate_task_state(state, task_id, workflow, spike=spike, review_required=review_required)
    except (OSError, UnicodeError) as error:
        raise stop_factory("TASK_STATE_INVALID", f"state file: allowed readable UTF-8 JSON; found {error}",
                           task_id=task_id, project=project_root) from error
    except TaskStateInvalid as error:
        raise stop_factory("TASK_STATE_INVALID", str(error), task_id=task_id, project=project_root) from error
