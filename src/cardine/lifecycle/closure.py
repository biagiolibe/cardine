from __future__ import annotations

from cardine.shared.layout import names

from cardine.integration.evidence import candidate_validation_declaration
from cardine.integration.evidence import record_task_evidence
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
    validation_commands: list[str],
    validation_exit_codes: list[int],
    *,
    accepted: bool,
    supplied_project: Path | None = None,
    candidate_commands: list[str] | None = None,
    candidate_exit_codes: list[int] | None = None,
) -> tuple[dict[str, object], bool]:
    """Run the mechanical closure steps and return where the agent must act next.

    It performs C5 (evidence), C6 (stage), C8 (finalize from the supplied
    candidate validation results) and C10 (cleanup) when closure_status says
    their preconditions hold. It never runs a command the agent supplied.
    The boolean is True when the result is a stop that the CLI reports with exit 2.
    """
    candidate_commands = candidate_commands or []
    candidate_exit_codes = candidate_exit_codes or []
    if len(validation_commands) != len(validation_exit_codes):
        raise CardineError("each --validation-command requires one --validation-exit-code")
    if len(candidate_commands) != len(candidate_exit_codes):
        raise CardineError("each --candidate-command requires one --candidate-exit-code")
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise CardineError("worktree advance must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    state_path, _lease_path, integration_path = _lifecycle_paths(project_root, identity)
    evidence_path = state_path.with_suffix(".evidence.json")
    task = identity.canonical_id
    performed: list[str] = []

    def result(
        step: str,
        action: str,
        *,
        commands: list[str] | None = None,
        required_fragments: list[str] | None = None,
        stop_code: str | None = None,
        resume: str | None = None,
        blocked: bool = False,
    ) -> tuple[dict[str, object], bool]:
        if stop_code is not None and resume is None:
            resume = stop_resume(stop_code, task_id=task, project=str(project_root), evidence=str(evidence_path))
        return ({
            "version": 1,
            "task_id": task,
            "step": step,
            "action_required": action,
            "commands": commands or [],
            **({"required_fragments": required_fragments} if required_fragments is not None else {}),
            "stop_code": stop_code,
            "resume": resume,
            "performed": performed,
        }, blocked)

    def stopped(step: str, code: str) -> tuple[dict[str, object], bool]:
        entry = load_stop_registry()[code]
        if entry.get("human_decision") is True:
            action = "human"
        elif step in ("C1", "C2"):
            action = "run-validation"
        else:
            action = "resolve"
        return result(step, action, stop_code=code, blocked=entry.get("kind") != "status")

    while True:
        status, _ready = closure_status(task, worktree_root, project_root)
        step = str(status["step"])
        code = status["stop_reason"] if isinstance(status["stop_reason"], str) else None
        if step in performed:
            raise CardineError(f"closure state did not advance after {step}; run closure-status")
        if step == "C1":
            return result("C1", "run-validation", stop_code="ACCEPTANCE_UNMET")
        if step == "C5":
            if not validation_commands:
                return result("C5", "run-validation", stop_code="EVIDENCE_INCOMPLETE")
            if any(exit_code != 0 for exit_code in validation_exit_codes):
                return stopped("C2", "VALIDATION_FAILED")
            if not accepted:
                return stopped("C1", "ACCEPTANCE_UNMET")
            record_task_evidence(
                task,
                worktree_root,
                validation_commands,
                validation_exit_codes,
                accepted=True,
                task_dependencies=[],
                task_behavioral_surfaces=[],
                main_advanced_dependencies=[],
                main_advanced_behavioral_surfaces=[],
                full_validation_required=False,
                supplied_project=project_root,
                require_effective_worktree=False,
            )
            performed.append("C5")
            _journal_advance_step(project_root, "evidence", task, "C5")
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
                if error.code == "TASK_STATE_MISSING":
                    recovery_project = _task_state_recovery_project(project_root, task)
                    recovery_identity = resolve_task_identity(
                        recovery_project, task, "existing", allow_archived_queue_links=True,
                    )
                    archived = recovery_identity.task_path.parent.name == "done"
                    recovery = ["cardine", "task", "transition", task, "in_progress"]
                    recovery.extend(["--project", str(recovery_project)])
                    if worktree_root is not None:
                        recovery = ["env", f"CARDINE_WORKTREE_ROOT={worktree_root}", *recovery]
                    commands = [f"cd {shlex.quote(str(recovery_project))} && {shlex.join(recovery)}"]
                    commands.append(shlex.join([
                        "git", "-C", str(recovery_project), "add", "--",
                        (names().tasks_path / f"{task}.json").as_posix(),
                        recovery_identity.task_path.relative_to(recovery_project).as_posix(),
                    ]))
                    commands.append(shlex.join([
                        "git", "-C", str(recovery_project), "commit", "-m", f"Recover task state {task}",
                    ]))
                    if not archived:
                        close = ["cardine", "task", "close", task, "--project", str(recovery_project)]
                        if worktree_root is not None:
                            close = ["env", f"CARDINE_WORKTREE_ROOT={worktree_root}", *close]
                        commands.append(f"cd {shlex.quote(str(recovery_project))} && {shlex.join(close)}")
                        commands.append(shlex.join([
                            "git", "-C", str(recovery_project), "commit", "-m", f"Close task {task}",
                        ]))
                    advance = ["cardine", "worktree", "advance", task, "--project", str(project_root),
                               "--format", "json"]
                    if worktree_root is not None:
                        advance.extend(["--worktree-root", str(worktree_root)])
                    if accepted:
                        advance.append("--accepted")
                    for command, exit_code in zip(validation_commands, validation_exit_codes):
                        advance.extend(["--validation-command", command, "--validation-exit-code", str(exit_code)])
                    for command, exit_code in zip(candidate_commands, candidate_exit_codes):
                        advance.extend(["--candidate-command", command, "--candidate-exit-code", str(exit_code)])
                    commands.append(f"cd {shlex.quote(str(project_root))} && {shlex.join(advance)}")
                    return result("C6", "resolve", commands=commands, stop_code=error.code,
                                  resume=" && ".join(commands), blocked=True)
                return result("C6", "resolve", commands=[resume], stop_code=error.code, resume=resume, blocked=True)
            try:
                staged = stage_task_integration(task, worktree_root, evidence_path, project_root)
            except CardineStop as error:
                return stopped("C6", error.code)
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
                return stopped("C8", error.code)
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

