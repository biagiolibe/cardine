# Pull Request Policy

Task context loading, reasoning selection, task shape, and completion handoffs are governed by `docs/CONTEXT_BUDGET_POLICY.md`, `tasks/TASK_BLUEPRINT.md`, and `docs/COMPLETION_REPORT_TEMPLATE.md`; this document defines review and forge integration only.

For `Review: REQUIRED`, the implementer pushes the task branch exactly once after validation and records the branch name, implementation commit, and base `main` commit in the completion handoff. The reviewer-integrator uses the same primary checkout in a fresh session that did not write the implementation. It must never push the task branch again.

If the reviewer session starts on clean `main`, run `git switch <task-branch>`. If the task branch is missing locally, or a dirty checkout prevents switching, return `BLOCKED` with the exact condition.

Before changing either status record, verify:

```bash
git merge-base --is-ancestor main <task-branch>
```

If this fails, do not mark the task `ACCEPTED`; return `BLOCKED`. Do not fetch, rebase, use a non-fast-forward merge, or force-push as recovery. After `APPROVE`, create only the local status-only `ACCEPTED` commit. If the check passes, switch to `main`, fast-forward merge the task branch, push `main` exactly once, then delete the local task branch.

For `Review: NOT_REQUIRED`, the implementer performs the same `ACCEPTED` status commit, fast-forward `main` merge, single `main` push, and local task-branch deletion after validation. Owner acceptance remains an explicit exception: it updates only statuses and does not automatically integrate the branch.

## Remote task-branch cleanup

A remote task branch may intentionally lack a local, status-only `ACCEPTED` commit: its acceptance evidence is published through the subsequent `main` push. Once `main` contains and has pushed the accepted work, local integration is complete and the local task branch may be deleted.

Remote task-branch deletion is optional and non-blocking. After successful `main` integration, an agent may attempt `git push origin --delete <task-branch>` without force. If the remote deletion fails or the branch is already absent, report a warning only. Never block accepted integration, fetch/rebase, or force-delete solely to clean up a remote task branch.

If the forge requires an approving review, a distinct authorized reviewer identity is required. The PR author cannot satisfy that gate.

## Reviewer-integrator identity on a single-operator project

Review must run in a fresh agent session that did not write the code and must re-derive evidence from the actual diff and cited sources. For the `ACCEPTED` commit only, use the project-scoped reviewer-specific author override, while retaining the operator's normal committer identity:

```bash
git commit --author="<PROJECT_NAME> Reviewer-Integrator <reviewer-integrator@<project-slug>.local>" -m "docs: reviewer-integrator pass <TASK-ID>; independently re-verified diff, cited sources, acceptance evidence, and validation"
```

Do not change global or repository Git config. Verify the override with `git log --format='%an <%ae>'`.
