# Task 020 — Extract console models, launch, and snapshot (split plan C01)

> **ID**: `020`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-18
> **Origin**: maintenance

## Objective

Continue work item 3 of `docs/ADR_CARDINE_1_0.md` with row C01 of
`docs/MODULE_SPLIT_PLAN.md`. Start the split of `scripts/project_console.py`
(2,097 lines) into `cardine.console`, without changing behavior.

## Acceptance Criteria

- [ ] `src/cardine/console/models.py`, `launch.py`, and `snapshot.py` exist,
  with the classes and functions that the plan's "Source and test size budget"
  section assigns to them. Package `__init__.py` files stay empty.
- [ ] The console's direct imports from `meridian` become imports from the
  owner modules in the plan's import graph. `scripts/project_console.py` keeps
  the remaining code and imports the moved names explicitly; `meridian
  console` keeps working.
- [ ] Models are leaves; launch and snapshot import models and no console
  module that a later row extracts.
- [ ] The inventory tests in `tests/test_module_inventory.py` pass: exactly
  one definition per baseline binding, no import cycle under `src/cardine/`,
  and no tracked Python file under `src/cardine/` or new test file over 1,500
  lines.
- [ ] Every patch is checked against the plan's "Patch targets and suite
  compatibility" rules. A patch moves only when code that looks the patched
  name up moves in this task, including calls between bindings that now share
  an owner module. The handoff lists each patch that moved, with its new
  target, and the number of patches reviewed that keep their target. No
  assertion, expected call, or intentional non-call is removed, and no platform
  skip changes.
- [ ] The parallel suite reports the same coverage `total` before and after
  the task, except for new tests. The handoff lists only the test IDs that
  changed, with their old and new IDs.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task
  worktree and record its result line in the handoff. No task branch push or
  CI evidence is required.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `scripts/project_console.py` | Source of the moved code. |
| `src/cardine/console/` | New modules. |
| `tests/test_project_console.py` | Console tests; split in task 021. |
| `tests/test_module_inventory.py`, `tests/fixtures/module_split_baseline.json` | Inventory checks. |

## Technical Context

- Tasks 004 to 016 show the pattern: owner modules, explicit imports in the monolith, thin adapters, unchanged bodies, and a handoff that records the patch review and changed test IDs by exception.
- Focused proof, from the plan: existing snapshot, state, and launch tests, including fixture identity and refresh cost; compare the discovered cases before and after.
- The console stays Experimental and keeps its current behavior. Rebuilding it on `cardine run` is work item 8, not this task.

## Out of scope

Other plan rows. Any behavior change, removal (work item 4), or rename
(work item 5). If the task cannot fit its 3-hour bound, stop and split it at a
module or test-class boundary, as the plan requires. Splitting `tests/test_project_console.py` (task 021).

## Dependencies

- **Depends on**: 019, 027
- **Blocks**: 021

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/run_tests.py --parallel --clean-clone`
