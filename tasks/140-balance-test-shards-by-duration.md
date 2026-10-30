# Task 140 — Balance test shards by measured duration without reducing coverage

> **ID**: `140`
> **Category**: Infrastructure
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Developer-requested test performance discovery, 2026-10-30
> **Origin**: maintenance

## Objective

Reduce the complete suite's wall time by assigning test modules to shards
using measured durations instead of round-robin positions of individual test
IDs. Retain all existing tests, scenarios, assertions, and validation gates.
Measure the actual full-suite improvement separately from scheduling forecasts.

This is a planning record. Implementation starts only after `Proceed with 140`
through the local Lean Delivery workflow and its deterministic task worktree.

## Acceptance Criteria

- [ ] **Fresh baseline.** Before implementation, run the complete clean-clone
  suite with eight workers on a clean, committed pre-implementation task HEAD.
  Record command wall time, runner wall time, every shard's duration, per-module
  durations, commit, Python version, machine, worker count, and test IDs/count/
  digest. Use disposable homes and a short temporary root consistently before
  and after. Run measurements sequentially, without another test suite active.
  Historical numbers below are context, not substitutes for this baseline.
- [ ] **Deterministic duration-based assignment.** Allocate whole modules
  by descending measured duration to the least-loaded shard. Define stable
  module-name and shard-index tie breakers. Parent and child processes,
  including direct `--shard I/N` invocations, derive the same assignment from
  the same discovered IDs, weights, and worker count. No runtime completion
  order, PID, filesystem enumeration order, or machine CPU count may affect
  assignment for an explicitly selected effective worker count.
- [ ] **Portable weights.** Commit a small, versioned module-duration data
  file derived from the fresh baseline. Record measurement provenance without
  absolute machine paths. Document how to refresh it explicitly. Successful
  test runs never modify this tracked file automatically. A missing weight or
  a new module receives a documented deterministic positive estimate and still
  runs. Removed modules in the data do not create phantom tests. Validate the
  data shape and reject malformed, non-finite, zero, or negative weights with
  a clear diagnostic; never turn a data problem into a passing empty run.
- [ ] **Every test exactly once.** Preserve every existing test ID, scenario,
  and assertion, including all 442 plugin-distribution interruption scenarios
  and all twelve cleanup scenarios. Prove that the full shards' union equals
  discovery and that intersections are empty for 1, 2, 4, and 8 workers. Keep
  the full sorted-ID count/digest independent of partitioning. New runner
  proof tests are allowed and must be listed in the handoff; no existing test
  may be removed, renamed, skipped, sampled, or weakened to obtain a speedup.
- [ ] **Runner modes remain sound.** Preserve worker-count bounds, private
  shard environments, full-run success/failure semantics, failure diagnostics,
  failed-test records, and clean-clone behavior. `--list` remains discovery
  evidence, not an execution. Keep `--module`, `--last-failed`, and partial
  summaries partial and exact; retaining round-robin assignment for partial
  selections is allowed to preserve useful parallelism within a single
  selected module. Parent/child selection must agree. Explicitly cover fewer
  modules than workers, empty shards, unknown weights, and changed discovery;
  preserve or clearly document existing empty-shard/error behavior. An
  intentionally changed full-shard membership is not an API-compatible claim
  of retaining the old round-robin assignment.
- [ ] **Meaningful scheduler proofs.** Test deterministic ties and an
  intentionally skewed synthetic workload whose predicted longest shard is
  lower than round-robin. Test exact coverage and failure propagation through
  the real runner, not only a duplicate implementation of its allocator.
  Update old tests that prescribe round-robin membership only where that
  membership is intentionally replaced; retain their underlying coverage and
  safety assertions.
- [ ] **Real full-suite gain.** After implementation is committed, run the
  same complete clean-clone command on the same environment with eight workers.
  Record seconds and percentage gained or lost, all shard durations, the
  longest shard, and the spread between shortest and longest. The measured
  complete-suite wall time must improve; a simulated balance or faster subset
  is not sufficient. Report workload/count changes from added proof tests and
  timing limitations. If background activity or overlapping measurements make
  the comparison inconclusive, repeat only the comparison needed to resolve
  that uncertainty. Do not promise the historical 11–12-minute forecast as a
  guaranteed result or count the first discarded experiment below.
