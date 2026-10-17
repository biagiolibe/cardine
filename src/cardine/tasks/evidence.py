"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from cardine.stops.render import stop_error
import re


def validation_commands(text: str) -> dict[str, str]:
    """Read named, literal validation commands from one task's Validation block."""
    section = re.search(r"^## Validation\s*$\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if section is None:
        return {}
    commands: dict[str, str] = {}
    for match in re.finditer(r"^- `([^`]+)`: `([^`]+)`\s*$", section.group(1), re.MULTILINE):
        command_id, command = match.groups()
        commands[command_id] = command
    return commands


def require_named_validation_commands(text: str) -> None:
    """Reject free-form Validation entries that the execution runner cannot run."""
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
