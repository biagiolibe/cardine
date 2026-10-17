# Task 024 — Move the remaining `test_meridian_cli.py` classes to domain test files

> **ID**: `024`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-18
> **Origin**: maintenance

## Objective

After task 023, `tests/test_meridian_cli.py` still holds the classes listed in
the plan's "Source and test size budget" section. Move each to a test file for
its domain and remove `tests/test_meridian_cli.py`.

## Acceptance Criteria

- [ ] Every remaining class of `tests/test_meridian_cli.py` moves intact to a
  domain test file: release self-check (with `FakeLatestReleaseResponse`);
  templates (marker, retirement, router, heading, manifest, surface upgrade,
  version detection); hosts (Codex and Claude setup and repair); tasks
  (identity, project); budget and context; worktree lifecycle, journal, and
  flow; launcher and task-state audit.
- [ ] `BudgetCliTest` (1,069 lines) and `WorktreeLifecycleCliTest` (921
  lines) stay intact unless their file would exceed 1,500 lines; then they are
  split by method responsibility, as the plan allows for `BudgetCliTest`.
- [ ] `tests/test_meridian_cli.py` no longer exists, and every new file is at
  most 1,500 lines.
- [ ] No test is lost or run twice: the parallel suite reports the same
  coverage `total` before and after the task, and the handoff maps every moved
  test ID from its old to its new location. No module re-imports `TestCase`
  classes into discovery, and shared fixtures hold no inherited `test_*`
  method.
- [ ] Tests keep their bodies: only imports, class placement, shared fixture
  bases, and registered test IDs (for example in
  `capabilities/stop-codes-v1.json`) change. No assertion is removed or
  weakened, and no platform skip changes.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task
  worktree and record its result line in the handoff. No task branch push or
  CI evidence is required.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `tests/test_meridian_cli.py` | Removed. |
| `capabilities/stop-codes-v1.json` | Registered test IDs. |

## Technical Context

- Task 023 already moved `MeridianCliTest` and created the fixture-only support module; reuse it.

## Out of scope

Any source change.

## Dependencies

- **Depends on**: 023
- **Blocks**: 025

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/run_tests.py --parallel --clean-clone`
