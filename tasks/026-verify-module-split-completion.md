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

- [ ] The plan's "Completion gate" holds: all 506 baseline bindings and the
  imported helper modules have owners, both launchers work, every affected mock
  keeps its expected calls and non-calls, and every text reader scans the new
  implementation.
- [ ] The line-budget test covers every tracked Python file in `src/`,
  `scripts/`, and `tests/`, not only new ones, and no file exceeds 1,500 lines.
- [ ] The adapters in `scripts/` hold no implementation. The plan's path
  reference inventory is repeated with `git ls-files` and a search for
  `scripts/meridian.py` and `meridian.py`, and every remaining reference is
  either correct or historical.
- [ ] `docs/MODULE_SPLIT_PLAN.md` records that work item 3 is complete, with
  the final module and file counts.
- [ ] The inventory tests in `tests/test_module_inventory.py` pass: exactly
  one definition per baseline binding, no import cycle under `src/cardine/`,
  and no tracked Python file under `src/cardine/` or new test file over 1,500
  lines.
- [ ] The parallel suite reports the same coverage `total` before and after
  the task, except for new tests. The handoff lists only the test IDs that
  changed, with their old and new IDs.
- [ ] **CI before integration.** Push the task branch once (`git push origin
  task-026`, authorized by `Proceed with`) as soon as the implementation
  commit passes `python3 scripts/run_tests.py --parallel`, and write the
  handoff while CI runs. Then record `T1_CI` evidence for that exact commit
  with `python3 scripts/ci_evidence.py --commit <sha> --task 026 --output
  <path> --wait 900`. Integrate only when that evidence reports a successful
  run on both operating systems. If CI fails, fix the failure on the task
  branch; do not integrate.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `tests/test_module_inventory.py` | Line-budget scope. |
| `scripts/` | Adapters. |
| `scripts/ci_evidence.py` | `T1_CI` evidence for the task commit. |

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
- `python3 scripts/ci_evidence.py --commit <task commit> --task 026 --output <path> --wait 900`
