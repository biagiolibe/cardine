# Task 060 — Remove the Meridian name and the old states from the template text (work item 5b)

> **ID**: `060`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~2.5h
> **Assigned to**: unassigned
> **Session**: Work items 5b and 7 planning, 2026-10-20
> **Origin**: maintenance

## Objective

Start work item 5b of `docs/ADR_CARDINE_1_0.md`. The single template set still
names the product "Meridian" in its prose and uses the old status words in 19
lines. Make the text of `templates/single/` describe Cardine and the single
state vocabulary of `docs/SINGLE_WORKFLOW_PLAN.md`, section 3.

## Acceptance Criteria

- [x] No text under `templates/single/` names Meridian, except the
  `MERIDIAN:BEGIN` and `MERIDIAN:END` markers (task 061) and the
  `.codex/rules/meridian.rules` file and its references (work item 9).
- [x] No text under `templates/single/` uses `READY_FOR_REVIEW`,
  `CHANGES_REQUESTED`, `ACCEPTED`, `Review: REQUIRED`, or `Review:
  NOT_REQUIRED` as a state or field value. The text uses `queued`,
  `in_progress`, `in_review`, `done`, and `cancelled`, and the review
  option `required` or `not_required`.
- [x] The archived-record Resume case in the `bounded-worktree-lifecycle`
  block no longer says "state is DONE", which the product's `task close`
  does not write before landing (`tasks/handoffs/055.md`). It describes
  what the product actually does.
- [x] Every capability block whose protected text changes gets a version bump,
  with `requiredVersion` and `capabilities/marker-baselines.json` updated
  in the same commit, under the pre-1.0 rule of `CONTRIBUTING.md`. Task
  061 then restarts all versions at `v1`.
- [x] The group 2 allowances in `tests/test_no_meridian_identifiers.py` for
  template prose are narrowed to what remains, and each remaining entry
  names task 061 or work item 9.
- [x] Skills, slash commands, the plugin, and the Codex rules file and profile
  are not changed (work item 9).
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/060.json`, which only
  the installed `meridian task close 060` writes.
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
| `templates/single/` | The text to change. |
| `capabilities/markers-v1.json`, `capabilities/marker-baselines.json` | Version bumps for changed blocks. |
| `tests/test_no_meridian_identifiers.py` | Group 2 allowances. |
| `docs/SINGLE_WORKFLOW_PLAN.md` | Section 3, the state vocabulary. |

## Technical Context

- On `main` at `d236eee`, a case-insensitive search for `meridian` finds 267
  matches under `templates/`, most of them markers, and 19 lines with old
  status words in `PROJECT_WORKFLOW.md` and eight documents under
  `templates/single/docs/`.
- Decision of 2026-10-20 in the ADR: skills, slash commands, the plugin, and
  the Codex rules move to work item 9.

## Out of scope

Markers (task 061), skills, slash commands, the plugin, the Codex rules file
and profile (work item 9), and every frozen file.

## Dependencies

- **Depends on**: 058
- **Blocks**: 061

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
