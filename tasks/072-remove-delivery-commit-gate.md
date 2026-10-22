# Task 072 — Remove the delivery commit gate

> **ID**: `072`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Rescoped from task 073, 2026-10-22
> **Origin**: maintenance

## Objective

Implement the rescoped task 072 of `docs/TEXT_GATE_INVENTORY.md`, section
"Task 072", under decision 13 of `docs/ADR_CARDINE_1_0.md`.

`delivery_readiness` rejects a delivery when the handoff's `Current task
commit` line does not match one of three text forms. The inventory verified
that this check adds no fact: every fact the line claims is already proved
from Git and command results, and no other product code reads the handoff's
commit fields. Remove the gate and the fields, so that no agent has to write a
commit description and no wording can stop a delivery.

## Acceptance Criteria

- [ ] `_delivery_current_commit` and its call in `delivery_readiness`
  (`src/cardine/lifecycle/execution.py`) are deleted, with their tests. A
  delivery whose handoff has no commit fields, or any text in them, passes
  when the Git and evidence facts hold.
- [ ] The tests that remain prove that delivery still rejects the cases those
  facts cover: no committed implementation after the prepared base, an
  uncommitted handoff, missing or stale validation evidence, and later
  commits that change more than the handoff.
- [ ] `templates/single/docs/COMPLETION_REPORT_TEMPLATE.md` no longer has the
  `Implementation commit`, `Validated task commit`, `Validated base main
  commit`, and `Current task commit` lines or the paragraph on the
  descriptive form; `templates/single/docs/workflows/REVIEW.md` no longer
  has the commit-field steps. No template asks an agent to write `Deliver
  <TASK-ID> for review`; Cardine alone creates that subject.
- [ ] The template change follows the pre-1.0 rule of task 031: the owning
  capability's version rises and its baseline is rewritten, with no
  migration and no `VERSION` change.
- [ ] The `Branch`, `Worktree`, and ``Base `main` commit`` check of
  `src/cardine/worktree/checkout.py` (inventory entry T-23) and the stored
  delivery commit (row RE3) stay out of scope; the handoff says so.
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
| `docs/TEXT_GATE_INVENTORY.md` | Authority: section "Task 072" and entries T-22, TPL-04, TPL-05, TPL-08. |
| `src/cardine/lifecycle/execution.py` | `_delivery_current_commit` and `delivery_readiness`. |
| `templates/single/docs/COMPLETION_REPORT_TEMPLATE.md`, `templates/single/docs/workflows/REVIEW.md` | Template text to remove. |
| `capabilities/catalog-v1.json`, `capabilities/marker-baselines.json` | Capability version and baseline. |

## Technical Context

- Meridian 1.4.x receives fixes only for blocking defects (ADR decision 10).
  Contoso works around the defect by writing the literal `Deliver <TASK-ID>
  for review` subject.
- Task 070 (single source SS7) edits `templates/single/` too. Run this task
  before 070 starts, or after 070 integrates; never at the same time.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

The handoff checks of row N3 of the inventory, the work item 8 engine, and any
Meridian release.

## Dependencies

- **Depends on**: 073
- **Blocks**: 078

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
