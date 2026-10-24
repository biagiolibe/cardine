# Forgery inventory — decision 14

Snapshot: `main` at `bf85ca68831acb6af28fc2c487b3182ca06f9add`, 2026-10-22.
This is an inventory of the product source at that commit, not a claim about
the installed tool running this repository. No exploit was run against a live
project, and no implementation or test is added by this document.

## Threat model and result

An implementing agent can write ordinary files in its task worktree, create
commits and use ordinary Git plumbing. A linked worktree also exposes the
shared Git directory; putting a receipt there does **not** make it authentic.
Rows distinguish task-tree attacks from attacks requiring primary/shared-path
access. A host permission boundary may deny the latter, but the product must
not mistake a conventional path or an atomic write for that boundary.

The current code validates shape, consistency, ancestry and freshness. It does
not authenticate a schema-valid state, a plausible validation result or a
reviewer's identity. This limitation is explicit in the Consequences of
`ADR_MACHINE_TASK_STATE.md`; decision 14 now requires a stronger boundary.
The Contoso hand-written state is therefore a provenance failure even when a
later integration check happens to reject its contents.

Here, **detected** means the named check rejects the specified inconsistency;
it never implies that all edits of that artifact are detected. **Undetected**
means the reader has no provenance check for a coherent replacement. Test
references below are source evidence inspected, not tests executed for this
documentation task. Where no adversarial test exists, that absence is stated
explicitly; normal writer tests are not presented as authentication tests.

## Repeatable inspection

Run in a disposable checkout of the snapshot, with the installed product kept
separate. These commands read source only:

```sh
git rev-parse main
git status --short
rg --files src/cardine tests schemas capabilities
rg -n 'read_text|write_text|json.loads|_read_json_object|_write_json_atomic' src/cardine
rg -n 'receipt|journal|lease|manifest|digest|sha256|attested_by|approved_by' src/cardine
rg -n 'git_output|_run_git|subprocess.run|interaction_assessment_complete' src/cardine
rg -n '^    def test_' tests/test_machine_task_state.py tests/test_task_integration_state.py tests/test_review_verdict.py
rg -n '^    def test_' tests/test_execution_evidence.py tests/test_validation_evidence.py tests/test_ci_evidence.py
rg -n '^    def test_' tests/test_task_creation.py tests/test_worktree_lifecycle.py tests/test_status_render.py tests/test_single_workflow_config.py tests/test_single_workflow_contract.py tests/test_lifecycle_journal_flow.py
rg -n 'SS6|SS7|RE[1-7]' docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md docs/RUN_ENGINE_PLAN.md
```

Follow each match to its reader and writer using `sed -n '<start>,<end>p'`.
The source references below name functions rather than unstable line numbers.
Reinspect the full reader when reproducing: a search match alone cannot prove
that a later check is absent. Include `tasks/status.py`, `status_render.py`,
`templates/audit.py`, `templates/manifest.py`, `templates/upgrade.py`,
`shared/flow.py`, `worktree/storage.py` and `console/snapshot.py` in that pass.

## Artifacts and attacks

Locations use product names from `shared/layout.py`. **T** is the task
worktree, **P** the primary checkout, **G** the shared Git directory, and
**M** the committed `main` tree. Files in T and P and ordinary G metadata are
writable by the same OS user unless a separate host boundary denies access.
The writer column names intended writers followed by actual access.

