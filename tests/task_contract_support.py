"""Complete records used by import fixtures without changing their evidence."""

VALIDATION = {
    "commands": {}, "baseline": [],
    "candidate": {"REUSE": [], "BOUNDED": [], "FULL": []},
}


def contract_record(task_id="001", *, extra="", spike=False):
    return (
        f"# Task {task_id} — Contract fixture\n\n> **ID**: `{task_id}`\n"
        "Priority: P1\nEstimate: 1h\n"
        + ("Class: spike\nQuestion: Is it feasible?\nTimebox: 1h\nDeliverable: docs/result.md\n" if spike else "")
        + extra + "\n## Objective\nResolve this bounded task.\n"
        "## Acceptance Criteria\n- [ ] The result is verified.\n"
        "## Relevant Files\n`docs/result.md`\n## Out of scope\nOther tasks.\n"
        "## Dependencies\nnone\n## Authority\nADR example, decision 1.\n"
        "## Expected code surface\nChange the documented deliverable only.\n"
        "## Validation\n- `task-check`: `python3 -c 'pass'`\n"
    )


def write_state(root, task_id="001", status="queued", *, review_required=None):
    """Register fixture state, preserving or initially freezing its policy."""
    import json
    path = root / ".cardine/tasks" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    steps = {"queued": (), "in_progress": ("in_progress",),
             "in_review": ("in_progress", "in_review"), "done": ("in_progress", "done"),
             "cancelled": ("cancelled",)}[status]
    transitions = []
    current = "queued"
    for target in steps:
        transition = {"from": current, "to": target, "commit": "a" * 40, "at": "2026-10-11T12:00:00Z"}
        if target == "cancelled":
            transition.update(authority="owner", reason="Fixture cancelled")
        transitions.append(transition)
        current = target
    previous = json.loads(path.read_text()) if path.exists() else {}
    state = {"version": 1, "task_id": task_id, "workflow": "single", "status": status, "transitions": transitions}
    if "contract" in previous:
        from copy import deepcopy
        state["contract"] = deepcopy(previous["contract"])
        if review_required is not None:
            state["contract"]["options"]["review"] = "required" if review_required else "not_required"
    if review_required is not None:
        state["review"] = {"required": review_required, "verdict": None, "attempt": 1,
                           "reviewed_commit": None, "approved_by": None}
    path.write_text(json.dumps(state))
    if "contract" not in state:
        from cardine.shared.errors import CardineError
        from cardine.tasks.identity import find_task_file
        try:
            record = find_task_file(root, task_id)
        except CardineError:
            record = None
        if record is not None:
            freeze_record(root, task_id, record)
    return path


def freeze_record(root, task_id, record=None, *, spike=None):
    """Freeze fixture input at setup time, preserving its independent machine history."""
    import json
    from types import SimpleNamespace
    from cardine.tasks.contract import resolve_human_fields
    from cardine.shared.project import preset_task_defaults
    root = root.resolve()
    record = (record or root / "tasks" / f"{task_id}.md").resolve()
    path = root / ".cardine/tasks" / f"{task_id}.json"
    state = json.loads(path.read_text()) if path.exists() else {
        "version": 1, "task_id": task_id, "workflow": "single", "status": "queued", "transitions": []}
    from cardine.tasks.contract import resolve_task_contract, task_contract_options
    from cardine.shared.errors import CardineError
    from cardine.shared.project import resolve_project_configuration
    identity = SimpleNamespace(canonical_id=task_id, task_path=record)
    text = record.read_text() if record.is_file() else ""
    if spike is None:
        from cardine.shared.text import read_task_field
        spike = (read_task_field(text, "Class") or "").lower() == "spike"
    try:
        contract = resolve_task_contract(root, task_id, text=text, identity=identity)
    except CardineError:
        human = resolve_human_fields(root, identity, text, "spike" if spike else "standard")
        try:
            config = resolve_project_configuration(root)
        except CardineError:
            config = {"preset": "lean", "taskDefaults": preset_task_defaults("lean")}
        contract = {"class": "spike" if spike else "standard", "preset": config["preset"],
                    "projectDigest": "sha256:" + "0" * 64,
                    "options": {**config["taskDefaults"], **task_contract_options(text)},
                    "validation": config.get("validation", VALIDATION), "ci": "none", "validationScoping": [], **human}
        if state.get("review", {}).get("required") or state["status"] == "in_review":
            contract["options"]["review"] = "required"
    state["contract"] = contract
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))
    return state
