# Task 025 — Split `test_task_worktree_isolation.py`

> **ID**: `025`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-18
> **Origin**: maintenance

## Objective

`tests/test_task_worktree_isolation.py` has 2,177 lines, and its
`BoundedWorktreeLifecycleTest` class has 1,406. Split it as the plan's
"Source and test size budget" section describes.

## Acceptance Criteria

- [x] `TaskWorktreeIsolationTest` moves to `test_worktree_paths`, and
  `GovernedCompletionRowsTest` to `test_integration_projections`.
- [x] `BoundedWorktreeLifecycleTest` is split by methods into
  checkout and inspection, evidence and integration, and closure and cleanup
  files, each sharing a fixture-only base in a support module that discovery
  does not collect.
- [x] `tests/test_task_worktree_isolation.py` no longer exists, and every new
  file is at most 1,500 lines.
- [x] No test is lost or run twice: the parallel suite reports the same
  coverage `total` before and after the task, and the handoff maps every moved
  test ID from its old to its new location. No module re-imports `TestCase`
  classes into discovery, and shared fixtures hold no inherited `test_*`
  method.
- [x] Tests keep their bodies: only imports, class placement, shared fixture
  bases, and registered test IDs (for example in
  `capabilities/stop-codes-v1.json`) change. No assertion is removed or
  weakened, and no platform skip changes.
- [x] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task
  worktree and record its result line in the handoff. No task branch push or
  CI evidence is required.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `tests/test_task_worktree_isolation.py` | Removed. |
| `capabilities/stop-codes-v1.json` | Registered test IDs. |

## Technical Context

- Reuse the support-module pattern of tasks 023 and 024.

## Out of scope

Any source change.

## Dependencies

- **Depends on**: 024
- **Blocks**: 026

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/run_tests.py --parallel --clean-clone`
