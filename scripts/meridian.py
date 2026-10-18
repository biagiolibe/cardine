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

from cardine.lifecycle.closure import (  # noqa: E402
    _journal_advance_step,
    advance_task_closure,
)

from cardine.lifecycle.commands import (  # noqa: E402
    execution_start,
    execution_deliver,
)

from cardine.templates.upgrade_support import (  # noqa: E402
    recorded_managed_digests,
    profile_surface_plan,
    prepare_upgrade_targets,
    print_plan,
    plan_has_blockers,
    _unused_adoption_backup,
)

from cardine.templates.merge import (  # noqa: E402
    copy_baseline,
    prune_stale_baselines,
    lock_project,
    merge_clean,
    apply_additive_move_checks,
    plan_from_baseline,
)

from cardine.templates.adoption import (  # noqa: E402
    _capability_declaration,
    bootstrap_capability_profile,
    detect_capabilities,
    parse_adoption_review,
    compute_adoption_state,
    assisted_implementer_prompt,
    assisted_reviewer_prompt,
    assisted_orchestrator_prompt,
    print_assisted_adoption_plan,
    copy_adoption_baseline,
    finalize_adoption,
)

from cardine.integration.merge import (  # noqa: E402
    _spike_disallowed_paths,
    _integration_task_state,
    stage_task_integration,
    finalize_task_integration,
    runnable_candidate_validation_command,
    missing_candidate_validation_commands,
    abort_task_integration,
    cleanup_task_worktree,
)

from cardine.tasks.recording import (  # noqa: E402
    record_validation,
    run_validation,
    record_execution_event,
    record_investigation,
)

from cardine.tasks.transitions import (  # noqa: E402
    transition_task_state,
    close_task,
)

from cardine.templates.audit import (  # noqa: E402
    _audit_evidence_reference,
    _audit_snapshot_evidence,
    _digest_exempt,
    installation_surface_diagnostics,
    _audit_probe_evidence,
    managed_copy_drift,
    declared_managed_copy_paths,
    is_markerless_managed_copy_digest_audited,
    audit_managed_copy_digests,
    audit_declared_capabilities,
    load_retired_text_registry,
    retired_text_advisories,
    run_audit,
    _load_profile_probe,
    profile_doctor,
)

from cardine.worktree.closure_status import (  # noqa: E402
    closure_status,
)

from cardine.tasks.preflight import (  # noqa: E402
    execution_contract,
    execution_preflight,
    reconcile_execution_contract,
    readiness_check,
)
from cardine.worktree.checkout import (  # noqa: E402
    repair_task_worktree_base,
    prepare_task_worktree,
    inspect_task_worktree,
    active_worktree_task,
    registered_worktree_task_states,
)
from cardine.integration.evidence import (  # noqa: E402
    _validation_reason,
    validation_evidence_reasons,
    check_validation_evidence,
    _string_tuple,
    _bool_field,
    candidate_validation_declaration,
    proposed_candidate_validation_declaration,
    undeclared_validation_commands_error,
    _integration_evidence,
    record_task_evidence,
    _remove_owned_file,
    _lifecycle_changes_after_validation,
)
from cardine.lifecycle.execution import (  # noqa: E402
    _execution_location,
    _execution_worktree,
    _execution_state,
    _execution_owned_paths,
    execution_source_digest,
    _delivery_current_commit,
    _delivery_later_commits,
    delivery_readiness,
)
from cardine.hosts.setup import (  # noqa: E402
    plan_setup,
    print_setup_plan,
    apply_setup,
    CODEX_CLOSURE_POLICY_PROBES,
    _codex_policy_probe_state,
    codex_doctor,
)

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
from cardine.shared.flow import (  # noqa: E402
    FLOW_TARGETS_PATH,
    FLOW_TARGETS_VERSION,
    FLOW_ORIGINS,
    FLOW_ORIGIN_PATTERN,
    FLOW_JOURNAL_TIME,
    FLOW_UNCODED,
    _flow_time,
    _flow_read_journal,
    _flow_origin,
    _flow_median,
    _flow_targets,
    _flow_tasks,
    flow_report,
    format_flow_report,
    _flow_duration,
)
from cardine.tasks.audit import (  # noqa: E402
    audit_task_state_projections,
)
from cardine.tasks.contract import (  # noqa: E402
    profile_cap,
    profile_digest,
    contract_digest,
    contract_requires_execution_commands,
    PREFLIGHT_HEADINGS,
    NORMAL_PREFLIGHT_HEADINGS,
    SPIKE_PREFLIGHT_FIELDS,
    HANDOFF_FIELDS,
    EXECUTION_EVIDENCE_PATH,
    HOST_IMPACT_STATES,
    HOST_IMPACT_EVIDENCE_CATEGORIES,
    host_impact_section,
    host_impact_field,
    host_impact_required_profiles,
    validate_host_impact_declaration,
    verify_host_impact_completion_evidence,
    execution_entries,
    verify_validation_skips,
    verify_execution_evidence,
    check_handoff,
    default_handoff_path,
)
from cardine.tasks.importer import (  # noqa: E402
    import_task_states,
)
from cardine.shared.budget_commands import (  # noqa: E402
    proposed_project_identity,
    task_cap,
    resolve_budget_key,
    budget_show,
    budget_spend,
)


# `git worktree list` reads identically from any registered worktree, so a
# read-only scope may share one parse between every lifecycle reader it calls.






# Each group is reported as its own doctor fact: (key, ((command, decision), ...)).


# Pre-marker capabilities (001, 002) shipped as bare phrases before migration
# 006 introduced markers. A project adopted between their release and 006 is
# legitimately compliant but has no marker to find; without this fallback,
# every such already-adopted project would regress to fully MISSING. Each
# entry proves only that v1 was implemented — the version that predates
# markers entirely — never a later one.






































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
    worktree_check.add_argument("--resume", action="store_true", help="accept only dirty-worktree after explicit Resume")
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
            from cardine.console import entry as project_console

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
                    resume=arguments.resume,
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
