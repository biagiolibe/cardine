# Task 028 — Accept a dirty worktree in `worktree check` during an explicit Resume

> **ID**: `028`
> **Category**: Bugfix
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Task 021 Resume stop, 2026-10-18
> **Origin**: friction

## Objective

Stop printing `BLOCKED` for a state that the workflow allows. A stop must
mean that a gate failed and that the agent must not continue.

`PROJECT_WORKFLOW.md` says that after `meridian worktree prepare <task-id>
--resume` returns `dirty: true`, `dirty-worktree` is the only error that
`worktree check` may report, and the agent continues after reading the status
and the diff. `worktree check` still exits 2 with `BLOCKED WRONG_WORKTREE`
in that case, and its resume command is `worktree prepare` without
`--resume`, which refuses the dirty worktree. `CLAUDE.md` and `AGENTS.md`
treat every `BLOCKED` line as a valid stop. So every Resume of an interrupted
task with uncommitted work stops, whatever the agent does.

In 22 tasks, this repository's journal records five command stops. Three of
them are this case: tasks 009, 019, and 021, each a `prepare --resume` with
`inspect-dirty` followed by a blocked `check`. The agents on 009 and 019
continued past the stop, and the agent on 021 stopped.

## Acceptance Criteria

- [ ] `meridian worktree check <task-id> --resume` exits 0 and prints no
  `BLOCKED` line when `dirty-worktree` is the only error. Its report says
  `status: ready-dirty`, `next_action: inspect-dirty`, and the changed and
  untracked path counts. It writes nothing.
- [ ] With `--resume`, any other error, alone or together with
  `dirty-worktree`, still stops with `BLOCKED WRONG_WORKTREE`.
- [ ] Without `--resume`, a dirty worktree still stops, as today, so a fresh
  start never runs on top of unexplained changes. Its resume command names
  `prepare --resume`, the command that accepts a dirty worktree, instead of a
  `prepare` that refuses it.
- [ ] `prepare --resume` with `dirty: true` returns the exact next command,
  `meridian worktree check <task-id> --resume --project <primary-checkout>
  --format json`, run from the task worktree.
- [ ] `execution start --resume` keeps accepting the same state; a test runs
  the whole dirty Resume, `prepare --resume`, `check --resume`, and
  `execution start --resume`, with exit 0 at every step and no `BLOCKED`
  line.
- [ ] A regression test covers clean and dirty Resume states: the lifecycle
  commands exit 0 in both cases, independently of managed template text.
- [ ] `tests/test_task_worktree_isolation.py`
  (`test_resume_accepts_a_dirty_worktree_and_changes_nothing`) keeps its
  assertions for `inspect_task_worktree` without `--resume`, and adds the
  `--resume` case.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `src/cardine/worktree/checkout.py` | `prepare_task_worktree` (`--resume` result) and `inspect_task_worktree`. |
| `scripts/meridian.py` | `worktree check` parser and handler, which turns any error into `BLOCKED`. |
| `src/cardine/lifecycle/execution.py` | `_execution_worktree`, which already accepts `dirty-worktree` on `--resume`. |
| `tests/test_task_worktree_isolation.py`, `tests/test_execution_boundaries.py` | Resume tests. |

## Technical Context

- **Current behavior**: the `worktree check` handler raises `stop_error`
  whenever `inspect_task_worktree` is not ready, with no Resume case.
  `prepare --resume` returns `next_action: inspect-dirty` and no next command.
- **Desired behavior**: only a failed gate prints `BLOCKED`. A state that the
  workflow allows returns exit 0 with the next step.
- Journal lines for the three stops: task 009 at 2026-10-17T20:13:29Z, task
  019 at 2026-10-17T23:25:47Z, and task 021 at 2026-10-18T10:16:56Z.

## Out of scope

Developer-approved scope change, 2026-10-18: managed Resume text, capability
versions, migration policy, and application to this repository are deferred to
task 029. This task changes CLI behavior and its tests only; it does not run
upgrade on this repository or change its managed manifest, release metadata,
or template files.

The `cardine run` engine (work item 8), which replaces these single-step
commands. Moving the `worktree check` handler to `cardine.cli` (task 022).

## Dependencies

- **Depends on**: 021
- **Blocks**: 022

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
