"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import CardineStop
from cardine.shared.git import _run_git
from cardine.shared.git import current_branch
from cardine.shared.git import git_output
from cardine.shared.jsonio import _write_json_atomic
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

def record_review_verdict(project_root: Path, task_id: str, verdict: str, *, owner: bool = False,
                          body: str = "") -> dict[str, object]:
    """Bind a review and its transition to HEAD, with prose as a projection only."""
    project_root = project_root.resolve()
    identity = resolve_task_identity(project_root, task_id, "existing")
    task_id = identity.canonical_id
    workflow = detect_mode(project_root)
    required = None
    path = state_path(project_root, task_id)
    head = git_output(project_root, "rev-parse", "HEAD")
    approved_by = "owner" if owner else "reviewer"

    def invalid(message):
        raise stop_error("TASK_STATE_INVALID", message, task_id=task_id, project=project_root)

    if current_branch(project_root) != identity.branch_name:
        invalid(f"branch: allowed {identity.branch_name!r}; found {current_branch(project_root)!r}")
    if verdict not in {"APPROVE", "CHANGES_REQUESTED", "BLOCKED"}:
        invalid(f"verdict: allowed APPROVE, CHANGES_REQUESTED, BLOCKED; found {verdict!r}")
    state = read_task_state(project_root, task_id, workflow,
                            review_required=required, stop_factory=stop_error, require_contract=True)
    from cardine.tasks.state import review_is_required
    if not review_is_required(state):
        invalid("review requires a required-review task")
    previous = state.get("review", {})
    repeated = (previous.get("verdict") == verdict and previous.get("reviewed_commit") == head
                and previous.get("approved_by") == approved_by
                and state["status"] == {"APPROVE": "in_progress", "CHANGES_REQUESTED": "in_progress",
                                        "BLOCKED": "in_review"}[verdict])
    dirty = git_output(project_root, "status", "--porcelain", "--untracked-files=all")
    if repeated and dirty:
        # A retry at the reviewed HEAD necessarily sees this command's uncommitted
        # outputs. Accept only byte-identical projections of the original HEAD;
        # staged files, edits to those outputs, and unrelated dirt still stop.
        original = _run_git(project_root, "show", f"HEAD:{path.relative_to(project_root)}")
        if original.returncode == 0:
            try:
                baseline = read_task_state(project_root, task_id, workflow,
                                           review_required=required, stop_factory=stop_error, require_contract=True, text=original.stdout)
                projected = _review_verdict_projection(baseline, verdict, head, approved_by,
                                                      state["transitions"][-1]["at"])
            except (CardineStop, ValueError, KeyError, IndexError):
                projected = None
            expected = {path: json.dumps(projected, indent=2, sort_keys=True) + "\n"}
            for target in (identity.review_path,):
                old = _run_git(project_root, "show", f"HEAD:{target.relative_to(project_root)}")
                text = old.stdout if old.returncode == 0 else ""
                expected[target] = _review_attempt_text(text, previous["attempt"], verdict, body)
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
    if state["status"] != "in_review":
        invalid(f"review status: allowed in_review; found {state['status']!r}")
    if verdict == "APPROVE":
        # Submission binds the implementation to the transition's parent.
        # Governance commits preserve it; any later implementation commit,
        # including a change that was reverted, needs a new submission.
        submitted = state["transitions"][-1]["commit"]
        allowed = {path.relative_to(project_root).as_posix(),
                   identity.task_path.relative_to(project_root).as_posix(),
                   identity.handoff_path.relative_to(project_root).as_posix(),
                   identity.review_path.relative_to(project_root).as_posix()}
        if _run_git(project_root, "merge-base", "--is-ancestor", submitted, head).returncode:
            invalid("submission commit is not an ancestor of the review HEAD")
        changed = git_output(project_root, "log", "--format=", "--name-only", f"{submitted}..{head}").splitlines()
        if set(filter(None, changed)) - allowed:
            raise stop_error("REVIEW_STALE", "implementation changed after submission; request changes and submit a new attempt",
                             task_id=task_id, project=project_root)
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    state = _review_verdict_projection(state, verdict, head, approved_by, at)
    try:
        validate_task_state(state, task_id, workflow, review_required=required)
    except TaskStateInvalid as error:
        invalid(str(error))
    review_text = identity.review_path.read_text(encoding="utf-8") if identity.review_path.exists() else ""
    projection = _review_attempt_text(review_text, state["review"]["attempt"], verdict, body)
    _write_json_atomic(path, state)
    identity.review_path.parent.mkdir(parents=True, exist_ok=True)
    identity.review_path.write_text(projection, encoding="utf-8")
    return state


def _review_verdict_projection(state, verdict, head, approved_by, at):
    state = json.loads(json.dumps(state))
    attempt = state.get("review", {}).get("attempt", 0) + 1
    state["review"] = {"required": True, "verdict": verdict, "attempt": attempt,
                       "reviewed_commit": head, "approved_by": approved_by, "source": "local"}
    state.setdefault("review_history", []).append(dict(state["review"]))
    if verdict != "BLOCKED":
        destination = "in_progress"
        state["transitions"].append({"from": state["status"], "to": destination,
                                     "commit": head, "at": at})
        state["status"] = destination
    return state


def _review_attempt_text(text, attempt, verdict, body):
    prefix = text.rstrip() + "\n\n" if text.strip() else ""
    return prefix + f"## Attempt {attempt} — {verdict}\n" + ("\n" + body.rstrip() + "\n" if body else "")
