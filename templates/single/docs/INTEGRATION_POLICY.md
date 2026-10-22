# Integration Policy

Task context loading, task shape, and completion handoffs are governed by `docs/CONTEXT_READING_POLICY.md`, `tasks/TASK_BLUEPRINT.md`, and `docs/COMPLETION_REPORT_TEMPLATE.md`; this document defines review and direct integration only.

<!-- CARDINE:BEGIN capability=task-worktree-integration v2 -->
For `Review: required`, the implementer pushes the task branch only to obtain `T1_CI` for that commit, at most once per review attempt, and not at all when the project has no CI, and records its deterministic branch,
machine-independent dedicated-worktree value (relative to the worktree root, never an absolute path), implementation commit, validated task and
base `main` commits, exact successful validation evidence, declared integration
surface, full-validation requirement, and current task commit in the completion handoff. The reviewer-integrator
uses that same task worktree in a fresh session after the implementer stops. It
verifies the registered mapping and cleanliness, never switches the primary
checkout to the task branch, and never pushes the task branch.

When the reviewer requests changes, run `cardine review verdict <TASK-ID> CHANGES_REQUESTED --body <review-evidence>` on the clean reviewed HEAD. Commit only the task state and task/review projections locally; do not push them. The implementer confirms `in_progress` with the retained verdict, resolves every unchecked finding, validates, commits implementation and the final handoff, then runs `cardine execution deliver <TASK-ID> --project .` last and stops writing. Any authorized T1_CI-only task-branch push precedes final handoff and delivery. Never edit a status or verdict by hand.

Before accepting, verify that the validated base is an ancestor of the
validated task commit, that the validated commit is an ancestor of current
task HEAD, and that the intervening diff contains only permitted
task-record, review-record, task-state, and handoff lifecycle records:

```bash
git merge-base --is-ancestor <validated-base-main> <validated-task-commit>
git merge-base --is-ancestor <validated-task-commit> <current-task-commit>
git diff --name-only <validated-task-commit>..<current-task-commit>
```

Current `main` need not be an ancestor of the branch. Missing evidence, a
failed ancestry check, or any task-relevant change after validation is
`BLOCKED EVIDENCE_MISMATCH`; do not record approval or completion. Do not fetch,
rebase, amend, cherry-pick, or force-push as recovery. On the clean reviewed HEAD use `cardine review verdict <TASK-ID> APPROVE --body <review-evidence>`, then commit only the state file and task/review projections. Never edit a status or verdict by hand.

Final integration is serialized in the primary checkout under one exclusive
integration lease, acquired by atomically creating
`cardine-integration.lock` in the absolute common Git directory, which is computed at runtime and never written to a tracked file. An existing
lease is `BLOCKED LEASE_HELD`; only its owner removes it, and stale-lease removal requires
explicit developer authorization. If the primary checkout is missing, dirty,
cannot switch to `main`, return `BLOCKED PRIMARY_DIRTY`; if another integration owns the lease, return
`BLOCKED LEASE_HELD`. Either stop preserves task state. When current `main` equals the validated
base, reuse the task evidence. When it advanced, compare
`git diff --name-only <validated-base>..main` and the advanced dependency,
generated-input, configuration, schema, shared-governance, and behavioral
identities with the handoff's declared integration surface. Equal or nested
paths or any shared identity are material interactions and select full
combined-tree validation. An incomplete declaration or comparison is
`BLOCKED EVIDENCE_MISMATCH`; neither a conflict-free merge nor disjoint filenames establishes
independence. Record an independent comparison before selecting the bounded
gate. An explicit task requirement also selects full validation.

Run `git merge --no-ff --no-commit <task-branch>`. Reject a conflict with `git
merge --abort`; never resolve it by choosing one task's governance state.
Every candidate runs `git diff --check` plus the gate declared in
`validation.candidate` in `.cardine/project.json`, frozen in the task contract.
Task commands supplement the project baseline; `FULL` includes the declared
full suite. Abort on any gate failure, record the
decision, comparison, commands, and results, and only then create the merge
commit and push `main` exactly once. Remove the linked
worktree and then the local branch only after success. Release the lease after
success or a clean abort.

For `Review: not_required`, the implementer commits validation evidence and runs the integration transaction; status remains `in_progress` until landing writes `done`.
`Accept <TASK-ID>` runs `cardine review verdict <TASK-ID> APPROVE --owner --body <owner-evidence>` on clean HEAD, commits the state and projections, and continues at C6 under the `Proceed with`
authority; a manual merge is never permitted.

Task reservation, completion, and review mutations stay on the task branch.
Concurrent tasks change only their own task records and state files. The
generated queue and plan status views are regenerated once, on the integration
candidate tree, by `cardine worktree integrate stage`; no task regenerates them
or archives a phase. Any shared-file conflict blocks integration with both
branches intact.
<!-- CARDINE:END -->

## Validation evidence for review

<!-- CARDINE:BEGIN capability=ci-verified-validation v1 -->
A reviewer never accepts a bare "tests passed" claim as evidence — that
self-report is exactly what an independent review exists to verify, not to
repeat back. Two paths, in order:

1. **CI configured and has a completed run for the exact task-branch
   commit:** use that run's status as validation evidence. A CI run is an
   independent, tamper-evident execution against an immutable commit; do not
   re-run the same checks locally when a passing run for that exact SHA
   already exists — that would be pure duplication of an equally trustworthy
   result. If CI ran but does not cover the task's actual validation
   surface, treat it as partial and fall through to (2) for the rest.
2. **No CI, or none for that commit:** the implementer's local run is
   self-reported and is not, by itself, independent evidence. Perform your
   own validation, scoped to the diff's actual surface per
   `docs/CONTEXT_READING_POLICY.md` — not the implementer's full historical
   run, and not zero verification. This is the difference between "re-derive
   evidence" (required) and "trust the implementation report" (prohibited)
   from `docs/CODE_REVIEW_PROMPT.md`.

Either path requires the completion report to name exact commands and exit
status, or the CI check run, per `docs/COMPLETION_REPORT_TEMPLATE.md` — a
claim that cannot be checked is not evidence.
<!-- CARDINE:END -->

## Remote task-branch cleanup

<!-- CARDINE:BEGIN capability=remote-branch-cleanup v1 -->
A remote task branch may intentionally lack a local review-and-approval commit: its acceptance evidence is published through the subsequent `main` push. Once `main` contains and has pushed the accepted work, local integration is complete and the local task branch may be deleted.

Remote task-branch deletion is optional and non-blocking. After successful `main` integration, an agent may attempt `git push origin --delete <task-branch>` without force. If the remote deletion fails or the branch is already absent, report a warning only. Never block accepted integration, fetch/rebase, or force-delete solely to clean up a remote task branch.
<!-- CARDINE:END -->
