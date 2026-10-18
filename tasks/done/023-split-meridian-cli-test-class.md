# Task 023 — Split the `MeridianCliTest` class by responsibility

> **ID**: `023`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-18
> **Origin**: maintenance

## Objective

`tests/test_meridian_cli.py` has 9,653 lines, and its `MeridianCliTest`
class alone has 3,257. The ADR limits every source and test file to 1,500
lines. Split that class by test-method responsibility, as the plan's "Source
and test size budget" section describes.

## Acceptance Criteria

- [x] `MeridianCliTest` is split into test files for upgrade and merge,
  migration and retirement, adoption and audit, manifest and protocol, and CLI
  and entry, each at most 1,500 lines. A class that would still exceed the
  limit is split again; none keeps more than 1,500 lines only to preserve its
  name.
- [x] Its setup, teardown, and helper methods move to a fixture-only mixin in
  a support module that discovery does not collect.
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
| `tests/test_meridian_cli.py` | Source of `MeridianCliTest`. |
| `capabilities/stop-codes-v1.json` | Registered test IDs. |

## Technical Context

- The other classes of `tests/test_meridian_cli.py` move in task 024.
- Discovery uses `tests/test_*.py`; a support module must not match that pattern.

## Out of scope

Other classes of `tests/test_meridian_cli.py` (task 024). Any source change.

## Dependencies

- **Depends on**: 022
- **Blocks**: 024

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/run_tests.py --parallel --clean-clone`
