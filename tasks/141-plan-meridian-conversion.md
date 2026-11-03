# Task 141 — Plan the Meridian conversion and cardine adopt (work item 10)

> **ID**: `141`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 10 planning, 2026-11-03
> **Origin**: maintenance

## Objective

Write `docs/CONVERSION_PLAN.md`, the plan for work item 10 of
`docs/ADR_CARDINE_1_0.md`: rebuild `cardine adopt`, convert open tasks, the ADR
log, and the project configuration, and end by converting this repository, so
that `cardine run` delivers its remaining tasks. The plan fixes the target, the
inventory to convert or remove, and an ordered table of rows small enough to
implement one at a time; no code changes in this task.

This is the first real use of the Cardine lifecycle on this repository, and the
step that moves it from the tool that governs it to the tool under development.
The plan must therefore treat the switch itself as a design subject, not as the
last line of a list.

## Acceptance Criteria

- [ ] `docs/CONVERSION_PLAN.md` exists, in English, and contains the sections
  below.
  - **Adopt target.** The command surface of `cardine adopt` with its preview
    and apply modes, for both cases of decision 10: a project without Cardine
    and a Meridian project. What it converts (open tasks, the ADR log, default
    assurances, validation commands, task identity) and what stays in place as
    an archive that Cardine ignores (closed tasks and review records). The
    conversion runs on copies first, then on the originals.
  - **Legacy readers.** How the readers of `src/cardine/legacy/` and the move
    of `cardine task state import` (`tasks/importer.py`) and `_queue_task_rows`
    (`integration/projections.py`) serve the converter, so that the three
    documented exceptions of `tests/test_product_prose_readers.py` and entries
    T-27 and T-31 of `docs/TEXT_GATE_INVENTORY.md` reach zero. This includes
    what happens to the rule that no product module imports `cardine.legacy`
    (`docs/RENAME_PLAN.md`), which the converter necessarily changes.
  - **Inventory of this repository.** Every path that the installed Meridian
    owns today (`.meridian/manifest.json` `managedFiles` and `managedSurface`,
    the rest of `.meridian/`, the frozen host files of the Technical Context),
    every check and test that guards those paths, and
    `load_meridian_snapshot`, each with its disposition: converted, removed, or
    pointed at Cardine's own records. Counts come from the files on `main` when
    the plan is written, not from the older tables of `docs/RENAME_PLAN.md`.
  - **The switch.** The exact order in which this repository moves to
    `cardine run`: which row runs under which tool, the last task the installed
    Meridian closes, and the first task Cardine delivers. It names the state of
    `main`, CI, and the task queue at each boundary, the recovery from an
    interrupted or failed conversion, and how the repository returns to Meridian
    if the first Cardine delivery fails. It also names the steps on the
    maintainer's machine, which stay the developer's to run, and how the plan
    proves the conversion before touching the originals.
  - **Review without role launches.** `docs/HOST_CAPABILITY_CONTRACT.md` records
    role launches as `unsupported` (D3) on both hosts, and
    `concrete_host_adapter` has no caller. The plan states what
    `cardine review` and `cardine run` actually do today for a task with
    required review, verified by reading the code and running it in a
    disposable project. It then maps each field-trial case of decision 10, step
    5, to the path that can deliver it. A case with no working path is a
    finding, reported as a row or as a developer decision.
  - **Deferred items.** Each `PROJECT_PLAN.md` row targeting work item 10 quoted
    below is assigned to exactly one row of the table. Each row quoted under
    "Rows to reconcile" is checked against the code and listed as resolved, with
    the task and the proof, or as still open, with a target. The plan does not
    edit `PROJECT_PLAN.md`; the coordinator applies the outcome.
  - **Rows.** An ordered table with one line per row in the form `| C<n><a> /
    <hours>h | scope | files | tests | interruption boundaries | depends on |`.
    Each row touches at most 10 files and one or two areas; a larger row is
    split. Every effect a row performs (conversion apply, file removal, state
    write) lists its interruption boundaries for rule 4 of decision 14. Each row
    states whether it runs under Meridian or Cardine.
  - **Developer decisions.** Every choice the plan cannot settle from the ADR,
    listed as a question with its options and consequences and left undecided.
    At least: the review path while role launches stay unsupported, and whether
    conversion of the private projects is part of work item 10 or of the field
    trial of work item 13.
- [ ] Every test the plan describes runs against disposable projects and
  disposable home directories. No row applies setup to the real home directory;
  the steps on the maintainer's machine are listed for the developer.
- [ ] The plan checks its rows against `docs/RUN_ENGINE_PLAN.md`,
  `docs/HOST_INTEGRATION_PLAN.md`, `docs/HOST_CAPABILITY_CONTRACT.md`, and
  `docs/RENAME_PLAN.md` and names any conflict instead of resolving it silently.
