# Task 021 — Extract console state, render, and entry, and split the console tests (split plan C02)

> **ID**: `021`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-18
> **Origin**: maintenance

## Objective

Continue work item 3 of `docs/ADR_CARDINE_1_0.md` with row C02 of
`docs/MODULE_SPLIT_PLAN.md`. Finish the split of `scripts/project_console.py`
into `cardine.console`, and split `tests/test_project_console.py` (2,512
lines) as the plan's size budget describes.

## Acceptance Criteria

- [ ] `src/cardine/console/state.py`, `render.py`, and `entry.py` exist, with
  the code that the plan assigns to them. `scripts/project_console.py` becomes a
  thin adapter that runs `cardine.console.entry.main`.
- [ ] `tests/test_project_console.py` is replaced by the files the plan lists:
  `test_console_launch`, `test_console_render`, `test_console_snapshot`,
  `test_console_states`, `test_console_closure`, and `test_console_refresh`.
  `RepoCase` and reusable fixtures move to a support module that discovery does
  not collect. Each file is at most 1,500 lines.
- [ ] The console launch mock moves from `project_console.main` to
  `cardine.console.entry.main`, and subprocess coverage of the legacy adapter
  stays.
- [ ] No test is lost or run twice: the parallel suite reports the same
  coverage `total` before and after the task, and the handoff maps every moved
  test ID from its old to its new location. No module re-imports `TestCase`
  classes into discovery, and shared fixtures hold no inherited `test_*`
  method.
- [ ] Tests keep their bodies: only imports, class placement, shared fixture
  bases, and registered test IDs (for example in
  `capabilities/stop-codes-v1.json`) change. No assertion is removed or
  weakened, and no platform skip changes.
- [ ] The inventory tests in `tests/test_module_inventory.py` pass: exactly
  one definition per baseline binding, no import cycle under `src/cardine/`,
  and no tracked Python file under `src/cardine/` or new test file over 1,500
  lines.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task
  worktree and record its result line in the handoff. No task branch push or
  CI evidence is required.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `scripts/project_console.py` | Becomes an adapter. |
| `src/cardine/console/` | New modules. |
| `tests/test_project_console.py` | Split into six files. |
| `tests/test_module_inventory.py`, `tests/fixtures/module_split_baseline.json` | Inventory checks. |

## Technical Context

- Tasks 004 to 016 show the pattern: owner modules, explicit imports in the monolith, thin adapters, unchanged bodies, and a handoff that records the patch review and changed test IDs by exception.
- Focused proof, from the plan: existing render, closure, refresh, and AppleScript tests; keep platform skips and inherited test counts.
- `AgentLaunchTest.test_split_payload_compiles_as_applescript` is skipped in agent sandboxes; record it under `Validation skips:` as earlier tasks did.

## Out of scope

Other plan rows. Any behavior change, removal (work item 4), or rename
(work item 5). If the task cannot fit its 3-hour bound, stop and split it at a
module or test-class boundary, as the plan requires.

## Dependencies

- **Depends on**: 020
- **Blocks**: 022

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/run_tests.py --parallel --clean-clone`
