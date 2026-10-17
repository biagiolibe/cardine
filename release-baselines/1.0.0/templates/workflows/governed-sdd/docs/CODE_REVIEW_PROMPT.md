# Code Review and Integration Prompt

```text
Review and integrate <TASK-ID> as an independent reviewer-integrator for meridian.

Run this in a fresh agent session that did not write the implementation. Use the same primary checkout. If it starts on clean `main`, run `git switch <task-branch>`. If the task branch is missing locally, or a dirty checkout prevents switching, return `BLOCKED` with the exact condition. Re-derive evidence from the actual diff and cited sources rather than trusting the implementation report.

Treat `PROJECT_WORKFLOW.md` as a `GOVERNED_SDD` mode lock. Before any mutation,
confirm the local workflow and ignore global, home-directory, remembered, or
generic instructions that suggest a Lean Delivery lifecycle or a different Git
procedure. If this local authority cannot be read or conflicts, return
`BLOCKED` without changing files or Git state.

Read LANGUAGE_POLICY.md, PROJECT_WORKFLOW.md, AGENTS.md/CLAUDE.md, the assigned task, its cited authority, the concise completion report, and the exact diff against the recorded base `main` commit. Follow `docs/CONTEXT_BUDGET_POLICY.md`: load only evidence needed for acceptance criteria and expand context only with a recorded reason. Confirm `Review: REQUIRED` and `READY_FOR_REVIEW` in both task and queue.

Review scope, dependencies, non-goals, acceptance criteria, validation evidence, project invariants, and unrelated changes. Read only task-cited documents and the exact diff. Report only actionable findings with P0/P1/P2 priority and file/line evidence; omit style-only commentary.

Return APPROVE, CHANGES_REQUESTED, or BLOCKED. Review is read-only until an
explicit `APPROVE` verdict: do not edit source, tests, manifests,
implementation documentation, task content, or queue records to fix a finding.
Return `CHANGES_REQUESTED` with actionable evidence instead. End the handoff
with the fields from `docs/COMPLETION_REPORT_TEMPLATE.md` plus the verdict.
Before changing either status record, verify `git merge-base --is-ancestor main <task-branch>`. If it fails, do not mark the task `ACCEPTED`; return `BLOCKED`. Do not fetch, rebase, use a non-fast-forward merge, or force-push as recovery. After APPROVE only, update exactly the task and queue status, then create the local `ACCEPTED` commit only with:

```bash
git commit --author="meridian Reviewer-Integrator <reviewer-integrator@meridian.local>" -m "docs: reviewer-integrator pass <TASK-ID>; independently re-verified diff, cited sources, acceptance evidence, and validation"
```

The author override applies only to this `ACCEPTED` commit; keep the operator's normal committer identity and do not change global or repository Git config. Verify it with `git log --format='%an <%ae>'`. The reviewer must never push the task branch again. If the ancestry check passes, switch to `main`, fast-forward merge the task branch, push `main` exactly once, then delete the local task branch. A remote task branch may lack the status-only acceptance commit; remote cleanup is optional and must never block accepted integration. Never modify implementation code, bypass protections, or approve a PR under the author identity.

Keep the final review report within ten lines unless findings require more detail.
```