| ID / artifact and location | Writers and trusting readers | Concrete attack and current detection | Defense / destination |
| --- | --- | --- | --- |
| F01 — `.cardine/tasks/<ID>.json`, including status, transitions, outcome, review/history; T, M; other task states used as dependency facts | `tasks/creation.py`, `transitions.py`, `review/verdict.py`, integration; agent can replace JSON and commit it. `tasks/state.py::read_task_state`, status, preflight, delivery, review, integration and console consume it. | Hand-write a valid queued state: schema/history validation accepts it without proof of creation. Hand-edit only `status` to `in_review`: history mismatch is detected; edit the whole legal history and it is not authenticated. Forge `done`/`ANSWERED` for a dependency: `dependency_satisfied` trusts these values. Integration rejects a task not in its required prelanding state, but that is not writer detection. | F-A, then RE1/RE4 amendments. Covers the honest Contoso mistake as well as coherent forgery. |
| F02 — nested `contract` snapshot: options, class, CI, validation, validation scoping and `projectDigest`; T, M | `tasks/contract.py::resolve_task_contract`, task creation/import; agent can edit snapshot. `review_is_required`, state validation, integration candidate declarations and status trust it. | Change `review: required` to `not_required`, change matching `review.required`, remove CI or replace validation with weaker commands. Closed schema and cross-reference checks reject malformed policy, not a coherent lower policy. `projectDigest` hashes the declaration at creation; it is not a protected receipt or an immutable-main comparison. | F-A pins the original contract and approved revisions; F-B pins policy. RE1 amendment; RE3/RE4/RE5/RE6 consume that identity. |
| F03 — `.cardine/project.json`; P for `shared/project.py::read_project_declaration`, per-root captured bytes in `tasks/status.py` | Consumer/developer config; ordinary file access can replace it. Contract creation, identity/locations, status and future engine config resolution trust it. | On T alone, changing a copy does not lower existing frozen policy through the primary-root reader. It can still affect readers taking local bytes; snapshot forgery is F02. With P access, set CI to `none`, lower defaults or redirect task roots to fabricated states. Valid values pass parser checks; no authenticated configuration-change check. | F-B; RE1 amendment. Default changes must not silently rewrite existing task contracts. |
| F04 — `.cardine/evidence/<TASK-ID>.json`: validation entries, captures, diagnostics, investigations; T | `tasks/recording.py` writers; agent can write identical JSON. `contract.py::verify_execution_evidence` and `lifecycle/execution.py::delivery_readiness` trust it. | Invent declared command IDs and `exitStatus: 0`. Handoff checks ID/command/status; delivery additionally checks latest entry, source digest and ancestor commit. Recompute those public values for the current tree and forged success remains undetected. Capture artifact paths and investigation findings do not prove the claimed observation happened. | F-C, RE3 amendment; retire prose evidence gates via text inventory N3. Honest stale/misrecorded evidence also covered. |
| F05 — external validation JSON, caller-selected path: T1 CI, T2 shard records/log references, T3 developer attestation | CI/shard/attestation producers; file owner or agent can replace record. `integration/evidence.py::check_validation_evidence` checks it; closure/status consumers use verdict. | Invent a success for a real commit/tree, consistent shard totals/digests, CI run metadata or `attested_by: developer`. Identity and consistency checks detect wrong SHA/tree or failing exit, but verifier does not independently query CI or authenticate the developer string. Logs and counts can be invented together. | F-C and F-D; RE3/RE6 amendments. Preserve an explicit developer attestation path only with authority outside agent-written JSON. |
| F06 — `.git/cardine-worktrees/<stem>.evidence.json`, or supplied integration evidence JSON | `integration/evidence.py::record_task_evidence` derives commits/paths but accepts caller results; direct file access also possible. `merge.py::stage_task_integration` and decision resolver trust acceptance, validation and interaction declarations. | Supply invented zero exit codes and `accepted`, omit dependency/surface interactions and choose `full_validation_required: false`. Writer sets `interaction_assessment_complete: true` unconditionally (text inventory defect 2). Real Git paths supplement the declared paths but do not prove semantic independence. Coherent claims are undetected. | F-C and RE5 amendment. Do not merely move declarations into receipts. |
| F07 — candidate validation JSON, caller-selected path; `advance` writes a G sidecar `.candidate-validation.json` | Agent-supplied candidate command/result pairs or direct JSON; `lifecycle/closure.py`, `merge.py::finalize_task_integration` | Read real `candidate_tree`, invent `passed: true`, correct scope and mandatory command strings without executing them. Finalize detects wrong tree/scope/missing command fragments, but trusts success. A fragment inside a harmless shell command can also satisfy a substring requirement. | F-C; RE5 amendment executes resolved literal commands and records actual outcomes. |
| F08 — `.cardine/candidate-validation.json`, P; compatibility declaration for pre-contract tasks | Setup/project owner; agent with P access can edit. `candidate_validation_declaration` uses it only without a contract snapshot. | Set `state: none` or weaken declared fragments: allowed declaration changes required candidate work. A task-tree edit alone does not replace the P file. Frozen snapshot tasks use F02 instead. | Remove product fallback under F-B/RE5 amendment; legacy diagnostics stay explicit and cannot authorize landing. |
| F09 — `.git/cardine-worktrees/<stem>.json`: registered branch, path, base/task commit and start time | Worktree prepare/repair; same-user G write access. `worktree/checkout.py::inspect_task_worktree`, evidence, closure/status and cleanup | Edit base to a convenient real ancestor, or replace a registration with matching actual Git metadata. Path/branch/common-dir/HEAD/cleanliness checks catch mismatches, not coherent rewritten preparation history. Start-time edits also alter reported duration. | F-A external operation identity; RE1 amendment. Retain real Git checks. |
| F10 — `.git/cardine-integration.lock` and `.git/cardine-integration.json`: lease, owner, candidate tree, decision, main identity | `merge.py::stage_task_integration`; same-user G access. Stage/retry, finalize, abort, closure/status, cleanup | Create a fake foreign lease to force a stop; remove an active lease; replace owner/decision with coherent actual tree and MERGE_HEAD values to misroute retry or validation scope. Exclusive creation and task/tree/HEAD checks detect inconsistency/races, not origin. Finalize checks task IDs, not an unforgeable ownership capability. | F-A plus RE5 amendment; no recovery or abort based solely on a caller-editable task ID. |
| F11 — review verdict/history inside state; review Markdown at configured review root, T/M | `record_review_verdict` writes both; agent can forge state or invoke same CLI including `--owner`. Merge reads structured verdict and ancestor identity; prose is a projection in the state-backed path. | Forge APPROVE with a real reviewed ancestor after implementation and append plausible history. Or invoke review as implementer while claiming reviewer/owner. Branch, clean-tree, status and stale-code checks do not authenticate role. A changed review heading alone cannot override state. | F-D, RE4 amendment. F-A authenticates persistence but cannot establish reviewer independence alone. |
| F12 — `.cardine/task-creation.lock`, `task-creation.guard`, `.task-new-*` staged pair bytes; T | `tasks/creation.py` transaction writer; agent can edit/remove journal and staged bytes. `_recover` and state reader barrier trust them. | Delete barrier to expose a partial pair, or replace journal, paths, digests and staged files together to make recovery accept fabricated ownership. Path/symlink checks, exclusive links, flock and byte comparison catch accidental drift, not a coordinated rewrite. No post-creation receipt survives as writer proof. | F-A, RE1 amendment. Keep crash-safe pair creation, add authenticated creation/recovery identity. |
| F13 — `.git/cardine-journal.jsonl` and rotated `.1.jsonl`; operation log and flow report | `shared/journal.py`, lifecycle closure; agent with G access. `shared/flow.py` trusts event codes, timestamps, classifications for metrics, not landing authorization. | Remove stops or invent finalize/timing events to improve flow/target status. Malformed lines are counted/skipped; valid forged lines are undetected. A failed journal write only warns. This is observability forgery, not currently a lifecycle bypass. | F-A/RE1 amendment for engine receipts; RE7 amendment for reporting. Never use this best-effort log as a recovery authority. |
| F14 — queue, archive, generated plan region/header digest; T/P/M; console-derived views | `tasks/status_render.py` and older projection writers; agent can edit all bytes. Generated status compares recomputed bytes; older console/projection consumers still have text reads. | Forge `[x]` or a matching-looking generated header. New status derives facts from state and detects stale bytes; it still trusts F01/F02. Remaining prose fallbacks can affect console eligibility or legacy integration. | SS6/SS7 already cover retiring projection machinery/fallbacks. Use text inventory T-27 to T-37 for exact readers; do not reimplement authenticity on view headers. |
| F15 — task record, handoff, authority citations, validation/acceptance declarations and review prose; T/P/M | People/agents and generators; preflight/readiness, identity, scope and legacy readers | Rewrite declarations and corresponding handoff assertions to claim completion or reduce work. Presence, format and matching text checks do not establish fact. | Exact entries and removals are in `TEXT_GATE_INVENTORY.md` T-01 to T-26, T-38 to T-44 and N1–N3. F-A/F-C protect replacement facts; RE3 amendment. No duplicate parser inventory here. |
| F16 — Git objects/refs/index/worktree registration: task HEAD, `main`, origin refs, trees, MERGE_HEAD, reflog, remote URL and config; G, T/P and remote | Git and any agent with local Git access; all worktree/merge/review/push/cleanup readers | Build new objects with coherent forged JSON, point task ref at them: content hashes prove bytes, not authority. Modify local origin tracking ref to fake pushed state; direct local main/index changes bypass CLI if host allows them. Actual ancestry/tree/dirty checks reject mismatches, not authorized-looking metadata edits. Remote ref protections remain a separate boundary. | F-A binds operation inputs; F-B pins accepted main identity; RE5/RE6 amendments re-read actual remote facts. F-G defines authority limits. |
| F17 — installation manifest, baselines and capability evidence: `.cardine/manifest.json`, `.cardine/baselines/<version>/…`, managed copies, `probe:` artifacts; project checkout | Lock/adopt/upgrade; agent file access. `templates/manifest.py`, protocol, upgrade planners and `templates/audit.py` trust version, migrations, profiles, digest/probe evidence | Rewrite managed file plus recorded digest, lower profile to advisory, invent probe JSON or migration history. Audit catches ordinary drift against unchanged evidence, missing paths and invalid schema; matching forged metadata has no independent provenance. Installation status/audit can be made misleading. | F-E proposed row; SS6/SS7 and RE1–RE7 do not currently cover installation integrity. Managed text semantics remain in text inventory's kept entries. |
| F18 — `.cardine/flow-targets.json`, context-size config, legacy task-identity config; project checkout | Consumer configuration, ordinary agent file access. `shared/flow.py`, context-size/audit and `tasks/identity.py` consume them | Relax thresholds to report targets met, increase context ceilings, or alter compatibility identity policy. Schema catches invalid settings, not unauthorized valid edits. Flow target misses are reporting only. | F-B for authoritative configuration; RE7 amendment removes legacy identity fallback from product resolution. Advisory targets remain owner-editable but cannot authorize lifecycle effects. |
| F19 — machine user config (`$XDG_CONFIG_HOME/cardine/config.json` or home default), environment/root overrides; outside worktree | Developer/setup and any process with that access. `worktree/storage.py::resolve_worktree_root`, path derivation and collision checks | Redirect root to an attacker-prepared matching checkout. Invalid/conflicting roots and collisions are detected; permitted roots are not proof of trusted receipts. A T-only writer cannot edit user config merely by committing a file. | F-A/RE1 amendment pins project/common-dir/root identity before trusting receipts; F-G covers deliberate developer-level replacement. |
| F20 — trusted executable, schemas, stop/capability/retired-text registries, migrations and template sources; installed package, or source checkout when explicitly selected | Package maintainer; task agent can edit a source checkout but should not control the installed distribution. `tasks/state.py`, `stops/registry.py::load_stop_registry`, catalog loaders, audit and release/upgrade readers trust these rules. | If validation invokes a task-controlled editable installation or framework override, weaken the schema, stop registry or gate implementation along with the artifact. Shape checks cannot defend against replacement of their own rules. Merely committing package-source changes does not replace a separate trusted installation. | F-G excludes compromise of the trusted installation; F-B/RE1 amendment must pin runtime/rule identity and refuse task-controlled rules as authority for their own landing. Package changes may be proposed and tested in isolation, never self-authorize installation. No runtime authenticity test found in these readers. |

