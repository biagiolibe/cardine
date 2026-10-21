# Single source of task state — work item 7

## Scope and authority

This plan implements decision 4 and work item 7 of
`docs/ADR_CARDINE_1_0.md`, preserving the machine-state guarantees of
`docs/ADR_MACHINE_TASK_STATE.md` and the vocabulary and dependency semantics
of sections 3 and 8 of `docs/SINGLE_WORKFLOW_PLAN.md`. It plans product work,
not conversion of this repository. The inventory below is against main
`9e1c3255fa326974d4367aa7718a909b73e35d33`, after task 061.

Only `.cardine/tasks/<TASK-ID>.json` determines status, transitions, review
attempts and commit-bound verdicts. Records describe work; worktrees describe
where work happens. Neither is a fallback state authority. Missing, invalid
or ambiguous state yields a diagnostic and prevents starting the affected
task; it never silently means queued. Preserve the existing schema validation,
atomic CLI writes, transition rules and exact-commit review checks.

## Duplicates to remove

These are product paths on the named main commit, not instructions to edit
the repository's own Meridian-managed records.

| Duplicate or inference | Current files and action |
| --- | --- |
| Record `Status:` | `templates/single/tasks/TASK_BLUEPRINT.md` supplies it; `src/cardine/tasks/transitions.py` writes it and `src/cardine/integration/merge.py` rewrites it to done. Remove those product fields and writes. |
| Record/queue agreement as a gate | `src/cardine/tasks/preflight.py` reads record status and compares queue rows; reconciliation also reads record status. Read validated state instead; dependencies must not be satisfied by prose. |
| Queue and plan completion | `src/cardine/integration/merge.py` calls `_apply_task_completion_rows`, stages the queue, plan and queue archive during `integrate stage`; `src/cardine/integration/projections.py` parses and replaces status tokens, completes plan rows, archives closed sections and resolves queue states. Replace product status ownership with rendering from state; remove phase archival as lifecycle machinery. |
| Archive path as closure evidence | `src/cardine/tasks/transitions.py::close_task` moves the record to `done/`; `src/cardine/tasks/identity.py` discovers records and queue links; `src/cardine/lifecycle/commands.py`, `src/cardine/lifecycle/closure.py` and `src/cardine/worktree/closure_status.py` distinguish archived records or construct archive recovery commands. Replace path-based gates with state and existing committed handoff/evidence checks. |
| Projection drift and import | `src/cardine/tasks/audit.py` compares queue/archive and record status; `src/cardine/tasks/importer.py` reads those plus review prose for explicit import. Product audit validates authoritative states and reports stale generated output separately. Keep legacy import isolated for later conversion; never call it as missing-state recovery. |
| Queue-driven discovery and console fallback | `src/cardine/console/snapshot.py` enumerates queue/archive rows, searches moved records and falls back to prose when state is absent; `scripts/console_workflow.py` supplies queue parsing, record status and effective-state helpers. Product enumeration must begin with states. Preserve the installation reader separately as described below. |
| Human-maintained queue/plan templates | `templates/single/tasks/QUEUE.md` instructs status edits, record moves and phase archival; `templates/single/PROJECT_PLAN.md` has backlog, progress and completion lists. Replace task status with generated views; retain human proposals and narrative without authoritative status. |
| Alignment script | `scripts/align_queue.py` resolves the declared queue and rewrites usage/closure ownership text. Remove its product mutation route and callers in favor of the renderer; preserve installation-only behavior if still required by Meridian fixtures. |
| Review display | `src/cardine/review/verdict.py` writes structured verdicts and human reports. Retain reports as explanations; no status reader may recover a verdict from report headings. `src/cardine/tasks/state.py` remains the validator and machine authority. |
| Briefing payload | `src/cardine/hosts/briefing.py` currently adds the configured preset to caller-supplied text without computing counts. Replace the product payload source with the shared status model; never parse queue rows in this adapter. Frozen copied hooks remain untouched. |

The integration evidence path declarations in
`src/cardine/integration/evidence.py` must follow the new generated surfaces;
they must not demand an archive move or hand-maintained status edit. Search
all callers of the named helpers when implementing each removal, including
templates and tests, rather than retaining a hidden prose fallback.

## Generated status contract

Add one read-only status service, proposed as `src/cardine/tasks/status.py`.
It enumerates validated state files by canonical ID, joins record metadata
(title, priority, phase and dependency IDs), and resolves the configured preset
independently of queue shape. Dependency declarations remain contract inputs,
not status cells. Each snapshot uses one resolved project root and a consistent
set of state reads; detect changing inputs and retry a bounded read or report
an incomplete snapshot rather than present mixed totals as authoritative.

