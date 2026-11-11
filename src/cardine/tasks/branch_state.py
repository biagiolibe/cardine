"""Observe canonical task branches for advisory, read-only status displays."""
from __future__ import annotations

import json
from pathlib import Path

from cardine.shared.errors import CardineError
from cardine.shared.git import _run_git, parse_worktree_records
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import TaskStateInvalid, validate_task_state
from cardine.tasks.state_core import state_path


def observe_task_branches(project_root: Path, model: dict) -> dict:
    """Return valid branch statuses, ignoring unavailable or invalid local bytes."""
    root = Path(project_root).resolve()
    observations = {}
    try:
        listed = _run_git(root, "worktree", "list", "--porcelain")
        if listed.returncode:
            return observations
        worktrees = {item.get("branch"): Path(item["worktree"])
                     for item in parse_worktree_records(listed.stdout) if "worktree" in item}
    except (OSError, UnicodeError, CardineError):
        return observations
    for row in model["tasks"]:
        if row["status"] in ("done", "cancelled"):
            continue
        try:
            task_id = row["id"]
            branch = resolve_task_identity(root, task_id, "existing").branch_name
            ref = f"refs/heads/{branch}"
            worktree = worktrees.get(ref)
            available = worktree is not None and worktree.is_dir()
            if available:
                content = state_path(worktree, task_id).read_text(encoding="utf-8")
                source = f"task state in worktree {branch}"
            else:
                relative = state_path(root, task_id).relative_to(root).as_posix()
                result = _run_git(root, "show", f"{ref}:{relative}")
                if result.returncode:
                    continue
                content = result.stdout
                source = f"task state on branch {branch}"
            state = json.loads(content)
            validate_task_state(state, task_id, "single", spike="outcome" in state)
            status = state["status"]
            if available and row["status"] == "queued" and status == "queued":
                status = "in_progress"
            observations[task_id] = {"status": status, "source": source}
        except (OSError, UnicodeError, ValueError, TypeError, TaskStateInvalid, CardineError):
            continue
    return observations
