# Task 081 — Allow every task record in the identifier guard by pattern

> **ID**: `081`
> **Category**: Test
> **Priority**: 🔴 P1
> **Estimate**: ~30m
> **Assigned to**: unassigned
> **Session**: Coordinator finding, 2026-10-22
> **Origin**: maintenance

## Objective

`tests/test_no_meridian_identifiers.py` exempts this repository's task records
from the retired-identifier scan by listing each open record by name in the
"kept: historical records" allowance. Every new record written by the
coordinator makes `main` fail until a task adds its name, and two tasks that
add names at the same time conflict on the same line. This happened between
tasks 069 and 077 and stopped 069 with `INTEGRATION_CONFLICT`.

Task records quote the installed Meridian by necessity until work item 10:
their Validation commands and the frozen surfaces name it. Replace the list of
names with one pattern for task records, so that writing or archiving a record
never touches the guard.

## Acceptance Criteria

- [ ] The "kept: historical records" allowance matches every task record under
  `tasks/` by the pattern `tasks/[0-9]{3}-[^/]+\.md`, in place of the list
  of record names. The other paths of that allowance (`tasks/done/`,
  `tasks/handoffs/`, the queue files, the blueprint, `PROJECT_PLAN.md`,
  and the rest) stay unchanged.
- [ ] A test proves that a new record file `tasks/<NNN>-<slug>.md` containing
  the retired identifier passes the guard without editing it, and that a
  file elsewhere under `tasks/` that does not match the pattern still
  fails.
- [ ] The guard still fails on the retired identifier in product code,
  templates, and tests outside their existing allowances; no other
  allowance changes.
- [ ] The allowance's removal label states that it is removed or narrowed by
  work item 10, when this repository moves to Cardine and its records stop
  naming the installed Meridian.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes this test file only.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/081.json`, which only
  the installed `meridian task close 081` writes.
- [ ] A test expectation that this task makes stale is updated in this task
  without weakening any other assertion. The parallel suite reports the
  same coverage `total` before and after the task, except for new or
  deliberately removed tests, which the handoff lists with their reason.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `tests/test_no_meridian_identifiers.py` | The guard and its allowlist. |
| `docs/ADR_CARDINE_1_0.md` | Work item 10: the move of this repository to Cardine. |

## Technical Context

- It can start now: task 069 no longer changes this file, so the two cannot
  conflict.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Other allowances of the guard, and every other file.

## Dependencies

- **Depends on**: —
- **Blocks**: —

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
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
