"""Synthetic Meridian projects for the conversion reader tests.

Each project is plain files in a disposable directory: no Git, no home
directory, no subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

LEAN_HEADER = "| Status | ID | Title |\n|---|---|---|\n"
GOVERNED_HEADER = "| Status | ID | Title | Review |\n|---|---|---|---|\n"


def queue_text(rows: list[tuple[str, ...]], *, governed: bool = False) -> str:
    """Render a queue table from `(status, id, title[, review])` tuples."""
    lines = [GOVERNED_HEADER if governed else LEAN_HEADER]
    for status, *rest in rows:
        cells = rest if governed else rest[:2]
        lines.append(f"| `{status}` | " + " | ".join(cells) + " |\n")
    return "# Queue\n\n" + "".join(lines)


def write_meridian_project(
    root: Path,
    *,
    governed: bool = False,
    queue: str | None = None,
    adr_log: str | None = None,
    adr_path: str = "docs/ARCHITECTURE_DECISIONS.md",
    declaration: dict[str, object] | None = None,
    identity: dict[str, object] | None = None,
    candidate: dict[str, object] | None = None,
    flow_targets: dict[str, object] | None = None,
    workflow_lock: str | None = None,
) -> Path:
    """Write a minimal Meridian project under `root` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    meridian = root / ".meridian"
    meridian.mkdir(exist_ok=True)
    (meridian / "manifest.json").write_text(json.dumps({"frameworkVersion": "1.4.1"}), encoding="utf-8")
    lock = workflow_lock if workflow_lock is not None else ("GOVERNED_SDD" if governed else "LEAN_DELIVERY")
    (root / "PROJECT_WORKFLOW.md").write_text(f"# Workflow\n\nThis file selects `{lock}`.\n", encoding="utf-8")
    for name, value in (("project.json", declaration), ("task-identity.json", identity),
                        ("candidate-validation.json", candidate), ("flow-targets.json", flow_targets)):
        if value is not None:
            (meridian / name).write_text(json.dumps(value), encoding="utf-8")
    if queue is not None:
        (root / "tasks").mkdir(exist_ok=True)
        (root / "tasks" / "QUEUE.md").write_text(queue, encoding="utf-8")
    if adr_log is not None:
        target = root / adr_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(adr_log, encoding="utf-8")
    return root
