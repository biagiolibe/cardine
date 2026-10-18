# Task 030 — Classify every stop code and prove each recovery command

> **ID**: `030`
> **Category**: Quality
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Stop policy review, 2026-10-18
> **Origin**: friction

## Objective

Make the registry's `human_decision` field trustworthy, because ADR decision
12 turns it into the rule for when an agent stops. Prove that
each recoverable code returns a command that runs unchanged and advances the
task. Two stops in this repository returned a command that did not: task 015
(`TASK_STATE_MISSING`, fixed by task 018) and task 021 (`WRONG_WORKTREE`
after a dirty Resume, fixed by task 028).

## Acceptance Criteria

- [ ] Every code in `capabilities/stop-codes-v1.json` is classified with the
  table of decision 12. The handoff lists every code whose `human_decision`
  value changes, with the reason. A code needs a person when the recovery
  needs authority, a decision, a permission, or information that the agent
  lacks. Examples are a rejected push, a host sandbox that denies a write, or
  a missing project declaration.
- [ ] Each entry gains a `resolution` field with the value `guardrail`,
  `recoverable`, or `failing-work`. `scripts/check_repository.py` rejects a
  missing value, and rejects `human_decision: true` on any class other than
  `guardrail`.
- [ ] Each `recoverable` code has a test that builds the state, takes the
  command from the stop, runs it unchanged, and asserts that the task
  advances or the next command succeeds. A code that cannot be tested this
  way is listed in the handoff with the reason and becomes a task proposal.
  If the work does not fit the 3-hour bound, stop at a code boundary and
  propose the remaining codes as a follow-up task.
- [ ] The journal records the `resolution` class with each blocked line.
  `meridian report flow`, or the journal reader that reports stops, counts
  stops per task by class.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `capabilities/stop-codes-v1.json` | The registry. |
| `scripts/check_repository.py` | Registry checks. |
| `src/cardine/stops/` | Registry loading and rendering. |
| `src/cardine/shared/journal.py` | Journal lines for stops. |
| `tests/` | Recovery tests per code. |

## Technical Context

- The registry has 55 codes. Their `class` values are `tool`,
  `command-exit`, and `judgment`, and 14 have `human_decision: true`.
- Some current values look wrong under decision 12. `CLEANUP_BLOCKED` has
  `human_decision: false`, but one of its causes is a sandbox that denies the
  write, which only a person can lift. Task 007 made the cleanup itself
  recoverable; the classification belongs here.

## Out of scope

Changes to the agent instructions (task 029) and the `cardine run` engine
(work item 8).

## Dependencies

- **Depends on**: 028
- **Blocks**: none

## Validation

- `python3 scripts/check_repository.py`
- `python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .`
- `python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`
