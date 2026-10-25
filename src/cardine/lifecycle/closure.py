from __future__ import annotations

from cardine.shared.layout import names

from cardine.integration.evidence import candidate_validation_declaration
from cardine.integration.merge import _integration_task_state
from cardine.integration.merge import abort_task_integration
from cardine.integration.merge import cleanup_task_worktree
from cardine.integration.merge import finalize_task_integration
from cardine.integration.merge import missing_candidate_validation_commands
from cardine.integration.merge import runnable_candidate_validation_command
from cardine.integration.merge import stage_task_integration
from cardine.shared.errors import InternalStopError
from cardine.shared.errors import CardineError
from cardine.shared.errors import CardineStop
from cardine.shared.journal import JOURNAL_VERSION
from cardine.shared.journal import append_journal_line
from cardine.shared.jsonio import _read_json_object
from cardine.shared.jsonio import _write_json_atomic
from cardine.stops.registry import load_stop_registry
from cardine.stops.render import _task_state_recovery_project
from cardine.stops.render import stop_resume
from cardine.tasks.identity import resolve_task_identity
from cardine.templates.mode import detect_mode
from cardine.worktree.checkout import inspect_task_worktree
from cardine.worktree.closure_status import closure_status
from cardine.worktree.storage import _lifecycle_paths
from cardine.worktree.storage import _verified_lifecycle_project
from datetime import datetime
from datetime import timezone
from pathlib import Path
import shlex
import sys


def _journal_advance_step(project_root: Path, command: str, task_id: str, step: str) -> None:
    """Journal one step that `advance` performed, under the single-step command's own name."""
    line = {
        "version": JOURNAL_VERSION,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": command,
        "task": task_id.removeprefix("task-"),
        "result": "ok",
        "exit": 0,
        "step": step,
    }
    try:
        append_journal_line(project_root, line)
    except (OSError, CardineError, InternalStopError) as error:
        print(f"warning: lifecycle journal not written: {type(error).__name__}", file=sys.stderr)



