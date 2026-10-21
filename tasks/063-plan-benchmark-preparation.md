# Task 063 — Plan the preparation of the benchmark against a minimal procedure

> **ID**: `063`
> **Category**: Architecture
> **Priority**: 🟡 P2
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Benchmark protocol discovery, 2026-10-22
> **Origin**: maintenance

## Objective

`docs/BENCHMARK_PROTOCOL.md` records the decided protocol for comparing
Cardine 0.9 with a minimal competent procedure. Measured runs wait for
Cardine 0.9, but the harness, the overlays, and the evaluator can be prepared
earlier. Add a "Preparation tasks" section to that document that turns its
open points and run conditions into an ordered sequence of tasks, before any
code changes.

## Acceptance Criteria

- [ ] `docs/BENCHMARK_PROTOCOL.md` gains a section "Preparation tasks", in
  English, with an ordered list of tasks of 2–3 hours. Each task states its
  scope, files, tests, dependencies, and whether it can start before
  Cardine 0.9. The sequence covers at least:
  - freezing both Contoso baselines and their Rust toolchain outside this
    repository, and how a run obtains them;
  - the contract split of section 5.2 for both tasks;
  - the group A overlay, and the group B overlay through `cardine adopt`
    once work item 10 lands;
  - the runner: model and effort pinning, host configuration isolation, the
    scripted operator, the limits and calibration runs, and journal-free
    grading. It says whether `scripts/run_agent_evals.py` is extended or a
    separate runner is added, and why;
  - the frozen deterministic check package and the blind rubric, with their
    calibration against the historical solution, a hand-written alternative
    correct solution, and deliberately wrong solutions;
  - the part 2 scenarios of section 6, starting from `evals/scenarios`;
  - the raw request of variant 2-bis.
- [ ] The section states where each artifact lives. Contoso code and
  baselines never enter this repository, and no tracked file names the real
  project behind the Contoso pseudonym.
- [ ] It answers the open point of section 12 on the field trial of work
  item 13: overlap, separation, or a stated reason to defer the choice.
- [ ] The protocol's decided sections 1 to 11 keep their decisions. A
  conflict found while planning is reported in the handoff, not resolved by
  changing a decision.
- [ ] No agent benchmark run, calibration run, or paid host invocation is
  made by this task.
- [ ] No file changes outside `docs/BENCHMARK_PROTOCOL.md` and this task's
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/063.json`, which only
  the installed `meridian task close 063` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/BENCHMARK_PROTOCOL.md` | Authority: the decided protocol and its open points. |
| `docs/ADR_CARDINE_1_0.md` | Decisions 3, 10, 11, and 12; work items 8, 10, 11, and 13. |
| `scripts/run_agent_evals.py`, `evals/` | Existing on-demand agent runner and scenarios. |

## Technical Context

- The runner grades from the Cardine journal and the record's `Status:`
  line, pins no model, and does not isolate the user `CLAUDE.md`, skills, or
  plugins (`isolation_notes`). The protocol needs all three changed.
- Group B's overlay depends on `cardine adopt` (work item 10). The other
  preparation can start before it.
- This task changes no product file and can run beside any other open task.

## Out of scope

Implementing any preparation task, running any agent, and changing the
protocol's decisions.

## Dependencies

- **Depends on**: —
- **Blocks**: the preparation tasks that the plan defines

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
