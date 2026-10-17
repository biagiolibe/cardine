# Task 001 — Make the evidence tests independent of Meridian task records

> **ID**: `001`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~1h
> **Assigned to**: unassigned
> **Session**: Cardine bootstrap, 2026-10-17
> **Origin**: maintenance

## Objective

The import of Meridian 1.4.0 kept two Meridian task records,
`tasks/done/113-validation-evidence-record-and-verifier.md` and
`tasks/done/114-ci-on-task-branches-and-evidence-lookup.md`, only because three
tests resolve task IDs `113` and `114` from this repository's own task records.
Without them, `check_validation_evidence` reports
`commit: unknown task identity: '113'`.

Make those tests build the project they need, so that no Meridian task record
remains in this repository.

## Acceptance Criteria

- [ ] No Meridian task record remains under `tasks/`: both files above are
  deleted, and `tasks/done/` holds no file.
- [ ] `tests/test_validation_evidence.py` and `tests/test_ci_evidence.py` pass.
  They no longer depend on task records, `HEAD`, or the tree of this
  repository: each test creates a temporary Git project that holds its own task
  record and commit.
- [ ] The tests still prove what they proved before: a passing record bound to
  the commit and tree is accepted, each invalid field is named, and
  `scripts/ci_evidence.py` writes a record that the verifier accepts.
- [ ] No change under `scripts/`.
- [ ] `python3 scripts/check_repository.py`, `python3 scripts/run_tests.py
  --parallel`, and `git diff --check` pass.

## Relevant Files

| File | Role |
|------|------|
| `tests/test_validation_evidence.py` | Uses task `113` and this repository's `HEAD`. |
| `tests/test_ci_evidence.py` | Uses task `114` and this repository's `HEAD`. |
| `tasks/done/113-…md`, `tasks/done/114-…md` | Meridian records to delete. |

## Technical Context

- `meridian.check_validation_evidence(record_path, project_root, commit)`
  resolves the record's `task_id` through the project's task identity, then
  checks commit and tree.
- Other tests already build temporary Git projects; reuse their helpers where
  one fits instead of adding a new one.

## Out of scope

Any change to evidence semantics or to `scripts/`.

## Dependencies

- **Depends on**: none
- **Blocks**: none

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/run_tests.py --parallel`
- `git diff --check`