- [ ] Every validation command passes. The completion report distinguishes
  test-ID coverage evidence from code/behavioral coverage and names any
  environmental skip with its test-reported reason.

## Relevant Files

| File | Role |
|------|------|
| `scripts/run_tests.py` | Shared full-run partitioning and validated duration-data loading. |
| `tests/test_run_tests.py` | Allocator, mode, coverage, and failure-path proofs. |
| new `tests/shard_durations.json` | Proposed small, versioned module-duration data file. |
| `CONTRIBUTING.md` | Partition semantics, reproducible measurement, and weight refresh procedure. |

These paths and task-local lifecycle artifacts are the implementation scope.
No task branch edits queue, queue archive, or project plan. Avoid a new
dependency, dynamic worker-queue service, or general benchmark framework.

## Technical Context

The runner sorts discovered unittest IDs and assigns positions modulo the
worker count. This balances test counts, not execution time. Modules are
split between processes and may each rebuild process-local fixtures.

Discovery on commit `a7cdf49b7d417bffce3e84ed4ca5bde5f289c9ad`, Python 3.15,
macOS with ten logical CPUs, produced these sequential full clean-clone runs:

| Workers | Whole-command seconds | Outcome |
|---------|----------------------:|---------|
| 2 | 2626.998 | 1900 tests, zero failures/errors, one environmental skip |
| 4 | 1562.796 | Same test IDs/digest and outcome |
| 8 | 1068.690 | Same test IDs/digest and outcome |

At eight workers the individual shard times were approximately 556, 566, 575,
594, 676, 705, 835, and 1065 seconds. Summed per-test duration was 5569.035
seconds; the longest shard contained the plugin-distribution interruption
matrix (464.102 seconds) and 300-task briefing (153.975 seconds). An offline
longest-processing-time simulation grouping whole modules predicted about
696 seconds, versus the observed 1065-second longest shard. This is a forecast
at unchanged costs, not a measured optimized execution: module-local fixture
reuse, new proof tests, and contention may change it.

The first exploratory two-worker run used excessively nested temporary paths,
causing four console line-wrapping assertion failures; it was excluded. The
three successful measurements used a short temporary root and identical
instrumentation. The shared environmental skip was the AppleScript compiler
test's inability to resolve the iTerm2 dictionary. A fresh baseline and its
weights must be obtainable without any temporary discovery files surviving.

## Suggested Implementation

Use one small allocator shared by full parallel and standalone shard modes.
Group by discovered module, use recorded module durations, sort with stable
ties, and allocate to the least-loaded effective shard. Keep tests within each
module in stable ID order. Do not cache passing test results or infer that
unaffected tests need not run. Prefer module affinity over a table of special
cases tailored to the currently slowest test IDs.

## Constraints and Out of Scope

No product-code changes, fixture optimizations, splitting or sampling matrices,
test removals, new automatic skips, changed worker cap/default, CI changes,
external infrastructure, or weaker lifecycle validation. Preserve frozen
workflow/host files and the installed Meridian self-hosting boundary. Do not
create `.cardine/` in this repository or apply setup to the real home. Only
installed Meridian lifecycle commands write `.meridian/tasks/140.json`.

## Dependencies

- **Depends on**: 138
- **Blocks**: none.
- Independent of task 139; neither task is authorization to implement the
  other. Serialize performance measurements on the same machine. Refresh
  evidence if an intervening fixture change invalidates the comparison.

## Validation

Focused development:

- `python3 scripts/run_tests.py --parallel --module test_run_tests`
- `python3 scripts/run_tests.py --parallel --module test_command_context`

Counted final validation:

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel 8 --clean-clone`
- `git diff --check`

Use `python3 scripts/run_tests.py --parallel 8 --clean-clone` for the baseline
as well. The final clean-clone run includes repository checks and the complete
parallel suite, so do not duplicate them as separate counted commands. Capture
phase/shard evidence externally if needed. Complete any candidate-validation
gate required by the local integration workflow. Record actual measurements
and deviations in `tasks/handoffs/140.md` using the local completion template.

## Execution

Execute only after `Proceed with 140`, in the deterministic task worktree
prepared by the installed Meridian lifecycle. This task requests neither
delegation nor work on another queue item.
