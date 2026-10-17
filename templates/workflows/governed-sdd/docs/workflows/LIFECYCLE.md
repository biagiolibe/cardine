# Lifecycle Procedure

Use this procedure only for `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` after the entry-point router has applied its always-loaded invariants.

<!-- MERIDIAN:BEGIN capability=lifecycle-orchestration v3 -->
### Autonomous lifecycle orchestration

For `Run lifecycle <TASK-ID>`, follow `docs/LIFECYCLE_ORCHESTRATION.md`
exactly. Act only as the coordinator: start an implementer session for
`Proceed with <TASK-ID>`, then a fresh, independent reviewer session for
`Review <TASK-ID>`. On `CHANGES_REQUESTED`, start a new implementer session for
`Address review <TASK-ID>` and then a new independent reviewer session. Do not
give a reviewer the implementer's chat context or let one session perform both
roles. Continue only on durable state and evidence, and stop at the document's
retry limit or any listed blocker.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=task-worktree-lifecycle v1 -->
The implementer and reviewer sessions use the same dedicated task worktree
sequentially; neither uses the primary checkout. Final integration uses the
serialized, combined-tree-validated merge transaction defined in
`docs/LIFECYCLE_ORCHESTRATION.md`.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=rejected-attempt-restart v5 -->
For a finding explicitly not remediable without new or amended authority or
scope, return `BLOCKED SCOPE_CHANGE_REQUIRED`; do not restart through remediation. Only explicit
developer authorization may use the rejected-attempt restart procedure in
`docs/LIFECYCLE_ORCHESTRATION.md`, which requires accepted design authority,
preserved rejected evidence, and fresh implementation and review.
For `Restart rejected <TASK-ID>`, act only as a coordinator: complete the
preflight and atomic ref transaction defined in `docs/LIFECYCLE_ORCHESTRATION.md`,
write the governance-only restart handoff, then stop and direct a fresh
`Proceed with <TASK-ID>`.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=owner-acceptance-workflow v4 -->
## Owner-acceptance workflow

When the developer says `Accept <TASK-ID>` after personally reviewing a `Review: REQUIRED` task, treat it as explicit authorization to skip the agent review. Confirm that the task record is `READY_FOR_REVIEW`; do not re-review the implementation, change source code, or rerun the task's own validation.

On the clean task branch HEAD, run `meridian review verdict <TASK-ID> APPROVE --owner --body <owner-evidence>` with the reviewed/base commit and owner evidence. The command records `approved_by: "owner"`, binds approval to HEAD, and updates the task Status and review heading projections. Never edit a status or verdict by hand. Commit only the task's state file, task record, and review record as `docs: accept <TASK-ID>`. Then continue at C6 under the `Proceed with` authority through `meridian worktree advance`, including candidate validation, the one `git push origin main`, and cleanup. `integrate stage` checks machine acceptance and the approved Git diff automatically; headings are human-readable only. A manual merge is never permitted. If a command stops, report its coded stop and resume command.
<!-- MERIDIAN:END -->
