# Task 138 — Restore the remaining heavy fixtures in place

> **ID**: `138`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Coordinator test suite analysis, 2026-10-28
> **Origin**: maintenance

## Objective

Task 137 made the two base fixtures of the run engine restore in place: one
build per process at a stable path, a saved copy, and a restore into the same
absolute path for each case, proved equivalent by
`tests/test_fixture_restore.py`. The modules on those fixtures fell by 51 to
84 percent, but the full run fell only about 22 percent, because half of the
remaining cost is in modules with their own fixtures.

This task applies the same mechanism to `BoundedWorktreeLifecycleFixture` in
`tests/worktree_support.py`, which `tests/test_run_integration.py`,
`tests/test_run_cleanup.py`, `tests/test_run_ci.py` inherit, and to the
fixtures of `tests/test_run_recovery.py`, `tests/test_worktree_lifecycle.py`,
`tests/test_execution_boundaries.py`, `tests/test_single_workflow_parity.py`,
`tests/test_task_integration_state.py`.

## Acceptance Criteria

- [ ] **Before.** Before any change, the handoff records the wall time of each
  of `test_run_integration`, `test_run_cleanup`, `test_run_ci`,
  `test_run_recovery`, `test_worktree_lifecycle`,
  `test_execution_boundaries`, `test_single_workflow_parity`,
  `test_task_integration_state` with `python3 scripts/run_tests.py
  --parallel --module <module>`, and one full parallel run, on the same
  machine and with no other suite running on it.
- [ ] **Restore in place.** `BoundedWorktreeLifecycleFixture` and each listed
  module's fixture are built once per process in a directory that process
  owns and restored into the same absolute path for every case, with
  `tests/fixture_restore_support.py` from task 137. Environment variables,
  the working directory, and anything a case adds stay per case; parallel
  shards never share a fixture directory.
- [ ] **Equivalence.** `tests/test_fixture_restore.py` gains one case per
  newly restored fixture, with the checks task 137 established:
  byte-identical to the saved state, matching `git worktree list`, refs,
  HEAD, and index, a task state that `verify_receipts` accepts where the
  fixture writes receipts, and no leak from one case into the next
  restore.
- [ ] **Nothing weakened.** No test is removed, renamed, or skipped, and every
  assertion stays. A case that needs a fixture different from its module's
  keeps building its own, and the handoff names it. A module whose
  measured gain is under 10 percent is left unchanged and reported.
- [ ] **After.** The handoff records the same measurements after the change,
  the gain per module, and the full run.
- [ ] The subprocess ceilings of `tests/test_command_context.py` still hold.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes tests and test helpers only.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/138.json`, which only
  the installed `meridian task close 138` writes.
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
| `tests/worktree_support.py` | `BoundedWorktreeLifecycleFixture`, the base of three run engine modules. |
| `tests/fixture_restore_support.py`, `tests/test_fixture_restore.py` | The restore helper and its equivalence test from task 137. |
| `tests/test_run_recovery.py` | A module with its own fixture. |
| `tests/test_worktree_lifecycle.py` | A module with its own fixture. |
| `tests/test_execution_boundaries.py` | A module with its own fixture. |
| `tests/test_single_workflow_parity.py` | A module with its own fixture. |
| `tests/test_task_integration_state.py` | A module with its own fixture. |
| `tests/test_run_integration.py`, `tests/test_run_cleanup.py`, `tests/test_run_ci.py` | Dependents, edited only if a case relies on rebuilding. |

## Authority excerpt

The parts of the plan and inventories this task needs, extracted from the
files on `main` when the record was written, so that the task reads them here
instead of the whole documents:

> From `docs/ADR_CARDINE_1_0.md`, section "14. Robust against weak and strong agents", item 4:
>
> 4. **Every effect can be repeated.** Interrupting any command at any effect
>    boundary, such as a commit, a state write, a merge, a push, or a cleanup,
>    and running it again converges to the same result. Two tasks that reach
>    integration together wait for each other instead of stopping.
>
## Technical Context

- Task 137 results, same machine: `test_run_delivery` 261 to 41 s,
  `test_run_host_roles` 218 to 57 s, `test_run_console` 200 to 51 s,
  `test_run_control` 232 to 114 s; base `setUp` 2.23 to 0.03 s; full run 1374
  to 1071 s under load.
- `tests/test_task_integration_state.py` uses the repository template of task 098 (`tests/repository_template_support.py`), which copies only the state before `prepare`; restoring in place may replace it for that module.
- No row of work item 9 edits these files, so this task can run in parallel
  with that chain.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.
- During development, run only what the change touches: `python3
  scripts/run_tests.py --parallel --module <name>` for a module, class, or
  test, and `python3 scripts/run_tests.py --parallel --last-failed` after a
  failed full run. Both print only failures. Do not run `python3 -m unittest`
  directly, and run the full suite once, as the counted clean-clone
  validation.

## Out of scope

Changing which cases or boundaries run; product code; modules not listed;
shard scheduling; selecting a subset of tests per task.

## Dependencies

- **Depends on**: 137
- **Blocks**: none

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

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone run executes `scripts/check_repository.py` and the parallel
suite on a clone of the committed HEAD, so the task does not run them again
in the worktree as counted validation.
