# Task 006 — Extract text, version, Git, JSON, and model modules (split plan E02)

> **ID**: `006`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-17
> **Origin**: maintenance

## Objective

Continue work item 3 of `docs/ADR_CARDINE_1_0.md` with row E02 of
`docs/MODULE_SPLIT_PLAN.md`. Move the next provider modules out of
`scripts/meridian.py` into `src/cardine/` without changing behavior, using the
extraction rule and inventory checks that task 004 introduced.

The task also closes two gaps that let task 004 land with `main` red: it
requires CI on the exact task commit before integration, and it stops the
test runner from leaking `MERIDIAN_ROOT` into tests.

## Acceptance Criteria

- [ ] These modules exist under `src/cardine/`, each holding exactly the
  bindings that the plan's "Complete symbol ownership" section assigns to it:
  `shared/text.py`, `release/version.py`, `shared/git.py`,
  `shared/jsonio.py`, and `shared/models.py`. Package `__init__.py` files stay
  empty.
- [ ] Each moved binding is defined once, in its owner, and
  `scripts/meridian.py` imports it explicitly, as in task 004. Mutable state
  stays with its writers; in particular `_SHARED_WORKTREES` stays in
  `shared/git.py` with its readers and context manager. Dataclass identities
  stay singletons across every entry point.
- [ ] The inventory tests in `tests/test_module_inventory.py` pass with the
  new owners: exactly one definition per baseline binding, no import cycle
  under `src/cardine/`, and no tracked Python file under `src/cardine/` or new
  test file over 1,500 lines.
- [ ] Every patch is checked against the plan's "Patch targets and suite
  compatibility" rules. A patch moves only when code that looks the patched
  name up moves in this task, including calls between bindings that now share
  an owner module (for example, a call from `canonical_project_root` to
  `_git_worktrees` inside `shared/git.py`). Patches whose consumers stay in
  `scripts/meridian.py` keep targeting `meridian`. The handoff lists each
  patch reviewed and the decision. No assertion, expected call, or intentional
  non-call is removed, and no platform skip changes.
- [ ] `scripts/run_tests.py` removes `MERIDIAN_ROOT` from the environment of
  the test processes it starts, and a test proves it. Tests that need the
  variable set it themselves.
- [ ] The discovered test IDs before and after the task are mapped in the
  handoff, with equal counts except for new tests.
- [ ] **CI before integration.** After validation, push the task branch once
  (`git push origin task-006`, authorized by `Proceed with`) and record `T1_CI`
  evidence for the exact task commit with `python3 scripts/ci_evidence.py
  --commit <sha> --task 006 --output <path> --wait 900`. Integrate only when
  that evidence reports a successful run on both operating systems. If CI
  fails, fix the failure on the task branch; do not integrate.
- [ ] `python3 scripts/check_repository.py`, `python3 scripts/meridian.py
  --framework-root . profile doctor meridian-self-hosting --project .`,
  `python3 scripts/meridian.py --framework-root . audit --project . --mode
  lean-delivery --ci-profile meridian-self-hosting`, `python3
  scripts/run_tests.py --parallel`, `python3 -m unittest discover -s tests
  -v`, and `git diff --check` pass.

## Relevant Files

| File | Role |
|------|------|
| `docs/MODULE_SPLIT_PLAN.md` | Authority: symbol ownership, extraction rule, patch rules, row E02. |
| `scripts/meridian.py` | Source of the moved bindings. |
| `src/cardine/shared/`, `src/cardine/release/` | New modules. |
| `tests/test_module_inventory.py`, `tests/fixtures/module_split_baseline.json` | Inventory checks from tasks 004 and 005. |
| `scripts/run_tests.py` | Test runner environment. |
| `scripts/ci_evidence.py` | `T1_CI` evidence for the task commit. |

## Technical Context

- Task 004 shows the pattern: owner modules, explicit imports in the monolith,
  thin adapters, unchanged bodies, and a handoff with the test-ID mapping.
- `release/version.py` owns `read_version` and `read_raw_version`. The
  `cardine` command and `bin/meridian` must keep reporting this checkout's
  `VERSION`, also with `MERIDIAN_ROOT` set to another checkout.
- Meridian task 231 and Cardine task 004 both failed outside the local
  environment: one on an inherited `MERIDIAN_ROOT`, one in CI's shallow
  checkout. The two new criteria above target those failure classes.

## Out of scope

Plan rows E03 and later. Any behavior change, removal (work item 4), or rename
(work item 5).

## Dependencies

- **Depends on**: 005
- **Blocks**: E03

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 -m unittest discover -s tests -v`
- `git diff --check`
- `python3 scripts/ci_evidence.py --commit <task commit> --task 006 --output <path> --wait 900`
