# Task 022 — Extract upgrade, adopt command, and CLI, and switch the entry points (split plan E13)

> **ID**: `022`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-18
> **Origin**: maintenance

## Objective

Finish moving code for work item 3 of `docs/ADR_CARDINE_1_0.md` with row E13
of `docs/MODULE_SPLIT_PLAN.md`. Move the last bindings out of
`scripts/meridian.py`, then make every entry point dispatch to the package.

## Acceptance Criteria

- [x] These modules exist under `src/cardine/`, each holding exactly the
  bindings that the plan's "Complete symbol ownership" section assigns to it:
  `templates/upgrade.py`, `templates/adopt_command.py`, and `cli.py`
  (which replaces the task 002 bridge). Package `__init__.py` files stay empty.
- [x] Each moved binding is defined once, in its owner, and
  `scripts/meridian.py` imports it explicitly, as in tasks 004 to 016.
  Mutable state stays with its writers, and dataclass identities stay
  singletons across every entry point.
- [x] The new modules import only providers that the plan's import graph lists
  for them, and only providers that earlier rows already extracted.
- [x] `scripts/meridian.py` keeps no implementation: it is a compatibility
  executable and import adapter under 100 lines. `bin/meridian` dispatches to
  the package, finding `src/` from its own checkout when nothing is
  installed, and keeps its Python version guard.
- [x] `bin/meridian`, `python3 scripts/meridian.py`, `import meridian` in
  tests, and the `cardine` command report the same `--version` and give the same
  output and exit code for the same arguments, also with `MERIDIAN_ROOT` set to
  another checkout. A test covers this parity.
- [x] The inventory tests in `tests/test_module_inventory.py` pass: exactly
  one definition per baseline binding, no import cycle under `src/cardine/`,
  and no tracked Python file under `src/cardine/` or new test file over 1,500
  lines.
- [x] Every patch is checked against the plan's "Patch targets and suite
  compatibility" rules. A patch moves only when code that looks the patched
  name up moves in this task, including calls between bindings that now share
  an owner module. The handoff lists each patch that moved, with its new
  target, and the number of patches reviewed that keep their target. No
  assertion, expected call, or intentional non-call is removed, and no platform
  skip changes.
- [x] Text readers that scan moved code, such as repository source checks and
  path references, read the new modules, as the plan's "Path references, text
  readers and managed evidence" section requires.
- [x] The parallel suite reports the same coverage `total` before and after
  the task, except for new tests. The handoff lists only the test IDs that
  changed, with their old and new IDs.
- [x] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task
  worktree and record its result line in the handoff. No task branch push or
  CI evidence is required.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, import graph, extraction rule, patch rules, size budget. |
| `scripts/meridian.py` | Becomes an adapter. |
| `src/cardine/cli.py`, `src/cardine/templates/` | New and replaced modules. |
| `bin/meridian` | Dispatches to the package. |
| `tests/test_module_inventory.py`, `tests/fixtures/module_split_baseline.json` | Inventory checks. |

## Technical Context

- Tasks 004 to 016 show the pattern: owner modules, explicit imports in the monolith, thin adapters, unchanged bodies, and a handoff that records the patch review and changed test IDs by exception.
- Focused proof, from the plan: manifest, marker, upgrade/adoption, router, and synthetic migration tests; legacy and package CLI parity; source checker; self-hosting doctor and audit.
- `.codex/hooks.json` and the shell hooks run `bin/meridian`; keep those commands and their permissions.
- The released Meridian CLI at `~/.local/share/meridian` drives this repository's lifecycle and is not affected.

## Out of scope

Other plan rows. Any behavior change, removal (work item 4), or rename
(work item 5). If the task cannot fit its 3-hour bound, stop and split it at a
module or test-class boundary, as the plan requires.

## Dependencies

- **Depends on**: 021, 028
- **Blocks**: 023

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- `python3 scripts/run_tests.py --parallel --clean-clone`

## Completion evidence

Implementation commit: `27a45228369eadc322df1dd4d985b3b7ece1cf33`.
All acceptance criteria passed; see `tasks/handoffs/022.md` for validation,
patch review, entry-point parity, and test identity evidence.
