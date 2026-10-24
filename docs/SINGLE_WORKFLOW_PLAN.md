# Single workflow plan — ADR work item 6

## Scope and delivery boundary

This plan implements decision 3 of [the Cardine 1.0 ADR](ADR_CARDINE_1_0.md),
with the contracts of decisions 4, 5, 11, and 12. It defines one lifecycle,
one template set, and project presets `lean` and `governed`. Presets supply
options, not separate engines. No implementation is authorized by this document.

All implementation tasks below depend on the **last work item 5a task defined
by task 040** (called `5a-final` here). The coordinator resolves that symbolic
dependency to its real ID before scheduling. Nothing here depends on reading
or modifying task 040's parallel `docs/RENAME_PLAN.md`. Product names below
assume 5a has landed: `cardine`, `.cardine/`, and the Cardine Git internals.

Product templates, schemas, tests, and Python modules may change in item 6.
This repository's managed files, `.meridian/`, hooks listed by its manifest,
and installed Meridian remain untouched until work item 10. Product fixtures
are separate from this repository's active workflow. No task below runs an
upgrade on this checkout or changes its own lifecycle to Cardine.

Work items 5b, 7, 8, and 9 are consumers of this design, not implementation
scope here. In particular, item 6 does not rename marker delimiters, remove
Markdown/queue/plan status duplicates, generate status, build `cardine run`,
or create host skills or replace host hook implementations.

## 1. Project configuration and resolution

Extend the consumer-owned `.cardine/project.json`, validated by
`schemas/project-v1.schema.json`; do not introduce another workflow file.
Retain the existing `project`, `locations`, `validationScoping`, and `ci`
properties and their path-safety rules. Add the following closed objects.
This is a proposed example, not a configuration for this repository:

```json
{
  "version": 1,
  "preset": "lean",
  "taskDefaults": {
    "review": "not_required",
    "authorityRequired": false,
    "expectedCodeSurfaceRequired": false,
    "validationRetryLimit": 3,
    "landingMode": "direct",
    "ciBeforeLanding": false
  },
  "taskIdentity": { "mode": "opaque" },
  "validation": {
    "commands": { "repository": "python3 scripts/check_repository.py" },
    "baseline": ["repository"],
    "candidate": {
      "REUSE": ["repository"],
      "BOUNDED": ["repository"],
      "FULL": ["repository"]
    }
  },
  "ci": "none"
}
```

`version` and `preset` are required for a new Cardine declaration. Preset is
exactly `lean|governed`; unknown values and unknown properties fail closed.
`taskDefaults` is optional; every member is optional and overrides the preset.
Review is `required|not_required`; the three requirement/CI flags are booleans;
`validationRetryLimit` is an integer >= 1 (booleans rejected); `landingMode`
is the enum containing only `direct` in 1.0. Reject `pull-request` explicitly,
without a forge probe. `taskIdentity.mode` is `opaque|milestone`, default
`opaque`, retaining the grammar, aliases, safety, and historical-ID rules of
[TASK_IDENTITY_POLICY.md](TASK_IDENTITY_POLICY.md).

`validation` is required at initialization. `commands` maps nonempty stable
IDs to nonempty literal commands. Baseline and candidate arrays reference only
known IDs, with no duplicate IDs; all three candidate outcomes are required.
An empty list is explicit, never an implicit omission of validation. Candidate
validation always adds `git diff --check`. Retain bounded path-based selection
through `validationScoping`; task commands supplement the baseline and do not
silently remove it. Full validation includes baseline plus the declared full
suite. The example has one command for illustration; init requires the owner
to choose the actual project commands before a task can execute.

`ci` keeps `none` or `{provider, requiredChecks}`. Effective
`ciBeforeLanding: true` requires a supported provider, nonempty required check
names, and exact-task-commit verification. An absent provider or empty check
set is invalid, never a successful no-op. `false` adds no forge dependency.
The later integration engine owns the single task-branch push, CI polling,
and safe remote cleanup of decision 11; item 6 defines and tests policy only.

