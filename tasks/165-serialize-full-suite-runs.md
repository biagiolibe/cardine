# Task 165 — Run one full test suite at a time on a machine

> **ID**: `165`
> **Category**: Refactor
> **Priority**: 🟡 P2
> **Estimate**: ~1h
> **Assigned to**: unassigned
> **Session**: Test suite cost records, 2026-11-04
> **Origin**: maintenance

## Objective

Concurrent full suites each start 8 workers on a 10-core machine, and nothing
coordinates them. The load reached 160 and a single run did not finish in 34
minutes. Make a full run wait for the one already running. A waiting run must say
so, and a killed run must release its place.

## Acceptance Criteria

- [ ] A full run (`--parallel` without `--module` or `--last-failed`, on the
  repository's own tests directory, and `--parallel --clean-clone`) holds an
  exclusive `fcntl.flock` on a fixed per-user file under `/tmp`, from before its
  first shard until its report is printed. Targeted runs take no lock.
- [ ] The clean-clone run's inner `--parallel` run does not wait for its own parent.
  The parent passes this through an environment variable, which also keeps
  `tests/test_run_tests.py` from waiting when the suite runs it.
- [ ] A waiting run prints one line saying that it waits for another full suite,
  before it waits. If the lock file cannot be opened, the run prints one line and
  continues: the lock never makes a validation fail.
- [ ] Tests prove, with real processes and a private lock path: a second run waits
  until the first ends; killing the holder with `SIGKILL` releases the lock; a
  shard process does not keep the lock alive after its parent dies; a targeted run
  does not wait; the inner clean-clone run does not wait.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/165.json`, which only
  the installed `meridian task close 165` writes.
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
| `scripts/run_tests.py`, `tests/test_run_tests.py`, `CONTRIBUTING.md` (one line, only if it describes running the suite) | The files this task edits. |

## Technical Context

- Shard processes must not inherit the lock descriptor. `subprocess` closes
  descriptors by default; do not pass the descriptor on.
- `/tmp` is chosen over the home directory and `tempfile.gettempdir()` because
  sandboxed agents can write there and all of them see the same path.
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
