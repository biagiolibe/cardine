"""Landing strategy interface: how a validated task candidate reaches ``main``.

The run engine resolves a task's frozen ``landingMode`` to one strategy and
speaks only this interface, so a later strategy changes neither the engine, the
task statuses nor the stable run output. A preset never selects a strategy.
Only ``direct`` ships in 1.0; any other mode is refused here without a forge call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cardine.shared.errors import CardineError


class LandingStrategy(Protocol):
    """Receipts and needs are plain structured dictionaries, as the resolver reads them."""

    name: str

    def prepare_candidate(self, task_id: str, worktree_root: Path | None, project: Path) -> dict[str, object]:
        """Stage the exact candidate, or recover or refuse an interrupted one."""

    def readiness(self, task_id: str, worktree_root: Path | None, project: Path) -> tuple[dict[str, object], bool]:
        """Read, without changing anything, the next landing step and any stop."""

    def candidate_needs(self, task_id: str, project: Path) -> dict[str, object]:
        """Name the validation the staged candidate requires; executing it is the engine's step."""

    def validate_candidate(self, task_id: str, project: Path) -> dict[str, object]:
        """Execute the frozen commands and return measured tree-bound progress."""

    def finalize_landing(self, task_id: str, validation: Path, project: Path) -> dict[str, object]:
        """Land the candidate once, only after its tree-bound validation."""

    def reconcile_landing(self, task_id: str, project: Path) -> dict[str, object]:
        """Restore only the caller-owned candidate and lease after a failure or interruption."""

    def cleanup(self, task_id: str, worktree_root: Path | None, project: Path) -> dict[str, object]:
        """Remove what the landing made removable, never unmerged or foreign work."""


def landing_for(mode: object) -> LandingStrategy:
    """Resolve a frozen ``landingMode`` to its strategy."""
    if mode != "direct":
        raise CardineError(f"landing mode {mode!r} is not supported; only direct is supported in 1.0")
    from cardine.integration.direct import DirectLanding
    return DirectLanding()
