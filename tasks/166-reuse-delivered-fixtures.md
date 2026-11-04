# Task 166 — Reuse the prepared state in the integration and cleanup tests

> **ID**: `166`
> **Category**: Refactor
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Test suite cost records, 2026-11-04
> **Origin**: maintenance

## Objective

`tests/test_run_cleanup.py` repeats prepare, stage, candidate validation, and
finalize in `setUp` for each of its 22 tests, and its matrices repeat them per
boundary. Build each prepared state once per process and restore it, with the
existing `ReadySnapshot`, so that each test still starts from an identical tree
and runs the same assertions.

## Acceptance Criteria

- [ ] In `tests/test_run_cleanup.py`, `setUp` builds the finalized state once and
  later tests restore it. Coordinator prototype: processes for the module went from
  18,268 to 8,692, child CPU from 437 s to 240 s, with all 22 tests passing.
- [ ] `tests/test_run_integration.py` reuses a prepared state in its boundary matrices:
  `test_finalize_every_effect_boundary_returns_the_same_commit` (544 s measured) and
  `test_candidate_result_boundaries_replay_once` (320 s), and in `ready()` when
  `command` is `None`. `tests/test_run_ci.py` does the same if its `setUp` repeats
  the same preparation.
- [ ] No test or subtest is removed, and no assertion changes meaning. The coverage
  `total` is unchanged. Each subtest of a matrix still starts from a restored tree.
- [ ] Modules pass in both orders within one process (each of the edited modules first
  and last), so that no state leaks between tests. The handoff gives process counts
  and child CPU before and after for each edited module, measured the same way.
- [ ] Only the files under Relevant Files are edited, together with this
  task's own record and its archive, handoff, and state file. A test file
  outside that list may change only to update an expectation that this change
  made stale, without new behavior, and the handoff lists it. Any other file,
  or new behavior beyond this record, stops the task before editing it and
  names the file.
- [ ] Every test runs against disposable projects and disposable home
  directories. No step runs `setup --apply` against the real home directory or
  writes real host configuration.
- [ ] The subprocess ceilings of `tests/test_command_context.py` still hold.
- [ ] Every source and test file stays below 1,500 lines.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/166.json`, which only
  the installed `meridian task close 166` writes.
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
| `tests/test_run_cleanup.py`, `tests/test_run_integration.py`, `tests/test_run_ci.py`, `tests/fixture_restore_support.py`, `tests/test_fixture_restore.py` | The files this task edits. |

## Technical Context

- `ReadySnapshot` must restore to the same absolute path, because worktrees and
  receipts bind it. `test_run_cleanup.py` already uses it in one matrix: follow that.
- The prototype in `CleanupTest.setUp`, after `super().setUp()` and `self.origin`:
  keep a class attribute holding `(ReadySnapshot(self.root), dict(worker=..., landed=...))`;
  when set, call `snapshot.restore()`, `os.chdir(self.primary)`, copy the fields onto
  `self`, recompute `self.locations`, and return. Otherwise build as today, then set it
  and `os.chdir(self.primary)`.
- A snapshot lives as long as the process. Close it at process exit, not per test.
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
- Other tasks share this machine. Stop only your own processes, by process ID;
  never `pkill` test runs by pattern.
- Coordinator measurements of 2026-11-04, on a machine shared with other suites:
  the module weights sum to about 3 hours, so 8 workers cannot finish in under
  24 minutes. Almost all of it is waiting on Git and Python subprocesses.

## Out of scope

Reducing what the counted validation runs, skipping tests, marking tests as
optional, and any change to the coverage `total` that the handoff cannot
justify. Other rows of the queue.

## Dependencies

- **Depends on**: none
- **Blocks**: 170

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
