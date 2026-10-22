# Task 079 — Freeze the remaining human contract fields in the snapshot (N1, part 1)

> **ID**: `079`
> **Category**: Feature
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Decision 13 planning, 2026-10-22
> **Origin**: maintenance

## Objective

Implement the first half of row N1 of `docs/TEXT_GATE_INVENTORY.md`. Decision
13 says that human intent is read once at creation and frozen in the contract
snapshot. Seven readers still parse the record after creation because the
snapshot lacks the fields they need (entries T-09, T-10, T-11, T-16, T-17,
T-18, T-36). Add those fields to the snapshot and write them at creation; task
080 switches the readers.

## Acceptance Criteria

- [ ] `schemas/task-state-v1.schema.json` and the contract snapshot gain
  `dependencies`, `title`, `priority`, `phase`, `origin`, `deliverables`
  (for spikes), `authority` citations, and the stable record path.
  `cardine task new` resolves them once from the record and validates them
  with the rest of the contract before publishing.
- [ ] A person changes a frozen field after creation through one CLI command
  that revalidates the record, rewrites the snapshot atomically, and
  records the change in the state history. Editing the record alone
  changes no gate; audit reports the drift and names that command.
- [ ] The handling of a snapshot created before this task, without the new
  fields, is stated and tested: a diagnostic with the command that
  completes it, never a fallback to record prose.
- [ ] Tests cover creation with every field, a dependency on an unknown ID, a
  record edited after creation (no gate changes, audit reports drift), the
  update command, and an older snapshot.
- [ ] No reader is switched in this task; the known-violation table of task
  078 is unchanged.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes product code, product templates, and tests
  only.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/079.json`, which only
  the installed `meridian task close 079` writes.
- [ ] A test expectation that this task makes stale is updated in this task
  without weakening any other assertion. The parallel suite reports the
  same coverage `total` before and after the task, except for new or
  deliberately removed tests, which the handoff lists with their reason.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/TEXT_GATE_INVENTORY.md` | Authority: row N1 and entries T-09, T-10, T-11, T-16, T-17, T-18, T-36. |
| `schemas/task-state-v1.schema.json`, `src/cardine/tasks/state.py` | Schema and validation. |
| `src/cardine/tasks/creation.py`, `src/cardine/tasks/contract.py`, `src/cardine/cli.py` | Creation path and the update command. |
| `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` | "Creation and stable records". |

## Technical Context

- Work item 7 continues after this task: 080 switches the readers, then 070
  (SS7).
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Switching readers (task 080), row N2, and work item 8.

## Dependencies

- **Depends on**: 077, 078
- **Blocks**: 080

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