def advance_task_closure(
    task_id: str,
    worktree_root: Path | None,
    *,
    supplied_project: Path | None = None,
    candidate_commands: list[str] | None = None,
    candidate_exit_codes: list[int] | None = None,
) -> tuple[dict[str, object], bool]:
    """Run the mechanical closure steps and return where the agent must act next.

    It performs C6 (stage), C8 (finalize from the supplied candidate
    validation results) and C10 (cleanup) when closure_status says their
    preconditions hold. C5 is satisfied only by the measured validation the
    run engine recorded; no caller-supplied result or acceptance is read.
    It never runs a command the agent supplied.
    The boolean is True when the result is a stop that the CLI reports with exit 2.
    """
    candidate_commands = candidate_commands or []
    candidate_exit_codes = candidate_exit_codes or []
    if len(candidate_commands) != len(candidate_exit_codes):
        raise CardineError("each --candidate-command requires one --candidate-exit-code")
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise CardineError("worktree advance must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    state_path, _lease_path, integration_path = _lifecycle_paths(project_root, identity)
    task = identity.canonical_id
    performed: list[str] = []

    def result(
        step: str,
        action: str,
        *,
        commands: list[str] | None = None,
        required_fragments: list[str] | None = None,
        stop_code: str | None = None,
        stop_detail: str | None = None,
        resume: str | None = None,
        blocked: bool = False,
    ) -> tuple[dict[str, object], bool]:
        if stop_code is not None and resume is None:
            resume = stop_resume(stop_code, task_id=task, project=str(project_root))
        # Status-only stops have no exception detail; keep the available reason,
        # or an empty string when closure-status supplied none.
        if stop_code is not None and stop_detail is None:
            stop_detail = str(status.get("resume") or "")
        return ({
            "version": 1,
            "task_id": task,
            "step": step,
            "action_required": action,
            "commands": commands or [],
            **({"required_fragments": required_fragments} if required_fragments is not None else {}),
            "stop_code": stop_code,
            "stop_detail": stop_detail if stop_code is not None else None,
            "resume": resume,
            "performed": performed,
        }, blocked)

    def error_detail(error: CardineStop) -> str:
        return str(error).split(f"{error.code}: ", 1)[-1].rsplit("; resume: ", 1)[0]

    def stopped(step: str, code: str, detail: str | None = None) -> tuple[dict[str, object], bool]:
        entry = load_stop_registry()[code]
        if entry.get("human_decision") is True:
            action = "human"
        elif step in ("C1", "C2"):
            action = "run-validation"
        else:
            action = "resolve"
        return result(step, action, stop_code=code, stop_detail=detail, blocked=entry.get("kind") != "status")

    while True:
        status, _ready = closure_status(task, worktree_root, project_root)
        step = str(status["step"])
        code = status["stop_reason"] if isinstance(status["stop_reason"], str) else None
        if step in performed:
            raise CardineError(f"closure state did not advance after {step}; run closure-status")
        if step == "C1":
            return result("C1", "run-validation", stop_code="ACCEPTANCE_UNMET")
        if step == "C5":
            return result("C5", "run-validation", stop_code="EVIDENCE_INCOMPLETE")
        elif step == "C6" and code is None:
            try:
                inspection, ready = inspect_task_worktree(
                    task, worktree_root, project_root, require_effective_worktree=False, identity=identity,
                )
                if ready:
                    _integration_task_state(project_root, identity, str(inspection["task_commit"]),
                                            Path(str(inspection["worktree"])), require_tracked=True)
            except CardineStop as error:
                resume = stop_resume(error.code, task_id=task, project=project_root)
                return result("C6", "resolve", commands=[resume], stop_code=error.code,
                              stop_detail=error_detail(error), resume=resume, blocked=True)
            try:
                staged = stage_task_integration(task, worktree_root, None, project_root)
            except CardineStop as error:
                return stopped("C6", error.code, error_detail(error))
            performed.append("C6")
            _journal_advance_step(project_root, "integrate stage", task, str(staged.get("next_action", "C6")))
        elif code is not None and not (step == "C9" and code == "PUSH_PENDING"):
            return stopped(step, code)
        elif step == "C7":
            staged = _read_json_object(integration_path, "staged integration state")
            declaration_state, fragments = candidate_validation_declaration(project_root, task)
            required = ["git diff --check", *fragments.get(str(staged.get("decision")), ())]
            commands = [entry for entry in required if runnable_candidate_validation_command(entry, project_root)]
            instruction = (
                "Run commands unchanged from the primary checkout. For each required_fragments entry "
                "not covered by commands, run a project command containing that exact fragment; "
                "report every command and exit code to advance."
            )
            if not candidate_commands:
                return result("C7", "run-candidate-validation", commands=commands,
                              required_fragments=required, resume=instruction)
            aborted_resume = (
                "the integration was aborted; fix the failure on the task branch, rerun validation, "
                "then rerun advance"
            )
            if any(exit_code != 0 for exit_code in candidate_exit_codes):
                abort_task_integration(task, project_root)
                _journal_advance_step(project_root, "integrate abort", task, "C7")
                performed.append("abort")
                return result(
                    "C7", "resolve", stop_code="CANDIDATE_VALIDATION_FAILED", resume=aborted_resume, blocked=True
                )
            missing = (
                commands
                if declaration_state == "undeclared"
                else list(missing_candidate_validation_commands(staged.get("decision"), candidate_commands, fragments))
            )
            if missing:
                abort_task_integration(task, project_root)
                _journal_advance_step(project_root, "integrate abort", task, "C7")
                performed.append("abort")
                return result(
                    "C7",
                    "run-candidate-validation",
                    commands=[entry for entry in missing if runnable_candidate_validation_command(entry, project_root)],
                    required_fragments=missing,
                    stop_code="UNDECLARED_VALIDATION_COMMANDS",
                    resume="the integration was aborted; " + instruction,
                    blocked=True,
                )
            candidate_evidence = state_path.with_suffix(".candidate-validation.json")
            _write_json_atomic(candidate_evidence, {
                "version": 1,
                "task_id": task,
                "candidate_tree": staged["candidate_tree"],
                "passed": True,
                "scope": "full" if staged.get("decision") == "FULL" else "bounded",
                "commands": candidate_commands,
            })
            try:
                finalize_task_integration(task, candidate_evidence, project_root)
            except CardineStop as error:
                return stopped("C8", error.code, error_detail(error))
            performed.append("C8")
            _journal_advance_step(project_root, "integrate finalize", task, "C8")
            return result(
                "C9", "push", commands=["git push origin main"], stop_code="PUSH_PENDING", resume="git push origin main"
            )
        elif step == "C9":
            return result("C9", "push", commands=["git push origin main"], stop_code=code, resume="git push origin main")
        elif step == "C10":
            cleaned = cleanup_task_worktree(task, worktree_root, project_root)
            if not cleaned.get("already_cleaned"):
                performed.append("C10")
                _journal_advance_step(project_root, "cleanup", task, "C10")
            return result("C10", "none")
        else:
            raise CardineError(f"unexpected closure state at {step}; run closure-status")