| Option | Lean default | Governed default | Replaces current authority |
| --- | --- | --- | --- |
| `preset` | `lean` | `governed` | Workflow-mode lock and mode selection |
| `review` | `not_required` | `required` | Workflow-wide review assumption |
| `authorityRequired` | false | true | Governed contract/template requirement |
| `expectedCodeSurfaceRequired` | false | true | Governed contract/template requirement |
| `validationRetryLimit` | 3 | 3 | Capability-profile diagnostic budgets; decision 5 removes the other counters |
| `landingMode` | `direct` | `direct` | Implicit local landing in workflow/capability instructions |
| `ciBeforeLanding` | false | false | CI validation tier/profile choice as a landing gate |
| `taskIdentity.mode` | `opaque` | `opaque` | `.meridian/task-identity.json` (the 5a-renamed equivalent is folded here) |
| `validation` | Owner-declared | Owner-declared | `.meridian/candidate-validation.json` and command defaults in capability profiles |

Capability profiles remain installation/evidence metadata where needed, not
an alternative authority for task options or commands. Evidence output bounds,
manual-evidence requirements, and host support declarations retain their
purpose; they do not recreate the removed spend counters. Existing location
and validation-scoping declarations compose with this schema rather than
being copied into another policy file. Conversion of real Meridian projects
and retiring their old declarations belong to item 10.

Resolution order is preset -> explicit project defaults -> explicit task
options. The task creation/contract resolver persists the fully resolved
options and validation command set, their project declaration digest, and
preset in a CLI-written `contract` snapshot in `.cardine/tasks/<ID>.json`.
These are policy fields, not additional status fields. Omission means inherit;
false and `not_required` are explicit overrides. No implicit tightening or
loosening follows from the task class, host, queue shape, or ID spelling.

Changing project preset/defaults affects new tasks only. An open task keeps
its snapshot. A deliberate contract revision is explicit, scoped, audited,
and invalidates incompatible validation/review evidence; a prose edit cannot
silently disable review of an already delivered commit. Task identity is a
project naming policy, not a task option that can rename an existing task.

`cardine.templates.mode` becomes a configuration resolver: expose the resolved
preset for display and select the single template root independently of it.
All consumers of `detect_mode` use this resolver; neither queue headers nor
`PROJECT_WORKFLOW.md` text select a workflow. Missing/malformed configuration
is reported as such, never guessed from a governed table or empty queue.
`cardine init` asks for the preset, offers `lean` as default, writes the
configuration, and installs exactly the same files for both choices.

## 2. One task contract

Use one `tasks/TASK_BLUEPRINT.md`. Human-authored scope and acceptance text
stay in the record; resolved policy and lifecycle history are CLI-owned.

| Field | Both presets | Preset-sensitive rule |
| --- | --- | --- |
| ID, title, priority, estimate, objective | Required; immutable canonical ID | None |
| Class | `standard` by default; `spike` available | Neither preset restricts spikes |
| Dependencies, out of scope, relevant files/context | Required; `none` is explicit | Dependencies block in both presets |
| Acceptance criteria, validation IDs and literal commands | Required for standard tasks | Baseline composes with task commands |
| Review | Optional explicit `required|not_required` override | Default from resolved project options |
| Authority | Named ADR/spec sections when supplied | Required by governed default; task may raise or lower requirement |
| Expected code surface | Add/change, preserve, evidence needed | Required by governed default; task may raise or lower requirement |
| Options | Optional keys from `taskDefaults` | Same type validation; explicit overrides in either direction |
| Host impact | Classification/rationale; profile and evidence matrix when applicable | Same routing in either preset |
| Manual verification | `none|required`, with perceptual rationale if required | Preserve evidence tiers and availability precondition |
| Completion/research handoff | Evidence, results, remaining uncertainty | One completion format; no Budget usage field |

For example, a lean task can set `review: required` and both scope requirements
to true; a governed task can explicitly set `review: not_required`. Both are
valid contract choices before execution. Missing required fields fail contract
validation. Optional Authority/surface fields, when supplied, still constrain
the work. When a surface is omitted, the explicit objective, relevant files,
and out-of-scope clauses still bound authorization: omission never grants
permission for unrelated work. A quick task is a minimal registered task with
an objective, acceptance/validation, dependencies, and resolved policy; it
has no unregistered or fileless lifecycle exemption.

