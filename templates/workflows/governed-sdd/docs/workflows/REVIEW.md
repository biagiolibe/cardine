# Review Procedure

Use this procedure only for `Review <TASK-ID>` after the entry-point router has applied its always-loaded invariants.

<!-- MERIDIAN:BEGIN capability=task-worktree-review-procedure v13 -->
## Mandatory task-worktree preflight

After `APPROVE`, `Review <TASK-ID>` has the `Proceed with` authority for C6 through C10, including the single plain `git push origin main` and cleanup, with the same prohibitions.

This is the first review action. Before reading the assigned task,
implementation files, or any implementation diff:

1. Start in the exact existing directory returned by `meridian worktree
   prepare` and run `meridian worktree check <TASK-ID> --project
   <primary-checkout> --format json`. A blocked result
   stops before any other read; never use host automatic worktree isolation.
2. Resolve the canonical completion-handoff location and read only that
   handoff. Obtain its `handoff_worktree` value (relative to the worktree root), task branch, current task
   commit, validated task commit, and validated base `main` commit. Confirm
   that the implementer session has stopped. A missing field, missing handoff,
   or active or unconfirmed implementer is `BLOCKED EVIDENCE_INCOMPLETE`.
3. Confirm that the successful check result and handoff name the same path,
   branch, HEAD, base, clean state, and repository. As an additional bounded
   check, run `git worktree list
   --porcelain` and locate exactly one registered entry whose normalized
   absolute path equals the `handoff_worktree` value resolved against the
   worktree root at runtime. The entry must record the handoff branch
   as `refs/heads/<task-branch>` and its `HEAD`. A full-SHA current task commit
   field must equal that `HEAD`. The handoff may describe the final delivery commit by its known subject
   `Deliver <TASK-ID> for review`, rather than a not-yet-existent SHA.
   For a descriptive current task commit field,
   resolve it to the registered task branch `HEAD` and confirm its stated
   subject matches `git log -1 --format=%s <task-branch>`; treat that resolved
   value as `HEAD` for this comparison. Do not infer the task worktree from
   the session's initial current directory. If the path is absent, unregistered,
   duplicated, disagrees with the handoff, names a different commit, or has a
   mismatched subject, return `BLOCKED WRONG_WORKTREE`.
4. Root additional read-only Git checks in the recorded path with `git -C
   <absolute-task-worktree> ...`. Verify its absolute top level, symbolic
   branch, `HEAD`, and empty `git status --short`; verify that the validated
   task and base commits exist; then verify that the base is an ancestor of
   the validated task commit and the validated task commit is an ancestor of
   current task `HEAD`. A missing commit, detached or mismatched branch,
   mismatched `HEAD`, dirty worktree, or failed ancestry check is `BLOCKED WRONG_WORKTREE`.

5. Run read-only `meridian execution ready-check <TASK-ID> --project .`
   in the verified worktree. Require a committed READY_FOR_REVIEW delivery
   and clean worktree before review. Pending delivery/changes cannot launch
   review. Never run execution start for a review or status request.

Every failure above stops before substantive review and preserves the task,
branch, primary checkout, and linked worktree exactly as found. Never switch,
move, create, repair, or delete a checkout to make preflight pass. The bounded
`check` result is required and is never replaced by a branch name or the
worker's initial directory.

Only after every preflight check passes may the reviewer read the task, queue,
implementation files, or compute the implementation diff. When the session
started in the primary checkout, every such read uses the verified absolute
task-worktree path and every Git command uses `git -C
<absolute-task-worktree>`; the initial current directory is never treated as
the task checkout. Review never runs concurrently with an implementer.

After approval, on the clean reviewed HEAD run `meridian review verdict <TASK-ID> APPROVE --body <review-evidence>`. The command binds approval to HEAD and writes the state file, review heading, and task Status projection. Commit those three artifacts on the task branch, then use the serialized integration transaction in `PROJECT_WORKFLOW.md`. Never edit a status or verdict by hand.
The validated task commit must remain an ancestor of task `HEAD`, with only
permitted lifecycle records in the intervening diff. Current `main` may have
advanced; reuse evidence, run the bounded gate, select full validation, or
return `BLOCKED EVIDENCE_MISMATCH` only through that transaction's deterministic decision.
Independent review, acceptance evidence, and forge gates remain mandatory.

`Proceed with <TASK-ID>` already authorizes the gated task lifecycle through
candidate validation, finalize or abort, one plain `git push origin main`, and
cleanup; it also authorizes the first attempt's plain task-branch push, and
`Address review <TASK-ID>` the next one, only to obtain `T1_CI` for that commit, at most once per review attempt, and not at all when the project has no CI. The reviewer never pushes the
task branch. `Proceed with` never authorizes tags, releases, force/deleting/mirroring pushes, history
rewrites, forced worktree removal, bypassing this independent review, textual
conflict resolution, or work on another task. This review is the gate:
`Review: REQUIRED` stops at `REVIEW_REQUIRED`, not to ask whether review may be
skipped. After `APPROVE`, the reviewer-integrator performs C6 through C10.
`Review: NOT_REQUIRED` needs no reviewer and proceeds through C10.