`cardine status --project <root>` prints preset, totals for all five states,
then task rows containing ID, title, status, dependencies, dependency blockers
and startability. Default rows show open tasks; `--all` includes terminal
tasks. Totals always include all validated tasks, regardless of display filter
or phase. Ordering is deterministic by priority then canonical ID. Explain
invalid tasks separately and return nonzero for an incomplete snapshot.

`--format json` returns a versioned object with `version: 1`, `preset`,
`totals` (queued, in_progress, in_review, done, cancelled and total), `tasks`
and `diagnostics`. Each task contains `id`, `title`, `status`, `record`,
`dependencies`, `blocked_by`, `startable`, `phase`, and structured review
metadata including verdict and reviewed commit when present. Diagnostics
identify paths and errors; invalid states are not counted as queued. Text
and JSON use the same model and filters, with no independently computed totals.

Keep the configured queue file as a generated Markdown convenience and keep
only a clearly delimited generated task-status region in the configured plan.
The remainder of the plan is human narrative and proposals. `cardine status`
is read-only by default; `cardine status --write` atomically replaces the queue
and that plan region from the same snapshot, preserving all surrounding plan
bytes. A malformed/missing region in an existing plan is diagnosed without
overwriting narrative; new project templates contain the region. Generated
headers name the command and input digest, with no time-based churn.

The developer or agent runs `--write` for a saved view when needed; initialization
creates the empty views. Task branches need not update shared views on each
transition. Integration regenerates them once on the candidate tree after the
CLI writes the landed state and stages them with that state. An abort restores
the candidate's state and views together. Status reads, the console and hooks
never write files. A stale or manually edited view is disposable: CLI output
and gates always use JSON; audit reports drift and suggests `status --write`.
No mismatch causes state import or state repair from generated files. A write
failure does not undo an already committed transition or fabricate success;
report the stale view and the regeneration command.

No queue archive is needed for product state. Terminal tasks remain available
in `--all`, totals and generated plan status. Removing an open phase from a
view changes neither totals nor dependency results.

## Startability and totals

A task is startable exactly when its validated status is `queued` and all
declared dependencies are satisfied. A standard dependency is satisfied only
by `done`; a spike additionally requires `outcome: ANSWERED`. Approval while
in_progress, an INCONCLUSIVE spike, cancellation, an unknown ID or invalid
state does not satisfy a dependency. Diagnose cycles and missing dependencies
without making those tasks startable. Review policy controls transitions, not
a second category of startability. In_progress and in_review never start
again; resuming them is a separate consumer action.

Name the ADR regressions in `tests/test_task_status.py`:

- `test_queued_row_with_met_dependencies_and_in_progress_state_is_not_startable`.
- `test_queued_row_with_met_dependencies_and_in_review_state_is_not_startable`.
- `test_empty_queue_with_done_states_preserves_totals`.

Also test no queue file, an archived/removed phase, both presets, cancellation,
ANSWERED/INCONCLUSIVE dependencies, invalid/missing states, cycles, duplicate
IDs and identical text/JSON counts. Worktree presence or stale queued prose
must not override state.

## Creation and stable records

Implement `cardine task new <ID>` using task 053's
`src/cardine/tasks/contract.py::resolve_task_contract`. Resolve identity,
project defaults and explicit overrides once; validate the complete record
and queued state, including the immutable resolved contract snapshot, before
publishing either. Reject existing/ambiguous IDs and unsafe paths without
overwriting either file. Stage temporary files, publish under a creation lock,
and roll back the first publication if the second fails; concurrent readers
honor the lock and report/retry interrupted creation. No lifecycle operation
may proceed on a record without registered state. Recovery reports the exact
partial pair and requires the creation command's safe recovery path, never
guessing status from Markdown. Test failure at each publication boundary.

Quick tasks use the same command and schema, with a minimal record containing
objective, acceptance criteria, validation and dependencies. They inherit the
same resolved options, identity rules and lifecycle gates. This delivers the
`cardine task new` item deferred in `PROJECT_PLAN.md`; it adds no recordless
execution route.

New records keep their initial stable path under the configured task root for
their entire life, including done and cancelled. Remove `Status:` from the
blueprint; do not move a record at close or landing. `task close` verifies and
prepares closure using committed records, handoff and evidence; only verified
landing writes done. Cancellation writes authorized reason/history in state
and preserves the record. Existing product records already under `done/` may
remain there with an explicit identity mapping; their location conveys no
status. Do not rename historical records or convert this repository here.

## Consumers and the Meridian boundary

The product console consumes the shared status service, adding worktree and
closure diagnostics for display only. It may offer resume for in_progress
without calling it startable. The task-057 per-turn adapter renders preset,
totals and startable IDs from the same service, even when queue files are empty.
Work item 8's future `cardine run` consumes these structured facts and rechecks
the authoritative state/dependencies immediately before a transition. This
plan defines that interface but does not design or implement its engine.

