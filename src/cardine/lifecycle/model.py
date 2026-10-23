"""Immutable inputs to the read-only run resolver.

Facts are supplied by receipt-verifying adapters, never by caller phase flags or
Markdown. They describe current identities, not proof of same-user authorship.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

STEPS = ("contract", "worktree", "implementation", "validation", "review", "candidate", "landing")
OUTCOMES = ("progress", "next", "waiting", "iterate", "blocked", "done")


@dataclass(frozen=True)
class RunLocations:
    task_id: str
    primary: Path
    common_dir: Path
    root: Path
    worktree: Path


@dataclass(frozen=True)
class Guardrail:
    code: str
    detail: str
    step: str = "contract"


@dataclass(frozen=True)
class WorkRequest:
    role: str
    worktree: Path
    snapshot_digest: str
    expected_surface: tuple[str, ...]
    acceptance_references: tuple[str, ...]
    validation_references: tuple[str, ...]
    delivery_receipt_requirements: tuple[str, ...]

    def __post_init__(self):
        if self.role not in ("implementer", "reviewer") or not self.worktree.is_absolute():
            raise ValueError("work requires a known role and absolute worktree")

    def as_json(self):
        return dict(role=self.role, worktree=str(self.worktree), contract_digest=self.snapshot_digest,
                    expected_surface=list(self.expected_surface),
                    acceptance_references=list(self.acceptance_references),
                    validation_references=list(self.validation_references),
                    delivery_receipt_requirements=list(self.delivery_receipt_requirements))


@dataclass(frozen=True)
class RunFacts:
    """Already verified observations for one coherent contract/source snapshot.

    Adapters must invalidate delivery/validation/approval when source changes,
    and candidate validation when the candidate changes. RE1b and later rows
    provide those adapters; this model does not verify or persist receipts.
    """
    task_id: str
    project: Path
    status: str
    contract_ready: bool = False
    worktree_ready: bool = False
    implementation_delivered: bool = False
    validation_passed: bool = False
    review_required: bool = True
    review_approved: bool = False
    candidate_validated: bool = False
    landing_complete: bool = False
    cleanup_pending: bool = False
    pending_step: str | None = None
    guardrail: Guardrail | None = None
    validation_failed: bool = False
    review_changes_requested: bool = False
    review_pending: bool = False
    ci_pending: bool = False
    implementation_work: WorkRequest | None = None
    review_work: WorkRequest | None = None

    def __post_init__(self):
        if self.status not in ("queued", "in_progress", "in_review", "done", "cancelled"):
            raise ValueError("unknown task status")
        if not self.project.is_absolute() or not self.task_id:
            raise ValueError("resolved task and absolute primary project are required")
        if self.pending_step is not None and self.pending_step not in STEPS:
            raise ValueError("unknown reconciliation step")
        if self.guardrail is not None and self.guardrail.step not in STEPS:
            raise ValueError("unknown guardrail step")
        for request, role in ((self.implementation_work, "implementer"), (self.review_work, "reviewer")):
            if request is not None and request.role != role:
                raise ValueError("work request role mismatch")
