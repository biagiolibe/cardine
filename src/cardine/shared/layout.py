"""Names used by project storage and the read-only installation snapshot.

Read ``names()`` at the point of use: a snapshot can select an installation's
layout without changing the product defaults or another execution context.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class ProjectNames:
    project_directory: str = ".cardine"
    worktree_root_directory: str | None = None
    worktree_state_directory: str = "cardine-worktrees"
    integration_lease_name: str = "cardine-integration.lock"
    integration_state_name: str = "cardine-integration.json"
    journal_name: str = "cardine-journal.jsonl"
    journal_rotated_name: str = "cardine-journal.1.jsonl"
    user_configuration_directory: str = "cardine"
    shared_worktrees_context: str = "cardine_shared_worktrees"

    @property
    def manifest_path(self) -> Path:
        return Path(self.project_directory) / "manifest.json"

    @property
    def baselines_path(self) -> Path:
        return Path(self.project_directory) / "baselines"

    @property
    def context_size_config_path(self) -> Path:
        return Path(self.project_directory) / "context-size.json"

    @property
    def task_identity_path(self) -> Path:
        return Path(self.project_directory) / "task-identity.json"

    @property
    def project_declaration_path(self) -> Path:
        return Path(self.project_directory) / "project.json"

    @property
    def candidate_validation_path(self) -> Path:
        return Path(self.project_directory) / "candidate-validation.json"

    def execution_evidence_path(self, canonical_id: str) -> Path:
        """Return the exact evidence file for one resolved, portable task ID."""
        import re
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", canonical_id):
            raise ValueError(f"unsafe evidence task ID: {canonical_id!r}")
        return Path(self.project_directory) / "evidence" / f"{canonical_id}.json"

    @property
    def flow_targets_path(self) -> Path:
        return Path(self.project_directory) / "flow-targets.json"

    @property
    def tasks_path(self) -> Path:
        return Path(self.project_directory) / "tasks"

    @property
    def worktree_root(self) -> Path:
        """Default worktree root, relative to the user's home directory."""
        return Path(self.worktree_root_directory or self.project_directory) / "worktrees"

    @property
    def user_configuration_path(self) -> Path:
        """Configuration path relative to XDG_CONFIG_HOME."""
        return Path(self.user_configuration_directory) / "config.json"


PRODUCT_NAMES = ProjectNames()
_NAMES: ContextVar[ProjectNames] = ContextVar("project_names", default=PRODUCT_NAMES)


def names() -> ProjectNames:
    return _NAMES.get()


@contextmanager
def use(selected_names: ProjectNames) -> Iterator[None]:
    """Select names for this context, restoring them even on failure."""
    token = _NAMES.set(selected_names)
    try:
        yield
    finally:
        _NAMES.reset(token)
