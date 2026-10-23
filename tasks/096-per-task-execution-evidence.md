# Task 096 — Store execution evidence in one file per task

> **ID**: `096`
> **Category**: Bug
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Defect triage, 2026-10-23
> **Origin**: maintenance

## Objective

Every task writes its entry into one shared file,
`.cardine/execution-evidence.json`, a JSON object with sorted keys, and
`integrate stage` merges the task branch with a plain `git merge --no-ff
--no-commit` (`src/cardine/integration/merge.py`). Two tasks reviewed in
parallel with adjacent IDs touch adjacent lines, so the second integration
stops with `INTEGRATION_CONFLICT` on that file alone. An approved task then
has no exit: merging `main` into its branch makes the review stale, and a
second verdict is refused.

The defect was found on Meridian 1.4.1 in a governed Contoso project and
reproduced by the coordinator with plain Git; Cardine inherited the shared
file. Task state already lives in one file per task (decision 4); evidence
must too, so that two tasks never write the same tracked file and the conflict
cannot exist.

## Acceptance Criteria

- [ ] Execution evidence lives in one file per task under the project
  directory, for example `.cardine/evidence/<TASK-ID>.json`, at a path
  resolved by the layout module from the canonical task ID. No product
  code reads or writes a shared evidence file, and no task writes another
  task's file.
- [ ] Every product reader and writer uses the per-task path: recording, the
  evidence and contract checks, delivery readiness and owned paths,
  integration evidence and staging, and the console. The installation
  reader under `cardine.legacy` keeps reading the installed Meridian's
  shared file unchanged.
- [ ] A test with two task branches created from the same `main`, each
  recording evidence, integrates them one after the other with `integrate
  stage` and `finalize`, and the second integration has no conflict. A
  test proves that a task cannot write or overwrite another task's
  evidence file.
- [ ] A conflict in any other file still stops with `INTEGRATION_CONFLICT`, as
  before.
- [ ] Product templates and documents that name the shared evidence file name
  the per-task path. The template change follows the pre-1.0 rule of task
  031: the owning capability's version rises and its baseline is
  rewritten, with no migration and no `VERSION` change.
- [ ] Every row of the known-violation table of `tests/test_text_gates.py`
  that this change makes stale is updated, and the test passes.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1; this task changes product code, product templates, and tests
  only.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/096.json`, which only
  the installed `meridian task close 096` writes.
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
| `src/cardine/shared/layout.py` | `execution_evidence_path`, to become per task. |
| `src/cardine/tasks/recording.py`, `tasks/evidence.py`, `tasks/contract.py` | Evidence writers and checks. |
| `src/cardine/lifecycle/execution.py`, `src/cardine/integration/evidence.py`, `integration/merge.py`, `src/cardine/console/snapshot.py` | Owned paths, integration, and display. |
| `docs/RUN_ENGINE_PLAN.md` | Row RE3b, which follows and rewrites validation evidence on top of the per-task file. |

## Technical Context

- It runs between task 093 (RE3a) and task 094 (RE3b), because RE3b rewrites
  the evidence and recording modules; doing it first keeps RE3b on the final
  layout.
- Meridian 1.4.x receives fixes only for blocking defects (ADR decision 10).
  The Meridian defect has a workaround that needs no release: a JSON union
  merge driver for the evidence file, declared in `.gitattributes` on `main`
  and configured in the primary checkout.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.

## Out of scope

Relaxing the stale-review gate or allowing a second verdict on an approved
task, both of which behaved correctly; a structural merge of shared JSON; any
Meridian release.

## Dependencies

- **Depends on**: 093
- **Blocks**: 094

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
