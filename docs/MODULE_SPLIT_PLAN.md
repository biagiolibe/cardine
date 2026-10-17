# Module split plan — ADR work item 3

## Contract and baseline

This plan covers only the mechanical module and test extraction in decision 8
of `docs/ADR_CARDINE_1_0.md`. Baseline: task 002, commit
`ceb84fdd88d2e0819ab42f6b1d6e5266fffff8fd`, inspected on 2026-10-17.
No implementation is moved by task 003. The inventory has 506 top-level
bindings: 357 functions, 35 classes, 111 plain assignments and 3 annotated
assignments. Imported bindings are listed separately below. Line numbers in
this document refer to that baseline, not to the future package.

Preserve CLI arguments, output, exit codes, project selection, Git mutations,
state formats, host policies and migration behavior. In particular, do not
introduce `cardine run`, remove compatibility, or rename persisted identifiers.
The extraction keeps the existing behavioral suite green, **not its source
unchanged**: imports, patch targets, discovery locations and source-scanning
fixtures must change. No assertions or platform skip conditions are weakened.

## File layout and extraction rule

The decision-8 domains with several responsibilities become Python packages
with empty `__init__.py` files. `cardine.cli` stays a single file. A qualified
name below maps directly to `src/cardine/<qualified/name>.py`; for example,
`templates.marker_history` means `src/cardine/templates/marker_history.py`.
The named `shared` modules hold existing cross-domain helpers, not a new API.
Do not import package facades internally or put dispatch code in `__init__.py`.

Each binding below has exactly one owner. Move its existing body and decorators;
replace global references with explicit imports from the recorded providers.
Keep `from __future__ import annotations`. Copy only the standard-library
imports used by that file. Bindings separated into support modules are deliberate:
merging them back into their broad domain creates dependency cycles. The small
files make that boundary explicit; this is an intermediate mechanical layout,
not a commitment to preserve all internal modules after item 4.

Use module-qualified access for mutable global state, and keep each `global`
writer in the same module as its binding. `_stop_registry_cache` stays with
`load_stop_registry`; `_SHARED_WORKTREES` stays with its readers/context manager.
The legacy location-warning set remains a shared object. Do not copy caches or
reset them through a compatibility facade. Keep dataclass/class identities
singletons across entry points.

