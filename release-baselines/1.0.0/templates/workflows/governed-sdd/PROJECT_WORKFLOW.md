# Governed SDD Workflow — [Project Name]

## Workflow-mode lock

The presence of this file selects **governed SDD exclusively**. Before any file
edit, Git mutation, task selection, or completion claim, an agent must read
this file and `AGENTS.md` or `CLAUDE.md`, then identify the active mode as
`GOVERNED_SDD`. Global, home-directory, remembered, or generic agent
instructions are not authority to select a lifecycle, task status, queue
format, branch procedure, or review action in this repository.

Do not fall back to Meridian Lean Delivery. In particular, checkbox statuses, moving
tasks to `tasks/done/`, using `PROJECT_PLAN.md` as the canonical queue,
autonomous task selection, and direct completion updates that bypass a task's
review policy are prohibited. A request such as “update the queue” changes
only the authorized governed-SDD record and never authorizes a different
workflow. If the local workflow documents are absent, contradictory, or cannot
be read before a mutation, return `BLOCKED` without changing files or Git
state.

## Document precedence

When documents conflict, the first applicable document wins:

1. `LANGUAGE_POLICY.md` — mandatory conversation-language preference and English-only repository-text invariant.
2. `AGENTS.md` / `CLAUDE.md` — operating rules for the active agent.
3. `docs/ARCHITECTURE_DECISIONS.md` — accepted architecture decisions.
4. Project and milestone specifications.
5. `tasks/QUEUE.md` and atomic task files — execution scope, dependencies, review policy, and validation.
6. `docs/CODE_ORGANIZATION.md` — normative source-organization policy; it cannot change task scope, behavior, or public contracts.
7. Design/background documents.

Implementation never resolves a conflict silently: update the lower-precedence document or record an ADR.

## Task lifecycle

```text
Review: REQUIRED
QUEUED -> IN_PROGRESS -> READY_FOR_REVIEW -> ACCEPTED

Review: NOT_REQUIRED
QUEUED -> IN_PROGRESS -> ACCEPTED
```

Only `ACCEPTED` tasks satisfy dependencies.

## Execution assets

- `docs/CONTEXT_BUDGET_POLICY.md` defines task-first context loading, reasoning profiles, and concise communication.
- `tasks/TASK_BLUEPRINT.md` defines the canonical atomic-task shape.
- `docs/COMPLETION_REPORT_TEMPLATE.md` defines the implementation and review handoff.
- `docs/CODE_ORGANIZATION.md` defines module ownership, dependency direction, and visibility rules for production code.
- `docs/AUDIT_PROMPT_READ_ONLY.md` defines a read-only conformance audit for this workflow.
- `docs/OPERATOR_PROMPTS.md` provides non-normative, focused prompts for operating the workflow.

For a task or review, start with `AGENTS.md` or `CLAUDE.md`, then read only the assigned task and sources it cites. These assets are operational guidance and do not supersede the precedence order above.

## Roles

- Tech designer: defines ADRs, specifications, task scope, dependencies, and review policy. Does not implement feature code unless explicitly assigned.
- Implementer: works on exactly one task in a dedicated branch/worktree, validates it, creates the task commit, pushes the task branch exactly once, and updates the task state according to its review policy.
- Reviewer-integrator: independently reviews `READY_FOR_REVIEW` tasks in a fresh agent session using the implementer's primary checkout. After `APPROVE`, it records `ACCEPTED` in a local status-only commit and integrates the task branch when repository gates allow it.

The developer drives these roles with three command triggers, defined in `AGENTS.md`/`CLAUDE.md`: `Proceed with <TASK-ID>` starts implementation, `Review <TASK-ID>` starts independent review, and `Accept <TASK-ID>` performs the owner-acceptance status handoff after the developer's own review, skipping the agent review without skipping the status/queue update.

## Review policy

Every task declares `Review: REQUIRED` or `Review: NOT_REQUIRED`. The latter is restricted to low-risk documentation, mechanical configuration, simple scaffolding, or focused tests that add no production behavior. It is prohibited for public APIs, dependencies, security, state transitions, deterministic rules, persistence/history, or unresolved design questions.

## Git workflow

- One writer per worktree.
- Use one branch per task, named from the normalized task ID without a provider prefix (for example, `task-012`).
- After validation, the implementer creates the task commit and pushes the task branch exactly once. Its completion handoff records the task branch, implementation commit, and base `main` commit. It leaves the primary checkout clean and on the task branch; it does not switch back to `main`.
- The reviewer-integrator uses that same primary checkout in a fresh agent session that did not write the implementation. If the session starts on clean `main`, it must run `git switch <task-branch>`. If the task branch is missing locally, or a dirty checkout prevents switching, return `BLOCKED` with the exact condition.
- For `Review: REQUIRED`, the reviewer-integrator must never push the task branch again. Before changing either status record, verify `git merge-base --is-ancestor main <task-branch>`. If it fails, do not mark the task `ACCEPTED`; return `BLOCKED` and do not fetch, rebase, use a non-fast-forward merge, or force-push as recovery. If it passes, create the local status-only `ACCEPTED` commit, switch to `main`, fast-forward merge the task branch, push `main` exactly once, then delete the local task branch.
- For `Review: NOT_REQUIRED`, the implementer performs the same `ACCEPTED` status commit, fast-forward `main` merge, single `main` push, and local task-branch deletion after validation. The implementer may not rebase, amend, or force-push.
- Owner acceptance is an explicit exception: it updates only statuses and does not automatically integrate the branch.
- A forge approval cannot be supplied by the same identity that authored the PR. If an external approval is required but unavailable, leave the PR open and report `BLOCKED`.

### Reviewer-integrator identity on a single-operator project

Both controls below are mandatory, and neither substitutes for the other:

- The review runs in a fresh agent session that did not write the code. The reviewer re-derives evidence from the actual diff and cited sources rather than trusting the implementation report.
- Only for the acceptance commit, use this project-scoped reviewer-specific author override, replacing the placeholders with the project's actual name and slug:

  ```bash
  git commit --author="<PROJECT_NAME> Reviewer-Integrator <reviewer-integrator@<project-slug>.local>" -m "docs: reviewer-integrator pass <TASK-ID>; independently re-verified diff, cited sources, acceptance evidence, and validation"
  ```

Keep the operator's normal committer identity. Do not change global or repository Git config. The author override applies only to the `ACCEPTED` commit and can be verified with `git log --format='%an <%ae>'`.

## Execution discipline

Apply `docs/CONTEXT_BUDGET_POLICY.md`. The review-policy restrictions above remain authoritative; use parallel agents only when their scopes and worktrees are independent.
