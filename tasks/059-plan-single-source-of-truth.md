# Task 059 — Plan the single source of task state (work item 7)

> **ID**: `059`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work items 5b and 7 planning, 2026-10-20
> **Origin**: maintenance

## Objective

Write `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md`, the plan for work item 7 of
`docs/ADR_CARDINE_1_0.md`. Decision 4 makes `.cardine/tasks/<TASK-ID>.json`
the only source of truth for status, transitions, and verdicts. It removes the
`Status` field of the Markdown record, the move to `tasks/done/` as a status
signal, and hand-maintained queue and plan status. `cardine status` generates
the queue, and the plan's status lines are generated too. The plan fixes the
design and the task sequence before any code changes.

## Acceptance Criteria

- [ ] `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` exists, in English, and contains:
  - **Duplicates to remove.** Every place in the product where status lives
    outside the task state file today: the `Status` field of the record, the
    queue and plan rows, the archive move to `tasks/done/`, and the code that
    writes or reads them. Each entry names its files on `main`, including the
    queue and plan edits of `integrate stage`, `task close`, the queue
    projections in `cardine.integration`, and `scripts/align_queue.py`.
  - **Generated status.** What `cardine status` prints (text and JSON),
    whether the queue and the plan's status lines remain files that the CLI
    regenerates or become command output only, who regenerates them and when,
    and how a person or agent reads them. A generated file must never be a
    second authority: the plan states what happens when one differs from the
    task states.
  - **Startable tasks and totals.** The rule of ADR work item 7: a task is
    startable only when its state is `queued` and its dependencies are met;
    `in_progress` and `in_review` are never startable; totals count task
    states, not queue rows. The three regression cases of the ADR are named as
    tests.
  - **Task creation.** `cardine task new`, which creates the record and its
    state file together (decision 4 and the deferred item in
    `PROJECT_PLAN.md`), using the contract resolver of task 053. Quick tasks
    are minimal tasks created the same way.
  - **Records after landing.** Where a task record lives once it is `done` or
    `cancelled`, now that the move to `tasks/done/` no longer signals status.
  - **Consumers.** The console, the per-turn briefing adapter of task 057, and
    the `cardine run` engine of work item 8: what each reads after this work
    item.
  - **Task sequence.** An ordered list of tasks of 2–3 hours, each with its
    scope, files, tests, and dependencies. Every task depends on task 061, the
    last task of work item 5b. Two tasks that touch the same file are never
    parallel.
- [ ] The plan keeps `load_meridian_snapshot` working on this repository,
  whose queue, plan, and records stay in their Meridian form until work
  item 10. It says how, or states that the product changes do not reach
  `cardine.legacy`.
- [ ] The plan does not plan work items 8, 9, or 10, but it names any choice
  that would make them harder.
- [ ] No file changes outside `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` and this
  task's records: the task record, its handoff, and its archive under
  `tasks/done/`.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/059.json`, which only
  the installed `meridian task close 059` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/ADR_CARDINE_1_0.md` | Decision 4 and work item 7. |
| `docs/ADR_MACHINE_TASK_STATE.md` | The machine-state design that decision 4 keeps. |
| `docs/SINGLE_WORKFLOW_PLAN.md` | Sections 3 and 8: the state vocabulary and what work item 7 inherits. |
| `src/cardine/tasks/`, `src/cardine/integration/`, `src/cardine/lifecycle/closure.py`, `src/cardine/console/`, `src/cardine/hosts/briefing.py`, `scripts/align_queue.py` | Current readers and writers of status. |
| `templates/single/tasks/QUEUE.md`, `templates/single/PROJECT_PLAN.md`, `templates/single/tasks/TASK_BLUEPRINT.md` | Product templates that carry status today. |

## Technical Context

- This task only writes a document. It can run while task 058 runs, because it
  changes no product file.
- This repository's own `tasks/QUEUE.md`, `PROJECT_PLAN.md`, and `tasks/done/`
  belong to the installed Meridian lifecycle until work item 10. The plan's
  tasks change product files only.

## Out of scope

Changing any code or template. Work items 8, 9, and 10.

## Dependencies

- **Depends on**: none
- **Blocks**: the work item 7 tasks that the plan defines

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

This task changes documentation only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff.
