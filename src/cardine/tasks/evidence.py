"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.stops.render import stop_error
import re
from pathlib import Path


def validation_commands(text: str) -> dict[str, str]:
    """Parse creation input; runtime consumers read frozen_validation_commands."""
    section = re.search(r"^## Validation\s*$\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if section is None:
        return {}
    commands: dict[str, str] = {}
    for match in re.finditer(r"^- `([^`]+)`: `([^`]+)`\s*$", section.group(1), re.MULTILINE):
        command_id, command = match.groups()
        commands[command_id] = command
    return commands


def require_named_validation_commands(text: str) -> None:
    """Reject free-form Validation entries when creating or revising a contract."""
    section = re.search(r"^## Validation\s*$\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if section is None:
        return
    entries = [line for line in section.group(1).splitlines() if line.startswith("- ")]
    if entries and len(validation_commands(text)) != len(entries):
        named = re.compile(r"^- `[^`]+`: `[^`]+`\s*$")
        unnamed = [line for line in entries if not named.match(line)]
        raise stop_error(
            "VALIDATION_ENTRY_FORMAT",
            "rule: every entry in the task's ## Validation section must be a named literal command; "
            "accepted form: - `validation-id`: `literal command`; found: "
            + "; ".join(repr(line) for line in unnamed or entries),
        )


def frozen_execution_contract(project_root: Path, task_id: str) -> dict:
    """Require execution inputs frozen at creation, never recover them from prose."""
    from cardine.tasks.state import read_task_state, state_path
    from cardine.tasks.identity import resolve_task_identity
    if not state_path(project_root, task_id).exists():
        task_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    state = read_task_state(project_root, task_id, "single", stop_factory=stop_error, require_contract=True)
    contract = state["contract"]
    if "hostImpact" not in contract:
        from cardine.shared.errors import CardineError
        raise CardineError(f"incomplete contract snapshot (missing hostImpact); run cardine task contract update {task_id}")
    return contract


def frozen_validation_commands(project_root: Path, task_id: str) -> dict[str, str]:
    """Read frozen baseline commands; candidate-only checks run at integration."""
    validation = frozen_execution_contract(project_root, task_id)["validation"]
    return {key: validation["commands"][key] for key in validation["baseline"]}


def require_measured_ledger(project_root, task_id):
    """Verify actual writer coverage; a JSON entry alone grants no progress."""
    from cardine.lifecycle import receipts
    from cardine.tasks.state import read_task_state
    from cardine.shared.layout import names
    state = read_task_state(project_root, task_id, 'single', stop_factory=stop_error, require_contract=True)
    name = names().execution_evidence_path(task_id).as_posix()
    path = receipts.safe_path(project_root, name)
    if path.exists() and not path.is_file():
        raise IsADirectoryError(str(path))
    covered = any(name in receipt['outputs'] for receipt in state.get('run', {}).get('receipts', []))
    if path.exists() and not covered:
        from cardine.shared.errors import CardineError
        raise CardineError('validation ledger lacks a measured writer receipt')
    receipts.verify_receipts(project_root, state, artifact_names={name})
    return state
