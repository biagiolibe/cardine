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

- [ ] `TaskWorktreeIsolationTest` moves to `test_worktree_paths`, and
  `GovernedCompletionRowsTest` to `test_integration_projections`.
- [ ] `BoundedWorktreeLifecycleTest` is split by methods into
  checkout and inspection, evidence and integration, and closure and cleanup
  files, each sharing a fixture-only base in a support module that discovery
  does not collect.
- [ ] `tests/test_task_worktree_isolation.py` no longer exists, and every new
  file is at most 1,500 lines.
- [ ] No test is lost or run twice: the parallel suite reports the same
  coverage `total` before and after the task, and the handoff maps every moved
  test ID from its old to its new location. No module re-imports `TestCase`
  classes into discovery, and shared fixtures hold no inherited `test_*`
  method.
- [ ] Tests keep their bodies: only imports, class placement, shared fixture
  bases, and registered test IDs (for example in
  `capabilities/stop-codes-v1.json`) change. No assertion is removed or
  weakened, and no platform skip changes.
- [ ] **CI before integration.** Push the task branch once (`git push origin
  task-025`, authorized by `Proceed with`) as soon as the implementation
  commit passes `python3 scripts/run_tests.py --parallel`, and write the
  handoff while CI runs. Then record `T1_CI` evidence for that exact commit
  with `python3 scripts/ci_evidence.py --commit <sha> --task 025 --output
  <path> --wait 900`. Integrate only when that evidence reports a successful
  run on both operating systems. If CI fails, fix the failure on the task
  branch; do not integrate.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `tests/test_task_worktree_isolation.py` | Removed. |
| `capabilities/stop-codes-v1.json` | Registered test IDs. |
| `scripts/ci_evidence.py` | `T1_CI` evidence for the task commit. |

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
- `python3 scripts/ci_evidence.py --commit <task commit> --task 025 --output <path> --wait 900`
