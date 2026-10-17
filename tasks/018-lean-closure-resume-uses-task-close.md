# Task 018 — Resume a Lean closure without state through `task close`

> **ID**: `018`
> **Category**: Bugfix
> **Priority**: 🟡 P2
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Task 015 closure stop, 2026-10-18
> **Origin**: friction

## Objective

Make `meridian worktree advance` print a runnable, workflow-correct resume when
a Lean task reaches closure step C6 without its tracked state file. Task 015
committed its completion records but skipped `meridian task close 015`.
`advance` then stopped with `BLOCKED TASK_STATE_MISSING` and the resume
`meridian task transition 015 DONE --project <task-worktree>`.

That resume leads away from the documented Lean closure in
`PROJECT_WORKFLOW.md`, where `meridian task close` writes DONE state and
stages the exact record archive together with the state file. A plain
transition writes DONE state, leaves the record unarchived and nothing
staged, and afterwards `task close` refuses the task as already DONE. ADR
decision 6 requires that the lifecycle returns only commands that run
unchanged and lead to the next step.

## Acceptance Criteria

- [ ] For a Lean task whose record is not archived and whose state file is
  missing at the task commit, `advance` stops at C6 with
  `TASK_STATE_MISSING`. Its `commands` and `resume` name, in order:
  `meridian task close <TASK-ID>` run in the registered task worktree, a
  commit of the staged closure records, and the same `advance` command again.
  Each command runs unchanged from the location it names.
- [ ] Following those commands in a test fixture brings the task to the
  next closure step (stage), with the record archived under `tasks/done/` and
  the DONE state tracked at the task commit.
- [ ] When the record is already archived but the state file is missing, the
  stop names that state and a resume that does not call `task close`, which
  refuses archived records. The handoff states the chosen recovery.
- [ ] Governed SDD keeps its current resume for this stop.
- [ ] The registry entry for `TASK_STATE_MISSING` in
  `capabilities/stop-codes-v1.json` and its summary describe the Lean
  closure resume. The stop-code checks in `scripts/check_repository.py` pass.
- [ ] `tests/test_task_integration_state.py`
  (`test_advance_state_gate_runs_before_stage`) asserts the new Lean resume
  instead of `meridian task transition 056 DONE`. Its other assertions stay:
  no stage call, no tree change in either checkout, no merge head.
- [ ] The fix stays inside existing function bodies, so the module inventory
  tests stay green.
- [ ] **CI before integration.** Push the task branch once (`git push origin
  task-018`, authorized by `Proceed with`) as soon as the implementation
  commit passes `python3 scripts/run_tests.py --parallel`, and write the
  handoff while CI runs. Then record `T1_CI` evidence for that exact commit
  with `python3 scripts/ci_evidence.py --commit <sha> --task 018 --output
  <path> --wait 900`. Integrate only when that evidence reports a successful
  run on both operating systems.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `scripts/meridian.py` (`advance_task_closure`, step C6) | Builds the Lean resume for a missing state. |
| `src/cardine/stops/render.py` (`_task_state_recovery_project`, `stop_resume`) | Resolves the task worktree for the resume. |
| `capabilities/stop-codes-v1.json` | Registry entry for `TASK_STATE_MISSING`. |
| `tests/test_task_integration_state.py` | C6 state-gate tests. |
| `PROJECT_WORKFLOW.md` | The documented Lean closure: `task close`, commit, `advance`. |

## Technical Context

- **Current behavior**: in step C6, `advance_task_closure` catches
  `TASK_STATE_MISSING` and, for `lean-delivery`, replaces the registry resume
  with `meridian task transition {task} DONE --project <task-worktree>`.
  Meridian task 218 added this on 2026-10-15 (commit `9cf3a90`). `task close`
  was added the same day (commit `57ea277`), and the C6 resume was never
  switched to it.
- `close_task` must run in the task worktree, refuses an archived record,
  requires a committed handoff, and refuses a task whose state is already
  DONE.
- The journal of this repository shows the stop once, for task 015
  (`advance`, step C6, 2026-10-17T22:16:30Z). Tasks 012 to 014 ran
  `task close` and passed C6.
- **Desired behavior**: the printed resume is the documented closure, so an
  agent that follows it ends with the record archived and the state tracked.

## Out of scope

The `cardine run` engine (work item 8), which replaces this closure sequence.
Moving `advance_task_closure` to `cardine.lifecycle.closure` (split row E12).

## Dependencies

- **Depends on**: 016
- **Blocks**: none

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/ci_evidence.py --commit <task commit> --task 018 --output <path> --wait 900`
