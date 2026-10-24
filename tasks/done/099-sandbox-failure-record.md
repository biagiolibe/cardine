# Task 099 — Keep the test failure record writable in the sandbox

> **ID**: `099`
> **Category**: Bugfix
> **Priority**: 🔴 P1
> **Estimate**: ~1h
> **Assigned to**: unassigned
> **Session**: Coordinator, 2026-10-24
> **Origin**: maintenance

## Objective

Task 097 stores the record of failed tests in the worktree's Git directory
(`git rev-parse --absolute-git-dir`, `scripts/run_tests.py`). For a linked
task worktree that directory is `.git/worktrees/<name>/` inside the primary
checkout, which the ordinary host sandbox does not let an agent write.
`write_failures` does not handle the error, so a full `--parallel` run in a
task worktree runs the whole suite and then ends with a `PermissionError`. A
`--clean-clone` run writes the record into its originating worktree too, so
the counted validation of every task fails in the sandbox. Tasks 097 and 098
passed it only with an approved elevated run.

A development aid must never make validation fail or require more permissions
than the suite itself.

## Acceptance Criteria

- [x] The failure record lives in the system temporary directory
  (`tempfile.gettempdir()`), in a Cardine-named subdirectory, in a file
  whose name is derived from the resolved absolute path of the worktree's
  top level. Two worktrees, including a primary checkout and a linked
  worktree of the same repository, never share a record. A `--clean-clone`
  run keys its record by the worktree it was started from. No file under
  the repository or its Git directory is written.
- [x] Failing to read or write the record never changes a run's outcome. A
  full or clean-clone run whose record cannot be written prints one
  warning line naming the path and the error, says that `--last-failed` is
  unavailable for this run, and exits with the code that the tests
  determined. A `--last-failed` run whose record cannot be read behaves as
  a missing record: it runs no tests, exits with code 2, and prints the
  full-run command.
- [x] `tests/test_run_tests.py` proves both behaviours: a record path that
  cannot be written keeps exit code 0 for a passing suite and 1 for a
  failing one, and separate worktrees of one repository keep separate
  records in the temporary directory. The existing tests for sorting,
  shrinking, clearing, obsolete IDs, and refused combinations still pass.
- [x] The runner documentation in `docs/HOST_CAPABILITY_CONTRACT.md` and
  `docs/SINGLE_WORKFLOW_PLAN.md` says where the record lives and that a
  write failure is only a warning.
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
- [x] `.meridian/` is unchanged, except `.meridian/tasks/099.json`, which only
  the installed `meridian task close 099` writes.
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
| `scripts/run_tests.py` | `failure_record`, `write_failures`, and the clean-clone handoff of the record path. |
| `tests/test_run_tests.py` | Runner tests, including the two-worktree record test. |
| `docs/HOST_CAPABILITY_CONTRACT.md`, `docs/SINGLE_WORKFLOW_PLAN.md` | Runner documentation. |

## Technical Context

- Found by the coordinator in the handoffs of tasks 097 and 098 on 2026-10-24:
  both report that the ordinary sandbox could not write the record and that
  validation needed approved elevated access.
- The sandbox already allows the runner's temporary shard directory
  (`tempfile.mkdtemp`), so the system temporary directory is writable wherever
  the suite runs.
- This task must pass its own counted validation in the ordinary sandbox,
  without elevated access. If the clean-clone run still needs elevated access,
  the task is not done.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Any other runner behaviour; the shard layout; host permission files; product
code.

## Dependencies

- **Depends on**: 098
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