## What the tests establish

The following anchors establish existing rejection/acceptance behavior. None
is an end-to-end proof that a coherent forged artifact is rejected as a write
Cardine did not make.

| Rows | Inspected test evidence and missing proof |
| --- | --- |
| F01–F02 | `test_machine_task_state.py::test_invalid_existing_schema_history_and_identity_write_nothing`, `test_transition_timestamps_must_be_chronological`, `test_dependencies_use_landed_results_for_both_presets`; `test_task_integration_state.py::test_schema_valid_but_impossible_history_stops`; `test_single_workflow_contract.py::test_schema_rejects_invalid_snapshot_types_unknown_keys_and_references`. No valid-file writer-authentication test. |
| F03, F08, F18–F19 | `test_single_workflow_config.py::test_invalid_types_and_unknown_properties_fail_closed`, `test_ci_consistency`, `test_configuration_is_independent_of_workflow_and_queue`; contract test `test_import_cli_preserves_snapshot_after_preset_defaults_and_record_change`. No test proving a valid unauthorized policy replacement is rejected. |
| F04 | `test_execution_evidence.py::test_handoff_rejects_fabricated_validation_and_requires_recorded_investigation` rejects a handoff without matching ledger entries; `test_validation_runs_only_a_declared_literal_command_and_records_status` proves the normal runner. Neither authenticates a forged matching ledger. Delivery's extra digest/ancestor checks are in `lifecycle/execution.py::delivery_readiness`; no provenance test found. |
| F05 | `test_validation_evidence.py::test_passing_sharded_record_is_bound_to_commit_and_tree`, `test_invalid_proofs_name_the_failing_field`, `test_attestation_requires_date`; `test_ci_evidence.py::test_run_for_another_commit_is_ignored`. Producer-side polling is stronger than trusting arbitrary verifier input. No verifier test rejects fabricated but coherent CI/shard/developer identity. |
| F06–F10, F16 | `test_worktree_lifecycle.py::test_integrate_finalize_reports_an_evidence_mismatch`, `test_advance_reports_a_candidate_tree_that_changed_after_stage`, `test_advance_aborts_without_finalizing_when_a_required_command_is_missing`, `test_integrate_stage_reports_a_held_lease_through_the_registry`, `test_prepare_and_worker_check_json_exit_codes`. No authenticated receipt, invented-success, coherent registration/lease replacement or actual remote-vs-local-ref forgery test found in these paths. |
| F11 | `test_review_verdict.py::test_contradictory_prose_cannot_supply_or_override_a_verdict`, `test_owner`, `test_approval_requires_resubmission_after_an_implementation_commit`; integration tests `test_reverted_implementation_commit_still_invalidates_approval`, `test_nonancestor_review_stop`, `test_only_own_governance_changes_preserve_approval`. No independent reviewer identity or coherent forged approval rejection test. |
| F12 | `test_task_creation.py::test_symlinked_task_root_and_state_directory_rejected`, `test_recovery_preserves_complete_pair_and_refuses_changed_partial`, `test_concurrent_creation_same_id_has_one_writer`. No coordinated journal/digest/staged-pair rewrite test. |
| F13 | `test_lifecycle_journal_flow.py::test_concurrent_appends_from_two_worktrees_produce_whole_lines`, `test_write_failure_warns_once_and_keeps_the_result`, `test_malformed_lines_are_counted_and_never_fatal`. No valid-line authenticity test. |
| F14 | `test_status_render.py::test_stale_or_hand_edited_view_is_reported_then_regenerated`, `test_header_digest_ignores_views_and_changes_with_inputs`; text inventory records remaining consumers. No view-header authenticity is needed once no gate reads views. |
| F15, F17–F18 | See text inventory for text checks; `templates/audit.py::audit_managed_copy_digests`, `audit_declared_capabilities` and manifest validation supply drift/shape checks. No coordinated manifest/baseline/probe or valid configuration provenance test found. |