- [ ] This task changes `docs/CONVERSION_PLAN.md` only, besides its own record,
  handoff, and state file. Any disposable project it runs stays outside the
  repository.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the checkout's
  `setup --apply` against the real home directory or creates `.cardine/` in this
  repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/141.json`, which only
  the installed `meridian task close 141` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/CONVERSION_PLAN.md` | The plan this task writes. |
| `docs/ADR_CARDINE_1_0.md` | Decisions 1, 9, 10, 11, 14 and work items 10 to 13. |
| `docs/RENAME_PLAN.md` | Frozen group 3 paths and the legacy reader. |
| `docs/HOST_CAPABILITY_CONTRACT.md`, `docs/HOST_INTEGRATION_PLAN.md` | Role launch state and D3. |
| `docs/RUN_ENGINE_PLAN.md`, `docs/RUN_COMMANDS.md` | The engine that takes over this repository. |
| `docs/TEXT_GATE_INVENTORY.md`, `tests/test_product_prose_readers.py` | The importer exceptions that must reach zero. |
| `src/cardine/legacy/`, `src/cardine/tasks/importer.py`, `src/cardine/integration/projections.py` | Readers and importer that the converter uses. |
| `src/cardine/hosts/launch.py`, `src/cardine/hosts/transports.py`, `src/cardine/lifecycle/engine.py`, `src/cardine/review/` | Today's review and launch paths. |
| `.meridian/manifest.json`, `scripts/check_repository.py`, `tests/test_no_meridian_identifiers.py`, `.github/workflows/` | What guards the Meridian-owned files today. |

## Authority excerpt

The parts of the ADR and the plan this task needs, extracted from the files on
`main` when the record was written, so that the task reads them here instead of
the whole documents:

> From `docs/ADR_CARDINE_1_0.md`, section "Work items to 0.9", item 10:
>
> 10. Meridian conversion: open tasks, ADRs, configuration. This item rebuilds
>     `cardine adopt`, which work item 4 removes together with the release
>     baselines. It ends by converting this repository with `cardine adopt`, so
>     that `cardine run` delivers its remaining tasks. That move releases the
>     files the installed Meridian owned: the checks and tests that guard them
>     are removed or pointed at Cardine's own records, and the changes deferred
>     to it, such as the old shell hooks and the managed copy of
>     `CONTEXT_BUDGET_POLICY.md`, are made. Items 11 and 12 run on Cardine.
>
> From `docs/ADR_CARDINE_1_0.md`, section "10. Transition from Meridian":
>
> 4. **Convert open work only.** `cardine adopt` converts the open tasks, the ADR
>    log, and the project configuration: default assurances, validation commands,
>    and task identity. Closed tasks and review records stay in place as an
>    archive that Cardine ignores. Conversion runs on copies first, then on the
>    originals.
> 5. **Field trial with an exit criterion.** Cardine 1.0.0 is released only when,
>    on 0.9, at least one real task of each case has landed on `main` in Contoso or
>    Fabrikam:
>    - required review with one round of requested changes;
>    - no review;
>    - a spike;
>    - `Authority` citing an ADR, with a declared code surface;
>    - a stop followed by a resume with `cardine run`.
>
>    A case that does not work as it does today becomes a task and blocks 1.0.
>
> From `docs/HOST_CAPABILITY_CONTRACT.md`, role proofs:
>
> | D3 | A host whose native policy doctor cannot show to enforce the protected paths and role actions is `unsupported` for role launches. No guarded transport adapter is built. Doctor reports `role-launch-<role>` as `ready`, `unsupported (D3): <gaps>`, `unverified: <reason>` or `approval-required: <reason>`. |
>
> From `PROJECT_PLAN.md`, rows targeting work item 10:
>
> | Rename this repository's managed copy of `CONTEXT_BUDGET_POLICY.md`; the templates are renamed by row SW5 of `docs/SINGLE_WORKFLOW_PLAN.md` | Work item 10 | `tasks/handoffs/035.md`, `docs/SINGLE_WORKFLOW_PLAN.md` |
> | Call product functions in-process in the tests that exercise logic rather than the executable; 38 tests start the CLI as a subprocess | Work item 10 | Coordinator code analysis, 2026-10-25 |
> | Import product modules directly in the 64 test modules that still go through the `scripts/cardine_cli.py` adapter, and merge the remaining duplicate helpers (`_worktrees`, `_primary_checkout`, `_read_text`, `_load_snapshot`) of the modules still marked as extracted from the legacy CLI | Work item 10 | Coordinator code analysis, 2026-10-25 |
> | Move `cardine task state import` (`tasks/importer.py`) and its queue reader `_queue_task_rows` (`integration/projections.py`, re-exported by `scripts/cardine_cli.py`) into the conversion that rebuilds `cardine adopt`, so that the three documented exceptions of `tests/test_product_prose_readers.py` and entries T-27 and T-31 of `docs/TEXT_GATE_INVENTORY.md` reach zero | Work item 10 | `tasks/handoffs/070.md`; coordinator decision, 2026-10-22 |
>
> From `PROJECT_PLAN.md`, rows to reconcile, whose target work item is closed:
>
> | A runnable recovery command for `EVIDENCE_INCOMPLETE`, proved by an end-to-end test | Work item 8 | `tasks/handoffs/030.md`, proposal 1 |
> | Split the mixed guardrail codes by cause, so that safe subcases become recoverable | Work item 8 | `tasks/handoffs/030.md`, proposal 2 |
> | Remove the budget lines from the per-turn queue briefing | Work item 9 | `tasks/handoffs/035.md` |
> | The queue briefing drops every queued task when a title contains an apostrophe (`xargs: unterminated quote`); add a regression test | Work item 9 | Coordinator finding, 2026-10-19 |
> | Add `cardine init` (decision 8), replacing the copy steps of the init slash command that task 055 rewrites | Work item 9 | Task 055 record |
> | Remove this repository's own scripts (`python3 scripts/check_repository.py`, `python3 scripts/run_tests.py --parallel`, `python3 -m unittest discover -s tests`) from the product's Claude allowlist (`src/cardine/hosts/claude.py`) and Codex rule probes (`src/cardine/hosts/setup.py`). Cardine ships rules only for its own commands, the lifecycle's Git commands, and the deny list; an adopter's test and validation commands stay in that project's own host configuration | Work item 9 | Coordinator finding, 2026-10-24 |
> | Defer the CLI's heavy imports (`http.client`, `ssl`, `email`, used only by self-update and release) to the commands that need them; startup is 110 ms against 24 ms for bare Python, and per-turn hooks pay it | Work item 9 | Coordinator code analysis, 2026-10-25 |
> | The governed skills route `Accept` to `docs/workflows/LIFECYCLE.md`, which the single template set no longer installs | Work item 9 | `tasks/handoffs/055.md` |