`SCRIPTS_ROOT` retains its current meaning (the checkout's `scripts/` directory).
Resolve it from the package file's checkout location, never from the caller's
working directory or selected project. Replace every moved `__file__` root
calculation with the equivalent executable-checkout root: validation schema,
setup/doctor defaults, parser framework default and self-update executable
ownership. Preserve explicit `--framework-root` precedence over environment
selection and the distinction between executable root and selected framework.

During the transition, the remaining monolith imports extracted owners and
still owns its unextracted function globals. Retarget mocks when each consumer
moves; patch both remaining legacy and extracted lookups when a test spans
both. Never leave a test patching a facade after its consumer has moved.

Existing imports `TaskStateInvalid`, `machine`, `read_task_state`, `state_path`
and `validate_task_state` move to `cardine.tasks.state` with the unchanged
`scripts/task_state.py` implementation. `latest_review_verdict` and `record_review`
move with `scripts/console_workflow.py` to `cardine.shared.console_workflow`;
its profile/queue types are shared by review and console. Old scripts become
thin adapters where callers still require them. These two modules have no
imports from the extracted CLI. Their schema/resource roots need the same
checkout-root treatment.

## Complete symbol ownership

The lists include private constants, caches and regular expressions as well
as public functions and classes. Each entry is `name@original-line`.

### `cardine.cli`

- `CLAUDE_MD_SHARED_ANCHOR@12016`, `MeridianArgumentParser@12022`, `generate_claude_md@12032`, `ShowVersionAction@12062`, `main@12071`

- `build_parser@12084`, `_run_cli@12550`

### `cardine.hosts.claude`

- `CLAUDE_PROJECT_ALLOWLIST@3643`, `CLAUDE_PROJECT_DENYLIST@3712`, `plan_claude_project_allowlist@3727`, `apply_claude_project_allowlist@3790`, `claude_hook_duplicate_advisories@3802`

### `cardine.hosts.codex`

- `CODEX_USER_RULES@457`, `plan_codex_user_rules@493`, `apply_codex_user_rules@537`, `_toml_quote@3177`, `_codex_managed_block@3181`

- `_replace_codex_managed_block@3199`, `_without_top_level_default_permissions@3213`, `_codex_expected_profile@3225`, `_codex_profile_divergence@3233`, `_codex_header_patterns@3248`

- `_codex_markers_intact@3257`, `_without_codex_profile_text@3289`, `_plan_codex_ownership_repair@3319`, `_plan_codex_ownership_repair_and_root_replacement@3352`, `plan_codex_configuration@3404`

- `print_codex_configuration_plan@3452`, `_write_exclusive_backup@3477`, `_unused_repair_backup@3493`, `apply_codex_configuration@3502`

### `cardine.hosts.setup`

- `plan_setup@3837`, `print_setup_plan@4065`, `apply_setup@4117`, `CODEX_CLOSURE_POLICY_PROBES@4197`, `_codex_policy_probe_state@4227`

- `codex_doctor@4253`

### `cardine.hosts.skills`

- `_directory_setup_state@3533`, `CODEX_SKILL_NAMES@3547`, `_framework_skill_links@3550`, `_aggregate_skill_state@3580`, `_stale_codex_skill_warnings@3593`

- `_setup_codex_state@3600`, `codex_profile_root_mismatch@3625`

### `cardine.integration.decision`

- `IntegrationValidationOutcome@4366`, `IntegrationValidationDecision@4376`, `_paths_interact@4381`, `decide_integration_validation@4389`

### `cardine.integration.evidence`

- `_validation_reason@832`, `validation_evidence_reasons@837`, `check_validation_evidence@886`, `_string_tuple@1667`, `_bool_field@1673`

- `candidate_validation_declaration@1679`, `proposed_candidate_validation_declaration@1714`, `undeclared_validation_commands_error@1731`, `_integration_evidence@1742`, `record_task_evidence@1776`

- `_remove_owned_file@1841`, `_lifecycle_changes_after_validation@1848`

### `cardine.integration.merge`

- `_spike_disallowed_paths@2459`, `_integration_task_state@2494`, `stage_task_integration@2581`, `finalize_task_integration@2784`, `runnable_candidate_validation_command@2849`

- `missing_candidate_validation_commands@2871`, `abort_task_integration@2886`, `cleanup_task_worktree@2909`

### `cardine.integration.projections`

- `_completed_task_row@1913`, `_queue_task_rows@1924`, `_QUEUE_TABLE_DIVIDER@1952`, `_QUEUE_TASK_ROW@1953`, `_QUEUE_ARCHIVE_HEADER@1954`

- `_GOVERNED_QUEUE_ARCHIVE_HEADER@1960`, `_GOVERNED_QUEUE_TASK_ROW@1965`, `_GOVERNED_QUEUE_STATUSES@1971`, `_MARKDOWN_HEADING@1974`, `_governed_completion_error@1977`

- `_governed_completion_row@1982`, `_queue_section_ranges@2119`, `_queue_section_completion@2131`, `_STATE_TERMINAL_STATUSES@2166`, `QueueStateResolver@2171`

- `_queue_state_resolver@2174`, `_queue_unidentified_tables@2211`, `_queue_section_decisions@2233`, `_archive_completed_queue_sections@2301`, `_queue_archival_warnings@2334`

- `_relink_archived_task_row@2370`, `_apply_task_completion_rows@2399`

### `cardine.lifecycle.closure`

- `_journal_advance_step@2968`, `advance_task_closure@2985`

### `cardine.lifecycle.commands`

- `execution_start@11653`, `execution_deliver@11822`

### `cardine.lifecycle.execution`

- `_execution_location@11570`, `_execution_worktree@11606`, `_execution_state@11645`, `_execution_owned_paths@11685`, `execution_source_digest@11691`

- `_delivery_current_commit@11713`, `_delivery_later_commits@11735`, `delivery_readiness@11765`

### `cardine.release.update`

- `fetch_latest_release@4630`, `run_self_update@4667`, `claude_user_settings_path@4761`, `plugin_marketplace_ref@4766`, `plugin_ref_report@4783`

- `run_self_check@4806`

### `cardine.release.version`

- `SemVer@4536`, `_SEMVER_IDENTIFIER@4552`, `_SEMVER_PATTERN@4553`, `parse_semver@4560`, `read_raw_version@4573`

- `require_release_version@4580`, `read_version@4590`, `version_key@4599`, `semver_precedence_key@4606`, `release_kind_from_body@4621`

### `cardine.review.verdict`

- `record_review_verdict@9486`, `_review_verdict_projection@9567`, `_review_attempt_text@9580`

### `cardine.shared.authority`

- `find_adr_log@10165`, `adr_title_matcher@10169`, `adr_show@10175`, `ADR_HEADING_ID@10191`, `ADR_LIKE_HEADING@10192`

- `ADR_STATUS_LINE@10193`, `adr_entries@10196`, `adr_list@10230`, `extract_spec_heading@10244`, `authority_entries@10256`

- `SPEC_HEADING_CITATION@10272`, `resolve_authority_entry@10275`, `context_authority@10312`

### `cardine.shared.budget`

- `BUDGET_PATH@9159`, `BUDGET_STATE_NAME@9160`, `BUDGET_KINDS@9161`, `EVIDENCE_EVENT_KINDS@9162`, `BUDGET_DEFAULT_CAPS@9163`

- `BUDGET_FIELD_NAMES@9164`, `budget_state_path@9192`, `tracked_budget_state@9201`, `legacy_budget_migration_needed@9206`, `migrate_budget_state@9212`

- `load_budget_state@9235`, `write_budget_state@9248`

### `cardine.shared.budget_commands`

- `proposed_project_identity@9183`, `task_cap@11051`, `resolve_budget_key@11063`, `budget_show@11082`, `budget_spend@11103`

### `cardine.shared.constants`

- `MANIFEST_PATH@46`, `VALIDATION_EVIDENCE_SCHEMA_PATH@47`, `VALIDATION_EXIT_PASSED@48`, `VALIDATION_EXIT_PENDING@49`, `VALIDATION_EXIT_FAILED@50`

- `CAPABILITY_CATALOG_VERSION@51`, `CAPABILITY_CATALOG_PATH@52`, `BASELINES_PATH@53`, `ADOPTION_REVIEW_PATH@54`, `PROTOCOL_VERSION@57`

- `LEGACY_PROTOCOL_VERSION@58`, `WORKFLOW_MODES@59`, `INSTALLATION_FORMS@60`, `STRICT_DIGEST_PROFILES@64`, `PROJECT_EDITABLE_MANAGED_PATHS@67`

- `INSTALLATION_STATES@76`, `HOST_ACTIVATION_STATES@77`, `VERIFICATION_STATES@78`, `AUDIT_STATES@79`, `LATEST_RELEASE_URL@80`

- `LATEST_RELEASE_TIMEOUT_SECONDS@81`, `LATEST_RELEASE_RESPONSE_LIMIT@82`, `SELF_CHECK_UPDATE_AVAILABLE@83`, `SELF_CHECK_UNKNOWN@84`, `CAPABILITY_DECLARATION_REQUIRED_PROTOCOL@88`

- `ADOPTION_VERDICTS@89`, `ADOPTION_RETRY_LIMIT@90`, `CAPABILITY_MARKER@91`, `MARKED_BLOCK@92`, `ENTRY_ROUTER_PATH@96`

- `ENTRY_ROUTER_MAP_PATH@97`, `ENTRY_ROUTER_OVERLAYS@98`, `ENTRY_ROUTER_BUDGET_BYTES@102`, `ENTRY_ROUTER_ROUTES@103`, `ENTRY_ROUTER_SAFEGUARDS@111`

- `CONTEXT_SIZE_CONFIG_PATH@119`, `CONTEXT_SIZE_POLICY_PATH@120`, `CONTEXT_PHASE_READS_BLOCK@121`, `CONTEXT_PHASE_READ_LINE@122`, `CONTEXT_SIZE_ROLES@123`

- `USAGE_HOSTS@127`, `USAGE_PRIVACY_BOUNDARY@128`, `USAGE_ADAPTER_NOTES@132`, `TASK_IDENTITY_PATH@341`, `PROJECT_DECLARATION_PATH@343`

### `cardine.shared.context`

- `_context_path_references@10338`, `_context_relative_references@10356`, `_context_phase_reads@10369`, `_context_router@10386`, `_context_routed_workflow@10395`

- `_context_file_record@10416`, `_context_configuration@10432`, `_context_threshold@10452`, `context_router_files@10458`, `context_size_report@10480`

- `format_context_size_report@10564`

### `cardine.shared.errors`

- `MeridianError@138`, `InternalStopError@151`, `MeridianStop@155`

### `cardine.shared.flow`

- `FLOW_TARGETS_PATH@10775`, `FLOW_TARGETS_VERSION@10776`, `FLOW_ORIGINS@10777`, `FLOW_ORIGIN_PATTERN@10778`, `FLOW_JOURNAL_TIME@10779`

- `FLOW_UNCODED@10780`, `_flow_time@10783`, `_flow_read_journal@10792`, `_flow_origin@10824`, `_flow_median@10834`

- `_flow_targets@10838`, `_flow_tasks@10901`, `flow_report@10943`, `format_flow_report@11012`, `_flow_duration@11045`

### `cardine.shared.git`

- `git_output@703`, `canonical_git_common_dir@715`, `_run_git@823`, `_SHARED_WORKTREES@939`, `parse_worktree_records@943`

- `shared_worktree_records@959`, `_git_worktrees@974`, `canonical_project_root@985`, `primary_project_root@9172`, `TASK_BRANCH_OPEN_STATUSES@11249`

- `current_branch@11252`

### `cardine.shared.hashing`

- `sha256@4531`

### `cardine.shared.journal`

- `JOURNAL_NAME@239`, `JOURNAL_ROTATED_NAME@240`, `JOURNAL_MAX_BYTES@241`, `JOURNAL_VERSION@242`, `JOURNALED_WORKTREE_COMMANDS@243`

- `JOURNALED_INTEGRATE_COMMANDS@244`, `LifecycleJournalEntry@247`, `append_journal_line@319`

### `cardine.shared.jsonio`

- `_write_json_atomic@1086`, `_read_json_object@1104`

### `cardine.shared.models`

- `CODEX_PERMISSION_PROFILE@337`, `CODEX_MANAGED_BEGIN@338`, `CODEX_MANAGED_END@339`, `SAFE_PATH_COMPONENT@340`, `CANDIDATE_VALIDATION_PATH@342`

- `WORKTREE_STATE_DIRECTORY@345`, `INTEGRATION_LEASE_NAME@346`, `INTEGRATION_STATE_NAME@347`, `STRUCTURED_TASK_ID@348`, `NUMERIC_TASK_ALIAS@352`

- `CANDIDATE_VALIDATION_OUTCOMES@353`, `RepositoryIdentity@357`, `TaskIdentityPolicy@364`, `TaskIdentityContext@370`, `ResolvedTaskIdentity@378`

- `ResolvedWorktreeRoot@422`, `CodexConfigurationPlan@429`, `ClaudeConfigurationPlan@440`, `CodexUserRulesPlan@449`, `SetupPlan@558`

- `CatalogSurface@591`, `CatalogCapability@597`, `CatalogProfile@610`, `CapabilityCatalog@620`, `EvidenceSnapshot@636`

- `DeclaredSurface@645`, `CapabilityDeclaration@651`, `CapabilityProfileDeclaration@661`, `AuditResult@668`, `ManagedFile@4468`

- `PlanItem@4474`, `Capability@4484`, `CapabilityMove@4491`, `ReviewRecord@4507`, `AdoptionState@4514`

- `ProjectLocations@4522`

### `cardine.shared.paths`

- `SCRIPTS_ROOT@38`

### `cardine.shared.project`

- `_LEGACY_LOCATION_WARNING_PROJECTS@344`, `_safe_project_path@9659`, `parse_project_declaration@9665`, `read_project_declaration@9715`

### `cardine.shared.text`

- `read_task_field@9598`, `HEADING_LINE@10140`, `extract_heading_block@10143`

### `cardine.shared.usage`

- `_usage_counter@10593`, `_claude_usage_call@10598`, `_usage_start@10606`, `_usage_session@10615`, `_codex_usage_session@10648`

- `_claude_usage_session@10677`, `usage_report@10713`, `format_usage_report@10757`

### `cardine.shared.validation`

- `_required_object@5002`, `_required_string@5008`, `_required_positive_integer@5014`, `_required_string_list@5020`, `_repository_relative_path@5030`

### `cardine.stops.registry`

- `STOP_REGISTRY_PATH@142`, `STOP_REGISTRY_VERSION@143`, `STOP_REGISTRY_FIELDS@144`, `_stop_registry_cache@148`, `load_stop_registry@167`

### `cardine.stops.render`

- `_task_state_recovery_project@195`, `stop_resume@207`, `format_stop@222`, `stop_error@230`

### `cardine.tasks.audit`

- `audit_task_state_projections@7353`

### `cardine.tasks.contract`

- `profile_cap@9605`, `profile_digest@9621`, `contract_digest@9650`, `contract_requires_execution_commands@9655`, `PREFLIGHT_HEADINGS@11131`

- `NORMAL_PREFLIGHT_HEADINGS@11132`, `SPIKE_PREFLIGHT_FIELDS@11133`, `HANDOFF_FIELDS@11134`, `EXECUTION_EVIDENCE_PATH@11144`, `HOST_IMPACT_STATES@11145`

- `HOST_IMPACT_EVIDENCE_CATEGORIES@11146`, `host_impact_section@11149`, `host_impact_field@11160`, `host_impact_required_profiles@11165`, `validate_host_impact_declaration@11211`

- `verify_host_impact_completion_evidence@11229`, `execution_entries@11407`, `verify_validation_skips@11422`, `verify_execution_evidence@11450`, `check_handoff@11511`

- `default_handoff_path@11558`

### `cardine.tasks.evidence`

- `validation_commands@11852`, `require_named_validation_commands@11864`

### `cardine.tasks.identity`

- `_safe_component@674`, `canonical_task_id@692`, `task_identity_json@9585`, `resolve_project_locations@9727`, `_TaskAuthority@9818`

- `parse_task_identity_policy@9825`, `read_task_identity_policy@9838`, `_task_record_id@9851`, `_clean_queue_id@9866`, `_task_authorities@9874`

- `_numeric_alias_key@9931`, `_authority_matches@9938`, `_identity_names@9951`, `_check_branch_name@9976`, `_identity_derivations@9987`

- `resolve_task_identity@9993`, `task_identity_context@10097`, `next_milestone_task_identity@10105`, `find_task_file@11058`

### `cardine.tasks.importer`

- `import_task_states@9256`

### `cardine.tasks.preflight`

- `execution_contract@9632`, `execution_preflight@11260`, `reconcile_execution_contract@11371`, `readiness_check@11562`

### `cardine.tasks.recording`

- `record_validation@11881`, `run_validation@11898`, `record_execution_event@11920`, `record_investigation@11964`

### `cardine.tasks.transitions`

- `transition_task_state@9409`, `close_task@9447`

### `cardine.templates.adopt_command`

- `adopt_project@9088`

### `cardine.templates.adoption`

- `_capability_declaration@7654`, `bootstrap_capability_profile@7719`, `detect_capabilities@7765`, `parse_adoption_review@7776`, `compute_adoption_state@7791`

- `assisted_implementer_prompt@7871`, `assisted_reviewer_prompt@7927`, `assisted_orchestrator_prompt@7982`, `print_assisted_adoption_plan@8024`, `copy_adoption_baseline@9078`

- `finalize_adoption@9126`

### `cardine.templates.audit`

- `_audit_evidence_reference@6866`, `_audit_snapshot_evidence@6889`, `_digest_exempt@6900`, `installation_surface_diagnostics@6907`, `_audit_probe_evidence@6955`

- `managed_copy_drift@6975`, `declared_managed_copy_paths@7005`, `is_markerless_managed_copy_digest_audited@7022`, `audit_managed_copy_digests@7035`, `audit_declared_capabilities@7071`

- `load_retired_text_registry@7270`, `retired_text_advisories@7321`, `run_audit@7406`, `_load_profile_probe@7535`, `profile_doctor@7588`

### `cardine.templates.catalog`

- `manifest_workflow_mode@5052`, `_parse_catalog_surface@5071`, `parse_capability_catalog@5083`, `load_capability_catalog@5265`, `_parse_evidence_snapshot@5276`

- `parse_capability_profiles@5319`

### `cardine.templates.files`

- `latest_migration_to@4845`, `manifest_baseline_version@4860`, `managed_files_for_workflow@4865`, `managed_files@4911`, `marker_declaring_migrations@4917`

- `strip_marker_block@4940`, `capped_managed_files@4953`, `detect_source_version@7852`

### `cardine.templates.manifest`

- `validate_manifest@5473`, `load_manifest@5493`, `canonical_manifest@5515`, `write_manifest@5524`

### `cardine.templates.marker_audit`

- `audit_capability_markers@6482`, `HEADING@6561`, `marker_headings@6564`, `audit_duplicate_headings@6582`, `audit_capability_moves@6626`

### `cardine.templates.marker_history`

- `declared_capability_moves@5840`, `pending_migration_establishes_move_source@5853`, `capability_presence_map@6066`, `retired_capability_versions@6464`

### `cardine.templates.markers`

- `marker_blocks@5821`, `marker_block_sha256@5831`, `exact_marker_matches@5835`, `find_capability_marker_version@6043`, `LEGACY_CAPABILITY_EVIDENCE@6056`

- `capability_ids_in_template@6123`, `extract_marker_block@6142`, `extract_marked_block@6159`, `marker_pairs@6170`, `append_only_new_markers@6174`

- `CLAUDE_AGENTS_POINTER_MARKER@6264`, `is_agents_pointer@6267`, `agents_pointer_satisfies_claude@6285`, `agents_pointer_can_follow_upgrade@6305`, `reflowed_marker_normalization@6343`

- `deduplicate_identical_template_markers@6386`, `remove_retired_markers@6412`

### `cardine.templates.merge`

- `copy_baseline@8125`, `prune_stale_baselines@8139`, `lock_project@8154`, `merge_clean@8180`, `apply_additive_move_checks@8198`

- `plan_from_baseline@8290`

### `cardine.templates.migration_audit`

- `validate_capability_moves@5879`, `removals_for_managed_file@6023`

### `cardine.templates.migrations`

- `migration_ids@5537`, `first_retirement_migration@5548`, `capped_target_version@5559`, `migration_record_paths@5574`, `validate_adopt_existing_paths@5586`

- `adopt_existing_paths@5620`, `migration_capability_entries@5632`, `migration_capability_removals@5651`, `migration_restructures@5665`, `pending_restructured_markers@5680`

- `pending_wrapped_capabilities@5696`, `drop_restructured_marker_blocks@5714`, `restructured_marker_edits@5738`, `project_sections@5752`, `restructured_text@5785`

- `migration_capability_moves@5798`, `capability_requirements@5958`, `retired_capability_ids@5985`, `pending_capability_removals@6001`

### `cardine.templates.mode`

- `detect_mode@7830`

### `cardine.templates.protocol`

- `check_protocol_compatibility@5038`

### `cardine.templates.router`

- `entry_router_overlay@6707`, `render_entry_router@6718`, `entry_router_outputs@6723`, `project_uses_entry_router@6746`, `entry_router_trigger_requirements@6751`

- `audit_entry_router@6824`

### `cardine.templates.upgrade`

- `plan_upgrade@8732`, `complete_profile_surfaces@8822`, `apply_plan@8858`, `apply_upgrade@9043`

### `cardine.templates.upgrade_support`

- `recorded_managed_digests@8646`, `profile_surface_plan@8655`, `prepare_upgrade_targets@8704`, `print_plan@8753`, `plan_has_blockers@8804`

- `_unused_adoption_backup@8809`

### `cardine.worktree.checkout`

- `repair_task_worktree_base@1185`, `prepare_task_worktree@1219`, `inspect_task_worktree@1378`, `active_worktree_task@1475`, `registered_worktree_task_states@1519`

### `cardine.worktree.closure_status`

- `closure_status@1553`

### `cardine.worktree.paths`

- `_normalized_local_repository_name@684`, `repository_identity@722`, `_task_worktree_path_for_identity@764`, `handoff_worktree_value@788`, `task_worktree_path@793`

- `validate_worktree_collision@802`

### `cardine.worktree.storage`

- `_verified_lifecycle_project@994`, `user_configuration_path@1006`, `_read_user_configuration@1017`, `resolve_worktree_root@1033`, `_effective_worktree_root@1072`

- `_lifecycle_paths@1076`, `_merge_head_path@1082`, `_branch_commit@1114`, `lifecycle_started_at@1123`, `_dirty_summary@1144`

- `_proven_stale_base@1161`

## Import graph and cycle proof

The table gives the complete cross-file dependency adjacency from the symbol
inventory. The rank is a provider-first topological order: every listed
provider has a strictly smaller rank. This proves the planned graph has no
cycle. Edges include references in class bodies, annotations and defaults;
function-local shadowing may conservatively add an edge. Standard-library
imports are omitted. All modules may additionally import `tasks.state` and
`shared.console_workflow` when their moved body already uses those imported
bindings; both are rank-zero leaves. Resource access may additionally import
`shared.paths`, also a leaf. Package initializers add no edges.

| Rank | Consumer under `cardine` | Providers under `cardine` |
| --- | --- | --- |
| 1 | `integration.decision` | none |
| 2 | `shared.constants` | none |
| 3 | `shared.errors` | none |
| 4 | `shared.hashing` | none |
| 5 | `shared.paths` | none |
| 6 | `shared.text` | none |
| 7 | `release.version` | `shared.errors` |
| 8 | `shared.git` | `shared.errors` |
| 9 | `shared.jsonio` | `shared.errors` |
| 10 | `shared.models` | `shared.errors` |
| 11 | `shared.usage` | `shared.constants`, `shared.errors` |
| 12 | `shared.validation` | `shared.errors` |
| 13 | `stops.registry` | `shared.errors`, `shared.paths` |
| 14 | `templates.markers` | `shared.constants` |
| 15 | `templates.mode` | `shared.errors` |
| 16 | `templates.protocol` | `shared.constants`, `shared.errors` |
| 17 | `hosts.claude` | `shared.errors`, `shared.jsonio`, `shared.models` |
| 18 | `shared.budget` | `shared.errors`, `shared.git` |
| 19 | `shared.project` | `shared.constants`, `shared.errors`, `shared.git` |
| 20 | `templates.catalog` | `shared.constants`, `shared.errors`, `shared.models`, `shared.validation`, `templates.protocol` |
| 21 | `templates.migrations` | `release.version`, `shared.errors`, `shared.models`, `templates.markers` |
| 22 | `tasks.identity` | `shared.budget`, `shared.constants`, `shared.errors`, `shared.git`, `shared.models`, `shared.project`, `shared.text` |
| 23 | `templates.files` | `release.version`, `shared.errors`, `shared.models`, `templates.markers`, `templates.migrations` |
| 24 | `templates.router` | `shared.constants`, `shared.errors`, `shared.models`, `templates.markers`, `templates.migrations` |
| 25 | `shared.authority` | `shared.errors`, `shared.text`, `tasks.identity` |
| 26 | `stops.render` | `shared.errors`, `shared.git`, `stops.registry`, `tasks.identity` |
| 27 | `templates.manifest` | `shared.constants`, `shared.errors`, `shared.models`, `shared.validation`, `templates.catalog`, `templates.files` |
| 28 | `templates.marker_history` | `shared.models`, `templates.files`, `templates.markers`, `templates.migrations` |
| 29 | `worktree.storage` | `shared.errors`, `shared.git`, `shared.jsonio`, `shared.models`, `tasks.identity` |
| 30 | `hosts.codex` | `shared.errors`, `shared.models`, `stops.render` |
| 31 | `integration.projections` | `shared.errors`, `shared.models`, `shared.text`, `stops.render`, `tasks.identity`, `templates.mode` |
| 32 | `release.update` | `release.version`, `shared.constants`, `shared.errors`, `shared.git`, `stops.render` |
| 33 | `review.verdict` | `shared.errors`, `shared.git`, `shared.jsonio`, `shared.text`, `stops.render`, `tasks.identity`, `templates.mode` |
| 34 | `shared.context` | `shared.authority`, `shared.constants`, `shared.errors`, `tasks.identity`, `templates.mode` |
| 35 | `shared.journal` | `shared.errors`, `shared.git`, `stops.registry`, `tasks.identity`, `worktree.storage` |
| 36 | `tasks.evidence` | `stops.render` |
| 37 | `templates.marker_audit` | `shared.constants`, `shared.errors`, `templates.files`, `templates.manifest`, `templates.marker_history`, `templates.markers` |
| 38 | `templates.migration_audit` | `shared.constants`, `templates.files`, `templates.marker_history`, `templates.markers`, `templates.migrations` |
| 39 | `worktree.paths` | `shared.errors`, `shared.git`, `shared.models`, `tasks.identity`, `worktree.storage` |
| 40 | `hosts.skills` | `hosts.codex`, `shared.git`, `shared.models` |
| 41 | `shared.flow` | `shared.errors`, `shared.git`, `shared.journal`, `stops.registry`, `tasks.identity`, `worktree.storage` |
| 42 | `tasks.audit` | `integration.projections`, `shared.errors`, `shared.models`, `shared.text`, `stops.render`, `tasks.identity` |
| 43 | `tasks.contract` | `shared.budget`, `shared.errors`, `stops.render`, `tasks.evidence`, `tasks.identity` |
| 44 | `tasks.importer` | `integration.projections`, `shared.errors`, `shared.git`, `shared.text`, `stops.render`, `tasks.identity`, `templates.mode` |
| 45 | `shared.budget_commands` | `shared.budget`, `shared.errors`, `shared.text`, `stops.render`, `tasks.contract`, `tasks.identity`, `worktree.paths` |
| 46 | `tasks.preflight` | `shared.budget`, `shared.budget_commands`, `shared.git`, `shared.text`, `stops.render`, `tasks.contract`, `tasks.evidence`, `tasks.identity` |
| 47 | `worktree.checkout` | `shared.budget`, `shared.budget_commands`, `shared.errors`, `shared.git`, `shared.journal`, `shared.jsonio`, `shared.models`, `shared.text`, `stops.render`, `tasks.identity`, `worktree.paths`, `worktree.storage` |
| 48 | `integration.evidence` | `shared.constants`, `shared.errors`, `shared.git`, `shared.jsonio`, `shared.models`, `stops.render`, `tasks.contract`, `tasks.evidence`, `tasks.identity`, `worktree.checkout`, `worktree.storage` |
| 49 | `lifecycle.execution` | `shared.errors`, `shared.git`, `shared.text`, `stops.render`, `tasks.contract`, `tasks.evidence`, `tasks.identity`, `tasks.preflight`, `templates.mode`, `worktree.checkout` |
| 50 | `hosts.setup` | `hosts.claude`, `hosts.codex`, `hosts.skills`, `integration.evidence`, `shared.budget_commands`, `shared.constants`, `shared.errors`, `shared.git`, `shared.jsonio`, `shared.models`, `shared.project`, `tasks.identity`, `worktree.storage` |
| 51 | `integration.merge` | `integration.decision`, `integration.evidence`, `integration.projections`, `shared.authority`, `shared.errors`, `shared.git`, `shared.jsonio`, `shared.models`, `shared.text`, `stops.render`, `tasks.contract`, `tasks.identity`, `templates.mode`, `worktree.checkout`, `worktree.paths`, `worktree.storage` |
| 52 | `tasks.recording` | `lifecycle.execution`, `shared.budget_commands`, `shared.errors`, `shared.git`, `stops.render`, `tasks.contract`, `tasks.evidence`, `tasks.identity`, `tasks.preflight` |
| 53 | `tasks.transitions` | `lifecycle.execution`, `shared.errors`, `shared.git`, `shared.jsonio`, `shared.text`, `stops.render`, `tasks.identity`, `templates.mode` |
| 54 | `templates.audit` | `integration.evidence`, `release.version`, `shared.budget`, `shared.constants`, `shared.context`, `shared.errors`, `shared.hashing`, `shared.models`, `shared.project`, `shared.validation`, `tasks.audit`, `templates.catalog`, `templates.files`, `templates.manifest`, `templates.marker_audit`, `templates.mode`, `templates.protocol`, `templates.router` |
| 55 | `worktree.closure_status` | `integration.evidence`, `shared.budget`, `shared.errors`, `shared.git`, `shared.jsonio`, `shared.models`, `stops.render`, `tasks.identity`, `worktree.checkout`, `worktree.paths`, `worktree.storage` |
| 56 | `lifecycle.closure` | `integration.evidence`, `integration.merge`, `shared.errors`, `shared.journal`, `shared.jsonio`, `stops.registry`, `stops.render`, `tasks.evidence`, `tasks.identity`, `templates.mode`, `worktree.checkout`, `worktree.closure_status`, `worktree.storage` |
| 57 | `lifecycle.commands` | `lifecycle.execution`, `shared.errors`, `shared.git`, `shared.text`, `stops.render`, `tasks.identity`, `tasks.preflight`, `tasks.transitions`, `templates.mode` |
| 58 | `templates.upgrade_support` | `release.version`, `shared.budget`, `shared.constants`, `shared.hashing`, `shared.models`, `stops.render`, `templates.audit`, `templates.catalog`, `templates.files`, `templates.manifest`, `templates.migrations` |
| 59 | `templates.merge` | `release.version`, `shared.constants`, `shared.errors`, `shared.hashing`, `shared.models`, `templates.audit`, `templates.files`, `templates.manifest`, `templates.marker_history`, `templates.markers`, `templates.migration_audit`, `templates.migrations`, `templates.router`, `templates.upgrade_support` |
| 60 | `templates.adoption` | `release.version`, `shared.constants`, `shared.errors`, `shared.hashing`, `shared.models`, `stops.render`, `templates.audit`, `templates.catalog`, `templates.files`, `templates.manifest`, `templates.marker_history`, `templates.merge`, `templates.migrations` |
| 61 | `templates.upgrade` | `hosts.codex`, `release.version`, `shared.budget`, `shared.constants`, `shared.errors`, `shared.hashing`, `shared.models`, `templates.adoption`, `templates.catalog`, `templates.files`, `templates.manifest`, `templates.markers`, `templates.merge`, `templates.migration_audit`, `templates.migrations`, `templates.router`, `templates.upgrade_support` |
| 62 | `templates.adopt_command` | `shared.constants`, `shared.errors`, `templates.adoption`, `templates.merge`, `templates.upgrade`, `templates.upgrade_support` |
| 63 | `cli` | `hosts.codex`, `hosts.setup`, `integration.evidence`, `integration.merge`, `lifecycle.closure`, `lifecycle.commands`, `lifecycle.execution`, `release.update`, `release.version`, `review.verdict`, `shared.authority`, `shared.budget`, `shared.budget_commands`, `shared.constants`, `shared.context`, `shared.errors`, `shared.flow`, `shared.git`, `shared.journal`, `shared.project`, `shared.usage`, `stops.registry`, `stops.render`, `tasks.contract`, `tasks.identity`, `tasks.importer`, `tasks.preflight`, `tasks.recording`, `tasks.transitions`, `templates.adopt_command`, `templates.adoption`, `templates.audit`, `templates.catalog`, `templates.files`, `templates.markers`, `templates.merge`, `templates.mode`, `templates.router`, `templates.upgrade`, `templates.upgrade_support`, `worktree.checkout`, `worktree.closure_status`, `worktree.paths`, `worktree.storage` |

This graph is obtained by parsing top-level definitions/assignments with
Python `ast`, collecting references to other top-level names, and projecting
those references through the ownership lists. Reproduce the audit at each
extraction: compare binding sets with the baseline (506, no missing/duplicate
owners), add imports for referenced globals, then topologically sort the
actual package import graph. Reject a cycle; do not hide it with a local import
or a runtime import back into `meridian`.

Non-symbol edges require explicit handling: `cli` dispatches to console and
host hook adapters. Move `project_console` imports of `meridian` to the owning
modules below; console must never import `cli`. Read-guard and stop-audit
adapters are CLI leaves unless they already depend on lower shared services;
inspect their imports before connecting dispatch. Keep the console root check
and unavailable-console error behavior. The legacy adapter must never be an
internal dependency of a package module. `release` tooling imports version and
protocol leaves, never the CLI facade.

## Patch targets and suite compatibility

Choose **test edits**, not assignment-forwarding compatibility re-exports.
A re-export preserves object identity but assigning `meridian.X` does not
replace the global `X` used by a function in another module. For each test,
patch the namespace where the exercised function looks up the dependency;
when multiple consumers are exercised, patch each consumer or use a shared
module-qualified dependency deliberately. Never patch only the defining module
when a consumer uses `from provider import X`. Retain fault-injection and
call-count assertions, and preserve expected calls and intentional non-calls. Tests importing old
names switch to owner modules in the same extraction commit.

Inventory from AST call nodes, including multiline calls, over all `tests/*.py`:
26 direct `patch.object(meridian, ...)` calls and 9 additional calls targeting imported
objects through `meridian`. No string-form `mock.patch(...)`/`patch(...)` targets
a Meridian name at this baseline (string targets are `sys.stdin`, `sys.stdout`
and `sys.stderr`). Environment patches and unrelated objects are unaffected.
The current AST inventory differs from the task’s earlier “at least 33” estimate: 35 calls target Meridian or its imported objects, 26 target the
module directly. The table lists all 35 Meridian-related calls; line numbers distinguish repeats.

| Original call site | Target | Replacement rule / consuming namespace |
| --- | --- | --- |
| `tests/test_codex_user_rules.py:99` | `meridian.shutil.which` | Use the exercised consumer’s `shutil` object; shared stdlib object mutation keeps current effect. |
| `tests/test_execution_boundaries.py:229` | `meridian._run_git` | Patch exercised lookup(s) in `lifecycle.commands`. |
| `tests/test_machine_task_state.py:160` | `meridian.os.replace` | Use the exercised consumer’s `os` object; shared stdlib object mutation keeps current effect. |
| `tests/test_machine_task_state.py:165` | `meridian.os.replace` | Use the exercised consumer’s `os` object; shared stdlib object mutation keeps current effect. |
| `tests/test_machine_task_state.py:238` | `meridian.extract_spec_heading` | Patch exercised lookup(s) in `shared.authority`. |
| `tests/test_meridian_cli.py:5793` | `meridian.Path.cwd` | Use the exercised consumer’s `Path` object; shared stdlib object mutation keeps current effect. |
| `tests/test_meridian_cli.py:225` | `meridian.urlopen` | Patch exercised lookup(s) in `release.update`. |
| `tests/test_meridian_cli.py:237` | `meridian.urlopen` | Patch exercised lookup(s) in `release.update`. |
| `tests/test_meridian_cli.py:3611` | `meridian.load_retired_text_registry` | Patch exercised lookup(s) in `templates.audit`. |
| `tests/test_meridian_cli.py:5744` | `meridian.os.replace` | Use the exercised consumer’s `os` object; shared stdlib object mutation keeps current effect. |
| `tests/test_meridian_cli.py:9590` | `meridian.audit_declared_capabilities` | Patch exercised lookup(s) in `templates.audit`. |
| `tests/test_meridian_cli.py:9591` | `meridian.audit_capability_markers` | Patch exercised lookup(s) in `templates.audit`. |
| `tests/test_meridian_cli.py:9592` | `meridian.audit_duplicate_headings` | Patch exercised lookup(s) in `templates.audit`. |
| `tests/test_meridian_cli.py:9593` | `meridian.audit_capability_moves` | Patch exercised lookup(s) in `templates.audit`. |
| `tests/test_meridian_cli.py:9594` | `meridian.audit_entry_router` | Patch exercised lookup(s) in `templates.audit`, `templates.upgrade`. |
| `tests/test_meridian_cli.py:7762` | `meridian.retired_text_advisories` | Patch exercised lookup(s) in `cli`, `templates.audit`. |
| `tests/test_project_console.py:2412` | `meridian.resolve_task_identity` | Patch exercised lookup(s) in `worktree.closure_status`, `worktree.storage`. |
| `tests/test_review_verdict.py:166` | `meridian.os.replace` | Use the exercised consumer’s `os` object; shared stdlib object mutation keeps current effect. |
| `tests/test_review_verdict.py:170` | `meridian.os.replace` | Use the exercised consumer’s `os` object; shared stdlib object mutation keeps current effect. |
| `tests/test_review_verdict.py:34` | `meridian.delivery_readiness` | Patch exercised lookup(s) in `tasks.transitions`. |
| `tests/test_review_verdict.py:83` | `meridian.delivery_readiness` | Patch exercised lookup(s) in `tasks.transitions`. |
| `tests/test_self_update.py:148` | `meridian.read_raw_version` | Patch exercised lookup(s) in `release.update`. |
| `tests/test_self_update.py:172` | `meridian.run_self_update` | Patch exercised lookup(s) in `cli`. |
| `tests/test_task_close.py:43` | `meridian.datetime` | Patch exercised lookup(s) in `tasks.transitions`. |
| `tests/test_task_integration_state.py:283` | `meridian.stage_task_integration` | Patch exercised lookup(s) in `lifecycle.closure`. |
| `tests/test_task_integration_state.py:294` | `meridian.stage_task_integration` | Patch exercised lookup(s) in `lifecycle.closure`. |
| `tests/test_task_integration_state.py:266` | `meridian.stage_task_integration` | Patch exercised lookup(s) in `lifecycle.closure`. |
| `tests/test_task_state_lookups.py:59` | `meridian._git_worktrees` | Patch exercised lookup(s) in `worktree.checkout`. |
| `tests/test_task_state_lookups.py:60` | `meridian.canonical_project_root` | Patch exercised lookup(s) in `worktree.checkout`. |
| `tests/test_task_state_lookups.py:61` | `meridian._task_authorities` | Patch exercised lookup(s) in `tasks.identity`. |
| `tests/test_task_worktree_isolation.py:632` | `meridian._write_json_atomic` | Patch exercised lookup(s) in `hosts.claude`, `hosts.setup`, `integration.evidence`, `integration.merge`, `lifecycle.closure`, `review.verdict`, `tasks.transitions`, `worktree.checkout`. |
| `tests/test_task_worktree_isolation.py:633` | `meridian.tempfile.mkstemp` | Use the exercised consumer’s `tempfile` object; shared stdlib object mutation keeps current effect. |
| `tests/test_task_worktree_isolation.py:661` | `meridian._write_json_atomic` | Patch exercised lookup(s) in `hosts.claude`, `hosts.setup`, `integration.evidence`, `integration.merge`, `lifecycle.closure`, `review.verdict`, `tasks.transitions`, `worktree.checkout`. |
| `tests/test_task_worktree_isolation.py:1268` | `meridian._run_git` | Patch exercised lookup(s) in `integration.evidence`. |
| `tests/test_validation_evidence.py:79` | `meridian.subprocess.run` | Use the exercised consumer’s `subprocess` object; shared stdlib object mutation keeps current effect. |

`sys.argv` patches continue to target `sys`; the console launch mock moves
from `project_console.main` to `cardine.console.entry.main` once dispatch moves.
Keep direct subprocess coverage of both legacy adapters and the package entry
point so test-import changes cannot conceal a broken launcher.

## Path references, text readers and managed evidence

Inventory method: tracked text containing `meridian.py`, including hidden
files and joined path components such as `"scripts" / "meridian.py"`.
There are 33 matching tracked files at the baseline, rather than the older
21-file estimate. Bare historical mentions are included to make the inventory
complete; changes below belong to extraction tasks, not task 003.

| File | Required treatment during extraction |
| --- | --- |
| `.codex/rules/local.rules` | Keep existing permitted legacy commands while the adapter remains; no blanket Python/package permission. Add a package spelling only if required, with equivalent scope. |
| `.github/workflows/validate.yml` | Retain explicit self-hosting doctor/audit gates; exercise package dispatch too when launchers switch. |
| `CHANGELOG.md` | Historical record; retain unchanged. |
| `CONTRIBUTING.md` | Expand changed-source validation instructions to src/cardine and document preserved legacy entry points. |
| `PROJECT_PLAN.md` | Mention of split objective; integration owns task status, no source-path rewrite needed. |
| `bin/meridian` | Replace runpy implementation dispatch with thin package dispatch, inserting checkout src for uninstalled source usage; preserve Python guard and CLI behavior. |
| `docs/ADR_CARDINE_1_0.md` | Historical architecture/source-size baseline; retain unchanged. |
| `docs/ADR_STOPS_AND_DENIALS.md` | Historical baseline; retain unchanged. |
| `docs/MERIDIAN_SELF_HOSTING_PROFILE.md` | Keep documented legacy probes valid; document equivalent package probe after entry-point switch. |
| `migrations/019-marker-aware-capability-insertion.json` | Historical migration metadata; retain unchanged, no rewrite or deletion. |
| `migrations/039-authority-excerpt-command.json` | Historical migration narrative; retain unchanged. |
| `scripts/check_repository.py` | Retain required adapter file; replace monolith-only AST/string scans and registered-stop mention scan with deterministic src/cardine/**/*.py scan plus adapters. Import protocol/catalog owners rather than dynamic CLI loading. Keep precise file:line diagnostics. |
| `scripts/meridian.py` | Thin compatibility executable/import adapter only; import owners explicitly if legacy imported names remain needed. No implementation duplication or monkeypatch forwarding. |
| `scripts/release.py` | Replace regex reading PROTOCOL_VERSION from the monolith with the protocol owner; keep fixture-root behavior, never accidentally import the running checkout’s protocol for a fixture release. |
| `src/cardine/cli.py` | Replace runpy bridge with parser/dispatch implementation; preserve executable root and argument restoration semantics at legacy boundaries. |
| `tasks/003-module-split-plan.md` | Task record baseline; archive through the task lifecycle, retain historical paths. |
| `tasks/QUEUE.md` | Queue label only; integration owns status, no source-path rewrite needed. |
| `tasks/done/002-package-skeleton.md` | Immutable historical implementation record; retain unchanged. |
| `tasks/handoffs/002.md` | Historical validation evidence; retain unchanged. |
| `tests/test_authority_excerpt.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_check_repository.py` | Update fake source trees and exact stop diagnostics to cover package files and adapter; add a stop in an extracted module to prevent lost scan coverage. |
| `tests/test_codex_read_guard.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_codex_worktree_hooks.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_context_size.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_execution_boundaries.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_machine_task_state.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_marker_structure_audit.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_meridian_cli.py` | Split by domain; retain legacy allowlist spelling while adapter remains; move imports and mocks to consumer modules. |
| `tests/test_release.py` | Move synthetic protocol-version fixtures with the source reader; keep both protocol-change and review-gate assertions. |
| `tests/test_review_verdict.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_stop_audit.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_task_state_import.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |
| `tests/test_task_worktree_isolation.py` | Keep legacy subprocess entry-point coverage; move direct imports/text-reader targets to owners where implementation moved. Preserve all assertions. |

Additional indirect boundaries: `.codex/hooks.json` and the shell hooks use
`bin/meridian`, so retain those commands and permissions. The self-hosting probe
files in `.meridian/probes/meridian-self-hosting/` and their snapshot digests in
`.meridian/manifest.json` must be checked against actual affected surfaces;
source moves alone do not authorize fabricating activation evidence. Inspect
`capabilities/catalog-v1.json`, `capabilities/stop-codes-v1.json` (including
fully qualified test IDs), `STOP_LIST_TEST_FILES` in the checker, host hook
adapters and test discovery lists when test files move. Update test IDs in the
same commit as their methods, preserving the registered stop they prove.

Managed digests are not source hashes. Run the repository check and the
self-hosting doctor/audit after source extraction; refresh only genuinely
changed managed-copy surfaces using the documented explicit digest writer,
and recapture probe evidence only where its recorded inputs changed. Keep
historical release baselines and migration records unchanged. `git ls-files`
plus a search for both `scripts/meridian.py` and `meridian.py` reproduces the
inventory; repeat after every entry-point change to catch newly introduced
readers. This document itself becomes an additional reference after task 003.

## Source and test size budget

Hard final limit: 1,500 physical lines per source or test file, including
imports, comments and fixtures. Target at most 1,200 so import plumbing has
headroom. The symbol groups above contain at most 1,019 original body lines
per file; verify actual size after copying, not only AST body sizes.

| Current oversized file | Lines | Planned split |
| --- | --- | --- |
| `scripts/meridian.py` | 13,050 | Ownership lists above; adapter below 100 lines. |
| `scripts/project_console.py` | 2,083 | `console.models` (FrameworkIdentity, AgentDefaults, Task, LaunchRequest, Snapshot); `console.launch` (agent defaults, title, AppleScript and launch); `console.snapshot` (RecordResolver, caches, Git/queue loading through _build_snapshot); `console.state` (ConsoleState, one_shot); `console.render` (drawing/layout/detail helpers); `console.entry` (run_terminal, main). Models are leaves; launch and snapshot consume models; state consumes snapshot; render consumes models; entry consumes all. Move _launch_selected into entry if its state dependency would create a launch/state cycle. |
| `tests/test_meridian_cli.py` | 9,619 | Mirror extracted domains; details below. |
| `tests/test_project_console.py` | 2,506 | `test_console_launch` (AgentLaunchTest and platform helpers); `test_console_render` (FakeScreen, ConsoleListLayoutTest); `test_console_snapshot` (ProjectConsoleTest, LinklessQueueTest, RefreshCostTest, SnapshotCostTest); `test_console_states` (LeanEffectiveStateTest, GovernedEffectiveStateTest, WorkflowModeLockTest, MachineStateConsoleTest); `test_console_closure` (ClosingTaskMixin and closing subclasses); `test_console_refresh` (BackgroundRefreshTest). Move RepoCase and reusable fixtures to a non-discovered support module. Keep inherited test counts unchanged. |
| `tests/test_task_worktree_isolation.py` | 2,162 | `test_worktree_paths` (TaskWorktreeIsolationTest); split BoundedWorktreeLifecycleTest by methods into checkout/inspection, evidence/integration, closure/cleanup files, each sharing a fixture-only base; `test_integration_projections` (GovernedCompletionRowsTest). |

For the CLI tests, preserve small existing test classes intact in domain files:
release self-check classes and FakeLatestReleaseResponse; templates marker,
retirement, router, heading, manifest, surface-upgrade and version-detection
classes; hosts Codex/Claude setup/repair classes; tasks identity/project and
budget/context classes; worktree lifecycle, journal and flow classes; launcher
and task-state audit classes. Split `MeridianCliTest` (lines 247–3505) by test
method responsibility: upgrade/merge, migration/retirement, adoption/audit,
manifest/protocol, CLI/entry. Extract setup/teardown and helper methods into a
fixture-only mixin; no inherited `test_*` methods in shared fixtures. Split
`BudgetCliTest` again into budget, authority/context and execution-contract
files if needed. Never keep a >1,500-line class merely to preserve its name.
Keep method names and registry test references synchronized.

Before and after every test move, collect discovered test IDs/counts and map
old IDs to new IDs; counts including intentionally inherited cases must agree.
No aggregation file may re-import TestCase classes into unittest discovery
and accidentally execute them twice. Preserve shared `ROOT` computation,
temporary Git repositories, subprocess environments, platform skips, mock
reachability and fault-injection semantics. Run a final tracked Python-file
line-count scan; split any newly oversized fixture file by the same rule.

## Ordered extraction tasks (proposed, not queued)

Each row is one bounded 2–3 hour task, including its focused verification and
handoff. These are local plan labels, not assigned repository task IDs. Create
actual task contracts through normal coordination before implementation.
`E01` has zero prerequisites and starts with leaves: errors, constants, types,
pure helpers and state/profile helpers, rather than moving CLI orchestration.
Every subsequent extraction consumes only already extracted providers listed
in the graph. Dependencies are deliberately serial to keep one writer and
reviewable imports; there is no parallel-agent requirement.

Move source readers in the same extraction that moves their inputs: E01
updates release protocol reading and its synthetic fixture, and starts package
coverage in repository source scans. Update registered test IDs alongside each
test move. V01 verifies these boundaries; it must not postpone fixes until the
end while intermediate commits are broken.

All extraction rows run the focused tests listed, `python3 scripts/check_repository.py`,
`git diff --check`, and the full existing suite once after their last source
change with `python3 scripts/run_tests.py --parallel`. Its coverage `total` and
`digest` prove that every test ran, and CI runs the same command on Linux and
macOS. The sequential `python3 -m unittest discover -s tests -v` added about 11
minutes to each row without covering anything more, so it runs once, in V01,
and in the release gate. Do not edit the suite’s assertions to obtain a pass. Split test files
alongside their corresponding source moves; all intermediate commits remain
runnable through the compatibility executable. Re-exporting a name during
transition is permitted only for callers, never as the chosen mock strategy.

| Task / estimate | Scope (providers before consumers) | Proof beyond common checks | Dependencies |
| --- | --- | --- | --- |
| E01 / 2–3 h | `integration.decision`, `shared.constants`, `shared.errors`, `shared.hashing`, `shared.paths` plus unchanged `tasks.state` and `shared.console_workflow` leaves | stop registry/resume, journal, authority/context, budget and usage tests for moved helpers; worktree isolation, validation-evidence, integration-state and cleanup tests | none |
| E02 / 2–3 h | `shared.text`, `release.version`, `shared.git`, `shared.jsonio`, `shared.models` | stop registry/resume, journal, authority/context, budget and usage tests for moved helpers; self-check/self-update and protocol release tests | E01 |
| E03 / 2–3 h | `shared.usage`, `shared.validation`, `stops.registry`, `templates.markers`, `templates.mode` | stop registry/resume, journal, authority/context, budget and usage tests for moved helpers; manifest, marker, upgrade/adoption, router and synthetic migration tests | E02 |
| E04 / 2–3 h | `templates.protocol`, `hosts.claude`, `shared.budget`, `shared.project`, `templates.catalog` | stop registry/resume, journal, authority/context, budget and usage tests for moved helpers; manifest, marker, upgrade/adoption, router and synthetic migration tests; Codex rules/configuration, setup/doctor and hook tests | E03 |
| E05 / 2–3 h | `templates.migrations`, `tasks.identity`, `templates.files`, `templates.router`, `shared.authority` | stop registry/resume, journal, authority/context, budget and usage tests for moved helpers; machine task-state, identity, execution-boundary, task-close and review-verdict tests; manifest, marker, upgrade/adoption, router and synthetic migration tests | E04 |
| E06 / 2–3 h | `stops.render`, `templates.manifest`, `templates.marker_history`, `worktree.storage`, `hosts.codex` | stop registry/resume, journal, authority/context, budget and usage tests for moved helpers; manifest, marker, upgrade/adoption, router and synthetic migration tests; Codex rules/configuration, setup/doctor and hook tests; worktree isolation, validation-evidence, integration-state and cleanup tests | E05 |
| E07 / 2–3 h | `integration.projections`, `release.update`, `review.verdict`, `shared.context`, `shared.journal` | stop registry/resume, journal, authority/context, budget and usage tests for moved helpers; machine task-state, identity, execution-boundary, task-close and review-verdict tests; worktree isolation, validation-evidence, integration-state and cleanup tests; self-check/self-update and protocol release tests | E06 |
| E08 / 2–3 h | `tasks.evidence`, `templates.marker_audit`, `templates.migration_audit`, `worktree.paths`, `hosts.skills` | machine task-state, identity, execution-boundary, task-close and review-verdict tests; manifest, marker, upgrade/adoption, router and synthetic migration tests; Codex rules/configuration, setup/doctor and hook tests; worktree isolation, validation-evidence, integration-state and cleanup tests | E07 |
| E09 / 2–3 h | `shared.flow`, `tasks.audit`, `tasks.contract`, `tasks.importer`, `shared.budget_commands` | stop registry/resume, journal, authority/context, budget and usage tests for moved helpers; machine task-state, identity, execution-boundary, task-close and review-verdict tests | E08 |
| E10 / 2–3 h | `tasks.preflight`, `worktree.checkout`, `integration.evidence`, `lifecycle.execution`, `hosts.setup` | machine task-state, identity, execution-boundary, task-close and review-verdict tests; Codex rules/configuration, setup/doctor and hook tests; worktree isolation, validation-evidence, integration-state and cleanup tests | E09 |
| E11 / 2–3 h | `integration.merge`, `tasks.recording`, `tasks.transitions`, `templates.audit`, `worktree.closure_status` | machine task-state, identity, execution-boundary, task-close and review-verdict tests; manifest, marker, upgrade/adoption, router and synthetic migration tests; worktree isolation, validation-evidence, integration-state and cleanup tests | E10 |
| E12 / 2–3 h | `lifecycle.closure`, `lifecycle.commands`, `templates.upgrade_support`, `templates.merge`, `templates.adoption` | machine task-state, identity, execution-boundary, task-close and review-verdict tests; manifest, marker, upgrade/adoption, router and synthetic migration tests | E11 |
| E13 / 2–3 h | `templates.upgrade`, `templates.adopt_command`, `cli` | manifest, marker, upgrade/adoption, router and synthetic migration tests; legacy/package CLI parity, source checker and self-hosting doctor/audit; switch both entry points only after console adaptation | E12, C02 |
| C01 / 2–3 h | Extract console models, launch and snapshot; move direct meridian imports to graph owners and keep a script adapter. Run after E12, before the CLI switch in E13. | Existing snapshot/state/launch tests, including fixture identity and refresh cost; compare discovered cases. | E12 |
| C02 / 2–3 h | Extract console state/render/entry and split its test files; preserve current console behavior rather than rebuild it on a future run engine. | Existing render, closure, refresh and AppleScript tests; retain platform skips and inherited counts. | C01; prerequisite of E13 |
| V01 / 2–3 h | Complete path-reader/checker/release fixtures, entry-point parity, test discovery and file-size audit; remove remaining implementation from adapters. | Full suite, also sequentially (`python3 -m unittest discover -s tests -v`); repository check; self-hosting doctor/audit; package and legacy --version parity; source/import DAG and line-count audits; unchanged patch call/non-call expectations. | E13, C02 |

Execution order is E01 through E12, C01, C02, E13, V01.
If a row cannot fit its 3-hour bound, divide it at a module or test-class
boundary before starting; retain the provider order and common checks.
The row includes test moves for its modules, not an extra unbounded test rewrite.

The first extraction also records executable inventory checks in its contract:
AST symbol coverage, package import DAG, test-ID mapping and tracked-file line
counts. Those are mechanical regression checks with meaning beyond matching
the implementation; task 003 introduces no test tooling or source change.

## Completion gate and deferred choices

Work item 3 finishes only when all 506 bindings and imported helper modules
have owners, both launchers work, every affected mock retains its expected calls or non-calls, all text
readers scan the new implementation, source/test files satisfy the line limit,
and the existing suite plus repository/self-hosting checks pass. Preserve a
reviewable old-to-new test-ID map, source inventory and import graph in the
extraction handoffs. Use the existing candidate-validation policy at integration.

Item 4 is deferred: retain migrations, baselines, budget counters and maintainer
commands. Keep historical helpers isolated in `templates.migrations`,
`templates.marker_history`, `templates.migration_audit`, `shared.budget` and
`shared.budget_commands` so later deletion does not require another cross-domain
rewrite. Do not bake migration-derived required versions into new modules or
replace tests with weaker empty-history fixtures here. Such choices would make
item 4 harder.

Item 5 is deferred: preserve Meridian command/environment/state/marker names,
Git-internal files and worktree roots. Do not spread new string literals for
those names across package initializers; retain their shared constant ownership.
Moving or rewriting release baselines and historical migration narratives would
make the later rename harder and is outside this plan. Compatibility adapters
remain removable boundaries, not a new Stable API. Distribution/resource
bundling beyond the current checkout skeleton and the future console/run engine
are separate ADR work items.
