# Task 026 — Verify the completed module split (split plan V01)

> **ID**: `026`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-18
> **Origin**: maintenance

## Objective

Close work item 3 of `docs/ADR_CARDINE_1_0.md` with row V01 of
`docs/MODULE_SPLIT_PLAN.md`: prove the completion gate of the plan and remove
what the transition left behind.

## Acceptance Criteria

- [x] The plan's "Completion gate" holds: all 506 baseline bindings and the
  imported helper modules have owners, both launchers work, every affected mock
  keeps its expected calls and non-calls, and every text reader scans the new
  implementation.
- [x] The line-budget test covers every tracked Python file in `src/`,
  `scripts/`, and `tests/`, not only new ones, and no file exceeds 1,500 lines.
- [x] The adapters in `scripts/` hold no implementation. The plan's path
  reference inventory is repeated with `git ls-files` and a search for
  `scripts/meridian.py` and `meridian.py`, and every remaining reference is
  either correct or historical.
- [x] `docs/MODULE_SPLIT_PLAN.md` records that work item 3 is complete, with
  the final module and file counts.
- [x] The inventory tests in `tests/test_module_inventory.py` pass: exactly
  one definition per baseline binding, no import cycle under `src/cardine/`,
  and no tracked Python file under `src/cardine/` or new test file over 1,500
  lines.
- [x] The parallel suite reports the same coverage `total` before and after
  the task, except for new tests. The handoff lists only the test IDs that
  changed, with their old and new IDs.
- [x] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task
  worktree and record its result line in the handoff. No task branch push or
  CI evidence is required.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `tests/test_module_inventory.py` | Line-budget scope. |
| `scripts/` | Adapters. |

## Technical Context

- Tasks 019 to 025 finish the moves; this task changes behavior nowhere and adds no new module.

## Out of scope

Work items 4 and 5.

## Dependencies

- **Depends on**: 025
- **Blocks**: work item 4

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/run_tests.py --parallel --clean-clone`