A spike requires `Question`, `Timebox`, and `Deliverable` (ADR or documented
reference value); these replace the standard objective/feature acceptance
shape. Its close-out validation checks the answer or documented uncertainty,
timebox, and deliverable. No production code is landed. Optional probe code
is isolated and never merged/pushed. `ANSWERED|INCONCLUSIVE` is an outcome,
not a new lifecycle. Unlike the old spike shortcut, review is an independent
option: a governed spike inherits required review unless explicitly waived.
Expected surface, when required, names the deliverable and permitted probes;
it is not an excuse to permit production changes. Authority follows the same
requirement rule as any task.

Execution evidence remains bound to task attempt and commit. The contract
stores `validationRetryLimit`; it does not ask the agent to count retries.
The attempt-bound automatic counter, intermittent rerun, execution journal,
and next-action orchestration are implemented by item 8. Templates already
state decision 12: guardrails stop, recoverable actions continue unchanged,
and failing work is corrected within the configured limit. No template
requires stopping merely because the first validation command failed.

## 3. One state vocabulary and transition contract

The authoritative field remains `status` in `.cardine/tasks/<ID>.json`,
validated by `schemas/task-state-v1.schema.json` and written only by the CLI.
Use `queued`, `in_progress`, `in_review`, `done`, `cancelled` and chronological
CLI-written transitions with commit/time binding. `contract.preset` records
provenance, never selects a different machine. Review attempt, verdict,
reviewed commit, approver, and an external-review source remain structured
metadata; reserve the source discriminator for the 1.1 integration adapter.

| Current Lean state/signal | Current Governed SDD state | Single state and preserved meaning |
| --- | --- | --- |
| `QUEUED`, `[ ]` | `QUEUED` | `queued` |
| Active worktree, `[/]` | `IN_PROGRESS` | `in_progress` |
| No dedicated state | `READY_FOR_REVIEW` | `in_review`, required review only |
| No dedicated state | `CHANGES_REQUESTED` | `in_progress`, retain rejected attempt and verdict |
| No dedicated state | `ACCEPTED` | `in_progress` with approval metadata until landing; acceptance alone is not `done` |
| No dedicated state | `ANSWERED`, `INCONCLUSIVE` | `in_progress` with spike outcome until landing, then `done` |
| `DONE`, `[x]` after integration | Completed governed task after integration | `done` |
| No canonical state | No canonical state | `cancelled`, explicit authorized cancellation |

Allowed transitions: `queued -> in_progress`; `in_progress -> in_review`
only if review is required; `in_review -> in_progress` on approval (retain
commit-bound approval) or requested changes (invalidate approval); and
`in_progress -> done` only through verified landing. No-review tasks never
enter `in_review`. Required-review tasks cannot land without approval of the
exact current commit; a new implementation commit invalidates approval and
must be submitted again. Guard this with evidence, not a second status such
as `accepted` or `ready_to_land`.

`queued|in_progress|in_review -> cancelled` requires explicit cancellation
authority and records its reason. `done` and `cancelled` are terminal; reopening
is a new task. Cancellation never force-removes a dirty/unmerged worktree.
Dependencies are met by a landed standard task, or a landed spike whose
outcome is `ANSWERED`. `INCONCLUSIVE` and `cancelled` never satisfy dependencies.
No task becomes startable while `in_progress` or `in_review`.

The mapping specifies product behavior and synthetic fixtures, not a bulk
rewrite of historical tasks. Conversion is item 10. Item 6 retains the current
Markdown status/archive and queue/plan projection machinery where it exists;
it adapts those consumers to the vocabulary without removing duplicate fields
or changing archival ownership. Item 7 removes those duplicates and builds
generated status. It must not have to interpret approval as completion.

## 4. Single template inventory

The sole source root is `templates/single/`; paths in the destination column
are relative to that root. Both presets install this complete set, including
review documents, with no preset-specific overlay. Rows enumerate every
current file in the three task-specified roots. `Merged` means content is
reconciled once, not that installation falls back to one of two sources.

