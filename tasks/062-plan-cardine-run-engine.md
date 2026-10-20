# Task 062 — Plan the cardine run engine (work item 8)

> **ID**: `062`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 8 planning, 2026-10-20
> **Origin**: maintenance

## Objective

Write `docs/RUN_ENGINE_PLAN.md`, the plan for work item 8 of
`docs/ADR_CARDINE_1_0.md`. Decision 6 makes `cardine run <TASK-ID>` the only
lifecycle command an agent needs: each call reads the task state, performs the
next possible step, and prints JSON with the outcome and the next action.
Decision 12 makes the engine stop only for guardrails, by construction.
Decision 11 builds integration around a landing mode, with `direct` as the
only mode of 1.0. The plan fixes the design and the task sequence before any
code changes.

## Acceptance Criteria

- [ ] `docs/RUN_ENGINE_PLAN.md` exists, in English, and contains:
  - **Steps and next-step resolution.** The seven steps of decision 6, how the
    engine derives the next one from the task state alone, and how it resumes
    after any step or stop. Each step names the existing code it reuses:
    `cardine worktree prepare`, `check`, `advance`, `integrate stage`,
    `finalize`, `abort`, `cleanup`, `cardine execution`, `cardine review`, and
    `cardine task close`, and what becomes Internal (decision 8).
  - **Output contract.** The JSON schema of one `cardine run` call: outcome,
    the step performed, the next action as a command that runs unchanged, and
    for a stop the registered code and the resume command. Every command it
    returns runs unchanged from any directory, and the plan says how the
    engine resolves the primary checkout and the task worktree itself
    (decision 6).
  - **Stops by construction.** How each outcome maps to the three classes of
    decision 12 through the `resolution` and `human_decision` fields of the
    stop registry: only a guardrail prints `BLOCKED`; a recoverable state
    returns the next action or is resolved by the engine when the recovery is
    safe and idempotent; failing work iterates. It assigns the two deferred
    items from `tasks/handoffs/030.md` in `PROJECT_PLAN.md`: a runnable
    recovery for `EVIDENCE_INCOMPLETE`, and splitting the mixed guardrail
    codes by cause.
  - **Validation retry limit.** The attempt-bound counter in the task state
    file of decision 5: what counts as an attempt, the automatic rerun of a
    failed run and the intermittent record, the limit from the resolved
    contract of task 053, and the stop code after N counted failures. The
    agent records nothing.
  - **Review.** How `cardine run` hands a required review to `cardine review`
    and resumes after approval or requested changes, with the verdict bound to
    the reviewed commit (task 054).
  - **Integration and landing mode.** `cardine.integration` with the landing
    mode as its extension point and `direct` as its only implementation;
    candidate validation from the project configuration of task 052; the
    CI-before-landing option, with one task-branch push and check polling
    through `gh`; and the deletion of the remote task branch after landing,
    only when `main` contains its commit (decision 11). The extension point
    must let 1.1 add `pull-request` mode without a second engine.
  - **Commands.** `cardine run`, `status`, `review`, `cancel`, and `abort` as
    the Stable lifecycle surface of decision 8, and which current commands
    become Internal.
  - **Console.** How the experimental console is rebuilt on the task state and
    the engine, reading what the engine reads.
  - **Unattended runs.** How the contract's `Expected code surface` bounds the
    agent, and how work outside it becomes a scope-change stop (decision 12).
  - **Task sequence.** An ordered list of tasks of 2–3 hours, each with its
    scope, files, tests, and dependencies. Every task depends on the last task
    of work item 7, which the plan of task 059 defines. Two tasks that touch
    the same file are never parallel. The tasks prove each recoverable code
    with a test that runs the command it returns, as decision 12 requires.
- [ ] The plan follows `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` (task 059) for
  task states and generated status, and `docs/SINGLE_WORKFLOW_PLAN.md`,
  section 8, for what work item 8 inherits. Where it needs a choice those
  plans leave open, it states the choice.
- [ ] This repository keeps running its lifecycle on the installed Meridian
  until work item 10. No planned task runs `cardine run` on this
  repository or changes how its tasks are delivered.
- [ ] The plan does not plan work items 9 or 10, but it names any choice that
  would make them harder.
- [ ] No file changes outside `docs/RUN_ENGINE_PLAN.md` and this task's
  records: the task record, its handoff, and its archive under
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/062.json`, which only
  the installed `meridian task close 062` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/ADR_CARDINE_1_0.md` | Decisions 5, 6, 8, 11, and 12; work item 8. |
| `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md`, `docs/SINGLE_WORKFLOW_PLAN.md` | Inputs from work items 7 and 6. |
| `docs/ADR_STOPS_AND_DENIALS.md`, `capabilities/stop-codes-v1.json` | Stop registry and its `resolution` and `human_decision` fields. |
| `src/cardine/lifecycle/`, `src/cardine/integration/`, `src/cardine/worktree/`, `src/cardine/review/`, `src/cardine/console/`, `src/cardine/cli.py` | Current single-step lifecycle code that the engine reuses or replaces. |
| `PROJECT_PLAN.md` | Deferred items that name work item 8. |

## Technical Context

- This task starts after task 059 integrates, so its plan can rely on the work
  item 7 design. It changes no product file and can run while tasks 060 and
  061 run.
- The single-step commands on `main` today include `worktree prepare`,
  `check`, `repair-base`, `advance`, `integrate stage|finalize|abort`,
  `cleanup`, `execution`, `review`, and `task close`. The installed Meridian
  1.4.1 runs this repository's lifecycle with its own copies of them.
- Decision 12, the stop registry's `resolution` field (task 030), and the
  template rules of task 029 already describe the three classes; the engine
  applies them by construction.

## Out of scope

Changing any code or template. Work items 9 and 10, and the `pull-request`
landing mode of 1.1.

## Dependencies

- **Depends on**: 059
- **Blocks**: the work item 8 tasks that the plan defines

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
