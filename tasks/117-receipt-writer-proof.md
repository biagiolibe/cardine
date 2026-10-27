# Task 117 — Prove the receipt writer once and test each operation's own boundaries

> **ID**: `117`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Coordinator CI analysis, 2026-10-27
> **Origin**: maintenance

## Objective

The suite's test time grew by about 76 percent after task 100 (module sum 4178
s to 7342 s, coordinator measurement on 2026-10-27), and CI went from about 3
to 8–10 minutes. Almost all of it comes from the interruption matrices of rule
4 that rows RE4a to RE7a added. Seven tests alone take about 1700 s, for
example `test_every_host_and_receipt_boundary_restarts_same_session` (362 s),
because each case rebuilds the whole fixture.

The matrices repeat, for every operation, every phase, and every host, all the
boundaries of the generic receipt writer (`write_operation` in
`src/cardine/lifecycle/receipts.py`: intent, staged pair, state replace,
result receipt). That writer is one mechanism. This task proves its
convergence once for every operation kind, keeps every boundary that is
specific to an operation in that operation's tests, and adds a test that fails
if any effect bypasses the writer, so no interruption guarantee is lost.

## Acceptance Criteria

- [x] **Before.** Before any change, the handoff records for each of
  `tests/test_run_host_roles.py`, `tests/test_run_review.py`,
  `tests/test_run_control.py`, `tests/test_run_cleanup.py`,
  `tests/test_run_console.py`, `tests/test_run_integration.py`,
  `tests/test_run_ci.py` and `tests/test_run_receipts.py`: the
  interruption points the module kills, counted by instrumenting its kill
  helper during a run, the number of cases, and the module's wall time
  with `python3 scripts/run_tests.py --parallel --module <module>`. It
  also records one full parallel run.
- [x] **Writer proved once.** One test module proves that the receipt writer
  converges at every boundary it exposes, for every operation kind the
  product writes: it kills the writer immediately before and after each
  boundary, reruns, and checks one receipt, no duplicate commit, and
  preserved foreign files. The set of operation kinds comes from the
  product, not from a list in the test. If the product has no enumerable
  set of kinds that the writer enforces, this task adds one in
  `src/cardine/lifecycle/receipts.py`; that is the only product change
  allowed. A new kind then fails the test until it is covered.
- [x] **Every effect goes through the writer.** A test fails if any operation
  changes a task state file or a receipt without going through
  `write_operation`. It checks a fact, at runtime or statically, the way
  task 100 checks the single Git gateway, and never reads prose.
- [x] **Operation boundaries stay.** Each operation's matrix still kills every
  boundary specific to that operation, such as host spawn and response,
  merge, push, CI query, worktree removal, branch deletion, and lease
  files, plus at least one receipt boundary that proves the operation is
  wired to the writer. Points that do not depend on the host run for one
  host; host-specific points run for every host.
- [x] **After.** The handoff lists, per module, the killed points before and
  after. Every removed case is a generic receipt point that the writer
  proof covers for the same operation kind. It records the case counts and
  wall times after the change, on the same machine, and the full parallel
  run.
- [x] Every remaining test keeps every assertion, and the subprocess ceilings
  of `tests/test_command_context.py` still hold.
