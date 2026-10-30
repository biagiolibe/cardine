# Task 139 — Reuse the ready cleanup fixture and measure the real savings

> **ID**: `139`
> **Category**: Refactor
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Developer-requested test performance discovery, 2026-10-30
> **Origin**: maintenance

## Objective

Accelerate only `CleanupTest.test_every_effect_boundary_replays_identically`
by reusing its already integrated fixture. Preserve all twelve real process
interruptions and every existing assertion. Measure the actual improvement of
the matrix and of the complete clean-clone suite separately.

This record authorizes planning only. Implementation starts only after an
explicit `Proceed with 139` instruction through the local Lean Delivery
workflow and its deterministic task worktree.

## Acceptance Criteria

- [ ] **Before measurements.** Before implementation, record three sequential
  uninstrumented runs of the exact focused command below and their median,
  one run of the cleanup module, and one full clean-clone run from a clean,
  committed pre-implementation task HEAD. Record the commit, Python version,
  machine, worker count, test IDs/count/digest, and whether other suites were
  running. Do not run these measurements concurrently with each other or with
  another test suite. Historical discovery numbers are context, not this
  task's baseline.
- [ ] **One ready build.** Build the matrix's integrated fixture once, save
  it before `own_remote()`, use it for the first scenario, and restore it
  before the other eleven. Eliminate the unused outer fixture build. Do not
  repeat prepare, implementation, task validation, staging, candidate
  validation, or finalization for each scenario. Keep `own_remote()` per
  scenario, including its real push and intent construction.
- [ ] **Stable identity and isolation.** Restore independent file copies,
  including the local bare origin, primary checkout, and linked worktree,
  into their original absolute paths. Do not relocate a prepared repository,
  use hard links for mutable files, share state across shard processes, or
  overwrite the shared bounded fixture's original snapshot. Change the
  working directory outside the live tree before deleting/restoring it.
  Manage environment patches, open handles, and temporary-copy cleanup for
  the matrix's lifetime; no process or held lock survives a scenario.
- [ ] **All twelve scenarios remain.** Execute both `before` and `after`
  for `cleanup_push`, `cleanup_remote`, `cleanup_worktree`,
  `cleanup_placeholder`, `cleanup_branch`, and `cleanup_lifecycle`.
  Each child must really terminate with exit 97 at the requested boundary.
  Preserve the existing matrix test ID and every existing test/assertion;
  no case may be removed, skipped, renamed, sampled, or replaced by mocked
  cleanup effects.
- [ ] **All four cleanup calls remain per scenario.** Retain the refusals
  for changed task ownership and changed actual remote destination, the
  successful recovery, and its identical idempotent repetition. Preserve
  every assertion on the merge commit, main remote tip, absent remote task
  ref, and removed local task branch.
- [ ] **Restore equivalence.** Add a narrowly scoped proof that a ready
  snapshot and its restored state have equal path/mode/link/content digests,
  Git worktree registrations, refs, primary and worker HEADs, and indexes;
  task receipts remain valid. After a scenario changes/deletes fixture state,
  the next restore must equal the saved state and retain no scenario data.
  Additional proof tests are allowed; list their IDs and account for their
  effect on round-robin shard assignment. Do not weaken existing assertions.
- [ ] **After measurements and useful gain.** Repeat the same three focused
  runs and cleanup-module run on the same environment. The focused median
  decreases; report every sample and their spread so timing noise is visible.
  Record the measured result, not the historical 52-percent forecast. Run the
  required final clean-clone
  validation once and compare it with the baseline. Report full-suite wall
  time, seconds and percentage gained or lost, all shard durations and the
  longest shard before/after. If suite timing varies or test additions
  redistribute work, distinguish those effects from the matrix improvement;
  never claim a full-suite gain from the focused result alone. A positive
  full-suite timing delta is not guaranteed by this bounded task.
- [ ] **Phase evidence.** Using temporary external instrumentation, report
  preparation (including remote intent), interruption, the two rejection
  checks, first successful recovery, and idempotent repetition separately
  for all twelve scenarios. Report cold build and snapshot capture/restore
  costs separately. Keep the uninstrumented runs as the performance baseline.
- [ ] All validation commands pass. The existing subprocess ceilings remain
  unchanged. The handoff lists added proof tests, environmental skips, and
  timing limitations explicitly.

## Relevant Files