## Defenses and destinations

These are proposals for subsequent tasks, not changes to the plan files or
permission to start those tasks. Every undetected attack above maps here.

**F-A — operation authority.** Keep tracked state portable, but require an
operation receipt binding project/common-dir identity, task, operation ID,
previous receipt, exact input/output digests, contract identity and committed
source. Creation, transition, cancellation and recovery must verify it before
using state. Refuse direct writes and unauthorized import/reconciliation paths.
A receipt outside the worktree only works if the agent cannot replace it or
invoke its writer with forged authority: a G file, a hash next to the data or a
secret readable by the same agent is insufficient. Use a host-enforced broker
or protected store; a fresh clone needs verified portable receipts or explicit
developer reauthorization, never silent acceptance of local JSON. This closes
F01/F02/F09/F10/F12/F13/F19 for both mistaken and deliberate edits.

**F-B — policy authority.** Resolve existing policy from the accepted main
commit and protect that commit identity; compare task snapshots to the creation
receipt and subsequent authorized amendments, not today's mutable defaults.
Reject task-branch configuration substitutions and separate a proposed policy
change from the policy authorizing its own landing. Pin executable command IDs,
CI requirements, locations, trusted runtime/rule identity and relevant configuration digests. Cover F20 and F02/F03/
F08/F16/F18; honest edits to the wrong copy get an actionable mismatch too.