| Source under `templates/` | Decision | Destination |
| --- | --- | --- |
| `base/CLAUDE.md` | Merged with both host routers | `CLAUDE.md` |
| `base/LANGUAGE_POLICY.md` | Merged with marked language policies | `LANGUAGE_POLICY.md` |
| `base/README.md` | Kept | `README.md` |
| `base/PROJECT_PLAN.md` | Kept; item 7 owns status generation | `PROJECT_PLAN.md` |
| `base/TECH_DESIGN.md` | Kept | `TECH_DESIGN.md` |
| `base/tasks/QUEUE.md` | Merged; remove fileless quick-task advice | `tasks/QUEUE.md` |
| `base/tasks/TASK_BLUEPRINT.md` | Merged into one contract | `tasks/TASK_BLUEPRINT.md` |
| `workflows/lean-delivery/AGENTS.md` | Merged with governed router | `AGENTS.md` |
| `workflows/lean-delivery/CLAUDE.md` | Merged with other routers | `CLAUDE.md` |
| `workflows/lean-delivery/LANGUAGE_POLICY.md` | Merged | `LANGUAGE_POLICY.md` |
| `workflows/lean-delivery/PROJECT_WORKFLOW.md` | Merged into option-driven lifecycle | `PROJECT_WORKFLOW.md` |
| `workflows/lean-delivery/docs/WORKTREE_LIFECYCLE.md` | Merged | `docs/WORKTREE_LIFECYCLE.md` |
| `workflows/lean-delivery/docs/COMPLETION_REPORT_TEMPLATE.md` | Merged | `docs/COMPLETION_REPORT_TEMPLATE.md` |
| `workflows/lean-delivery/docs/EXECUTION_EVIDENCE_PROFILE.md` | Merged; no spend counters | `docs/EXECUTION_EVIDENCE_PROFILE.md` |
| `workflows/lean-delivery/docs/CONTEXT_BUDGET_POLICY.md` | Merged and renamed | `docs/CONTEXT_READING_POLICY.md` |
| `workflows/governed-sdd/AGENTS.md` | Merged | `AGENTS.md` |
| `workflows/governed-sdd/CLAUDE.md` | Merged | `CLAUDE.md` |
| `workflows/governed-sdd/LANGUAGE_POLICY.md` | Merged | `LANGUAGE_POLICY.md` |
| `workflows/governed-sdd/PROJECT_WORKFLOW.md` | Merged | `PROJECT_WORKFLOW.md` |
| `workflows/governed-sdd/tasks/QUEUE.md` | Merged; projection removal deferred | `tasks/QUEUE.md` |
| `workflows/governed-sdd/tasks/TASK_BLUEPRINT.md` | Merged | `tasks/TASK_BLUEPRINT.md` |
| `workflows/governed-sdd/docs/CODE_ORGANIZATION.md` | Kept | `docs/CODE_ORGANIZATION.md` |
| `workflows/governed-sdd/docs/WORKTREE_LIFECYCLE.md` | Merged | `docs/WORKTREE_LIFECYCLE.md` |
| `workflows/governed-sdd/docs/COMPLETION_REPORT_TEMPLATE.md` | Merged | `docs/COMPLETION_REPORT_TEMPLATE.md` |
| `workflows/governed-sdd/docs/EXECUTION_EVIDENCE_PROFILE.md` | Merged | `docs/EXECUTION_EVIDENCE_PROFILE.md` |
| `workflows/governed-sdd/docs/AUDIT_PROMPT_READ_ONLY.md` | Kept; remove workflow exclusivity | `docs/AUDIT_PROMPT_READ_ONLY.md` |
| `workflows/governed-sdd/docs/OPERATOR_PROMPTS.md` | Kept; options replace mode branches | `docs/OPERATOR_PROMPTS.md` |
| `workflows/governed-sdd/docs/workflows/REVIEW.md` | Kept; conditional on review option | `docs/workflows/REVIEW.md` |
| `workflows/governed-sdd/docs/workflows/REMEDIATION.md` | Kept | `docs/workflows/REMEDIATION.md` |
| `workflows/governed-sdd/docs/workflows/LIFECYCLE.md` | Merged into canonical orchestration | `docs/LIFECYCLE_ORCHESTRATION.md` |
| `workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md` | Kept; one implementation procedure | `docs/workflows/IMPLEMENTATION.md` |
| `workflows/governed-sdd/docs/LIFECYCLE_ORCHESTRATION.md` | Merged with lifecycle procedure | `docs/LIFECYCLE_ORCHESTRATION.md` |
| `workflows/governed-sdd/docs/ARCHITECTURE_DECISIONS.md` | Kept | `docs/ARCHITECTURE_DECISIONS.md` |
| `workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md` | Merged and renamed | `docs/CONTEXT_READING_POLICY.md` |
| `workflows/governed-sdd/docs/CODE_REVIEW_PROMPT.md` | Kept | `docs/CODE_REVIEW_PROMPT.md` |
| `workflows/governed-sdd/docs/PULL_REQUEST_POLICY.md` | Renamed; describes direct integration only | `docs/INTEGRATION_POLICY.md` |
| `workflows/governed-sdd/docs/REVIEW_RECORD_TEMPLATE.md` | Kept | `docs/REVIEW_RECORD_TEMPLATE.md` |

