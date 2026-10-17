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
                    recovery_identity = resolve_task_identity(
                        recovery_project, task, "existing", allow_archived_queue_links=True,
                    )
                    archived = recovery_identity.task_path.parent.name == "done"
                    recovery = ["meridian", "task", "transition" if archived else "close", task]
                    if archived:
                        recovery.append("DONE")
                    recovery.extend(["--project", str(recovery_project)])
                    if worktree_root is not None:
                        recovery = ["env", f"MERIDIAN_WORKTREE_ROOT={worktree_root}", *recovery]
                    commands = [f"cd {shlex.quote(str(recovery_project))} && {shlex.join(recovery)}"]
                    if archived:
                        # close refuses archived records; recreate only their missing state.
                        commands.append(shlex.join([
                            "git", "-C", str(recovery_project), "add", "--",
                            f".meridian/tasks/{task}.json",
                            recovery_identity.task_path.relative_to(recovery_project).as_posix(),
                        ]))
                    commands.append(shlex.join([
                        "git", "-C", str(recovery_project), "commit", "-m", f"Close task {task}",
                    ]))
                    advance = ["meridian", "worktree", "advance", task, "--project", str(project_root),
                               "--format", "json"]
                    if worktree_root is not None:
                        advance.extend(["--worktree-root", str(worktree_root)])
                    if accepted:
                        advance.append("--accepted")
                    for command, exit_code in zip(validation_commands, validation_exit_codes):
                        advance.extend(["--validation-command", command, "--validation-exit-code", str(exit_code)])
                    for command, exit_code in zip(candidate_commands, candidate_exit_codes):
                        advance.extend(["--candidate-command", command, "--candidate-exit-code", str(exit_code)])
                    commands.append(f"cd {shlex.quote(str(project_root))} && {shlex.join(advance)}")
                    return result("C6", "resolve", commands=commands, stop_code=error.code,
                                  resume=" && ".join(commands), blocked=True)
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


# Each group is reported as its own doctor fact: (key, ((command, decision), ...)).


# Pre-marker capabilities (001, 002) shipped as bare phrases before migration
# 006 introduced markers. A project adopted between their release and 006 is
# legitimately compliant but has no marker to find; without this fallback,
# every such already-adopted project would regress to fully MISSING. Each
# entry proves only that v1 was implemented — the version that predates
# markers entirely — never a later one.


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
