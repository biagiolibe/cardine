#!/usr/bin/env python3
"""Versioned, deterministic upgrades for Meridian-generated projects."""

from __future__ import annotations

import argparse
import ast
import copy
import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import statistics
import stat
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


# Resolve both adapters and package modules from this executable checkout.
if str(Path(__file__).resolve().parents[1] / "src") not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cardine.templates.protocol import (  # noqa: E402
    check_protocol_compatibility,
)
from cardine.hosts.claude import (  # noqa: E402
    CLAUDE_PROJECT_ALLOWLIST,
    CLAUDE_PROJECT_DENYLIST,
    plan_claude_project_allowlist,
    apply_claude_project_allowlist,
    claude_hook_duplicate_advisories,
)
from cardine.shared.budget import (  # noqa: E402
    BUDGET_PATH,
    BUDGET_STATE_NAME,
    BUDGET_KINDS,
    EVIDENCE_EVENT_KINDS,
    BUDGET_DEFAULT_CAPS,
    BUDGET_FIELD_NAMES,
    budget_state_path,
    tracked_budget_state,
    legacy_budget_migration_needed,
    migrate_budget_state,
    load_budget_state,
    write_budget_state,
)
from cardine.shared.project import (  # noqa: E402
    _LEGACY_LOCATION_WARNING_PROJECTS,
    _safe_project_path,
    parse_project_declaration,
    read_project_declaration,
)
from cardine.templates.catalog import (  # noqa: E402
    manifest_workflow_mode,
    _parse_catalog_surface,
    parse_capability_catalog,
    load_capability_catalog,
    _parse_evidence_snapshot,
    parse_capability_profiles,
)
from cardine.shared import project as shared_project  # noqa: E402
from cardine.shared.paths import SCRIPTS_ROOT  # noqa: E402
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from cardine.tasks.state import TaskStateInvalid, machine, read_task_state, state_path, validate_task_state  # noqa: E402
from cardine.shared.console_workflow import latest_review_verdict, record_review  # noqa: E402
from cardine.integration.projections import (  # noqa: E402
    _completed_task_row,
    _queue_task_rows,
    _QUEUE_TABLE_DIVIDER,
    _QUEUE_TASK_ROW,
    _QUEUE_ARCHIVE_HEADER,
    _GOVERNED_QUEUE_ARCHIVE_HEADER,
    _GOVERNED_QUEUE_TASK_ROW,
    _GOVERNED_QUEUE_STATUSES,
    _MARKDOWN_HEADING,
    _governed_completion_error,
    _governed_completion_row,
    _queue_section_ranges,
    _queue_section_completion,
    _STATE_TERMINAL_STATUSES,
    QueueStateResolver,
    _queue_state_resolver,
    _queue_unidentified_tables,
    _queue_section_decisions,
    _archive_completed_queue_sections,
    _queue_archival_warnings,
    _relink_archived_task_row,
    _apply_task_completion_rows,
)
from cardine.release.update import (  # noqa: E402
    fetch_latest_release,
    run_self_update,
    claude_user_settings_path,
    plugin_marketplace_ref,
    plugin_ref_report,
    run_self_check,
)
from cardine.review.verdict import (  # noqa: E402
    record_review_verdict,
    _review_verdict_projection,
    _review_attempt_text,
)
from cardine.shared.context import (  # noqa: E402
    _context_path_references,
    _context_relative_references,
    _context_phase_reads,
    _context_router,
    _context_routed_workflow,
    _context_file_record,
    _context_configuration,
    _context_threshold,
    context_router_files,
    context_size_report,
    format_context_size_report,
)
from cardine.shared.journal import (  # noqa: E402
    JOURNAL_NAME,
    JOURNAL_ROTATED_NAME,
    JOURNAL_MAX_BYTES,
    JOURNAL_VERSION,
    JOURNALED_WORKTREE_COMMANDS,
    JOURNALED_INTEGRATE_COMMANDS,
    LifecycleJournalEntry,
    append_journal_line,
)
from cardine.integration.decision import (  # noqa: E402
    IntegrationValidationOutcome,
    IntegrationValidationDecision,
    _paths_interact,
    decide_integration_validation,
)
from cardine.shared.constants import (  # noqa: E402
    MANIFEST_PATH,
    VALIDATION_EVIDENCE_SCHEMA_PATH,
    VALIDATION_EXIT_PASSED,
    VALIDATION_EXIT_PENDING,
    VALIDATION_EXIT_FAILED,
    CAPABILITY_CATALOG_VERSION,
    CAPABILITY_CATALOG_PATH,
    BASELINES_PATH,
    ADOPTION_REVIEW_PATH,
    PROTOCOL_VERSION,
    LEGACY_PROTOCOL_VERSION,
    WORKFLOW_MODES,
    INSTALLATION_FORMS,
    STRICT_DIGEST_PROFILES,
    PROJECT_EDITABLE_MANAGED_PATHS,
    INSTALLATION_STATES,
    HOST_ACTIVATION_STATES,
    VERIFICATION_STATES,
    AUDIT_STATES,
    LATEST_RELEASE_URL,
    LATEST_RELEASE_TIMEOUT_SECONDS,
    LATEST_RELEASE_RESPONSE_LIMIT,
    SELF_CHECK_UPDATE_AVAILABLE,
    SELF_CHECK_UNKNOWN,
    CAPABILITY_DECLARATION_REQUIRED_PROTOCOL,
    ADOPTION_VERDICTS,
    ADOPTION_RETRY_LIMIT,
    CAPABILITY_MARKER,
    MARKED_BLOCK,
    ENTRY_ROUTER_PATH,
    ENTRY_ROUTER_MAP_PATH,
    ENTRY_ROUTER_OVERLAYS,
    ENTRY_ROUTER_BUDGET_BYTES,
    ENTRY_ROUTER_ROUTES,
    ENTRY_ROUTER_SAFEGUARDS,
    CONTEXT_SIZE_CONFIG_PATH,
    CONTEXT_SIZE_POLICY_PATH,
    CONTEXT_PHASE_READS_BLOCK,
    CONTEXT_PHASE_READ_LINE,
    CONTEXT_SIZE_ROLES,
    USAGE_HOSTS,
    USAGE_PRIVACY_BOUNDARY,
    USAGE_ADAPTER_NOTES,
    TASK_IDENTITY_PATH,
    PROJECT_DECLARATION_PATH,
)
from cardine.shared.errors import (  # noqa: E402
    MeridianError,
    InternalStopError,
    MeridianStop,
)
from cardine.shared.hashing import (  # noqa: E402
    sha256,
)
from cardine.shared.text import (  # noqa: E402
    read_task_field,
    HEADING_LINE,
    extract_heading_block,
)
from cardine.release.version import (  # noqa: E402
    SemVer,
    _SEMVER_IDENTIFIER,
    _SEMVER_PATTERN,
    parse_semver,
    read_raw_version,
    require_release_version,
    read_version,
    version_key,
    semver_precedence_key,
    release_kind_from_body,
)
from cardine.shared.git import (  # noqa: E402
    git_output,
    canonical_git_common_dir,
    _run_git,
    _SHARED_WORKTREES,
    parse_worktree_records,
    shared_worktree_records,
    _git_worktrees,
    canonical_project_root,
    primary_project_root,
    TASK_BRANCH_OPEN_STATUSES,
    current_branch,
)
from cardine.shared.jsonio import (  # noqa: E402
    _write_json_atomic,
    _read_json_object,
)
from cardine.shared.models import (  # noqa: E402
    CODEX_PERMISSION_PROFILE,
    CODEX_MANAGED_BEGIN,
    CODEX_MANAGED_END,
    SAFE_PATH_COMPONENT,
    CANDIDATE_VALIDATION_PATH,
    WORKTREE_STATE_DIRECTORY,
    INTEGRATION_LEASE_NAME,
    INTEGRATION_STATE_NAME,
    STRUCTURED_TASK_ID,
    NUMERIC_TASK_ALIAS,
    CANDIDATE_VALIDATION_OUTCOMES,
    RepositoryIdentity,
    TaskIdentityPolicy,
    TaskIdentityContext,
    ResolvedTaskIdentity,
    ResolvedWorktreeRoot,
    CodexConfigurationPlan,
    ClaudeConfigurationPlan,
    CodexUserRulesPlan,
    SetupPlan,
    CatalogSurface,
    CatalogCapability,
    CatalogProfile,
    CapabilityCatalog,
    EvidenceSnapshot,
    DeclaredSurface,
    CapabilityDeclaration,
    CapabilityProfileDeclaration,
    AuditResult,
    ManagedFile,
    PlanItem,
    Capability,
    CapabilityMove,
    ReviewRecord,
    AdoptionState,
    ProjectLocations,
)
from cardine.shared.usage import (  # noqa: E402
    _usage_counter,
    _claude_usage_call,
    _usage_start,
    _usage_session,
    _codex_usage_session,
    _claude_usage_session,
    usage_report,
    format_usage_report,
)

from cardine.shared.validation import (  # noqa: E402
    _required_object,
    _required_string,
    _required_positive_integer,
    _required_string_list,
    _repository_relative_path,
)

from cardine.stops.registry import (  # noqa: E402
    STOP_REGISTRY_PATH,
    STOP_REGISTRY_VERSION,
    STOP_REGISTRY_FIELDS,
    load_stop_registry,
)

from cardine.templates.markers import (  # noqa: E402
    marker_blocks,
    marker_block_sha256,
    exact_marker_matches,
    find_capability_marker_version,
    LEGACY_CAPABILITY_EVIDENCE,
    capability_ids_in_template,
    extract_marker_block,
    extract_marked_block,
    marker_pairs,
    append_only_new_markers,
    CLAUDE_AGENTS_POINTER_MARKER,
    is_agents_pointer,
    agents_pointer_satisfies_claude,
    agents_pointer_can_follow_upgrade,
    reflowed_marker_normalization,
    deduplicate_identical_template_markers,
    remove_retired_markers,
)

from cardine.templates.mode import (  # noqa: E402
    detect_mode,
)

from cardine.templates.migrations import (  # noqa: E402
    migration_ids,
    first_retirement_migration,
    capped_target_version,
    migration_record_paths,
    validate_adopt_existing_paths,
    adopt_existing_paths,
    migration_capability_entries,
    migration_capability_removals,
    migration_restructures,
    pending_restructured_markers,
    pending_wrapped_capabilities,
    drop_restructured_marker_blocks,
    restructured_marker_edits,
    project_sections,
    restructured_text,
    migration_capability_moves,
    capability_requirements,
    retired_capability_ids,
    pending_capability_removals,
)

from cardine.tasks.identity import (  # noqa: E402
    _safe_component,
    canonical_task_id,
    task_identity_json,
    resolve_project_locations,
    _TaskAuthority,
    parse_task_identity_policy,
    read_task_identity_policy,
    _task_record_id,
    _clean_queue_id,
    _task_authorities,
    _numeric_alias_key,
    _authority_matches,
    _identity_names,
    _check_branch_name,
    _identity_derivations,
    resolve_task_identity,
    task_identity_context,
    next_milestone_task_identity,
    find_task_file,
)

from cardine.templates.files import (  # noqa: E402
    latest_migration_to,
    manifest_baseline_version,
    managed_files_for_workflow,
    managed_files,
    marker_declaring_migrations,
    strip_marker_block,
    capped_managed_files,
    detect_source_version,
)

from cardine.templates.router import (  # noqa: E402
    entry_router_overlay,
    render_entry_router,
    entry_router_outputs,
    project_uses_entry_router,
    entry_router_trigger_requirements,
    audit_entry_router,
)

from cardine.shared.authority import (  # noqa: E402
    find_adr_log,
    adr_title_matcher,
    adr_show,
    ADR_HEADING_ID,
    ADR_LIKE_HEADING,
    ADR_STATUS_LINE,
    adr_entries,
    adr_list,
    extract_spec_heading,
    authority_entries,
    SPEC_HEADING_CITATION,
    resolve_authority_entry,
    context_authority,
)
from cardine.hosts.codex import (  # noqa: E402
    CODEX_USER_RULES,
    plan_codex_user_rules,
    apply_codex_user_rules,
    _toml_quote,
    _codex_managed_block,
    _replace_codex_managed_block,
    _without_top_level_default_permissions,
    _codex_expected_profile,
    _codex_profile_divergence,
    _codex_header_patterns,
    _codex_markers_intact,
    _without_codex_profile_text,
    _plan_codex_ownership_repair,
    _plan_codex_ownership_repair_and_root_replacement,
    plan_codex_configuration,
    print_codex_configuration_plan,
    _write_exclusive_backup,
    _unused_repair_backup,
    apply_codex_configuration,
)
from cardine.stops.render import (  # noqa: E402
    _task_state_recovery_project,
    stop_resume,
    format_stop,
    stop_error,
)
from cardine.templates.manifest import (  # noqa: E402
    validate_manifest,
    load_manifest,
    canonical_manifest,
    write_manifest,
)
from cardine.templates.marker_history import (  # noqa: E402
    declared_capability_moves,
    pending_migration_establishes_move_source,
    capability_presence_map,
    retired_capability_versions,
)
from cardine.worktree.storage import (  # noqa: E402
    _verified_lifecycle_project,
    user_configuration_path,
    _read_user_configuration,
    resolve_worktree_root,
    _effective_worktree_root,
    _lifecycle_paths,
    _merge_head_path,
    _branch_commit,
    lifecycle_started_at,
    _dirty_summary,
    _proven_stale_base,
)
from cardine.tasks.evidence import (  # noqa: E402
    validation_commands,
    require_named_validation_commands,
)
from cardine.templates.marker_audit import (  # noqa: E402
    audit_capability_markers,
    HEADING,
    marker_headings,
    audit_duplicate_headings,
    audit_capability_moves,
)
from cardine.templates.migration_audit import (  # noqa: E402
    validate_capability_moves,
    removals_for_managed_file,
)
from cardine.worktree.paths import (  # noqa: E402
    _normalized_local_repository_name,
    repository_identity,
    _task_worktree_path_for_identity,
    handoff_worktree_value,
    task_worktree_path,
    validate_worktree_collision,
)
from cardine.hosts.skills import (  # noqa: E402
    _directory_setup_state,
    CODEX_SKILL_NAMES,
    _framework_skill_links,
    _aggregate_skill_state,
    _stale_codex_skill_warnings,
    _setup_codex_state,
    codex_profile_root_mismatch,
)


def _validation_reason(reasons: list[str], condition: bool, reason: str) -> None:
    if not condition:
        reasons.append(reason)


def validation_evidence_reasons(record: object) -> list[str]:
    """Return schema-shaped errors without running a project command."""
    if not isinstance(record, dict):
        return ["record: must be an object"]
    reasons: list[str] = []
    required = ("version", "task_id", "status", "level", "commit", "tree", "command", "tests_run", "produced_at")
    for field in required:
        _validation_reason(reasons, field in record, f"{field}: is required")
    _validation_reason(reasons, record.get("version") == 1, "version: must be 1")
    _validation_reason(reasons, isinstance(record.get("task_id"), str) and bool(record.get("task_id")), "task_id: must be a non-empty string")
    _validation_reason(reasons, record.get("status") in {"running", "unavailable", "failed", "passed"}, "status: unknown value")
    _validation_reason(reasons, record.get("level") in {"T1_CI", "T2_SHARDED", "T3_ATTESTED"}, "level: unknown value")
    for field in ("commit", "tree", "produced_at"):
        _validation_reason(reasons, isinstance(record.get(field), str) and bool(record.get(field)), f"{field}: must be a non-empty string")
    _validation_reason(reasons, isinstance(record.get("command"), list) and all(isinstance(item, str) and item for item in record.get("command", [])), "command: must be an array of non-empty strings")
    _validation_reason(reasons, isinstance(record.get("tests_run"), int) and not isinstance(record.get("tests_run"), bool), "tests_run: must be an integer")
    status = record.get("status")
    if status == "running":
        for field in ("started_at", "log"):
            _validation_reason(reasons, isinstance(record.get(field), str) and bool(record.get(field)), f"{field}: is required for running")
    elif status == "unavailable":
        _validation_reason(reasons, isinstance(record.get("reason"), str) and bool(record.get("reason")), "reason: is required for unavailable")
    elif status in {"failed", "passed"}:
        _validation_reason(reasons, isinstance(record.get("exit_code"), int) and not isinstance(record.get("exit_code"), bool), f"exit_code: is required for {status}")
    level = record.get("level")
    if level == "T1_CI":
        ci = record.get("ci")
        _validation_reason(reasons, isinstance(ci, dict), "ci: is required for T1_CI")
        if isinstance(ci, dict):
            for field in ("run_id", "run_url", "workflow", "conclusion", "head_sha"):
                _validation_reason(reasons, isinstance(ci.get(field), str) and bool(ci.get(field)), f"ci.{field}: is required for T1_CI")
    elif level == "T2_SHARDED":
        shards = record.get("shards")
        _validation_reason(reasons, isinstance(shards, list) and bool(shards), "shards: is required for T2_SHARDED")
        for field in ("total", "digest"):
            _validation_reason(reasons, field in record, f"{field}: is required for T2_SHARDED")
        if isinstance(shards, list):
            for number, shard in enumerate(shards, 1):
                _validation_reason(reasons, isinstance(shard, dict), f"shards[{number}]: must be an object")
                if isinstance(shard, dict):
                    for field in ("index", "count", "exit_code", "tests_run", "digest", "total"):
                        _validation_reason(reasons, field in shard, f"shards[{number}].{field}: is required")
    elif level == "T3_ATTESTED":
        _validation_reason(reasons, record.get("attested_by") == "developer", "attested_by: must be developer for T3_ATTESTED")
        _validation_reason(reasons, isinstance(record.get("attested_on"), str) and bool(record.get("attested_on")), "attested_on: is required for T3_ATTESTED")
        _validation_reason(reasons, isinstance(record.get("statement"), str) and bool(record.get("statement").strip()), "statement: is required for T3_ATTESTED")
    return reasons


def check_validation_evidence(record_path: Path, project_root: Path, expected_commit: str | None) -> tuple[dict[str, object], int]:
    """Read an external validation attestation using Git plumbing only."""
    reasons: list[str] = []
    try:
        schema = json.loads((Path(__file__).resolve().parents[1] / VALIDATION_EVIDENCE_SCHEMA_PATH).read_text(encoding="utf-8"))
        if not isinstance(schema, dict) or schema.get("$id") != "https://meridian.local/schemas/validation-evidence-v1.schema.json":
            reasons.append("schema: validation-evidence-v1 is invalid")
    except (OSError, json.JSONDecodeError) as error:
        reasons.append(f"schema: {error}")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        record = None
        reasons.append(f"record: {error}")
    reasons.extend(validation_evidence_reasons(record))
    if not isinstance(record, dict):
        return {"status": "VALIDATION_FAILED", "level": None, "reasons": reasons}, VALIDATION_EXIT_FAILED
    status, level = record.get("status"), record.get("level")
    if status == "running" and not reasons:
        return {"status": "VALIDATION_RUNNING", "level": level, "reasons": []}, VALIDATION_EXIT_PENDING
    if status == "unavailable" and not reasons:
        return {"status": "VALIDATION_UNAVAILABLE", "level": level, "reasons": []}, VALIDATION_EXIT_PENDING
    if status != "passed":
        reasons.append("status: is not passed")
    try:
        branch = resolve_task_identity(project_root, str(record.get("task_id", "")), "existing").branch_name
        target = expected_commit or git_output(project_root, "rev-parse", branch)
        resolved = git_output(project_root, "rev-parse", f"{record.get('commit', '')}^{{commit}}")
        _validation_reason(reasons, resolved == target, "commit: does not equal the expected commit")
        _validation_reason(reasons, git_output(project_root, "rev-parse", f"{resolved}^{{tree}}") == record.get("tree"), "tree: does not equal commit tree")
    except MeridianError as error:
        reasons.append(f"commit: {error}")
    _validation_reason(reasons, record.get("exit_code") == 0, "exit_code: must be 0")
    _validation_reason(reasons, isinstance(record.get("tests_run"), int) and record.get("tests_run", 0) > 0, "tests_run: must be above 0")
    if level == "T1_CI" and isinstance(record.get("ci"), dict):
        ci = record["ci"]
        _validation_reason(reasons, ci.get("conclusion") == "success", "ci.conclusion: must be success")
        _validation_reason(reasons, ci.get("head_sha") == record.get("commit"), "ci.head_sha: must equal commit")
    elif level == "T2_SHARDED" and isinstance(record.get("shards"), list):
        shards = record["shards"]
        counts = {shard.get("count") for shard in shards if isinstance(shard, dict)}
        count = next(iter(counts)) if len(counts) == 1 else None
        indexes = [shard.get("index") for shard in shards if isinstance(shard, dict)]
        _validation_reason(reasons, isinstance(count, int) and sorted(indexes) == list(range(1, count + 1)), "shards.index: must contain 1..count exactly once")
        _validation_reason(reasons, all(isinstance(shard, dict) and shard.get("exit_code") == 0 for shard in shards), "shards.exit_code: every shard must be 0")
        _validation_reason(reasons, sum(shard.get("tests_run", 0) for shard in shards if isinstance(shard, dict)) == record.get("total"), "total: must equal shard tests_run sum")
        _validation_reason(reasons, all(isinstance(shard, dict) and shard.get("digest") == record.get("digest") and shard.get("total") == record.get("total") for shard in shards), "shards.digest: every shard must carry the record digest and total")
    report_status = "VALIDATION_PASSED" if not reasons else "VALIDATION_FAILED"
    return {"status": report_status, "level": level, "reasons": reasons}, VALIDATION_EXIT_PASSED if not reasons else VALIDATION_EXIT_FAILED


# `git worktree list` reads identically from any registered worktree, so a
# read-only scope may share one parse between every lifecycle reader it calls.


def repair_task_worktree_base(
    task_id: str, worktree_root: Path | None, supplied_project: Path | None = None,
) -> dict[str, object]:
    project = _verified_lifecycle_project(supplied_project)
    identity = resolve_task_identity(project, task_id, "existing")
    report, _ready = inspect_task_worktree(task_id, worktree_root, project, require_effective_worktree=False)
    errors = [item for item in report["errors"] if item != "stale-base-record"]
    if Path.cwd().resolve() not in (project, Path(str(report["worktree"]))):
        errors.append("wrong-worktree")
    if report["integration_active"]:
        errors.append("active-integration")
    state_path, _lease, _integration = _lifecycle_paths(project, identity)
    state = _read_json_object(state_path, "worktree lifecycle state") if state_path.is_file() else {}
    head = str(report["task_commit"])
    unchanged = state.get("base_commit") == head and state.get("task_commit") == head
    if unchanged and _run_git(project, "merge-base", "--is-ancestor", head, "main").returncode != 0:
        errors.append("task-owned-commits")
    if errors or (not unchanged and "stale-base-record" not in report["errors"]):
        raise stop_error(
            "WRONG_WORKTREE", "base recovery rejected: " + ", ".join(errors or ["unproven-fast-forward"]),
            task_id=identity.canonical_id, project=project,
        )
    old_base = state["base_commit"]
    if not unchanged:
        state.update(base_commit=head, task_commit=head)
        _write_json_atomic(state_path, state)
    return {
        "version": 1, "task_id": identity.canonical_id, "repaired": not unchanged,
        "previous_base_commit": old_base, "base_commit": head,
        "evidence_renewal_required": True,
        "next_action": "renew-validation-and-evidence",
    }


