"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import InternalStopError
from cardine.shared.errors import MeridianError
from cardine.shared.errors import MeridianStop
from cardine.shared.git import _git_worktrees
from cardine.shared.git import canonical_project_root
from cardine.stops.registry import load_stop_registry
from cardine.tasks.identity import resolve_task_identity
from pathlib import Path
import shlex


def _task_state_recovery_project(project: Path, task_id: str) -> Path:
    """Direct state recovery to the task branch's registered checkout when present."""
    project = project.expanduser().resolve()
    try:
        primary = canonical_project_root(project)
        identity = resolve_task_identity(primary, task_id, "existing", check_queue_links=False)
        return next((Path(item["worktree"]).resolve() for item in _git_worktrees(primary)
                     if item.get("branch") == f"refs/heads/{identity.branch_name}"), primary)
    except MeridianError:
        return project


def stop_resume(code: str, **fields: object) -> str:
    """Return the registered resume template for `code` with its fields filled in."""
    entry = load_stop_registry().get(code)
    if entry is None:
        raise InternalStopError(f"unregistered stop code: {code}")
    if code == "TASK_STATE_MISSING" and fields.get("project") and fields.get("task_id"):
        fields["project"] = shlex.quote(str(_task_state_recovery_project(
            Path(str(fields["project"])), str(fields["task_id"]),
        )))
    try:
        return str(entry["resume"]).format(**fields)
    except KeyError as error:
        raise InternalStopError(f"stop {code} resume template needs field {error}") from error


def format_stop(code: str, detail: str, *, resume: str | None = None, **fields: object) -> str:
    """Format the single `BLOCKED <CODE>: <detail>; resume: <command>` line."""
    resume_text = resume if resume is not None else stop_resume(code, **fields)
    if code not in load_stop_registry():
        raise InternalStopError(f"unregistered stop code: {code}")
    return f"BLOCKED {code}: {detail}; resume: {resume_text}"


def stop_error(code: str, detail: str, **fields: object) -> MeridianStop:
    """Build the error for a registered stop; the CLI prints it unchanged and exits 2."""
    if code == "TASK_STATE_MISSING":
        # Missing state is also a normal legacy probe. Resolve Git recovery paths
        # only when the stop is displayed, not when a caller catches that probe.
        return MeridianStop(code, detail, render=lambda: format_stop(code, detail, **fields))
    return MeridianStop(code, format_stop(code, detail, **fields))
