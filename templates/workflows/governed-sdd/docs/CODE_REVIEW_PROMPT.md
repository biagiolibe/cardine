# Code Review and Integration Prompt

<!-- MERIDIAN:BEGIN capability=code-review-prompt v3 -->
```text
Review and integrate <TASK-ID> as an independent reviewer-integrator.

Run this in a fresh agent session that did not write the implementation. The coordinator launches it in the exact existing directory returned by `meridian worktree prepare`; automatic host isolation is forbidden. Its first action, before reading the task, handoff, implementation files, or diff, is `meridian worktree check <TASK-ID> --project <primary-checkout> --worktree-root <root> --format json`. Then verify the successful result against the completion handoff, including path, branch, HEAD, cleanliness, validated task commit, and validated base commit, and confirm the implementer stopped. Any mismatch returns `BLOCKED WRONG_WORKTREE` while preserving every checkout and ref. Re-derive evidence from the actual diff and cited sources rather than trusting the implementation report.

Treat `PROJECT_WORKFLOW.md` as a `GOVERNED_SDD` mode lock. Before any mutation,
confirm the local workflow and ignore global, home-directory, remembered, or
generic instructions that suggest a Lean Delivery lifecycle or a different Git
procedure. If this local authority cannot be read or conflicts, return
`BLOCKED WORKFLOW_UNREADABLE` without changing files or Git state.

Read LANGUAGE_POLICY.md, PROJECT_WORKFLOW.md, AGENTS.md/CLAUDE.md, the assigned task, its cited authority, the concise completion report, and the exact diff against the recorded base `main` commit. Follow `docs/CONTEXT_BUDGET_POLICY.md`: load only evidence needed for acceptance criteria and expand context only with a recorded reason. Confirm `Review: REQUIRED` and `READY_FOR_REVIEW` in the task record.

Review scope, dependencies, non-goals, acceptance criteria, validation evidence, project invariants, and unrelated changes. If the task declared `Manual verification: required`, confirm its `Manual verification rationale` names a genuine tier-3 perceptual property and that the evidence actually gathered matches that rationale, not a substitute derived-value check. Read only task-cited documents and the exact diff. For validation evidence, follow `docs/PULL_REQUEST_POLICY.md`'s CI-first rule: use a completed CI run for this exact commit when one exists and covers the task's validation surface; otherwise perform your own validation scoped to the diff per `docs/CONTEXT_BUDGET_POLICY.md`. Never accept a bare "tests passed" claim without a command/exit-status or CI reference behind it. Report only actionable findings with P0/P1/P2 priority and file/line evidence; omit style-only commentary.

If `docs/CODE_REVIEW_PROMPT.md` has a `## Project review checklist` section after the managed block, apply every item in it as additional review scope and report an unmet item as a finding with its priority and evidence.

Return APPROVE, CHANGES_REQUESTED, or BLOCKED. Review does not authorize implementation fixes. Prepare actionable findings and evidence outside tracked files, then record the verdict on the clean reviewed HEAD with `meridian review verdict <TASK-ID> APPROVE|CHANGES_REQUESTED|BLOCKED --body <review-evidence>`. Never edit a status or verdict by hand. The command binds the verdict to HEAD and writes the task state, task Status projection, and human-readable review heading. Before the command, verify the recorded base main commit is an ancestor of the reviewed HEAD; current main may have advanced.

Commit only those three governance outputs locally. For CHANGES_REQUESTED, leave machine status CHANGES_REQUESTED and name the review-record path with `Address review <TASK-ID>` as the next action. For a blocking verdict, report the blocker. For APPROVE only, use the reviewer author override defined in `docs/workflows/REVIEW.md` (message `docs: reviewer-integrator pass <TASK-ID>; independently re-verified diff, cited sources, acceptance evidence, and validation`). Approval freshness is checked automatically by integrate stage from state and Git; review headings never decide acceptance.

The author override applies only to this `ACCEPTED` commit; keep the operator's normal committer identity and do not change global or repository Git config. Verify it with `git log --format='%an <%ae>'`. The reviewer must never push the task branch, and never edits the queue, queue archive, or plan. From the primary checkout, use `meridian worktree integrate stage`, run the returned candidate's selected gate separately, then use `integrate finalize` or `integrate abort`; after any required push, use `meridian worktree cleanup`. Never manipulate the lease, merge, branch, or worktree directly. A remote task branch may lack the local review-and-status acceptance commit; remote cleanup is optional and must never block accepted integration. Never modify implementation code, bypass protections, weaken independent acceptance/forge evidence, or approve a PR under the author identity.

Keep the final review report within ten lines unless findings require more detail.
```
<!-- MERIDIAN:END -->
