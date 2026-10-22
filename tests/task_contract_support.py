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
    """Register explicit machine state for lifecycle fixtures."""
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
    state = {"version": 1, "task_id": task_id, "workflow": "single", "status": status, "transitions": transitions}
    if review_required is not None:
        state["review"] = {"required": review_required, "verdict": None, "attempt": 1,
                           "reviewed_commit": None, "approved_by": None}
    path.write_text(json.dumps(state))
    return path
