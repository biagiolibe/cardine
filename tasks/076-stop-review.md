# Task 076 — Review every stop the tool could resolve itself (decision 14)

> **ID**: `076`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Decision 14 planning, 2026-10-22
> **Origin**: maintenance

## Objective

Write `docs/STOP_REVIEW.md`. Rule 3 of decision 14 says that a stop for
something the tool can determine is a defect, and decision 12 keeps stops for
what a person brings. This repository's journal records 15 stops: eight
`WRONG_WORKTREE` and five `COMMAND_REFUSED`, one of them a task waiting for
another task's integration lease. The review examines every registered stop
code and every recorded stop and says which become resolution, waiting, or a
next action.

## Acceptance Criteria

- [ ] `docs/STOP_REVIEW.md` exists, in English, names the `main` commit it was
  taken on, and gives the commands it used, so that it can be repeated.
- [ ] It examines all codes of `capabilities/stop-codes-v1.json`. For each
  guardrail it answers what the person brings: authority, a decision, or
  information. A guardrail with no answer is proposed as recoverable,
  waiting, or failing work, with the resolution the tool performs or the
  next action it returns.
- [ ] It proposes merging codes that differ only in wording or emitter, and
  removing codes that no emitter raises, consistently with the split of
  mixed codes in row RE2.
- [ ] It analyses every `blocked` entry of this repository's
  `.git/meridian-journal.jsonl` and every stop pasted in the coordinator's
  task handoffs under `tasks/handoffs/`: the code, the situation, and
  whether the tool could have resolved it. For `WRONG_WORKTREE` and the
  integration lease it describes the behavior that replaces the stop:
  location resolution by the tool (decision 6) and a bounded wait for
  another task's integration.
- [ ] It covers rule 4 of decision 14 for stops: which recoveries are not
  idempotent today, and the interruption points where rerunning the same
  command does not converge.
- [ ] It gives the expected count of guardrail codes after the proposals, and
  the journal counts this repository would have had with them.
- [ ] Every finding that needs a change has a destination: a named row of
  `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` (SS6, SS7) or
  `docs/RUN_ENGINE_PLAN.md` (RE1 to RE7) whose scope text already covers
  it, a one-sentence amendment to such a row, a proposed new row with size
  and placement, or removal. Where an existing row does not cover a
  finding, the document says so.
- [ ] It cross-references `docs/TEXT_GATE_INVENTORY.md` (task 073) instead of
  repeating its entries.
- [ ] No file changes outside `docs/STOP_REVIEW.md` and this task's records:
  the task record, its handoff, and its archive under `tasks/done/`.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/076.json`, which only
  the installed `meridian task close 076` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/ADR_CARDINE_1_0.md` | Decisions 12, 13, and 14; decision 6 for location independence. |
| `docs/RUN_ENGINE_PLAN.md`, `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` | Planned destinations. |
| `docs/TEXT_GATE_INVENTORY.md` | Task 073: text gates, already inventoried. |
| `capabilities/stop-codes-v1.json`, `docs/ADR_STOPS_AND_DENIALS.md` | Stop registry and its classes. |
| `src/cardine/stops/` and the emitters under `src/cardine/` | Where each code is raised. |
| `.git/meridian-journal.jsonl`, `tasks/handoffs/` | Recorded stops of this repository (read only). |

## Technical Context

- The journal belongs to the installed Meridian 1.4.1 lifecycle of this
  repository; its codes match Cardine's registry closely. Read it only; never
  write to it.
- This task changes no code. Tasks 074, 075, and 076 write different documents
  and can run at the same time, and alongside the work item 7 tasks.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Changing code, templates, tests, or the stop registry; writing the work item 8
task records; this repository's own installed Meridian.

## Dependencies

- **Depends on**: —
- **Blocks**: the work item 8 task records

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
- `git diff --check`
- `python3 -m unittest tests.test_no_meridian_identifiers`

This task changes documentation only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff. It still runs the identifier guard, which scans documentation.
