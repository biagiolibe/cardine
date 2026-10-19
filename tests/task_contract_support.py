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
