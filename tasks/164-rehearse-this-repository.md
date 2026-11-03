# Task 164 — Rehearse the conversion of this repository (C6a)

> **ID**: `164`
> **Category**: Infrastructure
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Work item 10 records, 2026-11-03
> **Origin**: maintenance

## Objective

Implement row C6a of `docs/CONVERSION_PLAN.md`, work item 10 of
`docs/ADR_CARDINE_1_0.md`. The row fixes the scope, the files, the tests, and
the interruption boundaries; this record adds the developer's decisions and no
design.

rehearsal on a clone of this repository; evidence in the handoff. The last task Meridian closes.

## Acceptance Criteria

- [ ] Row C6a is implemented as its line in the excerpt describes it.
- [ ] This task changes only its own record, archive, handoff, and state file. Any
  disposable project stays outside the repository, under a disposable home.
  A product defect found here is a finding in the handoff for the coordinator,
  who writes a new row; it is not fixed in this task.
- [ ] The row's evidence is in the handoff: Receipt, verifier output, unchanged original digest.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/164.json`, which only
  the installed `meridian task close 164` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `tasks/handoffs/<id>.md` | The files this row edits, as the plan lists them. |

## Authority excerpt

The parts of the plan this task needs, extracted from the file on `main` when
the record was written, so that the task reads them here instead of the whole
document:

> From `docs/CONVERSION_PLAN.md`, row C6a:
>
> | C6a / 2h | Meridian: rehearsal on a clone of this repository; evidence in the handoff. The last task Meridian closes. | `tasks/handoffs/<id>.md` | Receipt, verifier output, unchanged original digest. | None. | C2f, C3f, C4b, C5a, C5b, C5c, C5d, C5e |

## Technical Context

- This task depends on 158, 152, 151, 159, 160, 161, 162, 163; the plan's own dependency cell reads:
  C2f, C3f, C4b, C5a, C5b, C5c, C5d, C5e.
- Developer decisions of 2026-11-03, binding on every row: DD1: a developer
  channel from an interactive terminal covers the owner verdict, `cancel`, and
  `abort`; reviewer sessions stay refused. DD2: the private projects are converted
  in item 13; `cardine.legacy` and `adopt` stay. DD3: `.meridian/` is removed at
  the switch. DD4: `ci: none`. DD5: the standalone ADR files stay and are cited by
  path.
- Sections 1, 5, and 7 of `docs/CONVERSION_PLAN.md` hold the observations (O1 to
  O9) and the switch that this row serves; read only the parts the row cites.
- The plan estimates this row at 2h. If it turns out larger, finish the
  scope; do not stop for the size alone.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.
- Before this task closes, the coordinator writes the records of rows C7a to C7f
  in Meridian format, so that the rehearsal converts real open tasks. The switch
  itself is steps S1 to S7 of `docs/CONVERSION_PLAN.md`, which belong to the
  developer and are not part of this task.

## Out of scope

Other rows of the plan, the switch steps that belong to the developer, the
documentation of work item 11, the release script of work item 12, and the
installation surface deferred after 1.0.

## Dependencies

- **Depends on**: 158, 152, 151, 159, 160, 161, 162, 163
- **Blocks**: the switch

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

This task changes records only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff.