def prepare_task_worktree(
    task_id: str,
    worktree_root: Path | None,
    supplied_project: Path | None = None,
    base: str = "main",
    resume: bool = False,
    new_attempt: bool = False,
    reason: str | None = None,
) -> dict[str, object]:
    if new_attempt and (not reason or not reason.strip()):
        raise MeridianError("--new-attempt requires a non-empty --reason")
    if reason is not None and not new_attempt:
        raise MeridianError("--reason requires --new-attempt")
    if new_attempt and resume:
        raise MeridianError("--new-attempt cannot be combined with --resume")
    if base != "main":
        raise MeridianError("worktree prepare permits only the main base")
    project_root = _verified_lifecycle_project(supplied_project)
    root = _effective_worktree_root(worktree_root)
    identity = resolve_task_identity(project_root, task_id, "existing")
    path = _task_worktree_path_for_identity(project_root, root, identity)
    state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    records = _git_worktrees(project_root)
    registered = next((item for item in records if Path(item["worktree"]).resolve() == path), None)
    if new_attempt and any(item.get("branch") == f"refs/heads/{identity.branch_name}" for item in records):
        raise MeridianError("--new-attempt requires retiring the registered task worktree first")
    budget_state = load_budget_state(project_root)
    budget_key, _ = resolve_budget_key(project_root, budget_state, identity.canonical_id)
    inherited = dict(budget_state.get(budget_key, {}))
    previous_attempt = int(budget_state[identity.canonical_id]["attempt"])
    if registered is None and any(int(value) > 0 for value in inherited.values()) and not new_attempt:
        raise stop_error(
            "BUDGET_ATTEMPT_REQUIRES_AUTHORIZATION",
            f"{identity.canonical_id} attempt {previous_attempt} has inherited counters: "
            + json.dumps(inherited, sort_keys=True),
            task_id=identity.canonical_id, project=shlex.quote(str(project_root)),
        )
    branch_commit = _branch_commit(project_root, identity.branch_name)
    if (registered is None) != (branch_commit is None):
        raise MeridianError(
            f"partial task state retained for {identity.canonical_id}; branch and canonical worktree must both exist or both be absent"
        )
    if new_attempt and identity.budget_key(previous_attempt + 1) in budget_state:
        raise MeridianError("next budget attempt already has ledger history; retained unchanged")
    base_commit = git_output(project_root, "rev-parse", "--verify", f"{base}^{{commit}}")
    created = False
    prior: dict[str, object] = {}
    dirty_summary: dict[str, int] | None = None
    state_missing = False
    if resume:
        if registered is None:
            raise MeridianError(
                f"nothing to resume for {identity.canonical_id}: no task branch or canonical worktree exists"
            )
        for retained in (lease_path, integration_path):
            if retained.exists():
                try:
                    holder = _read_json_object(retained, "integration state").get("task_id")
                except MeridianError:
                    holder = None
                if holder in (None, identity.canonical_id):
                    raise MeridianError(
                        f"cannot resume {identity.canonical_id} while an integration lease or staged merge is active: {retained}"
                    )
    if registered is None:
        if path.exists():
            raise MeridianError(f"worktree path collision at {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        added = _run_git(project_root, "worktree", "add", "-b", identity.branch_name, str(path), base_commit)
        if added.returncode != 0:
            raise MeridianError(added.stderr.strip() or "git worktree add failed")
        if new_attempt:
            next_attempt = previous_attempt + 1
            append_journal_line(project_root, {
                "version": JOURNAL_VERSION,
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "command": "worktree prepare new-attempt", "task": identity.canonical_id,
                "result": "ok", "exit": 0,
                "previous_attempt": previous_attempt, "new_attempt": next_attempt,
                "reason": reason.strip(), "historical_counters": inherited,
            })
            budget_state[identity.canonical_id]["attempt"] = next_attempt
            budget_state[identity.budget_key(next_attempt)] = {}
            write_budget_state(project_root, budget_state)
        branch_commit = base_commit
        created = True
    else:
        expected_ref = f"refs/heads/{identity.branch_name}"
        if registered.get("branch") != expected_ref or registered.get("HEAD") != branch_commit:
            raise MeridianError(
                f"canonical worktree mismatch retained at {path}: expected {expected_ref} at {branch_commit}"
            )
        if resume:
            dirty_summary = _dirty_summary(path)
        elif git_output(path, "status", "--porcelain"):
            raise MeridianError(f"existing task worktree is dirty and was retained: {path}")
        if state_path.is_file():
            prior = _read_json_object(state_path, "worktree lifecycle state")
            if prior.get("worktree") != str(path) or prior.get("branch") != identity.branch_name:
                raise stop_error(
                    "WRONG_WORKTREE",
                    f"lifecycle state mismatch retained at {state_path}: expected worktree {path} and branch "
                    f"{identity.branch_name}; found worktree {prior.get('worktree')} and branch {prior.get('branch')}",
                    resume=f"the developer corrects or removes the lifecycle state file {state_path}, then rerun "
                    f"meridian worktree prepare {identity.canonical_id} --project {project_root} --format json",
                )
            base_commit = str(prior.get("base_commit", base_commit))
            if not resume and _proven_stale_base(project_root, prior, str(branch_commit)):
                raise stop_error("STALE_WORKTREE_BASE", "prepared branch fast-forwarded without task commits",
                                 resume=stop_resume("STALE_WORKTREE_BASE", task_id=identity.canonical_id,
                                                    project=shlex.quote(str(project_root)))
                                 + f" --worktree-root {shlex.quote(str(root))}")
        elif resume:
            # Missing state is never repaired by a resume; Git supplies the facts instead.
            merge_base = _run_git(project_root, "merge-base", base, identity.branch_name)
            if merge_base.returncode != 0:
                raise MeridianError(merge_base.stderr.strip() or f"cannot derive the base commit of {identity.branch_name}")
            base_commit = merge_base.stdout.strip()
            state_missing = True
    state = {
        "version": 1,
        "task_id": identity.canonical_id,
        "branch": identity.branch_name,
        "worktree": str(path),
        "worktree_root": str(root),
        "project": str(project_root),
        "git_common_dir": str(canonical_git_common_dir(project_root)),
        "base_commit": base_commit,
        "task_commit": branch_commit,
        "handoff": str(identity.handoff_path),
    }
    if created:
        state["started_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    elif "started_at" in prior:
        # Keep a pre-existing value byte-for-byte; malformed values are handled
        # as unavailable by the read-only console rather than rewritten.
        state["started_at"] = prior["started_at"]
    if not resume:
        _write_json_atomic(state_path, state)
    result: dict[str, object] = {
        **state,
        "handoff_worktree": handoff_worktree_value(root, path),
        "created": created,
        "next_action": "check",
    }
    if state_missing:
        result.update({
            "base_commit_source": "derived",
            "state": "missing",
            "state_repair": f"meridian worktree prepare {identity.canonical_id} --project {project_root} --format json",
        })
    if dirty_summary is not None:
        dirty = bool(dirty_summary["changed_paths"] or dirty_summary["untracked_paths"])
        result.update({"resumed": True, "dirty": dirty, **dirty_summary})
        if dirty:
            result["next_action"] = "inspect-dirty"
    return result


def inspect_task_worktree(
    task_id: str,
    worktree_root: Path | None,
    supplied_project: Path | None = None,
    *,
    require_effective_worktree: bool = True,
    inspection_directory: Path | None = None,
    identity: ResolvedTaskIdentity | None = None,
) -> tuple[dict[str, object], bool]:
    project_root = (_verified_lifecycle_project(supplied_project) if inspection_directory is None
                    else canonical_project_root(inspection_directory))
    root = _effective_worktree_root(worktree_root)
    identity = identity or resolve_task_identity(project_root, task_id, "existing")
    expected = _task_worktree_path_for_identity(project_root, root, identity)
    state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    errors: list[str] = []
    state: dict[str, object] = {}
    if state_path.is_file():
        state = _read_json_object(state_path, "worktree lifecycle state")
    else:
        errors.append("missing-state")
    records = _git_worktrees(project_root)
    registered = next((item for item in records if Path(item["worktree"]).resolve() == expected), None)
    current = Path.cwd().resolve()
    if require_effective_worktree and current != expected:
        errors.append("wrong-worktree")
    if registered is None:
        errors.append("unregistered-worktree")
        head = ""
        branch = ""
        clean = False
    else:
        head = registered.get("HEAD", "")
        branch = registered.get("branch", "").removeprefix("refs/heads/")
        if branch != identity.branch_name:
            errors.append("branch-mismatch")
        status = _run_git(expected, "status", "--porcelain")
        clean = status.returncode == 0 and not status.stdout
        if not clean:
            errors.append("dirty-worktree")
    if state:
        if state.get("task_id") != identity.canonical_id:
            errors.append("state-task-mismatch")
        if state.get("project") != str(project_root) or state.get("worktree") != str(expected):
            errors.append("state-path-mismatch")
        if state.get("branch") != identity.branch_name:
            errors.append("state-branch-mismatch")
        if state.get("worktree_root") != str(root):
            errors.append("state-root-mismatch")
        if state.get("git_common_dir") != str(canonical_git_common_dir(project_root)):
            errors.append("state-common-dir-mismatch")
        base_commit = state.get("base_commit")
        if not isinstance(base_commit, str) or _run_git(
            project_root, "cat-file", "-e", f"{base_commit}^{{commit}}"
        ).returncode != 0:
            errors.append("base-commit-mismatch")
    handoff_consistent = bool(state) and not any(item.startswith("state-") for item in errors)
    if identity.handoff_path.is_file():
        handoff_text = identity.handoff_path.read_text(encoding="utf-8")
        expected_fields = {
            "Branch": identity.branch_name,
            "Worktree": (handoff_worktree_value(root, expected), str(expected)),
            "Base `main` commit": (str(state.get("base_commit", "")),),
        }
        for label, accepted in expected_fields.items():
            match = re.search(rf"^- {re.escape(label)}:\s*`([^`]+)`", handoff_text, re.MULTILINE)
            if match is not None and match.group(1) not in accepted:
                errors.append("handoff-mismatch")
                handoff_consistent = False
                break
    result = {
        "version": 1,
        "status": "ready" if not errors else "blocked",
        "task_id": identity.canonical_id,
        "branch": branch or identity.branch_name,
        "worktree": str(expected),
        "git_common_dir": str(canonical_git_common_dir(project_root)),
        "canonical_prepared_path": str(expected),
        "handoff_worktree": handoff_worktree_value(root, expected),
        "effective_worker_path": str(current),
        "base_commit": state.get("base_commit", ""),
        "task_commit": head,
        "clean": clean,
        "handoff_consistent": handoff_consistent,
        "integration_active": lease_path.exists() or integration_path.exists(),
        "errors": errors,
        "next_action": "implement" if not errors else "repair-or-abort",
    }
    if not errors and not result["integration_active"] and _proven_stale_base(project_root, state, head):
        errors.append("stale-base-record")
        result.update(status="blocked", next_action="repair-base", stop_reason="STALE_WORKTREE_BASE",
                      resume=stop_resume("STALE_WORKTREE_BASE", task_id=identity.canonical_id,
                                         project=shlex.quote(str(project_root)))
                      + f" --worktree-root {shlex.quote(str(root))}")
    return result, not errors


def active_worktree_task(directory: Path) -> dict[str, object] | None:
    """Resolve the task owned by an exact, registered task worktree.

    This deliberately uses the lifecycle registration and branch-to-identity
    mapping, rather than a queue status.  It is a small read-only companion to
    ``worktree check`` for hooks which do not know a task ID in advance.
    """
    current = directory.expanduser().resolve()
    primary = canonical_project_root(current)
    if current == primary:
        return None
    records = _git_worktrees(primary)
    registered = next((item for item in records if Path(item["worktree"]).resolve() == current), None)
    if registered is None:
        return None
    branch = registered.get("branch", "").removeprefix("refs/heads/")
    state_directory = canonical_git_common_dir(primary) / WORKTREE_STATE_DIRECTORY
    context: TaskIdentityContext | None = None
    for state_path in sorted(state_directory.glob("*.json")) if state_directory.is_dir() else ():
        try:
            state = _read_json_object(state_path, "worktree lifecycle state")
            if state.get("branch") != branch or state.get("worktree") != str(current):
                continue
            task_id = state.get("task_id")
            if not isinstance(task_id, str):
                continue
            context = context or task_identity_context(primary)
            identity = resolve_task_identity(primary, task_id, "existing", context=context)
        except MeridianError:
            continue
        if state_path.name != f"{identity.artifact_stem}.json" or identity.branch_name != branch or state.get("task_id") != identity.canonical_id:
            continue
        archived = identity.task_path.parent / "done" / identity.task_path.name
        exempt = [identity.task_path, archived, identity.handoff_path, identity.review_path,
                  primary / ".meridian/tasks" / f"{identity.canonical_id}.json"]
        return {
            "task_id": identity.canonical_id,
            "branch": branch,
            "worktree": str(current),
            "exempt_paths": [str(path) for path in exempt],
        }
    return None


def registered_worktree_task_states(project_root: Path) -> list[dict[str, str]]:
    """Return in-flight task states from lifecycle registrations and records."""
    primary = canonical_project_root(project_root)
    worktrees = {
        Path(item["worktree"]).resolve(): item.get("branch", "").removeprefix("refs/heads/")
        for item in _git_worktrees(primary) if "worktree" in item
    }
    states: list[dict[str, str]] = []
    state_directory = canonical_git_common_dir(primary) / WORKTREE_STATE_DIRECTORY
    context: TaskIdentityContext | None = None
    for state_path in sorted(state_directory.glob("*.json")) if state_directory.is_dir() else ():
        try:
            lifecycle = _read_json_object(state_path, "worktree lifecycle state")
            task_id = lifecycle.get("task_id")
            if not isinstance(task_id, str):
                continue
            context = context or task_identity_context(primary)
            identity = resolve_task_identity(primary, task_id, "existing", context=context)
            worktree = Path(str(lifecycle["worktree"])).resolve()
        except (KeyError, TypeError, MeridianError):
            continue
        if (state_path.name != f"{identity.artifact_stem}.json"
                or lifecycle.get("task_id") != identity.canonical_id
                or lifecycle.get("branch") != identity.branch_name
                or worktrees.get(worktree) != identity.branch_name):
            continue
        record = worktree / identity.task_path.relative_to(primary)
        if not record.is_file():
            continue
        status = read_task_field(record.read_text(encoding="utf-8"), "Status") or "IN_PROGRESS"
        states.append({"task_id": identity.canonical_id, "status": status})
    return states


def closure_status(
    task_id: str,
    worktree_root: Path | None,
    supplied_project: Path | None = None,
    identity: ResolvedTaskIdentity | None = None,
) -> tuple[dict[str, object], bool]:
    """Report the next closure step without changing Git or lifecycle state.

    `identity` is the caller's already resolved identity of `task_id` under the
    primary checkout; it only saves the resolution.
    """
    project_root = _verified_lifecycle_project(supplied_project)
    root = _effective_worktree_root(worktree_root)
    identity = identity or resolve_task_identity(project_root, task_id, "existing")
    expected = _task_worktree_path_for_identity(project_root, root, identity)
    state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    records = _git_worktrees(project_root)
    registered = next((item for item in records if Path(item["worktree"]).resolve() == expected), None)
    branch_commit = _branch_commit(project_root, identity.branch_name)
    project = str(project_root)

    def report(step: str, stop_reason: str | None, resume: str | None) -> tuple[dict[str, object], bool]:
        if stop_reason is not None:
            stop_resume(stop_reason, task_id=identity.canonical_id, project=project, evidence="")
        return ({
            "version": 1,
            "task_id": identity.canonical_id,
            "step": step,
            "stop_reason": stop_reason,
            "resume": resume,
        }, stop_reason is None)

    if not state_path.is_file() or registered is None or branch_commit is None:
        if identity.handoff_path.is_file() and registered is None and branch_commit is None:
            return report("C10", None, None)
        return report(
            "C4",
            "WRONG_WORKTREE",
            stop_resume("WRONG_WORKTREE", task_id=identity.canonical_id, project=project),
        )

    if lease_path.exists() and not integration_path.exists():
        return report(
            "C6",
            "LEASE_HELD",
            stop_resume("LEASE_HELD", task_id=identity.canonical_id, project=project),
        )
    if integration_path.exists():
        return report("C7", None, "run the selected candidate validation")

    state = _read_json_object(state_path, "worktree lifecycle state")
    inspection, _ready = inspect_task_worktree(task_id, root, project_root, require_effective_worktree=False,
                                               identity=identity)
    if inspection.get("stop_reason") == "STALE_WORKTREE_BASE":
        return report("C4", "STALE_WORKTREE_BASE", str(inspection["resume"]))
    if state.get("base_commit") == branch_commit:
        return report("C1", "ACCEPTANCE_UNMET", stop_resume("ACCEPTANCE_UNMET"))

    if _run_git(project_root, "merge-base", "--is-ancestor", branch_commit, "main").returncode == 0:
        origin = _run_git(project_root, "remote", "get-url", "origin")
        remote_main = _run_git(project_root, "rev-parse", "--verify", "refs/remotes/origin/main")
        if origin.returncode != 0 or (
            remote_main.returncode == 0
            and _run_git(project_root, "merge-base", "--is-ancestor", "main", "refs/remotes/origin/main").returncode == 0
        ):
            return report(
                "C10",
                None,
                f"meridian worktree cleanup {identity.canonical_id} --project {project} --format json",
            )
        return report(
            "C9",
            "PUSH_PENDING" if remote_main.returncode == 0 and _run_git(
                project_root, "merge-base", "--is-ancestor", "refs/remotes/origin/main", "main"
            ).returncode == 0 else None,
            stop_resume("PUSH_PENDING"),
        )

    dirty_primary = git_output(project_root, "status", "--porcelain").splitlines()
    if dirty_primary:
        paths = [line[3:] for line in dirty_primary]
        listed = ", ".join(paths[:10])
        if len(paths) > 10:
            listed += f", … (+{len(paths) - 10} more)"
        detail = f"primary checkout is dirty ({len(paths)} path(s): {listed})"
        if paths == [str(BUDGET_PATH)]:
            detail += "; .meridian/budget.json is the legacy budget file; commit its deletion to continue"
        return report(
            "C6",
            "PRIMARY_DIRTY",
            f"{detail}; {stop_resume('PRIMARY_DIRTY')}",
        )
    evidence_path = state_path.with_suffix(".evidence.json")
    if evidence_path.is_file():
        try:
            evidence = _integration_evidence(evidence_path)
        except MeridianError:
            evidence = None
        if (
            evidence is not None
            and evidence["accepted"] is True
            and evidence["validation_passed"] is True
            and evidence["validated_task_commit"] == branch_commit
            and evidence["validated_base_commit"] == state["base_commit"]
        ):
            return report(
                "C6",
                None,
                f"meridian worktree integrate stage {identity.canonical_id} --project {project} "
                f"--evidence {evidence_path} --format json",
            )
    return report("C5", "EVIDENCE_INCOMPLETE", stop_resume("EVIDENCE_INCOMPLETE"))


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise MeridianError(f"integration evidence field {label!r} must be an array of non-empty strings")
    return tuple(value)


def _bool_field(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise MeridianError(f"integration evidence field {label!r} must be boolean")
    return value


def candidate_validation_declaration(project_root: Path) -> tuple[str, dict[str, tuple[str, ...]]]:
    """Load the consumer-owned candidate-validation declaration without running it."""
    path = project_root / CANDIDATE_VALIDATION_PATH
    if not path.exists():
        return "undeclared", {}
    data = _read_json_object(path, "candidate-validation declaration")
    if data.get("version") != 1:
        raise MeridianError(f"{path}: version must be 1")
    state = data.get("state")
    if state == "undeclared":
        if set(data) != {"version", "state"}:
            raise MeridianError(f"{path}: undeclared state must contain only version and state")
        return state, {}
    if state == "none":
        if set(data) != {"version", "state"}:
            raise MeridianError(f"{path}: none state must contain only version and state")
        return state, {}
    if state != "declared":
        raise MeridianError(f"{path}: state must be declared, none, or undeclared")
    outcomes = data.get("outcomes")
    if set(data) != {"version", "state", "outcomes"} or not isinstance(outcomes, dict):
        raise MeridianError(f"{path}: declared state requires only version, state, and outcomes")
    if set(outcomes) != set(CANDIDATE_VALIDATION_OUTCOMES):
        raise MeridianError(f"{path}: outcomes must declare REUSE, BOUNDED, and FULL")
    parsed: dict[str, tuple[str, ...]] = {}
    for outcome in CANDIDATE_VALIDATION_OUTCOMES:
        fragments = outcomes[outcome]
        if not isinstance(fragments, list) or not fragments or not all(
            isinstance(fragment, str) and fragment.strip() for fragment in fragments
        ):
            raise MeridianError(f"{path}: outcomes.{outcome} must be a non-empty array of non-empty strings")
        parsed[outcome] = tuple(fragments)
    return state, parsed


def proposed_candidate_validation_declaration(project_root: Path) -> dict[str, object]:
    """Offer conservative detected-stack defaults; setup applies them only on --apply."""
    repository_check = "python3 scripts/check_repository.py"
    has_repository_check = (project_root / "scripts/check_repository.py").is_file()
    has_python_tests = (project_root / "tests").is_dir()
    if not has_repository_check:
        return {"version": 1, "state": "undeclared"}
    outcomes: dict[str, list[str]] = {
        "REUSE": [repository_check],
        "BOUNDED": [repository_check],
        "FULL": [repository_check],
    }
    if has_python_tests:
        outcomes["FULL"].append("python3 -m unittest discover -s tests")
    return {"version": 1, "state": "declared", "outcomes": outcomes}


def undeclared_validation_commands_error(project_root: Path, evidence: dict[str, object]) -> MeridianError:
    commands = evidence.get("validation_commands")
    recorded = ", ".join(commands) if isinstance(commands, list) and commands else "none recorded"
    proposal = json.dumps(proposed_candidate_validation_declaration(project_root), sort_keys=True)
    return stop_error(
        "UNDECLARED_VALIDATION_COMMANDS",
        f"no project choice is recorded at {CANDIDATE_VALIDATION_PATH}. "
        f"Task validation commands: {recorded}. Proposed declaration: {proposal}",
    )


def _integration_evidence(path: Path) -> dict[str, object]:
    evidence = _read_json_object(path.expanduser().resolve(), "integration evidence")
    required = {
        "accepted",
        "validation_passed",
        "validated_task_commit",
        "validated_base_commit",
        "full_validation_required",
        "interaction_assessment_complete",
        "task_paths",
        "task_dependencies",
        "task_behavioral_surfaces",
        "main_advanced_dependencies",
        "main_advanced_behavioral_surfaces",
    }
    missing = sorted(required - evidence.keys())
    if missing:
        raise MeridianError(f"integration evidence is incomplete; missing: {', '.join(missing)}")
    for field in ("accepted", "validation_passed", "full_validation_required", "interaction_assessment_complete"):
        _bool_field(evidence[field], field)
    for field in (
        "task_paths",
        "task_dependencies",
        "task_behavioral_surfaces",
        "main_advanced_dependencies",
        "main_advanced_behavioral_surfaces",
    ):
        _string_tuple(evidence[field], field)
    for field in ("validated_task_commit", "validated_base_commit"):
        if not isinstance(evidence[field], str) or not re.fullmatch(r"[0-9a-f]{40}", evidence[field]):
            raise MeridianError(f"integration evidence field {field!r} must be a full Git object ID")
    return evidence


def record_task_evidence(
    task_id: str,
    worktree_root: Path | None,
    validation_commands: list[str],
    validation_exit_codes: list[int],
    *,
    accepted: bool,
    task_dependencies: list[str],
    task_behavioral_surfaces: list[str],
    main_advanced_dependencies: list[str],
    main_advanced_behavioral_surfaces: list[str],
    full_validation_required: bool,
    supplied_project: Path | None = None,
    require_effective_worktree: bool = True,
) -> dict[str, object]:
    """Record Git-derived task-validation facts without running validation."""
    if len(validation_commands) != len(validation_exit_codes):
        raise MeridianError("each --validation-command requires one --validation-exit-code")
    if not validation_commands or any(not command.strip() for command in validation_commands):
        raise MeridianError("at least one non-empty --validation-command is required")
    project_root = _verified_lifecycle_project(supplied_project)
    identity = resolve_task_identity(project_root, task_id, "existing")
    inspection, ready = inspect_task_worktree(
        identity.canonical_id,
        worktree_root,
        project_root,
        require_effective_worktree=require_effective_worktree,
    )
    if not ready:
        raise MeridianError(f"task worktree is not ready: {', '.join(inspection['errors'])}")
    state_path, _lease, _integration = _lifecycle_paths(project_root, identity)
    state = _read_json_object(state_path, "worktree lifecycle state")
    task_commit = str(inspection["task_commit"])
    base_commit = str(state["base_commit"])
    task_paths = tuple(filter(None, git_output(
        project_root, "diff", "--name-only", base_commit, task_commit
    ).splitlines()))
    evidence_path = state_path.with_suffix(".evidence.json")
    evidence = {
        "accepted": accepted,
        "validation_passed": all(code == 0 for code in validation_exit_codes),
        "validated_task_commit": task_commit,
        "validated_base_commit": base_commit,
        "full_validation_required": full_validation_required,
        "interaction_assessment_complete": True,
        "task_paths": list(task_paths),
        "task_dependencies": task_dependencies,
        "task_behavioral_surfaces": task_behavioral_surfaces,
        "main_advanced_dependencies": main_advanced_dependencies,
        "main_advanced_behavioral_surfaces": main_advanced_behavioral_surfaces,
        "validation_commands": validation_commands,
        "validation_exit_codes": validation_exit_codes,
    }
    _write_json_atomic(evidence_path, evidence)
    return {
        "version": 1,
        "task_id": identity.canonical_id,
        "evidence": str(evidence_path),
        "validated_task_commit": task_commit,
        "validated_base_commit": base_commit,
        "task_paths": list(task_paths),
        "validation_passed": evidence["validation_passed"],
    }


def _remove_owned_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _lifecycle_changes_after_validation(
    project_root: Path,
    identity: ResolvedTaskIdentity,
    validated_task: str,
    task_commit: str,
) -> tuple[bool, tuple[str, ...]]:
    """Accept only lifecycle-only changes, including one exact task archive rename."""
    project_root = project_root.resolve()
    active_record = identity.task_path.relative_to(project_root)
    if active_record.parts[:2] == ("tasks", "done"):
        active_record = Path("tasks") / active_record.name
    archive_record = Path("tasks") / "done" / active_record.name
    plan_path = resolve_project_locations(project_root).plan
    allowed = {
        str(active_record),
        str(archive_record),
        str(identity.queue_path.relative_to(project_root)),
        str(identity.handoff_path.relative_to(project_root)),
        str(identity.review_path.relative_to(project_root)),
        str(state_path(project_root, identity.canonical_id).relative_to(project_root)),
        EXECUTION_EVIDENCE_PATH.as_posix(),
        str(plan_path),
        "tasks/QUEUE_ARCHIVE.md",
    }
    output = _run_git(
        project_root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames=100%",
        validated_task,
        task_commit,
    ).stdout
    fields = output.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    offending: set[str] = set()
    validated_is_archived = _run_git(
        project_root, "cat-file", "-e", f"{validated_task}:{archive_record}"
    ).returncode == 0
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if status.startswith(("R", "C")):
            if index + 1 >= len(fields):
                raise MeridianError("invalid rename-aware Git diff output")
            old_path, new_path = fields[index], fields[index + 1]
            index += 2
            if status != "R100" or old_path != str(active_record) or new_path != str(archive_record):
                offending.update((old_path, new_path))
            continue
        if index >= len(fields):
            raise MeridianError("invalid rename-aware Git diff output")
        path = fields[index]
        index += 1
        if path not in allowed:
            offending.add(path)
        elif path == str(archive_record):
            offending.add(path)
        elif path == str(active_record) and (status != "M" or validated_is_archived):
            offending.add(path)
    return not offending, tuple(sorted(offending))


def _spike_disallowed_paths(
    project_root: Path, identity: ResolvedTaskIdentity, validated_base: str, validated_task: str
) -> tuple[str, ...]:
    """Return changed paths a SPIKE task is not allowed to integrate."""
    record_path = identity.task_path
    archived_path = record_path.parent / "done" / record_path.name
    task_record = ""
    for candidate in (record_path, archived_path):
        relative = candidate.relative_to(project_root)
        shown = _run_git(project_root, "show", f"{validated_task}:{relative}")
        if shown.returncode == 0:
            task_record = shown.stdout
            break
    if read_task_field(task_record, "Class") != "SPIKE":
        return ()
    allowed = {
        str(record_path.relative_to(project_root)),
        str(archived_path.relative_to(project_root)),
        str(identity.handoff_path.relative_to(project_root)),
        str(find_adr_log(project_root).relative_to(project_root)),
        EXECUTION_EVIDENCE_PATH.as_posix(),
        str(state_path(project_root, identity.canonical_id).relative_to(project_root)),
    }
    deliverable = read_task_field(task_record, "Deliverable") or ""
    allowed.update(
        match.split("#", 1)[0]
        for match in re.findall(r"`(docs/[^`]+)`", deliverable)
        if match.split("#", 1)[0]
    )
    changed = tuple(filter(None, git_output(
        project_root, "diff", "--name-only", validated_base, validated_task
    ).splitlines()))
    return tuple(path for path in changed if path not in allowed and not re.fullmatch(r"changelog\.d/[^/]+\.md", path))


def _integration_task_state(
    project_root: Path, identity: ResolvedTaskIdentity, task_commit: str, worktree: Path,
    *, require_tracked: bool = False,
) -> dict[str, object] | None:
    """Prove terminal state and commit-bound approval before any lease or merge."""
    relative = state_path(project_root, identity.canonical_id).relative_to(project_root)
    adopted = (
        (project_root / relative.parent).is_dir()
        or (worktree / relative.parent).is_dir()
        or bool(git_output(project_root, "ls-tree", "-d", task_commit, "--", str(relative.parent)))
    )
    if not adopted and not require_tracked:
        if detect_mode(project_root) == "governed-sdd":
            candidate_identity = resolve_task_identity(worktree, identity.canonical_id, "existing", check_queue_links=False)
            _row, accepted, reason = _governed_completion_row(
                candidate_identity.queue_path.read_text(encoding="utf-8"), candidate_identity, candidate_identity.queue_path,
            )
            if not accepted:
                raise stop_error(
                    "REVIEW_NOT_APPROVED", f"{identity.review_path}: expected APPROVE; found {reason} (legacy)",
                    task_id=identity.canonical_id, project=project_root,
                )
        return None
    try:
        shown = _run_git(project_root, "show", f"{task_commit}:{relative.as_posix()}")
    except UnicodeError as error:
        raise stop_error(
            "TASK_STATE_INVALID", f"{relative}: expected readable UTF-8 JSON; found {error}",
            task_id=identity.canonical_id, project=project_root,
        ) from error
    if shown.returncode != 0:
        raise stop_error(
            "TASK_STATE_MISSING", f"{relative}: expected tracked state at {task_commit}; found missing",
            task_id=identity.canonical_id, project=project_root,
        )
    workflow = detect_mode(project_root)
    record = identity.task_path.relative_to(project_root)
    if record.parent.name == "done":
        record = record.parent.parent / record.name
    record_text = ""
    for candidate in (record, record.parent / "done" / record.name):
        snapshot = _run_git(project_root, "show", f"{task_commit}:{candidate.as_posix()}")
        if snapshot.returncode == 0:
            record_text = snapshot.stdout
            break
    spike = workflow == "governed-sdd" and read_task_field(record_text, "Class") == "SPIKE"
    state = read_task_state(
        project_root, identity.canonical_id, workflow, spike=spike, review_required=None,
        stop_factory=lambda code, detail, **context: stop_error(code, f"{relative}: {detail}", **context),
        text=shown.stdout,
    )
    review = state.get("review", {})
    required = not spike and review.get("required", workflow == "governed-sdd")
    terminal = ("ANSWERED", "INCONCLUSIVE") if spike else ("ACCEPTED",) if workflow == "governed-sdd" else ("DONE",)
    if state["status"] not in terminal:
        raise stop_error(
            "TASK_STATE_INVALID", f"{relative}: status expected {terminal}; found {state['status']!r}",
            task_id=identity.canonical_id, project=project_root,
        )
    if required:
        if review.get("verdict") != "APPROVE":
            raise stop_error(
                "REVIEW_NOT_APPROVED", f"{relative}: review.verdict expected APPROVE; found {review.get('verdict')!r}",
                task_id=identity.canonical_id, project=project_root,
            )
        reviewed = review.get("reviewed_commit")
        if not reviewed or _run_git(project_root, "merge-base", "--is-ancestor", str(reviewed), task_commit).returncode != 0:
            raise stop_error(
                "REVIEW_STALE", f"{relative}: review.reviewed_commit expected ancestor of {task_commit}; found {reviewed!r}",
                task_id=identity.canonical_id, project=project_root,
            )
        allowed = {
            record.as_posix(), (record.parent / "done" / record.name).as_posix(),
            identity.handoff_path.relative_to(project_root).as_posix(),
            identity.review_path.relative_to(project_root).as_posix(),
            relative.as_posix(), EXECUTION_EVIDENCE_PATH.as_posix(),
        }
        changed = git_output(project_root, "diff", "--name-only", str(reviewed), task_commit).splitlines()
        offending = sorted(set(changed) - allowed)
        if offending:
            raise stop_error(
                "REVIEW_STALE", f"{relative}: expected only task governance paths after {reviewed}; offending paths: {', '.join(offending)}",
                task_id=identity.canonical_id, project=project_root,
            )
    return state


def stage_task_integration(
    task_id: str,
    worktree_root: Path | None,
    evidence_path: Path,
    supplied_project: Path | None = None,
) -> dict[str, object]:
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise MeridianError("integration stage must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    _state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    if integration_path.exists():
        prior = _read_json_object(integration_path, "staged integration state")
        lease_matches = lease_path.is_file() and _read_json_object(
            lease_path, "integration lease"
        ).get("task_id") == identity.canonical_id
        candidate_matches = prior.get("candidate_tree") == git_output(project_root, "write-tree")
        merge_matches = _merge_head_path(project_root).is_file() and git_output(
            project_root, "rev-parse", "HEAD"
        ) == prior.get("main_commit")
        if (
            prior.get("task_id") == identity.canonical_id
            and lease_matches
            and candidate_matches
            and merge_matches
        ):
            return prior
        raise MeridianError(f"staged integration state is mismatched or stale at {integration_path}")
    if lease_path.exists():
        raise stop_error(
            "LEASE_HELD",
            f"an interrupted integration lease is retained at {lease_path}; use `meridian worktree integrate abort`",
            task_id=identity.canonical_id, project=project_root,
        )
    inspection, ready = inspect_task_worktree(
        identity.canonical_id,
        worktree_root,
        project_root,
        require_effective_worktree=False,
    )
    if not ready:
        raise MeridianError(f"task worktree is not ready: {', '.join(inspection['errors'])}")
    if git_output(project_root, "branch", "--show-current") != "main":
        raise MeridianError("primary checkout must be on main")
    if git_output(project_root, "status", "--porcelain"):
        raise stop_error("PRIMARY_DIRTY", "primary checkout must be clean")
    origin = _run_git(project_root, "remote", "get-url", "origin")
    remote_main = _run_git(project_root, "rev-parse", "--verify", "refs/remotes/origin/main")
    if (
        origin.returncode == 0
        and remote_main.returncode == 0
        and _run_git(
            project_root, "merge-base", "--is-ancestor", "main", "refs/remotes/origin/main"
        ).returncode == 0
        and git_output(project_root, "rev-parse", "main") != git_output(
            project_root, "rev-parse", "refs/remotes/origin/main"
        )
    ):
        raise stop_error(
            "MAIN_BEHIND_ORIGIN",
            "local main is behind the already fetched origin/main "
            f"(local main {git_output(project_root, 'rev-parse', '--short=12', 'main')}, "
            f"origin/main {git_output(project_root, 'rev-parse', '--short=12', 'refs/remotes/origin/main')})",
            task_id=identity.canonical_id, project=project_root, evidence=evidence_path,
        )
    evidence = _integration_evidence(evidence_path)
    declaration_state, _fragments = candidate_validation_declaration(project_root)
    if declaration_state == "undeclared":
        # This is deliberately before inspection, lease creation, and merge so the
        # first-use decision cannot strand an integration transaction.
        raise undeclared_validation_commands_error(project_root, evidence)
    if not evidence["accepted"] or not evidence["validation_passed"]:
        raise MeridianError("accepted, successful task validation evidence is required")
    task_commit = str(inspection["task_commit"])
    task_state = _integration_task_state(project_root, identity, task_commit, Path(str(inspection["worktree"])))
    validated_task = str(evidence["validated_task_commit"])
    validated_base = str(evidence["validated_base_commit"])
    if validated_base != inspection["base_commit"]:
        raise stop_error(
            "EVIDENCE_MISMATCH",
            f"validated base {validated_base} differs from recorded base {inspection['base_commit']}; renew validation evidence",
            task_id=identity.canonical_id, project=project_root,
        )
    base_is_ancestor = _run_git(
        project_root, "merge-base", "--is-ancestor", validated_base, validated_task
    ).returncode == 0
    validated_is_ancestor = _run_git(
        project_root, "merge-base", "--is-ancestor", validated_task, task_commit
    ).returncode == 0
    relevant_unchanged = validated_task == task_commit
    if validated_is_ancestor and not relevant_unchanged:
        relevant_unchanged, offending = _lifecycle_changes_after_validation(
            project_root, identity, validated_task, task_commit
        )
        if offending:
            raise MeridianError(f"paths changed after validation: {', '.join(offending)}")
    current_main = git_output(project_root, "rev-parse", "main")
    task_paths = tuple(filter(None, git_output(
        project_root, "diff", "--name-only", validated_base, validated_task
    ).splitlines()))
    disallowed_spike_paths = _spike_disallowed_paths(
        project_root, identity, validated_base, validated_task
    )
    if disallowed_spike_paths:
        raise MeridianError(
            "SPIKE task changes disallowed path(s): " + ", ".join(disallowed_spike_paths)
        )
    main_paths = tuple(
        filter(None, git_output(project_root, "diff", "--name-only", validated_base, current_main).splitlines())
    ) if current_main != validated_base else ()
    decision = decide_integration_validation(
        evidence_complete=True,
        validated_task_commit=validated_task,
        current_task_commit=task_commit,
        validated_base_commit=validated_base,
        current_main_commit=current_main,
        validated_base_is_task_ancestor=base_is_ancestor,
        full_validation_required=bool(evidence["full_validation_required"]),
        validated_task_is_current_ancestor=validated_is_ancestor,
        relevant_tree_unchanged_after_validation=relevant_unchanged,
        interaction_assessment_complete=bool(evidence["interaction_assessment_complete"]),
        task_paths=tuple(sorted(set(task_paths) | set(_string_tuple(evidence["task_paths"], "task_paths")))),
        main_advanced_paths=main_paths,
        task_dependencies=_string_tuple(evidence["task_dependencies"], "task_dependencies"),
        main_advanced_dependencies=_string_tuple(evidence["main_advanced_dependencies"], "main_advanced_dependencies"),
        task_behavioral_surfaces=_string_tuple(evidence["task_behavioral_surfaces"], "task_behavioral_surfaces"),
        main_advanced_behavioral_surfaces=_string_tuple(
            evidence["main_advanced_behavioral_surfaces"], "main_advanced_behavioral_surfaces"
        ),
    )
    if decision.outcome == IntegrationValidationOutcome.BLOCKED:
        raise stop_error("EVIDENCE_MISMATCH", decision.reason, task_id=identity.canonical_id, project=project_root)
    lease = {
        "version": 1,
        "task_id": identity.canonical_id,
        "branch": identity.branch_name,
        "project": str(project_root),
        "main_commit": current_main,
    }
    try:
        _write_json_atomic(lease_path, lease, exclusive=True)
    except FileExistsError as error:
        raise stop_error(
            "LEASE_HELD", f"integration lease already exists: {lease_path}",
            task_id=identity.canonical_id, project=project_root,
        ) from error
    merged = _run_git(project_root, "merge", "--no-ff", "--no-commit", identity.branch_name)
    if merged.returncode != 0:
        aborted = _run_git(project_root, "merge", "--abort")
        if aborted.returncode == 0:
            _remove_owned_file(lease_path)
        raise stop_error(
            "INTEGRATION_CONFLICT",
            "integration conflict was aborted; task branch and worktree were retained",
            task_id=identity.canonical_id, project=project_root, evidence=evidence_path,
        )
    try:
        archival: list[dict[str, object]] = []
        completion = _apply_task_completion_rows(project_root, identity, task_state, archival)
        queue_warnings = _queue_archival_warnings(
            identity.queue_path.read_text(encoding="utf-8"), detect_mode(project_root),
            _queue_state_resolver(project_root, detect_mode(project_root),
                                  {identity.canonical_id: task_state} if task_state else None),
        )
        lifecycle_paths = [str(identity.queue_path.relative_to(project_root))]
        if detect_mode(project_root) == "lean-delivery":
            lifecycle_paths.append(str(resolve_project_locations(project_root).plan))
        archive_path = identity.queue_path.with_name("QUEUE_ARCHIVE.md")
        if archive_path.exists():
            lifecycle_paths.append(str(archive_path.relative_to(project_root)))
        staged_rows = _run_git(
            project_root,
            "add",
            "--",
            *lifecycle_paths,
        )
        if staged_rows.returncode != 0:
            raise MeridianError(staged_rows.stderr.strip() or "could not stage completion rows")
    except (OSError, MeridianError) as error:
        aborted = _run_git(project_root, "merge", "--abort")
        if aborted.returncode == 0:
            _remove_owned_file(lease_path)
        raise MeridianError(str(error)) from error
    candidate_tree = git_output(project_root, "write-tree")
    staged = {
        **lease,
        "task_commit": task_commit,
        "validated_task_commit": validated_task,
        "validated_base_commit": validated_base,
        "task_paths": list(task_paths),
        "main_advanced_paths": list(main_paths),
        "decision": decision.outcome.value,
        "reason": decision.reason,
        "candidate_tree": candidate_tree,
        "next_action": "validate-candidate",
        "completion": completion,
        "archival": archival,
        "warnings": queue_warnings,
    }
    _write_json_atomic(integration_path, staged, exclusive=True)
    return staged


def finalize_task_integration(
    task_id: str,
    validation_path: Path,
    supplied_project: Path | None = None,
) -> dict[str, object]:
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise MeridianError("integration finalize must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    _task_state, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    lease = _read_json_object(lease_path, "integration lease")
    staged = _read_json_object(integration_path, "staged integration state")
    if lease.get("task_id") != identity.canonical_id or staged.get("task_id") != identity.canonical_id:
        raise MeridianError("integration ownership does not match the requested task")
    if not _merge_head_path(project_root).is_file() or git_output(
        project_root, "rev-parse", "HEAD"
    ) != staged.get("main_commit"):
        raise MeridianError("the owned staged merge state is missing or its main commit changed")
    if git_output(project_root, "write-tree") != staged.get("candidate_tree"):
        raise stop_error("EVIDENCE_MISMATCH", "staged candidate tree changed after integration stage", task_id=identity.canonical_id, project=project_root)
    validation = _read_json_object(validation_path.expanduser().resolve(), "candidate validation evidence")
    if validation.get("candidate_tree") != staged.get("candidate_tree") or validation.get("passed") is not True:
        raise stop_error(
            "EVIDENCE_MISMATCH", "candidate validation evidence is stale, mismatched, or failed", task_id=identity.canonical_id, project=project_root
        )
    required_scope = "full" if staged.get("decision") == "FULL" else "bounded"
    if validation.get("scope") != required_scope:
        raise stop_error(
            "EVIDENCE_MISMATCH", f"candidate validation scope must be {required_scope!r}", task_id=identity.canonical_id, project=project_root
        )
    commands = validation.get("commands")
    if not isinstance(commands, list) or not commands or not all(isinstance(item, str) and item for item in commands):
        raise stop_error(
            "EVIDENCE_MISMATCH", "candidate validation evidence must name successful commands", task_id=identity.canonical_id, project=project_root
        )
    declaration_state, declaration_fragments = candidate_validation_declaration(project_root)
    if declaration_state == "undeclared":
        raise stop_error(
            "UNDECLARED_VALIDATION_COMMANDS", "declare candidate validation commands before finalize"
        )
    missing_commands = missing_candidate_validation_commands(
        staged["decision"], commands, declaration_fragments
    )
    if missing_commands:
        raise stop_error(
            "EVIDENCE_MISMATCH",
            "candidate validation evidence is missing mandatory command(s): " + ", ".join(missing_commands),
            task_id=identity.canonical_id, project=project_root,
        )
    committed = _run_git(project_root, "commit", "-m", f"Integrate {identity.canonical_id}")
    if committed.returncode != 0:
        raise MeridianError(committed.stderr.strip() or "integration commit failed; staged state was retained")
    merge_commit = git_output(project_root, "rev-parse", "HEAD")
    _remove_owned_file(integration_path)
    _remove_owned_file(lease_path)
    return {
        "version": 1,
        "task_id": identity.canonical_id,
        "merge_commit": merge_commit,
        "candidate_tree": staged["candidate_tree"],
        "decision": staged["decision"],
        "next_action": "push-or-cleanup",
    }


def runnable_candidate_validation_command(command: str, project_root: Path) -> bool:
    """Check the first POSIX shell token locally, without running the command.

    A path token must name an executable file relative to the primary checkout
    (or an absolute file). Bare names resolve on PATH, with relative PATH
    entries anchored to that checkout. Invalid quoting and empty entries fail.
    This is executable discovery, not validation of arguments or shell syntax.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = tokens[0]
    if "/" in executable:
        path = project_root / executable
        return path.is_file() and os.access(path, os.X_OK)
    search_path = os.pathsep.join(str(project_root / entry) for entry in os.get_exec_path())
    return shutil.which(executable, path=search_path) is not None


def missing_candidate_validation_commands(
    decision: object, commands: list[str], fragments: dict[str, tuple[str, ...]] | None = None
) -> tuple[str, ...]:
    """Return mandatory command fragments absent from candidate evidence.

    This is intentionally a pure string check.  It accepts the profile's
    optional ``set -o pipefail;`` prefix and output-bounding pipelines because
    the required fragment remains in the command entry.
    """
    if fragments is None:
        _state, fragments = candidate_validation_declaration(Path.cwd())
    required = ("git diff --check", *fragments.get(str(decision), ()))
    return tuple(fragment for fragment in required if not any(fragment in command for command in commands))


def abort_task_integration(task_id: str, supplied_project: Path | None = None) -> dict[str, object]:
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise MeridianError("integration abort must run from the canonical primary checkout")
    # Abort must stay possible when the queue link is stale, so it skips link checks.
    identity = resolve_task_identity(project_root, task_id, "existing", check_queue_links=False)
    _task_state, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    lease = _read_json_object(lease_path, "integration lease")
    staged = _read_json_object(integration_path, "staged integration state") if integration_path.is_file() else None
    if lease.get("task_id") != identity.canonical_id or (
        staged is not None and staged.get("task_id") != identity.canonical_id
    ):
        raise MeridianError("integration ownership does not match the requested task")
    merge_head = _merge_head_path(project_root)
    if merge_head.exists():
        aborted = _run_git(project_root, "merge", "--abort")
        if aborted.returncode != 0:
            raise MeridianError(aborted.stderr.strip() or "cannot abort the owned staged integration")
    _remove_owned_file(integration_path)
    _remove_owned_file(lease_path)
    return {"version": 1, "task_id": identity.canonical_id, "status": "aborted", "next_action": "inspect"}


def cleanup_task_worktree(
    task_id: str,
    worktree_root: Path | None,
    supplied_project: Path | None = None,
) -> dict[str, object]:
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise MeridianError("worktree cleanup must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    root = _effective_worktree_root(worktree_root)
    expected = _task_worktree_path_for_identity(project_root, root, identity)
    state_path, lease_path, integration_path = _lifecycle_paths(project_root, identity)
    registered_paths = {Path(item["worktree"]).resolve() for item in _git_worktrees(project_root)}
    if (
        expected not in registered_paths
        and (not expected.exists() or (expected.is_dir() and not any(expected.iterdir())))
        and _branch_commit(project_root, identity.branch_name) is None
        and not state_path.exists()
    ):
        return {"version": 1, "task_id": identity.canonical_id, "status": "cleaned", "already_cleaned": True}
    inspection, ready = inspect_task_worktree(
        identity.canonical_id,
        worktree_root,
        project_root,
        require_effective_worktree=False,
    )
    if lease_path.exists() or integration_path.exists():
        raise stop_error("CLEANUP_BLOCKED", "cleanup is blocked while an integration lease or staged merge is active", task_id=identity.canonical_id, project=project_root)
    if not ready:
        raise stop_error("CLEANUP_BLOCKED", f"cleanup preflight failed: {', '.join(inspection['errors'])}", task_id=identity.canonical_id, project=project_root)
    if git_output(project_root, "status", "--porcelain"):
        raise stop_error("CLEANUP_BLOCKED", "primary checkout must be clean", task_id=identity.canonical_id, project=project_root)
    task_commit = str(inspection["task_commit"])
    if _run_git(project_root, "merge-base", "--is-ancestor", task_commit, "main").returncode != 0:
        raise stop_error("CLEANUP_BLOCKED", "task commit is not integrated into main", task_id=identity.canonical_id, project=project_root)
    origin = _run_git(project_root, "remote", "get-url", "origin")
    if origin.returncode == 0:
        remote_main = _run_git(project_root, "rev-parse", "--verify", "refs/remotes/origin/main")
        if remote_main.returncode != 0 or _run_git(
            project_root, "merge-base", "--is-ancestor", "main", "refs/remotes/origin/main"
        ).returncode != 0:
            raise stop_error("CLEANUP_BLOCKED", "local main is not proven pushed to origin/main", task_id=identity.canonical_id, project=project_root)
    removed = _run_git(project_root, "worktree", "remove", str(inspection["worktree"]))
    if removed.returncode != 0:
        raise stop_error(
            "CLEANUP_BLOCKED", removed.stderr.strip() or "worktree removal failed; branch was retained", task_id=identity.canonical_id, project=project_root
        )
    # Codex launches Stop hooks with the session path as cwd, even after cleanup.
    # Keep an empty, unregistered directory so the host can start the hook.
    expected.mkdir(exist_ok=True)
    deleted = _run_git(project_root, "branch", "-d", identity.branch_name)
    if deleted.returncode != 0:
        raise stop_error(
            "CLEANUP_BLOCKED", deleted.stderr.strip() or "non-force branch deletion failed", task_id=identity.canonical_id, project=project_root
        )
    _remove_owned_file(state_path)
    return {"version": 1, "task_id": identity.canonical_id, "status": "cleaned"}


def _journal_advance_step(project_root: Path, command: str, task_id: str, step: str) -> None:
    """Journal one step that `advance` performed, under the single-step command's own name."""
    line = {
        "version": JOURNAL_VERSION,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": command,
        "task": task_id.removeprefix("task-"),
        "result": "ok",
        "exit": 0,
        "step": step,
    }
    try:
        append_journal_line(project_root, line)
    except (OSError, MeridianError, InternalStopError) as error:
        print(f"warning: lifecycle journal not written: {type(error).__name__}", file=sys.stderr)


def advance_task_closure(
    task_id: str,
    worktree_root: Path | None,
    validation_commands: list[str],
    validation_exit_codes: list[int],
    *,
    accepted: bool,
    supplied_project: Path | None = None,
    candidate_commands: list[str] | None = None,
    candidate_exit_codes: list[int] | None = None,
) -> tuple[dict[str, object], bool]:
    """Run the mechanical closure steps and return where the agent must act next.

    It performs C5 (evidence), C6 (stage), C8 (finalize from the supplied
    candidate validation results) and C10 (cleanup) when closure_status says
    their preconditions hold. It never runs a command the agent supplied.
    The boolean is True when the result is a stop that the CLI reports with exit 2.
    """
    candidate_commands = candidate_commands or []
    candidate_exit_codes = candidate_exit_codes or []
    if len(validation_commands) != len(validation_exit_codes):
        raise MeridianError("each --validation-command requires one --validation-exit-code")
    if len(candidate_commands) != len(candidate_exit_codes):
        raise MeridianError("each --candidate-command requires one --candidate-exit-code")
    project_root = _verified_lifecycle_project(supplied_project)
    if Path.cwd().resolve() != project_root:
        raise MeridianError("worktree advance must run from the canonical primary checkout")
    identity = resolve_task_identity(project_root, task_id, "existing")
    state_path, _lease_path, integration_path = _lifecycle_paths(project_root, identity)
    evidence_path = state_path.with_suffix(".evidence.json")
    task = identity.canonical_id
    performed: list[str] = []

    def result(
        step: str,
        action: str,
        *,
        commands: list[str] | None = None,
        required_fragments: list[str] | None = None,
        stop_code: str | None = None,
        resume: str | None = None,
        blocked: bool = False,
    ) -> tuple[dict[str, object], bool]:
        if stop_code is not None and resume is None:
            resume = stop_resume(stop_code, task_id=task, project=str(project_root), evidence=str(evidence_path))
        return ({
            "version": 1,
            "task_id": task,
            "step": step,
            "action_required": action,
            "commands": commands or [],
            **({"required_fragments": required_fragments} if required_fragments is not None else {}),
            "stop_code": stop_code,
            "resume": resume,
            "performed": performed,
        }, blocked)

    def stopped(step: str, code: str) -> tuple[dict[str, object], bool]:
        entry = load_stop_registry()[code]
        if entry.get("human_decision") is True:
            action = "human"
        elif step in ("C1", "C2"):
            action = "run-validation"
        else:
            action = "resolve"
        return result(step, action, stop_code=code, blocked=entry.get("kind") != "status")

    while True:
        status, _ready = closure_status(task, worktree_root, project_root)
        step = str(status["step"])
        code = status["stop_reason"] if isinstance(status["stop_reason"], str) else None
        if step in performed:
            raise MeridianError(f"closure state did not advance after {step}; run closure-status")
        if step == "C1":
            return result("C1", "run-validation", stop_code="ACCEPTANCE_UNMET")
        if step == "C5":
            if not validation_commands:
                return result("C5", "run-validation", stop_code="EVIDENCE_INCOMPLETE")
            if any(exit_code != 0 for exit_code in validation_exit_codes):
                return stopped("C2", "VALIDATION_FAILED")
            if not accepted:
                return stopped("C1", "ACCEPTANCE_UNMET")
            record_task_evidence(
                task,
                worktree_root,
                validation_commands,
                validation_exit_codes,
                accepted=True,
                task_dependencies=[],
                task_behavioral_surfaces=[],
                main_advanced_dependencies=[],
                main_advanced_behavioral_surfaces=[],
                full_validation_required=False,
                supplied_project=project_root,
                require_effective_worktree=False,
            )
            performed.append("C5")
            _journal_advance_step(project_root, "evidence", task, "C5")
        elif step == "C6" and code is None:
            try:
                inspection, ready = inspect_task_worktree(
                    task, worktree_root, project_root, require_effective_worktree=False, identity=identity,
                )
                if ready:
                    _integration_task_state(project_root, identity, str(inspection["task_commit"]),
                                            Path(str(inspection["worktree"])), require_tracked=True)
            except MeridianStop as error:
                resume = stop_resume(error.code, task_id=task, project=project_root)
                if error.code == "TASK_STATE_MISSING" and detect_mode(project_root) == "lean-delivery":
                    recovery_project = _task_state_recovery_project(project_root, task)
                    resume = f"meridian task transition {task} DONE --project {shlex.quote(str(recovery_project))}"
                return result("C6", "resolve", commands=[resume], stop_code=error.code, resume=resume, blocked=True)
            try:
                staged = stage_task_integration(task, worktree_root, evidence_path, project_root)
            except MeridianStop as error:
                return stopped("C6", error.code)
            performed.append("C6")
            _journal_advance_step(project_root, "integrate stage", task, str(staged.get("next_action", "C6")))
        elif code is not None and not (step == "C9" and code == "PUSH_PENDING"):
            return stopped(step, code)
        elif step == "C7":
            staged = _read_json_object(integration_path, "staged integration state")
            declaration_state, fragments = candidate_validation_declaration(project_root)
            required = ["git diff --check", *fragments.get(str(staged.get("decision")), ())]
            commands = [entry for entry in required if runnable_candidate_validation_command(entry, project_root)]
            instruction = (
                "Run commands unchanged from the primary checkout. For each required_fragments entry "
                "not covered by commands, run a project command containing that exact fragment; "
                "report every command and exit code to advance."
            )
            if not candidate_commands:
                return result("C7", "run-candidate-validation", commands=commands,
                              required_fragments=required, resume=instruction)
            aborted_resume = (
                "the integration was aborted; fix the failure on the task branch, rerun validation, "
                "then rerun advance"
            )
            if any(exit_code != 0 for exit_code in candidate_exit_codes):
                abort_task_integration(task, project_root)
                _journal_advance_step(project_root, "integrate abort", task, "C7")
                performed.append("abort")
                return result(
                    "C7", "resolve", stop_code="CANDIDATE_VALIDATION_FAILED", resume=aborted_resume, blocked=True
                )
            missing = (
                commands
                if declaration_state == "undeclared"
                else list(missing_candidate_validation_commands(staged.get("decision"), candidate_commands, fragments))
            )
            if missing:
                abort_task_integration(task, project_root)
                _journal_advance_step(project_root, "integrate abort", task, "C7")
                performed.append("abort")
                return result(
                    "C7",
                    "run-candidate-validation",
                    commands=[entry for entry in missing if runnable_candidate_validation_command(entry, project_root)],
                    required_fragments=missing,
                    stop_code="UNDECLARED_VALIDATION_COMMANDS",
                    resume="the integration was aborted; " + instruction,
                    blocked=True,
                )
            candidate_evidence = state_path.with_suffix(".candidate-validation.json")
            _write_json_atomic(candidate_evidence, {
                "version": 1,
                "task_id": task,
                "candidate_tree": staged["candidate_tree"],
                "passed": True,
                "scope": "full" if staged.get("decision") == "FULL" else "bounded",
                "commands": candidate_commands,
            })
            try:
                finalize_task_integration(task, candidate_evidence, project_root)
            except MeridianStop as error:
                return stopped("C8", error.code)
            performed.append("C8")
            _journal_advance_step(project_root, "integrate finalize", task, "C8")
            return result(
                "C9", "push", commands=["git push origin main"], stop_code="PUSH_PENDING", resume="git push origin main"
            )
        elif step == "C9":
            return result("C9", "push", commands=["git push origin main"], stop_code=code, resume="git push origin main")
        elif step == "C10":
            cleaned = cleanup_task_worktree(task, worktree_root, project_root)
            if not cleaned.get("already_cleaned"):
                performed.append("C10")
                _journal_advance_step(project_root, "cleanup", task, "C10")
            return result("C10", "none")
        else:
            raise MeridianError(f"unexpected closure state at {step}; run closure-status")


def plan_setup(
    worktree_root: Path | None,
    codex_config: Path,
    *,
    task_identity: str | None = None,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
    user_config: Path | None = None,
    framework_root: Path | None = None,
    project_root: Path | None = None,
) -> SetupPlan:
    home = (home or Path.home()).expanduser().resolve()
    framework_root = (framework_root or Path(__file__).resolve().parents[1]).expanduser().resolve()
    project_root = primary_project_root((project_root or Path.cwd()).expanduser().resolve())
    environment = environment or os.environ
    if task_identity not in (None, "opaque", "milestone"):
        raise MeridianError(f"unsupported task identity mode: {task_identity!r}")
    resolution = resolve_worktree_root(
        worktree_root,
        environment=environment,
        home=home,
        config_path=user_config,
    )
    # Applying with a higher-precedence source must never overwrite malformed
    # lower-precedence user state without first reporting it.
    existing_config = _read_user_configuration(resolution.config_path)
    default_root = home / ".meridian/worktrees"
    expected_config = {"version": 1, "worktreeRoot": str(resolution.path)}
    if resolution.path == default_root:
        config_action = "remove" if existing_config is not None else "none"
    elif existing_config == expected_config:
        config_action = "none"
    else:
        config_action = "write"

    user_rules = plan_codex_user_rules(home / ".codex/rules/default.rules")
    directory_state, directory_change = _directory_setup_state(resolution.path)
    codex_plan: CodexConfigurationPlan | None = None
    try:
        codex_plan = plan_codex_configuration(codex_config, resolution.path)
        codex_state = _setup_codex_state(codex_plan)
        if codex_state == "blocked":
            parsed = tomllib.loads(codex_plan.current_text or "")
            differences = _codex_profile_divergence(parsed, resolution.path)
            codex_detail = (
                "owned Codex profile has unexpected divergence in: "
                + ", ".join(differences)
            )
        else:
            codex_detail = codex_plan.detail
    except MeridianError as error:
        codex_state = "blocked"
        codex_detail = str(error)

    claude_plan = plan_claude_project_allowlist(project_root)
    claude_state = claude_plan.status
    claude_detail = claude_plan.detail
    claude_hook_duplicates = claude_hook_duplicate_advisories(project_root, home)
    candidate_validation_path = project_root / CANDIDATE_VALIDATION_PATH
    candidate_validation_proposal: dict[str, object] | None = None
    try:
        candidate_validation_state, _candidate_fragments = candidate_validation_declaration(project_root)
        if candidate_validation_state == "undeclared":
            proposal = proposed_candidate_validation_declaration(project_root)
            if not candidate_validation_path.is_file() or json.loads(
                candidate_validation_path.read_text(encoding="utf-8")
            ) != proposal:
                candidate_validation_proposal = proposal
    except MeridianError:
        candidate_validation_state = "blocked"

    project_declaration_path = project_root / PROJECT_DECLARATION_PATH
    project_declaration_proposal: dict[str, object] | None = None
    try:
        if project_declaration_path.exists():
            declaration = read_project_declaration(project_root)
            assert declaration is not None
            if "project" in declaration:
                project_declaration_state = "present"
            else:
                project_declaration_state = "advisory-incomplete"
                project_declaration_proposal = {
                    **declaration,
                    "project": proposed_project_identity(project_root),
                }
        else:
            locations = resolve_project_locations(project_root)
            project_declaration_state = "advisory-missing"
            project_declaration_proposal = {
                "version": 1,
                "project": proposed_project_identity(project_root),
                "locations": {
                    "queue": str(locations.queue), "taskRoots": [str(root) for root in locations.task_roots],
                    "reviewRoot": str(locations.review_root), "handoffRoot": str(locations.handoff_root),
                    "adrLog": str(locations.adr_log), "plan": str(locations.plan),
                },
            }
            parse_project_declaration(project_declaration_proposal)
    except MeridianError:
        project_declaration_state = "blocked"

    task_identity_path = project_root / TASK_IDENTITY_PATH
    task_identity_proposal: dict[str, object] | None = None
    task_identity_detail = "no task-identity choice requested"
    if task_identity is None:
        task_identity_state = "not-requested"
    elif task_identity_path.exists():
        try:
            existing_identity = read_task_identity_policy(project_root)
        except MeridianError as error:
            task_identity_state = "blocked"
            task_identity_detail = str(error)
        else:
            if existing_identity.mode == task_identity:
                task_identity_state = "already-set"
                task_identity_detail = f"task identity is already set to {task_identity}"
            else:
                task_identity_state = "different"
                task_identity_detail = (
                    f"task identity is already set to {existing_identity.mode}; requested {task_identity}"
                )
    else:
        task_identity_proposal = {"version": 1, "mode": task_identity}
        # Validate the exact declaration that --apply will write using the
        # resolver's closed-schema parser before any mutation is possible.
        parse_task_identity_policy(task_identity_proposal)
        task_identity_state = "planned"
        task_identity_detail = f"write task identity declaration with mode {task_identity}"

    changes: list[str] = []
    if user_rules.proposed_text is not None:
        changes.append(f"configure Meridian Codex user-rules block in {user_rules.path}")
    if directory_state != "ready":
        changes.append(directory_change)
    if config_action == "write":
        changes.append(f"write {resolution.config_path} with version 1 and worktreeRoot {resolution.path}")
    elif config_action == "remove":
        changes.append(f"remove {resolution.config_path} because the built-in default needs no configuration")
    if codex_plan is not None and codex_plan.proposed_text is not None:
        verb = "repair" if codex_state in ("repair-required", "repair-and-replace-required") else "configure"
        changes.append(f"{verb} Codex permission profile in {codex_config} for {resolution.path}")
    if claude_plan.proposed_settings is not None:
        changes.append(
            f"add project Claude Code command allowlist and deny rules in {claude_plan.settings_path}"
        )
    if candidate_validation_proposal is not None:
        changes.append(
            f"write candidate-validation declaration in {candidate_validation_path} after explicit --apply consent"
        )
    if project_declaration_proposal is not None:
        changes.append(f"write project declaration in {project_declaration_path} after explicit --apply consent")
    if task_identity_proposal is not None:
        changes.append(f"write {task_identity_path} with task identity mode {task_identity}")
    if (
        directory_state == "blocked"
        or codex_state == "blocked"
        or claude_state == "blocked"
        or candidate_validation_state == "blocked"
        or project_declaration_state == "blocked"
        or task_identity_state == "blocked"
    ):
        changes = ["none; setup is blocked before mutation"]
    elif not changes:
        changes.append("none")
    warnings: list[str] = list(user_rules.warnings)
    skill_links = _framework_skill_links(framework_root, home)
    skill_links_state = _aggregate_skill_state(skill_links)
    if skill_links_state in ("blocked", "conflict"):
        changes = ["none; setup is blocked before mutation"]
    elif skill_links_state == "missing" and changes != ["none; setup is blocked before mutation"]:
        changes.append(f"create missing Codex skill links in {home / '.agents/skills'}")
    meridian_root_value = environment.get("MERIDIAN_ROOT")
    meridian_root_state = (
        "unset"
        if meridian_root_value is None
        else "ready"
        if Path(meridian_root_value).expanduser().resolve() == framework_root
        else "mismatch"
    )
    if meridian_root_state == "mismatch":
        warnings.append(f"MERIDIAN_ROOT differs from framework root: {meridian_root_value}")
    warnings.extend(_stale_codex_skill_warnings(home))
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if resolution.path == temporary_root or temporary_root in resolution.path.parents:
        warnings.append("resolved root is under a temporary directory and is unsuitable for persistent setup")
    probe_path = resolution.path
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent
    if not probe_path.is_dir():
        probe_path = probe_path.parent
    repository_probe = _run_git(probe_path, "rev-parse", "--show-toplevel")
    if repository_probe.returncode == 0:
        repository_root = Path(repository_probe.stdout.strip()).resolve()
        if resolution.path == repository_root or repository_root in resolution.path.parents:
            warnings.append("resolved root is inside the current repository and is unsuitable for machine setup")
    return SetupPlan(
        user_rules,
        resolution,
        codex_config,
        directory_state,
        codex_state,
        codex_plan,
        codex_detail,
        claude_state,
        claude_plan,
        claude_detail,
        claude_hook_duplicates,
        candidate_validation_state,
        candidate_validation_path,
        candidate_validation_proposal,
        project_declaration_state,
        project_declaration_path,
        project_declaration_proposal,
        task_identity,
        task_identity_state,
        task_identity_path,
        task_identity_proposal,
        task_identity_detail,
        config_action,
        framework_root,
        skill_links,
        skill_links_state,
        meridian_root_state,
        tuple(changes),
        tuple(warnings),
    )


def print_setup_plan(plan: SetupPlan) -> None:
    print(f"codex-user-rules: {plan.user_rules.status} ({plan.user_rules.path})")
    if plan.user_rules.proposed_text is not None:
        print("".join(difflib.unified_diff(
            plan.user_rules.current_text.splitlines(keepends=True),
            plan.user_rules.proposed_text.splitlines(keepends=True),
            fromfile=str(plan.user_rules.path), tofile=str(plan.user_rules.path) + " (planned)",
        )), end="")
    print(f"worktree-root: {plan.resolution.path}")
    print(f"worktree-root-source: {plan.resolution.source}")
    print(f"directory-exists: {'no' if plan.directory_state == 'missing' else 'yes'}")
    print(f"directory-owner-only: {'yes' if plan.directory_state == 'ready' else 'no'}")
    print(f"directory: {plan.directory_state}")
    print(f"codex-profile: {plan.codex_state}")
    print(f"codex-detail: {plan.codex_detail}")
    print(f"claude-project-allowlist: {plan.claude_state}")
    print(f"claude-detail: {plan.claude_detail}")
    print(
        "claude-deny-note: deny rules are prefix rules and defense in depth; a reworded command can "
        "evade them, and the managed denial text remains in force"
    )
    for advisory in plan.claude_hook_duplicates:
        print(f"claude-hook-duplicate: {advisory}")
    print(f"candidate-validation-commands: {plan.candidate_validation_state}")
    if plan.candidate_validation_proposal is not None:
        print("candidate-validation-proposal: " + json.dumps(plan.candidate_validation_proposal, sort_keys=True))
    print(f"project-declaration: {plan.project_declaration_state}")
    if plan.project_declaration_proposal is not None:
        print("project-declaration-proposal: " + json.dumps(plan.project_declaration_proposal, sort_keys=True))
    print(f"task-identity: {plan.task_identity_state}")
    print(f"task-identity-detail: {plan.task_identity_detail}")
    if plan.task_identity_proposal is not None:
        print("task-identity-proposal: " + json.dumps(plan.task_identity_proposal, sort_keys=True))
    mismatch = codex_profile_root_mismatch(
        plan.codex_config,
        plan.resolution.path,
    )
    if mismatch:
        print(f"codex-root-mismatch: {mismatch}")
    print(f"codex-skill-links: {plan.skill_links_state}")
    for name, path, state, detail in plan.skill_links:
        print(f"codex-skill-{name}: {state} ({path}; {detail})")
    print(f"MERIDIAN_ROOT: {plan.meridian_root_state}")
    print(f"shell-profile-MERIDIAN_ROOT: export MERIDIAN_ROOT={plan.framework_root}")
    print('shell-profile-PATH: export PATH="$MERIDIAN_ROOT/bin:$PATH"')
    for warning in plan.warnings:
        print(f"warning: {warning}")
    print("changes:")
    for change in plan.changes:
        print(f"- {change}")


def apply_setup(plan: SetupPlan) -> bool:
    if (
        plan.directory_state == "blocked"
        or plan.codex_state == "blocked"
        or plan.claude_state == "blocked"
        or plan.candidate_validation_state == "blocked"
        or plan.project_declaration_state == "blocked"
        or plan.task_identity_state == "blocked"
        or plan.skill_links_state in ("blocked", "conflict")
        or plan.codex_plan is None
    ):
        detail = (
            next(detail for _, _, state, detail in plan.skill_links if state in ("blocked", "conflict"))
            if plan.skill_links_state in ("blocked", "conflict")
            else plan.codex_detail
            if plan.codex_state == "blocked"
            else plan.claude_detail
            if plan.claude_state == "blocked"
            else plan.task_identity_detail
            if plan.task_identity_state == "blocked"
            else _directory_setup_state(plan.resolution.path)[1]
        )
        raise MeridianError(f"setup is blocked: {detail}")
    # Revalidate the user-owned file before any setup mutation.
    fresh_rules = plan_codex_user_rules(plan.user_rules.path)
    if fresh_rules.current_text != plan.user_rules.current_text:
        raise MeridianError("Codex user rules changed since planning; rerun --check")
    changed = apply_codex_user_rules(plan.user_rules)
    root = plan.resolution.path
    if plan.directory_state == "missing":
        root.mkdir(parents=True, mode=0o700)
        os.chmod(root, 0o700)
        changed = True
    elif plan.directory_state == "repair-required":
        os.chmod(root, 0o700)
        changed = True
    if plan.config_action == "write":
        _write_json_atomic(
            plan.resolution.config_path,
            {"version": 1, "worktreeRoot": str(root)},
        )
        changed = True
    elif plan.config_action == "remove":
        plan.resolution.config_path.unlink()
        changed = True
    changed = apply_codex_configuration(plan.codex_plan) or changed
    changed = apply_claude_project_allowlist(plan.claude_plan) or changed
    if plan.candidate_validation_proposal is not None:
        _write_json_atomic(plan.candidate_validation_path, plan.candidate_validation_proposal)
        changed = True
    if plan.project_declaration_proposal is not None:
        if plan.project_declaration_path.exists():
            existing = read_project_declaration(plan.project_declaration_path.parent)
            if existing is None or "project" in existing:
                raise MeridianError("project declaration appeared or changed since it was planned; rerun --check")
        _write_json_atomic(plan.project_declaration_path, plan.project_declaration_proposal)
        changed = True
    if plan.task_identity_proposal is not None:
        if plan.task_identity_path.exists():
            raise MeridianError("task identity declaration appeared since it was planned; rerun --check")
        _write_json_atomic(plan.task_identity_path, plan.task_identity_proposal)
        changed = True
    missing_links = [
        (path, plan.framework_root / "skills" / name)
        for name, path, state, _ in plan.skill_links
        if state == "missing"
    ]
    if missing_links:
        skills_root = missing_links[0][0].parent
        if not skills_root.exists():
            skills_root.mkdir(parents=True, mode=0o700)
            os.chmod(skills_root, 0o700)
            changed = True
        for path, target in missing_links:
            path.symlink_to(target)
            changed = True
    return changed


# Each group is reported as its own doctor fact: (key, ((command, decision), ...)).
CODEX_CLOSURE_POLICY_PROBES = (
    (
        "archive-rename-policy",
        (
            (("git", "mv", "tasks/1.md", "tasks/done/1.md"), "allow"),
            (("git", "mv", "-f", "tasks/1.md", "tasks/done/1.md"), "prompt"),
        ),
    ),
    (
        "inspection-command-policy",
        tuple(
            ((tool, "tasks"), "allow")
            for tool in ("ls", "cat", "head", "tail", "wc", "grep")
        )
        + (
            (("sed", "-i", "s/a/b/", "tasks/QUEUE.md"), None),
            (("rg", "--pre", "cat", "x"), None),
        ),
    ),
    (
        "validation-command-policy",
        (
            (("python3", "scripts/check_repository.py"), "allow"),
            (("python3", "-m", "unittest", "discover", "-s", "tests", "-q"), "allow"),
            (("set", "-o", "pipefail"), "allow"),
        ),
    ),
)


def _codex_policy_probe_state(
    command_policy: str,
    codex_executable: str | None,
    rules: Path,
    probes: tuple[tuple[tuple[str, ...], str | None], ...],
) -> str:
    """Report `ready` only when every probe returns its expected decision."""
    if command_policy != "ready" or not codex_executable:
        return "blocked" if command_policy == "blocked" else "approval-required"
    gaps = []
    for command, expected in probes:
        checked = subprocess.run(
            [codex_executable, "execpolicy", "check", "--rules", str(rules), "--", *command],
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            actual = json.loads(checked.stdout).get("decision") if checked.returncode == 0 else "error"
        except json.JSONDecodeError:
            actual = "error"
        if actual != expected:
            gaps.append(" ".join(command[:2]) if command[0] == "git" else command[0])
    return "ready" if not gaps else "gap: " + ", ".join(sorted(set(gaps)))


def codex_doctor(
    project_root: Path,
    config_path: Path,
    worktree_root: Path,
    *,
    framework_root: Path | None = None,
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        plan = plan_codex_configuration(config_path, worktree_root)
        result["permission-model"] = plan.status
        result["profile-ownership"] = (
            "ready"
            if plan.status == "ready"
            else plan.status
            if plan.status in ("repair-required", "repair-and-replace-required")
            else "not-applicable"
        )
    except MeridianError:
        result["permission-model"] = "blocked"
        result["profile-ownership"] = "blocked"
    mismatch = codex_profile_root_mismatch(config_path, worktree_root)
    if mismatch:
        result["codex-root-mismatch"] = mismatch
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        parsed = {}
    trusted = any(
        isinstance(settings, dict)
        and settings.get("trust_level") == "trusted"
        and Path(path).expanduser().resolve() == project_root.resolve()
        for path, settings in parsed.get("projects", {}).items()
    )
    result["project-trust"] = "ready" if trusted else "approval-required"
    rules = project_root / ".codex/rules/meridian.rules"
    result["command-policy"] = "ready" if rules.is_file() and trusted else ("approval-required" if rules.is_file() else "blocked")
    claude_plan = plan_claude_project_allowlist(project_root)
    result["claude-project-allowlist"] = claude_plan.status
    try:
        validation_state, _fragments = candidate_validation_declaration(project_root)
        result["candidate-validation-commands"] = (
            "advisory-undeclared" if validation_state == "undeclared" else "ready"
        )
    except MeridianError:
        result["candidate-validation-commands"] = "blocked"
    lifecycle_policy = "approval-required"
    codex_executable = shutil.which("codex")
    if result["command-policy"] == "ready" and codex_executable:
        probes = (
            ("path", "TASK-1", "--worktree-root", str(worktree_root)),
            ("prepare", "TASK-1", "--worktree-root", str(worktree_root), "--format", "json"),
            ("check", "TASK-1", "--worktree-root", str(worktree_root), "--format", "json"),
            ("evidence", "TASK-1", "--format", "json"),
            ("closure-status", "TASK-1", "--format", "json"),
            ("advance", "TASK-1", "--format", "json"),
            ("integrate", "stage", "TASK-1", "--worktree-root", str(worktree_root), "--evidence", "handoff.json", "--format", "json"),
            ("integrate", "finalize", "TASK-1", "--evidence", "candidate.json", "--format", "json"),
            ("integrate", "abort", "TASK-1", "--format", "json"),
            ("cleanup", "TASK-1", "--worktree-root", str(worktree_root), "--format", "json"),
        )
        decisions: list[str | None] = []
        for probe in probes:
            checked = subprocess.run(
                [codex_executable, "execpolicy", "check", "--rules", str(rules), "--", "meridian", "worktree", *probe],
                text=True,
                capture_output=True,
                check=False,
            )
            try:
                decisions.append(json.loads(checked.stdout).get("decision") if checked.returncode == 0 else None)
            except json.JSONDecodeError:
                decisions.append(None)
        lifecycle_policy = "ready" if decisions and all(item == "allow" for item in decisions) else "blocked"
    elif result["command-policy"] == "blocked":
        lifecycle_policy = "blocked"
    result["lifecycle-command-policy"] = lifecycle_policy
    for key, group in CODEX_CLOSURE_POLICY_PROBES:
        result[key] = _codex_policy_probe_state(
            result["command-policy"], codex_executable, rules, group
        )
    root_write = "approval-required"
    if result["permission-model"] in ("ready", "repair-required", "repair-and-replace-required") and worktree_root.is_dir():
        try:
            descriptor, probe_name = tempfile.mkstemp(prefix=".meridian-codex-probe-", dir=worktree_root)
            os.close(descriptor)
            Path(probe_name).unlink()
            root_write = "ready"
        except OSError:
            root_write = "blocked"
    result["worktree-root-write"] = root_write
    result["git-metadata"] = "ready" if lifecycle_policy == "ready" else "approval-required"
    home = (home or Path.home()).expanduser().resolve()
    framework_root = (framework_root or Path(__file__).resolve().parents[1]).expanduser().resolve()
    try:
        result["user-command-policy"] = plan_codex_user_rules(home / ".codex/rules/default.rules").status
    except MeridianError:
        result["user-command-policy"] = "stale"
    result["skill-links"] = _aggregate_skill_state(_framework_skill_links(framework_root, home))
    meridian_root_value = (environment or os.environ).get("MERIDIAN_ROOT")
    result["MERIDIAN_ROOT"] = (
        "unset"
        if meridian_root_value is None
        else "ready"
        if Path(meridian_root_value).expanduser().resolve() == framework_root
        else "mismatch"
    )
    return result


# Pre-marker capabilities (001, 002) shipped as bare phrases before migration
# 006 introduced markers. A project adopted between their release and 006 is
# legitimately compliant but has no marker to find; without this fallback,
# every such already-adopted project would regress to fully MISSING. Each
# entry proves only that v1 was implemented — the version that predates
# markers entirely — never a later one.


def _audit_evidence_reference(
    project_root: Path, reference: str, surface_digests: set[str]
) -> str | None:
    """Return a diagnostic when a persisted evidence reference is not current."""
    if reference.startswith("sha256:"):
        digest = reference.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return f"invalid digest evidence {reference!r}"
        if digest not in surface_digests:
            return f"stale digest evidence {reference}"
        return None
    if reference.startswith("path:"):
        raw_path = reference.removeprefix("path:")
        try:
            relative_path = _repository_relative_path(raw_path, "audit evidence path")
        except MeridianError as error:
            return str(error)
        if not (project_root / relative_path).is_file():
            return f"missing evidence artifact {relative_path}"
        return None
    return f"unresolvable evidence reference {reference!r}; expected path:<path> or sha256:<digest>"


def _audit_snapshot_evidence(
    project_root: Path, snapshot: EvidenceSnapshot, surface_digests: set[str]
) -> list[str]:
    return [
        diagnostic
        for reference in snapshot.evidence
        if (diagnostic := _audit_evidence_reference(project_root, reference, surface_digests))
        is not None
    ]


def _digest_exempt(relative: str, path: Path) -> bool:
    """Whether a consumer profile verifies this managed copy without its digest."""
    return relative in PROJECT_EDITABLE_MANAGED_PATHS or (
        CAPABILITY_MARKER.search(path.read_text(encoding="utf-8")) is not None
    )


def installation_surface_diagnostics(
    project_root: Path,
    declaration: CapabilityDeclaration,
    managed_files: dict[str, object],
    *,
    marker_files_exempt: bool = False,
) -> tuple[list[str], list[str]]:
    """Compare declared installation surfaces without resolving host probes.

    Repository validation and the profile doctor share this comparison so a
    managed-copy edit receives the same verdict before either command examines
    host-specific evidence.
    """
    failures: list[str] = []
    surface_digests: set[str] = set()
    identities: list[str] = []
    for surface in declaration.managed_surface:
        identities.append(f"{surface.form}:{surface.path}")
        path = project_root / surface.path
        if surface.form == "declaration-only":
            continue
        if not path.is_file():
            failures.append(f"missing {surface.form} surface {surface.path}")
            continue
        if (
            marker_files_exempt
            and surface.form == "managed-copy"
            and _digest_exempt(surface.path, path)
        ):
            # Verified by the marker-integrity rows, or configured by the project
            # by design; neither is drift.
            continue
        digest = sha256(path)
        surface_digests.add(digest)
        if f"sha256:{digest}" not in declaration.installation.evidence:
            failures.append(f"{surface.form} surface {surface.path} lacks matching digest evidence")
        if surface.form == "managed-copy":
            expected_digest = managed_files.get(surface.path)
            if expected_digest is None:
                failures.append(f"managed-copy surface {surface.path} has no managedFiles digest")
            elif expected_digest != digest:
                failures.append(
                    f"drifted managed-copy surface {surface.path}: expected {expected_digest}, got {digest}"
                )
    failures.extend(_audit_snapshot_evidence(project_root, declaration.installation, surface_digests))
    return identities, failures


def _audit_probe_evidence(project_root: Path, snapshot: EvidenceSnapshot) -> list[str]:
    """Require runtime/behavior claims to name concrete probe artifacts."""
    diagnostics: list[str] = []
    for reference in snapshot.evidence:
        if not reference.startswith("probe:"):
            diagnostics.append(
                f"invalid positive evidence {reference!r}; expected probe:<path>"
            )
            continue
        raw_path = reference.removeprefix("probe:")
        try:
            relative_path = _repository_relative_path(raw_path, "audit probe path")
        except MeridianError as error:
            diagnostics.append(str(error))
            continue
        if not (project_root / relative_path).is_file():
            diagnostics.append(f"missing probe artifact {relative_path}")
    return diagnostics


def managed_copy_drift(
    project_root: Path,
    managed_files: dict[str, object],
    *,
    skip_paths: tuple[str, ...] | set[str] = (),
    skip_marker_files: bool = False,
) -> list[tuple[str, str]]:
    """(path, diagnostic) for each recorded managed copy that is missing or whose
    digest differs from `managedFiles`. The repository check and the project audit share
    this comparison. `skip_marker_files` leaves out files carrying capability
    markers, which the marker-integrity audit verifies region by region."""
    skipped = set(skip_paths)
    diagnostics: list[tuple[str, str]] = []
    for relative, expected in sorted(managed_files.items()):
        if relative in skipped:
            continue
        path = project_root / relative
        if not path.is_file():
            diagnostics.append((relative, f"missing managed-copy surface {relative}"))
            continue
        if skip_marker_files and CAPABILITY_MARKER.search(path.read_text(encoding="utf-8")):
            continue
        current = sha256(path)
        if expected != current:
            diagnostics.append(
                (relative, f"drifted managed-copy surface {relative}: expected {expected}, got {current}")
            )
    return diagnostics


def declared_managed_copy_paths(
    manifest: dict[str, object], framework_root: Path
) -> set[str]:
    """Return managed-copy surfaces a capability profile audits independently."""
    if int(manifest.get("protocolVersion", 0)) < PROTOCOL_VERSION:
        return set()
    return {
        surface.path
        for declared in parse_capability_profiles(
            manifest, load_capability_catalog(framework_root), []
        )
        for declaration in declared.capabilities
        for surface in declaration.managed_surface
        if surface.form == "managed-copy"
    }


def is_markerless_managed_copy_digest_audited(
    project_root: Path, relative: str, declared_paths: set[str]
) -> bool:
    """Whether the managed-copy digest audit checks this local file."""
    path = project_root / relative
    return (
        relative not in PROJECT_EDITABLE_MANAGED_PATHS
        and relative not in declared_paths
        and path.is_file()
        and CAPABILITY_MARKER.search(path.read_text(encoding="utf-8")) is None
    )


def audit_managed_copy_digests(
    project_root: Path, managed_files: dict[str, object], declared_paths: set[str]
) -> list[AuditResult]:
    """One row per markerless managed copy: PASS when its digest is the recorded
    one, FAIL when it drifted. Files that carry markers, project-owned files, and
    copies a declared profile already verifies are not repeated here."""
    candidates = {
        relative: expected
        for relative, expected in managed_files.items()
        if is_markerless_managed_copy_digest_audited(project_root, relative, declared_paths)
    }
    drifted = {
        relative
        for relative, _diagnostic in managed_copy_drift(
            project_root, candidates, skip_paths=declared_paths, skip_marker_files=True
        )
    }
    results: list[AuditResult] = []
    for relative in sorted(candidates):
        path = project_root / relative
        if relative in drifted:
            results.append(
                AuditResult(
                    "FAIL",
                    "managed-copy-digest",
                    f"{relative}: differs from the digest `meridian upgrade` recorded; restore the released "
                    "text and put project-specific content in the project's own files",
                )
            )
        else:
            results.append(
                AuditResult("PASS", "managed-copy-digest", f"{relative}: matches the recorded digest")
            )
    return results


def audit_declared_capabilities(
    project_root: Path, framework_root: Path, requested_mode: str
) -> tuple[list[AuditResult], str]:
    """Audit effective declarations without projecting migration provenance."""
    try:
        manifest = load_manifest(project_root, framework_root)
    except MeridianError as error:
        # Preserve the CLI's protocol-compatibility diagnostic: callers must
        # update the framework before this version can interpret the manifest.
        if "newer than this Meridian CLI supports" in str(error):
            raise
        return [AuditResult("FAIL", "declaration/manifest", str(error))], requested_mode

    workflow_mode = manifest_workflow_mode(manifest)
    if requested_mode != workflow_mode:
        return [
            AuditResult(
                "FAIL",
                "declaration/workflow-mode",
                f"requested {requested_mode}, but the locked manifest declares {workflow_mode}",
            )
        ], workflow_mode

    protocol_version = check_protocol_compatibility(manifest)
    if "capabilityProfiles" not in manifest or not manifest.get("capabilityProfiles"):
        status = (
            "FAIL"
            if protocol_version >= CAPABILITY_DECLARATION_REQUIRED_PROTOCOL
            else "UNVERIFIED"
        )
        rationale = (
            f"protocol v{protocol_version} requires explicit capabilityProfiles"
            if status == "FAIL"
            else f"legacy protocol v{protocol_version} manifest has no capabilityProfiles; "
            "migration history is provenance only"
        )
        return [AuditResult(status, "declaration/legacy-compatibility", rationale)], workflow_mode

    catalog = load_capability_catalog(framework_root)
    try:
        profiles = parse_capability_profiles(manifest, catalog)
    except MeridianError as error:
        return [AuditResult("FAIL", "declaration/capabilityProfiles", str(error))], workflow_mode

    managed_files = manifest.get("managedFiles", {})
    assert isinstance(managed_files, dict)
    framework_version = read_version(framework_root)
    results: list[AuditResult] = []
    for profile in profiles:
        for declaration in profile.capabilities:
            capability = catalog.capability(declaration.capability_id)
            assert capability is not None
            prefix = f"{profile.profile_id}/{declaration.capability_id}"
            exclusions: list[str] = []
            if workflow_mode not in capability.workflow_modes:
                exclusions.append("workflow-mode-excluded")
            if profile.profile_id == "meridian-self-hosting" and not capability.self_hosting_eligible:
                exclusions.append("self-hosting-ineligible")
            if exclusions:
                rationale = ", ".join(exclusions)
                results.append(
                    AuditResult(
                        "NOT_APPLICABLE",
                        f"{prefix}/installation",
                        f"catalog exclusion: {rationale}",
                    )
                )
                for host_id, _snapshot in declaration.host_activation:
                    host_rationale = (
                        "host-profile-unsupported"
                        if host_id not in dict(capability.host_profiles)
                        else rationale
                    )
                    results.append(
                        AuditResult(
                            "NOT_APPLICABLE",
                            f"{prefix}/host/{host_id}",
                            f"catalog exclusion: {host_rationale}",
                        )
                    )
                results.append(
                    AuditResult(
                        "NOT_APPLICABLE",
                        f"{prefix}/verification",
                        f"catalog exclusion: {rationale}",
                    )
                )
                continue

            surface_identities, surface_failures = installation_surface_diagnostics(
                project_root,
                declaration,
                managed_files,
                marker_files_exempt=profile.profile_id not in STRICT_DIGEST_PROFILES,
            )
            if declaration.installation.state != "INSTALLED":
                surface_failures.append(
                    f"declared installation state is {declaration.installation.state}"
                )
            installation_status = "FAIL" if surface_failures else "PASS"
            results.append(
                AuditResult(
                    installation_status,
                    f"{prefix}/installation",
                    "verified surfaces: "
                    + ", ".join(surface_identities)
                    + "; "
                    + "; ".join(surface_failures)
                    if surface_failures
                    else "verified surfaces: " + ", ".join(surface_identities),
                )
            )

            supported_hosts = dict(capability.host_profiles)
            for host_id, snapshot in declaration.host_activation:
                identity = f"{prefix}/host/{host_id}"
                if host_id not in supported_hosts:
                    results.append(
                        AuditResult(
                            "NOT_APPLICABLE",
                            identity,
                            "catalog exclusion: host-profile-unsupported",
                        )
                    )
                    continue
                evidence_failures = _audit_probe_evidence(project_root, snapshot)
                if snapshot.state == "NOT_APPLICABLE":
                    results.append(
                        AuditResult(
                            "FAIL",
                            identity,
                            "host is catalog-supported, so NOT_APPLICABLE is contradictory",
                        )
                    )
                elif snapshot.state in {"ENFORCED", "ADVISORY"}:
                    failures = list(evidence_failures)
                    if installation_status != "PASS":
                        failures.append("positive activation claim depends on failed installation")
                    results.append(
                        AuditResult(
                            "FAIL" if failures else ("PASS" if snapshot.state == "ENFORCED" else "ADVISORY"),
                            identity,
                            "; ".join(failures)
                            if failures
                            else f"{snapshot.state.lower()} with {supported_hosts[host_id]} evidence",
                        )
                    )
                elif snapshot.state == "UNSUPPORTED":
                    results.append(
                        AuditResult(
                            "ADVISORY",
                            identity,
                            "declared UNSUPPORTED for a catalog-supported host",
                        )
                    )
                else:
                    results.append(
                        AuditResult(
                            "UNVERIFIED",
                            identity,
                            "applicable host activation has no effective probe evidence",
                        )
                    )

            verification = declaration.verification
            verification_failures = _audit_probe_evidence(project_root, verification)
            if verification.state in {"PASS", "ADVISORY"}:
                if verification.verified_at is None:
                    verification_failures.append("positive verification has no verifiedAt value")
                if verification.verifier_version != framework_version:
                    verification_failures.append(
                        "stale verifierVersion "
                        f"{verification.verifier_version!r}; expected {framework_version!r}"
                    )
                if installation_status != "PASS":
                    verification_failures.append("positive verification depends on failed installation")
                verification_status = (
                    "FAIL" if verification_failures else verification.state
                )
                detail = (
                    "; ".join(verification_failures)
                    if verification_failures
                    else f"verified at {verification.verified_at} by Meridian {verification.verifier_version}"
                )
            elif verification.state == "NOT_APPLICABLE":
                verification_status = "FAIL"
                detail = "capability is catalog-applicable, so NOT_APPLICABLE is contradictory"
            elif verification.state == "FAIL":
                verification_status = "FAIL"
                detail = "persisted verification state is FAIL"
            else:
                verification_status = "UNVERIFIED"
                detail = "applicable capability lacks current verification evidence"
            results.append(
                AuditResult(verification_status, f"{prefix}/verification", detail)
            )
    return results, workflow_mode


def load_retired_text_registry(framework_root: Path) -> list[dict[str, object]]:
    """Read the versioned advisory registry; older framework fixtures lack it."""
    path = framework_root / "capabilities/retired-text-v1.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "retirements"}
            or type(data["version"]) is not int
            or data["version"] != 1
        ):
            raise ValueError("expected version 1 and retirements")
        entries = data["retirements"]
        if not isinstance(entries, list):
            raise ValueError("retirements must be an array")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "capability", "retiredIn", "phrases", "files", "remedy"
            }:
                raise ValueError("invalid retirement fields")
            for field, pattern in (
                ("capability", r"[a-z0-9]+(?:-[a-z0-9]+)*"),
                ("retiredIn", r"[0-9]+\.[0-9]+\.[0-9]+"),
            ):
                if not isinstance(entry[field], str) or not re.fullmatch(pattern, entry[field]):
                    raise ValueError(f"invalid {field}")
            if not isinstance(entry["remedy"], str) or not entry["remedy"].strip():
                raise ValueError("missing remedy")
            for field in ("phrases", "files"):
                values = entry[field]
                if (
                    not isinstance(values, list) or not values
                    or any(not isinstance(value, str) or not value for value in values)
                    or len(set(values)) != len(values)
                ):
                    raise ValueError(f"invalid {field}")
            for value in entry["files"]:
                path_value = Path(value)
                if (
                    not path_value.parts or path_value.is_absolute()
                    or ".." in path_value.parts or path_value.parts[0] == "tasks"
                    or "\\" in value
                ):
                    raise ValueError("retired text files must be safe project paths outside tasks")
        return entries
    except (OSError, ValueError) as error:
        raise MeridianError(f"invalid retired-text registry: {error}") from error


def retired_text_advisories(
    project_root: Path, framework_root: Path, manifest: dict[str, object]
) -> list[AuditResult]:
    """Match literal phrases only in explicitly listed, project-owned text."""
    results = []
    installed = version_key(str(manifest["frameworkVersion"]))
    for entry in load_retired_text_registry(framework_root):
        if installed < version_key(entry["retiredIn"]):
            continue
        for relative_path in entry["files"]:
            path = project_root / relative_path
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            # Blank managed regions without changing line numbers. An unfinished
            # region remains managed through EOF; marker audit handles corruption.
            text = re.sub(
                r"<!-- MERIDIAN:BEGIN\b.*?(?:<!-- MERIDIAN:END -->|\Z)",
                lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
                text, flags=re.DOTALL,
            )
            for line_number, line in enumerate(text.splitlines(), 1):
                for phrase in entry["phrases"]:
                    if phrase.casefold() in line.casefold():
                        results.append(AuditResult(
                            "ADVISORY", "retired-text",
                            f"{relative_path}:{line_number}: retired capability={entry['capability']}; "
                            f"phrase={phrase!r}; {entry['remedy']}",
                        ))
    return results


def audit_task_state_projections(project_root: Path, workflow: str) -> list[AuditResult]:
    """Explicit full check: enumerate state files and report prose drift without repairs."""
    project_root = project_root.resolve()
    directory = project_root / ".meridian/tasks"
    paths = sorted(directory.glob("*.json"))
    if not paths:
        return []
    locations = resolve_project_locations(project_root)
    authorities = _task_authorities(project_root, locations)
    projections: dict[str, list[tuple[str, str]]] = {}
    queue = project_root / locations.queue
    for path in (queue, queue.with_name("QUEUE_ARCHIVE.md")):
        if not path.is_file():
            continue
        for found in _queue_task_rows(path.read_text(encoding="utf-8")):
            value = str(found["status"])
            if workflow == "lean-delivery":
                value = {"[ ]": "QUEUED", "[/]": "IN_PROGRESS", "[x]": "DONE"}.get(value, value)
            projections.setdefault(str(found["id"]), []).append((path.relative_to(project_root).as_posix(), value))
    results = []
    for path in paths:
        task_id = path.stem
        relative = path.relative_to(project_root).as_posix()
        authority = authorities.get(task_id)
        records = authority.task_paths if authority else ()
        record = records[0] if len(records) == 1 else None
        try:
            record_text = record.read_text(encoding="utf-8") if record else ""
            state = read_task_state(
                project_root, task_id, workflow, review_required=None,
                spike=read_task_field(record_text, "Class") == "SPIKE", stop_factory=stop_error,
            )
        except (MeridianError, OSError, UnicodeError) as error:
            results.append(AuditResult("FAIL", "task-state", f"{relative}: {error}"))
            continue
        expected = state["status"]
        drift = []
        queue_values = projections.get(task_id, [(locations.queue, "missing")])
        for label, value in queue_values:
            if value != expected:
                drift.append(f"{label} queue Status: state={expected}, projection={value}")
        value = read_task_field(record_text, "Status")
        value = value.strip("`") if value else "missing"
        label = record.relative_to(project_root).as_posix() if record else "task record (missing or ambiguous)"
        if value != expected:
            drift.append(f"{label} record Status: state={expected}, projection={value}")
        results.append(AuditResult(
            "ADVISORY" if drift else "PASS", "task-state",
            f"{relative}: " + ("; ".join(drift) if drift else f"queue Status and record Status match {expected}"),
        ))
    return results


def run_audit(
    project_root: Path,
    framework_root: Path,
    mode: str,
    ci_profile: str | None = None,
) -> int:
    results, locked_mode = audit_declared_capabilities(project_root, framework_root, mode)
    try:
        results.extend(audit_task_state_projections(project_root, locked_mode))
    except (MeridianError, OSError, UnicodeError) as error:
        results.append(AuditResult("FAIL", "task-state", str(error)))
    legacy_checks = (
        ("marker-integrity", audit_capability_markers),
        ("duplicate-heading", audit_duplicate_headings),
        ("capability-move", audit_capability_moves),
    )
    for check_name, check in legacy_checks:
        try:
            check_results = check(project_root, framework_root, locked_mode)
        except MeridianError as error:
            results.append(AuditResult("FAIL", check_name, str(error)))
            continue
        for status, detail in check_results:
            normalized_status = "UNVERIFIED" if status == "SKIP" else status
            results.append(AuditResult(normalized_status, check_name, detail))
    for status, detail in audit_entry_router(project_root):
        results.append(AuditResult(status, "entry-router", detail))
    try:
        digest_manifest = load_manifest(project_root, framework_root)
        results.extend(retired_text_advisories(project_root, framework_root, digest_manifest))
        recorded_digests = digest_manifest.get("managedFiles", {})
        declared_copy_paths = declared_managed_copy_paths(digest_manifest, framework_root)
        if isinstance(recorded_digests, dict):
            results.extend(
                audit_managed_copy_digests(project_root, recorded_digests, declared_copy_paths)
            )
    except (MeridianError, ValueError):
        # Projects without a readable manifest have no recorded digests to compare.
        pass
    try:
        detect_mode(project_root)
    except MeridianError as error:
        # Fixture and legacy projects may have a valid manifest but no local
        # workflow-mode lock, so their router read set is not available.
        results.append(AuditResult("NOT_APPLICABLE", "context-size", str(error)))
    else:
        try:
            for role in CONTEXT_SIZE_ROLES[locked_mode]:
                report = context_size_report(project_root, role, workflow_mode=locked_mode)
                for path in report["exceeded"]:
                    results.append(AuditResult("FAIL", "context-size", f"{role}: {path} exceeds its configured ceiling"))
        except MeridianError as error:
            results.append(AuditResult("FAIL", "context-size", str(error)))
    try:
        validation_state, _fragments = candidate_validation_declaration(project_root)
        if validation_state == "undeclared":
            results.append(AuditResult(
                "ADVISORY", "candidate-validation-commands",
                "undeclared; choose declared fragments or none before the first integration",
            ))
    except MeridianError as error:
        results.append(AuditResult("FAIL", "candidate-validation-commands", str(error)))
    try:
        declaration = read_project_declaration(project_root)
        if declaration is not None and "project" not in declaration:
            results.append(AuditResult("ADVISORY", "project-declaration", "advisory-incomplete; missing project identity"))
    except MeridianError as error:
        results.append(AuditResult("FAIL", "project-declaration", str(error)))
    try:
        if tracked_budget_state(project_root):
            results.append(AuditResult("ADVISORY", "budget-state", "tracked legacy .meridian/budget.json; the next budget write migrates it"))
    except MeridianError as error:
        results.append(AuditResult("FAIL", "budget-state", str(error)))

    results.sort(key=lambda result: (result.identity, result.detail))
    for result in results:
        print(f"{result.status:14} {result.identity} — {result.detail}")

    counts = {state: 0 for state in AUDIT_STATES}
    for result in results:
        counts[result.status] += 1
    if counts["FAIL"]:
        aggregate = "FAIL"
        exit_code = 2
    elif counts["ADVISORY"] or counts["UNVERIFIED"]:
        aggregate = "UNVERIFIED" if counts["UNVERIFIED"] else "ADVISORY"
        exit_code = int(bool(counts["UNVERIFIED"] or any(
            result.status == "ADVISORY" and result.identity != "retired-text"
            for result in results
        )))
    else:
        aggregate = "PASS"
        exit_code = 0
    summary = " ".join(f"{state}={counts[state]}" for state in AUDIT_STATES)
    print(f"SUMMARY worst={aggregate} {summary}")
    if ci_profile is not None:
        required = [
            result
            for result in results
            if result.status == "FAIL"
            or (
                result.identity.startswith(f"{ci_profile}/")
                and result.identity.endswith("/installation")
            )
        ]
        profile_installations = [
            result
            for result in required
            if result.identity.startswith(f"{ci_profile}/")
            and result.identity.endswith("/installation")
        ]
        required_failures = [result for result in required if result.status != "PASS"]
        if not profile_installations:
            required_failures.append(
                AuditResult(
                    "FAIL",
                    f"{ci_profile}/ci-gate",
                    "profile has no declared installation results",
                )
            )
        ci_status = "FAIL" if required_failures else "PASS"
        print(
            f"CI_GATE profile={ci_profile} worst={ci_status} "
            f"required={len(required)} failures={len(required_failures)}"
        )
        return 2 if required_failures else 0
    return exit_code


def _load_profile_probe(
    project_root: Path,
    relative_path: str,
    profile: CatalogProfile,
    expected_host: str,
) -> dict[str, object]:
    path = project_root / relative_path
    if not path.is_file():
        raise MeridianError(f"required probe is missing: {relative_path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MeridianError(f"required probe is invalid JSON: {relative_path}") from error
    data = _required_object(value, f"probe {relative_path}")
    if data.get("schemaVersion") != 1:
        raise MeridianError(f"probe {relative_path} must use schemaVersion 1")
    if data.get("profileId") != profile.profile_id or data.get("profileVersion") != profile.version:
        raise MeridianError(f"probe {relative_path} targets the wrong profile version")
    if data.get("hostProfile") != expected_host:
        raise MeridianError(f"probe {relative_path} must target host profile {expected_host}")
    for field in ("host", "hostVersion", "invocationMode", "configurationLayer", "fallback"):
        _required_string(data.get(field), f"probe {relative_path}.{field}")
    state = _required_string(data.get("state"), f"probe {relative_path}.state")
    if state not in {"PASS", "ADVISORY", "UNSUPPORTED", "UNVERIFIED"}:
        raise MeridianError(f"probe {relative_path}.state is unsupported: {state}")
    for field in ("observationTime", "evidenceArtifact"):
        field_value = data.get(field)
        if field_value is not None and (not isinstance(field_value, str) or not field_value.strip()):
            raise MeridianError(f"probe {relative_path}.{field} must be null or a non-empty string")
    if state == "PASS" and (data.get("observationTime") is None or data.get("evidenceArtifact") is None):
        raise MeridianError(f"probe {relative_path} PASS requires observationTime and evidenceArtifact")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise MeridianError(f"probe {relative_path}.checks must be a non-empty list")
    covered: set[str] = set()
    for index, raw_check in enumerate(checks):
        check = _required_object(raw_check, f"probe {relative_path}.checks[{index}]")
        capability_id = _required_string(
            check.get("capability"), f"probe {relative_path}.checks[{index}].capability"
        )
        if capability_id not in dict(profile.capabilities):
            raise MeridianError(f"probe {relative_path} names undeclared capability {capability_id}")
        _required_string(check.get("behavior"), f"probe {relative_path}.checks[{index}].behavior")
        dimensions = _required_string_list(
            check.get("dimensions"), f"probe {relative_path}.checks[{index}].dimensions", non_empty=True
        )
        if len(set(dimensions)) != len(dimensions):
            raise MeridianError(f"probe {relative_path} has duplicate check dimensions")
        covered.add(capability_id)
    data["_coveredCapabilities"] = sorted(covered)
    return data


def profile_doctor(project_root: Path, framework_root: Path, profile_id: str) -> int:
    """Resolve a profile and all repository-owned evidence without mutation."""
    results: list[AuditResult] = []
    try:
        manifest = load_manifest(project_root, framework_root)
        catalog = load_capability_catalog(framework_root)
        profile = catalog.profile(profile_id)
        if profile is None:
            raise MeridianError(f"capability profile is not present in the catalog: {profile_id}")
        declarations = {item.profile_id: item for item in parse_capability_profiles(manifest, catalog)}
        declaration = declarations.get(profile_id)
        if declaration is None:
            raise MeridianError(f"manifest does not declare capability profile: {profile_id}")
        audit_results, _mode = audit_declared_capabilities(
            project_root, framework_root, manifest_workflow_mode(manifest)
        )
        for result in audit_results:
            if result.identity.startswith(f"{profile_id}/") and result.identity.endswith("/installation"):
                results.append(result)
        for capability in declaration.capabilities:
            references = list(capability.installation.evidence)
            references.extend(
                reference
                for _host, snapshot in capability.host_activation
                for reference in snapshot.evidence
            )
            references.extend(capability.verification.evidence)
            for reference in references:
                if reference.startswith(("path:", "probe:")):
                    raw_path = reference.split(":", 1)[1]
                    relative = _repository_relative_path(raw_path, "profile evidence path")
                    status = "PASS" if (project_root / relative).is_file() else "FAIL"
                    results.append(AuditResult(status, f"{profile_id}/evidence/{relative}", "resolved" if status == "PASS" else "missing"))
        ci_probe = _load_profile_probe(
            project_root, profile.verification_probe, profile, "host-neutral-ci"
        )
        missing_ci = sorted(set(dict(profile.capabilities)) - set(ci_probe["_coveredCapabilities"]))
        results.append(AuditResult(
            "FAIL" if missing_ci else "PASS",
            f"{profile_id}/probe/host-neutral-ci",
            "missing capability checks: " + ", ".join(missing_ci) if missing_ci else f"resolved {profile.verification_probe}",
        ))
        supported_by_host: dict[str, set[str]] = {}
        for capability_id, _version in profile.capabilities:
            capability = catalog.capability(capability_id)
            assert capability is not None
            for host_id, _kind in capability.host_profiles:
                supported_by_host.setdefault(host_id, set()).add(capability_id)
        for host_id, probe_path in profile.host_probes:
            probe = _load_profile_probe(project_root, probe_path, profile, host_id)
            missing = sorted(supported_by_host[host_id] - set(probe["_coveredCapabilities"]))
            results.append(AuditResult(
                "FAIL" if missing else "PASS",
                f"{profile_id}/probe/{host_id}",
                "missing capability checks: " + ", ".join(missing) if missing else f"resolved {probe_path}; host state={probe['state']}",
            ))
    except MeridianError as error:
        results.append(AuditResult("FAIL", f"{profile_id}/doctor", str(error)))
    results.sort(key=lambda result: (result.identity, result.detail))
    for result in results:
        print(f"{result.status:14} {result.identity} — {result.detail}")
    failures = sum(result.status == "FAIL" for result in results)
    print(f"SUMMARY profile={profile_id} PASS={sum(result.status == 'PASS' for result in results)} FAIL={failures}")
    return 2 if failures else 0


def _capability_declaration(
    project_root: Path,
    capability: CatalogCapability,
    required_version: int,
    managed_files: dict[str, object],
    strict: bool,
) -> dict[str, object]:
    """One profile capability declaration built from the catalog surface and the
    files on disk; records managed-copy digests into `managed_files`."""
    surfaces: list[dict[str, str]] = []
    evidence: list[str] = []
    complete = True
    for surface in capability.managed_surfaces:
        form = surface.forms[0]
        surfaces.append({"path": surface.path, "form": form})
        path = project_root / surface.path
        if form != "declaration-only" and not path.is_file():
            complete = False
            continue
        if form != "declaration-only":
            digest = sha256(path)
            digest_exempt = (
                form == "managed-copy"
                and not strict
                and _digest_exempt(surface.path, path)
            )
            if form == "managed-copy":
                recorded = managed_files.get(surface.path)
                # Recording the current digest over a different recorded one
                # would launder a drifted copy. A marker-bearing consumer file is
                # verified region by region, so its recorded digest is left alone.
                if recorded is not None and recorded != digest and not digest_exempt:
                    raise MeridianError(
                        f"managed copy {surface.path} differs from the digest recorded at install; "
                        "restore the released text before bootstrapping"
                    )
                if not digest_exempt:
                    managed_files[surface.path] = digest
            evidence.append(f"path:{surface.path}" if digest_exempt else f"sha256:{digest}")
    return {
        "requiredVersion": required_version,
        "managedSurface": surfaces,
        "installation": {
            "state": "INSTALLED" if complete else "MISSING",
            "evidence": sorted(set(evidence)),
            "notApplicableRationale": None,
        },
        "hostActivation": {
            host_id: {
                "state": "UNVERIFIED",
                "evidence": [],
                "notApplicableRationale": None,
            }
            for host_id, _evidence_kind in capability.host_profiles
        },
        "verification": {
            "state": "UNVERIFIED",
            "evidence": [],
            "verifiedAt": None,
            "verifierVersion": None,
            "notApplicableRationale": None,
        },
    }


def bootstrap_capability_profile(
    project_root: Path, framework_root: Path, profile_id: str, *, apply: bool
) -> dict[str, object]:
    """Observe catalog surfaces and conservatively declare one profile.

    Static files can establish installation only. Host activation and
    capability verification remain UNVERIFIED until a versioned probe records
    stronger evidence.
    """
    manifest = load_manifest(project_root, framework_root)
    catalog = load_capability_catalog(framework_root)
    profile = catalog.profile(profile_id)
    if profile is None:
        raise MeridianError(f"capability profile is not present in the catalog: {profile_id}")
    workflow_mode = manifest_workflow_mode(manifest)
    if profile.workflow_modes and workflow_mode not in profile.workflow_modes:
        raise MeridianError(
            f"profile {profile_id} applies to {', '.join(profile.workflow_modes)}, not {workflow_mode}"
        )
    strict = profile_id in STRICT_DIGEST_PROFILES
    declarations: dict[str, object] = {}
    managed_files = dict(manifest.get("managedFiles", {}))
    for capability_id, required_version in profile.capabilities:
        capability = catalog.capability(capability_id)
        assert capability is not None
        if workflow_mode not in capability.workflow_modes:
            raise MeridianError(
                f"profile {profile_id} capability {capability_id} excludes workflow {workflow_mode}"
            )
        declarations[capability_id] = _capability_declaration(
            project_root, capability, required_version, managed_files, strict
        )
    updated = canonical_manifest(manifest)
    profiles = dict(updated.get("capabilityProfiles", {}))
    profiles[profile_id] = {
        "profileVersion": profile.version,
        "capabilities": declarations,
    }
    updated["capabilityProfiles"] = profiles
    updated["managedFiles"] = dict(sorted(managed_files.items()))
    validate_manifest(updated, catalog)
    if apply:
        write_manifest(project_root, updated, framework_root)
    return updated


def detect_capabilities(project_root: Path, mode: str, framework_root: Path) -> list[Capability]:
    if mode != "governed-sdd":
        return []
    requirements = capability_requirements(framework_root)
    presence = capability_presence_map(project_root, mode, framework_root)
    return [
        Capability(migration_id, *presence[capability_id])
        for capability_id, (_required_version, migration_id) in sorted(requirements.items())
    ]


def parse_adoption_review(project_root: Path) -> "ReviewRecord | None":
    path = project_root / ADOPTION_REVIEW_PATH
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    verdict_match = re.search(r"^Verdict:\s*(\S+)\s*$", text, re.MULTILINE)
    attempt_match = re.search(r"^Attempt:\s*(\d+)\s*$", text, re.MULTILINE)
    if not verdict_match or verdict_match.group(1) not in ADOPTION_VERDICTS or not attempt_match:
        raise MeridianError(
            f"adoption review record is missing a machine-readable Verdict/Attempt header: {path}"
        )
    unchecked = len(re.findall(r"^\s*-\s*\[ \]", text, re.MULTILINE))
    return ReviewRecord(verdict=verdict_match.group(1), attempt=int(attempt_match.group(1)), unchecked=unchecked)


def compute_adoption_state(project_root: Path, mode: str, framework_root: Path) -> AdoptionState:
    if mode != "governed-sdd":
        raise MeridianError(
            "assisted adoption tracks capabilities only for governed-sdd mode; "
            "use `meridian adopt --mode lean-delivery --from <version> --check` instead"
        )
    capabilities = detect_capabilities(project_root, mode, framework_root)
    missing = [capability for capability in capabilities if not capability.present]
    review = parse_adoption_review(project_root)

    if review is not None and review.verdict == "CHANGES_REQUESTED" and review.attempt >= ADOPTION_RETRY_LIMIT:
        return AdoptionState(
            "BLOCKED",
            missing,
            review,
            f"two consecutive CHANGES_REQUESTED verdicts (attempt {review.attempt}); "
            f"resolve {project_root / ADOPTION_REVIEW_PATH} manually before retrying",
        )
    if missing:
        if review is not None and review.verdict == "CHANGES_REQUESTED":
            return AdoptionState("ADDRESS_REVIEW", missing, review, "unresolved findings in the adoption review record")
        return AdoptionState("IMPLEMENT_MIGRATION", missing, review, "missing framework capabilities")
    if review is None:
        return AdoptionState(
            "REVIEW_MIGRATION", missing, review, "capabilities detected as present; independent review has not run yet"
        )
    if review.verdict == "CHANGES_REQUESTED":
        return AdoptionState(
            "ADDRESS_REVIEW", missing, review, "reviewer requested changes despite capability detection"
        )
    if review.verdict == "APPROVE":
        if review.unchecked:
            return AdoptionState(
                "BLOCKED", missing, review, "approved adoption review record still has unchecked findings"
            )
        return AdoptionState("FINALIZE", missing, review, "review approved; ready to finalize")
    return AdoptionState("BLOCKED", missing, review, f"unexpected verdict in adoption review record: {review.verdict}")


def assisted_implementer_prompt(
    project_root: Path,
    framework_root: Path,
    mode: str,
    source_version: str,
    missing: list[Capability],
) -> str:
    migration_ids_to_find = [capability.migration for capability in missing]
    migration_ids = ", ".join(migration_ids_to_find)
    records = migration_record_paths(framework_root, migration_ids_to_find)
    deltas = [
        f"- {data['id']}: {data['delta']}"
        for data in (json.loads(path.read_text(encoding="utf-8")) for path in records)
        if data.get("delta")
    ]
    executable = framework_root / "bin" / "meridian"
    return "\n".join(
        [
            "Perform the capability-aware Meridian adoption migration for this project.",
            "",
            "Read the local LANGUAGE_POLICY.md, PROJECT_WORKFLOW.md, AGENTS.md,",
            "and docs/CONTEXT_BUDGET_POLICY.md before editing.",
            "Read these framework migration records before planning the change:",
            *[f"- {path}" for path in records],
            f"- {framework_root / 'migrations/ASSISTED_ADOPTION.md'}",
            f"The project is adopting from Meridian {source_version} in {mode} mode.",
            f"Implement only these missing framework capabilities: {migration_ids}.",
            *(
                [
                    "",
                    "For a capability already partially present at an older version, apply only this",
                    "delta — do not rewrite the capability from scratch:",
                    *deltas,
                ]
                if deltas
                else []
            ),
            "",
            "Use the project's established paths, terminology, governance, validation, and Git rules.",
            "Preserve every capability already detected as present. Do not replace local workflow",
            f"documents with generic Meridian templates and do not run `{executable} adopt --apply`.",
            f"If {project_root / '.meridian/adoption-review.md'} exists, read it and address only its",
            "unchecked findings; otherwise implement the missing capability named above.",
            "Create a dedicated migration branch, then run only the project checks whose surface the",
            "migration actually touches — this migration edits documentation/policy text, so skip the",
            "project's full build/test/lint suite and state that explicitly instead of running it",
            "defensively. Commit only this bounded migration. Do not review your own work and do not",
            "run `finalize-adoption`.",
            "",
            "Report the changed files, validation evidence, and the named migration IDs for a fresh",
            "independent reviewer. After an APPROVE verdict, run:",
            f"{executable} finalize-adoption --project {project_root} --mode {mode}",
        ]
    )


def assisted_reviewer_prompt(
    project_root: Path,
    framework_root: Path,
    mode: str,
    source_version: str,
    missing: list[Capability],
) -> str:
    migration_ids_to_find = [capability.migration for capability in missing]
    records = migration_record_paths(framework_root, migration_ids_to_find)
    executable = framework_root / "bin" / "meridian"
    review_path = project_root / ADOPTION_REVIEW_PATH
    if missing:
        scope_line = "Review only the missing capabilities named by the adoption plan."
    else:
        scope_line = (
            "No capability is reported missing; independently confirm that detection is correct "
            "and that no prior migration attempt is incomplete."
        )
    return "\n".join(
        [
            "Independently review the completed capability-aware Meridian adoption migration.",
            "",
            "This reviewer session must be fresh and must not have implemented the migration.",
            "Read the local LANGUAGE_POLICY.md, PROJECT_WORKFLOW.md, AGENTS.md,",
            "docs/CONTEXT_BUDGET_POLICY.md, the exact migration diff, and these records:",
            *[f"- {path}" for path in records],
            f"- {framework_root / 'migrations/ASSISTED_ADOPTION.md'}",
            f"The project is adopting from Meridian {source_version} in {mode} mode.",
            "",
            scope_line,
            "Confirm that existing review-remediation behavior and local project workflow",
            "customizations remain intact. Verify the migration record's criteria and that no generic",
            "template replacement or unrelated workflow change is included. Verify validation evidence",
            "is scoped to the actual diff surface: a documentation/policy-only migration should report",
            "the project's full build/test/lint suite as explicitly skipped, not run defensively; flag",
            "it as a finding if disproportionate validation output was run and presented as evidence, or",
            "if a command that should have run for the actual diff was skipped instead. Do not edit",
            "implementation artifacts or repair findings during review.",
            "",
            f"Write your verdict as a machine-readable record at {review_path} with this exact header",
            "shape (increment Attempt by one from any prior record; use 0 if none exists):",
            "Verdict: APPROVE | CHANGES_REQUESTED | BLOCKED",
            "Attempt: <n>",
            "then a `## Findings` list using `- [ ]` for each open finding (leave empty, or check every",
            "item `- [x]`, only when the verdict is APPROVE). Commit only that review record.",
            "",
            "After APPROVE with zero unchecked findings only, register the deterministic framework",
            "baseline with:",
            f"{executable} finalize-adoption --project {project_root} --mode {mode}",
            "Then review the resulting manifest and baseline snapshot diff and commit it with the",
            "approved migration. On CHANGES_REQUESTED or BLOCKED, do not finalize adoption.",
        ]
    )


def assisted_orchestrator_prompt(
    project_root: Path, framework_root: Path, mode: str, source_version: str
) -> str:
    executable = framework_root / "bin" / "meridian"
    command = (
        f"{executable} adopt --project {project_root} --mode {mode} "
        f"--from {source_version} --assisted --check"
    )
    return "\n".join(
        [
            "Coordinate a capability-aware Meridian adoption as a stateless loop. Do not implement or",
            "review the migration yourself, and never copy an implementer's or reviewer's chat context",
            "into the next session — only the fields below cross a session boundary.",
            "",
            f"Repeat: run `{command}` and read its first `NEXT_ACTION <value>` line plus its exit code.",
            "",
            "NEXT_ACTION IMPLEMENT_MIGRATION or ADDRESS_REVIEW (exit 3): start a fresh implementer",
            "session (a distinct Task-tool subagent when this host supports one, otherwise a separate",
            "chat) and send it the exact text between IMPLEMENTER_PROMPT_BEGIN and IMPLEMENTER_PROMPT_END",
            f"(or `{executable} adopt ... --assisted --check --emit implementer` to fetch just that block).",
            "Wait for it to report completion, then loop.",
            "",
            "NEXT_ACTION REVIEW_MIGRATION or ADDRESS_REVIEW's next pass (exit 3): start a fresh reviewer",
            "session that did not implement the migration and send it the text between",
            "REVIEWER_PROMPT_BEGIN and REVIEWER_PROMPT_END (or `--emit reviewer`). Wait for it to commit",
            f"its verdict to {project_root / ADOPTION_REVIEW_PATH}, then loop.",
            "",
            "NEXT_ACTION FINALIZE (exit 0, READY_TO_FINALIZE): have the reviewer that approved the",
            "migration run the emitted absolute finalize-adoption command, inspect the manifest/baseline",
            "diff, and commit it together with the approved migration. Never run generic adopt --apply",
            "for an assisted adoption.",
            "",
            "Exit 2 (a BLOCKED ADOPTION_BLOCKED line): stop immediately and report the exact printed line — this covers two",
            "consecutive CHANGES_REQUESTED verdicts and any malformed review record. A developer must",
            "resolve the underlying issue before an orchestrator restarts the loop.",
            "",
            "The command's own state (capability detection plus the adoption review record) is the only",
            "handoff interface; do not track progress in the chat.",
        ]
    )


def print_assisted_adoption_plan(
    project_root: Path,
    framework_root: Path,
    mode: str,
    source_version: str,
    emit: str | None = None,
) -> int:
    state = compute_adoption_state(project_root, mode, framework_root)
    snapshot_workflow = (
        framework_root
        / "release-baselines"
        / source_version
        / "templates"
        / "workflows"
        / mode
    )
    if not snapshot_workflow.is_dir():
        raise MeridianError(
            f"no packaged baseline for {mode} {source_version}; adoption cannot infer it safely"
        )

    if emit is not None:
        if emit == "orchestrator":
            print(assisted_orchestrator_prompt(project_root, framework_root, mode, source_version))
        elif emit == "implementer":
            if state.action not in ("IMPLEMENT_MIGRATION", "ADDRESS_REVIEW"):
                raise MeridianError(f"no implementer prompt applies to the current state: {state.action}")
            print(
                assisted_implementer_prompt(
                    project_root, framework_root, mode, source_version, state.missing
                )
            )
        elif emit == "reviewer":
            if state.action not in ("REVIEW_MIGRATION", "ADDRESS_REVIEW"):
                raise MeridianError(f"no reviewer prompt applies to the current state: {state.action}")
            print(
                assisted_reviewer_prompt(
                    project_root, framework_root, mode, source_version, state.missing
                )
            )
        return 0 if state.action == "FINALIZE" else (2 if state.action == "BLOCKED" else 3)

    target_version = read_version(framework_root)
    print(f"Assisted adoption {source_version} -> {target_version} ({mode})")
    capabilities = detect_capabilities(project_root, mode, framework_root)
    for capability in capabilities:
        capability_state = "PRESENT" if capability.present else "MISSING"
        print(f"CAPABILITY {capability_state:7} {capability.migration} — {capability.evidence}")

    if state.action == "BLOCKED":
        raise stop_error("ADOPTION_BLOCKED", state.reason)

    if state.action in ("IMPLEMENT_MIGRATION", "ADDRESS_REVIEW"):
        print("AGENT_REQUIRED")
        for capability in state.missing:
            print(f"MIGRATION {capability.migration}")
        print(f"NEXT_ACTION {state.action}")
        if state.review is not None:
            print(f"ATTEMPT {state.review.attempt}")
        print("IMPLEMENTER_PROMPT_BEGIN")
        print(
            assisted_implementer_prompt(
                project_root, framework_root, mode, source_version, state.missing
            )
        )
        print("IMPLEMENTER_PROMPT_END")
        print("REVIEWER_PROMPT_BEGIN")
        print(
            assisted_reviewer_prompt(
                project_root, framework_root, mode, source_version, state.missing
            )
        )
        print("REVIEWER_PROMPT_END")
        print("ORCHESTRATOR_PROMPT_BEGIN")
        print(assisted_orchestrator_prompt(project_root, framework_root, mode, source_version))
        print("ORCHESTRATOR_PROMPT_END")
        print("No files were changed.")
        return 3

    if state.action == "REVIEW_MIGRATION":
        print("AGENT_REQUIRED")
        print(f"NEXT_ACTION {state.action}")
        print("REVIEWER_PROMPT_BEGIN")
        print(
            assisted_reviewer_prompt(
                project_root, framework_root, mode, source_version, state.missing
            )
        )
        print("REVIEWER_PROMPT_END")
        print("ORCHESTRATOR_PROMPT_BEGIN")
        print(assisted_orchestrator_prompt(project_root, framework_root, mode, source_version))
        print("ORCHESTRATOR_PROMPT_END")
        print("No files were changed.")
        return 3

    print("READY_TO_FINALIZE")
    print("NEXT_ACTION FINALIZE")
    print("No files were changed.")
    return 0


def copy_baseline(
    project_root: Path,
    framework_root: Path,
    mode: str,
    version: str,
    managed_files_override: list[ManagedFile] | None = None,
) -> None:
    destination_root = project_root / BASELINES_PATH / version
    for item in managed_files_override or managed_files(framework_root, mode):
        destination = destination_root / item.target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.source, destination)


def prune_stale_baselines(project_root: Path, keep_version: str) -> None:
    """Remove every baseline snapshot except the one the manifest now points at.

    Only the baseline matching `manifest.workflowBaselineVersion` is ever read again
    (see `plan_upgrade`); older snapshots are dead weight the moment an
    upgrade or adoption completes.
    """
    baselines_root = project_root / BASELINES_PATH
    if not baselines_root.is_dir():
        return
    for entry in baselines_root.iterdir():
        if entry.is_dir() and entry.name != keep_version:
            shutil.rmtree(entry)


def lock_project(
    project_root: Path,
    framework_root: Path,
    mode: str,
) -> None:
    require_release_version(framework_root)
    version = read_version(framework_root)
    baseline_version = latest_migration_to(framework_root, version)
    files = managed_files(framework_root, mode)
    missing = [str(item.target) for item in files if not (project_root / item.target).is_file()]
    if missing:
        raise MeridianError("project is missing managed files: " + ", ".join(missing))

    copy_baseline(project_root, framework_root, mode, baseline_version)
    manifest = {
        "frameworkVersion": version,
        "protocolVersion": PROTOCOL_VERSION,
        "workflowMode": mode,
        "managedFiles": {str(item.target): sha256(item.source) for item in files},
        "appliedMigrations": migration_ids(framework_root, "0.0.0", baseline_version),
    }
    manifest["workflowBaselineVersion"] = baseline_version
    write_manifest(project_root, manifest, framework_root)
    print(f"Locked {project_root} to Meridian {version} ({mode}).")


def merge_clean(local: Path, base: Path, incoming: Path) -> tuple[bool, bytes]:
    with tempfile.TemporaryDirectory(prefix="meridian-merge-") as directory:
        output = Path(directory) / "merged"
        process = subprocess.run(
            ["git", "merge-file", "-p", str(local), str(base), str(incoming)],
            check=False,
            capture_output=True,
        )
        # git merge-file returns the number of conflicts (not merely 1) for a
        # successful merge operation with conflict markers. Only 128+ signals
        # a command failure.
        if process.returncode >= 128:
            detail = process.stderr.decode("utf-8", errors="replace").strip()
            raise MeridianError(detail or "git merge-file failed")
        output.write_bytes(process.stdout)
        return process.returncode == 0, output.read_bytes()


def apply_additive_move_checks(
    plan: list[PlanItem],
    project_root: Path,
    framework_root: Path,
    mode: str,
    baseline_root: Path,
    pending_migrations: list[str],
) -> list[PlanItem]:
    """Turn unsafe pending additive moves into deterministic upgrade conflicts.

    A normal three-way merge only reasons about whole files. A capability move
    instead proves the protected block itself: the old marker must be identical
    to the installed baseline, while unrelated project-owned text in that file
    remains eligible for preservation. A pre-created destination may be
    retained only if it is the exact released marker block.
    """
    by_target = {item.file.target: index for index, item in enumerate(plan)}
    derived_entry_points = {
        item.file.target for item in plan if item.action == "router"
    }

    def conflict(target: Path, detail: str) -> None:
        index = by_target[target]
        plan[index] = PlanItem(plan[index].file, "conflict", detail)

    for move in declared_capability_moves(framework_root, pending_migrations):
        if move.stage not in ("additive", "retirement"):
            continue
        if move.source_path in derived_entry_points or move.target_path in derived_entry_points:
            continue
        source_base = baseline_root / move.source_path
        source_local = project_root / move.source_path
        if not source_base.is_file() or not source_local.is_file():
            conflict(move.source_path, f"capability move {move.migration} source baseline or local file is missing")
            continue
        base_text = source_base.read_text(encoding="utf-8")
        local_text = source_local.read_text(encoding="utf-8")
        if move.source_path == Path("CLAUDE.md") and is_agents_pointer(local_text):
            # A declared pointer deliberately owns no duplicated Claude marker;
            # the matching AGENTS move supplies the source proof instead.
            continue
        source_in_intermediate_state = False
        if not exact_marker_matches(base_text, move.source_capability, move.source_version, move.source_sha256):
            source_in_intermediate_state = (
                not marker_blocks(base_text, move.source_capability, move.source_version)
                and not marker_blocks(local_text, move.source_capability, move.source_version)
                and pending_migration_establishes_move_source(
                    framework_root, pending_migrations, move
                )
            )
            if not source_in_intermediate_state:
                conflict(move.source_path, f"capability move {move.migration} source does not match the installed baseline")
                continue
        if not source_in_intermediate_state and not exact_marker_matches(
            local_text, move.source_capability, move.source_version, move.source_sha256
        ):
            conflict(move.source_path, f"capability move {move.migration} source marker was locally modified or duplicated")
            continue
        target_local = project_root / move.target_path
        if target_local.is_file():
            target_text = target_local.read_text(encoding="utf-8")
            if not exact_marker_matches(
                target_text, move.target_capability, move.target_version, move.target_sha256
            ):
                conflict(move.target_path, f"capability move {move.migration} target marker is not exact")
                continue
            current = plan[by_target[move.target_path]]
            if move.stage == "additive" and current.action == "conflict" and not (baseline_root / move.target_path).is_file():
                plan[by_target[move.target_path]] = PlanItem(
                    current.file,
                    "keep",
                    f"pre-created target marker for capability move {move.migration} is exact",
                )
        elif move.stage == "retirement":
            planned_target = plan[by_target[move.target_path]]
            incoming_target = planned_target.file.source.read_text(encoding="utf-8")
            if planned_target.action != "add" or not exact_marker_matches(
                incoming_target, move.target_capability, move.target_version, move.target_sha256
            ):
                conflict(move.target_path, f"capability move {move.migration} target file is missing")
        if move.stage == "retirement":
            current = plan[by_target[move.source_path]]
            if current.action == "append-markers":
                plan[by_target[move.source_path]] = PlanItem(
                    current.file,
                    "append-retire-markers",
                    "update required marker versions, then retire declared duplicate marker blocks "
                    "without touching other local text",
                )
    return plan


def plan_from_baseline(
    project_root: Path,
    framework_root: Path,
    mode: str,
    installed_version: str,
    baseline_root: Path,
    applied_migrations: list[object],
    target_version_override: str | None = None,
    managed_files_override: list[ManagedFile] | None = None,
    installed_framework_version: str | None = None,
    capability_profiles: object | None = None,
) -> tuple[dict[str, object], list[PlanItem]]:
    target_framework_version = target_version_override or read_version(framework_root)
    target_baseline_version = latest_migration_to(framework_root, target_framework_version)
    if version_key(target_baseline_version) < version_key(installed_version):
        raise MeridianError("framework source is older than the project lockfile")
    if not baseline_root.is_dir():
        raise MeridianError(f"baseline snapshot is missing: {baseline_root}")

    manifest: dict[str, object] = {
        "frameworkVersion": installed_framework_version or installed_version,
        "workflowBaselineVersion": installed_version,
        "workflowMode": mode,
        "appliedMigrations": applied_migrations,
    }
    if capability_profiles is not None:
        manifest["capabilityProfiles"] = capability_profiles
        manifest["protocolVersion"] = PROTOCOL_VERSION

    requirements = capability_requirements(framework_root)
    applied = {str(migration) for migration in applied_migrations}
    pending_migrations = [
        migration
        for migration in migration_ids(framework_root, installed_version, target_baseline_version)
        if migration not in applied
    ]
    adoptable_paths = adopt_existing_paths(framework_root, pending_migrations)

    planned_files = managed_files_override or managed_files(framework_root, mode)
    declared_copy_paths = declared_managed_copy_paths(manifest, framework_root)
    router_project = project_uses_entry_router(project_root)
    router_problems = entry_router_trigger_requirements(
        project_root, framework_root, pending_migrations, planned_files
    )
    router_problem_owner = Path("AGENTS.md")

    plan = []
    for item in planned_files:
        if router_project and item.target in {Path("AGENTS.md"), Path("CLAUDE.md")}:
            plan.append(
                PlanItem(
                    item,
                    "router",
                    f"generated from {ENTRY_ROUTER_PATH}; template merge is disabled",
                    router_problems if item.target == router_problem_owner else (),
                )
            )
            continue
        local = project_root / item.target
        base = baseline_root / item.target
        if not base.is_file():
            if local.exists():
                if item.target not in adoptable_paths or not local.is_file():
                    plan.append(PlanItem(item, "conflict", "managed baseline is missing"))
                elif sha256(local) == sha256(item.source):
                    plan.append(
                        PlanItem(
                            item,
                            "adopt",
                            "existing file matches target; record the managed baseline",
                        )
                    )
                else:
                    backup = _unused_adoption_backup(local).relative_to(project_root)
                    plan.append(
                        PlanItem(
                            item,
                            "adopt-replace",
                            f"replace existing file after preserving it as {backup}",
                            backup=backup,
                        )
                    )
            else:
                plan.append(PlanItem(item, "add", "new managed file"))
            continue
        if not local.is_file():
            plan.append(PlanItem(item, "conflict", "local managed file is missing"))
            continue
        if (
            sha256(local) != sha256(base)
            and is_markerless_managed_copy_digest_audited(
                project_root, str(item.target), declared_copy_paths
            )
        ):
            plan.append(
                PlanItem(
                    item,
                    "edited-copy",
                    "local edits will remain outside the released digest and make `meridian audit` fail; "
                    "restore the released text and keep project content in the project's own files",
                )
            )
        if sha256(item.source) == sha256(base):
            local_text = local.read_text(encoding="utf-8")
            if (
                item.target == Path("CLAUDE.md")
                and CLAUDE_AGENTS_POINTER_MARKER not in local_text
                and "036-explicit-claude-agents-pointer" in pending_migrations
                and agents_pointer_satisfies_claude(
                    project_root, framework_root, mode, item.source.read_text(encoding="utf-8"), local_text
                )
            ):
                plan.append(
                    PlanItem(
                        item,
                        "pointer-upgrade",
                        "add the explicit Claude-to-AGENTS pointer marker without changing project-owned pointer text",
                    )
                )
                continue
            normalized = deduplicate_identical_template_markers(
                local_text, item.source.read_text(encoding="utf-8")
            )
            if normalized is not None:
                plan.append(
                    PlanItem(
                        item,
                        "deduplicate-markers",
                        "template unchanged, but local file contains duplicate identical protected marker(s)",
                    )
                )
            else:
                plan.append(PlanItem(item, "keep", "template unchanged"))
        elif sha256(local) == sha256(base):
            plan.append(PlanItem(item, "replace", "local file matches installed baseline"))
        elif sha256(local) == sha256(item.source):
            plan.append(PlanItem(item, "keep", "local file already matches target"))
        else:
            clean, merged = merge_clean(local, base, item.source)
            if clean:
                merged_text = merged.decode("utf-8")
                if deduplicate_identical_template_markers(
                    merged_text, item.source.read_text(encoding="utf-8")
                ) is not None:
                    plan.append(
                        PlanItem(
                            item,
                            "merge-deduplicate-markers",
                            "three-way merge duplicated an identical new protected marker; retain one canonical copy",
                        )
                    )
                else:
                    plan.append(PlanItem(item, "merge", "three-way merge"))
                continue
            local_text = local.read_text(encoding="utf-8")
            base_text = base.read_text(encoding="utf-8")
            template_text = item.source.read_text(encoding="utf-8")
            if item.target == Path("CLAUDE.md") and agents_pointer_can_follow_upgrade(
                project_root, framework_root, mode, baseline_root, template_text, local_text
            ):
                legacy_pointer = CLAUDE_AGENTS_POINTER_MARKER not in local_text
                action = (
                    "pointer-upgrade"
                    if legacy_pointer and "036-explicit-claude-agents-pointer" in pending_migrations
                    else "pointer-verified"
                )
                plan.append(
                    PlanItem(
                        item,
                        action,
                        "project declares CLAUDE.md as an AGENTS.md pointer; shared markers are current or "
                        "will be updated safely in AGENTS.md",
                    )
                )
                continue
            wrapped = [
                f"{capability} v{version}"
                for capability, version in pending_wrapped_capabilities(
                    framework_root, pending_migrations, item.target
                )
                if extract_marker_block(local_text, capability, version) is None
            ]
            if wrapped:
                plan.append(
                    PlanItem(
                        item,
                        "conflict",
                        f"three-way merge conflicted inside text the new {', '.join(wrapped)} block wraps; "
                        "reconcile the edit by hand or move project text outside the block",
                    )
                )
                continue
            restructured = [
                f"{capability} v{version}"
                for capability, version in pending_restructured_markers(
                    framework_root, pending_migrations, item.target
                )
                if extract_marker_block(local_text, capability, version) is not None
            ]
            if restructured:
                backup = _unused_adoption_backup(local, "pre-restructure").relative_to(project_root)
                carried = len(project_sections(local_text, base_text, template_text))
                edited = restructured_marker_edits(
                    local_text,
                    base_text,
                    pending_restructured_markers(framework_root, pending_migrations, item.target),
                )
                edited_detail = (
                    "; edited retired marker content "
                    f"({', '.join(f'{capability} v{version}' for capability, version in edited)}) "
                    "will be removed from carried project sections; the original remains in the backup"
                    if edited
                    else ""
                )
                plan.append(
                    PlanItem(
                        item,
                        "restructure",
                        f"three-way merge conflicted around retired inline marker(s) ({', '.join(restructured)}); "
                        f"replace with the standalone template block after preserving the current file as {backup}"
                        + (f" and carrying over {carried} project section(s)" if carried else "")
                        + edited_detail
                        + "; re-apply any project prose from the backup after the managed block",
                        backup=backup,
                    )
                )
                continue
            capability_ids = capability_ids_in_template(item.source)
            marker_append = append_only_new_markers(local_text, base_text, template_text)
            if marker_append is not None:
                local_by_name = dict(marker_pairs(local_text))
                added = [
                    capability
                    for capability, version in marker_pairs(template_text)
                    if capability not in local_by_name
                ]
                superseded = [
                    f"{capability} v{local_by_name[capability]}->v{version}"
                    for capability, version in marker_pairs(template_text)
                    if capability in local_by_name and version > local_by_name[capability]
                ]
                detail = "three-way merge conflicted, but existing protected markers are intact; "
                parts = []
                if added:
                    parts.append(f"add new marker block(s) ({', '.join(added)})")
                if superseded:
                    parts.append(f"replace superseded block(s) in place ({', '.join(superseded)})")
                detail += " and ".join(parts) + " without touching other local text"
                pending_removals = removals_for_managed_file(framework_root, pending_migrations, item.target)
                if pending_removals:
                    retired_append = remove_retired_markers(
                        marker_append,
                        base_text,
                        [(capability, version) for capability, version, _superseded_by in pending_removals],
                    )
                    if retired_append is None:
                        plan.append(
                            PlanItem(
                                item,
                                "conflict",
                                "a retired capability block was edited locally; reconcile it by hand "
                                "before this upgrade can remove it",
                            )
                        )
                        continue
                    if retired_append != marker_append:
                        plan.append(
                            PlanItem(
                                item,
                                "append-retire-markers",
                                detail + "; then retire the declared capability block(s) "
                                "that still match the installed baseline",
                            )
                        )
                        continue
                plan.append(
                    PlanItem(
                        item,
                        "append-markers",
                        detail,
                    )
                )
                continue
            normalized_markers = reflowed_marker_normalization(local_text, template_text)
            if normalized_markers is not None:
                plan.append(
                    PlanItem(
                        item,
                        "normalize-markers",
                        "three-way merge conflicted, but protected marker content differs only by prose line wrapping; normalize to the current canonical block",
                    )
                )
                continue
            removals = removals_for_managed_file(framework_root, pending_migrations, item.target)
            retirement_conflict = False
            if removals:
                removal_pairs = [(capability, version) for capability, version, _superseded_by in removals]
                retired = remove_retired_markers(local_text, base_text, removal_pairs)
                if retired is not None and retired != local_text:
                    labels = [
                        f"{capability} -> {superseded_by}" if superseded_by else capability
                        for capability, _version, superseded_by in removals
                    ]
                    plan.append(
                        PlanItem(
                            item,
                            "retire-markers",
                            "three-way merge conflicted, but the retired capability block(s) "
                            f"({', '.join(labels)}) still matched the installed baseline and were "
                            "removed in place",
                        )
                    )
                    continue
                # A locally modified block awaiting retirement must never be
                # silently downgraded to VERIFIED below: `capability_ids`
                # comes from the *current* template, which by definition no
                # longer carries a capability this migration just retired, so
                # that check alone is blind to this exact conflict.
                retirement_conflict = retired is None
            satisfied_here = (
                not retirement_conflict
                and capability_ids
                and all(
                    extract_marker_block(local_text, capability_id, requirements[capability_id][0])
                    is not None
                    and extract_marker_block(local_text, capability_id, requirements[capability_id][0])
                    == extract_marker_block(template_text, capability_id, requirements[capability_id][0])
                    for capability_id in capability_ids
                )
            )
            if satisfied_here:
                plan.append(
                    PlanItem(
                        item,
                        "verified",
                        "three-way merge conflicted, but this file's own capability marker(s) "
                        f"({', '.join(sorted(capability_ids))}) already satisfy the required version — "
                        "left untouched",
                    )
                )
            else:
                plan.append(PlanItem(item, "conflict", "three-way merge"))
    if mode == "governed-sdd":
        plan = apply_additive_move_checks(
            plan,
            project_root,
            framework_root,
            mode,
            baseline_root,
            pending_migrations,
        )
    if capability_profiles is not None:
        plan.extend(profile_surface_plan(project_root, framework_root, manifest))
    return manifest, plan


def recorded_managed_digests(project_root: Path) -> dict[str, object]:
    try:
        recorded = json.loads((project_root / MANIFEST_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    digests = recorded.get("managedFiles") if isinstance(recorded, dict) else None
    return dict(digests) if isinstance(digests, dict) else {}


def profile_surface_plan(
    project_root: Path, framework_root: Path, manifest: dict[str, object]
) -> list[PlanItem]:
    """One row per profile capability whose declared surface is a strict subset
    of the target catalog surface. A managed copy that drifted from its recorded
    digest is a conflict here, so apply stops before it writes anything."""
    catalog = load_capability_catalog(framework_root)
    gaps: list[tuple[str, str, tuple[str, ...]]] = []
    parse_capability_profiles(manifest, catalog, gaps)
    recorded = recorded_managed_digests(project_root)
    items: list[PlanItem] = []
    for profile_id, capability_id, missing in gaps:
        capability = catalog.capability(capability_id)
        assert capability is not None
        label = f"{profile_id}/{capability_id}"
        drifted = [
            surface.path
            for surface in capability.managed_surfaces
            if surface.forms[0] == "managed-copy"
            and (project_root / surface.path).is_file()
            and recorded.get(surface.path) not in (None, sha256(project_root / surface.path))
            and not (
                profile_id not in STRICT_DIGEST_PROFILES
                and _digest_exempt(surface.path, project_root / surface.path)
            )
        ]
        target = ManagedFile(framework_root / missing[0], Path(missing[0]))
        if drifted:
            items.append(
                PlanItem(
                    target,
                    "conflict",
                    f"{label}: managed copy {', '.join(drifted)} differs from the digest recorded at "
                    "install; restore the released text before upgrading",
                    profile_surface=(profile_id, capability_id),
                )
            )
        else:
            items.append(
                PlanItem(
                    target,
                    "profile-surface",
                    f"{label}: add {', '.join(missing)}",
                    profile_surface=(profile_id, capability_id),
                )
            )
    return items


def prepare_upgrade_targets(
    project_root: Path, framework_root: Path, stop_before_retirement: bool
) -> tuple[dict[str, object], str | None, list[ManagedFile] | None]:
    """The manifest, plus an effective target-version cap and matching
    managed-files substitution when `--stop-before-retirement` is set and it
    actually narrows the upgrade. Both are `None` when the flag is unset, or
    the pending migrations contain no retirement-stage move (a full,
    unmodified upgrade)."""
    manifest = load_manifest(project_root, framework_root, defer_surface_gaps=True)
    if not stop_before_retirement:
        return manifest, None, None
    installed_version = manifest_baseline_version(manifest)
    full_target = read_version(framework_root)
    capped_target = capped_target_version(framework_root, installed_version, full_target)
    if capped_target == full_target:
        return manifest, None, None
    applied = {str(migration) for migration in manifest.get("appliedMigrations", [])}
    full_pending = set(migration_ids(framework_root, installed_version, full_target)) - applied
    capped_pending = set(migration_ids(framework_root, installed_version, capped_target)) - applied
    excluded = full_pending - capped_pending
    scratch_dir = Path(tempfile.mkdtemp(prefix="meridian-capped-"))
    baseline_root = project_root / BASELINES_PATH / installed_version
    managed_override = capped_managed_files(
        framework_root, manifest_workflow_mode(manifest), baseline_root, excluded, scratch_dir
    )
    return manifest, capped_target, managed_override


def plan_upgrade(
    project_root: Path, framework_root: Path, stop_before_retirement: bool = False
) -> tuple[dict[str, object], list[PlanItem]]:
    manifest, target_override, managed_override = prepare_upgrade_targets(
        project_root, framework_root, stop_before_retirement
    )
    installed_version = manifest_baseline_version(manifest)
    return plan_from_baseline(
        project_root,
        framework_root,
        manifest_workflow_mode(manifest),
        installed_version,
        project_root / BASELINES_PATH / installed_version,
        list(manifest.get("appliedMigrations", [])),
        target_version_override=target_override,
        managed_files_override=managed_override,
        installed_framework_version=str(manifest.get("frameworkVersion", "")),
        capability_profiles=manifest.get("capabilityProfiles"),
    )


def print_plan(
    project_root: Path,
    manifest: dict[str, object],
    framework_root: Path,
    plan: list[PlanItem],
    target_version_override: str | None = None,
) -> None:
    target_version = target_version_override or read_version(framework_root)
    installed_baseline_version = manifest_baseline_version(manifest)
    target_baseline_version = latest_migration_to(framework_root, target_version)
    print(
        f"Meridian {installed_baseline_version} -> {target_baseline_version} "
        f"({manifest_workflow_mode(manifest)})"
    )
    framework_delta = f"Framework: {manifest['frameworkVersion']} -> {target_version}"
    if (
        str(manifest["frameworkVersion"]) != target_version
        and installed_baseline_version == target_baseline_version
    ):
        framework_delta += " (CLI-only; no baseline change)"
    print(framework_delta)
    applied = {str(item) for item in manifest.get("appliedMigrations", [])}
    pending = [
        migration
        for migration in migration_ids(
            framework_root, installed_baseline_version, target_baseline_version
        )
        if migration not in applied
    ]
    for migration in pending:
        print(f"MIGRATION {migration}")
    for item in plan:
        if item.action == "profile-surface":
            print(f"PROFILE-SURFACE {item.detail}")
            continue
        print(f"{item.action.upper():8} {item.file.target} — {item.detail}")
        for problem in item.problems:
            print(f"MISSING-ROUTER {problem}")
    if legacy_budget_migration_needed(project_root):
        print("MIGRATE  .meridian/budget.json — remove legacy budget state from the index; commit its deletion")
    conflicts = sum(item.action == "conflict" for item in plan)
    edited_copies = sum(item.action == "edited-copy" for item in plan)
    router_blockers = sum(bool(item.problems) for item in plan)
    if edited_copies:
        print(f"WARNING: {edited_copies} edited managed copy/copies will fail the digest audit after upgrade.")
    if conflicts:
        print(format_stop("UPGRADE_BLOCKED", f"{conflicts} conflict(s); no files were changed"))
    if router_blockers:
        print(format_stop("UPGRADE_BLOCKED", f"{router_blockers} router requirement(s); no files were changed"))


def plan_has_blockers(plan: list[PlanItem], owner_reconciled: bool = False) -> bool:
    """Whether apply/check must stop before writing any project file."""
    return any(item.problems or (item.action == "conflict" and not owner_reconciled) for item in plan)


def _unused_adoption_backup(path: Path, kind: str = "pre-adoption") -> Path:
    """Choose a deterministic adjacent backup path without reusing an existing name."""
    first = path.with_name(path.name + f".meridian-{kind}.bak")
    if not first.exists():
        return first
    suffix = 1
    while True:
        candidate = first.with_name(first.name + f".{suffix}")
        if not candidate.exists():
            return candidate
        suffix += 1


def complete_profile_surfaces(
    project_root: Path,
    framework_root: Path,
    manifest: dict[str, object],
    plan: list[PlanItem],
) -> None:
    """Rebuild each declaration the plan marked as lacking catalog surfaces, in the
    manner of `bootstrap_capability_profile`. Host-activation and verification
    snapshots are kept; only the surface list and installation evidence change."""
    affected = [item.profile_surface for item in plan if item.profile_surface is not None]
    if not affected:
        return
    catalog = load_capability_catalog(framework_root)
    profiles = manifest["capabilityProfiles"]
    managed = dict(manifest["managedFiles"])
    for profile_id, capability_id in affected:
        profile = catalog.profile(profile_id)
        capability = catalog.capability(capability_id)
        assert profile is not None and capability is not None
        declaration = profiles[profile_id]["capabilities"][capability_id]
        rebuilt = _capability_declaration(
            project_root,
            capability,
            dict(profile.capabilities)[capability_id],
            managed,
            profile_id in STRICT_DIGEST_PROFILES,
        )
        for field in ("hostActivation", "verification"):
            if field == "hostActivation":
                rebuilt[field] = {**rebuilt[field], **declaration[field]}
            else:
                rebuilt[field] = declaration[field]
        profiles[profile_id]["capabilities"][capability_id] = rebuilt
    manifest["managedFiles"] = dict(sorted(managed.items()))


def apply_plan(
    project_root: Path,
    framework_root: Path,
    manifest: dict[str, object],
    plan: list[PlanItem],
    baseline_root: Path,
    owner_reconciled: bool = False,
    target_version_override: str | None = None,
    managed_files_override: list[ManagedFile] | None = None,
) -> None:
    print_plan(project_root, manifest, framework_root, plan, target_version_override=target_version_override)
    if plan_has_blockers(plan, owner_reconciled=owner_reconciled):
        raise MeridianError("upgrade has blocking plan items")

    installed_version = manifest_baseline_version(manifest)
    target_version = target_version_override or read_version(framework_root)
    target_baseline_version = latest_migration_to(framework_root, target_version)
    if owner_reconciled:
        print(
            "Owner-reconciled upgrade: skipped automatic file changes for every managed "
            "file, trusting that local content was already brought to the target version "
            "by hand outside the three-way merge."
        )
    else:
        applied = {str(migration) for migration in manifest.get("appliedMigrations", [])}
        pending_migrations = [
            migration
            for migration in migration_ids(framework_root, installed_version, target_baseline_version)
            if migration not in applied
        ]
        for item in plan:
            local = project_root / item.file.target
            if item.action == "replace" or item.action == "add":
                local.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item.file.source, local)
            elif item.action == "adopt-replace":
                if item.backup is None:
                    raise MeridianError(f"adoption backup is missing for {item.file.target}")
                _write_exclusive_backup(local, project_root / item.backup)
                shutil.copyfile(item.file.source, local)
            elif item.action == "restructure":
                if item.backup is None:
                    raise MeridianError(f"restructure backup is missing for {item.file.target}")
                local_text = local.read_text(encoding="utf-8")
                updated = restructured_text(
                    local_text,
                    (baseline_root / item.file.target).read_text(encoding="utf-8"),
                    item.file.source.read_text(encoding="utf-8"),
                    pending_restructured_markers(framework_root, pending_migrations, item.file.target),
                )
                _write_exclusive_backup(local, project_root / item.backup)
                local.write_text(updated, encoding="utf-8")
            elif item.action == "merge":
                _, merged = merge_clean(local, baseline_root / item.file.target, item.file.source)
                local.write_bytes(merged)
            elif item.action == "merge-deduplicate-markers":
                _, merged = merge_clean(local, baseline_root / item.file.target, item.file.source)
                normalized = deduplicate_identical_template_markers(
                    merged.decode("utf-8"), item.file.source.read_text(encoding="utf-8")
                )
                if normalized is None:
                    raise MeridianError(
                        f"marker deduplication is no longer safe for {item.file.target}; rerun upgrade --check"
                    )
                local.write_text(normalized, encoding="utf-8")
            elif item.action == "deduplicate-markers":
                normalized = deduplicate_identical_template_markers(
                    local.read_text(encoding="utf-8"), item.file.source.read_text(encoding="utf-8")
                )
                if normalized is None:
                    raise MeridianError(
                        f"marker deduplication is no longer safe for {item.file.target}; rerun upgrade --check"
                    )
                local.write_text(normalized, encoding="utf-8")
            elif item.action == "pointer-upgrade":
                local_text = local.read_text(encoding="utf-8")
                if not agents_pointer_satisfies_claude(
                    project_root,
                    framework_root,
                    manifest_workflow_mode(manifest),
                    item.file.source.read_text(encoding="utf-8"),
                    local_text,
                ):
                    raise MeridianError(
                        f"AGENTS.md no longer satisfies the Claude pointer for {item.file.target}; rerun upgrade --check"
                    )
                if CLAUDE_AGENTS_POINTER_MARKER not in local_text:
                    first_newline = local_text.find("\n")
                    insertion = CLAUDE_AGENTS_POINTER_MARKER + "\n"
                    updated = (
                        insertion + "\n" + local_text
                        if first_newline < 0
                        else local_text[: first_newline + 1] + "\n" + insertion + local_text[first_newline + 1 :]
                    )
                    local.write_text(updated, encoding="utf-8")
            elif item.action == "append-markers":
                base = baseline_root / item.file.target
                appended = append_only_new_markers(
                    local.read_text(encoding="utf-8"),
                    base.read_text(encoding="utf-8"),
                    item.file.source.read_text(encoding="utf-8"),
                )
                if appended is None:
                    raise MeridianError(
                        f"marker-aware insertion is no longer safe for {item.file.target}; rerun upgrade --check"
                    )
                local.write_text(appended, encoding="utf-8")
            elif item.action == "append-retire-markers":
                base = baseline_root / item.file.target
                appended = append_only_new_markers(
                    local.read_text(encoding="utf-8"),
                    base.read_text(encoding="utf-8"),
                    item.file.source.read_text(encoding="utf-8"),
                )
                removals = removals_for_managed_file(framework_root, pending_migrations, item.file.target)
                removal_pairs = [(capability, version) for capability, version, _superseded_by in removals]
                retired = remove_retired_markers(appended or "", base.read_text(encoding="utf-8"), removal_pairs)
                if appended is None or retired is None:
                    raise MeridianError(
                        f"marker-aware relocation is no longer safe for {item.file.target}; rerun upgrade --check"
                    )
                local.write_text(retired, encoding="utf-8")
            elif item.action == "normalize-markers":
                normalized = reflowed_marker_normalization(
                    local.read_text(encoding="utf-8"), item.file.source.read_text(encoding="utf-8")
                )
                if normalized is None:
                    raise MeridianError(
                        f"marker normalization is no longer safe for {item.file.target}; rerun upgrade --check"
                    )
                local.write_text(normalized, encoding="utf-8")
            elif item.action == "retire-markers":
                base = baseline_root / item.file.target
                removals = removals_for_managed_file(framework_root, pending_migrations, item.file.target)
                removal_pairs = [(capability, version) for capability, version, _superseded_by in removals]
                local_text = local.read_text(encoding="utf-8")
                retired = remove_retired_markers(local_text, base.read_text(encoding="utf-8"), removal_pairs)
                if retired is None or retired == local_text:
                    raise MeridianError(
                        f"marker retirement is no longer safe for {item.file.target}; rerun upgrade --check"
                    )
                local.write_text(retired, encoding="utf-8")

    if project_uses_entry_router(project_root):
        for target, output in entry_router_outputs(project_root).items():
            (project_root / target).write_text(output, encoding="utf-8")
        router_failures = [
            detail for status, detail in audit_entry_router(project_root) if status == "FAIL"
        ]
        if router_failures:
            raise MeridianError(
                "entry-router audit failed after regeneration: " + "; ".join(router_failures)
            )

    if target_baseline_version != installed_version:
        copy_baseline(
            project_root,
            framework_root,
            manifest_workflow_mode(manifest),
            target_baseline_version,
            managed_files_override=managed_files_override,
        )
        prune_stale_baselines(project_root, target_baseline_version)
    manifest["frameworkVersion"] = target_version
    manifest["workflowBaselineVersion"] = target_baseline_version
    manifest["protocolVersion"] = PROTOCOL_VERSION
    manifest["managedFiles"] = {}
    for item in managed_files_override or managed_files(framework_root, manifest_workflow_mode(manifest)):
        digest_source = item.source
        if project_uses_entry_router(project_root) and item.target in {
            Path("AGENTS.md"),
            Path("CLAUDE.md"),
        }:
            digest_source = project_root / item.target
        manifest["managedFiles"][str(item.target)] = sha256(digest_source)
    prior = {str(item) for item in manifest.get("appliedMigrations", [])}
    prior.update(migration_ids(framework_root, installed_version, target_baseline_version))
    manifest["appliedMigrations"] = sorted(prior)
    complete_profile_surfaces(project_root, framework_root, manifest, plan)
    write_manifest(project_root, manifest, framework_root)
    if migrate_budget_state(project_root):
        print("Migrated legacy .meridian/budget.json out of the index; commit its deletion.", file=sys.stderr)
    print("Upgrade applied. Review the diff, run project checks, then commit it.")


def apply_upgrade(
    project_root: Path,
    framework_root: Path,
    owner_reconciled: bool = False,
    stop_before_retirement: bool = False,
) -> None:
    require_release_version(framework_root)
    manifest, target_override, managed_override = prepare_upgrade_targets(
        project_root, framework_root, stop_before_retirement
    )
    installed_version = manifest_baseline_version(manifest)
    manifest, plan = plan_from_baseline(
        project_root,
        framework_root,
        manifest_workflow_mode(manifest),
        installed_version,
        project_root / BASELINES_PATH / installed_version,
        list(manifest.get("appliedMigrations", [])),
        target_version_override=target_override,
        managed_files_override=managed_override,
        installed_framework_version=str(manifest.get("frameworkVersion", "")),
        capability_profiles=manifest.get("capabilityProfiles"),
    )
    apply_plan(
        project_root,
        framework_root,
        manifest,
        plan,
        project_root / BASELINES_PATH / manifest_baseline_version(manifest),
        owner_reconciled=owner_reconciled,
        target_version_override=target_override,
        managed_files_override=managed_override,
    )


def copy_adoption_baseline(
    project_root: Path, snapshot_workflow: Path, mode: str, version: str
) -> None:
    destination_root = project_root / BASELINES_PATH / version
    for item in managed_files_for_workflow(snapshot_workflow, mode):
        destination = destination_root / item.target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.source, destination)


def adopt_project(
    project_root: Path, framework_root: Path, mode: str, source_version: str, apply: bool
) -> int:
    if (project_root / MANIFEST_PATH).exists():
        raise MeridianError("project already has a manifest; use `meridian upgrade` instead")
    snapshot_workflow = (
        framework_root
        / "release-baselines"
        / source_version
        / "templates"
        / "workflows"
        / mode
    )
    if not snapshot_workflow.is_dir():
        raise MeridianError(
            f"no packaged baseline for {mode} {source_version}; adoption cannot infer it safely"
        )
    baseline_root = project_root / BASELINES_PATH / source_version
    if baseline_root.exists():
        raise MeridianError(f"adoption baseline already exists: {baseline_root}")
    manifest, plan = plan_from_baseline(
        project_root,
        framework_root,
        mode,
        source_version,
        snapshot_workflow,
        [],
    )
    print_plan(project_root, manifest, framework_root, plan)
    if not apply:
        return 2 if any(item.action == "conflict" for item in plan) else 0
    if any(item.action == "conflict" for item in plan):
        raise MeridianError("adoption has conflicts")
    copy_adoption_baseline(project_root, snapshot_workflow, mode, source_version)
    apply_plan(project_root, framework_root, manifest, plan, baseline_root)
    return 0


def finalize_adoption(
    project_root: Path, framework_root: Path, mode: str, owner_accepted: bool = False
) -> None:
    if (project_root / MANIFEST_PATH).exists():
        raise MeridianError("project already has a manifest; use `meridian upgrade` instead")
    missing = [
        capability.migration
        for capability in detect_capabilities(project_root, mode, framework_root)
        if not capability.present
    ]
    if missing:
        raise MeridianError("adoption capabilities are still missing: " + ", ".join(missing))

    if mode == "governed-sdd" and not owner_accepted:
        review = parse_adoption_review(project_root)
        if review is None:
            raise MeridianError(
                "no independent review record found at "
                f"{project_root / ADOPTION_REVIEW_PATH}; run `meridian adopt --assisted --check` "
                "for the reviewer prompt, or pass --owner-accepted after personally reviewing it"
            )
        if review.verdict != "APPROVE" or review.unchecked:
            raise MeridianError(
                "adoption review record does not record an unconditional APPROVE "
                f"(verdict={review.verdict}, unchecked findings={review.unchecked})"
            )

    lock_project(project_root, framework_root, mode)
    if owner_accepted:
        print("Owner-accepted finalize: skipped the independent-review gate.")
    print("Adoption finalized. Review the migration diff and commit the project baseline.")


def proposed_project_identity(project_root: Path) -> dict[str, str]:
    """Derive a stable setup proposal even before a directory is a Git repository."""
    try:
        slug = repository_identity(project_root).repository
    except MeridianError:
        slug = project_root.resolve().name.lower()
    return {"name": slug.replace("-", " ").title(), "slug": slug}


def import_task_states(
    project_root: Path, task_ids: list[str], *, apply: bool = False, include_terminal: bool = False
) -> dict[str, object]:
    """Explicitly bootstrap tasks; validate the entire proposal before writing.

    Terminal legacy tasks are skipped unless `include_terminal` asks for their
    state, which needs consistent texts and, for a reviewed Governed task, a
    recorded APPROVE verdict.

    Imported transitions describe the bootstrap at HEAD, not historical events.
    Existing machine files are never rewritten.
    """
    project_root = project_root.resolve()
    workflow = detect_mode(project_root)
    context = task_identity_context(project_root)
    queue_path = project_root / context.locations.queue
    rows: dict[str, list[dict[str, object]]] = {}
    for found in _queue_task_rows(queue_path.read_text(encoding="utf-8")):
        rows.setdefault(str(found["id"]), []).append({
            "path": context.locations.queue.as_posix(), "line": found["line"],
            "status": found["status"], "review": found["review"]})
    selected = task_ids or list(rows)
    proposals = []
    seen = set()
    head = None
    at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    terminal = {"DONE", "ACCEPTED", "ANSWERED", "INCONCLUSIVE"}

    def normalize(value):
        if workflow == "lean-delivery":
            return {"[ ]": "QUEUED", "TODO": "QUEUED", "[/]": "QUEUED", "IN_PROGRESS": "QUEUED",
                    "[x]": "DONE"}.get(value, value)
        return value

    for supplied in selected:
        matches = _authority_matches(context.authorities, supplied)
        task_id = matches[0] if len(matches) == 1 else supplied

        def invalid(message):
            raise stop_error("TASK_STATE_INVALID", message, task_id=task_id, project=project_root)

        if task_id in seen:
            continue
        seen.add(task_id)
        entries = rows.get(task_id, [])
        if len(entries) != 1:
            invalid(f"queue evidence: allowed one row for {task_id}; found {len(entries)}")
        queue = entries[0]
        status = normalize(queue["status"])
        path = state_path(project_root, task_id)
        proposal = {"task_id": task_id, "path": path.relative_to(project_root).as_posix(),
                    "evidence": {"queue": queue}}
        proposals.append(proposal)
        if path.exists():
            proposal["action"] = "skip-existing"
            continue
        if status in terminal and not include_terminal:
            proposal["action"] = "skip-terminal"
            continue
        try:
            identity = resolve_task_identity(project_root, task_id, "existing", context=context,
                                             allow_archived_queue_links=True)
        except MeridianError as error:
            invalid(str(error))
        record = identity.task_path.read_text(encoding="utf-8")
        record_status = read_task_field(record, "Status")
        record_status = record_status.strip("`") if record_status else None
        proposal["evidence"]["record"] = {"path": identity.task_path.relative_to(project_root).as_posix(),
                                             "status": record_status}
        # Lean records may have no Status field; progress is derived from worktrees.
        if (record_status is None and workflow == "governed-sdd") or (record_status is not None and normalize(record_status) != status):
            invalid(f"queue Status={queue['status']!r}; record Status={record_status!r}")
        spike = read_task_field(record, "Class") == "SPIKE"
        review_policy = read_task_field(record, "Review")
        review_policy = review_policy.strip("`") if review_policy else None
        required = workflow == "governed-sdd" and not spike and review_policy != "NOT_REQUIRED"
        spike_column = spike and queue["review"] == "SPIKE"  # the queue's own spelling of Class: SPIKE
        if workflow == "governed-sdd" and queue["review"] and queue["review"] != review_policy and not spike_column:
            invalid(f"queue Review={queue['review']!r}; record Review={review_policy!r}")
        review_path = identity.review_path
        review_text = review_path.read_text(encoding="utf-8") if review_path.is_file() else ""
        attempts = []
        for heading in re.finditer(r"^## Attempt (\d+)[^\n]*", review_text, re.MULTILINE):
            verdicts = re.findall(r"\b(APPROVE|CHANGES_REQUESTED|BLOCKED)\b", heading.group())
            if not verdicts and status in terminal:
                continue  # a remediation heading of a closed task carries no verdict
            if len(verdicts) != 1:
                invalid(f"review heading: allowed one verdict; found {heading.group()!r}")
            attempts.append((int(heading.group(1)), verdicts[0], heading.start(), heading.group()))
        if len({item[0] for item in attempts}) != len(attempts):
            invalid("review evidence: allowed unique attempt numbers; found duplicate attempts")
        latest = max(attempts, default=None, key=lambda item: item[0])
        proposal["evidence"]["review"] = {"path": review_path.relative_to(project_root).as_posix(),
                                             "exists": review_path.is_file(),
                                             "heading": latest[3] if latest else None,
                                             "verdict": latest[1] if latest else None}
        if latest and status not in terminal and (
                latest[1] == "APPROVE" or status == "QUEUED"
                or (latest[1] == "BLOCKED" and status != "READY_FOR_REVIEW")):
            invalid(f"queue/record Status={status!r}; review verdict={latest[1]!r}")
        if status in terminal and workflow == "governed-sdd" and required and latest and latest[1] != "APPROVE":
            # A recorded verdict must agree with the terminal text; an absent
            # record stays absent (verdict null), so an import never invents an approval.
            invalid(f"queue/record Status={status!r}; review verdict: allowed 'APPROVE'; found {latest[1]!r}")
        if status == "CHANGES_REQUESTED" and (not latest or latest[1] != "CHANGES_REQUESTED"):
            invalid(f"queue/record Status={status!r}; review verdict={latest[1] if latest else None!r}")
        states = machine(workflow, spike, required)
        # A shortest legal path bootstraps current state without inventing old reviews.
        routes = [("QUEUED", [])]
        visited = set()
        route = None
        while routes:
            current, steps = routes.pop(0)
            if current == status:
                route = steps
                break
            if current in visited:
                continue
            visited.add(current)
            routes.extend((target, steps + [target]) for target in states[current])
        if route is None:
            invalid(f"queue Status: allowed {list(states)}; found {status!r}")
        state = {"version": 1, "task_id": task_id, "workflow": workflow, "status": status, "transitions": []}
        current = "QUEUED"
        for target in route:
            head = head or git_output(project_root, "rev-parse", "HEAD")
            state["transitions"].append({"from": current, "to": target, "commit": head, "at": at})
            current = target
        if workflow == "governed-sdd" and not required:
            state["review"] = {"required": False, "verdict": None, "attempt": 1,
                               "reviewed_commit": None, "approved_by": None}
        if latest:
            if not required:
                invalid(f"record Review={review_policy!r}, Class={read_task_field(record, 'Class')!r}; review verdict={latest[1]!r}")
            state["review"] = {"required": True, "verdict": latest[1], "attempt": latest[0],
                               "reviewed_commit": None, "approved_by": None}
        try:
            validate_task_state(state, task_id, workflow, spike=spike, review_required=required)
        except TaskStateInvalid as error:
            invalid(str(error))
        proposal.update(action="write", state=state)
    if apply:
        for proposal in proposals:
            if proposal["action"] != "write":
                continue
            path = project_root / proposal["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation also refuses a file created since the preview.
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(proposal["state"], indent=2, sort_keys=True) + "\n")
    return {"version": 1, "workflow": workflow, "applied": apply, "tasks": proposals}


def transition_task_state(project_root: Path, task_id: str, status: str) -> dict[str, object]:
    """Apply one validated machine transition and update the record projection."""
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    workflow = detect_mode(project_root)
    record = identity.task_path.read_text(encoding="utf-8")
    spike = read_task_field(record, "Class") == "SPIKE"
    review_required = read_task_field(record, "Review") != "NOT_REQUIRED"
    try:
        path = state_path(project_root, task_id)
        try:
            state = read_task_state(project_root, task_id, workflow, spike=spike, review_required=review_required, stop_factory=stop_error)
        except MeridianStop as error:
            if error.code != "TASK_STATE_MISSING":
                raise
            state = {"version": 1, "task_id": task_id, "workflow": workflow,
                     "status": "QUEUED", "transitions": []}
        allowed = machine(workflow, spike, review_required)[state["status"]]
        if status not in allowed:
            raise TaskStateInvalid(f"transition from {state['status']}: allowed {list(allowed)}; found {status!r}")
        state["transitions"].append({
            "from": state["status"], "to": status,
            "commit": git_output(project_root, "rev-parse", "HEAD"),
            "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        state["status"] = status
        validate_task_state(state, task_id, workflow, spike=spike, review_required=review_required)
    except TaskStateInvalid as error:
        raise stop_error("TASK_STATE_INVALID", str(error), task_id=task_id, project=project_root) from error
    if status == "READY_FOR_REVIEW":
        delivery_readiness(project_root, task_id)
    projection = re.sub(r"^Status:[^\n]*", f"Status: {status}", record, flags=re.MULTILINE)
    _write_json_atomic(path, state)
    if projection != record:
        identity.task_path.write_text(projection, encoding="utf-8")
    return state


def close_task(project_root: Path, task_id: str) -> dict[str, object]:
    """Close a validated Lean task, staging its state and exact record archive."""
    project_root = project_root.resolve()
    _execution_worktree(project_root, task_id, command=("task", "close"))
    if detect_mode(project_root) != "lean-delivery":
        raise stop_error("TASK_STATUS_REJECTED", "task close is Lean-only; use meridian task transition for Governed SDD",
                         task_id=task_id, project=project_root)
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    record_path = identity.task_path
    if record_path.parent.name == "done":
        raise stop_error("TASK_STATUS_REJECTED", "record is already archived; use meridian worktree advance",
                         task_id=task_id, project=project_root)
    archive = record_path.parent / "done" / record_path.name
    if archive.exists():
        raise stop_error("TASK_STATUS_REJECTED", "exact archive path already exists; inspect the task record before retrying task close",
                         task_id=task_id, project=project_root)
    handoff = identity.handoff_path.relative_to(project_root).as_posix()
    if not identity.handoff_path.is_file() or _run_git(project_root, "cat-file", "-e", f"HEAD:{handoff}").returncode:
        raise stop_error("HANDOFF_REPORT_MISSING", "task close requires a committed handoff; commit it before meridian task close",
                         task_id=task_id, project=project_root)
    path = state_path(project_root, task_id)
    if path.exists():
        state = read_task_state(project_root, task_id, "lean-delivery", stop_factory=stop_error)
        if state["status"] == "DONE":
            raise stop_error("TASK_STATUS_REJECTED", "task is already DONE; use meridian worktree advance",
                             task_id=task_id, project=project_root)
    # The transition validates everything before writing and is the single state writer.
    state = transition_task_state(project_root, task_id, "DONE")
    archive.parent.mkdir(parents=True, exist_ok=True)
    record_path.rename(archive)
    staged = _run_git(project_root, "add", "--", record_path.relative_to(project_root).as_posix(),
                      archive.relative_to(project_root).as_posix(), path.relative_to(project_root).as_posix())
    if staged.returncode:
        raise MeridianError(f"could not stage closure records: {staged.stderr.strip()}")
    return {"task_id": task_id, "state": state, "archive": archive.relative_to(project_root).as_posix(),
            "staged": True, "committed": False}


def profile_cap(project_root: Path, kind: str) -> int:
    """Read the project's declared budget default, retaining framework defaults
    only for pre-profile projects.

    The profile is prose by design, but each shipped default has a stable
    backticked field name followed by its numeric cap.  Keeping this lookup
    here prevents the CLI's default silently drifting from project policy.
    """
    profile = project_root / "docs" / "EXECUTION_EVIDENCE_PROFILE.md"
    if not profile.is_file():
        return BUDGET_DEFAULT_CAPS[kind]
    field = re.escape(BUDGET_FIELD_NAMES[kind])
    match = re.search(rf"`{field}`:\s*(\d+)", profile.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else BUDGET_DEFAULT_CAPS[kind]


def profile_digest(project_root: Path) -> str:
    profile = project_root / "docs" / "EXECUTION_EVIDENCE_PROFILE.md"
    if not profile.is_file():
        raise stop_error(
            "EXECUTION_PROFILE_MISSING",
            "rule: the execution contract derives from the project profile; source checked: "
            "docs/EXECUTION_EVIDENCE_PROFILE.md; expected: the file exists; found: no such file",
        )
    return hashlib.sha256(profile.read_bytes()).hexdigest()


def execution_contract(project_root: Path, task_id: str) -> str:
    """Render the profile-derived execution block placed in a task at design time."""
    task = find_task_file(project_root, task_id)
    text = task.read_text(encoding="utf-8")
    require_named_validation_commands(text)
    commands = ", ".join(validation_commands(text)) or "none"
    caps = ", ".join(f"{BUDGET_FIELD_NAMES[kind]}: {task_cap(project_root, text, kind)}" for kind in BUDGET_KINDS)
    return "\n".join((
        "## Execution contract — resolved",
        "",
        "- Profile source: `docs/EXECUTION_EVIDENCE_PROFILE.md`",
        f"- Profile revision: `sha256:{profile_digest(project_root)}`",
        f"- Budgets: {caps}",
        f"- Validation IDs: {commands}",
        "- Execution commands: `required via meridian execution`",
    ))


def contract_digest(text: str) -> str | None:
    match = re.search(r"^- Profile revision: `sha256:([0-9a-f]{64})`$", text, re.MULTILINE)
    return match.group(1) if match else None


def contract_requires_execution_commands(text: str) -> bool:
    return "- Execution commands: `required via meridian execution`" in text


FLOW_TARGETS_PATH = Path(".meridian/flow-targets.json")
FLOW_TARGETS_VERSION = 1
FLOW_ORIGINS = ("capability", "friction", "maintenance", "release")
FLOW_ORIGIN_PATTERN = re.compile(r"^>\s*\*\*Origin\*\*:\s*(\S+)", re.MULTILINE)
FLOW_JOURNAL_TIME = "%Y-%m-%dT%H:%M:%SZ"
FLOW_UNCODED = "uncoded"


def _flow_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, FLOW_JOURNAL_TIME).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _flow_read_journal(project_root: Path) -> tuple[list[dict[str, object]], int]:
    """Read the rotated and current journal; return valid records in file order and the malformed-line count."""
    directory = canonical_git_common_dir(project_root)
    records: list[dict[str, object]] = []
    malformed = 0
    for name in (JOURNAL_ROTATED_NAME, JOURNAL_NAME):
        try:
            text = (directory / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                malformed += 1
                continue
            when = _flow_time(record.get("ts")) if isinstance(record, dict) else None
            if (
                when is None
                or record.get("version") != JOURNAL_VERSION
                or not isinstance(record.get("command"), str)
                or not isinstance(record.get("result"), str)
            ):
                malformed += 1
                continue
            record["_when"] = when
            records.append(record)
    return records, malformed


def _flow_origin(project_root: Path, task: str) -> str:
    """Read the optional `Origin` task header from the task record or its archive."""
    try:
        text = find_task_file(project_root, task).read_text(encoding="utf-8")
    except (MeridianError, OSError, UnicodeDecodeError):
        return "unknown"
    match = FLOW_ORIGIN_PATTERN.search(text)
    return match.group(1).lower() if match and match.group(1).lower() in FLOW_ORIGINS else "unknown"


def _flow_median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _flow_targets(project_root: Path, tasks: list[dict[str, object]], unbacked_times: list[datetime]) -> list[dict[str, object]]:
    """Evaluate the declared targets over count windows of integrated tasks; a missing file declares none."""
    path = project_root / FLOW_TARGETS_PATH
    if not path.is_file():
        return []
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MeridianError(f"{FLOW_TARGETS_PATH} is unreadable: {error}") from error
    if not isinstance(declared, dict) or declared.get("version") != FLOW_TARGETS_VERSION:
        raise MeridianError(f"{FLOW_TARGETS_PATH} must be a version {FLOW_TARGETS_VERSION} object")
    integrated = sorted((task for task in tasks if task["_integrated"] is not None), key=lambda task: task["_integrated"])
    results: list[dict[str, object]] = []

    def window_of(entry: object, name: str) -> int:
        window = entry.get("window") if isinstance(entry, dict) else None
        if not isinstance(window, int) or isinstance(window, bool) or window < 1:
            raise MeridianError(f"{FLOW_TARGETS_PATH}: {name}.window must be a positive integer")
        return window

    def limit_of(entry: object, name: str, key: str) -> float:
        value = entry.get(key) if isinstance(entry, dict) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise MeridianError(f"{FLOW_TARGETS_PATH}: {name}.{key} must be a non-negative number")
        return value

    def state(measured: float | None, limit: float) -> str:
        return "insufficient data" if measured is None else ("met" if measured <= limit else "missed")

    if "unbacked_blocks" in declared:
        entry = declared["unbacked_blocks"]
        window, limit = window_of(entry, "unbacked_blocks"), limit_of(entry, "unbacked_blocks", "max")
        recent = integrated[-window:]
        measured = None
        if len(recent) >= window:
            start = min(task["_started"] or task["_integrated"] for task in recent)
            measured = sum(1 for when in unbacked_times if when >= start)
        results.append({"target": "unbacked_blocks", "window": window, "limit": limit, "measured": measured, "state": state(measured, limit)})
    if "lead_time_regression" in declared:
        entry = declared["lead_time_regression"]
        window, limit = window_of(entry, "lead_time_regression"), limit_of(entry, "lead_time_regression", "max_percent")
        timed = [task["lead_time_seconds"] for task in integrated if task["lead_time_seconds"] is not None]
        measured = None
        if len(timed) >= 2 * window:
            recent_median = statistics.median(timed[-window:])
            prior_median = statistics.median(timed[-2 * window:-window])
            measured = (recent_median - prior_median) / prior_median * 100 if prior_median else (0.0 if not recent_median else float("inf"))
        results.append({
            "target": "lead_time_regression", "window": window, "limit": limit,
            "measured": None if measured is None else (round(measured, 1) if measured != float("inf") else "unbounded"),
            "state": "insufficient data" if measured is None else ("met" if measured <= limit else "missed"),
        })
    if "friction_share" in declared:
        entry = declared["friction_share"]
        window, limit = window_of(entry, "friction_share"), limit_of(entry, "friction_share", "max_percent")
        declaring = [task for task in integrated if task["origin"] != "unknown"][-window:]
        measured = None
        if len(declaring) >= window:
            measured = round(100 * sum(1 for task in declaring if task["origin"] == "friction") / window, 1)
        results.append({"target": "friction_share", "window": window, "limit": limit, "measured": measured, "state": state(measured, limit)})
    return results


def _flow_tasks(project_root: Path, records: list[dict[str, object]], cutoff: datetime | None) -> list[dict[str, object]]:
    """Build one entry per task that has a journal record in the period; lead time uses the task's whole history."""
    in_period = lambda record: cutoff is None or record["_when"] >= cutoff  # noqa: E731
    by_task: dict[str, list[dict[str, object]]] = {}
    for record in records:
        task = record.get("task")
        if isinstance(task, str) and record["command"] != "stop-audit":
            by_task.setdefault(task, []).append(record)
    tasks: list[dict[str, object]] = []
    for task, task_records in sorted(by_task.items(), key=lambda item: (len(item[0]), item[0])):
        if not any(in_period(record) for record in task_records):
            continue
        prepared = [r["_when"] for r in task_records if r["command"] == "prepare" and r["result"] == "ok" and not r.get("resume")]
        finalized = [r["_when"] for r in task_records if r["command"] == "integrate finalize" and r["result"] == "ok"]
        started = min(prepared) if prepared else None
        if started is None:
            try:
                recorded = lifecycle_started_at(task, project_root)
            except (MeridianError, OSError):
                recorded = None
            started = datetime.fromisoformat(recorded.replace("Z", "+00:00")) if recorded else None
        integrated = min(finalized) if finalized else None
        counted = [r for r in task_records if in_period(r)]
        stops: dict[str, int] = {}
        for record in counted:
            if record["result"] == "blocked":
                code = record.get("stop_code")
                key = code if isinstance(code, str) else FLOW_UNCODED
                stops[key] = stops.get(key, 0) + 1
        tasks.append({
            "task": task,
            "lead_time_seconds": int((integrated - started).total_seconds()) if started and integrated else None,
            "stops": dict(sorted(stops.items())),
            "aborts": sum(1 for r in counted if r["command"] == "integrate abort" and r["result"] == "ok"),
            "resumes": sum(1 for r in counted if r["command"] == "prepare" and r.get("resume") and r["result"] == "ok"),
            "origin": _flow_origin(project_root, task),
            "_started": started,
            "_integrated": integrated,
        })
    return tasks


def flow_report(project_root: Path, since: str | None, now: datetime | None = None) -> dict[str, object]:
    """Summarize the lifecycle journal into lead time, stops, and origin shares; read-only."""
    cutoff = None
    if since is not None:
        try:
            cutoff = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError as error:
            raise MeridianError("--since must be an ISO date (YYYY-MM-DD)") from error
    records, malformed = _flow_read_journal(project_root)
    registry = load_stop_registry()
    in_period = lambda record: cutoff is None or record["_when"] >= cutoff  # noqa: E731
    tasks = _flow_tasks(project_root, records, cutoff)
    unbacked_times = [record["_when"] for record in records if record["result"] == "unbacked_block"]
    stops_by_code: dict[str, int] = {}
    for record in records:
        if in_period(record) and record["result"] == "blocked":
            code = record.get("stop_code")
            key = code if isinstance(code, str) else FLOW_UNCODED
            stops_by_code[key] = stops_by_code.get(key, 0) + 1
    stops_by_class: dict[str, int] = {}
    for code, count in stops_by_code.items():
        klass = FLOW_UNCODED if code == FLOW_UNCODED else str(registry.get(code, {}).get("class", "unknown"))
        stops_by_class[klass] = stops_by_class.get(klass, 0) + count
    origins = {name: 0 for name in (*FLOW_ORIGINS, "unknown")}
    for task in tasks:
        origins[str(task["origin"])] += 1
    total = len(tasks)
    origin_share = {name: (round(100 * count / total, 1) if total else 0.0) for name, count in origins.items()}
    lead_times = [task["lead_time_seconds"] for task in tasks if task["lead_time_seconds"] is not None]
    period_records = [record for record in records if in_period(record)]
    start = cutoff or (min(record["_when"] for record in period_records) if period_records else None)
    end = now or datetime.now(timezone.utc)
    period_days = max(0, (end - start).days) if start else 0
    emitted = {record.get("stop_code") for record in period_records if record["result"] == "blocked"}
    candidates = sorted(code for code, entry in registry.items() if entry.get("class") == "tool" and code not in emitted) if period_records else []
    # Targets use count windows over all integrated tasks, never the --since period.
    targets = _flow_targets(project_root, tasks if cutoff is None else _flow_tasks(project_root, records, None), unbacked_times)
    public_tasks = [{key: value for key, value in task.items() if not key.startswith("_")} for task in tasks]
    blocks_by_host = {host: {"unbacked": 0, "declared": 0} for host in ("claude", "codex")}
    for record in period_records:
        kind = {"unbacked_block": "unbacked", "declared_block": "declared"}.get(str(record["result"]))
        if kind is not None:
            host = record.get("host", "claude")
            blocks_by_host.setdefault(host if isinstance(host, str) else "unknown", {"unbacked": 0, "declared": 0})[kind] += 1
    report: dict[str, object] = {
        "since": since,
        "malformed_lines": malformed,
        "period_days": period_days,
        "tasks": public_tasks,
        "totals": {
            "tasks": total,
            "integrated": len(lead_times),
            "median_lead_time_seconds": _flow_median(lead_times),
            "aborts": sum(task["aborts"] for task in tasks),
            "resumes": sum(task["resumes"] for task in tasks),
            "stops": sum(stops_by_code.values()),
        },
        "stops_by_code": dict(sorted(stops_by_code.items())),
        "stops_by_class": dict(sorted(stops_by_class.items())),
        "unbacked_blocks": sum(1 for record in period_records if record["result"] == "unbacked_block"),
        "blocks_by_host": blocks_by_host,
        "origin_counts": origins,
        "origin_share_percent": origin_share,
        "targets": targets,
        "removal_candidates": candidates,
    }
    return report


def format_flow_report(report: dict[str, object]) -> str:
    totals = report["totals"]  # type: ignore[assignment]
    median = totals["median_lead_time_seconds"]
    lines = [
        f"Flow report{' since ' + str(report['since']) if report['since'] else ''}: {totals['tasks']} tasks, "
        f"{totals['integrated']} integrated, median lead time {_flow_duration(median)}, "
        f"{totals['stops']} stops, {totals['aborts']} aborts, {totals['resumes']} resumes",
    ]
    if report["malformed_lines"]:
        lines.append(f"Malformed journal lines skipped: {report['malformed_lines']}")
    for task in report["tasks"]:  # type: ignore[index]
        stops = ", ".join(f"{code}={count}" for code, count in task["stops"].items()) or "none"
        lines.append(
            f"  task {task['task']}: lead time {_flow_duration(task['lead_time_seconds'])}, stops {stops}, "
            f"aborts {task['aborts']}, resumes {task['resumes']}, origin {task['origin']}"
        )
    lines.append("Stops by code: " + (", ".join(f"{k}={v}" for k, v in report["stops_by_code"].items()) or "none"))  # type: ignore[attr-defined]
    lines.append("Stops by class: " + (", ".join(f"{k}={v}" for k, v in report["stops_by_class"].items()) or "none"))  # type: ignore[attr-defined]
    by_host = report["blocks_by_host"]  # type: ignore[assignment]
    for kind, label in (("unbacked", "Unbacked stop reports"), ("declared", "Declared stop reports")):
        if any(counts[kind] for counts in by_host.values()):
            lines.append(f"{label}: " + ", ".join(f"{host}={counts[kind]}" for host, counts in by_host.items()))
    lines.append("Origin share: " + ", ".join(f"{k}={v}%" for k, v in report["origin_share_percent"].items()))  # type: ignore[attr-defined]
    for target in report["targets"]:  # type: ignore[index]
        lines.append(f"Target {target['target']}: {target['state']} (measured {target['measured']}, limit {target['limit']}, window {target['window']})")
    candidates = report["removal_candidates"]
    lines.append(
        f"Removal candidates (tool-class stops not emitted in {report['period_days']} days): "
        + (", ".join(candidates) or "none")  # type: ignore[arg-type]
    )
    return "\n".join(lines)


def _flow_duration(seconds: object) -> str:
    if not isinstance(seconds, (int, float)):
        return "n/a"
    return f"{seconds / 3600:.1f}h"


def task_cap(project_root: Path, text: str, kind: str) -> int:
    raw = read_task_field(text, BUDGET_FIELD_NAMES[kind])
    if raw and raw.isdigit():
        return int(raw)
    return profile_cap(project_root, kind)


def resolve_budget_key(project_root: Path, state: dict[str, object], task_id: str) -> tuple[str, str]:
    """Return the qualified `<TASK-ID>:<attempt>` state key and the task file's
    text, bumping `state`'s attempt bookkeeping in place when the task file
    shows a fresh READY_FOR_REVIEW -> IN_PROGRESS transition (a new
    remediation attempt) since the last time this was resolved.
    """
    identity = resolve_task_identity(project_root, task_id, "existing")
    task_file = identity.task_path
    text = task_file.read_text(encoding="utf-8")
    status = read_task_field(text, "Status") or "UNKNOWN"
    canonical_id = identity.canonical_id
    meta = dict(state.get(canonical_id) or {"attempt": 1, "lastStatus": None})
    if meta.get("lastStatus") == "READY_FOR_REVIEW" and status == "IN_PROGRESS":
        meta["attempt"] = int(meta.get("attempt", 1)) + 1
    meta["lastStatus"] = status
    state[canonical_id] = meta
    return identity.budget_key(int(meta["attempt"])), text


def budget_show(project_root: Path, task_id: str) -> str:
    state = load_budget_state(project_root)
    key, text = resolve_budget_key(project_root, state, task_id)
    counters = state.get(key, {})
    parts = [f"Attempt {key.rsplit(':', 1)[1]}"]
    for kind, label in (
        ("diagnostic", "Diagnostics"),
        ("captures", "Captures"),
        ("expansions", "Expansions"),
        ("investigations", "Investigations"),
    ):
        cap = task_cap(project_root, text, kind)
        if kind == "captures":
            scoped = sorted((key.removeprefix("captures:"), value) for key, value in counters.items() if key.startswith("captures:"))
            if scoped:
                parts.append(f"{label} " + ", ".join(f"{criterion} {int(count)}/{cap}" for criterion, count in scoped))
                continue
        parts.append(f"{label} {int(counters.get(kind, 0))}/{cap}")
    return " · ".join(parts)


def budget_spend(
    project_root: Path, task_id: str, kind: str, scope: str | None = None, amount: int = 1
) -> tuple[int, int]:
    if amount < 1:
        raise stop_error(
            "EXECUTION_EVIDENCE_ARGUMENTS",
            f"rule: a budget use is at least one; option checked: --scope; accepted: an integer of 1 or more; found: {amount}",
            resume="rerun meridian execution investigate with --scope of 1 or more",
        )
    state = load_budget_state(project_root)
    key, text = resolve_budget_key(project_root, state, task_id)
    counters = dict(state.get(key, {}))
    counter_key = f"{kind}:{scope}" if kind == "captures" and scope else kind
    stored = int(counters.get(counter_key, 0))
    count = stored + amount
    cap = task_cap(project_root, text, kind)
    if count > cap:
        raise stop_error(
            "BUDGET_EXHAUSTED",
            f"{BUDGET_FIELD_NAMES[kind]} exhausted for {task_id}: "
            f"{stored} of {cap} allowed uses already recorded, {amount} more requested; do not raise the cap",
        )
    counters[counter_key] = count
    state[key] = counters
    write_budget_state(project_root, state)
    return count, cap


PREFLIGHT_HEADINGS = ("Authority", "Validation")
NORMAL_PREFLIGHT_HEADINGS = ("Expected code surface",)
SPIKE_PREFLIGHT_FIELDS = ("Question", "Budget", "Deliverable")
HANDOFF_FIELDS = (
    "Files changed",
    "Validation",
    "Validation skips",
    "Manual verification",
    "Acceptance criteria",
    "Budget usage",
    "Isolated exploration",
    "Blockers/deviations",
)
EXECUTION_EVIDENCE_PATH = Path(".meridian/execution-evidence.json")
HOST_IMPACT_STATES = ("enforced", "advisory", "unsupported", "unverified")
HOST_IMPACT_EVIDENCE_CATEGORIES = ("Static", "Host execution", "Manual activation")


def host_impact_section(text: str) -> str | None:
    """Return the optional host-impact declaration from a task record.

    Records created before the Task 044 blueprint deliberately have no such
    section.  They remain valid historical inputs rather than being rewritten
    solely to satisfy a newly introduced lifecycle gate.
    """
    section = re.search(r"^## Host impact\s*$\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return section.group(1) if section else None


def host_impact_field(section: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(\S.*)$", section, re.MULTILINE)
    return match.group(1).strip() if match else None


def host_impact_required_profiles(section: str) -> list[tuple[str, str]]:
    """Validate a REQUIRED declaration and return its claimed profile states."""
    if not host_impact_field(section, "Policy outcome"):
        raise stop_error("HOST_IMPACT_DECLARATION_INVALID", "REQUIRED declaration is missing Policy outcome")

    table = re.search(
        r"^\|\s*Profile\s*\|\s*Before\s*\|\s*Intended after\s*\|\s*Activation preconditions\s*\|\s*Fallback\s*\|\s*$\n"
        r"^\|(?:\s*:?-+\s*\|){4}\s*:?-+\s*\|\s*$\n"
        r"((?:^\|.*\|\s*$\n?)+)",
        section,
        re.MULTILINE,
    )
    if table is None:
        raise stop_error("HOST_IMPACT_DECLARATION_INVALID", "REQUIRED declaration is missing the profile table")

    profiles: list[tuple[str, str]] = []
    for line in table.group(1).splitlines():
        if not line.strip():
            continue
        values = [value.strip() for value in line.strip().strip("|").split("|")]
        if len(values) != 5:
            raise stop_error("HOST_IMPACT_DECLARATION_INVALID", "profile table row must contain five fields")
        profile, before, intended_after, activation, fallback = values
        for name, value in (
            ("Profile", profile),
            ("Before", before),
            ("Intended after", intended_after),
            ("Activation preconditions", activation),
            ("Fallback", fallback),
        ):
            if not value:
                raise stop_error("HOST_IMPACT_DECLARATION_INVALID", f"profile table is missing {name}")
        for name, value in (("Before", before), ("Intended after", intended_after)):
            if value not in HOST_IMPACT_STATES:
                raise stop_error(
                    "HOST_IMPACT_DECLARATION_INVALID",
                    f"profile {profile!r} has invalid {name} state {value!r}; accepted: {', '.join(HOST_IMPACT_STATES)}",
                )
        profiles.append((profile, intended_after))

    for category in HOST_IMPACT_EVIDENCE_CATEGORIES:
        if not re.search(rf"^- {re.escape(category)}:\s*\S+", section, re.MULTILINE):
            raise stop_error("HOST_IMPACT_DECLARATION_INVALID", f"REQUIRED declaration is missing {category} evidence plan")
    return profiles


def validate_host_impact_declaration(text: str) -> list[tuple[str, str]]:
    """Validate a Task 044 declaration, retaining pre-migration task records."""
    section = host_impact_section(text)
    if section is None:
        return []
    classification = host_impact_field(section, "Classification")
    if classification == "NOT_APPLICABLE":
        if not host_impact_field(section, "Rationale"):
            raise stop_error("HOST_IMPACT_DECLARATION_INVALID", "NOT_APPLICABLE declaration is missing Rationale")
        return []
    if classification == "REQUIRED":
        return host_impact_required_profiles(section)
    raise stop_error(
        "HOST_IMPACT_DECLARATION_INVALID",
        f"Classification must be NOT_APPLICABLE or REQUIRED; found: {classification!r}",
    )


def verify_host_impact_completion_evidence(text: str) -> None:
    """Require profile-specific durable evidence for each enforced claim."""
    section = host_impact_section(text)
    if section is None:
        return
    enforced_profiles = [profile for profile, state in validate_host_impact_declaration(text) if state == "enforced"]
    if not enforced_profiles:
        return
    evidence = {
        match.group(1).strip()
        for match in re.finditer(r"^- \[([^\]]+)\]:\s*\S+", section, re.MULTILINE)
    }
    missing = [profile for profile in enforced_profiles if profile not in evidence]
    if missing:
        raise stop_error(
            "HOST_IMPACT_EVIDENCE_MISSING",
            "enforced profile is missing Completion evidence: " + ", ".join(missing),
        )


def execution_preflight(project_root: Path, task_id: str) -> str:
    """Validate the minimum durable execution contract before implementation.

    This intentionally does not inspect a chat's reasoning setting: that is a
    host concern and is outside this command's authority.
    """
    identity = resolve_task_identity(project_root, task_id, "existing")
    task_file = identity.task_path
    text = task_file.read_text(encoding="utf-8")
    require_named_validation_commands(text)
    validate_host_impact_declaration(text)
    expected_digest = profile_digest(project_root)
    recorded_digest = contract_digest(text)
    task_name = task_file.relative_to(project_root).as_posix()
    if recorded_digest is None:
        raise stop_error(
            "EXECUTION_CONTRACT_UNRESOLVED",
            f"rule: a task needs a resolved execution contract; field checked: `- Profile revision` in {task_name}; "
            f"expected: sha256:{expected_digest}; found: no such line",
            task_id=task_id,
        )
    if recorded_digest != expected_digest:
        raise stop_error(
            "EXECUTION_CONTRACT_UNRESOLVED",
            f"rule: the resolved contract must match the current profile; field checked: `- Profile revision` in "
            f"{task_name} against docs/EXECUTION_EVIDENCE_PROFILE.md; expected: sha256:{expected_digest}; "
            f"found: sha256:{recorded_digest}",
            task_id=task_id,
        )
    if not contract_requires_execution_commands(text):
        raise stop_error(
            "EXECUTION_CONTRACT_UNRESOLVED",
            f"rule: the contract must require execution commands; field checked: `- Execution commands` in "
            f"{task_name}; expected: `required via meridian execution`; found: no such line",
            task_id=task_id,
        )
    required_headings = PREFLIGHT_HEADINGS
    missing = [
        f"## {heading}"
        for heading in required_headings
        if not re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE)
    ]
    if read_task_field(text, "Class") == "SPIKE":
        missing.extend(field for field in SPIKE_PREFLIGHT_FIELDS if not read_task_field(text, field))
    else:
        missing.extend(
            f"## {heading}"
            for heading in NORMAL_PREFLIGHT_HEADINGS
            if not re.search(rf"^## {re.escape(heading)}\s*$", text, re.MULTILINE)
        )
    if missing:
        is_spike = read_task_field(text, "Class") == "SPIKE"
        required = [f"## {heading}" for heading in PREFLIGHT_HEADINGS] + (
            list(SPIKE_PREFLIGHT_FIELDS) if is_spike else [f"## {heading}" for heading in NORMAL_PREFLIGHT_HEADINGS]
        )
        raise stop_error(
            "TASK_RECORD_INCOMPLETE",
            f"rule: a {'SPIKE' if is_spike else 'normal'} task record must contain its required headings"
            f"{' and fields' if is_spike else ''}; source checked: {task_name}; accepted: "
            + ", ".join(required) + "; missing: " + ", ".join(missing),
            task_id=task_id,
        )
    status = read_task_field(text, "Status")
    on_task_branch = current_branch(project_root) == identity.branch_name
    open_statuses = TASK_BRANCH_OPEN_STATUSES if on_task_branch else ("QUEUED", "IN_PROGRESS")
    if status not in open_statuses:
        raise stop_error(
            "TASK_STATUS_REJECTED",
            f"rule: preflight runs only on an open task; field checked: Status in {task_name}; "
            f"accepted: {', '.join(open_statuses)}; found: {status or 'missing'}",
        )
    queue = project_root / resolve_project_locations(project_root).queue
    if queue.is_file():
        header = next((line for line in queue.read_text(encoding="utf-8").splitlines() if line.startswith("| Order |")), "")
        columns = [value.strip() for value in header.strip("|").split("|")]
        if "ID" in columns and "Status" in columns:
            for line in queue.read_text(encoding="utf-8").splitlines():
                if not re.match(r"^\|\s*\d+\s*\|", line):
                    continue
                values = [value.strip() for value in line.strip("|").split("|")]
                if len(values) == len(columns) and values[columns.index("ID")] == identity.canonical_id:
                    queued_status = values[columns.index("Status")]
                    # A task branch never edits the queue, so its row stays QUEUED while the record moves.
                    if queued_status != status and not (on_task_branch and queued_status == "QUEUED"):
                        queue_name = queue.relative_to(project_root).as_posix()
                        permitted = (
                            f"on task branch {identity.branch_name} the actor may change only {task_name}, "
                            f"and the queue row stays QUEUED"
                            if on_task_branch
                            else f"the actor may change {task_name} and {queue_name} together through the lifecycle"
                        )
                        accepted = (
                            f"equal values, or queue QUEUED with task {', '.join(TASK_BRANCH_OPEN_STATUSES)}"
                            if on_task_branch
                            else "equal values"
                        )
                        raise stop_error(
                            "QUEUE_STATUS_MISMATCH",
                            f"rule: the task record and its queue row must agree; sources checked: Status in "
                            f"{task_name} and the Status column of row {identity.canonical_id} in "
                            f"{queue_name}; accepted: {accepted}; "
                            f"found: task {status}, queue {queued_status}; {permitted}",
                            task_id=task_id,
                        )
                    break
    caps = ", ".join(
        f"{BUDGET_FIELD_NAMES[kind]}={task_cap(project_root, text, kind)}" for kind in BUDGET_KINDS
    )
    return f"Execution contract: {task_file.relative_to(project_root)} · {caps}"


def reconcile_execution_contract(project_root: Path, task_id: str, apply: bool) -> str:
    """Refresh only a nonterminal task's generated execution-contract block."""
    task_file = find_task_file(project_root, task_id)
    text = task_file.read_text(encoding="utf-8")
    status = read_task_field(text, "Status") or "missing"
    if status in ("ACCEPTED", "ANSWERED", "INCONCLUSIVE"):
        return f"Execution reconciliation skipped for terminal task {task_id} ({status})"
    if status not in ("QUEUED", "IN_PROGRESS"):
        raise stop_error(
            "TASK_STATUS_REJECTED",
            f"rule: reconcile refreshes only an open task; field checked: Status in "
            f"{task_file.relative_to(project_root).as_posix()}; accepted: QUEUED, IN_PROGRESS "
            f"(terminal tasks are skipped); found: {status}",
        )
    generated = execution_contract(project_root, task_id)
    section = re.compile(
        r"^## Execution contract — resolved\s*$\n.*?(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    replacement = generated + "\n\n"
    match = section.search(text)
    if match:
        separator = "\n\n" if match.end() < len(text) else "\n"
        reconciled = text[:match.start()] + generated + separator + text[match.end():]
    elif re.search(r"^## Completion\s*$", text, re.MULTILINE):
        reconciled = re.sub(r"^## Completion\s*$", replacement + "## Completion", text, count=1, flags=re.MULTILINE)
    else:
        reconciled = text.rstrip() + "\n\n" + generated + "\n"
    if reconciled == text:
        return f"Execution reconciliation already current for {task_id}: {task_file.relative_to(project_root)}"
    if not apply:
        return f"Execution reconciliation required for {task_id}: {task_file.relative_to(project_root)} (rerun with --apply)"
    task_file.write_text(reconciled, encoding="utf-8")
    return f"Execution reconciliation applied for {task_id}: {task_file.relative_to(project_root)}"


def execution_entries(project_root: Path, task_id: str) -> list[dict[str, object]]:
    path = project_root / EXECUTION_EVIDENCE_PATH
    if not path.is_file():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MeridianError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    entries = state.get(canonical_id, [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise MeridianError(f"invalid execution evidence entries for {task_id}: {path}")
    return entries


def verify_validation_skips(report_text: str, task_id: str) -> None:
    """Reject validation failures that a handoff's skip declaration cannot excuse."""
    reported = re.search(r"^- Validation skips:\s*(.+)$", report_text, re.MULTILINE)
    assert reported is not None  # HANDOFF_FIELDS has already checked its presence.
    value = reported.group(1).strip()
    validation = re.search(r"^- Validation:\s*(.+)$", report_text, re.MULTILINE)
    assert validation is not None  # HANDOFF_FIELDS has already checked its presence.
    failed_validation = re.search(r"\bexit\s+[1-9][0-9]*\b", validation.group(1))

    if value.lower() == "none":
        if failed_validation:
            raise stop_error(
                "HANDOFF_VALIDATION_FAILING",
                f"rule: a failing validation needs a named skip; field checked: Validation; accepted: no "
                f"`exit <non-zero>`; found: `{failed_validation.group(0)}` with Validation skips: none",
                task_id=task_id,
            )
        return

    if failed_validation:
        raise stop_error(
            "HANDOFF_VALIDATION_FAILING",
            f"rule: a named skip does not make a failing validation pass; field checked: Validation; "
            f"accepted: no `exit <non-zero>`; found: `{failed_validation.group(0)}` with Validation skips: {value}",
            task_id=task_id,
        )


def verify_execution_evidence(project_root: Path, task_id: str, report_text: str) -> None:
    """Require report claims to be backed by durable, task-declared evidence."""
    task_text = find_task_file(project_root, task_id).read_text(encoding="utf-8")
    entries = execution_entries(project_root, task_id)
    commands = validation_commands(task_text)
    missing_validations = [
        command_id for command_id, command in commands.items()
        if not any(
            entry.get("id") == command_id
            and entry.get("command") == command
            and entry.get("exitStatus") == 0
            for entry in entries
        )
    ]
    if missing_validations:
        raise stop_error(
            "HANDOFF_VALIDATION_EVIDENCE_MISSING",
            f"rule: every declared validation needs a successful durable record; source checked: "
            f"{EXECUTION_EVIDENCE_PATH.as_posix()} for {task_id}; accepted: an entry with the declared id and "
            f"command and exitStatus 0; missing for: " + ", ".join(missing_validations),
            task_id=task_id,
        )

    investigations = [entry for entry in entries if entry.get("kind") == "investigation"]
    reported = re.search(r"^- Isolated exploration:\s*(.+)$", report_text, re.MULTILINE)
    assert reported is not None  # HANDOFF_FIELDS has already checked its presence.
    value = reported.group(1).strip()
    if not investigations:
        if not re.match(r"(?i)(?:none|no)(?![A-Za-z0-9])", value):
            raise stop_error(
                "HANDOFF_EXPLORATION_MISMATCH",
                f"rule: with no recorded investigation the report must say there was none; field checked: "
                f"Isolated exploration against {EXECUTION_EVIDENCE_PATH.as_posix()}; accepted: `none`, or text "
                f"starting with `none` or `no`; found: {value!r}; expected `none` (or record the investigation)",
                task_id=task_id,
            )
        return
    if value.lower() == "none":
        raise stop_error(
            "HANDOFF_EXPLORATION_MISMATCH",
            f"rule: recorded investigations must be reported; field checked: Isolated exploration against "
            f"{EXECUTION_EVIDENCE_PATH.as_posix()}; accepted: a summary of each recorded investigation; "
            f"found: `none` with {len(investigations)} recorded",
            task_id=task_id,
        )
    missing_summaries = [
        str(entry.get("question", ""))
        for entry in investigations
        if str(entry.get("question", "")) not in report_text
        or str(entry.get("finding", "")) not in report_text
    ]
    if missing_summaries:
        raise stop_error(
            "HANDOFF_EXPLORATION_SUMMARY_MISSING",
            f"rule: the report must contain each recorded question and finding; source checked: "
            f"{EXECUTION_EVIDENCE_PATH.as_posix()}; accepted: the exact question and finding text; "
            f"missing the question or finding of: " + "; ".join(missing_summaries),
            task_id=task_id,
        )


def check_handoff(project_root: Path, task_id: str, report: Path) -> str:
    """Reject incomplete completion evidence before it can be used as a handoff."""
    if not report.is_file():
        raise stop_error(
            "HANDOFF_REPORT_MISSING",
            f"rule: the handoff check reads a completion report; source checked: {report}; "
            "expected: an existing file; found: no such file",
            task_id=task_id,
        )
    text = report.read_text(encoding="utf-8")
    missing = [field for field in HANDOFF_FIELDS if not re.search(rf"^- {re.escape(field)}:\s*\S+", text, re.MULTILINE)]
    if missing:
        labels = re.findall(r"^- ([^:\n]+):", text, re.MULTILINE)
        malformed = {
            field: label for field in missing for label in labels
            if label not in HANDOFF_FIELDS and re.match(rf"{re.escape(field)}(?![A-Za-z0-9])", label)
        }
        if malformed:
            raise stop_error(
                "HANDOFF_FIELD_FORMAT",
                f"rule: a required field's name must be followed directly by the colon; source checked: {report.name}; "
                "accepted form: `- <Field>: <value>`; found: "
                + "; ".join(f"`- {label}:` (expected `- {field}: <value>`)" for field, label in malformed.items()),
                task_id=task_id,
            )
        raise stop_error(
            "HANDOFF_FIELDS_MISSING",
            f"rule: every required field needs a non-empty value; source checked: {report.name}; "
            "accepted form: `- <Field>: <value>`; required: " + ", ".join(HANDOFF_FIELDS)
            + "; missing: " + ", ".join(missing),
            task_id=task_id,
        )
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    if f"Completion Report — {canonical_id}" not in text:
        heading = re.search(r"Completion Report — (\S+)", text)
        raise stop_error(
            "HANDOFF_TASK_MISMATCH",
            f"rule: the report must identify its task; source checked: {report.name}; "
            f"accepted: `Completion Report — {canonical_id}`; found: "
            + (f"`{heading.group(0)}`" if heading else "no Completion Report heading"),
            task_id=task_id,
        )
    verify_validation_skips(text, task_id)
    verify_execution_evidence(project_root, task_id, text)
    return f"Handoff evidence complete for {task_id}: {report}"


def default_handoff_path(project_root: Path, task_id: str) -> Path:
    return resolve_task_identity(project_root, task_id, "existing").handoff_path


def readiness_check(project_root: Path, task_id: str, report: Path) -> str:
    """Combine execution and handoff gates before a task enters review."""
    execution_preflight(project_root, task_id)
    verify_host_impact_completion_evidence(find_task_file(project_root, task_id).read_text(encoding="utf-8"))
    check_handoff(project_root, task_id, report)
    return f"READY_FOR_REVIEW gate passed for {task_id}"


def _execution_location(project_root: Path, task_id: str, *,
                        command: tuple[str, ...] = ("execution", "start")) -> dict[str, object]:
    """Verify the supplied checkout independently of the caller's directory."""
    supplied = project_root.resolve()
    # A stale path may still have a Git parent. Never infer a different task
    # checkout from cwd; cwd is only a fallback for locating the primary.
    primary = None
    for candidate in (supplied, *supplied.parents, Path.cwd()):
        try:
            primary = canonical_project_root(candidate)
            break
        except MeridianError:
            continue
    if primary is None:
        raise MeridianError(f"cannot identify the primary checkout from {supplied}")
    identity = resolve_task_identity(primary, task_id, "existing", allow_archived_queue_links=True)
    result, _valid = inspect_task_worktree(
        task_id, None, primary, require_effective_worktree=False,
        inspection_directory=primary, identity=identity)
    expected = Path(str(result["worktree"])).resolve()
    if supplied != expected or "unregistered-worktree" in result["errors"]:
        detail = (f"cwd={Path.cwd().resolve()}; --project={supplied}; expected worktree={expected}; "
                  + ("no registered task worktree" if "unregistered-worktree" in result["errors"]
                     else "--project does not name the canonical task worktree"))
        recovery = None
        if "unregistered-worktree" not in result["errors"]:
            recovery = shlex.join(("meridian", *command, identity.canonical_id, "--project", str(expected)))
        error = stop_error("WRONG_WORKTREE", detail, resume=recovery,
                           task_id=identity.canonical_id, project=shlex.quote(str(primary)))
        if recovery is not None:
            error.recovery_worktree = expected
            error.recovery_detail = detail
        raise error
    return result


def _execution_worktree(project_root: Path, task_id: str, *, resume: bool = False,
                        repeated_start: bool = False,
                        command: tuple[str, ...] = ("execution", "start"),
                        inspection: dict[str, object] | None = None) -> dict[str, object]:
    """Reuse canonical worktree verification; Resume is explicit, never inferred."""
    project_root = project_root.resolve()
    result = inspection if inspection is not None else _execution_location(project_root, task_id, command=command)
    errors = list(result["errors"])
    if errors == ["dirty-worktree"] and (resume or repeated_start):
        if repeated_start and not resume:
            identity = resolve_task_identity(project_root, task_id, "existing")
            owned = {state_path(project_root, identity.canonical_id).relative_to(project_root).as_posix(),
                     identity.task_path.relative_to(project_root).as_posix()}
            changed = set(git_output(project_root, "diff", "HEAD", "--name-only").splitlines())
            untracked = set(git_output(project_root, "ls-files", "--others", "--exclude-standard").splitlines())
            prior_record = _run_git(project_root, "show", f"HEAD:{identity.task_path.relative_to(project_root)}")
            expected_record = re.sub(r"^Status:[^\n]*", "Status: IN_PROGRESS", prior_record.stdout, flags=re.MULTILINE)
            state = _execution_state(project_root, task_id)
            previous = _run_git(project_root, "show", f"HEAD:{state_path(project_root, task_id).relative_to(project_root)}")
            if previous.returncode:
                original = {"version": 1, "task_id": task_id, "workflow": "governed-sdd", "status": "QUEUED", "transitions": []}
            else:
                original = json.loads(previous.stdout)
            expected_state = dict(original)
            if original["status"] == "QUEUED" and state["transitions"]:
                expected_state.update(status="IN_PROGRESS", transitions=original["transitions"] + [state["transitions"][-1]])
            # A repeated start tolerates only the exact command-owned projection.
            if (changed | untracked <= owned and prior_record.returncode == 0
                    and identity.task_path.read_text(encoding="utf-8") == expected_record
                    and state == expected_state):
                errors = []
        else:
            errors = []
    if errors or result["integration_active"]:
        raise stop_error("WRONG_WORKTREE", "execution worktree verification: "
                         + ", ".join(errors or ["integration-active"]), task_id=task_id, project=canonical_project_root(project_root))
    return result


def _execution_state(project_root: Path, task_id: str) -> dict[str, object]:
    record = find_task_file(project_root, task_id).read_text(encoding="utf-8")
    return read_task_state(project_root, task_id, detect_mode(project_root),
                           spike=read_task_field(record, "Class") == "SPIKE",
                           review_required=read_task_field(record, "Review") != "NOT_REQUIRED",
                           stop_factory=stop_error)


def execution_start(project_root: Path, task_id: str, *, resume: bool = False) -> dict[str, object]:
    """Record the first legal start only after worktree and contract preflight."""
    inspection = _execution_location(project_root, task_id)
    identity = resolve_task_identity(project_root, task_id, "existing", allow_archived_queue_links=True)
    task_id = identity.canonical_id
    workflow = detect_mode(project_root)
    record = identity.task_path.read_text(encoding="utf-8")
    state = read_task_state(project_root, task_id, workflow,
                            spike=read_task_field(record, "Class") == "SPIKE",
                            review_required=read_task_field(record, "Review") != "NOT_REQUIRED",
                            stop_factory=stop_error) if state_path(project_root, task_id).exists() else None
    _execution_worktree(project_root, task_id, resume=resume,
                        repeated_start=bool(state and state["status"] == "IN_PROGRESS"), inspection=inspection)
    status = state["status"] if state else "QUEUED"
    if resume and workflow == "lean-delivery" and status == "DONE" and identity.task_path.parent.name == "done":
        dirty = bool(git_output(project_root, "status", "--porcelain"))
        return {"task_id": task_id, "workflow": workflow, "status": status, "started": False,
                "state": state, "commit": git_output(project_root, "rev-parse", "HEAD"),
                "next_action": "commit-closure-records" if dirty else "worktree-advance"}
    eligible = ("QUEUED",) if workflow == "lean-delivery" else ("QUEUED", "IN_PROGRESS")
    if status not in eligible:
        raise stop_error("TASK_STATUS_REJECTED", f"execution start allows {eligible}; found {status}", task_id=task_id, project=canonical_project_root(project_root))
    if workflow == "governed-sdd":
        execution_preflight(project_root, task_id)
        if status == "QUEUED":
            state = transition_task_state(project_root, task_id, "IN_PROGRESS")
    # Lean has no execution-contract requirement or IN_PROGRESS machine state.
    return {"task_id": task_id, "workflow": workflow, "status": state["status"] if state else status,
            "started": workflow == "governed-sdd", "state": state,
            "commit": git_output(project_root, "rev-parse", "HEAD")}


def _execution_owned_paths(project_root: Path, task_id: str) -> set[str]:
    identity = resolve_task_identity(project_root, task_id, "existing")
    return {path.relative_to(project_root).as_posix() for path in
            (identity.task_path, identity.handoff_path, state_path(project_root, task_id))} | {EXECUTION_EVIDENCE_PATH.as_posix()}


def execution_source_digest(project_root: Path, task_id: str) -> str:
    """Bind validation to source contents and modes, including unstaged files.

    Only the task's delivery-owned paths are excluded. Queue, plan, and other
    tasks remain part of the fingerprint. No index or Git object is written.
    """
    owned = _execution_owned_paths(project_root, task_id)
    paths = set(git_output(project_root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0"))
    entries = []
    for relative in sorted(paths - owned - {""}):
        path = project_root / relative
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            entries.append((relative, bool(path.stat().st_mode & 0o111), hashlib.sha256(path.read_bytes()).hexdigest()))
        elif path.is_dir():
            # Gitlinks carry a commit identity; dirty nested trees cannot be delivered.
            entries.append((relative, "gitlink", git_output(path, "rev-parse", "HEAD"),
                            git_output(path, "status", "--porcelain")))
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def _delivery_current_commit(project_root: Path, task_id: str, report: Path, head: str, base: str) -> None:
    """Reject handoff commit fields that cannot identify the review HEAD."""
    text = report.read_text(encoding="utf-8")
    match = re.search(r"^- Current task commit:[ \t]*(.+)$", text, re.MULTILINE)
    value = match.group(1).strip().strip("`") if match else ""
    valid = False
    if re.fullmatch(r"[0-9a-f]{40}", value):
        valid = value != base and _run_git(project_root, "merge-base", "--is-ancestor", value, head).returncode == 0
    elif value:
        subject = git_output(project_root, "log", "-1", "--format=%s", head)
        branch = git_output(project_root, "branch", "--show-current")
        # Delivery's known subject is usable before its commit exists.
        valid = (f"Deliver {task_id} for review" in value
                 or (subject in value and branch in value))
    if not valid:
        raise stop_error(
            "EVIDENCE_INCOMPLETE",
            "Current task commit must name a full task commit SHA (never the validated base main commit), "
            f"or describe the commit by subject and branch; for delivery use `Deliver {task_id} for review`; "
            f"found: {value!r}", task_id=task_id, project=canonical_project_root(project_root))


def _delivery_later_commits(project_root: Path, task_id: str, state: dict[str, object], head: str,
                            owned: set[str], report_path: str) -> list[str]:
    """Check every post-delivery commit, including changes later reverted.

    The transition anchors the original delivery's parent. Subsequent empty
    Deliver commits renew the review anchor without inventing state transitions.
    """
    transition_head = state["transitions"][-1]["commit"]
    if _run_git(project_root, "merge-base", "--is-ancestor", transition_head, head).returncode:
        raise stop_error("EVIDENCE_INCOMPLETE", "delivery transition HEAD is not an ancestor",
                         task_id=task_id, project=canonical_project_root(project_root))
    commits = git_output(project_root, "rev-list", "--reverse", f"{transition_head}..{head}").splitlines()
    if not commits:
        raise stop_error("EVIDENCE_INCOMPLETE", "READY_FOR_REVIEW needs a committed delivery",
                         task_id=task_id, project=canonical_project_root(project_root))
    delivery_paths = owned - {EXECUTION_EVIDENCE_PATH.as_posix(), report_path}
    later = []
    for index, commit in enumerate(commits):
        paths = set(git_output(project_root, "diff", "--name-only", f"{commit}^", commit).splitlines())
        allowed = delivery_paths if index == 0 else {report_path}
        if paths - allowed:
            raise stop_error("EVIDENCE_INCOMPLETE", "changes after delivery require renewed implementation and delivery",
                             task_id=task_id, project=canonical_project_root(project_root))
        if index and (paths or git_output(project_root, "log", "-1", "--format=%s", commit) != f"Deliver {task_id} for review"):
            later.append(commit)
        else:
            later = []
    return later


def delivery_readiness(project_root: Path, task_id: str, *, verify_worktree: bool = True,
                       allow_handoff_correction: bool = False) -> dict[str, object]:
    """Read-only delivery gate, also used by direct READY_FOR_REVIEW transitions."""
    inspection = _execution_location(project_root, task_id, command=("execution", "deliver"))
    identity = resolve_task_identity(project_root, task_id, "existing")
    task_id = identity.canonical_id
    state = _execution_state(project_root, task_id)
    record = identity.task_path.read_text(encoding="utf-8")
    if (state["workflow"] != "governed-sdd" or read_task_field(record, "Class") == "SPIKE"
            or not state.get("review", {}).get("required", True)
            or state["status"] not in ("IN_PROGRESS", "READY_FOR_REVIEW")):
        raise stop_error("TASK_STATUS_REJECTED", f"delivery requires a review-required Governed task; found {state['status']}", task_id=task_id, project=canonical_project_root(project_root))
    if verify_worktree:
        worktree = _execution_worktree(project_root, task_id, inspection=inspection)
    else:
        if git_output(project_root, "status", "--porcelain"):
            raise stop_error("WRONG_WORKTREE", "delivery requires a clean worktree", task_id=task_id, project=canonical_project_root(project_root))
        primary = canonical_project_root(project_root)
        worktree, valid = inspect_task_worktree(task_id, None, primary, require_effective_worktree=False,
                                                  inspection_directory=primary)
        if not valid or worktree["integration_active"] or Path(worktree["worktree"]).resolve() != project_root.resolve():
            raise stop_error("WRONG_WORKTREE", "delivery requires the clean canonical worktree", task_id=task_id, project=canonical_project_root(project_root))
    readiness_check(project_root, task_id, identity.handoff_path)
    head = git_output(project_root, "rev-parse", "HEAD")
    base = str(worktree["base_commit"])
    owned = _execution_owned_paths(project_root, task_id)
    changed = set(git_output(project_root, "diff", "--name-only", base, head).splitlines())
    if not changed - owned:
        raise stop_error("EVIDENCE_INCOMPLETE", "delivery needs a committed implementation change after the prepared base", task_id=task_id, project=canonical_project_root(project_root))
    report_path = identity.handoff_path.relative_to(project_root).as_posix()
    if _run_git(project_root, "cat-file", "-e", f"HEAD:{report_path}").returncode:
        raise stop_error("EVIDENCE_INCOMPLETE", "final handoff must be committed", task_id=task_id, project=canonical_project_root(project_root))
    _delivery_current_commit(project_root, task_id, identity.handoff_path, head, base)
    digest = execution_source_digest(project_root, task_id)
    entries = execution_entries(project_root, task_id)
    commands = validation_commands(record)
    if not commands:
        raise stop_error("EVIDENCE_INCOMPLETE", "delivery needs declared completed validation evidence", task_id=task_id, project=canonical_project_root(project_root))
    for command_id, command in commands.items():
        matching = [entry for entry in entries if entry.get("id") == command_id]
        entry = matching[-1] if matching else {}
        commit = entry.get("commit", "")
        if (entry.get("command") != command or entry.get("exitStatus") != 0
                or entry.get("sourceDigest") != digest or not re.fullmatch(r"[0-9a-f]{40}", str(commit))
                or _run_git(project_root, "merge-base", "--is-ancestor", str(commit), head).returncode):
            raise stop_error("EVIDENCE_INCOMPLETE", f"validation {command_id} is missing, failing, or stale; rerun execution validate and commit evidence/handoff", task_id=task_id, project=canonical_project_root(project_root))
    if state["status"] == "READY_FOR_REVIEW":
        persisted = _run_git(project_root, "show", f"HEAD:{state_path(project_root, task_id).relative_to(project_root)}")
        if persisted.returncode or json.loads(persisted.stdout) != state:
            raise stop_error("EVIDENCE_INCOMPLETE", "READY_FOR_REVIEW state must be committed", task_id=task_id, project=canonical_project_root(project_root))
        later = _delivery_later_commits(project_root, task_id, state, head, owned, report_path)
        if later and not allow_handoff_correction:
            raise stop_error("EVIDENCE_INCOMPLETE", "handoff correction requires execution deliver before review",
                             task_id=task_id, project=canonical_project_root(project_root))
    return {"task_id": task_id, "commit": head, "clean": True, "status": state["status"]}


def execution_deliver(project_root: Path, task_id: str) -> dict[str, object]:
    result = delivery_readiness(project_root, task_id, allow_handoff_correction=True)
    task_id = str(result["task_id"])
    if result["status"] == "READY_FOR_REVIEW":
        identity = resolve_task_identity(project_root, task_id, "existing")
        later = _delivery_later_commits(
            project_root, task_id, _execution_state(project_root, task_id), str(result["commit"]),
            _execution_owned_paths(project_root, task_id), identity.handoff_path.relative_to(project_root).as_posix())
        if later:
            completed = _run_git(project_root, "commit", "--allow-empty", "-m", f"Deliver {task_id} for review")
            if completed.returncode:
                raise stop_error("EVIDENCE_INCOMPLETE", f"re-delivery commit failed: {completed.stderr.strip()}",
                                 task_id=task_id, project=canonical_project_root(project_root))
        return delivery_readiness(project_root, task_id)
    try:
        transition_task_state(project_root, task_id, "READY_FOR_REVIEW")
    except (OSError, MeridianError) as error:
        actual = _execution_state(project_root, task_id)["status"]
        raise stop_error("EVIDENCE_INCOMPLETE", f"delivery transition failed: {error}; actual state {actual}; inspect git status and repair command-owned state/projection before retrying delivery",
                         task_id=task_id, project=canonical_project_root(project_root)) from error
    identity = resolve_task_identity(project_root, task_id, "existing")
    paths = [state_path(project_root, task_id).relative_to(project_root).as_posix(),
             identity.task_path.relative_to(project_root).as_posix()]
    for args in (("add", "--", *paths), ("commit", "-m", f"Deliver {task_id} for review", "--", *paths)):
        completed = _run_git(project_root, *args)
        if completed.returncode:
            raise stop_error("EVIDENCE_INCOMPLETE", f"delivery {args[0]} failed: {completed.stderr.strip()}; actual state READY_FOR_REVIEW, pending delivery; inspect git status, commit only state/projection, then rerun execution deliver", task_id=task_id, project=canonical_project_root(project_root))
    return delivery_readiness(project_root, task_id)


def record_validation(project_root: Path, task_id: str, command_id: str, command: str, status: int,
                      binding: dict[str, str] | None = None) -> None:
    path = project_root / EXECUTION_EVIDENCE_PATH
    state: dict[str, object] = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise MeridianError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    entries = list(state.get(canonical_id, []))
    entries.append({"id": command_id, "command": command, "exitStatus": status, **(binding or {})})
    state[canonical_id] = entries
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_validation(project_root: Path, task_id: str, command_id: str) -> int:
    """Execute only the task-declared literal command and retain its outcome."""
    execution_preflight(project_root, task_id)
    text = find_task_file(project_root, task_id).read_text(encoding="utf-8")
    commands = validation_commands(text)
    if command_id not in commands:
        available = ", ".join(sorted(commands)) or "none"
        raise stop_error(
            "VALIDATION_ID_UNDECLARED",
            f"rule: only a task-declared validation ID runs; field checked: Validation in the {task_id} record; "
            f"accepted: {available}; found: {command_id!r}",
        )
    command = commands[command_id]
    head = _run_git(project_root, "rev-parse", "HEAD")
    binding = ({"commit": head.stdout.strip(), "sourceDigest": execution_source_digest(project_root, task_id)}
               if head.returncode == 0 else None)
    completed = subprocess.run(command, shell=True, executable="/bin/bash", cwd=project_root, check=False)
    record_validation(project_root, task_id, command_id, command, completed.returncode, binding)
    print(f"Validation {task_id}/{command_id}: exit {completed.returncode}")
    return completed.returncode


def record_execution_event(
    project_root: Path,
    task_id: str,
    kind: str,
    gap: str,
    criterion: str | None,
    artifact: str | None,
) -> str:
    """Spend a semantic budget only alongside the evidence that justifies it."""
    if not gap.strip():
        raise stop_error(
            "EXECUTION_EVIDENCE_ARGUMENTS",
            f"rule: evidence is recorded with the gap that justifies it; option checked: --gap; "
            f"accepted: a non-empty string; found: {gap!r}",
        )
    if kind == "captures" and (not criterion or not artifact):
        absent = [name for name, value in (("--criterion", criterion), ("--artifact", artifact)) if not value]
        raise stop_error(
            "EXECUTION_EVIDENCE_ARGUMENTS",
            "rule: captures need provenance; options checked: --criterion and --artifact; "
            "accepted: both non-empty; missing: " + ", ".join(absent),
        )
    count, cap = budget_spend(project_root, task_id, kind, criterion if kind == "captures" else None)
    path = project_root / EXECUTION_EVIDENCE_PATH
    state: dict[str, object] = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise MeridianError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    events = list(state.get(canonical_id, []))
    event: dict[str, object] = {"kind": kind, "gap": gap, "count": count, "cap": cap}
    if criterion:
        event["criterion"] = criterion
    if artifact:
        event["artifact"] = artifact
    events.append(event)
    state[canonical_id] = events
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"Evidence {task_id}: {kind} {count}/{cap} recorded"


def record_investigation(
    project_root: Path,
    task_id: str,
    question: str,
    scope: int,
    sources: list[str],
    finding: str,
) -> str:
    """Record a bounded exploration without making a host or worker normative."""
    empty = [option for option, present in (("--question", question.strip()), ("--source", sources), ("--finding", finding.strip())) if not present]
    if empty:
        raise stop_error(
            "EXECUTION_EVIDENCE_ARGUMENTS",
            "rule: an investigation records its question, sources, and finding; options checked: --question, --source, "
            "--finding; accepted: a non-empty value for each; found: missing or empty " + ", ".join(empty),
            resume="rerun meridian execution investigate with --question, --source, and --finding",
        )
    execution_preflight(project_root, task_id)
    count, cap = budget_spend(project_root, task_id, "investigations", amount=scope)
    path = project_root / EXECUTION_EVIDENCE_PATH
    state: dict[str, object] = {}
    if path.is_file():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise MeridianError(f"invalid execution evidence state: {path}") from error
    canonical_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    events = list(state.get(canonical_id, []))
    events.append({
        "kind": "investigation",
        "question": question,
        "scope": scope,
        "sources": sources,
        "finding": finding,
        "count": count,
        "cap": cap,
    })
    state[canonical_id] = events
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"Investigation {task_id}: {count}/{cap} recorded"


# `CLAUDE.md` is Claude Code's own instructions file; it cannot be reduced to a
# bare pointer, since a Claude Code session never reads `AGENTS.md` itself. So
# each workflow's `CLAUDE.md` keeps a hand-authored preamble (title, pointer
# paragraph, any Claude-Code-specific sections) up to this anchor heading, and
# everything from the anchor onward — the actual shared rule content, capability
# markers included — is generated verbatim from `AGENTS.md`, which stays the
# single source of truth for that text. The anchor is matched by heading text,
# not position, per this repo's own role-scoped-agent-rules precedent: it must
# be a heading that both files currently carry.
CLAUDE_MD_SHARED_ANCHOR = {
    "governed-sdd": "## Command triggers",
    "lean-delivery": "## Command triggers",
}


class MeridianArgumentParser(argparse.ArgumentParser):
    """Use sysexits-style usage status for machine-oriented namespaces."""

    def error(self, message: str) -> None:
        if " task identity" in self.prog or " worktree" in self.prog:
            self.print_usage(sys.stderr)
            self.exit(64, f"{self.prog}: error: {message}\n")
        super().error(message)


def generate_claude_md(mode: str, agents_text: str, existing_claude_text: str) -> str:
    anchors = (CLAUDE_MD_SHARED_ANCHOR[mode], "## Code organization") if mode == "governed-sdd" else (CLAUDE_MD_SHARED_ANCHOR[mode],)
    for anchor in anchors:
        pattern = re.compile(rf"^{re.escape(anchor)}$", re.MULTILINE)
        agents_match = pattern.search(agents_text)
        claude_match = pattern.search(existing_claude_text)
        if agents_match is not None and claude_match is not None:
            break
    else:
        raise MeridianError(f"AGENTS.md and CLAUDE.md ({mode}) do not share a supported anchor heading")
    preamble = existing_claude_text[: claude_match.start()]
    shared_body = agents_text[agents_match.start() :]

    # A capability marker's content is versioned; changing it without bumping
    # the version is exactly the defect this generator must never reproduce
    # (see tasks/014-generator-altered-protected-blocks.md). So the shared
    # body is copied from AGENTS.md everywhere *except* inside a marker: there,
    # CLAUDE.md's own existing block for that same capability+version wins
    # verbatim, byte for byte, if one is already present. A capability with no
    # prior block in CLAUDE.md (a brand-new marker) has nothing to preserve,
    # so it is copied from AGENTS.md like the rest of the shared body.
    def preserve_existing_marker(match: re.Match[str]) -> str:
        capability, version = match.group(1), int(match.group(2))
        existing_block = extract_marked_block(existing_claude_text, capability, version)
        return existing_block if existing_block is not None else match.group(0)

    shared_body = MARKED_BLOCK.sub(preserve_existing_marker, shared_body)
    return preamble + shared_body


class ShowVersionAction(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, default=argparse.SUPPRESS, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        print(parse_semver(read_raw_version(namespace.framework_root)))
        parser.exit()


def main() -> int:
    if sys.argv[1:2] == ["hook"]:
        try:
            Path.cwd()
        except FileNotFoundError:
            # Advisory hooks must also tolerate an inherited, deleted cwd.
            return 0
    journal = LifecycleJournalEntry()
    exit_code = _run_cli(journal)
    journal.write(exit_code)
    return exit_code


def build_parser() -> MeridianArgumentParser:
    """Build the CLI parser, also used to verify the published command surface."""
    parser = MeridianArgumentParser(prog="meridian")
    parser.add_argument(
        "--framework-root",
        type=Path,
        default=Path(os.environ.get("MERIDIAN_ROOT", Path(__file__).resolve().parents[1])),
    )
    parser.add_argument(
        "--version",
        action=ShowVersionAction,
        help="print the framework SemVer, including prerelease and build metadata",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    self_check = subparsers.add_parser(
        "self-check", help="inspect this Meridian installation"
    )
    self_check.add_argument(
        "--check-latest",
        action="store_true",
        required=True,
        help="query the latest public GitHub Release",
    )

    self_update = subparsers.add_parser(
        "self-update", help="update the CLI checkout (experimental)",
        description="Experimental: plan or apply an update of the running CLI checkout.",
    )
    update_mode = self_update.add_mutually_exclusive_group(required=True)
    update_mode.add_argument("--check", action="store_true")
    update_mode.add_argument("--apply", action="store_true")
    self_update.add_argument("--to", dest="target_tag")

    console = subparsers.add_parser(
        "console", help="open the read-only project state console (experimental)",
        description="Experimental: interactive keys and agent launch may change in minor releases."
    )
    console.add_argument("--project", type=Path, default=Path.cwd())
    console.add_argument(
        "--interval", type=float, default=2.0,
        help="seconds between local refreshes (default: 2)",
    )

    lock = subparsers.add_parser("lock", help="register a newly initialized project for deterministic upgrades")
    lock.add_argument("--project", type=Path, default=Path.cwd())
    lock.add_argument("--mode", choices=("lean-delivery", "governed-sdd"), required=True)

    upgrade = subparsers.add_parser("upgrade", help="plan or apply a framework upgrade")
    upgrade.add_argument("--project", type=Path, default=Path.cwd())
    group = upgrade.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    upgrade.add_argument(
        "--owner-reconciled",
        action="store_true",
        help="register the target version and baseline without touching any managed file, "
        "for a project too customized for the automatic three-way merge whose developer has "
        "already reconciled every managed file by hand outside this command; --apply only",
    )
    upgrade.add_argument(
        "--stop-before-retirement",
        action="store_true",
        help="cap this upgrade to the last migration before the first one that retires a "
        "duplicated entry-point marker, so a long-lag consumer can complete an additive-only "
        "release; a no-op if no pending migration retires anything",
    )

    adopt = subparsers.add_parser("adopt", help="migrate an untracked project from a packaged baseline")
    adopt.add_argument("--project", type=Path, default=Path.cwd())
    adopt.add_argument(
        "--mode",
        choices=("lean-delivery", "governed-sdd"),
        help="detected from the project's PROJECT_WORKFLOW.md mode lock when omitted",
    )
    adopt.add_argument(
        "--from",
        dest="source_version",
        help="detected when exactly one packaged baseline is available for the mode",
    )
    adopt_group = adopt.add_mutually_exclusive_group(required=True)
    adopt_group.add_argument("--check", action="store_true")
    adopt_group.add_argument("--apply", action="store_true")
    adopt.add_argument(
        "--assisted",
        action="store_true",
        help="produce a capability-aware plan for an agent instead of generic template merging",
    )
    adopt.add_argument(
        "--emit",
        choices=("implementer", "reviewer", "orchestrator"),
        help="print only the named prompt block, with --assisted --check, for a host or operator to relay directly",
    )

    finalize = subparsers.add_parser(
        "finalize-adoption",
        help="write a manifest after an assisted migration has been reviewed",
    )
    finalize.add_argument("--project", type=Path, default=Path.cwd())
    finalize.add_argument(
        "--mode",
        choices=("lean-delivery", "governed-sdd"),
        help="detected from the project's PROJECT_WORKFLOW.md mode lock when omitted",
    )
    finalize.add_argument(
        "--owner-accepted",
        action="store_true",
        help="skip the independent-review gate after the developer personally reviewed the migration, "
        "mirroring the `Accept <TASK-ID>` owner-acceptance path",
    )

    audit = subparsers.add_parser(
        "audit",
        help="verify protected capability-marker regions were not edited outside meridian upgrade",
    )
    audit.add_argument("--project", type=Path, default=Path.cwd())
    audit.add_argument(
        "--mode",
        choices=("lean-delivery", "governed-sdd"),
        help="detected from the project's PROJECT_WORKFLOW.md mode lock when omitted",
    )
    audit.add_argument(
        "--ci-profile",
        help="gate catalog-required static installation while retaining visible host UNVERIFIED rows",
    )

    profile_parser = subparsers.add_parser(
        "profile", description="Framework-internal: no compatibility promise.", help="inspect or bootstrap an effective capability profile (framework-internal)"
    )
    profile_sub = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_doctor_parser = profile_sub.add_parser(
        "doctor", description="Framework-internal: no compatibility promise.", help="resolve a declared profile, its evidence, and required probes (framework-internal)"
    )
    profile_doctor_parser.add_argument("profile_id")
    profile_doctor_parser.add_argument("--project", type=Path, default=Path.cwd())
    profile_bootstrap = profile_sub.add_parser(
        "bootstrap", description="Framework-internal: no compatibility promise.", help="observe installation surfaces without claiming host activation (framework-internal)"
    )
    profile_bootstrap.add_argument("profile_id")
    profile_bootstrap.add_argument("--project", type=Path, default=Path.cwd())
    profile_action = profile_bootstrap.add_mutually_exclusive_group(required=True)
    profile_action.add_argument("--check", action="store_true")
    profile_action.add_argument("--apply", action="store_true")

    locations = subparsers.add_parser("locations", help="print resolved project locations")
    locations.add_argument("--project", type=Path, default=Path.cwd())
    locations.add_argument("--field", choices=("queue", "queue-archive", "task-roots", "review-root", "handoff-root", "adr-log", "plan"))

    project = subparsers.add_parser("project", help="show the resolved project declaration")
    project.add_argument("show", nargs="?", default="show")
    project.add_argument("--project", type=Path, default=Path.cwd())
    project.add_argument("--field", choices=("project", "locations", "validation-scoping", "ci", "reviewer-author"))
    project.add_argument("--format", choices=("json", "text"), default="text")

    setup = subparsers.add_parser("setup", help="plan or apply worktree, Codex, and project Claude Code setup")
    setup_group = setup.add_mutually_exclusive_group(required=True)
    setup_group.add_argument("--check", action="store_true")
    setup_group.add_argument("--apply", action="store_true")
    setup.add_argument("--worktree-root", type=Path)
    setup.add_argument("--project", type=Path, default=Path.cwd())
    setup.add_argument(
        "--task-identity",
        choices=("opaque", "milestone"),
        help="record the project's task-identity choice without changing an existing declaration",
    )
    setup.add_argument("--config", type=Path, default=Path.home() / ".codex/config.toml", help=argparse.SUPPRESS)

    codex = subparsers.add_parser("codex", help="configure and diagnose Codex task-worktree access")
    codex_sub = codex.add_subparsers(dest="codex_command", required=True)
    codex_configure = codex_sub.add_parser("configure", help="plan or apply a bounded Codex permission profile")
    codex_configure_group = codex_configure.add_mutually_exclusive_group(required=True)
    codex_configure_group.add_argument("--check", action="store_true")
    codex_configure_group.add_argument("--apply", action="store_true")
    codex_configure.add_argument("--worktree-root", type=Path)
    codex_configure.add_argument("--config", type=Path, default=Path.home() / ".codex/config.toml", help=argparse.SUPPRESS)
    codex_configure.add_argument("--requirements", type=Path, help=argparse.SUPPRESS)
    codex_path = codex_sub.add_parser("worktree-path", help="derive one repository-qualified task worktree path")
    codex_path.add_argument("task_id")
    codex_path.add_argument("--project", type=Path, default=Path.cwd())
    codex_path.add_argument("--worktree-root", type=Path)
    codex_doctor_parser = codex_sub.add_parser("doctor", help="report Codex host capabilities separately")
    codex_doctor_parser.add_argument("--project", type=Path, default=Path.cwd())
    codex_doctor_parser.add_argument("--worktree-root", type=Path)
    codex_doctor_parser.add_argument("--config", type=Path, default=Path.home() / ".codex/config.toml", help=argparse.SUPPRESS)

    worktree = subparsers.add_parser("worktree", help="run the bounded host-neutral task-worktree lifecycle")
    worktree_sub = worktree.add_subparsers(dest="worktree_command", required=True)
    worktree_path_parser = worktree_sub.add_parser("path", help="derive the canonical task-worktree path")
    worktree_path_parser.add_argument("task_id")
    worktree_path_parser.add_argument("--project", type=Path)
    worktree_path_parser.add_argument("--worktree-root", type=Path)
    worktree_path_parser.add_argument("--format", choices=("json",))
    worktree_prepare = worktree_sub.add_parser("prepare", help="create or select exactly one canonical task worktree")
    worktree_prepare.add_argument("task_id")
    worktree_prepare.add_argument("--project", type=Path)
    worktree_prepare.add_argument("--worktree-root", type=Path)
    worktree_prepare.add_argument("--base", choices=("main",), default="main")
    worktree_prepare.add_argument(
        "--resume",
        action="store_true",
        help="accept an existing dirty worktree of this task; never creates or changes anything",
    )
    worktree_prepare.add_argument("--new-attempt", action="store_true", help="developer-authorized fresh budget attempt after retirement")
    worktree_prepare.add_argument("--reason", help="developer reason for the new attempt, recorded in the journal")
    worktree_prepare.add_argument("--format", choices=("json",), required=True)
    worktree_check = worktree_sub.add_parser("check", help="inspect the effective worker worktree without mutation")
    worktree_check.add_argument("task_id")
    worktree_check.add_argument("--project", type=Path)
    worktree_check.add_argument("--worktree-root", type=Path)
    worktree_check.add_argument("--format", choices=("json",), required=True)
    worktree_repair = worktree_sub.add_parser("repair-base", help="repair a proven commit-less main fast-forward base")
    worktree_repair.add_argument("task_id")
    worktree_repair.add_argument("--project", type=Path)
    worktree_repair.add_argument("--worktree-root", type=Path)
    worktree_repair.add_argument("--format", choices=("json",), required=True)
    worktree_active = worktree_sub.add_parser("active", description="Framework-internal: no compatibility promise.", help="resolve the active task from this registered worktree (framework-internal)")
    worktree_active.add_argument("--format", choices=("json",), required=True)
    worktree_states = worktree_sub.add_parser("states", description="Framework-internal: no compatibility promise.", help="list task states from registered worktrees (framework-internal)")
    worktree_states.add_argument("--project", type=Path, default=Path.cwd())
    worktree_states.add_argument("--format", choices=("json",), required=True)
    worktree_evidence = worktree_sub.add_parser(
        "evidence", description="Framework-internal: no compatibility promise.", help="record Git-derived task validation evidence without running commands (framework-internal)"
    )
    worktree_evidence.add_argument("task_id")
    worktree_evidence.add_argument("--project", type=Path)
    worktree_evidence.add_argument("--worktree-root", type=Path)
    worktree_evidence.add_argument("--accepted", action="store_true")
    worktree_evidence.add_argument("--validation-command", action="append", default=[])
    worktree_evidence.add_argument("--validation-exit-code", action="append", type=int, default=[])
    worktree_evidence.add_argument("--task-dependency", action="append", default=[])
    worktree_evidence.add_argument("--task-behavioral-surface", action="append", default=[])
    worktree_evidence.add_argument("--main-advanced-dependency", action="append", default=[])
    worktree_evidence.add_argument("--main-advanced-behavioral-surface", action="append", default=[])
    worktree_evidence.add_argument("--full-validation-required", action="store_true")
    worktree_evidence.add_argument("--format", choices=("json",), required=True)
    worktree_closure_status = worktree_sub.add_parser(
        "closure-status", description="Framework-internal: no compatibility promise.", help="report the next closure step without changing lifecycle state (framework-internal)"
    )
    worktree_closure_status.add_argument("task_id")
    worktree_closure_status.add_argument("--project", type=Path)
    worktree_closure_status.add_argument("--worktree-root", type=Path)
    worktree_closure_status.add_argument("--format", choices=("json",))
    worktree_advance = worktree_sub.add_parser(
        "advance", help="run the mechanical closure steps and report the next action the agent owns"
    )
    worktree_advance.add_argument("task_id")
    worktree_advance.add_argument("--project", type=Path)
    worktree_advance.add_argument("--worktree-root", type=Path)
    worktree_advance.add_argument("--accepted", action="store_true")
    worktree_advance.add_argument("--validation-command", action="append", default=[])
    worktree_advance.add_argument("--validation-exit-code", action="append", type=int, default=[])
    worktree_advance.add_argument("--candidate-command", action="append", default=[])
    worktree_advance.add_argument("--candidate-exit-code", action="append", type=int, default=[])
    worktree_advance.add_argument("--format", choices=("json",), required=True)
    worktree_integrate = worktree_sub.add_parser("integrate", help="stage, finalize, or abort one owned integration")
    integrate_sub = worktree_integrate.add_subparsers(dest="integrate_command", required=True)
    integrate_stage = integrate_sub.add_parser("stage", help="lease and stage the prescribed no-commit merge")
    integrate_stage.add_argument("task_id")
    integrate_stage.add_argument("--project", type=Path)
    integrate_stage.add_argument("--worktree-root", type=Path)
    integrate_stage.add_argument("--evidence", type=Path, required=True)
    integrate_stage.add_argument("--format", choices=("json",), required=True)
    integrate_finalize = integrate_sub.add_parser("finalize", help="commit an exactly validated staged candidate")
    integrate_finalize.add_argument("task_id")
    integrate_finalize.add_argument("--project", type=Path)
    integrate_finalize.add_argument("--evidence", type=Path, required=True)
    integrate_finalize.add_argument("--format", choices=("json",), required=True)
    integrate_abort = integrate_sub.add_parser("abort", help="abort one Meridian-owned staged integration")
    integrate_abort.add_argument("task_id")
    integrate_abort.add_argument("--project", type=Path)
    integrate_abort.add_argument("--format", choices=("json",), required=True)
    worktree_cleanup = worktree_sub.add_parser("cleanup", help="remove an integrated worktree and its merged local branch")
    worktree_cleanup.add_argument("task_id")
    worktree_cleanup.add_argument("--project", type=Path)
    worktree_cleanup.add_argument("--worktree-root", type=Path)
    worktree_cleanup.add_argument("--format", choices=("json",), required=True)

    validation = subparsers.add_parser("validation", description="Framework-internal: no compatibility promise.", help="read and verify an external validation evidence record (framework-internal)")
    validation_sub = validation.add_subparsers(dest="validation_command", required=True)
    validation_check = validation_sub.add_parser("check", description="Framework-internal: no compatibility promise.", help="verify a record without running validation (framework-internal)")
    validation_check.add_argument("record", type=Path)
    validation_check.add_argument("--project", type=Path, default=Path.cwd())
    validation_check.add_argument("--commit")
    validation_check.add_argument("--format", choices=("json",), required=True)

    review = subparsers.add_parser("review", help="record commit-bound task reviews")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    verdict = review_sub.add_parser("verdict", help="record a verdict and its task-state transition")
    verdict.add_argument("task_id")
    verdict.add_argument("verdict", choices=("APPROVE", "CHANGES_REQUESTED", "BLOCKED"))
    verdict.add_argument("--owner", action="store_true")
    verdict.add_argument("--body", default="", help="free-form review Markdown")
    verdict.add_argument("--project", type=Path, default=Path.cwd())
    verdict.add_argument("--format", choices=("json",), default="json")

    task = subparsers.add_parser("task", help="inspect task records and identities")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    transition = task_sub.add_parser("transition", help="apply a tracked task-state transition")
    transition.add_argument("task_id")
    transition.add_argument("status")
    transition.add_argument("--project", type=Path, default=Path.cwd())
    transition.add_argument("--format", choices=("json",), default="json")
    close = task_sub.add_parser("close", help="stage Lean task state and record archive without committing")
    close.add_argument("task_id")
    close.add_argument("--project", type=Path, default=Path.cwd())
    close.add_argument("--format", choices=("json",), default="json")
    state = task_sub.add_parser("state", help="explicit task-state adoption")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    state_import = state_sub.add_parser("import", help="preview or create state for legacy tasks")
    state_import.add_argument("task_ids", nargs="*")
    state_import.add_argument("--apply", action="store_true")
    state_import.add_argument("--include-terminal", action="store_true",
                              help="also propose state for terminal tasks, so queue archival reads it")
    state_import.add_argument("--project", type=Path, default=Path.cwd())
    state_import.add_argument("--format", choices=("json",), default="json")
    identity = task_sub.add_parser("identity", help="resolve the project-selected task identity policy")
    identity_sub = identity.add_subparsers(dest="identity_command", required=True)
    identity_check = identity_sub.add_parser("check", description="Framework-internal: no compatibility promise.", help="validate and print one resolved task identity (framework-internal)")
    identity_check.add_argument("task_id")
    identity_check.add_argument("--project", type=Path, default=Path.cwd())
    identity_check.add_argument("--format", choices=("json",), required=True)
    identity_next = identity_sub.add_parser("next", help="derive the next milestone-mode task identity")
    identity_next.add_argument("--milestone", required=True)
    identity_next.add_argument("--workstream", required=True)
    identity_next.add_argument("--project", type=Path, default=Path.cwd())
    identity_next.add_argument("--format", choices=("json",), required=True)

    adr = subparsers.add_parser("adr", help="read a project's ADR log")
    adr_sub = adr.add_subparsers(dest="adr_command", required=True)
    adr_show_parser = adr_sub.add_parser("show", help="print exactly one ADR section")
    adr_show_parser.add_argument("adr_id")
    adr_show_parser.add_argument("--project", type=Path, default=Path.cwd())
    adr_list_parser = adr_sub.add_parser("list", help="print one line per ADR: ID, title, and status")
    adr_list_parser.add_argument("--project", type=Path, default=Path.cwd())
    adr_list_parser.add_argument("--status", help="keep only entries whose Status field equals this value, ignoring case")
    adr_list_parser.add_argument("--format", choices=("text", "json"), default="text")

    context = subparsers.add_parser("context", help="inspect task authority or measure a role's startup read set")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    context_authority_parser = context_sub.add_parser(
        "authority", help="print a task's Authority entries resolved to ADR/spec excerpts"
    )
    context_authority_parser.add_argument("task_id")
    context_authority_parser.add_argument("--project", type=Path, default=Path.cwd())
    context_authority_parser.add_argument(
        "--labels-only", action="store_true", help="print source + heading only, not excerpt bodies"
    )
    context_size_parser = context_sub.add_parser("size", help="measure the documents a workflow role is instructed to read")
    context_size_parser.add_argument("--role", required=True, help="workflow role (for example implementation or review)")
    context_size_parser.add_argument("--task", dest="context_task_id")
    context_size_parser.add_argument("--project", type=Path, default=Path.cwd())
    context_size_parser.add_argument("--threshold-bytes", type=int, default=None, help="fail when an included file exceeds this size")
    context_size_parser.add_argument("--format", choices=("json", "text"), default="text")

    usage = subparsers.add_parser("usage", help="report local host session token counters (experimental)", description="Experimental: report local host session token counters without reading message content.")
    usage_sub = usage.add_subparsers(dest="usage_command", required=True)
    usage_report_parser = usage_sub.add_parser("report", help="summarize private host session token counters (experimental)", description="Experimental: summarize private host session token counters.")
    usage_report_parser.add_argument("--host", choices=USAGE_HOSTS)
    usage_report_parser.add_argument("--project", type=Path)
    usage_report_parser.add_argument("--since", help="include sessions starting on or after YYYY-MM-DD")
    usage_report_parser.add_argument("--breakdown", action="store_true", help="report the call with the greatest input growth")
    usage_report_parser.add_argument("--format", choices=("json", "text"), default="text")

    report = subparsers.add_parser("report", description="Framework-internal: no compatibility promise.", help="read-only reports over the lifecycle journal (framework-internal)")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    report_flow_parser = report_sub.add_parser("flow", description="Framework-internal: no compatibility promise.", help="lead time, stops, and origin shares from the lifecycle journal (framework-internal)")
    report_flow_parser.add_argument("--project", type=Path)
    report_flow_parser.add_argument("--since", help="include journal records on or after YYYY-MM-DD")
    report_flow_parser.add_argument("--format", choices=("json", "text"), default="text")

    budget = subparsers.add_parser(
        "budget", description="Framework-internal: no compatibility promise.",
        help="track a governed-SDD task's diagnostic/evidence/context-expansion/investigation caps (framework-internal)",
    )
    budget_sub = budget.add_subparsers(dest="budget_command", required=True)

    budget_show_parser = budget_sub.add_parser("show", description="Framework-internal: no compatibility promise.", help="print the active attempt's budget state (framework-internal)")
    budget_show_parser.add_argument("task_id")
    budget_show_parser.add_argument("--project", type=Path, default=Path.cwd())

    budget_spend_parser = budget_sub.add_parser(
        "spend", description="Framework-internal: no compatibility promise.", help="record one diagnostic/evidence/context use and check the declared cap (framework-internal)"
    )
    budget_spend_parser.add_argument("task_id")
    budget_spend_parser.add_argument("kind", choices=BUDGET_KINDS)
    budget_spend_parser.add_argument("--project", type=Path, default=Path.cwd())

    execution = subparsers.add_parser("execution", help="validate a governed task's durable execution evidence")
    execution_sub = execution.add_subparsers(dest="execution_command", required=True)
    for operation in ("start", "deliver"):
        boundary = execution_sub.add_parser(operation, help=f"verified execution {operation} boundary")
        boundary.add_argument("task_id")
        boundary.add_argument("--project", type=Path, default=Path.cwd())
        boundary.add_argument("--format", choices=("json",), default="json")
        if operation == "start":
            boundary.add_argument("--resume", action="store_true", help="only after explicit Resume and dirty-diff inspection")
    preflight = execution_sub.add_parser("preflight", help="check the task contract before implementation")
    preflight.add_argument("task_id")
    preflight.add_argument("--project", type=Path, default=Path.cwd())
    contract = execution_sub.add_parser("contract", help="print the profile-resolved execution contract for a task")
    contract.add_argument("task_id")
    contract.add_argument("--project", type=Path, default=Path.cwd())
    reconcile = execution_sub.add_parser(
        "reconcile", help="refresh a nonterminal task's generated execution contract"
    )
    reconcile.add_argument("task_id")
    reconcile.add_argument("--apply", action="store_true")
    reconcile.add_argument("--project", type=Path, default=Path.cwd())
    handoff = execution_sub.add_parser("handoff-check", help="check a structured completion handoff")
    handoff.add_argument("task_id")
    handoff.add_argument("report", type=Path, nargs="?")
    handoff.add_argument("--project", type=Path, default=Path.cwd())
    ready = execution_sub.add_parser("ready-check", help="require preflight and complete handoff before review")
    ready.add_argument("task_id")
    ready.add_argument("report", type=Path, nargs="?")
    ready.add_argument("--project", type=Path, default=Path.cwd())
    validate = execution_sub.add_parser("validate", help="run one task-declared literal validation command")
    validate.add_argument("task_id")
    validate.add_argument("validation_id")
    validate.add_argument("--project", type=Path, default=Path.cwd())
    evidence = execution_sub.add_parser("evidence", help="record the gap and one budgeted diagnostic, capture, or expansion")
    evidence.add_argument("task_id")
    evidence.add_argument("kind", choices=EVIDENCE_EVENT_KINDS)
    evidence.add_argument("--gap", required=True)
    evidence.add_argument("--criterion")
    evidence.add_argument("--artifact")
    evidence.add_argument("--project", type=Path, default=Path.cwd())
    investigate = execution_sub.add_parser(
        "investigate", help="record a bounded, isolated exploration and its distilled finding"
    )
    investigate.add_argument("task_id")
    investigate.add_argument("--question", required=True)
    investigate.add_argument("--scope", required=True, type=int)
    investigate.add_argument("--source", action="append", required=True)
    investigate.add_argument("--finding", required=True)
    investigate.add_argument("--project", type=Path, default=Path.cwd())

    generate_claude = subparsers.add_parser(
        "generate-claude-md",
        help="regenerate a workflow template's CLAUDE.md shared body from its AGENTS.md (framework-internal)",
        description="Framework-internal: regenerate CLAUDE.md shared bodies from AGENTS.md.",
    )
    generate_claude.add_argument("--mode", choices=tuple(CLAUDE_MD_SHARED_ANCHOR), required=True)
    generate_group = generate_claude.add_mutually_exclusive_group(required=True)
    generate_group.add_argument("--check", action="store_true", help="exit non-zero if CLAUDE.md is stale")
    generate_group.add_argument("--write", action="store_true", help="regenerate CLAUDE.md in place")

    generate_router = subparsers.add_parser(
        "generate-entry-routers", description="Framework-internal: no compatibility promise.",
        help="generate a consumer's AGENTS.md and CLAUDE.md from docs/workflows/ENTRY_ROUTER.md (framework-internal)",
    )
    generate_router.add_argument("--project", type=Path, default=Path.cwd())
    generate_router_group = generate_router.add_mutually_exclusive_group(required=True)
    generate_router_group.add_argument("--check", action="store_true", help="exit non-zero if either generated entry point drifts")
    generate_router_group.add_argument("--write", action="store_true", help="write both generated entry points")

    hook = subparsers.add_parser("hook", help="run a Meridian host hook entry point")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    read_guard = hook_sub.add_parser("read-guard", help="apply the advisory-safe read guard")
    read_guard.add_argument("--host", choices=("codex",), required=True)
    stop_audit = hook_sub.add_parser("stop-audit", help="record `BLOCKED <CODE>` reports that no command emitted (Stop hook)")
    stop_audit.add_argument("--host", choices=("claude", "codex"), default="claude")

    return parser


def _run_cli(journal: LifecycleJournalEntry) -> int:
    arguments = build_parser().parse_args()
    journal.begin(arguments)
    framework_root = arguments.framework_root.resolve()
    project_root = (
        arguments.project.resolve()
        if hasattr(arguments, "project") and arguments.project is not None
        else None
    )
    try:
        if arguments.command == "self-update":
            # Environment and --framework-root select upgrade inputs, never the
            # checkout that owns this running executable.
            return run_self_update(Path(__file__).resolve().parents[1],
                                   apply=arguments.apply, target_tag=arguments.target_tag)
        if arguments.command == "self-check":
            return run_self_check(framework_root)
        if arguments.command == "console":
            if not 0.2 <= arguments.interval <= 60:
                raise MeridianError("--interval must be between 0.2 and 60")
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise MeridianError("interactive console requires a terminal")
            console_path = framework_root / "scripts" / "project_console.py"
            if not console_path.is_file():
                raise MeridianError(f"console is unavailable from framework root: {framework_root}")
            sys.path.insert(0, str(console_path.parent))
            import project_console

            return project_console.main([
                "--project", str(project_root), "--interval", str(arguments.interval),
            ])
        if arguments.command == "lock":
            lock_project(project_root, framework_root, arguments.mode)
        elif arguments.command == "adopt":
            if arguments.emit and not (arguments.assisted and arguments.check):
                raise MeridianError("--emit requires --assisted --check")
            mode = arguments.mode or detect_mode(project_root)
            source_version = arguments.source_version or detect_source_version(framework_root, mode)
            if arguments.assisted:
                if arguments.apply:
                    raise MeridianError("assisted adoption has no --apply; implement and review the plan, then finalize-adoption")
                return print_assisted_adoption_plan(
                    project_root,
                    framework_root,
                    mode,
                    source_version,
                    arguments.emit,
                )
            return adopt_project(
                project_root,
                framework_root,
                mode,
                source_version,
                arguments.apply,
            )
        elif arguments.command == "finalize-adoption":
            mode = arguments.mode or detect_mode(project_root)
            finalize_adoption(project_root, framework_root, mode, arguments.owner_accepted)
        elif arguments.command == "audit":
            mode = arguments.mode or detect_mode(project_root)
            return run_audit(project_root, framework_root, mode, arguments.ci_profile)
        elif arguments.command == "profile":
            if arguments.profile_command == "doctor":
                return profile_doctor(project_root, framework_root, arguments.profile_id)
            manifest = bootstrap_capability_profile(
                project_root,
                framework_root,
                arguments.profile_id,
                apply=arguments.apply,
            )
            print(json.dumps(manifest["capabilityProfiles"][arguments.profile_id], indent=2, sort_keys=True))
        elif arguments.command == "locations":
            locations = resolve_project_locations(project_root)
            if arguments.field == "queue":
                print(locations.queue)
            elif arguments.field == "queue-archive":
                print(locations.queue.with_name("QUEUE_ARCHIVE.md"))
            elif arguments.field == "task-roots":
                print("\n".join(str(root) for root in locations.task_roots))
            elif arguments.field == "review-root":
                print(locations.review_root)
            elif arguments.field == "handoff-root":
                print(locations.handoff_root)
            elif arguments.field == "adr-log":
                print(locations.adr_log)
            elif arguments.field == "plan":
                print(locations.plan)
            else:
                print(json.dumps({"queue": str(locations.queue), "taskRoots": [str(root) for root in locations.task_roots]}))
        elif arguments.command == "project":
            declaration = read_project_declaration(project_root) or {"version": 1}
            locations = resolve_project_locations(project_root)
            resolved = {
                **declaration,
                "locations": {
                    "queue": str(locations.queue), "taskRoots": [str(root) for root in locations.task_roots],
                    "reviewRoot": str(locations.review_root), "handoffRoot": str(locations.handoff_root),
                    "adrLog": str(locations.adr_log), "plan": str(locations.plan),
                },
            }
            if arguments.field == "reviewer-author":
                project_info = declaration.get("project")
                if not isinstance(project_info, dict):
                    raise MeridianError("project declaration key 'project' is required for reviewer-author")
                value = f"{project_info['name']} Reviewer-Integrator <reviewer-integrator@{project_info['slug']}.local>"
            elif arguments.field == "validation-scoping":
                value = declaration.get("validationScoping", [])
            elif arguments.field == "ci":
                value = declaration.get("ci", "none")
            elif arguments.field:
                value = resolved.get(arguments.field)
            else:
                value = resolved
            if arguments.format == "json":
                print(json.dumps(value, sort_keys=True))
            elif isinstance(value, (dict, list)):
                print(json.dumps(value, indent=2, sort_keys=True))
            else:
                print(value)
        elif arguments.command == "setup":
            plan = plan_setup(
                arguments.worktree_root,
                arguments.config.expanduser().resolve(),
                task_identity=arguments.task_identity,
                framework_root=framework_root,
                project_root=arguments.project,
            )
            print_setup_plan(plan)
            if arguments.apply:
                changed = apply_setup(plan)
                print("result: updated; restart Codex" if changed else "result: no-op")
        elif arguments.command == "codex":
            resolved_root = resolve_worktree_root(arguments.worktree_root)
            if arguments.codex_command == "configure":
                plan = plan_codex_configuration(
                    arguments.config.expanduser().resolve(),
                    resolved_root.path,
                    arguments.requirements.expanduser().resolve() if arguments.requirements else None,
                )
                print_codex_configuration_plan(plan)
                if arguments.apply:
                    changed = apply_codex_configuration(plan)
                    if changed and plan.status in ("repair-required", "repair-and-replace-required"):
                        action = (
                            "ownership metadata repaired and root replaced"
                            if plan.status == "repair-and-replace-required"
                            else "ownership metadata repaired"
                        )
                        print(
                            f"result: {action}; this does not prove the running session loaded "
                            "the profile, so start a fresh Codex session and probe it"
                        )
                    else:
                        print("result: updated; restart Codex and select the profile" if changed else "result: no-op")
            elif arguments.codex_command == "worktree-path":
                path = task_worktree_path(project_root, resolved_root.path, arguments.task_id)
                validate_worktree_collision(project_root, path, arguments.task_id)
                print("DEPRECATED: use `meridian worktree path`", file=sys.stderr)
                print(path)
            else:
                report = codex_doctor(
                    project_root,
                    arguments.config.expanduser().resolve(),
                    resolved_root.path,
                    framework_root=framework_root,
                )
                for capability, status in report.items():
                    print(f"{capability}: {status}")
        elif arguments.command == "worktree":
            if arguments.worktree_command == "active":
                print(json.dumps(active_worktree_task(Path.cwd()) or {}, sort_keys=True))
            elif arguments.worktree_command == "states":
                print(json.dumps(registered_worktree_task_states(arguments.project), sort_keys=True))
            elif arguments.worktree_command == "path":
                canonical_project = _verified_lifecycle_project(project_root)
                path_identity = resolve_task_identity(
                    canonical_project, arguments.task_id, "existing"
                )
                path = _task_worktree_path_for_identity(
                    canonical_project,
                    _effective_worktree_root(arguments.worktree_root),
                    path_identity,
                )
                validate_worktree_collision(canonical_project, path, arguments.task_id)
                if arguments.format == "json":
                    print(json.dumps({
                        "version": 1,
                        "path": str(path),
                        "handoff_worktree": handoff_worktree_value(
                            _effective_worktree_root(arguments.worktree_root), path
                        ),
                    }, sort_keys=True))
                else:
                    print(path)
            elif arguments.worktree_command == "prepare":
                prepared = prepare_task_worktree(
                    arguments.task_id,
                    arguments.worktree_root,
                    project_root,
                    arguments.base,
                    arguments.resume,
                    arguments.new_attempt,
                    arguments.reason,
                )
                journal.observe(prepared)
                print(json.dumps(prepared, sort_keys=True))
            elif arguments.worktree_command == "repair-base":
                repaired = repair_task_worktree_base(arguments.task_id, arguments.worktree_root, project_root)
                journal.observe(repaired)
                print(json.dumps(repaired, sort_keys=True))
            elif arguments.worktree_command == "check":
                report, ready = inspect_task_worktree(
                    arguments.task_id,
                    arguments.worktree_root,
                    project_root,
                )
                journal.observe(report)
                print(json.dumps(report, sort_keys=True))
                if not ready:
                    mismatch = stop_error(
                        str(report.get("stop_reason", "WRONG_WORKTREE")),
                        "worktree check reported: " + ", ".join(str(error) for error in report["errors"]),
                        resume=report.get("resume"),
                        task_id=arguments.task_id,
                        project=project_root,
                    )
                    journal.stopped(mismatch.code)
                    print(mismatch, file=sys.stderr)
                    return 2
            elif arguments.worktree_command == "evidence":
                recorded = (record_task_evidence(
                    arguments.task_id,
                    arguments.worktree_root,
                    arguments.validation_command,
                    arguments.validation_exit_code,
                    accepted=arguments.accepted,
                    task_dependencies=arguments.task_dependency,
                    task_behavioral_surfaces=arguments.task_behavioral_surface,
                    main_advanced_dependencies=arguments.main_advanced_dependency,
                    main_advanced_behavioral_surfaces=arguments.main_advanced_behavioral_surface,
                    full_validation_required=arguments.full_validation_required,
                    supplied_project=project_root,
                ))
                journal.observe(recorded)
                print(json.dumps(recorded, sort_keys=True))
            elif arguments.worktree_command == "closure-status":
                report, ready = closure_status(
                    arguments.task_id,
                    arguments.worktree_root,
                    project_root,
                )
                journal.observe(report)
                if not ready:
                    journal.stopped(str(report["stop_reason"]) if report["stop_reason"] is not None else None)
                if arguments.format == "json":
                    print(json.dumps(report, sort_keys=True))
                elif report["stop_reason"] is not None:
                    print(format_stop(
                        str(report["stop_reason"]),
                        str(load_stop_registry()[str(report["stop_reason"])]["summary"]),
                        resume=str(report["resume"]),
                    ))
                else:
                    print(f"{report['step']}; resume: {report['resume'] or 'none'}")
                if not ready:
                    return 2
            elif arguments.worktree_command == "advance":
                advanced, blocked = advance_task_closure(
                    arguments.task_id,
                    arguments.worktree_root,
                    arguments.validation_command,
                    arguments.validation_exit_code,
                    accepted=arguments.accepted,
                    supplied_project=project_root,
                    candidate_commands=arguments.candidate_command,
                    candidate_exit_codes=arguments.candidate_exit_code,
                )
                journal.observe(advanced)
                print(json.dumps(advanced, sort_keys=True))
                if blocked:
                    journal.stopped(str(advanced["stop_code"]))
                    return 2
            elif arguments.worktree_command == "integrate":
                if arguments.integrate_command == "stage":
                    result = stage_task_integration(
                        arguments.task_id,
                        arguments.worktree_root,
                        arguments.evidence,
                        project_root,
                    )
                elif arguments.integrate_command == "finalize":
                    result = finalize_task_integration(
                        arguments.task_id,
                        arguments.evidence,
                        project_root,
                    )
                else:
                    result = abort_task_integration(arguments.task_id, project_root)
                journal.observe(result)
                print(json.dumps(result, sort_keys=True))
            else:
                cleaned = cleanup_task_worktree(
                    arguments.task_id,
                    arguments.worktree_root,
                    project_root,
                )
                journal.observe(cleaned)
                print(json.dumps(cleaned, sort_keys=True))
        elif arguments.command == "review":
            print(json.dumps(record_review_verdict(project_root, arguments.task_id, arguments.verdict,
                                                   owner=arguments.owner, body=arguments.body), sort_keys=True))
        elif arguments.command == "task":
            if arguments.task_command == "transition":
                print(json.dumps(transition_task_state(project_root, arguments.task_id, arguments.status), sort_keys=True))
            elif arguments.task_command == "close":
                print(json.dumps(close_task(project_root, arguments.task_id), sort_keys=True))
            elif arguments.task_command == "state":
                print(json.dumps(import_task_states(project_root, arguments.task_ids, apply=arguments.apply,
                                                  include_terminal=arguments.include_terminal), sort_keys=True))
            elif arguments.identity_command == "check":
                resolved = resolve_task_identity(project_root, arguments.task_id, "existing")
                print(json.dumps(task_identity_json(project_root, resolved), sort_keys=True))
            else:
                resolved = next_milestone_task_identity(
                    project_root, arguments.milestone, arguments.workstream
                )
                print(json.dumps(resolved.as_json(project_root), sort_keys=True))
        elif arguments.command == "validation":
            report, exit_code = check_validation_evidence(
                arguments.record, canonical_project_root(project_root), arguments.commit
            )
            print(json.dumps(report, sort_keys=True))
            return exit_code
        elif arguments.command == "adr":
            if arguments.adr_command == "list":
                listed, adr_warnings = adr_list(project_root, arguments.status)
                for adr_warning in adr_warnings:
                    print(f"warning: {adr_warning}", file=sys.stderr)
                if arguments.format == "json":
                    print(json.dumps(listed, sort_keys=True))
                else:
                    for entry in listed:
                        print(f"{entry['id']}\t{entry['title']}\t{entry['status'] or '-'}")
            else:
                print(adr_show(project_root, arguments.adr_id))
        elif arguments.command == "context":
            if arguments.context_command == "authority":
                print(context_authority(project_root, arguments.task_id, arguments.labels_only))
            else:
                if arguments.threshold_bytes is not None and arguments.threshold_bytes < 0:
                    raise MeridianError("--threshold-bytes must be a non-negative integer")
                report = context_size_report(project_root, arguments.role, arguments.context_task_id, arguments.threshold_bytes)
                print(json.dumps(report, sort_keys=True) if arguments.format == "json" else format_context_size_report(report))
                return 2 if report["exceeded"] else 0
        elif arguments.command == "usage":
            report = usage_report(arguments.host, arguments.project, arguments.since, arguments.breakdown)
            print(json.dumps(report, sort_keys=True) if arguments.format == "json" else format_usage_report(report))
            return 0 if report["status"] == "ok" else 2
        elif arguments.command == "report":
            report = flow_report(_verified_lifecycle_project(arguments.project), arguments.since)
            print(json.dumps(report, sort_keys=True) if arguments.format == "json" else format_flow_report(report))
            return 0
        elif arguments.command == "budget":
            if arguments.budget_command == "show":
                print(budget_show(project_root, arguments.task_id))
            else:
                count, cap = budget_spend(project_root, arguments.task_id, arguments.kind)
                print(f"{arguments.task_id}: {arguments.kind} {count}/{cap}")
        elif arguments.command == "execution":
            if arguments.execution_command == "start":
                print(json.dumps(execution_start(project_root, arguments.task_id, resume=arguments.resume), sort_keys=True))
            elif arguments.execution_command == "deliver":
                print(json.dumps(execution_deliver(project_root, arguments.task_id), sort_keys=True))
            elif arguments.execution_command == "contract":
                print(execution_contract(project_root, arguments.task_id))
            elif arguments.execution_command == "reconcile":
                print(reconcile_execution_contract(project_root, arguments.task_id, arguments.apply))
            elif arguments.execution_command == "preflight":
                print(execution_preflight(project_root, arguments.task_id))
            elif arguments.execution_command == "validate":
                return run_validation(project_root, arguments.task_id, arguments.validation_id)
            elif arguments.execution_command == "evidence":
                print(record_execution_event(
                    project_root, arguments.task_id, arguments.kind, arguments.gap,
                    arguments.criterion, arguments.artifact,
                ))
            elif arguments.execution_command == "investigate":
                print(record_investigation(
                    project_root, arguments.task_id, arguments.question, arguments.scope,
                    arguments.source, arguments.finding,
                ))
            elif arguments.execution_command == "ready-check":
                if state_path(project_root, arguments.task_id).exists():
                    result = delivery_readiness(project_root, arguments.task_id)
                    print(json.dumps(result, sort_keys=True))
                else:
                    print(readiness_check(project_root, arguments.task_id, (project_root / arguments.report if arguments.report else default_handoff_path(project_root, arguments.task_id))))
            else:
                print(check_handoff(project_root, arguments.task_id, (project_root / arguments.report if arguments.report else default_handoff_path(project_root, arguments.task_id))))
        elif arguments.command == "generate-claude-md":
            workflow = framework_root / "templates" / "workflows" / arguments.mode
            agents_path = workflow / "AGENTS.md"
            claude_path = workflow / "CLAUDE.md"
            agents_text = agents_path.read_text(encoding="utf-8")
            claude_text = claude_path.read_text(encoding="utf-8")
            generated = generate_claude_md(arguments.mode, agents_text, claude_text)
            if arguments.check:
                if generated == claude_text:
                    print(f"CLAUDE.md ({arguments.mode}) matches the generator's output.")
                else:
                    print(f"STALE {claude_path}: does not match AGENTS.md-generated output.", file=sys.stderr)
                    return 2
            else:
                claude_path.write_text(generated, encoding="utf-8")
                print(f"Regenerated {claude_path}.")
        elif arguments.command == "generate-entry-routers":
            outputs = entry_router_outputs(project_root)
            drifted = [target for target, expected in outputs.items() if not (project_root / target).is_file() or (project_root / target).read_text(encoding="utf-8") != expected]
            if arguments.check:
                if drifted:
                    print("STALE generated entry router(s): " + ", ".join(str(path) for path in drifted), file=sys.stderr)
                    return 2
                print("Generated entry routers match their canonical source.")
            else:
                for target, output in outputs.items():
                    (project_root / target).write_text(output, encoding="utf-8")
                print("Generated AGENTS.md and CLAUDE.md from ENTRY_ROUTER.md.")
        elif arguments.command == "hook":
            if arguments.hook_command == "read-guard" and arguments.host == "codex":
                from codex_read_guard import main as codex_read_guard_main

                return codex_read_guard_main()
            if arguments.hook_command == "stop-audit":
                from stop_audit import main as stop_audit_main

                return stop_audit_main(arguments.host)
        elif arguments.check:
            if arguments.owner_reconciled:
                raise MeridianError("--owner-reconciled only applies to --apply")
            base_manifest, target_override, managed_override = prepare_upgrade_targets(
                project_root, framework_root, arguments.stop_before_retirement
            )
            installed_version = manifest_baseline_version(base_manifest)
            manifest, plan = plan_from_baseline(
                project_root,
                framework_root,
                manifest_workflow_mode(base_manifest),
                installed_version,
                project_root / BASELINES_PATH / installed_version,
                list(base_manifest.get("appliedMigrations", [])),
                target_version_override=target_override,
                managed_files_override=managed_override,
                installed_framework_version=str(base_manifest.get("frameworkVersion", "")),
                capability_profiles=base_manifest.get("capabilityProfiles"),
            )
            print_plan(project_root, manifest, framework_root, plan, target_version_override=target_override)
            for advisory in retired_text_advisories(project_root, framework_root, base_manifest):
                print(f"{advisory.status:14} {advisory.identity} — {advisory.detail}")
            if plan_has_blockers(plan):
                return 2
        else:
            apply_upgrade(
                project_root,
                framework_root,
                arguments.owner_reconciled,
                arguments.stop_before_retirement,
            )
    except MeridianStop as error:
        if getattr(error, "recovery_worktree", None) is not None:
            # Preserve the exact invocation, including optional flags and values.
            rerun = []
            tokens = iter(sys.argv[1:])
            for token in tokens:
                if token == "--project":
                    next(tokens, None)
                elif not token.startswith("--project="):
                    rerun.append(token)
            rerun.extend(("--project", str(error.recovery_worktree)))
            detail = error.recovery_detail
            if str(arguments.project) != str(project_root):
                detail = detail.replace(f"--project={project_root};",
                                        f"--project={arguments.project}; resolved project={project_root};", 1)
            error = stop_error(error.code, detail, resume=shlex.join(("meridian", *rerun)))
        journal.stopped(error.code)
        print(error, file=sys.stderr)
        return 2
    except MeridianError as error:
        refused = stop_error("COMMAND_REFUSED", str(error))
        journal.stopped(refused.code)
        print(refused, file=sys.stderr)
        return 2
    except OSError as error:
        failed = stop_error("OS_ACCESS_FAILED", str(error))
        journal.stopped(failed.code)
        print(failed, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
