"""Shared models bindings extracted from the legacy CLI."""

from __future__ import annotations

from cardine.shared.layout import PRODUCT_NAMES

import re
from dataclasses import dataclass
from pathlib import Path


CODEX_PERMISSION_PROFILE = "meridian-worktrees"


CODEX_MANAGED_BEGIN = "# MERIDIAN:BEGIN worktree-permissions v1"


CODEX_MANAGED_END = "# MERIDIAN:END worktree-permissions"


SAFE_PATH_COMPONENT = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")


CANDIDATE_VALIDATION_PATH = PRODUCT_NAMES.candidate_validation_path


WORKTREE_STATE_DIRECTORY = PRODUCT_NAMES.worktree_state_directory


INTEGRATION_LEASE_NAME = PRODUCT_NAMES.integration_lease_name


INTEGRATION_STATE_NAME = PRODUCT_NAMES.integration_state_name


STRUCTURED_TASK_ID = re.compile(
    r"M(?P<milestone>[1-9][0-9]*)-(?P<workstream>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*)-"
    r"(?P<ordinal>00[1-9]|0[1-9][0-9]|[1-9][0-9]{2})"
)


NUMERIC_TASK_ALIAS = re.compile(r"(?:task-)?([0-9]+)", re.IGNORECASE)


CANDIDATE_VALIDATION_OUTCOMES = ("REUSE", "BOUNDED", "FULL")


@dataclass(frozen=True)
class RepositoryIdentity:
    remote_host: str
    owner: str
    repository: str


@dataclass(frozen=True)
class TaskIdentityPolicy:
    version: int
    mode: str


@dataclass(frozen=True)
class TaskIdentityContext:
    """Inputs shared by multiple identity resolutions in one command."""
    policy: TaskIdentityPolicy
    locations: "ProjectLocations"
    authorities: dict[str, "_TaskAuthority"]


@dataclass(frozen=True)
class ResolvedTaskIdentity:
    policy_version: int
    mode: str
    kind: str
    canonical_id: str
    branch_name: str
    artifact_stem: str
    semantic_tuple: dict[str, object] | None
    task_path: Path
    queue_path: Path
    handoff_path: Path
    review_path: Path


    def as_json(self, project_root: Path) -> dict[str, object]:
        project_root = project_root.resolve()

        def display(path: Path) -> str:
            try:
                return str(path.relative_to(project_root))
            except ValueError:
                return str(path)

        return {
            "policy_version": self.policy_version,
            "mode": self.mode,
            "kind": self.kind,
            "canonical_id": self.canonical_id,
            "branch_name": self.branch_name,
            "artifact_stem": self.artifact_stem,
            "semantic_tuple": self.semantic_tuple,
            "task_path": display(self.task_path),
            "queue_path": display(self.queue_path),
            "handoff_path": display(self.handoff_path),
            "review_path": display(self.review_path),
        }


@dataclass(frozen=True)
class ResolvedWorktreeRoot:
    path: Path
    source: str
    config_path: Path


@dataclass(frozen=True)
class CodexConfigurationPlan:
    status: str
    config_path: Path
    worktree_root: Path
    current_model: str
    proposed_text: str | None
    detail: str
    current_text: str | None = None


@dataclass(frozen=True)
class ClaudeConfigurationPlan:
    status: str
    settings_path: Path
    proposed_settings: dict[str, object] | None
    detail: str
    current_text: str | None = None


@dataclass(frozen=True)
class CodexUserRulesPlan:
    path: Path
    status: str
    current_text: str
    proposed_text: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SetupPlan:
    user_rules: CodexUserRulesPlan
    resolution: ResolvedWorktreeRoot
    codex_config: Path
    directory_state: str
    codex_state: str
    codex_plan: CodexConfigurationPlan | None
    codex_detail: str
    claude_state: str
    claude_plan: ClaudeConfigurationPlan | None
    claude_detail: str
    claude_hook_duplicates: tuple[str, ...]
    candidate_validation_state: str
    candidate_validation_path: Path
    candidate_validation_proposal: dict[str, object] | None
    project_declaration_state: str
    project_declaration_path: Path
    project_declaration_proposal: dict[str, object] | None
    task_identity_mode: str | None
    task_identity_state: str
    task_identity_path: Path
    task_identity_proposal: dict[str, object] | None
    task_identity_detail: str
    config_action: str
    framework_root: Path
    skill_links: tuple[tuple[str, Path, str, str], ...]
    skill_links_state: str
    cardine_root_state: str
    changes: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CatalogSurface:
    path: str
    forms: tuple[str, ...]


@dataclass(frozen=True)
class CatalogCapability:
    capability_id: str
    version: int
    workflow_modes: tuple[str, ...]
    self_hosting_eligible: bool
    host_profiles: tuple[tuple[str, str], ...]
    installation_forms: tuple[str, ...]
    managed_surfaces: tuple[CatalogSurface, ...]
    evidence_requirements: tuple[tuple[str, tuple[str, ...]], ...]
    dependencies: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class CatalogProfile:
    profile_id: str
    version: int
    capabilities: tuple[tuple[str, int], ...]
    verification_probe: str
    host_probes: tuple[tuple[str, str], ...]
    workflow_modes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityCatalog:
    catalog_version: int
    capabilities: tuple[CatalogCapability, ...]
    profiles: tuple[CatalogProfile, ...]

    def capability(self, capability_id: str) -> CatalogCapability | None:
        return next(
            (item for item in self.capabilities if item.capability_id == capability_id),
            None,
        )

    def profile(self, profile_id: str) -> CatalogProfile | None:
        return next((item for item in self.profiles if item.profile_id == profile_id), None)


@dataclass(frozen=True)
class EvidenceSnapshot:
    state: str
    evidence: tuple[str, ...]
    not_applicable_rationale: str | None
    verified_at: str | None = None
    verifier_version: str | None = None


@dataclass(frozen=True)
class DeclaredSurface:
    path: str
    form: str


@dataclass(frozen=True)
class CapabilityDeclaration:
    capability_id: str
    required_version: int
    managed_surface: tuple[DeclaredSurface, ...]
    installation: EvidenceSnapshot
    host_activation: tuple[tuple[str, EvidenceSnapshot], ...]
    verification: EvidenceSnapshot


@dataclass(frozen=True)
class CapabilityProfileDeclaration:
    profile_id: str
    profile_version: int
    capabilities: tuple[CapabilityDeclaration, ...]


@dataclass(frozen=True)
class AuditResult:
    status: str
    identity: str
    detail: str


@dataclass(frozen=True)
class ManagedFile:
    source: Path
    target: Path


@dataclass(frozen=True)
class PlanItem:
    file: ManagedFile
    action: str
    detail: str
    problems: tuple[str, ...] = ()
    backup: Path | None = None
    profile_surface: tuple[str, str] | None = None


@dataclass(frozen=True)
class CapabilityMove:
    """One declared relocation of an exact protected marker block."""

    stage: str
    source_path: Path
    source_capability: str
    source_version: int
    source_sha256: str
    target_path: Path
    target_capability: str
    target_version: int
    target_sha256: str
    migration: str


@dataclass(frozen=True)
class ProjectLocations:
    queue: Path
    task_roots: tuple[Path, ...]
    adr_log: Path
    handoff_root: Path
    review_root: Path
    plan: Path
