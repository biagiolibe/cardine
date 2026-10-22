#!/usr/bin/env python3
"""Report where an adopted project's declared queue lives. Read-only.

The queue is a generated view: `cardine status --write` renders it from the
validated task states. This script no longer rewrites queue text; it only
resolves the declared queue path for installation tooling.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

def resolve_queue(project: Path, cardine: str | None) -> Path:
    """Ask the Cardine CLI for the declared queue; fall back to tasks/QUEUE.md."""
    candidates = [cardine] if cardine else []
    found = shutil.which("cardine")
    if found:
        candidates.append(found)
    for executable in candidates:
        try:
            result = subprocess.run(
                [executable, "locations", "--project", str(project), "--field", "queue"],
                capture_output=True, text=True, check=False, timeout=30,
            )
        except OSError:
            continue
        relative = result.stdout.strip().splitlines()
        if result.returncode == 0 and relative:
            return project / relative[-1].strip()
    return project / "tasks" / "QUEUE.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("projects", nargs="+", type=Path)
    parser.add_argument("--cardine", help="path to bin/cardine used to resolve the queue location")
    args = parser.parse_args()
    status = 0
    for project in args.projects:
        project = project.resolve()
        queue = resolve_queue(project, args.cardine)
        if not queue.is_file():
            print(f"== {project}: no queue at {queue.relative_to(project)}, skipped")
            status = 1
            continue
        print(f"== {project} ({queue.relative_to(project)}): unchanged; regenerate with `cardine status --write`")
    return status


if __name__ == "__main__":
    sys.exit(main())
