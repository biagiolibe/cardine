# Task 152 — Deliver a disposable task with an agent following run (C3f)

> **ID**: `152`
> **Category**: Infrastructure
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 10 records, 2026-11-03
> **Origin**: maintenance

## Objective

Implement row C3f of `docs/CONVERSION_PLAN.md`, work item 10 of
`docs/ADR_CARDINE_1_0.md`. The row fixes the scope, the files, the tests, and
the interruption boundaries; this record adds the developer's decisions and no
design.

agent-driven delivery in a disposable project. The agent executing this task follows only what `cardine run` prints, from queued to landed, with a local bare remote. Every point where it needed knowledge the output did not give is a finding.

## Acceptance Criteria

- [ ] Row C3f is implemented as its line in the excerpt describes it.
- [ ] This task changes only its own record, archive, handoff, and state file. Any
  disposable project stays outside the repository, under a disposable home.
  A product defect found here is a finding in the handoff for the coordinator,
  who writes a new row; it is not fixed in this task.
- [ ] The row's evidence is in the handoff: No test file. The handoff records the sequence of `run` outputs, the landed commit, and the findings.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/152.json`, which only
  the installed `meridian task close 152` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `tasks/handoffs/<id>.md` | The files this row edits, as the plan lists them. |

## Authority excerpt

The parts of the plan this task needs, extracted from the file on `main` when
the record was written, so that the task reads them here instead of the whole
document:

> From `docs/CONVERSION_PLAN.md`, row C3f:
>
> | C3f / 3h | Meridian: agent-driven delivery in a disposable project. The agent executing this task follows only what `cardine run` prints, from queued to landed, with a local bare remote. Every point where it needed knowledge the output did not give is a finding. | `tasks/handoffs/<id>.md` | No test file. The handoff records the sequence of `run` outputs, the landed commit, and the findings. | None in this repository; the disposable run is repeated from scratch if interrupted. | C3c, C3d, C3e, C4b |

## Technical Context

- This task depends on 147, 148, 149, 151; the plan's own dependency cell reads:
  C3c, C3d, C3e, C4b.
- Developer decisions of 2026-11-03, binding on every row: DD1: a developer
  channel from an interactive terminal covers the owner verdict, `cancel`, and
  `abort`; reviewer sessions stay refused. DD2: the private projects are converted
  in item 13; `cardine.legacy` and `adopt` stay. DD3: `.meridian/` is removed at
  the switch. DD4: `ci: none`. DD5: the standalone ADR files stay and are cited by
  path.
- Sections 1, 5, and 7 of `docs/CONVERSION_PLAN.md` hold the observations (O1 to
  O9) and the switch that this row serves; read only the parts the row cites.
- The plan estimates this row at 3h. If it turns out larger, finish the
  scope; do not stop for the size alone.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.
- The agent executing this task is the agent under test. It reads only the
  disposable project's own files and the output of `cardine run`, and it does not
  use this plan to decide what to do next. Host role launches stay unavailable,
  so no second session is started.

## Out of scope

Other rows of the plan, the switch steps that belong to the developer, the
documentation of work item 11, the release script of work item 12, and the
installation surface deferred after 1.0.

## Dependencies

- **Depends on**: 147, 148, 149, 151
- **Blocks**: 164

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
- A measurement the record asks the handoff to report: use in-process Python
  (wrap `subprocess.Popen` to count, read `resource.getrusage(RUSAGE_CHILDREN)` for
  CPU), never a tool that needs privileges. If one still cannot be obtained, say so in
  the handoff; that is not a stop.
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

This task changes records only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff.
