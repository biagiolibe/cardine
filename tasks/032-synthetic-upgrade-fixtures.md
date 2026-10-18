# Task 032 — Move the upgrade and merge tests to synthetic migration fixtures

> **ID**: `032`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 4 planning, 2026-10-18
> **Origin**: maintenance

## Objective

Work item 4 keeps the migration mechanism with an empty chain, and its upgrade
tests use synthetic fixtures instead of Meridian's migrations. This task
builds the fixture support and moves the upgrade and merge tests onto it,
while the real chain still exists. Task 033 then moves the remaining tests
and deletes the chain.

## Acceptance Criteria

- [ ] A test fixture builder creates a temporary framework root with a
  synthetic migration chain, templates, catalog, and marker baseline. Tests
  can declare each migration in a few lines: capability, version, operation,
  and content. It lives in a support module under `tests/`, and that module
  defines no `TestCase` classes.
- [ ] The upgrade and merge tests no longer read any file under
  `migrations/`. These are the upgrade/merge test file that task 023 created
  from `MeridianCliTest`, and `ProfileSurfaceUpgradeTest` and
  `WrappedTextUpgradeTest` wherever task 024 placed them. They run against
  synthetic chains that cover the same behaviors:
  - insertion;
  - supersession;
  - conflict reporting;
  - consumer-text preservation;
  - retirement alongside supersession.
- [ ] Each moved test keeps its assertions. Where a test asserted the identity
  of a real migration, for example a migration number in a message, it
  asserts the synthetic one instead. The handoff lists these tests.
- [ ] A test proves that upgrade with an empty chain is a no-op that reports
  the project as current.
- [ ] Production code changes only where a test needs to point the framework
  root at a fixture. The handoff names each such change.
- [ ] The parallel suite reports the same coverage `total` before and after
  the task, except for new tests.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `tests/` support module (new) | Synthetic framework-root builder. |
| Upgrade/merge test files from tasks 023 and 024 | Tests moved to fixtures. |
| `src/cardine/templates/migrations.py`, `upgrade.py`, `merge.py` | Code under test. |

## Technical Context

- The 2026-10-18 deletion probe failed 83 tests in `MeridianCliTest`, most
  of them upgrade tests, plus 6 in `ProfileSurfaceUpgradeTest` and 2 in
  `WrappedTextUpgradeTest`. The typical error was a missing file such as
  `migrations/056-manual-governed-proceed-worktree.json` or
  `migrations/063-retire-reasoning-budget-contract.json`.
- Task 031 already reads required and retired capabilities from the catalog.

## Out of scope

Deleting migration records and release baselines (tasks 033 and 034), and
changing upgrade behavior.

## Dependencies

- **Depends on**: 031
- **Blocks**: 033

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