**F-C — observed execution.** Engine executes configured commands and records
actual exit status, task/source/tree identity, command/config digest, cwd,
attempt and bounded logs. Verify protected receipt provenance on consumption;
an agent-supplied digest cannot substitute for measurement. Hash inputs before
and after execution and invalidate on change, including concurrent mutation.
Remove success/acceptance/scope options as authority. Acceptance requiring human
judgment needs a separate authenticated decision, not a fabricated automatic
test. Derive interactions conservatively; use FULL when independence is not
proved. Covers F04–F07 and replacement facts for F15, including honest stale
results and defect 2's unconditional assertion.

**F-D — reviewer/developer authority.** Route review to a distinct protected
principal/session capability bound to task, attempt, contract and source.
The implementer cannot mint that capability or assert `--owner`; explicit
developer approval uses a separately authenticated channel. Query the CI
provider for exact repository/SHA/check identities, and bind any cache to a
protected receipt. Covers F05/F11 and prevents honest wrong-head approval.

**F-E — installation authority.** Validate manifest/baseline/probe claims
against the trusted installed package/catalog and authorized installation
receipts. Project-controlled probe results must be rerun or verified by the
protected executor, with source/config identity. Keep intentionally editable
managed regions editable; their contents must not confer lifecycle authority.
Covers F17, including honest stale manifests. This is not presently covered
by any SS6/SS7 or RE1–RE7 scope text.

