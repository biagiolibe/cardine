# Task 084 — Read class, review policy, and deliverables from the snapshot (N2a)

> **ID**: `084`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 8 planning, 2026-10-23
> **Origin**: maintenance

## Objective

Implement the first half of row N2 of `docs/TEXT_GATE_INVENTORY.md`. Decision
13 says that the record is read once at creation; after that, gates read the
contract snapshot. Product code still reads the task class, the review policy,
and spike deliverables from the record, and two paths still resolve a contract
after creation.

## Acceptance Criteria

- [x] The `Class` reads of entry T-13, the `Review` reads of entry T-14 that
  remain, and the deliverables read of entry T-16
  (`integration/merge.py::_spike_disallowed_paths`) use
  `state["contract"]`. `tasks/importer.py` keeps its reads as the
  documented legacy route (entry T-31).
- [x] Entry T-02: `transition_task_state` no longer backfills a missing
  contract and `execution_start` no longer re-resolves options. A task
  whose state has no contract snapshot gets a diagnostic naming the
  command that completes it, and no gate falls back to the record.
- [x] Amendment A-N2-1 of `docs/RULE_ENFORCEMENT_INVENTORY.md`: `task outcome
  ANSWERED` requires every frozen deliverable path to be changed on the
  task branch.
- [x] Tests prove that a record edited after creation, with a different
  `Class`, `Review`, or deliverable, changes no gate.
- [x] Every row of the known-violation table of `tests/test_text_gates.py` for
  entries T-02, T-13, T-14, and T-16 that this task removes is deleted,
  and the test passes. The handoff lists the deleted rows and any row of
  those entries that remains, with its destination.
- [x] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes product code, product templates, and tests
  only.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/084.json`, which only
  the installed `meridian task close 084` writes.
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
| `docs/TEXT_GATE_INVENTORY.md` | Authority: row N2 and entries T-02, T-13, T-14, T-16. |
| `docs/RULE_ENFORCEMENT_INVENTORY.md` | Amendment A-N2-1. |
| `src/cardine/tasks/transitions.py`, `preflight.py`, `audit.py`, `src/cardine/lifecycle/execution.py`, `commands.py`, `src/cardine/review/verdict.py`, `src/cardine/integration/merge.py`, `projections.py`, `src/cardine/console/snapshot.py` | The readers. |

## Technical Context

- Task 085 follows and edits `preflight.py` and `execution.py` too; the two
  never run at the same time.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Validation commands, host impact, headings, and locations (task 085); the
importer (work item 10); the engine of work item 8.

## Dependencies

- **Depends on**: 083
- **Blocks**: 085

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

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

## Completion

Implemented and verified on 2026-10-23. Class, review policy and spike landing
deliverables use the frozen contract; missing snapshots require explicit
contract update. ANSWERED requires all frozen deliverables in the committed
task-branch diff. Both full suites passed 1,289 tests with one named host-only
skip. Coverage grew by five tests; no existing test was removed.

Validation evidence, deleted ratchet rows, remaining legacy destinations,
fixture repairs and an unassigned creation-parser follow-up requirement are
recorded in `tasks/handoffs/084.md`. Installed Meridian 1.4.1 owns closure;
the frozen local workflow and host configuration were not changed.
