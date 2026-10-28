# Task 137 — Restore the run engine fixtures in place instead of rebuilding them

> **ID**: `137`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Coordinator test suite analysis, 2026-10-28
> **Origin**: maintenance

## Objective

The run engine tests are 23 percent of the suite's tests and 65 percent of its
time (coordinator measurement on 2026-10-28, module sum 4737 of 7342 s).
Inside them most of the time is rebuilding the fixture: `setUp` takes 71 of
130 s in `test_all_delivery_boundaries_converge_once_and_keep_original_source`
and almost all of
`test_every_host_and_receipt_boundary_restarts_same_session`, which runs it
136 times.

The fixtures form a chain: `RunPreparationTest.setUp` in
`tests/test_run_preparation.py` builds the repository, the frozen contract,
and the prepared worktree, and `RunDeliveryTest.setUp` in
`tests/test_run_delivery.py` adds `execution start` and an implementation
commit; the host roles, review, validation, console, and control modules build
on them, and handoff builds on validation. Task 098 copied a repository before
`prepare` to another directory and gained little, because `prepare` and the
receipts stayed per test, and a prepared state cannot move: worktrees register
absolute paths and receipts bind the root's identity (decision 14).

This task builds each of the two base fixtures once per process at a stable
path, keeps a copy, and restores that copy into the same path for every case,
so paths, worktree registrations, and receipt identity stay exactly as a fresh
build would make them.

## Acceptance Criteria

- [x] **Before.** Before any change, the handoff records the wall time of each
  of `test_run_preparation`, `test_run_delivery`, `test_run_host_roles`,
  `test_run_review`, `test_run_validation`, `test_run_handoff`,
  `test_run_console`, `test_run_control` with `python3
  scripts/run_tests.py --parallel --module <module>`, the `setUp` share of
  the two tests named above, and one full parallel run, all on the same
  machine.
- [x] **Restore in place.** `RunPreparationTest` and `RunDeliveryTest` build
  their fixture once per process in a directory that process owns, keep a
  copy, and for every case remove the directory and restore the copy into
  the same absolute path. Environment variables, the working directory,
  and anything a case adds stay per case. Parallel shards never share a
  fixture directory, and the directory and its copy are removed when the
  process's tests finish.
- [x] **Equivalence.** A test in a new module proves, for both fixtures, that
  a restored fixture is byte-identical to the state it was copied from,
  that `git worktree list`, the refs, HEAD, and the index match it, that
  `verify_receipts` accepts the restored task state, and that a case which
  changes the restored fixture leaves the next restore unchanged. If
  restoring ever diverges, this test fails.
- [x] **Nothing weakened.** No test is removed, renamed, or skipped, and every
  assertion stays. A dependent module whose cases need a fixture that
  differs from the base keeps building its own; the handoff names it.
- [x] **After.** The handoff records the same measurements after the change
  and the gain per module and for the full run.
- [x] The subprocess ceilings of `tests/test_command_context.py` still hold.
- [x] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes tests and test helpers only.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/137.json`, which only
  the installed `meridian task close 137` writes.
- [x] A test expectation that this task makes stale is updated in this task
  without weakening any other assertion. The parallel suite reports the
  same coverage `total` before and after the task, except for new or
  deliberately removed tests, which the handoff lists with their reason.
- [x] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| new `tests/fixture_restore_support.py` | The build-once, restore-in-place helper. |
| new `tests/test_fixture_restore.py` | The equivalence test. |
| `tests/test_run_preparation.py`, `tests/test_run_delivery.py` | The two base fixtures. |
| `tests/test_run_host_roles.py`, `tests/test_run_review.py`, `tests/test_run_validation.py`, `tests/test_run_console.py`, `tests/test_run_control.py`, `tests/control_support.py` | Dependents, edited only if a case relies on rebuilding the fixture. |

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

- Coordinator measurement, 2026-10-28, eight modules at a time: run engine
  4737 s with 423 tests; lifecycle core 1364 s; console, status, and briefing
  790 s; legacy, upgrade, and release 258 s; templates, guards, and tooling 99
  s; hosts and CLI 63 s; total 7342 s for 1819 tests.
- Tasks 133 (H5a) and 135 (H5c) of work item 9 edit
  `tests/test_run_host_roles.py`, so they depend on this task. Rows H1 to H4
  do not touch these files, and this task can run in parallel with them.
- Task 117 already removed the generic receipt-writer cases from the matrices;
  this task does not change which cases run.
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

Changing which cases or boundaries run; product code; modules whose fixtures
do not build on these two (for example `tests/test_run_integration.py`,
`tests/test_run_cleanup.py`, `tests/test_run_ci.py`); shard scheduling;
selecting a subset of tests per task.

## Dependencies

- **Depends on**: 117
- **Blocks**: 133, 135

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