Remove the three old source roots once all generators/package manifests and
tests use the single set; no runtime template fallback remains. Preserve
project-local prose on installation/update. The above is a product-source
inventory, not permission to edit this checkout's managed copies.

### Capabilities and task 038

`capabilities/catalog-v1.json` replaces `workflowModes` selection with the
single distribution and conditional option requirements where applicable.
Rename capability `context-budgeting` to `context-reading`, update dependency
references and managed paths to `docs/CONTEXT_READING_POLICY.md`, and retain
task-first reads, large-file guard, evidence tiers, and bounded reading rules.
Do not retain budget show/spend, the ledger, or self-reported counters. The
repository's `docs/CONTEXT_BUDGET_POLICY.md` stays until item 10.

`capabilities/markers-v1.json` has one `requiredVersion` per live capability;
all occurrences in `templates/single/` use that version. Preserve the existing
number of the selected canonical block, not a fresh `v1`. Prefer the current
highest shipped block when reconciling lower variants: lifecycle orchestration
is v12, not v3; bounded-worktree-lifecycle is v8, not v6. Reconcile the text
before removing either source. Audit every capability, including versions
that differ from today's governed-only `requiredVersion`. Rewrite the product
`capabilities/marker-baselines.json` to match canonical content at those
numbers; no historical release baseline or migration is added before 1.0.

Keep `MERIDIAN:BEGIN` / `MERIDIAN:END` syntax and the selected version numbers.
Even `context-reading` retains the old capability's numeric version. Item 5b
owns the later delimiter/name cleanup and reset of every capability to v1.
Do not combine that reset with this consolidation.

This resolves task 038's fallback proposal by removing its premise: a single
set never compares a lower-version Lean block with a governed-only catalog.
Do not add a permanent per-file version fallback. Merge integrity still checks
the installed file's exact marker/digest against its recorded baseline before
applying an update; divergent local edits remain conflicts. Tests must prove
both identical-version distribution and refusal of a tampered block.

## 5. Briefing and future hosts

The per-turn briefing reads the configured preset through the shared resolver
and prints `Preset: lean` or `Preset: governed`, irrespective of queue layout.
It never infers a mode from columns, headers, or the presence of rows. Missing
configuration produces a configuration diagnostic, not a Lean header.

Regression fixture: a governed project with every closed phase archived and
no task in its queue must still print `Preset: governed`. Run the same fixture
through both host invocation fixtures using the product briefing adapter, plus the lean counterpart, malformed
configuration, and a governed-looking table with `preset: lean`. The last
fixture must print lean. The adapter supplies the configured preset header and retains the existing
briefing payload/count behavior in isolated fixtures. It does not modify or
activate this checkout's manifest-owned hook. Counts/status semantics are
unchanged here; item 7
owns totals from task states and exclusion of active/review tasks from the
startable list. Item 9 must reuse these fixtures against its shared Python
hook and both hosts rather than writing a second preset inference path.