- [x] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes tests, and at most the operation-kind set of
  `src/cardine/lifecycle/receipts.py`.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/117.json`, which only
  the installed `meridian task close 117` writes.
- [x] A test expectation that this task makes stale is updated in this task
  without weakening any other assertion. The parallel suite reports the
  same coverage `total` before and after the task, except for new or
  deliberately removed tests, which the handoff lists with their reason.
- [x] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `src/cardine/lifecycle/receipts.py` | The receipt writer, its boundaries, and the operation kinds. |
| `tests/test_run_receipts.py` | The existing writer tests; the writer proof may live here or in a new module. |
| `tests/test_run_host_roles.py` | An interruption matrix to reduce. |
| `tests/test_run_review.py` | An interruption matrix to reduce. |
| `tests/test_run_control.py` | An interruption matrix to reduce. |
| `tests/test_run_cleanup.py` | An interruption matrix to reduce. |
| `tests/test_run_console.py` | An interruption matrix to reduce. |
| `tests/test_run_integration.py` | An interruption matrix to reduce. |
| `tests/test_run_ci.py` | An interruption matrix to reduce. |

## Authority excerpt

The parts of the plan and inventories this task needs, extracted from the
files on `main` when the record was written, so that the task reads them here
instead of the whole documents:

> From `docs/ADR_CARDINE_1_0.md`, section "14. Robust against weak and strong agents", item 4:
>
> 4. **Every effect can be repeated.** Interrupting any command at any effect
>    boundary, such as a commit, a state write, a merge, a push, or a cleanup,
>    and running it again converges to the same result. Two tasks that reach
>    integration together wait for each other instead of stopping.
>
## Technical Context

- Coordinator measurement, 2026-10-27, eight modules at a time:
  test_run_integration 611 s, test_run_cleanup 548 s, test_run_host_roles 517
  s, test_run_control 509 s, test_run_review 416 s, test_run_console 314 s,
  test_run_ci 305 s. CI suite time went from 165 s at task 100 to 350–610 s at
  task 115.
- In `test_run_host_roles.py` the matrix runs 2 hosts times the host points
  plus 3 phases times every receipt point, with a full `setUp` per case; the
  receipt points do not depend on the host.
- This task shares no file with task 116, which is documentation only, and can
  run in parallel with it.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.
- During development, run only what the change touches: `python3
  scripts/run_tests.py --parallel --module <name>` for a module, class, or
  test, and `python3 scripts/run_tests.py --parallel --last-failed` after a
  failed full run. Both print only failures. Do not run `python3 -m unittest`
  directly, and run the full suite once, as the counted clean-clone
  validation.

## Out of scope

Other test modules, including `tests/test_run_recovery.py` and
`tests/test_run_delivery.py`; shard scheduling; any change to what an
operation or the writer does, beyond the operation-kind set.

## Dependencies

- **Depends on**: 115
- **Blocks**: none

## Developer decisions given in advance

The developer records these decisions in the task contract, so that they
hold however the task is launched, including a bare `Proceed with <TASK-ID>`
from the project console (ADR decision 12). None of these situations needs a
new decision from the developer. After fixing a failure, continue with
revalidation in the same turn; do not stop to report the fix.

- A required command that exits non-zero because of a precondition the agent
  can satisfy (command order, an uncommitted worktree, a missing argument):
  satisfy it and run the command again, once.
- A validation failure caused by this task's own changes, including a name
  collision, a stale reference, a broken link, or a test expectation that the
  task made obsolete: fix it and revalidate, at most 3 counted attempts. A
  test that fails once and passes on an identical unchanged rerun is
  intermittent, recorded in the handoff, and does not count. Only after 3
  counted failures stop with `BLOCKED VALIDATION_FAILED` and a summary of the
  failures.
- A counted attempt is one run of the whole Validation section on a
  committed implementation that the agent considers complete. Test runs
  during implementation are development, not attempts, however many fail.
  An unfinished implementation is never a reason to stop: finish it first.
- A `BLOCKED <CODE>` from a Meridian command whose entry in
  `capabilities/stop-codes-v1.json` of the primary checkout's `main` has
  `human_decision: false`: run the command the stop names, once. If it stops
  again with the same code, stop.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope
  remain stops.

## Validation

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone run executes `scripts/check_repository.py` and the parallel
suite on a clone of the committed HEAD, so the task does not run them again
in the worktree as counted validation.

## Completion evidence

Implemented in `6d2b0ad77b80cb01b046677d4c961baa8a1eae58`. See
`tasks/handoffs/117.md` for instrumented before/after point inventories, case
counts, wall times, unchanged assertion checks and the successful 1838-test
clean-clone result. All operation-specific interruption points remain; 129
generic operation cases moved to the shared writer proof.
