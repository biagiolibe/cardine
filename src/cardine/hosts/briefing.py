"""Render the per-turn briefing from the shared task status service.

The caller supplies the hook's existing payload. Its queue block is replaced by
the preset, totals, and startable task IDs that `cardine status` reports from
validated task state, so the briefing is correct even when the queue files are
empty. Every other payload byte is preserved. The adapter reads no queue rows.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from cardine.shared.errors import CardineError
from cardine.tasks.state import STATUSES
from cardine.tasks.status import load_task_status
from cardine.templates.mode import resolve_preset


LEGACY_QUEUE_HEADERS = frozenset({
    # MERIDIAN-INSTALLATION-CHECK: headings emitted by the frozen copied hook.
    "[Meridian Lean Delivery Queue]", "[Meridian Governed Queue]",
})


def _without_queue_block(payload: str) -> str:
    """Drop each queue block: its heading and the lines up to the next block heading."""
    kept: list[str] = []
    skipping = False
    for line in payload.splitlines(keepends=True):
        if line.startswith("["):
            skipping = line.rstrip("\r\n") in LEGACY_QUEUE_HEADERS
        if not skipping:
            kept.append(line)
    return "".join(kept)


def render_status_lines(project_root: Path) -> str:
    model = load_task_status(project_root)
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
    """Resolve policy before rendering, preserving all non-queue payload bytes."""
    preset = resolve_preset(project_root)
    return f"Preset: {preset}\n{render_status_lines(project_root)}{_without_queue_block(payload)}"


def briefing_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    try:
        output = render_briefing(arguments.project, sys.stdin.read())
    except CardineError as error:
        print(f"Briefing configuration error: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(briefing_main())
