# Task 080 — Read the human contract fields from the snapshot (N1, part 2)

> **ID**: `080`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Decision 13 planning, 2026-10-22
> **Origin**: maintenance

## Objective

Implement the second half of row N1 of `docs/TEXT_GATE_INVENTORY.md`: switch
the readers of entries T-09, T-10, T-11, T-16, T-17, T-18, and T-36 from
record prose to the snapshot fields that task 079 added.

## Acceptance Criteria

- [x] Dependency checks at start (`check_dependencies`), the status service
  (`tasks/status.py`: dependencies, title, phase, priority), identity
  resolution, the flow report origin, the Codex read guard authority
  exemptions, and the console title lookup read the snapshot. None parses
  the record after creation.
- [x] Tests prove that a record edited after creation, with a different
  `Depends on`, title, priority, or authority list, changes neither
  startability, ordering, identity, nor the read guard decision.
- [x] Spike `deliverables` are available to the landing check of entry T-16;
  switching that check is row N2, and the handoff says so.
- [x] Every known-violation entry of `tests/test_text_gates.py` (task 078)
  that this task removes is deleted from its table, and the test passes.
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
- [x] `.meridian/` is unchanged, except `.meridian/tasks/080.json`, which only
  the installed `meridian task close 080` writes.
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
| `docs/TEXT_GATE_INVENTORY.md` | Authority: row N1 and its entries. |
| `src/cardine/tasks/preflight.py`, `status.py`, `identity.py` | Dependency, status, and identity readers. |
| `src/cardine/shared/flow.py`, `shared/authority.py`, `shared/context.py`, `scripts/codex_read_guard.py` | Origin and authority readers. |
| `src/cardine/console/snapshot.py`, `shared/console_workflow.py` | Title lookup. |

## Technical Context

- Task 070 (SS7) follows and also edits the console; it starts after this task
  integrates.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Row N2 (Class, Review, Validation, host impact), work item 8, and display
changes that belong to SS7.

## Dependencies

- **Depends on**: 079
- **Blocks**: 070

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

## Completion evidence

- Implemented in `c946a5068030e3868ddbfb7c034fd9c5af9cc94c`, including preceding implementation and fixture commits.
- Every required validation command passed. The full and clean-clone suites each ran 1321 tests with zero failures/errors and one named environment skip.
- See `tasks/handoffs/080.md` for exact commands, coverage accounting, frozen-file verification, and integration scope.
- Runtime readers use frozen human intent. The known-violation table falls from 102 to 96 entries without new violations.
- Spike deliverables are available in the snapshot; switching the T-16 landing check remains N2. SS7 retains the console section/display work.
