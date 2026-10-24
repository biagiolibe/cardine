"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.shared.errors import InternalStopError
from cardine.shared.errors import CardineError
from cardine.shared.errors import CardineStop
from cardine.shared.git import _git_worktrees
from cardine.shared.git import canonical_project_root
from cardine.stops.registry import load_stop_registry
from cardine.tasks.identity import resolve_task_identity
from pathlib import Path
import shlex
import json
import sys


def _task_state_recovery_project(project: Path, task_id: str) -> Path:
    """Direct state recovery to the task branch's registered checkout when present."""
    project = project.expanduser().resolve()
    try:
        primary = canonical_project_root(project)
        identity = resolve_task_identity(primary, task_id, "existing", check_queue_links=False)
        return next((Path(item["worktree"]).resolve() for item in _git_worktrees(primary)
                     if item.get("branch") == f"refs/heads/{identity.branch_name}"), primary)
    except CardineError:
        return project


def stop_resume(code: str, **fields: object) -> str:
    """Return the registered resume template for `code` with its fields filled in."""
    entry = load_stop_registry().get(code)
    if entry is None:
        raise InternalStopError(f"unregistered stop code: {code}")
    if code == "TASK_STATE_MISSING" and fields.get("project") and fields.get("task_id"):
        fields["project"] = str(_task_state_recovery_project(
            Path(str(fields["project"])), str(fields["task_id"]),
        ))
    try:
        return str(entry["resume"]).format(**{key: shlex.quote(str(value)) for key, value in fields.items()})
    except KeyError as error:
        raise InternalStopError(f"stop {code} resume template needs field {error}") from error


def format_stop(code: str, detail: str, *, resume: str | None = None, **fields: object) -> str:
    """Format the single `BLOCKED <CODE>: <detail>; resume: <command>` line."""
    resume_text = resume if resume is not None else stop_resume(code, **fields)
    if code not in load_stop_registry():
        raise InternalStopError(f"unregistered stop code: {code}")
    prefix = {"blocked": "BLOCKED", "next": "NEXT", "iterate": "ITERATE"}[outcome_for_code(code)]
    return f"{prefix} {code}: {detail}; resume: {resume_text}"


def stop_error(code: str, detail: str, **fields: object) -> CardineStop:
    """Build a typed diagnostic; lazy rendering never performs a lifecycle effect."""
    recovery = lambda: str(fields["resume"]) if fields.get("resume") is not None else stop_resume(code, **fields)
    error = CardineStop(code, detail, render=lambda: format_stop(code, detail, resume=recovery()))
    error.detail = detail
    error.resume = recovery
    return error


def outcome_for_code(code: str) -> str:
    """Classify a registered diagnostic without granting repair authority."""
    entry = load_stop_registry().get(code)
    if entry is None:
        raise InternalStopError(f"unregistered stop code: {code}")
    return {"guardrail": "blocked", "recoverable": "next", "failing-work": "iterate"}[entry["resolution"]]


def emit_diagnostic(error: CardineStop, journal=None) -> int:
    """Render an Internal adapter diagnostic after its operation has finished."""
    outcome = outcome_for_code(error.code)
    if journal is not None:
        journal.stopped(error.code)
    print(error, file=sys.stderr)
    return 2 if outcome == "blocked" else 0


def render_run_output(result: dict, validate) -> str:
    """Serialize a closed run response without writing diagnostics or state."""
    validate(result)
    return json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def emit_run(result: dict, validate) -> int:
    """Emit the complete run envelope; diagnostics cannot advance operation state."""
    text = render_run_output(result, validate)
    stop = result["stop"]
    print(text)
    if stop is not None:
        print(format_stop(stop["code"], stop["detail"], resume=stop["resume"]), file=sys.stderr)
    return 2 if result["outcome"] == "blocked" else 0