| Destination | Current coverage / exact proposed amendment or new row |
| --- | --- |
| RE1 amendment, F-A/F-B | Atomic operation receipts are already named, but writer authenticity and bootstrap are not: “Protect creation, state, contract, policy and recovery receipts from task-agent writes, verify every consumed artifact against their digests and authorized main identity, and define fresh-clone reauthorization, root binding and trusted runtime/rule identity.” Add coherent F01/F02/F03/F09/F12/F19 attacks to its tests. |
| RE3 amendment, F-C | Automatic validation and recorded delivery are covered; ledger provenance and external attestations are not: “Execute and authenticate validation and acceptance evidence, reject caller-invented results and stale/concurrently changed inputs, and retire agent-written evidence as gate authority.” Test F04/F05/F15 plus honest stale results. |
| RE4 amendment, F-D | Independent review is already required in the plan prose, but its enforceable trust boundary is unspecified: “Require a protected reviewer/developer capability and receipt for verdict and cancellation authority, reject implementer self-approval and forged state/history, and bind approval to the authenticated contract and source.” Test F01/F11, including CLI owner spoofing. |
| RE5 amendment, F-A/F-B/F-C | Tree-bound candidate execution is covered; forged lease/evidence and semantic declarations are not: “Authenticate leases, candidate state and observed command outcomes, remove caller acceptance/interaction/scope authority and pre-contract product declaration fallback, and derive candidate requirements from pinned policy and actual Git facts.” Test F06–F10/F16 and defect 2. |
| RE6 amendment, F-D | Exact-head CI and push reconciliation are covered; authenticating cached proofs is not: “Reject editable local CI/push receipts as proof, verify provider and actual remote ref facts for the pinned repository/SHA, and authenticate any reusable result.” Test F05/F16, fake local tracking refs and fabricated successful CI JSON. |
| RE7 amendment | Console/shared-fact use and final audit are covered; forged metrics and config fallback are not: “Consume authenticated facts in console/flow reports, label unverifiable historical events, remove product legacy identity fallback, and exercise every forgery row through the same protected boundary as run.” Covers F13/F18 and verifies all rows end to end. |
| SS6 and SS7, no amendment | Their existing stable-record, generated-view and shared-fact scopes cover F14 removal; the text inventory supplies the remaining exact parser/removal destinations for F15. They do not by themselves authenticate state. |
| Proposed FI1 / 3h, after RE1 and before RE7 | “Protect installation manifest, baselines, capability/probe evidence and upgrade recovery against coherent project-file forgery using trusted package data and authorized operation receipts.” Adds F17 tests for simultaneous file/digest/profile/probe edits. No current row covers this installation surface; if deferred from 1.0, explicitly remove installation claims from decision 14's promised boundary rather than silently omit them. |

