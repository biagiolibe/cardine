# Task 082 — Revise the run engine plan with the inventories and the trust boundary

> **ID**: `082`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 8 planning, 2026-10-23
> **Origin**: maintenance

## Objective

Revise `docs/RUN_ENGINE_PLAN.md` so that its task sequence can be turned into
records without further design. Since task 062 wrote the plan, decisions 13
and 14 of `docs/ADR_CARDINE_1_0.md` were added, decision 14 rule 2 set the
trust boundary at the host's permissions (2026-10-23), and four inventories
proposed amendments and new rows: `docs/TEXT_GATE_INVENTORY.md` (073),
`docs/RULE_ENFORCEMENT_INVENTORY.md` (074), `docs/FORGERY_INVENTORY.md` (075),
and `docs/STOP_REVIEW.md` (076). Several of them overlap or disagree, and most
RE rows now exceed 3 hours.

## Acceptance Criteria

- [x] A new section **Trust boundary** states how work item 8 applies decision
  14 rule 2 as amended: which row writes operation receipts and binds them
  to inputs and outputs, which gates reject an artifact no receipt covers,
  how the engine launches the implementer and the reviewer with distinct
  host profiles (and which row does it), what work item 9 must install on
  both hosts, and the declared limit. It does not claim authenticity
  against an agent that bypasses the host permissions.
- [x] The section **Ordered implementation tasks** is replaced by one table in
  which every row has: a label, at most 3 hours of work, its scope and
  files, its tests, its dependencies, the known-violation entries of
  `tests/test_text_gates.py` it deletes, its effect boundaries for rule 4
  of decision 14 with the interruption test for each, and the other rows
  that share a file with it. Rows that share a file are never parallel;
  the shared ratchet table counts as a shared file.
- [x] Every amendment is either folded into a row or rejected with a reason:
  A-RE1-1 to A-RE7-1 and RX1, TR1, TR2 of 074; F-A to F-D and the RE
  amendments of 075 (F-E and row FI1 are deferred after 1.0 by the
  developer); A1 to A8 and SR1 of 076; N3 and the RE3, RE5, RE6 amendments
  of 073 (T-38 to T-44). A table maps each amendment ID to its row.
- [x] Where the inventories disagree, the plan states one choice and why. At
  least: the review stop codes (074 emits `REVIEW_REQUIRED` and
  `REVIEW_LOOP_EXHAUSTED` from facts; 076 merges `REVIEW_REQUIRED` and
  `REVIEW_STALE` into `REVIEW_NOT_APPROVED`), the retry code name
  (A-RE3-1), and the evidence handling that 073 and 075 both amend in RE3
  and RE5.
- [x] The closure of the static guard is corrected: the last row asserts that
  the known-violation table holds only entries assigned to work item 9
  (T-46, T-47) and work item 10 (T-27, T-31, and any other the plan
  names), not that it is empty.
- [x] The two work item 8 items in the Deferred Items of `PROJECT_PLAN.md` (a
  runnable `EVIDENCE_INCOMPLETE` recovery, and the split of mixed
  guardrail codes) are each mapped to a row.
- [x] Rows RX1, N2a, and N2b, which tasks 083 to 085 implement, appear as
  completed or in progress inputs, not as new rows.
- [x] No file changes outside `docs/RUN_ENGINE_PLAN.md` and this task's
  records: the task record, its handoff, and its archive under
  `tasks/done/`.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/082.json`, which only
  the installed `meridian task close 082` writes.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/RUN_ENGINE_PLAN.md` | The plan to revise. |
| `docs/ADR_CARDINE_1_0.md` | Decisions 6, 8, 11, 12, 13, and 14 as amended on 2026-10-23. |
| `docs/TEXT_GATE_INVENTORY.md`, `docs/RULE_ENFORCEMENT_INVENTORY.md`, `docs/FORGERY_INVENTORY.md`, `docs/STOP_REVIEW.md` | The amendments and proposed rows. |
| `tests/test_text_gates.py` | The ratchet table and its T-IDs. |
| `PROJECT_PLAN.md` | Deferred Items that name work item 8. |

## Technical Context

- Tasks 083 to 085 run at the same time as this task and change product code,
  not this document.
- This task changes no code.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Writing task records; planning work items 9 and 10; the installation surface
(deferred after 1.0).

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

## Completion evidence

- Revised `docs/RUN_ENGINE_PLAN.md` with the amended host trust boundary,
  serial implementation rows of at most three hours, effect/retry proofs,
  ratchet ownership and exhaustive amendment dispositions.
- Implementation validated at `35171385434d9743a155a983c8adf40b4edef9d3`;
  base main `fd6d0a3bd7c30e87702b80467120f805b151cec7`.
- All five required commands passed; the identifier guard ran three tests.
  Full implementation suites were omitted under the documentation-only scope.
- No product code, frozen governance, host configuration or unrelated record
  changed. Lifecycle state is written only by installed Meridian closure.
- Detailed results: `tasks/handoffs/082.md`.
