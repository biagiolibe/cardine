"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from pathlib import Path

from cardine.tasks.contract import profile_cap
from cardine.shared.budget import BUDGET_FIELD_NAMES
from cardine.shared.budget import load_budget_state
from cardine.shared.budget import write_budget_state
from cardine.shared.errors import MeridianError
from cardine.shared.text import read_task_field
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.paths import repository_identity


def proposed_project_identity(project_root: Path) -> dict[str, str]:
    """Derive a stable setup proposal even before a directory is a Git repository."""
    try:
        slug = repository_identity(project_root).repository
    except MeridianError:
        slug = project_root.resolve().name.lower()
    return {"name": slug.replace("-", " ").title(), "slug": slug}


def task_cap(project_root: Path, text: str, kind: str) -> int:
    raw = read_task_field(text, BUDGET_FIELD_NAMES[kind])
    if raw and raw.isdigit():
        return int(raw)
    return profile_cap(project_root, kind)


def resolve_budget_key(project_root: Path, state: dict[str, object], task_id: str) -> tuple[str, str]:
    """Return the qualified `<TASK-ID>:<attempt>` state key and the task file's
    text, bumping `state`'s attempt bookkeeping in place when the task file
    shows a fresh READY_FOR_REVIEW -> IN_PROGRESS transition (a new
    remediation attempt) since the last time this was resolved.
    """
    identity = resolve_task_identity(project_root, task_id, "existing")
    task_file = identity.task_path
    text = task_file.read_text(encoding="utf-8")
    status = read_task_field(text, "Status") or "UNKNOWN"
    canonical_id = identity.canonical_id
    meta = dict(state.get(canonical_id) or {"attempt": 1, "lastStatus": None})
    if meta.get("lastStatus") == "READY_FOR_REVIEW" and status == "IN_PROGRESS":
        meta["attempt"] = int(meta.get("attempt", 1)) + 1
    meta["lastStatus"] = status
    state[canonical_id] = meta
    return identity.budget_key(int(meta["attempt"])), text


def budget_show(project_root: Path, task_id: str) -> str:
    state = load_budget_state(project_root)
    key, text = resolve_budget_key(project_root, state, task_id)
    counters = state.get(key, {})
    parts = [f"Attempt {key.rsplit(':', 1)[1]}"]
    for kind, label in (
        ("diagnostic", "Diagnostics"),
        ("captures", "Captures"),
        ("expansions", "Expansions"),
        ("investigations", "Investigations"),
    ):
        cap = task_cap(project_root, text, kind)
        if kind == "captures":
            scoped = sorted((key.removeprefix("captures:"), value) for key, value in counters.items() if key.startswith("captures:"))
            if scoped:
                parts.append(f"{label} " + ", ".join(f"{criterion} {int(count)}/{cap}" for criterion, count in scoped))
                continue
        parts.append(f"{label} {int(counters.get(kind, 0))}/{cap}")
    return " · ".join(parts)


def budget_spend(
    project_root: Path, task_id: str, kind: str, scope: str | None = None, amount: int = 1
) -> tuple[int, int]:
    if amount < 1:
        raise stop_error(
            "EXECUTION_EVIDENCE_ARGUMENTS",
            f"rule: a budget use is at least one; option checked: --scope; accepted: an integer of 1 or more; found: {amount}",
            resume="rerun meridian execution investigate with --scope of 1 or more",
        )
    state = load_budget_state(project_root)
    key, text = resolve_budget_key(project_root, state, task_id)
    counters = dict(state.get(key, {}))
    counter_key = f"{kind}:{scope}" if kind == "captures" and scope else kind
    stored = int(counters.get(counter_key, 0))
    count = stored + amount
    cap = task_cap(project_root, text, kind)
    if count > cap:
        raise stop_error(
            "BUDGET_EXHAUSTED",
            f"{BUDGET_FIELD_NAMES[kind]} exhausted for {task_id}: "
            f"{stored} of {cap} allowed uses already recorded, {amount} more requested; do not raise the cap",
        )
    counters[counter_key] = count
    state[key] = counters
    write_budget_state(project_root, state)
    return count, cap
