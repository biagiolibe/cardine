"""Helpers extracted from the legacy CLI; see the module split plan."""

from __future__ import annotations

from pathlib import Path

from cardine.shared.errors import CardineError


def detect_mode(project_root: Path) -> str:
    workflow = project_root / "PROJECT_WORKFLOW.md"
    if not workflow.is_file():
        raise CardineError(
            "cannot detect workflow mode: PROJECT_WORKFLOW.md is missing; pass --mode explicitly"
        )
    text = workflow.read_text(encoding="utf-8")
    is_governed = "GOVERNED_SDD" in text
    is_lean = "LEAN_DELIVERY" in text
    if is_governed and is_lean:
        raise CardineError(
            "cannot detect workflow mode: PROJECT_WORKFLOW.md mentions both mode locks; pass --mode explicitly"
        )
    if is_governed:
        return "governed-sdd"
    if is_lean:
        return "lean-delivery"
    raise CardineError(
        "cannot detect workflow mode: PROJECT_WORKFLOW.md has no recognized mode lock; pass --mode explicitly"
    )
