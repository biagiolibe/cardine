"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import MeridianStop
from cardine.shared.git import _run_git
from cardine.shared.git import current_branch
from cardine.shared.git import git_output
from cardine.shared.jsonio import _write_json_atomic
from cardine.shared.text import read_task_field
from cardine.stops.render import stop_error
from cardine.tasks.identity import resolve_task_identity
from cardine.tasks.state import TaskStateInvalid
from cardine.tasks.state import read_task_state
from cardine.tasks.state import state_path
from cardine.tasks.state import validate_task_state
from cardine.templates.mode import detect_mode
from datetime import datetime
from datetime import timezone
from pathlib import Path
import json
import re

def record_review_verdict(project_root: Path, task_id: str, verdict: str, *, owner: bool = False,
                          body: str = "") -> dict[str, object]:
    """Bind a review and its transition to HEAD, with prose as a projection only."""
    project_root = project_root.resolve()
    identity = resolve_task_identity(project_root, task_id, "existing")
    task_id = identity.canonical_id
    workflow = detect_mode(project_root)
    record = identity.task_path.read_text(encoding="utf-8")
    spike = read_task_field(record, "Class") == "SPIKE"
    required = read_task_field(record, "Review") != "NOT_REQUIRED"
    path = state_path(project_root, task_id)
    head = git_output(project_root, "rev-parse", "HEAD")
    approved_by = "owner" if owner else "reviewer"

    def invalid(message):
        raise stop_error("TASK_STATE_INVALID", message, task_id=task_id, project=project_root)

    if current_branch(project_root) != identity.branch_name:
        invalid(f"branch: allowed {identity.branch_name!r}; found {current_branch(project_root)!r}")
    if verdict not in {"APPROVE", "CHANGES_REQUESTED", "BLOCKED"}:
        invalid(f"verdict: allowed APPROVE, CHANGES_REQUESTED, BLOCKED; found {verdict!r}")
    state = read_task_state(project_root, task_id, workflow, spike=spike,
                            review_required=required, stop_factory=stop_error)
    previous = state.get("review", {})
    repeated = (previous.get("verdict") == verdict and previous.get("reviewed_commit") == head
                and previous.get("approved_by") == approved_by
                and state["status"] == {"APPROVE": "ACCEPTED", "CHANGES_REQUESTED": "CHANGES_REQUESTED",
                                        "BLOCKED": "READY_FOR_REVIEW"}[verdict])
    dirty = git_output(project_root, "status", "--porcelain", "--untracked-files=all")
    if repeated and dirty:
        # A retry at the reviewed HEAD necessarily sees this command's uncommitted
        # outputs. Accept only byte-identical projections of the original HEAD;
        # staged files, edits to those outputs, and unrelated dirt still stop.
        original = _run_git(project_root, "show", f"HEAD:{path.relative_to(project_root)}")
        if original.returncode == 0:
            try:
                baseline = read_task_state(project_root, task_id, workflow, spike=spike,
                                           review_required=required, stop_factory=stop_error, text=original.stdout)
                projected = _review_verdict_projection(baseline, verdict, head, approved_by,
                                                      state["transitions"][-1]["at"])
            except (MeridianStop, ValueError, KeyError, IndexError):
                projected = None
            expected = {path: json.dumps(projected, indent=2, sort_keys=True) + "\n"}
            for target in (identity.task_path, identity.review_path):
                old = _run_git(project_root, "show", f"HEAD:{target.relative_to(project_root)}")
                text = old.stdout if old.returncode == 0 else ""
                expected[target] = (_review_attempt_text(text, previous["attempt"], verdict, body)
                                    if target == identity.review_path else
                                    re.sub(r"^Status:[^\n]*", f"Status: {state['status']}", text, flags=re.MULTILINE))
            changed = _run_git(project_root, "diff", "--name-only", "HEAD", "-z").stdout.split("\0")
            untracked = _run_git(project_root, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")
            names = {name for name in changed + untracked if name}
            allowed = {str(target.relative_to(project_root)) for target in expected}
            if (projected == state and names <= allowed
                    and not git_output(project_root, "diff", "--cached", "--name-only")
                    and all(target.is_file() and target.read_text(encoding="utf-8") == text
                            for target, text in expected.items())):
                return state
    if dirty:
        invalid("worktree: allowed clean worktree; found uncommitted changes")
    if repeated:
        return state
    if state["status"] != "READY_FOR_REVIEW":
        invalid(f"review status: allowed READY_FOR_REVIEW; found {state['status']!r}")
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    state = _review_verdict_projection(state, verdict, head, approved_by, at)
    try:
        validate_task_state(state, task_id, workflow, spike=spike, review_required=required)
    except TaskStateInvalid as error:
        invalid(str(error))
    review_text = identity.review_path.read_text(encoding="utf-8") if identity.review_path.exists() else ""
    projection = _review_attempt_text(review_text, state["review"]["attempt"], verdict, body)
    record_projection = re.sub(r"^Status:[^\n]*", f"Status: {state['status']}", record, flags=re.MULTILINE)
    _write_json_atomic(path, state)
    identity.review_path.parent.mkdir(parents=True, exist_ok=True)
    identity.review_path.write_text(projection, encoding="utf-8")
    if record_projection != record:
        identity.task_path.write_text(record_projection, encoding="utf-8")
    return state


def _review_verdict_projection(state, verdict, head, approved_by, at):
    state = json.loads(json.dumps(state))
    attempt = state.get("review", {}).get("attempt", 0) + 1
    state["review"] = {"required": True, "verdict": verdict, "attempt": attempt,
                       "reviewed_commit": head, "approved_by": approved_by}
    if verdict != "BLOCKED":
        destination = "ACCEPTED" if verdict == "APPROVE" else "CHANGES_REQUESTED"
        state["transitions"].append({"from": state["status"], "to": destination,
                                     "commit": head, "at": at})
        state["status"] = destination
    return state


def _review_attempt_text(text, attempt, verdict, body):
    prefix = text.rstrip() + "\n\n" if text.strip() else ""
    return prefix + f"## Attempt {attempt} — {verdict}\n" + ("\n" + body.rstrip() + "\n" if body else "")
