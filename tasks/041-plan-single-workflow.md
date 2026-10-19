# Task 041 — Plan the single workflow (work item 6)

> **ID**: `041`
> **Category**: Architecture
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work items 5 to 12 planning, 2026-10-19
> **Origin**: maintenance

## Objective

Write `docs/SINGLE_WORKFLOW_PLAN.md`, the plan for work item 6 of
`docs/ADR_CARDINE_1_0.md`. Decision 3 replaces the two workflows with one
lifecycle, one template set, and two presets, `lean` and `governed`. Each
preset sets the defaults of options that a task can override. The plan fixes
the design and the task sequence before any template or code changes.

## Acceptance Criteria

- [ ] `docs/SINGLE_WORKFLOW_PLAN.md` exists, in English, and contains:
  - **Project configuration.** The file under `.cardine/` that declares the
    preset and the project defaults, and its schema. It covers at least:
    - review;
    - required `Authority` and `Expected code surface`;
    - the validation retry limit;
    - the landing mode, `direct` only in 1.0;
    - CI before landing;
    - task identity;
    - the validation commands.
    The plan says which current file each value replaces:
    `.meridian/task-identity.json`, `.meridian/candidate-validation.json`, the
    capability profiles, or the workflow mode. It also says how
    `cardine.templates.mode` stops deriving the workflow from the shape of
    the queue file, as ADR work item 6 requires.
  - **Task contract.** The fields of the one task template, which ones a
    preset makes required, and how a task overrides a default: review, the
    `spike` class with `ANSWERED` and `INCONCLUSIVE`, `Authority`, and
    `Expected code surface`.
  - **States.** The mapping from today's Lean and Governed SDD statuses to
    `queued`, `in_progress`, `in_review`, `done`, and `cancelled`, with the
    allowed transitions and the field of the task state file that holds
    them. Work item 7 removes the duplicate status fields, so this plan does
    not.
  - **Template set.** A table of every file under `templates/base/`,
    `templates/workflows/lean-delivery/`, and
    `templates/workflows/governed-sdd/`. For each file, the plan says
    whether it is kept, merged, or removed, and gives its destination in the
    single set. It also covers the capability catalog
    (`capabilities/catalog-v1.json` and `capabilities/markers-v1.json`) and
    states three things:
    - each capability ships at one version in the single set, which resolves
      the merge-fallback proposal of task 038 or says why not;
    - `CONTEXT_BUDGET_POLICY.md` and the `context-budgeting` capability get
      their new name in the template set; this repository's managed copy
      stays until work item 10;
    - markers keep the `MERIDIAN:BEGIN` syntax and their version numbers,
      because work item 5b renames them and restarts every capability at
      `v1` after this item.
  - **Briefing.** How the per-turn queue briefing names the preset from the
    configuration, with the regression case of ADR work item 6: a project
    whose queue lists no task.
  - **Parity.** Each row of the Governed SDD parity table in decision 3,
    with the part of the plan that keeps it.
  - **Task sequence.** An ordered list of tasks of 2–3 hours, each with its
    scope, the files it touches, the tests that prove it, and its
    dependencies. Every task depends on the last task of work item 5a, which
    task 040 defines. Two tasks that touch the same file are never parallel.
- [ ] The plan uses the Cardine names that ADR work item 5a fixes, such as
  `.cardine/` and `cardine`, without planning the rename itself.
- [ ] The plan does not plan work items 5b, 7, 8, or 9, but it names any
  choice that would make them harder. Skills, one per host, belong to work
  item 9. The plan states which template files they read.
- [ ] No file changes outside `docs/SINGLE_WORKFLOW_PLAN.md` and this task's
  records: the task record, its handoff, its archive under `tasks/done/`,
  and `.meridian/tasks/041.json`, which only the installed `meridian task
  close 041` writes.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `docs/ADR_CARDINE_1_0.md` | Decisions 3, 4, 5, 11, and 12; work items 6 and 7. |
| `templates/base/`, `templates/workflows/` | The two template sets. |
| `capabilities/catalog-v1.json`, `capabilities/markers-v1.json`, `capabilities/marker-baselines.json` | Capability catalog. |
| `src/cardine/templates/mode.py`, `src/cardine/tasks/`, `src/cardine/shared/project.py` | Workflow mode, contract, states, project declaration. |
| `docs/ADR_MACHINE_TASK_STATE.md`, `docs/TASK_IDENTITY_POLICY.md`, `docs/PROJECT_DECLARATION.md` | Current state, identity, and declaration design. |

## Technical Context

- Task 038 found that `requiredVersion` follows the Governed SDD templates
  only, and that `lifecycle-orchestration` ships v12 and v3 in two Governed
  SDD files. Its handoff proposes verifying conflicted merge blocks against
  each template file's own marker version.
- Task 035 kept the template files named `CONTEXT_BUDGET_POLICY.md` because
  the self-hosting doctor then compared the checkout's catalog with this
  repository's manifest. Task 039 removed that comparison.
- Until work item 10, the installed Meridian owns `.meridian/`, the managed
  copies, and the shared-source hooks that `.meridian/manifest.json` lists.
  The plan's tasks change product files only.

## Out of scope

Changing any template, catalog, or code. Work items 5a, 5b, 7, 8, and 9.

## Dependencies

- **Depends on**: none
- **Blocks**: the work item 6 tasks that the plan defines

## Validation

- `python3 scripts/check_repository.py`
- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `git diff --check`

This task changes documentation only. Under the validation-scoping rule of
`PROJECT_WORKFLOW.md`, it skips the test suites and records that skip in the
handoff.
