"""Integration validation scope, decided from measured results and Git facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

DEPENDENCY_MANIFESTS = frozenset({
    "pyproject.toml", "setup.py", "setup.cfg", "poetry.lock", "uv.lock", "pipfile", "pipfile.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.mod", "go.sum",
    "cargo.toml", "cargo.lock", "gemfile", "gemfile.lock", "pom.xml", "build.gradle", "composer.json",
    "composer.lock",
})


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

def is_dependency_manifest(path: str) -> bool:
    name = Path(path).name.lower()
    return name in DEPENDENCY_MANIFESTS or (name.startswith("requirements") and name.endswith(".txt"))

def decide_integration_validation(
    *,
    validation_measured: bool,
    validated_task_commit: str,
    current_task_commit: str,
    validated_base_commit: str,
    current_main_commit: str,
    validated_base_is_task_ancestor: bool,
    validated_task_is_current_ancestor: bool = False,
    relevant_tree_unchanged_after_validation: bool = False,
    task_paths: tuple[str, ...] = (),
    main_advanced_paths: tuple[str, ...] = (),
    pinned_paths: tuple[str, ...] = (),
) -> IntegrationValidationDecision:
    """Choose the integration validation scope from measured results and Git paths.

    Every input is a measured or Git-derived fact; nothing is declared by a
    caller. ``REUSE`` and ``BOUNDED`` both require the mandatory bounded gate
    after the no-commit merge. ``REUSE`` means current ``main`` is the validated
    base. ``BOUNDED`` needs a positive proof of independence; when that proof is
    unavailable the scope is ``FULL``, never a smaller one.
    """
    if not validation_measured:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.BLOCKED,
            "measured task validation is missing or does not cover this source",
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
    if current_main_commit == validated_base_commit:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.REUSE,
            "current main equals the validated base",
        )
    if not task_paths:
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.FULL,
            "the task changed no path, so independence from advanced main cannot be established",
        )
    if any(path in pinned_paths for path in main_advanced_paths):
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.FULL,
            "advanced main changed pinned policy",
        )
    if any(_paths_interact(task_path, main_path) for task_path in task_paths for main_path in main_advanced_paths):
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.FULL,
            "advanced main changed paths that the task also changed",
        )
    if (any(map(is_dependency_manifest, task_paths))
            and any(map(is_dependency_manifest, main_advanced_paths))):
        return IntegrationValidationDecision(
            IntegrationValidationOutcome.FULL,
            "task and advanced main both changed dependency manifests",
        )
    return IntegrationValidationDecision(
        IntegrationValidationOutcome.BOUNDED,
        "advanced main changed no path that the task changed",
    )
