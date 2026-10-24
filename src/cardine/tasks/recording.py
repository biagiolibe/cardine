from __future__ import annotations

from cardine.shared.layout import names

from cardine.shared.errors import CardineError
from pathlib import Path
from cardine.shared.git import _run_git
from cardine.tasks.preflight import execution_preflight
from cardine.lifecycle.execution import execution_source_digest
import json
from cardine.tasks.identity import resolve_task_identity
from cardine.stops.render import stop_error
import subprocess
from cardine.tasks.evidence import frozen_validation_commands


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
    from cardine.lifecycle.execution import enforce_execution_scope
    enforce_execution_scope(project_root, task_id)
    execution_preflight(project_root, task_id)
    commands = frozen_validation_commands(project_root, task_id)
    if command_id not in commands:
        available = ", ".join(sorted(commands)) or "none"
        raise stop_error(
            "VALIDATION_ID_UNDECLARED",
            f"rule: only a task-declared validation ID runs; field checked: validation.commands in the {task_id} frozen contract; "
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
