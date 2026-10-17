# Task 027 — Replace the per-task CI gate with a clean-clone run and a two-platform release gate

> **ID**: `027`
> **Category**: Tooling
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: CI gate review, 2026-10-18
> **Origin**: friction

## Objective

Stop waiting for CI before each task lands, without losing what that gate
caught. Since task 006, every Cardine task pushes its branch and waits for the
`Validate repository` workflow on Ubuntu and macOS, about 4.5 minutes per task
on the macOS job alone. The tasks run on macOS, so their local validation
already covers macOS.

Since macOS joined CI on 2026-10-15, the per-task gate in Meridian and Cardine
caught one real defect that local validation missed: task 004's module
inventory baseline failed in CI's shallow checkout, on both operating systems.
The only Ubuntu-only failure was an `OSError` while removing a test's
temporary directory. A clean local clone reproduces the first case. Ubuntu
and macOS together belong in the release gate, which today runs on Ubuntu
only.

This changes how this repository validates its own tasks. The `direct`-mode
option of ADR decision 11, which lets a project require CI before landing,
stays in Cardine's 1.0 scope.

## Acceptance Criteria

- [ ] `python3 scripts/run_tests.py --parallel --clean-clone` clones the
  current `HEAD` with `git clone --depth 1 --no-local` into a new temporary
  directory. It runs `python3 scripts/check_repository.py` and the parallel
  suite there, with the same environment isolation the runner already
  applies, and removes the clone afterwards.
- [ ] The clean-clone run refuses to start when the working tree has
  uncommitted changes, so it always tests a commit. Its result line names the
  commit, the coverage `total` and `digest`, and the outcome.
- [ ] A test proves that the clean-clone run sees only committed files: an
  untracked file in the source checkout is absent from the clone. A test also
  reproduces the task 004 class: a check that needs history beyond the
  shallow commit fails in the clean clone and passes in the full checkout.
- [ ] `.github/workflows/release.yml` runs the repository check and the
  sequential suite on `ubuntu-latest` and `macos-latest` in a matrix job. The
  job that publishes the release depends on both and runs only when both pass.
- [ ] `.github/workflows/validate.yml` runs on `ubuntu-latest` only, as a
  non-blocking signal on pushes to `main` and on pull requests.
- [ ] `CONTRIBUTING.md` states the new rules:
  - a task validates locally and in a clean clone;
  - no task waits for CI;
  - the release gate runs on both platforms.

  It drops the step that pushes a task branch for `T1_CI` evidence, and the
  rule that a task contract may require that evidence.
- [ ] `docs/PLATFORM_SUPPORT.md` says that macOS and Linux are validated by
  the release gate, and that each push to `main` runs CI on Linux.
- [ ] `.meridian/candidate-validation.json` is unchanged.
  `scripts/ci_evidence.py` and its tests stay, for projects that require CI
  before landing.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `scripts/run_tests.py` | Adds `--clean-clone`. |
| `tests/test_run_tests.py` | Clean-clone tests. |
| `.github/workflows/release.yml` | Two-platform release gate. |
| `.github/workflows/validate.yml` | Ubuntu-only signal on `main`. |
| `CONTRIBUTING.md`, `docs/PLATFORM_SUPPORT.md` | Contributor and platform rules. |

## Technical Context

- Task 006 removed `MERIDIAN_ROOT` from the test processes, which closed the
  other environment leak that the per-task CI gate guarded against.
- `scripts/release.py` waits for the `Publish release` workflow on the tag.
  The new matrix job must keep that run's name and result semantics.
- Open tasks 020 to 026 already require the clean-clone run instead of CI
  evidence, and task 020 depends on this task.

## Out of scope

The `direct`-mode CI option of ADR decision 11, `scripts/ci_evidence.py`
behavior, and the managed workflow text in `PROJECT_WORKFLOW.md`, `AGENTS.md`,
and `CLAUDE.md`. That text authorizes a task-branch push only when a task needs
`T1_CI` evidence, so it stays valid.

## Dependencies

- **Depends on**: none
- **Blocks**: 020

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
