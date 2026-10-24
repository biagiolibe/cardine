# Task 098 — Build heavy lifecycle test fixtures once per class

> **ID**: `098`
> **Category**: Infrastructure
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Coordinator, 2026-10-24
> **Origin**: maintenance

## Objective

Six lifecycle modules take about 1270 of the suite's roughly 2700 seconds of
test time: `test_execution_boundaries`, `test_single_workflow_parity`,
`test_task_integration_state`, `test_worktree_lifecycle`,
`test_console_snapshot`, and `test_run_recovery`. Every test in them builds
its repository from scratch in `setUp`: `git init`, Git configuration, project
configuration, frozen task records, an initial commit, and then `prepare`. No
module builds anything once per class. Measured on its own, a typical test
spends 2.2 of its 5.7 seconds in `setUp`.

This task builds the part of the fixture that is the same for every test once
per class and gives each test its own copy, without weakening any test.

## Acceptance Criteria

- [ ] Before any change, the handoff records the wall time of each of the six
  modules, run with `python3 scripts/run_tests.py --parallel --module
  <module>`, and the time of one full parallel run. It records the same
  measurements after the change, on the same machine.
- [ ] In each of the six modules, the part of the fixture that does not depend
  on the test is built once per class. That part covers the repository,
  its Git configuration, the project configuration, the frozen records,
  and the initial commit. Each test then gets its own copy in a fresh
  temporary directory, its own worktree root, and its own working
  directory, and still runs `prepare` itself. Worktrees and worktree
  registrations are never copied.
- [ ] One helper under `tests/` builds and copies the template, and its own
  test proves three things: two copies are independent, a change in one
  does not reach the other, and a copy's HEAD tree, index, and Git
  configuration equal a fresh build.
- [ ] Every test keeps every assertion. The six modules keep exactly the same
  test IDs: no test in them is added, removed, renamed, or skipped. The
  only new tests are the helper's own, which the handoff lists.
- [ ] A module whose measured gain is under 10 percent is left unchanged, and
  the handoff reports its numbers. The handoff states the total gain for
  the six modules and for the full run.
- [ ] Each template lives in the temporary space of the process that built it
  and is removed when its class finishes, so parallel shards never share a
  fixture path.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes test modules and test helpers only.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/098.json`, which only
  the installed `meridian task close 098` writes.
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
| `tests/test_execution_boundaries.py`, `tests/test_single_workflow_parity.py`, `tests/test_task_integration_state.py`, `tests/test_worktree_lifecycle.py`, `tests/test_console_snapshot.py`, `tests/test_run_recovery.py` | The six heavy modules. |
| `tests/project_config_support.py`, `tests/task_contract_support.py`, `tests/task_state_support.py` | Fixture helpers that the templates build on. |
| `scripts/run_tests.py` | The `--module` and `--list` modes used for measurement (task 097). |

## Technical Context

- Coordinator measurements from 2026-10-24 (eight modules at a time, so
  contended): `test_execution_boundaries` 350 s, `test_single_workflow_parity`
  234 s, `test_task_integration_state` 227 s, `test_worktree_lifecycle` 208 s,
  `test_console_snapshot` 181 s, `test_run_recovery` 164 s.
- Git worktrees record absolute paths in the main repository's Git directory
  and in each worktree, so a copied repository that already has registered
  worktrees points at the wrong places. Copy only the state before `prepare`.
- Tests patch environment variables such as `CARDINE_WORKTREE_ROOT` and change
  the working directory; both stay per test.
- The run engine rows that follow (RE2c onward) edit the same test files, so
  this task runs alone in the serial chain, between 097 and 091.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Changing what a test asserts; runner or shard changes; product code; modules
outside the six unless the same helper applies with a measured gain of at
least 10 percent.

## Dependencies

- **Depends on**: 097
- **Blocks**: 091

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
