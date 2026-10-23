"""State-first task fixtures: a record, a frozen contract snapshot, and validated state."""
from __future__ import annotations

import json
from pathlib import Path

from task_contract_support import freeze_record, seal_state

AT = "2026-10-11T12:00:00Z"


def route(status: str, *, verdict: str | None = None, required: bool = True) -> list[str]:
    """The ordered statuses a task passes through to reach `status`."""
    steps = ["queued"]
    if status == "cancelled":
        return [*steps, "cancelled"]
    if status != "queued":
        steps.append("in_progress")
    if status == "in_review" or (verdict and status == "in_progress"):
        steps.append("in_review")
    if steps[-1] != status:
        steps.append(status)
    return steps


def build_state(task_id: str, status: str, *, verdict: str | None = None, required: bool = True,
                outcome: str | None = None) -> dict:
    steps = route(status, verdict=verdict, required=required)
    transitions = [{"from": before, "to": after, "commit": "a" * 40, "at": AT,
                    **({"authority": "owner", "reason": "obsolete"} if after == "cancelled" else {})}
                   for before, after in zip(steps, steps[1:])]
    state = {"version": 1, "task_id": task_id, "workflow": "single", "status": status,
             "transitions": transitions}
    if verdict or required or status == "in_review":
        state["review"] = {"required": required, "verdict": verdict, "attempt": 1,
                           "reviewed_commit": "a" * 40 if verdict else None,
                           "approved_by": "reviewer" if verdict else None}
    if outcome:
        state["outcome"] = outcome
    return state


def write_task(root: Path, task_id: str, status: str = "queued", dependencies: str = "none", *,
               title: str | None = None, priority: str = "P1", phase: str = "Build",
               verdict: str | None = None, required: bool = True, outcome: str | None = None,
               objective: str = "Do it.", criteria: str = "Check.", record: str | None = None) -> Path:
    """Write the record and the validated state of one task; return the record path."""
    path = root / (record or f"tasks/{task_id}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {title or f'Task {task_id}'}\n\n> **ID**: `{task_id}`\n> **Priority**: {priority}\n"
        f"> **Phase**: {phase}\n\n## Objective\n\n{objective}\n\n## Acceptance Criteria\n\n- [ ] {criteria}\n\n"
        f"## Dependencies\n- **Depends on**: {dependencies}\n", encoding="utf-8")
    state_file = root / ".cardine/tasks" / f"{task_id}.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(build_state(task_id, status, verdict=verdict, required=required,
                                                 outcome=outcome)), encoding="utf-8")
    freeze_record(root, task_id, path, spike=bool(outcome))
    return path


def set_state(root: Path, task_id: str, status: str, *, verdict: str | None = None,
              required: bool = True) -> None:
    """Move an existing task's state to another status, keeping its frozen contract."""
    state_file = root / ".cardine/tasks" / f"{task_id}.json"
    contract = json.loads(state_file.read_text(encoding="utf-8"))["contract"]
    state = build_state(task_id, status, verdict=verdict, required=required)
    state["contract"] = contract
    state_file.write_text(json.dumps(state), encoding="utf-8")
    seal_state(root, task_id)
