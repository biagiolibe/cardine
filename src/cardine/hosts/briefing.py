"""Add the configured preset to an existing host briefing payload.

This adapter owns display only. The caller supplies the hook's existing
payload; task counts and startable-task selection remain with that producer.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from cardine.shared.errors import CardineError
from cardine.templates.mode import resolve_preset


LEGACY_QUEUE_HEADERS = frozenset({
    # MERIDIAN-INSTALLATION-CHECK: headings emitted by the frozen copied hook.
    "[Meridian Lean Delivery Queue]", "[Meridian Governed Queue]",
})


def render_briefing(project_root: Path, payload: str) -> str:
    """Resolve policy before rendering, preserving all non-heading payload bytes."""
    preset = resolve_preset(project_root)
    body = "".join(
        line for line in payload.splitlines(keepends=True)
        if line.rstrip("\r\n") not in LEGACY_QUEUE_HEADERS
    )
    return f"Preset: {preset}\n{body}"


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