The closure stops are `ACCEPTANCE_UNMET`, `VALIDATION_FAILED`,
`REVIEW_REQUIRED`, `WRONG_WORKTREE`, `EVIDENCE_INCOMPLETE`, `PRIMARY_DIRTY`,
`MAIN_BEHIND_ORIGIN`, `LEASE_HELD`, `INTEGRATION_CONFLICT`,
`CANDIDATE_VALIDATION_FAILED`, `EVIDENCE_MISMATCH`, `PUSH_REJECTED`, and
`CLEANUP_BLOCKED`; each reports once with its resume command. A named,
test-reported sandbox skip is accepted only when no acceptance criterion
depends solely on it and the handoff records it as `Validation skips:`.
<!-- MERIDIAN:END -->

Candidate validation reads the project's declared fragments for `REUSE`, `BOUNDED`,
and `FULL` from `.meridian/candidate-validation.json`; `REUSE` also proves only
governance paths changed. A missing declaration stops before staging rather than silently
accepting evidence.

<!-- MERIDIAN:BEGIN capability=review-mode-boundary v3 -->
### Review-mode boundary

For `Review <TASK-ID>`, do not edit implementation artifacts to remedy findings. Prepare the evidence as a command argument outside the tracked review record so the reviewed worktree stays clean. Record each verdict with `meridian review verdict <TASK-ID> APPROVE|CHANGES_REQUESTED|BLOCKED --body <review-evidence>` on the clean reviewed HEAD. Never edit a status or verdict by hand. For `CHANGES_REQUESTED`, commit only the state file, task record projection, and review record locally; leave machine status `CHANGES_REQUESTED` for the implementer. For a blocking verdict, record and commit only the same governance outputs and report the blocker. Findings with priority and evidence form the bounded remediation scope. Do not push these commits. For `APPROVE`, commit the same three outputs with the required reviewer-integrator author override after the required ancestry check. A reviewer never edits the queue, queue archive, or plan; `integrate stage` applies their status.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=implementer-reviewer-handoff v5 -->
## Implementer-to-reviewer handoff

After validation, create the task commit and, only to obtain `T1_CI` for that commit, at most once per review attempt, and not at all when the project has no CI, push the task branch. The completion handoff must record the branch name,
`handoff_worktree` value (relative to the worktree root, never an absolute path), implementation and current task commits,
validated task and base `main` commits, successful validation evidence, and
declared integration surface. Stop the implementer and leave the registered
task worktree clean before starting the fresh reviewer session. This durable
handoff transfers sequential ownership of that worktree; implementation and
review never overlap.

For `Review: REQUIRED`, the reviewer must never push the task branch. On
`CHANGES_REQUESTED`, it records the verdict with `meridian review verdict <TASK-ID> CHANGES_REQUESTED` and commits only the state file and record projections; the implementer then resolves the findings and
makes the next permitted push. For `Review: NOT_REQUIRED`, the implementer
runs `meridian task transition <TASK-ID> ACCEPTED` after validation without creating a
reviewer session. Owner acceptance runs `meridian review verdict <TASK-ID> APPROVE --owner` and
continues at C6. Checkout selection, validation ancestry, integration, and cleanup
are governed by their current dedicated procedures, not by this handoff.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=reviewer-integrator-identity v3 -->
## Reviewer-integrator identity on a single-operator project

Both controls are mandatory and neither substitutes for the other:

- Review runs in a fresh agent session that did not write the code. Re-derive evidence from the actual diff and cited sources; do not trust the implementation report.
- Only for the `ACCEPTED` commit, use the project-scoped reviewer author override. Its value is printed by `meridian project show --field reviewer-author`, which formats the project declared in `.meridian/project.json`; if that declaration is missing, the command reports `BLOCKED COMMAND_REFUSED` and the commit waits for the developer to declare the project:

  ```bash
  git commit --author="$(meridian project show --field reviewer-author)" -m "docs: reviewer-integrator pass <TASK-ID>; independently re-verified diff, cited sources, acceptance evidence, and validation"
  ```

This is the only place the identity rule is stated; every other document defers to it.

Keep the operator's normal committer identity. Do not change global or repository Git config. The override applies only to the `ACCEPTED` commit and can be verified with `git log --format='%an <%ae>'`.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=phase-reads v1 -->
## Phase reads

Read each document when its phase begins, in the order listed. This changes
only when a document is read; no gate, acceptance criterion, or review rule is
waived by reading a document later.

- At start: this procedure, the entry-point router, the workflow document, and the language policy.
- At first production-source diff hunk: `docs/CODE_ORGANIZATION.md`.
- At first validation evidence check: `docs/EXECUTION_EVIDENCE_PROFILE.md`.
- At verdict: `docs/REVIEW_RECORD_TEMPLATE.md`.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=bounded-context-readers v2 -->
## Bounded context readers

Read the task's cited ADRs and specification sections with `meridian context
authority <TASK-ID>`, and a single ADR with `meridian adr show <ADR-ID>`.
Find the ADR that governs a question with `meridian adr list`, which prints one
line per ADR. Do not open the whole ADR log or a whole specification to find
them. Read the
queue state through the resolved queue briefing, never by opening the whole
queue file. When the briefing did not fire, conflicts with other evidence, or a
row must be read verbatim or edited, locate that row and read only its range.
Open a source document directly only when a bounded reader reports an entry
unresolved or its excerpt cannot verify an acceptance criterion, and record
that reason in the report.
<!-- MERIDIAN:END -->
