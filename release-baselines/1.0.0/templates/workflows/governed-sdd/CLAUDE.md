# [Project Name]

Read `PROJECT_WORKFLOW.md` before acting. It defines the governed SDD lifecycle, review policy, roles, and Git workflow for this project.

`PROJECT_WORKFLOW.md` locks this repository to `GOVERNED_SDD`. Before any file
edit, Git mutation, task selection, or completion claim, confirm that mode from
the local file. Never use global, home-directory, remembered, or generic
Meridian/Claude/Codex instructions to select a lifecycle, task status, queue
format, branch procedure, or review action. Do not fall back to Lean Delivery:
checkbox statuses, moving tasks to `tasks/done/`, `PROJECT_PLAN.md` as a
canonical queue, autonomous task selection, and review-policy bypasses are
prohibited. If the local workflow cannot be read or conflicts with these rules,
return `BLOCKED` before making a mutation.

Read `LANGUAGE_POLICY.md` before responding or writing. It is a mandatory invariant: use its persisted conversation language even when a prompt uses another language, and write every repository artifact in English.

Follow `docs/CONTEXT_BUDGET_POLICY.md` for task-first context loading and reasoning selection. Use the assigned task as the navigation map, and use `docs/COMPLETION_REPORT_TEMPLATE.md` for the final handoff.

## Commands

```bash
# Fill in run, test, lint, and format commands for this project.
```

## Project invariants

- Add domain- and stack-specific invariants here.
- Treat accepted ADRs and task acceptance criteria as binding.

## Code organization

Follow `docs/CODE_ORGANIZATION.md` for every production-source change: one owning module per responsibility, preserved dependency direction between layers, narrowest working visibility, and structural refactors kept out of behavior-change tasks. If a task needs a new ownership boundary or cannot fit the documented module structure without coupling responsibilities, stop and report the missing architectural decision instead of creating an opportunistic abstraction.

## Command triggers

Treat these developer phrases as the complete authorization for the named workflow. Do not select a different task or act on an unassigned one.

- `Proceed with <TASK-ID>` — run the implementation workflow below for exactly that task.
- `Review <TASK-ID>` — act as an independent reviewer-integrator using `docs/CODE_REVIEW_PROMPT.md`, ideally in a fresh chat or Task-tool subagent.
- `Accept <TASK-ID>` — run the owner-acceptance workflow below.

### Implementation workflow

1. Read the assigned task, every referenced higher-precedence specification/ADR, and `git status --short`.
2. Before code changes, ensure the worktree contains no unrelated uncommitted changes. If it does, do not stage, modify, discard, or commit those changes; report the exact conflict and stop unless the developer explicitly directs how to proceed.
3. Create and switch to a dedicated branch named after the normalized task ID, without a provider prefix (for example, `TASK-012` uses `task-012`). Only one task may write in this checkout at a time. If the branch already exists, inspect it and stop for direction rather than overwriting or rebasing it. Do not create or switch branches in a dirty checkout.
4. State a short plan, then implement only the assigned task and its explicit dependencies. Preserve architectural boundaries and all SDD scope limits.
5. Run the task's validation commands and the project baseline checks from the `## Commands` section, unless a command is inapplicable because the task has not yet established the required project artifact. Report any inapplicable command and why.
6. When every required validation passes, record completion according to the task's review policy: `READY_FOR_REVIEW` for `Review: REQUIRED`, `ACCEPTED` for `Review: NOT_REQUIRED`. Make no status change if any validation failed, a required manual check is incomplete, or acceptance criteria are not met.
7. Review the diff to confirm it contains only the assigned task and its required status updates. Create one atomic commit using Conventional Commit style and the task ID. Follow `docs/PULL_REQUEST_POLICY.md` for the branch push and hand-off.
8. Report the branch name, commit hash, changed files, acceptance-criteria evidence, validation results, and assumptions. If validation fails or scope is ambiguous, do not commit a partial implementation; report the blocker.

Never run two writing agents concurrently in the same worktree.

### Review-mode boundary

For `Review <TASK-ID>`, review is read-only until an explicit `APPROVE` verdict.
Do not edit source code, tests, manifests, implementation documentation, task
content, or queue records to remedy a finding. Return `CHANGES_REQUESTED` with
actionable evidence instead. Only after `APPROVE` and the required ancestry
check may the reviewer make the two status-only `ACCEPTED` edits and commit
them with the required reviewer-integrator author override.

## Owner-acceptance workflow

When the developer says `Accept <TASK-ID>` after personally reviewing a `Review: REQUIRED` task, treat it as explicit authorization to skip the agent review and perform only the acceptance-state handoff. Confirm that the task and its canonical queue row are both `READY_FOR_REVIEW`; do not re-review the implementation, rerun validation, change source code, or merge the branch.

Update exactly the task `Status` and its canonical queue row to `ACCEPTED`, and commit only those two edits as `docs: accept <TASK-ID>` on the existing local task branch. Report the commit. If the required state records are missing or inconsistent, stop and report `BLOCKED`.

## Implementer-to-reviewer handoff

After validation, create the task commit and push the task branch exactly once. Record the branch name, implementation commit, and base `main` commit in the completion handoff. Leave the primary checkout clean and on the task branch; do not switch back to `main`.

The reviewer-integrator uses that same primary checkout in a fresh agent session that did not write the implementation. If the reviewer session starts on clean `main`, run `git switch <task-branch>`. If the branch is missing locally, or a dirty checkout prevents switching, return `BLOCKED` with the exact condition.

For `Review: REQUIRED`, the reviewer must never push the task branch. Before changing either status record, run `git merge-base --is-ancestor main <task-branch>`. If it fails, do not mark the task `ACCEPTED`; return `BLOCKED` with no fetch, rebase, non-fast-forward merge, or force-push recovery. If it passes, create the local status-only `ACCEPTED` commit, switch to `main`, fast-forward merge the task branch, push `main` exactly once, and delete the local task branch. For `Review: NOT_REQUIRED`, the implementer performs the same acceptance commit and main integration after validation. Owner acceptance is status-only and does not automatically integrate the branch.

## Reviewer-integrator identity on a single-operator project

Review independence and Git identity separation are both mandatory controls; neither substitutes for the other. The review session must not have written the code and must re-derive evidence from the actual diff and cited sources rather than trusting the implementation report. Only for the `ACCEPTED` commit, use the project-scoped reviewer-specific author override:

```bash
git commit --author="<PROJECT_NAME> Reviewer-Integrator <reviewer-integrator@<project-slug>.local>" -m "docs: reviewer-integrator pass <TASK-ID>; independently re-verified diff, cited sources, acceptance evidence, and validation"
```

Keep the operator's normal committer identity. Do not change global or repository Git config. The override applies only to the `ACCEPTED` commit and can be verified with `git log --format='%an <%ae>'`.
