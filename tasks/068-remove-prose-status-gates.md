# Task 068 — Remove the product prose status gates (single source SS5)

> **ID**: `068`
> **Category**: Refactor
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 7 planning, 2026-10-22
> **Origin**: maintenance

## Objective

Implement row SS5 of `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md`, work item 7 of
`docs/ADR_CARDINE_1_0.md`.

Make every product gate read validated task state: remove the record `Status:`
reads and writes, the record and queue agreement gate, and verdict recovery
from report headings, and isolate the legacy importer.

## Acceptance Criteria

- [ ] The scope of row SS5 is implemented as the design of the plan's sections
  "Duplicates to remove", "Generated status contract", "Startability and
  totals", "Creation and stable records", and "Consumers and the Meridian
  boundary" describes it. A file the row missed but that the same change
  needs is in scope; the handoff lists it.
- [ ] Every test that row SS5 lists under "Tests" exists and passes.
- [ ] Product preflight, transitions, audit, identity, and review code read
  status and verdicts only from validated state. Tests prove that
  contradictory prose in a record, the queue, or a review report changes
  neither eligibility nor the verdict.
- [ ] The importer stays available as an explicit legacy route and no product
  command calls it as recovery for missing state.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1. Its Meridian-shaped records stay as they are: `Status:` lines,
  archive moves to `tasks/done/`, hand-maintained `tasks/QUEUE.md`,
  `tasks/QUEUE_ARCHIVE.md`, and `PROJECT_PLAN.md`. The task changes
  product code, product templates, and tests only; it edits none of those
  repository records except its own task record, handoff, and archive.
  `python3 scripts/check_repository.py` still passes on them.
- [ ] `cardine.legacy.meridian_installation.load_meridian_snapshot(Path("."))`
  still returns this repository's tasks with the same IDs and states, and
  the legacy fixture assertions are not weakened.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/068.json`, which only
  the installed `meridian task close 068` writes.
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
| `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` | Authority: the design sections and row SS5, with its bounded files and tests. |
| `docs/ADR_CARDINE_1_0.md` | Decision 4 and work item 7. |
| `docs/ADR_MACHINE_TASK_STATE.md` | Machine-state guarantees that must hold: schema validation, atomic writes, transition rules, exact-commit review checks. |
| `src/cardine/tasks/preflight.py`, `transitions.py`, `audit.py`, `identity.py`, `importer.py` | Product gates and the importer. |
| `src/cardine/review/verdict.py` | Structured verdicts and human reports. |

## Technical Context

- The work item 7 tasks run strictly in sequence (plan, "Ordered
  implementation tasks"). Intermediate tasks keep existing lifecycle callers
  working until their replacement lands.
- Until work item 10 the installed Meridian runs this repository's lifecycle
  and owns the frozen files and `.meridian/`. Product fixtures are separate
  from this repository's own workflow; no task converts this repository or
  creates `.cardine/` in it.

## Out of scope

Other rows of the plan, work items 8, 9, and 10, conversion of this
repository, and every frozen file.

## Dependencies

- **Depends on**: 067
- **Blocks**: 069

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
