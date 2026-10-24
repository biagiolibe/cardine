# Task 097 — Add focused development runs to the test runner

> **ID**: `097`
> **Category**: Infrastructure
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Coordinator, 2026-10-24
> **Origin**: maintenance

## Objective

A task runs the whole suite several times during development: a first run
finds the expectations its change made stale, often spread over 30 to 40 test
files, and every later run only checks whether the fixes worked. The suite
takes six to seven minutes, so these repeated runs, not the single counted
run, are most of a task's duration. Running one module by hand also fails:
`python3 -m unittest tests.<module>` cannot import the helpers under `tests/`.

This task lets the runner resolve what it already knows (ADR decision 14, rule
3). A full run records which tests failed, and the next run executes only
those until they pass. A named module, class, or test runs on its own without
any path setup. The counted validation stays the full clean-clone run.

## Acceptance Criteria

- [x] `python3 scripts/run_tests.py --parallel` records the sorted IDs of the
  tests that failed or errored in a file inside the current worktree's own
  Git directory (`git rev-parse --git-dir`), so two worktrees never share
  a record and nothing tracked changes. A run in which every test passes
  leaves an empty record. A `--clean-clone` run writes its record into the
  Git directory of the worktree it was started from.
- [x] `--parallel --last-failed` runs exactly the recorded IDs, sharded as a
  full run is. A recorded ID that no longer exists is named in the output
  and skipped. When the run ends, the record keeps only the tests that
  still fail.
- [x] `--parallel --module <name>` can be given more than once. `<name>` is a
  module name (`test_worktree_lifecycle`), its path
  (`tests/test_worktree_lifecycle.py`), a class, or a full test ID. The
  selection runs from any working directory, and the helpers under
  `tests/` import without any environment setup. An unknown name is
  refused with exit code 2 before any test runs, and the refusal names the
  closest existing modules.
- [x] A partial run cannot be mistaken for a full one. Its summary line starts
  with `PARTIAL` and states the selection, the number of tests run, and
  the full coverage total, for example `PARTIAL selection=last-failed
  ran=12 total=1367 failures=0 errors=0`. It never prints the full run's
  `coverage total=` line or its `OK` summary. `--clean-clone` combined
  with `--last-failed` or `--module` is refused with exit code 2, because
  a clean-clone run is always full.
- [x] The runner prints the next command itself. A failed full run ends with
  `python3 scripts/run_tests.py --parallel --last-failed`. A partial run
  in which every selected test passes ends with `python3
  scripts/run_tests.py --parallel --clean-clone`. `--last-failed` with a
  missing or empty record, or with no recorded ID left, runs nothing,
  exits with code 2, and prints the full-run command.
- [x] Full runs are unchanged: shard assignment, the shard header, the
  coverage total and digest, `--shard`, `--list`, and the clean-clone
  output stay as they are.
- [x] `tests/test_run_tests.py` covers every behaviour above, including two
  worktrees that keep separate records, a record that shrinks as tests are
  fixed, a renamed test in the record, and each refused combination.
  Documentation that lists the runner's options names the new ones.
- [x] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes `scripts/run_tests.py`, its tests, and
  documentation only.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/097.json`, which only
  the installed `meridian task close 097` writes.
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
| `scripts/run_tests.py` | Runner: discovery, sharding, parallel and clean-clone modes. |
| `tests/test_run_tests.py` | Runner tests. |
| `docs/HOST_CAPABILITY_CONTRACT.md`, `docs/SINGLE_WORKFLOW_PLAN.md` | Documents that name runner commands. |

## Technical Context

- Coordinator measurements from 2026-10-24: one full parallel run takes 395 to
  456 seconds, and the module times add up to about 2700 seconds of test time.
- A selector based on changed files or the import graph is deliberately out of
  scope. The stale expectations of a stop-code rename sit in fixtures far from
  the changed modules, and such a selector would miss them. The record of
  failed tests needs no dependency map and no judgement from the agent.
- The counted validation of every task stays `python3 scripts/run_tests.py
  --parallel --clean-clone`. Partial runs are development runs and never count
  as validation.
- Task 098 uses `--module` to measure the heavy lifecycle modules before and
  after its change.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Selecting tests from changed files or imports; faster fixtures (task 098);
shard balancing; changing host permission files; any change to the counted
validation.

## Dependencies

- **Depends on**: 090
- **Blocks**: 098

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