## Technical Context

- The row table follows the coordinator's planning rule of 2026-10-27: rows are
  sized by the files they touch, not by hours, so each implementation task stays
  small in context. The coordinator generates one task record per row and
  extracts each row's line from the table into that record.
- Findings of the status review of 2026-11-03, to be verified rather than
  assumed: `cardine adopt` is absent from the CLI; `cardine run` has not
  delivered a real task, and this repository's handoffs still use `meridian`
  commands; the `run` parser help in `src/cardine/cli.py` still says "preview
  (read-only)" while `docs/RUN_COMMANDS.md` says the command performs the step.
  The help mismatch is a candidate for a row of this plan.
- This repository runs on the installed Meridian until the switch this plan
  defines. Task 141 itself runs under Meridian.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait until
  the other integration finalizes or aborts, then rerun the same `advance`
  command.

## Out of scope

Implementing any row; the documentation of work item 11; the release script of
work item 12; running the field trial or converting the private projects;
choosing among the developer decisions the plan lists; the installation surface,
deferred after 1.0.

## Dependencies

- **Depends on**: 136
- **Blocks**: the work item 10 task records, written from the plan's row table

## Developer decisions given in advance

The developer records these decisions in the task contract, so that they
hold however the task is launched, including a bare `Proceed with <TASK-ID>`
from the project console (ADR decision 12). None of these situations needs a
new decision from the developer. After fixing a failure, continue with
revalidation in the same turn; do not stop to report the fix.

- A required command that exits non-zero because of a precondition the agent
  can satisfy (command order, an uncommitted worktree, a missing argument):
  satisfy it and run the command again, once.
- A validation failure caused by this task's own changes, including a name
  collision, a stale reference, a broken link, or a test expectation that the
  task made obsolete: fix it and revalidate, at most 3 counted attempts. A
  test that fails once and passes on an identical unchanged rerun is
  intermittent, recorded in the handoff, and does not count. Only after 3
  counted failures stop with `BLOCKED VALIDATION_FAILED` and a summary of the
  failures.
- A counted attempt is one run of the whole Validation section on a
  committed implementation that the agent considers complete. Test runs
  during implementation are development, not attempts, however many fail.
  An unfinished implementation is never a reason to stop: finish it first.
- A `BLOCKED <CODE>` from a Meridian command whose entry in
  `capabilities/stop-codes-v1.json` of the primary checkout's `main` has
  `human_decision: false`: run the command the stop names, once. If it stops
  again with the same code, stop.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope
  remain stops.

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `git diff --check`
- `python3 -m unittest tests.test_no_meridian_identifiers`

This task changes documentation only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff. It still runs the identifier guard, which scans documentation.