One skill per host belongs to item 9. Those skills read installed
`PROJECT_WORKFLOW.md`, `tasks/TASK_BLUEPRINT.md`,
`docs/CONTEXT_READING_POLICY.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`,
`docs/WORKTREE_LIFECYCLE.md`, `docs/LIFECYCLE_ORCHESTRATION.md`, and
`docs/workflows/IMPLEMENTATION.md`; review additionally reads
`docs/workflows/REVIEW.md`, `docs/workflows/REMEDIATION.md`,
`docs/CODE_REVIEW_PROMPT.md`, `docs/REVIEW_RECORD_TEMPLATE.md`, and
`docs/INTEGRATION_POLICY.md`. `LANGUAGE_POLICY.md` and the host's
`AGENTS.md`/`CLAUDE.md` remain entry authorities. No host skill selects a
preset-specific template tree.

## 6. Governed SDD parity ledger

Every row of decision 3's parity table has a retained implementation point.

| ADR feature | Preserved by |
| --- | --- |
| Required review | Section 1 governed default; sections 2–3 exact-commit gate |
| Per-task review not required | Explicit override and frozen contract in sections 1–2 |
| Verdict bound to approved commit | Section 3 structured review metadata and invalidation |
| Changes requested and new attempt | Section 3 review return to implementation, new attempt; item 8 runs the next action |
| Exploratory ANSWERED/INCONCLUSIVE | Sections 2–3 spike outcome and dependency semantics |
| Authority citing ADRs | Section 2 contract requirement and retained ADR references |
| Expected code surface | Section 2 bounded surface and explicit override |
| ADR log | Section 4 retained log; existing `cardine adr list/show` unchanged |
| Blocking dependencies | Section 3 landed-result gate for both presets |
| Milestone task identity | Section 1 project option, existing identity resolver retained |
| Execution evidence | Section 2 attempt/commit binding; item 8 records it through `cardine run` |
| Context budget counters | Sections 1–2 retry-limit option; section 4 reading policy preserves read guard, item 8 implements counting |

## 7. Ordered implementation tasks

These are proposed planning labels, not queued or started tasks. Every row is
2–3 hours. Dependencies include `5a-final` explicitly. Execute serially: shared
schemas, contract/state readers, templates, catalog, and fixtures make parallel
writers unsafe. Paths below are product files only; no managed checkout copy
or `.meridian/` file is an implementation target.

| Order / estimate | Scope and bounded files | Tests that prove it | Dependencies |
| --- | --- | --- | --- |
| SW1 / 3h | Project schema, presets and resolution; `schemas/project-v1.schema.json`, `src/cardine/shared/project.py`, `src/cardine/templates/mode.py`, new `tests/test_single_workflow_config.py` | Absent vs explicit defaults, invalid types/unknown keys, direct-only, CI consistency, command references, config independent of queue | `5a-final` |
| SW2 / 3h | One resolved task contract and creation snapshot; `src/cardine/tasks/contract.py`, `src/cardine/tasks/identity.py`, `src/cardine/tasks/recording.py`, task creation CLI adapter, `schemas/task-state-v1.schema.json`, `tests/test_single_workflow_contract.py`, `tests/test_task_identity_project.py` | Lean required review, governed waiver, required-field overrides, spike contracts, registered quick tasks, preset switch leaves open snapshots unchanged | `5a-final`, SW1 |
| SW3 / 3h | Single machine, review and dependency gates; `src/cardine/tasks/state.py`, `transitions.py`, `preflight.py`, `schemas/task-state-v1.schema.json`, `src/cardine/review/`, integration task-state consumers, `tests/test_machine_task_state.py`, `tests/test_review_verdict.py`, `tests/test_task_integration_state.py` | Full transition matrix, stale approval, requested changes/new attempt, cancellation, spike outcomes, landing-only done, dependency blocking | `5a-final`, SW2 |
| SW4 / 3h | Consolidate all 37 inventory sources into `templates/single/`; update `src/cardine/templates/files.py`, `generator.py`, `router.py`, distribution inclusion and init adapter; `tests/test_template_router.py`, `tests/test_template_manifest.py` | Both presets install same file list; no old-root fallback; inventory coverage and links; one task shape; preserved local prose | `5a-final`, SW3 |
| SW5 / 3h | Reconcile capability catalog, markers/baselines and single template blocks; `capabilities/catalog-v1.json`, `markers-v1.json`, `marker-baselines.json`, `templates/single/`, `src/cardine/templates/catalog.py`, `marker_audit.py`, `merge.py`, `tests/test_template_surface_upgrade.py`, `tests/test_template_stop_policy.py`, new `tests/test_single_workflow_capabilities.py` | One version per capability, v12/v3 regression, policy/path rename, intact delimiter/numbers, tamper refusal, decision-12 instruction assertions | `5a-final`, SW4 |
| SW6 / 2h | Preset-only briefing output adapter; new `src/cardine/hosts/briefing.py` and isolated Claude/Codex hook invocation fixtures (copies under test temporary roots), `tests/test_queue_briefing.py`, new `tests/test_single_workflow_briefing.py` | Empty queue for both presets on both hosts, misleading table, invalid config; no managed hook edits, host activation, replacement hook implementation, or new state counting | `5a-final`, SW5 |
| SW7 / 2h | Remove residual product workflow branching and exercise parity; `src/cardine/templates/`, task/integration consumer adapters found by mode-reference search, user configuration docs, `tests/test_single_workflow_parity.py`, affected fixtures | All twelve parity rows; init/contract/state/review/landing fixture chain for both presets; no duplicate workflow machine/template root; handoff to 5b/7/8/9 | `5a-final`, SW6 |