RE2 continues to own classification and safe recovery codes; it does not make
any file authentic. Every amended effectful row must also retain decision 14's
interruption/retry criterion. Tests must attempt both an inconsistent edit and
a coherent rewrite with recomputed public digests; only testing malformed JSON
would leave the strong-agent case open.

## Attacks that remain possible by design

**F-G — ultimate authority.** A developer who intentionally grants the agent
their own protected credentials, approves a weaker contract, changes remote
protection or replaces the installed trusted broker can authorize the same
effects as the developer. Root/administrator compromise, Git hash collisions
and compromise of the trusted CI provider/package distribution are outside
this task-agent boundary. Ordinary same-user access to an unprotected G file
is not such an exception: F-A must either enforce a real boundary or report
that writer authenticity is unavailable. Never advertise a same-user hash file
as satisfying decision 14.

An agent may implement bad code that passes legitimate tests, or supply a
misleading human explanation. Receipts prove which operation observed which
inputs, not semantic correctness; independent review and acceptance remain
necessary. Free-form reports and generated views can remain editable once no
gate trusts them. A malicious process may also deny service by removing its
own worktree or withholding work; the product must preserve foreign work and
fail closed, not promise task completion against an uncooperative writer.

Future run-engine operation receipts do not exist in today's product paths.
The creation transaction journal, best-effort lifecycle journal and Git-side
integration state above are the current analogues, not equivalent security
guarantees. Installed-tool metadata and managed prose readers retained for
compatibility are covered here as separate surfaces; their text details remain
in [the text gate inventory](TEXT_GATE_INVENTORY.md).
