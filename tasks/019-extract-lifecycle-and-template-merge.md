# Task 019 — Extract lifecycle, upgrade support, merge, and adoption modules (split plan E12)

> **ID**: `019`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-18
> **Origin**: maintenance

## Objective

Continue work item 3 of `docs/ADR_CARDINE_1_0.md` with row E12 of
`docs/MODULE_SPLIT_PLAN.md`. Move the row's modules out of
`scripts/meridian.py` into `src/cardine/` without changing behavior.

## Acceptance Criteria

- [ ] These modules exist under `src/cardine/`, each holding exactly the
  bindings that the plan's "Complete symbol ownership" section assigns to it:
  `lifecycle/closure.py`, `lifecycle/commands.py`,
  `templates/upgrade_support.py`, `templates/merge.py`, and
  `templates/adoption.py`. Package `__init__.py` files stay empty.
- [ ] Each moved binding is defined once, in its owner, and
  `scripts/meridian.py` imports it explicitly, as in tasks 004 to 016.
  Mutable state stays with its writers, and dataclass identities stay
  singletons across every entry point.
- [ ] The new modules import only providers that the plan's import graph lists
  for them, and only providers that earlier rows already extracted.
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
- [ ] Text readers that scan moved code, such as repository source checks and
  path references, read the new modules, as the plan's "Path references, text
  readers and managed evidence" section requires.
- [ ] The parallel suite reports the same coverage `total` before and after
  the task, except for new tests. The handoff lists only the test IDs that
  changed, with their old and new IDs.
- [ ] **CI before integration.** Push the task branch once (`git push origin
  task-019`, authorized by `Proceed with`) as soon as the implementation
  commit passes `python3 scripts/run_tests.py --parallel`, and write the
  handoff while CI runs. Then record `T1_CI` evidence for that exact commit
  with `python3 scripts/ci_evidence.py --commit <sha> --task 019 --output
  <path> --wait 900`. Integrate only when that evidence reports a successful
  run on both operating systems. If CI fails, fix the failure on the task
  branch; do not integrate.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `scripts/meridian.py` | Source of the moved bindings. |
| `src/cardine/lifecycle/`, `src/cardine/templates/` | New modules. |
| `tests/test_module_inventory.py`, `tests/fixtures/module_split_baseline.json` | Inventory checks. |
| `scripts/ci_evidence.py` | `T1_CI` evidence for the task commit. |

## Technical Context

- Tasks 004 to 016 show the pattern: owner modules, explicit imports in the monolith, thin adapters, unchanged bodies, and a handoff that records the patch review and changed test IDs by exception.
- Focused proof for this row, from the plan: machine task-state, identity, execution-boundary, task-close and review-verdict tests; manifest, marker, upgrade/adoption, router and synthetic migration tests.
- `advance_task_closure` moves to `cardine.lifecycle.closure`. Task 018 changes its Lean closure resume first, so this task moves the corrected code unchanged.

## Out of scope

Other plan rows. Any behavior change, removal (work item 4), or rename
(work item 5). If the task cannot fit its 3-hour bound, stop and split it at a
module or test-class boundary, as the plan requires.

## Dependencies

- **Depends on**: 016, 007, 018
- **Blocks**: 020

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/ci_evidence.py --commit <task commit> --task 019 --output <path> --wait 900`
