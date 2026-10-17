"""Schema validation and complete-history state machines for tracked task state.

Consumers use read_task_state, addressing one task directly without directory scans.
This module has no dependency on the CLI; the CLI supplies its registered stop factory.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


STATE_MACHINES = {
    "lean-delivery": {"QUEUED": ("DONE",), "DONE": ()},
    "governed-sdd": {
        "QUEUED": ("IN_PROGRESS",),
        "IN_PROGRESS": ("READY_FOR_REVIEW",),
        "READY_FOR_REVIEW": ("ACCEPTED", "CHANGES_REQUESTED"),
        "CHANGES_REQUESTED": ("IN_PROGRESS",),
        "ACCEPTED": (),
    },
}
SPIKE_MACHINE = {
    "QUEUED": ("IN_PROGRESS",),
    "IN_PROGRESS": ("ANSWERED", "INCONCLUSIVE"),
    "ANSWERED": (), "INCONCLUSIVE": (),
}
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas/task-state-v1.schema.json"


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
            if name not in properties:
                _invalid(f"{field}.{name}", sorted(properties), item)
            _validate_schema(item, properties[name], f"{field}.{name}")
    elif kind == "array":
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


def machine(workflow, spike=False, review_required=True):
    if workflow not in STATE_MACHINES:
        _invalid("workflow", list(STATE_MACHINES), workflow)
    if workflow == "governed-sdd" and spike:
        return SPIKE_MACHINE
    if workflow == "governed-sdd" and not review_required:
        return {"QUEUED": ("IN_PROGRESS",), "IN_PROGRESS": ("ACCEPTED",), "ACCEPTED": ()}
    return STATE_MACHINES[workflow]


def validate_task_state(state, task_id, workflow, *, spike=False, review_required=True):
    """Validate history; review_required=None selects the snapshot's review policy."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _validate_schema(state, schema)
    # Integration reads policy from the snapshot, without consulting prose.
    if review_required is None:
        review_required = state.get("review", {}).get("required", workflow == "governed-sdd")
    for field, expected in (("task_id", task_id), ("workflow", workflow)):
        if state[field] != expected:
            _invalid(field, [expected], state[field])
    states = machine(workflow, spike, review_required)
    current = "QUEUED"
    for index, transition in enumerate(state["transitions"]):
        if transition["from"] != current:
            _invalid(f"transitions[{index}].from", [current], transition["from"])
        if transition["to"] not in states[current]:
            _invalid(f"transitions[{index}].to", list(states[current]), transition["to"])
        current = transition["to"]
    if state["status"] not in states:
        _invalid("status", list(states), state["status"])
    if state["status"] != current:
        _invalid("status", [current], state["status"])
    return state


def state_path(project_root, task_id):
    if not isinstance(task_id, str) or not task_id or re.search(r"[/\\\s]", task_id) or task_id in {".", ".."}:
        _invalid("task_id", "one safe task ID", task_id)
    return Path(project_root) / ".meridian" / "tasks" / f"{task_id}.json"


def read_task_state(project_root, task_id, workflow, *, spike=False, review_required=True, stop_factory,
                    text=None):
    """Read one state file (or its Git snapshot), returning state or a registered stop."""
    try:
        path = state_path(project_root, task_id)
        if text is None:
            try:
                text = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                raise stop_factory("TASK_STATE_MISSING", f"state file: allowed existing {path}; found missing",
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
