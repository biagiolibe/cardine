# Task 013 — Extract evidence, marker audit, migration audit, worktree path, and skill modules (split plan E08)

> **ID**: `013`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-17
> **Origin**: maintenance

## Objective

Continue work item 3 of `docs/ADR_CARDINE_1_0.md` with row E08 of
`docs/MODULE_SPLIT_PLAN.md`. Move the row's modules out of
`scripts/meridian.py` into `src/cardine/` without changing behavior, using the
extraction rule and inventory checks that tasks 004 and 006 applied.

## Acceptance Criteria

- [ ] These modules exist under `src/cardine/`, each holding exactly the
  bindings that the plan's "Complete symbol ownership" section assigns to it:
  `tasks/evidence.py`, `templates/marker_audit.py`,
  `templates/migration_audit.py`, `worktree/paths.py`, and `hosts/skills.py`.
  Package `__init__.py` files stay empty.
- [ ] Each moved binding is defined once, in its owner, and
  `scripts/meridian.py` imports it explicitly, as in tasks 004 and 006.
  Mutable state stays with its writers, and dataclass identities stay
  singletons across every entry point.
- [ ] The new modules import only providers that the plan's import graph lists
  for them, and only providers that earlier rows already extracted.
- [ ] The inventory tests in `tests/test_module_inventory.py` pass with the
  new owners: exactly one definition per baseline binding, no import cycle
  under `src/cardine/`, and no tracked Python file under `src/cardine/` or new
  test file over 1,500 lines.
- [ ] Every patch is checked against the plan's "Patch targets and suite
  compatibility" rules. A patch moves only when code that looks the patched
  name up moves in this task, including calls between bindings that now share
  an owner module. Patches whose consumers stay in `scripts/meridian.py` keep
  targeting `meridian`. The handoff lists each patch reviewed and the
  decision. No assertion, expected call, or intentional non-call is removed,
  and no platform skip changes.
- [ ] Text readers that scan moved code, such as repository source checks and
  path references, read the new modules, as the plan's "Path references, text
  readers and managed evidence" section requires.
- [ ] The discovered test IDs before and after the task are mapped in the
  handoff, with equal counts except for new tests.
- [ ] **CI before integration.** After validation, push the task branch once
  (`git push origin task-013`, authorized by `Proceed with`) and record
  `T1_CI` evidence for the exact task commit with `python3
  scripts/ci_evidence.py --commit <sha> --task 013 --output <path> --wait
  900`. Integrate only when that evidence reports a successful run on both
  operating systems. If CI fails, fix the failure on the task branch; do not
  integrate.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, row E08. |
| `scripts/meridian.py` | Source of the moved bindings. |
| `src/cardine/hosts/`, `src/cardine/tasks/`, `src/cardine/templates/`, `src/cardine/worktree/` | New modules. |
| `tests/test_module_inventory.py`, `tests/fixtures/module_split_baseline.json` | Inventory checks from tasks 004 and 005. |
| `scripts/ci_evidence.py` | `T1_CI` evidence for the task commit. |

## Technical Context

- Tasks 004 and 006 show the pattern: owner modules, explicit imports in the
  monolith, thin adapters, unchanged bodies, and a handoff with the test-ID
  mapping and the patch review.
- Focused proof for this row, from the plan: machine task-state, identity,
  execution-boundary, task-close and review-verdict tests; manifest, marker,
  upgrade/adoption, router and synthetic migration tests; Codex
  rules/configuration, setup/doctor and hook tests; worktree isolation,
  validation-evidence, integration-state and cleanup tests.

## Out of scope

Other plan rows. Any behavior change, removal (work item 4), or rename
(work item 5). If the row cannot fit its 3-hour bound, stop and split it at a
module or test-class boundary, as the plan requires.

## Dependencies

- **Depends on**: 012
- **Blocks**: 014 (split plan E09)

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 -m unittest discover -s tests -v`
- `git diff --check`
- `python3 scripts/ci_evidence.py --commit <task commit> --task 013 --output <path> --wait 900`