| File | Role |
|------|------|
| `tests/test_run_cleanup.py` | The one matrix and its ready fixture. |
| `tests/fixture_restore_support.py` | Existing stable-path restore helper; change only if needed for this matrix. |
| `tests/test_fixture_restore.py` | Narrow restore-equivalence proof, if required. |
| `tests/worktree_support.py` | Read-only context: the existing snapshot stops before the expensive cleanup-specific preparation. |
| `scripts/run_tests.py` | Read-only runner, focused selection, coverage proof, and shard assignment. |

Only the first three implementation paths and task-local lifecycle artifacts
are in scope. Task branches do not edit queue, queue archive, or project plan.

## Technical Context

The existing `CleanupTest.setUp` restores the bounded base, then creates the
bare origin, prepares the worker, commits implementation, measures task
validation, stages integration, validates the candidate, and finalizes it.
The matrix's outer setup is unused; its body builds twelve more complete
fixtures. Task 138 reused only the earlier bounded base.

External discovery on commit `0b55d70cb9799943c54ea07cb6c549f98968e3f6`,
Python 3.15, with disposable homes and an isolated clone, found:

| Phase | Profiled seconds |
|-------|-----------------:|
| Unused outer ready build | 8.386 |
| Twelve additional ready builds | 82.764 |
| Twelve remote/intent preparations | 7.382 |
| Real process interruption | 24.644 |
| Rejection checks | 1.976 |
| Successful recovery | 27.873 |
| Idempotent repetition | 3.470 |
| Remaining checks and teardown | 0.794 |

The unchanged matrix passed in 150.470 seconds without instrumentation and
157.289 seconds with profiling. A separate file-operation probe measured a
0.041-second snapshot capture and twelve successful restores totaling 0.717
seconds, with equal tree digests/Git observations and valid receipts. This
supports a roughly 75-second matrix forecast under the profiled conditions;
the accelerated matrix has not been implemented or measured. Temporary
discovery files are not required inputs to execute this task.

An earlier complete run on commit
`7c7b18f3b39b2b921fd9c67116fade718b995f71` took 1644.065 seconds externally
and 1639.0 seconds inside the parallel runner (1892 tests). The matrix took
428.714 seconds under that load and belonged to the longest shard:
1638.770 seconds versus 1459.980 seconds for the next-longest shard.
At fixed assignments and unchanged other durations, speeding up only this
matrix can save at most about 179 seconds of that historical full run before
the other shard becomes the bottleneck. An isolated 52-percent matrix gain
is not a 52-percent full-suite gain. Do not extrapolate it as a promised
result, and do not compare different machines, Python versions, or concurrent
loads as a controlled before/after experiment.

## Suggested Implementation

Keep the change local to the matrix. Reuse its automatically built outer
fixture as the initial ready state, capture it before per-case remote
ownership, and restore that complete tree at the same location between
scenarios. Reuse the existing restore mechanism where practical without
changing fixtures used by unrelated tests. Reload path-derived runtime
objects where needed and prove that stale caches do not affect a restore.
Prefer this bounded change over a new general fixture framework.

## Out of Scope

Product code; other cleanup tests' setup behavior; other matrices; changing
test selection, worker count, shard scheduling, suite gates, receipt rules,
or host configuration; removing supposedly redundant tests. Preserve all
local workflow and host files. Do not create `.cardine/` in this repository
or run setup/apply against the real home. Only installed Meridian lifecycle
commands may write this task's `.meridian/tasks/139.json` state.

## Dependencies

- **Depends on**: 138
- **Blocks**: none.
- Independent of the remaining host-integration task chain.

## Validation

Focused measurement/development:

- `python3 scripts/run_tests.py --parallel --module test_run_cleanup.CleanupTest.test_every_effect_boundary_replays_identically`
- `python3 scripts/run_tests.py --parallel --module test_run_cleanup`
- `python3 scripts/run_tests.py --parallel --module test_fixture_restore --module test_command_context`

Counted final validation:

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone command includes repository checks and the full parallel
suite; do not repeat them as separate counted checks. Capture per-shard
timings externally without changing the runner. Use disposable homes and
record that environment consistently before and after. Complete the local
candidate-validation gate if integration requires it. Save measured evidence
in `tasks/handoffs/139.md` using the local completion-report template.

## Execution

Execute only after `Proceed with 139`, in the deterministic task worktree
prepared by the installed Meridian lifecycle. This record does not request
implementation, delegation, or independent changes to another task.
