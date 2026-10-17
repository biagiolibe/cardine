# Task 114 — Validate task branches in CI and capture the result as evidence

> **ID**: `114`
> **Category**: Infrastructure
> **Priority**: 🟡 P2
> **Estimate**: ~1.5h
> **Assigned to**: unassigned
> **Session**: Task 101 validation could not finish in the agent host

## Objective

`.github/workflows/validate.yml` runs the full suite only on `pull_request` and
on `push` to `main`, so a task branch has no CI result for its commit. A
completed CI run for the exact task commit is the strongest evidence a host with
a short command limit can use. Make CI run on task branches and add a small
script that turns the CI result for a commit into a `T1_CI` validation evidence
record.

## Acceptance Criteria

- [ ] `validate.yml` also runs on `push` to branches named `task-*`, keeps its
  current triggers, and sets `concurrency` so a newer push to the same ref
  cancels an in-progress run of that ref. The job steps are unchanged.
- [ ] `python3 scripts/ci_evidence.py --commit <sha> --task <TASK-ID> --output
  <path> [--wait SECONDS]` finds the `Validate repository` run for exactly that
  commit and event `push` or `pull_request` with read-only `gh run list` and
  `gh run view` calls, and writes a `T1_CI` record as defined by Task 113 only
  when the run completed with conclusion `success`.
- [ ] The script maps each observed state to an outcome and exit code, and writes
  a record only for the passed case: a successful run produces a `passed`
  record; a run in progress produces `running` (and with `--wait` is polled
  until the timeout); no run for the commit produces `unavailable` with the
  reason `no_ci_run`; a failed or cancelled run produces `failed`.
- [ ] A run is accepted only when its `headSha` equals the requested commit. A run
  for another commit is ignored, and the script never reuses a run for a similar
  branch name.
- [ ] Polling uses named constants for the interval and timeout, tolerates a
  transient `gh` error inside the window, and never prints a raw Python exception
  as its result.
- [ ] The script uses `gh` only, stores no credentials, makes no write call, and
  runs no project command. Missing `gh` is reported as `unavailable` with the
  reason `gh_missing`.
- [ ] Tests replace `gh`, the clock, and `sleep`; none uses the network or waits
  in real time. They cover success, in progress then success, no run, a run for
  another commit, failure, cancellation, a transient error, a missing `gh`, and
  the exact shape of the written record against Task 113's verifier.
- [ ] `CONTRIBUTING.md` documents the trigger, the script, that CI runs on Linux
  where macOS-only tests are skipped, and that the task branch must be pushed
  before a CI run can exist. It states that whether pushing the task branch is
  covered by the standing authorization is a decision recorded in
  `docs/TASK_CLOSURE_DESIGN.md` (Task 115); until then a missing run is reported
  as `unavailable`, not worked around.
- [ ] `changelog.d/114.md` records both changes.
- [ ] `python3 scripts/check_repository.py` and the unit tests pass.

## Relevant Files

| File | Role |
|------|------|
| `.github/workflows/validate.yml` | Add the `task-*` push trigger and `concurrency`. |
| `scripts/ci_evidence.py` | New script. |
| `tests/test_ci_evidence.py` | New tests. |
| `CONTRIBUTING.md` | Validation and CI documentation. |
| `CHANGELOG.md` | `[Unreleased]` entry. |

## Technical Context

- On 2026-10-02 the branch `task-101` was not on `origin`, and `validate.yml`
  triggered only on `pull_request` and `push` to `main`.
- `docs/TASK_CLOSURE_DESIGN.md` (Decision 1) authorizes `git push origin main`; it
  does not say that pushing the task branch is covered, which T1 needs. Task 115
  records that decision.
- The Governed templates already contain a `ci-verified-validation` capability
  that lets a reviewer use a completed CI run for the exact commit. This task
  does not change those templates.
- This workflow change applies to this repository's own CI. Adopters' CI is theirs.
- The polling pattern is the one of Task 096 for the release workflow; reuse its
  approach, not its code, unless the two scripts can share a helper without
  coupling.

## Validation

- `python3 scripts/check_repository.py`
- `python3 -m unittest discover -s tests`
- Evidence tier: the YAML structure, the script's decisions, and the record shape
  are program-computed and asserted. The first real run on a pushed `task-*`
  branch is recorded in the handoff as the only live evidence.

## Out of scope

Changing the job steps, adding macOS runners, the record format and verifier
(Task 113), pushing branches automatically, and updating action versions or
runner images.

## Dependencies

- **Depends on**: 113
- **Blocks**: none
