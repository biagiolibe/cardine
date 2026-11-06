# Task 185 — Plan the release script (work item 12)

> **ID**: `185`
> **Category**: Architecture
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work items 11 and 12 planning, 2026-11-06
> **Origin**: maintenance

## Objective

Write `docs/RELEASE_PLAN.md`, the plan for work item 12 of `docs/ADR_CARDINE_1_0.md`:
one script that prepares and publishes a release to GitHub and PyPI, merging
`scripts/release.py` (894 lines) and `scripts/prepare_release.py` (155 lines) under
decision 7. The ADR lists six gaps that Meridian 1.4.0 and 1.4.1 exposed, and the
script must close them; the plan maps each gap to a mechanism, a test, and a row.
This task changes no other file.

## Acceptance Criteria

- [ ] `docs/RELEASE_PLAN.md` exists, in English, with these sections.
  - **Current procedure.** What `scripts/release.py`, `scripts/prepare_release.py`,
    `.github/workflows/release.yml`, `releases/`, the changelog fragments, and the
    release section of `CONTRIBUTING.md` do today, function by function, with the tests
    that cover each (`grep` over `tests/`). Each function gets a disposition: kept,
    merged, rewritten, or deleted.
  - **The six gaps.** Each of the six gaps the ADR lists under work item 12 is quoted
    and mapped to:
    - the code that has the gap today, with its line;
    - the mechanism that closes it, naming the function that changes;
    - the test that proves it.

    The ADR requires a real preparation in a disposable clone, not a dry run. For each
    test, the plan states how it builds that clone and which validation it runs there.
  - **PyPI.** What publication to PyPI needs that GitHub publication does not: the
    package metadata in `pyproject.toml`, the build, the upload, and how credentials
    reach CI. The plan never proposes that an agent handles a credential or runs a
    publication. Publication stays a developer step on `main`, as the ADR states, and
    the plan names the exact command or workflow the developer runs.
  - **One procedure.** The outline of `docs/RELEASING.md` as the single maintainer
    document, and the part of `CONTRIBUTING.md` that remains for outside contributors.
  - **Rows.** An ordered table `| R<n> / <hours>h | scope | files | tests | interruption
    boundaries | depends on |`, one or two areas per row, at most 10 files each. A row
    that writes release files lists the boundaries of each write. The first row
    depends on row C7a of `docs/CONVERSION_PLAN.md`.
  - **Developer decisions.** Every choice the plan cannot settle from the ADR, as a
    question with options and consequences, left undecided. At least: the PyPI project
    name and its availability (checked read-only), trusted publishing versus a token,
    and the first version number Cardine publishes.
- [ ] `tests/test_no_meridian_identifiers.py` allows the new plan: `RELEASE_PLAN\.md`
  is added to the alternation of design documents under `docs/` that already lists
  `CONVERSION_PLAN\.md`, and nothing else in that file changes.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/185.json`, which only
  the installed `meridian task close 185` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/RELEASE_PLAN.md` | The new plan this task writes. |
| `tests/test_no_meridian_identifiers.py` | The identifier guard's allowance for the plan. |

## Technical Context

- Authority: `docs/ADR_CARDINE_1_0.md`, work item 12; the
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
- `python3 scripts/run_tests.py --parallel --module test_no_meridian_identifiers`
- `git diff --check`

This task changes one document and one guard allowance. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff.
