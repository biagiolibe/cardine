# Task 074 — Inventory the template rules and their enforcement (decision 14)

> **ID**: `074`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Decision 14 planning, 2026-10-22
> **Origin**: maintenance

## Objective

Write `docs/RULE_ENFORCEMENT_INVENTORY.md`. Rule 1 of decision 14 says that an
agent needs little to read, and that every rule in the templates is enforced
by the tool and stated in one line, labelled as advice, or deleted. The single
template set gives agents about 21,000 words today. The inventory lists every
rule, how it is enforced, and what to do with it, and sets a size target for
the instructions an agent always reads.

## Acceptance Criteria

- [x] `docs/RULE_ENFORCEMENT_INVENTORY.md` exists, in English, names the
  `main` commit it was taken on, and gives the commands it used, so that
  it can be repeated.
- [x] It covers every instruction to an agent in `templates/single/`
  (workflow, entry routers, `docs/`, workflows, blueprint, completion
  report template, host rule files) and the host assets that product setup
  installs. It reports the word count per file and which files an agent
  reads on every task, on some tasks, or only on demand.
- [x] Every rule is one entry with file and line, the rule in a few words, and
  its enforcement: a CLI gate (name the function), a hook, a host deny
  rule, or none. Entries with no enforcement say what harm a violation
  causes.
- [x] Every entry has one action: **enforce** (name the gate to add and its
  row), **one line** (already enforced; the prose shrinks to one line),
  **advice** (no harm; labelled as advice), **delete** (duplicated,
  obsolete, or describing what `cardine run` will do for the agent), or
  **moved** (belongs to a document an agent reads only on demand).
- [x] It proposes a word budget for what an agent reads on every task after
  work item 8, and shows that the actions reach it. It names the rules
  that `cardine run` makes unnecessary, because the engine returns the
  next action.
- [x] It lists duplicated rules, rules that contradict each other or the code,
  and rules that refer to removed commands or Meridian behavior.
- [x] Every finding that needs a change has a destination: a named row of
  `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` (SS6, SS7) or
  `docs/RUN_ENGINE_PLAN.md` (RE1 to RE7) whose scope text already covers
  it, a one-sentence amendment to such a row, a proposed new row with size
  and placement, or removal. Where an existing row does not cover a
  finding, the document says so.
- [x] It cross-references `docs/TEXT_GATE_INVENTORY.md` (task 073) instead of
  repeating its entries.
- [x] No file changes outside `docs/RULE_ENFORCEMENT_INVENTORY.md` and this
  task's records: the task record, its handoff, and its archive under
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
- [x] `.meridian/` is unchanged, except `.meridian/tasks/074.json`, which only
  the installed `meridian task close 074` writes.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/ADR_CARDINE_1_0.md` | Decisions 12, 13, and 14; decision 6 for location independence. |
| `docs/RUN_ENGINE_PLAN.md`, `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` | Planned destinations. |
| `docs/TEXT_GATE_INVENTORY.md` | Task 073: text gates, already inventoried. |
| `templates/single/` | The instructions to inventory. |
| `src/cardine/hosts/` | Host assets and hooks that enforce rules. |

## Technical Context

- The work item 9 host rules and skills are created later under Cardine names;
  record their needed rules as findings for work item 9 without planning that
  item.
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