`load_meridian_snapshot` in `src/cardine/legacy/meridian_installation.py`
currently delegates to the shared console loader under scoped state, status
and execution-assets adapters. Therefore changing that loader unconditionally
would break the repository coordinator. Preserve its current queue/archive,
record fallback and Meridian vocabulary in a separate installation snapshot
path before switching the product loader. The legacy entry point selects that
path explicitly; product commands never dispatch it based on missing state.
Shared display models may remain, but product state discovery cannot replace
installation discovery. Add tests against this repository's Meridian-shaped
fixtures, both empty and populated archives, and compare coordinator task
visibility before/after. No `.cardine/` is created in this repository.

## Ordered implementation tasks

These are planning labels, not new queue entries or permission to start work.
Every row depends explicitly on 061. Execute serially in the listed order:
shared CLI, snapshot, template and integration files must never have parallel
writers. Each task runs its named tests plus the applicable repository baseline.

| Label / estimate | Scope and files | Tests | Dependencies |
| --- | --- | --- | --- |
| SS1 / 2h | Extract the installation snapshot path without changing behavior; `src/cardine/legacy/meridian_installation.py`, `src/cardine/console/snapshot.py`, new `src/cardine/legacy/snapshot.py` | `tests/test_console_snapshot.py`, `tests/test_console_states.py`, installation fixtures in new `tests/test_status_legacy_boundary.py`; assert no writes | 061 |
| SS2 / 3h | Build state enumeration, dependency facts and text/JSON status; new `src/cardine/tasks/status.py`, `src/cardine/cli.py`, state/identity/preflight helpers as needed | New `tests/test_task_status.py`, all three named ADR regressions, invalid states, dependency and snapshot consistency cases | 061, SS1 |
| SS3 / 3h | Add atomic paired task creation and minimal quick tasks; `src/cardine/tasks/creation.py` (new), `tasks/contract.py`, `tasks/identity.py`, `src/cardine/cli.py`, blueprint | New `tests/test_task_creation.py`, `tests/test_single_workflow_contract.py`; duplicate/concurrent ID, overrides and rollback injection | 061, SS2 |
| SS4 / 3h | Add deterministic generated queue and plan region with read-only default and explicit write; new `src/cardine/tasks/status_render.py`, `src/cardine/cli.py`, queue/plan templates, `scripts/align_queue.py` and its callers | New `tests/test_status_render.py`; stale view, malformed region, narrative preservation, idempotence, failed writes, empty plan | 061, SS3 |
| SS5 / 3h | Remove product prose status gates and transition writes; `src/cardine/tasks/preflight.py`, `transitions.py`, `audit.py`, `identity.py`, `src/cardine/review/verdict.py`; isolate importer | `tests/test_machine_task_state.py`, `test_task_state_lookups.py`, `test_task_state_import.py`, new status gate tests; contradictory prose cannot alter eligibility or verdict | 061, SS4 |
| SS6 / 3h | Keep records stable through close and landing; `src/cardine/tasks/transitions.py`, `src/cardine/lifecycle/commands.py`, `closure.py`, `src/cardine/worktree/closure_status.py`, `src/cardine/integration/merge.py`, `projections.py`, `evidence.py` | `tests/test_task_integration_state.py`, `test_integration_projections.py`, `test_queue_archival_state.py`, `test_console_closure.py`; candidate generation/abort, cancellation and exact-commit review gates | 061, SS5 |
| SS7 / 3h | Switch product console and briefing to shared facts, retire remaining product prose fallbacks and document reading/regeneration; `src/cardine/console/snapshot.py`, `state.py`, `src/cardine/hosts/briefing.py`, `scripts/console_workflow.py`, single workflow/queue/plan/blueprint templates | `tests/test_console_snapshot.py`, `test_console_states.py`, `test_single_workflow_briefing.py`, `test_queue_briefing.py`, SS1 legacy fixtures; ADR cases through consumer output, static search for remaining product prose status readers | 061, SS6 |

Intermediate tasks keep existing lifecycle callers working until their
replacement lands; new services can be tested before routing all consumers to
them. SS6 removes the product projection mutation route only after SS4 supplies
its replacement. SS7 must demonstrate no product gate or consumer enumerates
tasks from a generated queue. Adapt obsolete product assertions rather than
weakening the legacy fixture contract.

## Boundaries for later work

Work items 8, 9 and 10 are not planned here. A versioned shared read model,
stable task paths and read-only status make engine and host consumption easier.
Requiring a shell hook to parse generated Markdown, retaining a queue fallback,
or changing JSON shape without versioning would make those items harder and
is excluded. Preserve explicit legacy reading and import isolation so item 10
can later convert records deliberately; this plan performs no conversion.
Do not rebuild host installation assets, activate hooks, change real home
configuration or run setup --apply. The frozen repository governance files,
hooks and `.meridian/` remain under installed Meridian ownership until item 10.
