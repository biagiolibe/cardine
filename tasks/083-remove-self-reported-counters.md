# Task 083 — Remove the self-reported evidence counters (RX1)

> **ID**: `083`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Work item 8 planning, 2026-10-23
> **Origin**: maintenance

## Objective

Implement row RX1 of `docs/RULE_ENFORCEMENT_INVENTORY.md`, section "Proposed
new rows". Decision 5 of `docs/ADR_CARDINE_1_0.md` replaced the budget
counters with the validation retry limit, and rule 1 of decision 14 forbids a
command that the engine makes redundant. `cardine execution evidence`
(`diagnostic`, `captures`, `expansions`) and `cardine execution investigate
--scope` still ask the agent to report its own work.

## Acceptance Criteria

- [x] `cardine execution evidence` and `cardine execution investigate` are
  removed from the CLI with their implementation in
  `src/cardine/tasks/recording.py` and wherever else they live, and with
  their tests. No product code reads what they wrote.
- [x] The template text that asks agents to run them or report those counters
  is removed (inventory entries TB-10, CR-07, EE-02, IM-14). The template
  change follows the pre-1.0 rule of task 031: the owning capability's
  version rises and its baseline is rewritten, with no migration and no
  `VERSION` change.
- [x] `cardine execution validate` and every other command that records real
  results keep working; the handoff lists what the removal touched and
  confirms that no gate lost a fact it needed.
- [x] Every row of the known-violation table of `tests/test_text_gates.py` for
  entries in `src/cardine/tasks/recording.py` and the `build_parser`
  options of `src/cardine/cli.py` that this task removes is deleted, and
  the test passes. The handoff lists the deleted rows and any row of those
  entries that remains, with its destination.
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
- [x] `.meridian/` is unchanged, except `.meridian/tasks/083.json`, which only
  the installed `meridian task close 083` writes.
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
| `docs/RULE_ENFORCEMENT_INVENTORY.md` | Authority: row RX1 and entries TB-10, CR-07, EE-02, IM-14. |
| `src/cardine/cli.py`, `src/cardine/tasks/recording.py` | The commands to remove. |
| `templates/single/` | Text that asks for the counters. |
| `capabilities/catalog-v1.json`, `capabilities/marker-baselines.json` | Capability version and baseline. |

## Technical Context

- It runs before tasks 084 and 085, which edit nearby rows of the ratchet
  table and `tasks/recording.py`, and before row RE3 of the run engine plan.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Rows N2a and N2b, the engine of work item 8, and every other inventory entry.

## Dependencies

- **Depends on**: —
- **Blocks**: 084

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

Implemented RX1 and verified every acceptance criterion on commit
`2af046304aa30907b9fa131eaee00950f1f92a01`. All six required validation
commands passed; local and clean-clone suites each ran 1,284 tests without
failures, errors or skips. See [the handoff](handoffs/083.md) for the reader
inventory, retained gate facts, marker versions, ratchet destinations, coverage
changes and the three validation attempts. Installed Meridian owns closure
and integration records.