Before scheduling each task, the coordinator binds named adapter surfaces to
exact files in the post-5a tree and splits a row if its bounded 2–3h estimate
no longer holds. This is contract preparation, not license for an implementer
to expand scope. Every implementation task declares its exact unit commands,
runs `python3 scripts/check_repository.py`, the applicable targeted tests,
`python3 scripts/run_tests.py --parallel` for source/runtime changes, and
`git diff --check`. Commands use the post-5a `cardine` product in fixtures;
this repository continues closing tasks with installed Meridian.

## 8. Constraints handed to later work items

- **5b:** single root and uniform versions simplify marker reset; no new
  delimiter or marker version namespace is introduced here.
- **7:** frozen contracts and landed-only `done` keep policy separate from
  status. Duplicate prose status and archives remain for item 7 to remove;
  briefing preset lookup must not be expanded into another state calculator.
- **8:** policy resolution, transitions, and evidence gates are reusable
  library functions. No preset-specific runner is permitted. Retry options,
  approval metadata, direct landing, CI-before-landing, and recoverable-next
  instruction semantics are inputs, not a second orchestration engine.
- **9:** stable installed document paths and common preset resolver permit one
  skill per host and one shared Python hook. Current hook regression fixtures
  are retained as a compatibility contract; replacing hooks is deferred.
- **10:** do not read renamed Meridian state as a second live authority or
  silently convert this checkout. Real conversion of configuration, state,
  managed copies, and the old context-policy path is an explicit later step.

No 1.1 pull-request implementation is planned. Keeping landing policy and
external review provenance independent of presets preserves that extension
without inventing additional states or a second template set.

## Coordinator notes (2026-10-19)

- `5a-final` is task 051, the last row (R10) of `docs/RENAME_PLAN.md`.
- `cardine.legacy.meridian_installation.load_meridian_snapshot` (rename plan
  row R2) builds the coordinator's snapshot of this repository through the
  same snapshot code, and that code reads the workflow through `detect_mode`,
  from the frozen `PROJECT_WORKFLOW.md` and `tasks/QUEUE.md`. When row SW1
  makes every consumer of `detect_mode` use the configuration resolver, the
  Meridian workflow detection moves into `cardine.legacy`, and
  `load_meridian_snapshot` keeps reading this repository until work item 10.
  Rename plan choice 5 states the same constraint.


For development, `python3 scripts/run_tests.py --parallel --last-failed`
reruns the failing test IDs recorded in this worktree's Git directory.
`--parallel --module <name>` selects a module, `tests/test_name.py` path,
class, or test ID; repeat `--module` to select their union. Unknown names
are refused with nearby module suggestions. Partial runs print `PARTIAL`
with the selection and full test count. They do not count as validation:
finish with `python3 scripts/run_tests.py --parallel --clean-clone`.
The full clean-clone run records failures in the originating worktree.
`--last-failed` and `--module` require `--parallel`, are mutually exclusive,
and cannot be combined with `--clean-clone`. An absent, empty, or entirely
obsolete failure record runs no tests and exits with status 2.
