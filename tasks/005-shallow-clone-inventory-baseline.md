# Task 005 — Make the module inventory test pass in a shallow clone

> **ID**: `005`
> **Category**: Bugfix
> **Priority**: 🔴 P1
> **Estimate**: ~30min
> **Assigned to**: unassigned
> **Session**: Cardine module split, 2026-10-17
> **Origin**: friction

## Objective

CI on `main` (44c8ab1, "Integrate 004") fails on both operating systems.
`tests/test_module_inventory.py`, in
`test_package_and_new_tests_fit_line_budget`, runs
`git ls-tree -r --name-only ceb84fd -- tests`. `actions/checkout` makes a
shallow clone, so commit `ceb84fd` is missing and `git` exits with status 128.
Coordination reproduced the failure with `git clone --depth 1`; the test
passes only with full history.

Task 004 required a committed inventory generated from `ceb84fd`; the
baseline test file list was left out of it.

## Acceptance Criteria

- [ ] `tests/fixtures/module_split_baseline.json` records the baseline test
  file list under a new `tests` key, generated once from
  `git ls-tree -r --name-only ceb84fd -- tests`.
- [ ] The test reads that list from the fixture and calls no Git command that
  needs a commit other than `HEAD`.
- [ ] The 1,500-line rule and its scope are unchanged.
  `.github/workflows/validate.yml` is unchanged; in particular it gets no
  `fetch-depth: 0`.
- [ ] In a temporary `git clone --depth 1` of the task commit, `python3 -m
  unittest discover -s tests -p test_module_inventory.py` passes.
- [ ] `python3 scripts/check_repository.py`, `python3 scripts/run_tests.py
  --parallel`, and `git diff --check` pass.

## Relevant Files

| File | Role |
|------|------|
| `tests/test_module_inventory.py` | The failing test. |
| `tests/fixtures/module_split_baseline.json` | Committed baseline inventory. |

## Out of scope

Any other test or source change.

## Dependencies

- **Depends on**: 004
- **Blocks**: the next extraction (split plan E02)

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
- In a temporary `git clone --depth 1` of the task commit:
  `python3 -m unittest discover -s tests -p test_module_inventory.py`
