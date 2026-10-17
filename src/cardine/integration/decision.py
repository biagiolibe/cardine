"""Integration decision helpers extracted from the legacy CLI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class IntegrationValidationOutcome(str, Enum):
    """Validation scope selected for a serialized task-worktree integration."""

    REUSE = "REUSE"
    BOUNDED = "BOUNDED"
    FULL = "FULL"
    BLOCKED = "BLOCKED"

@dataclass(frozen=True)
class IntegrationValidationDecision:
    outcome: IntegrationValidationOutcome
    reason: str

def _paths_interact(left: str, right: str) -> bool:
    """Return whether normalized repository paths are equal or nested."""
    left_parts = Path(left).parts
    right_parts = Path(right).parts
    shortest = min(len(left_parts), len(right_parts))
    return left_parts[:shortest] == right_parts[:shortest]

def decide_integration_validation(
    *,
    evidence_complete: bool,
    validated_task_commit: str,
    current_task_commit: str,
    validated_base_commit: str,
    current_main_commit: str,
    validated_base_is_task_ancestor: bool,
    full_validation_required: bool,
    validated_task_is_current_ancestor: bool = False,
    relevant_tree_unchanged_after_validation: bool = False,
    interaction_assessment_complete: bool = False,
    task_paths: tuple[str, ...] = (),
    main_advanced_paths: tuple[str, ...] = (),
    task_dependencies: tuple[str, ...] = (),
    main_advanced_dependencies: tuple[str, ...] = (),
    task_behavioral_surfaces: tuple[str, ...] = (),
    main_advanced_behavioral_surfaces: tuple[str, ...] = (),
) -> IntegrationValidationDecision:
    """Choose the integration validation scope from durable evidence.

    ``REUSE`` and ``BOUNDED`` both require the mandatory bounded gate after the
    no-commit merge. ``REUSE`` means current ``main`` is the validated base;
    ``BOUNDED`` records a deterministic independent-change comparison.
    """
    if not evidence_complete:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.BLOCKED,
            "validation evidence is missing or incomplete",
        )
    if validated_task_commit != current_task_commit and not (
        validated_task_is_current_ancestor and relevant_tree_unchanged_after_validation
    ):
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.BLOCKED,
            "the task-relevant tree changed or cannot be proven unchanged after validation",
        )
    if not validated_base_is_task_ancestor:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.BLOCKED,
            "the validated base is not an ancestor of the task commit",
        )
    if full_validation_required:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.FULL,
            "the task explicitly requires full combined-tree validation",
        )
    if current_main_commit == validated_base_commit:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.REUSE,
            "current main equals the validated base",
        )
    if not interaction_assessment_complete:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.BLOCKED,
            "independence from advanced main cannot be established",
        )

    path_interaction = any(
        _paths_interact(task_path, main_path)
        for task_path in task_paths
        for main_path in main_advanced_paths
    )
    dependency_interaction = bool(set(task_dependencies) & set(main_advanced_dependencies))
    behavioral_interaction = bool(
        set(task_behavioral_surfaces) & set(main_advanced_behavioral_surfaces)
    )
    if path_interaction or dependency_interaction or behavioral_interaction:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.FULL,
            "advanced main materially interacts with the declared task surface",
        )
    return IntegrationValidationDecision(
        IntegrationValidationOutcome.BOUNDED,
        "advanced main is independent of the declared task surface",
    )
