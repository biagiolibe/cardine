# Task 075 — Map what an agent can forge among the artifacts gates trust (decision 14)

> **ID**: `075`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Decision 14 planning, 2026-10-22
> **Origin**: maintenance

## Objective

Write `docs/FORGERY_INVENTORY.md`. Rule 2 of decision 14 says that every
artifact a gate trusts is written by Cardine, and that Cardine detects a write
it did not make. On Contoso a hand-written state file passed every command
until integration. The inventory lists every artifact a gate trusts, who can
write it, what a forged or edited copy would let an agent pass, and the
defense that closes it.

## Acceptance Criteria

- [ ] `docs/FORGERY_INVENTORY.md` exists, in English, names the `main` commit
  it was taken on, and gives the commands it used, so that it can be
  repeated.
- [ ] It lists every file or Git object that a product gate, verdict, status,
  or stop trusts: task state and its contract snapshot, execution
  evidence, integration evidence and lease, the project configuration
  (`.cardine/project.json`), review verdicts, operation journals and
  receipts, generated views, and any other found. For each it gives the
  gates that read it, where it lives (task worktree, primary checkout,
  `.git`, `main`), and who can write it.
- [ ] For each artifact it describes the concrete attack of a strong agent
  with ordinary file and Git access on the task branch, for example a
  hand-written queued state, a state edited to `in_review`, a contract
  changed from `review: required` to `not_required`, evidence with
  invented exit codes, or a configuration that disables CI, and says
  whether today's code detects it, with the test that proves it or the
  absence of one.
- [ ] It proposes a defense for each undetected attack, such as an operation
  receipt outside the worktree, comparing the contract with the copy on
  `main`, binding evidence to digests that Cardine computed, or refusing a
  write path. It states which defense also covers a weak agent's honest
  mistake, such as the Contoso hand-written state.
- [ ] It names the attacks that stay possible by design, for example an agent
  with the developer's own authority, and why they are out of scope.
- [ ] Every finding that needs a change has a destination: a named row of
  `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` (SS6, SS7) or
  `docs/RUN_ENGINE_PLAN.md` (RE1 to RE7) whose scope text already covers
  it, a one-sentence amendment to such a row, a proposed new row with size
  and placement, or removal. Where an existing row does not cover a
  finding, the document says so.
- [ ] It cross-references `docs/TEXT_GATE_INVENTORY.md` (task 073) instead of
  repeating its entries.
- [ ] No file changes outside `docs/FORGERY_INVENTORY.md` and this task's
  records: the task record, its handoff, and its archive under
  `tasks/done/`.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/075.json`, which only
  the installed `meridian task close 075` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/ADR_CARDINE_1_0.md` | Decisions 12, 13, and 14; decision 6 for location independence. |
| `docs/RUN_ENGINE_PLAN.md`, `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` | Planned destinations. |
| `docs/TEXT_GATE_INVENTORY.md` | Task 073: text gates, already inventoried. |
| `src/cardine/tasks/state.py`, `src/cardine/tasks/contract.py` | State, contract snapshot, and validation. |
| `src/cardine/lifecycle/`, `src/cardine/integration/`, `src/cardine/review/` | Evidence, lease, and verdict writers and readers. |
| `docs/ADR_MACHINE_TASK_STATE.md` | The machine-state guarantees. |

## Technical Context

- Defect 2 of `docs/TEXT_GATE_INVENTORY.md`, an
  `interaction_assessment_complete` value written unconditionally, is in scope
  as an example of a declaration that no fact supports.
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

This task changes documentation only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff.
