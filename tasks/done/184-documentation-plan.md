# Task 184 — Plan the documentation (work item 11)

> **ID**: `184`
> **Category**: Architecture
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work items 11 and 12 planning, 2026-11-06
> **Origin**: maintenance

## Objective

Write `docs/DOCUMENTATION_PLAN.md`, the plan for work item 11 of
`docs/ADR_CARDINE_1_0.md`: "Documentation: README positioning, quick start, agent
reference." The plan fixes the audience, an inventory of every user-facing document
with its disposition, and an ordered table of rows small enough to implement one at a
time. This task changes no other file.

Today `README.md` still opens with "Meridian in 30 seconds" and names Meridian 23
times; `docs/QUICKSTART.md` 38 times and `docs/AGENT_OPERATIONS.md` 31 times.
`docs/RUN_COMMANDS.md` names it none. After the switch, these documents are what a
new adopter of Cardine reads first.

## Acceptance Criteria

- [ ] `docs/DOCUMENTATION_PLAN.md` exists, in English, with these sections.
  - **Audience and positioning.** Who reads the README, the quick start, and the agent
    reference, and what each must let them do. The positioning is quoted from the ADR
    (Context and decisions 1 to 3) and from `docs/PUBLIC_SURFACE.md`, not invented.
  - **Inventory.** Every Markdown file under the repository root, `docs/`,
    `docs/examples/`, `templates/`, and `skills/` that a user or an agent of an adopting
    project reads. For each: its readers, the count of `Meridian` and `meridian`
    mentions on `main`, the commands it quotes, and a disposition (keep, rewrite,
    merge into a named file, move to an archive directory, or delete). Design and
    history documents of this repository (plans, ADRs, inventories) are listed with
    the disposition "maintainer archive" and the plan states where they go.
  - **Commands quoted versus commands that exist.** For every `cardine` command line
    quoted in a kept or rewritten document, whether `cardine <command> --help`
    accepts it on `main` (run in a disposable directory). A quoted command that does
    not parse is a finding, assigned to a row.
  - **A mechanical check.** A proposal for one repository check, owned by a row, that
    keeps the rewritten documents true without prose matching. For example, it could
    parse every fenced `cardine` command in the user-facing documents with the CLI
    parser. The proposal names the existing check or test it extends.
  - **Rows.** An ordered table `| D<n> / <hours>h | scope | files | tests |
    interruption boundaries | depends on |`, one or two areas per row, at most 10
    files each. The README, the quick start, and the agent reference are each at
    least one row. The first row depends on row C7a of `docs/CONVERSION_PLAN.md`.
  - **Developer decisions.** Every choice the plan cannot settle from the ADR, as a
    question with options and consequences, left undecided. At least: whether the
    Meridian history stays visible in the README, and where the maintainer archive
    lives.
- [ ] The plan cites every count and line from the files on `main` at the commit it
  names, and states that commit.
- [ ] Only the files under Relevant Files are edited, together with this
  task's own record and its archive, handoff, and state file. A test file
  outside that list may change only to update an expectation that this change
  made stale, without new behavior, and the handoff lists it. Any other file,
  or new behavior beyond this record, stops the task before editing it and
  names the file.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/184.json`, which only
  the installed `meridian task close 184` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/DOCUMENTATION_PLAN.md` | The new plan this task writes. |

## Technical Context

- Authority: `docs/ADR_CARDINE_1_0.md`, work item 11; the
  developer's request of 2026-11-06 to plan the work after the switch while the
  conversion completes. `docs/CONVERSION_PLAN.md` (task 141) is the model for the
  structure.
- A planning task changes no product code, test, or script. Measure what the plan
  states by reading the files on `main` and by running commands in a disposable
  directory; never by editing this repository.
- The plan's rows follow the conventions of `docs/CONVERSION_PLAN.md`: each row touches
  at most 10 files in one or two areas, names its tests, and lists the interruption
  boundaries of every effect it performs (rule 4 of decision 14). Rows run under
  Cardine, after the switch (ADR, work item 10: "Items 11 and 12 run on Cardine").
- Each row is written so that a record can quote it unchanged: scope, files, tests,
  boundaries, and dependencies, without "and similar" or "where needed". A row that
  names a mechanism names the function or file that already does the same thing, so
  that the implementer does not have to discover a downstream reader.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Implementing any row, editing the documents or scripts the plan covers, the switch, and
rows C7a onward. Other rows of the queue.

## Dependencies

- **Depends on**: none
- **Blocks**: none

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
- A test outside the files this record lists that inventories what the
  repository contains (boundary modules, stop codes, allowances, markers, module
  bindings) and fails only because this task added an item: add that one item, naming
  the real test or owner the inventory asks for, and list the file in the handoff. This
  is not a change of scope. Removing an item, or widening a pattern beyond the new
  item, is.
- Before stopping for a change of scope, finish everything else, commit it, and run
  the repository check and the affected tests, so that one stop names every file
  needed. Do not stop once per file.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope
  remain stops.

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `git diff --check`

This task changes one document only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff.
