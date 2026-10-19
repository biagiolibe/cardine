from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import CardineError
from pathlib import Path
from cardine.shared.git import _run_git
from cardine.tasks.preflight import execution_preflight
from cardine.lifecycle.execution import execution_source_digest
from cardine.tasks.identity import find_task_file
import json
from cardine.tasks.identity import resolve_task_identity
from cardine.stops.render import stop_error
import subprocess
from cardine.tasks.evidence import validation_commands


EVIDENCE_EVENT_KINDS = ("diagnostic", "captures", "expansions")


def record_validation(project_root: Path, task_id: str, command_id: str, command: str, status: int,
                      binding: dict[str, str] | None = None) -> None:
    path = project_root / names().execution_evidence_path
    state: dict[str, object] = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise CardineError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    entries = list(state.get(canonical_id, []))
    entries.append({"id": command_id, "command": command, "exitStatus": status, **(binding or {})})
    state[canonical_id] = entries
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_validation(project_root: Path, task_id: str, command_id: str) -> int:
    """Execute only the task-declared literal command and retain its outcome."""
    execution_preflight(project_root, task_id)
    text = find_task_file(project_root, task_id).read_text(encoding="utf-8")
    commands = validation_commands(text)
    if command_id not in commands:
        available = ", ".join(sorted(commands)) or "none"
        raise stop_error(
            "VALIDATION_ID_UNDECLARED",
            f"rule: only a task-declared validation ID runs; field checked: Validation in the {task_id} record; "
            f"accepted: {available}; found: {command_id!r}",
        )
    command = commands[command_id]
    head = _run_git(project_root, "rev-parse", "HEAD")
    binding = ({"commit": head.stdout.strip(), "sourceDigest": execution_source_digest(project_root, task_id)}
               if head.returncode == 0 else None)
    completed = subprocess.run(command, shell=True, executable="/bin/bash", cwd=project_root, check=False)
    record_validation(project_root, task_id, command_id, command, completed.returncode, binding)
    print(f"Validation {task_id}/{command_id}: exit {completed.returncode}")
    return completed.returncode


def record_execution_event(
    project_root: Path,
    task_id: str,
    kind: str,
    gap: str,
    criterion: str | None,
    artifact: str | None,
) -> str:
    """Record an evidence gap and its provenance without self-reported counters."""
    if not gap.strip():
        raise stop_error(
            "EXECUTION_EVIDENCE_ARGUMENTS",
            f"rule: evidence is recorded with the gap that justifies it; option checked: --gap; "
            f"accepted: a non-empty string; found: {gap!r}",
        )
    if kind == "captures" and (not criterion or not artifact):
        absent = [name for name, value in (("--criterion", criterion), ("--artifact", artifact)) if not value]
        raise stop_error(
            "EXECUTION_EVIDENCE_ARGUMENTS",
            "rule: captures need provenance; options checked: --criterion and --artifact; "
            "accepted: both non-empty; missing: " + ", ".join(absent),
        )
    path = project_root / names().execution_evidence_path
    state: dict[str, object] = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise CardineError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    events = list(state.get(canonical_id, []))
    event: dict[str, object] = {"kind": kind, "gap": gap}
    if criterion:
        event["criterion"] = criterion
    if artifact:
        event["artifact"] = artifact
    events.append(event)
    state[canonical_id] = events
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"Evidence {task_id}: {kind} recorded"


def record_investigation(
    project_root: Path,
    task_id: str,
    question: str,
    scope: int,
    sources: list[str],
    finding: str,
) -> str:
    """Record a bounded exploration without making a host or worker normative."""
    empty = [option for option, present in (("--question", question.strip()), ("--source", sources), ("--finding", finding.strip())) if not present]
    if empty:
        raise stop_error(
            "EXECUTION_EVIDENCE_ARGUMENTS",
            "rule: an investigation records its question, sources, and finding; options checked: --question, --source, "
            "--finding; accepted: a non-empty value for each; found: missing or empty " + ", ".join(empty),
            resume="rerun cardine execution investigate with --question, --source, and --finding",
        )
    if scope < 1:
        raise stop_error("EXECUTION_EVIDENCE_ARGUMENTS", "--scope must be an integer of 1 or more")
    execution_preflight(project_root, task_id)
    path = project_root / names().execution_evidence_path
    state: dict[str, object] = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise CardineError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    events = list(state.get(canonical_id, []))
    events.append({
        "kind": "investigation",
        "question": question,
        "scope": scope,
        "sources": sources,
        "finding": finding,
    })
    state[canonical_id] = events
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"Investigation {task_id}: recorded"
