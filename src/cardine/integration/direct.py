"""The ``direct`` landing strategy: lease, no-commit merge, tree-bound validation, finalize."""

from __future__ import annotations

from pathlib import Path

from cardine.integration.evidence import candidate_validation_declaration
from cardine.integration.merge import (
    abort_task_integration, cleanup_task_worktree, finalize_task_integration, stage_task_integration,
)
from cardine.shared.jsonio import _read_json_object
from cardine.tasks.identity import resolve_task_identity
from cardine.worktree.closure_status import closure_status
from cardine.worktree.storage import _lifecycle_paths, _verified_lifecycle_project


class DirectLanding:
    name = "direct"

    def prepare_candidate(self, task_id: str, worktree_root: Path | None, project: Path) -> dict[str, object]:
        from cardine.integration.records import commit_closure_records
        from cardine.integration.candidate import locations_for
        commit_closure_records(locations_for(task_id, project))
        return stage_task_integration(task_id, worktree_root, None, project)

    def readiness(self, task_id: str, worktree_root: Path | None, project: Path) -> tuple[dict[str, object], bool]:
        return closure_status(task_id, worktree_root, project)

    def candidate_needs(self, task_id: str, project: Path) -> dict[str, object]:
        root = _verified_lifecycle_project(project)
        identity = resolve_task_identity(root, task_id, "existing")
        staged = _read_json_object(_lifecycle_paths(root, identity)[2], "staged integration state")
        _state, fragments = candidate_validation_declaration(root, identity.canonical_id)
        return {"version": 1, "task_id": identity.canonical_id, "decision": staged["decision"],
                "candidate_tree": staged["candidate_tree"],
                "required": ["git diff --check", *fragments.get(str(staged["decision"]), ())]}

    def validate_candidate(self, task_id: str, project: Path) -> dict[str, object]:
        from cardine.integration.candidate import run_candidate_validation
        return run_candidate_validation(task_id, project)

    def finalize_landing(self, task_id: str, validation: Path, project: Path) -> dict[str, object]:
        return finalize_task_integration(task_id, validation, project)

    def reconcile_landing(self, task_id: str, project: Path) -> dict[str, object]:
        return abort_task_integration(task_id, project)

    def finish_delivery(self, locations):
        from cardine.integration.cleanup import finish_delivery
        return finish_delivery(locations)

    def cleanup(self, task_id: str, worktree_root: Path | None, project: Path) -> dict[str, object]:
        return cleanup_task_worktree(task_id, worktree_root, project)
