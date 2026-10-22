# Task 072 — Give the delivery commit field a literal form

> **ID**: `072`
> **Category**: Bug
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Defect triage, 2026-10-22
> **Origin**: maintenance

## Objective

`cardine execution ready-check` and `execution deliver` stop with
`EVIDENCE_INCOMPLETE` when the handoff's `Current task commit` describes the
coming delivery commit in the agent's own words. `_delivery_current_commit` in
`src/cardine/lifecycle/execution.py` accepts a full SHA, a value containing
`Deliver <TASK-ID> for review`, or a value containing both the HEAD subject
and the branch. The completion report template only says that the field may
use "a descriptive form that identifies the commit by subject and branch", so
the exact subject that delivery will create is learned only from the failure.
Each stop costs a correction commit, a new delivery, and a new session.

The defect recurred twice on Meridian 1.4.1 in a governed project, and Cardine
inherited the same check and template text. Make the delivery form literal and
copyable, and make the stop say exactly what to write.

## Acceptance Criteria

- [ ] The completion report template of `templates/single/docs/` gives, for a
  review-required task, the literal line to copy: ``- Current task commit:
  the task commit `Deliver <TASK-ID> for review` on branch `<task-branch>`
  (created by delivery; see `git log -1 <task-branch>`)``, and says that
  delivery creates that subject. The general descriptive form stays for
  the other cases.
- [ ] When `_delivery_current_commit` rejects a value, the
  `EVIDENCE_INCOMPLETE` detail contains the exact line to write, with the
  real task ID and branch filled in, and the value it found.
- [ ] The accepted forms do not widen: a description that names an earlier
  commit, the validated base `main` commit, or no identifiable commit is
  still rejected. Tests cover the literal form, an own-words description
  of the coming delivery (rejected, with the copyable line in the detail),
  a full SHA, and the base commit.
- [ ] The template change follows the pre-1.0 rule of task 031: the owning
  capability's version rises and its baseline is rewritten, with no
  migration and no `VERSION` change.
- [ ] This repository's own `docs/COMPLETION_REPORT_TEMPLATE.md` is a frozen
  copy of the installed Meridian and stays unchanged.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/072.json`, which only
  the installed `meridian task close 072` writes.
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
| `src/cardine/lifecycle/execution.py` | `_delivery_current_commit` and the readiness gate. |
| `templates/single/docs/COMPLETION_REPORT_TEMPLATE.md` | Product template text for the commit fields. |
| `capabilities/catalog-v1.json`, `capabilities/marker-baselines.json` | Capability version and baseline of the changed template. |
| `docs/RUN_ENGINE_PLAN.md` | Row RE3: the engine owns evidence and handoff writes. |

## Technical Context

- The self-referential field exists because a committed handoff cannot name
  its own commit. Work item 8 makes the engine own delivery and evidence
  writes (`docs/RUN_ENGINE_PLAN.md`, row RE3), and the commit fields should
  then be derived rather than written by the agent; `PROJECT_PLAN.md` records
  that as a deferred item for work item 8. This task is the bounded fix until
  then.
- Meridian 1.4.x receives fixes only for blocking defects (ADR decision 10).
  This defect has a workaround, writing the literal `Deliver <TASK-ID> for
  review` subject, so it gets no Meridian fix.
- Task 070 (single source SS7) also edits `templates/single/` and the
  capability baseline; it waits for this task. Task 068 can run at the same
  time.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Removing or deriving the commit fields (work item 8); changing other handoff
fields; any Meridian release.

## Dependencies

- **Depends on**: 067
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
