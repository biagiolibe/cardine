# Task 004 — Extract the leaf modules (split plan E01)

> **ID**: `004`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-17
> **Origin**: maintenance

## Objective

Start work item 3 of `docs/ADR_CARDINE_1_0.md` with row E01 of
`docs/MODULE_SPLIT_PLAN.md`: move the leaf modules out of
`scripts/meridian.py` into `src/cardine/`, without changing behavior, and
add the inventory checks that every later extraction reuses.

## Acceptance Criteria

- [x] These modules exist under `src/cardine/`, each holding exactly the
  bindings that the plan's "Complete symbol ownership" section assigns to it:
  `integration/decision.py`, `shared/constants.py`, `shared/errors.py`,
  `shared/hashing.py`, and `shared/paths.py`. Package `__init__.py` files are
  empty.
- [x] `scripts/task_state.py` moves unchanged to `src/cardine/tasks/state.py`
  and `scripts/console_workflow.py` to
  `src/cardine/shared/console_workflow.py`. The old scripts become thin
  adapters for their existing callers.
- [x] Each moved binding is defined once, in its owner. `scripts/meridian.py`
  imports the owners explicitly: no copied bodies, no star imports, no
  forwarding of assignments. Mutable state and caches stay with their writers,
  as the plan's extraction rule requires.
- [x] `SCRIPTS_ROOT` keeps its meaning (this checkout's `scripts/`
  directory), resolved from the package file's checkout location and never from
  the caller's working directory, the selected project, or `MERIDIAN_ROOT`.
- [x] Every entry point keeps working with the same behavior:
  `bin/meridian`, `python3 scripts/meridian.py` (run by CI with no install),
  `import meridian` in tests, and the `cardine` command from task 002.
- [x] `scripts/release.py` no longer reads `PROTOCOL_VERSION` from
  `scripts/meridian.py` with a regular expression. It reads the owner module
  of the release root it is given, so a fixture release never picks up the
  running checkout's value. The synthetic fixtures in `tests/test_release.py`
  move with it, and both the protocol-change and review-gate assertions stay.
- [x] `scripts/check_repository.py` scans `src/cardine/**/*.py` as well as the
  adapters wherever it scans the monolith today, including the registered stop
  mention scan. A test places a stop in an extracted module and shows the scan
  still finds it.
- [x] New inventory checks run in the suite and are reusable by the next
  extractions: every top-level binding of the plan's baseline (a committed
  inventory generated from commit `ceb84fd`) has exactly one definition across
  `scripts/meridian.py` and `src/cardine/`; the import graph
  under `src/cardine/` has no cycle; no tracked Python file under
  `src/cardine/` or of a new test file exceeds 1,500 lines.
- [x] Tests change only their imports, patch targets, and fixtures, following
  the plan's "Patch targets and suite compatibility" rules. No assertion is
  removed or weakened, and no platform skip changes. The discovered test IDs
  before and after the task are mapped in the handoff, with equal counts except
  for the new inventory and scan tests.
- [x] `python3 scripts/check_repository.py`, `python3 scripts/meridian.py
  --framework-root . profile doctor meridian-self-hosting --project .`,
  `python3 scripts/meridian.py --framework-root . audit --project . --mode
  lean-delivery --ci-profile meridian-self-hosting`, `python3
  scripts/run_tests.py --parallel`, `python3 -m unittest discover -s tests
  -v`, and `git diff --check` pass.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, extraction rule, patch rules, path references, row E01. |
| `scripts/meridian.py` | Source of the moved bindings; imports their owners afterwards. |
| `scripts/task_state.py`, `scripts/console_workflow.py` | Move to the package; become adapters. |
| `src/cardine/` | New modules. |
| `scripts/release.py`, `tests/test_release.py` | Protocol-version reader and its fixtures. |
| `scripts/check_repository.py`, `tests/test_check_repository.py` | Source scans. |
| `bin/meridian`, `src/cardine/cli.py` | Entry points to keep working. |

## Technical Context

- CI runs `python3 scripts/meridian.py` and `scripts/run_tests.py` with no
  package installed, and tests import `meridian` from `scripts/`. The
  monolith therefore has to find `src/` from its own checkout location, never
  from an installed package or from `MERIDIAN_ROOT`.
- The released Meridian CLI at `~/.local/share/meridian` drives this
  repository's lifecycle and is not affected by these changes.
- The patch targets that E01 touches are listed in the plan's inventory table;
  later rows retarget the rest when their consumers move.
- Managed digests and self-hosting probe evidence are not source hashes:
  refresh only surfaces that really changed, with the documented digest writer.

## Out of scope

Plan rows E02 and later. Any behavior change, removal (work item 4), or rename
(work item 5).

## Dependencies

- **Depends on**: 003
- **Blocks**: E02

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 -m unittest discover -s tests -v`
- `git diff --check`
