"""Render only shared task status for per-turn host briefings, without writes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from cardine.shared.errors import CardineError
from cardine.shared.layout import names
from cardine.tasks.state import STATUSES
from cardine.tasks.status import load_task_status


def render_status_lines(project_root: Path) -> str:
    return _status_lines(load_task_status(project_root))


def _status_lines(model: dict) -> str:
    if model["preset"] is None:
        detail = "; ".join(f"{item['path']}: {item['error']}" for item in model["diagnostics"])
        return f"Status unavailable: {detail}\n"
    totals = model["totals"]
    lines = ["Tasks: " + ", ".join(f"{key}={totals[key]}" for key in (*STATUSES, "total"))]
    startable = [row["id"] for row in model["tasks"] if row["startable"]]
    lines.append("Startable: " + (", ".join(startable) or "none"))
    for status in ("in_progress", "in_review"):
        active = [row["id"] for row in model["tasks"] if row["status"] == status]
        if active:
            lines.append(f"{status.replace('_', ' ').capitalize()}: {', '.join(active)}")
    if model["diagnostics"]:
        lines.append(f"Diagnostics: {len(model['diagnostics'])}; run cardine status")
    return "\n".join(lines) + "\n"


def render_briefing(project_root: Path, payload: str) -> str:
    """Ignore caller prose; only validated product state contributes output."""
    model = load_task_status(project_root)
    prefix = f"Preset: {model['preset']}\n" if model["preset"] is not None else ""
    return prefix + _status_lines(model)


def _payload_project(payload: str, host: str) -> Path | None:
    """Decode the cwd field shared by Claude and Codex turn event payloads.

    These are payload adapters, not evidence that a runtime loaded a user hook.
    Never fall back to the hook process cwd after an invalid payload.
    """
    event = json.loads(payload)
    if not isinstance(event, dict):
        raise ValueError(f"{host} payload must be an object")
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd or "\0" in cwd or not Path(cwd).is_absolute():
        raise ValueError(f"{host} payload requires an absolute cwd")
    current = Path(cwd)
    for candidate in (current, *current.parents):
        if (candidate / names().project_declaration_path).exists():
            return candidate
    return None


def briefing_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--host", choices=("claude", "codex"))
    arguments = parser.parse_args(argv)
    try:
        payload = sys.stdin.read()
        project = arguments.project
        if project is None:
            project = _payload_project(payload, arguments.host or "claude")
            if project is None:
                return 0
        output = render_briefing(project, payload)
    except (CardineError, OSError, ValueError) as error:
        print(f"Briefing configuration error: {error}", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(output)
        sys.stdout.flush()
    except BrokenPipeError:
        # An interrupted consumer cannot publish status or leave a receipt.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(briefing_main())
