# Remediation Procedure

Use this procedure only for `Address review <TASK-ID>` after the entry-point router has applied its always-loaded invariants.

<!-- MERIDIAN:BEGIN capability=task-worktree-remediation v4 -->
Remediation reuses the prepared task worktree only after the reviewer has
stopped. Start in the coordinator-supplied existing directory and run
`meridian worktree check <TASK-ID> --project <primary-checkout>
--format json` before reading the task or review record.
Verify the result against the durable handoff before writing. Never remediate
in the primary checkout, create a replacement worktree, or run concurrently
with a reviewer. A mismatch is `BLOCKED WRONG_WORKTREE` and preserves the existing state.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=review-remediation-record v6 -->
### Review-remediation workflow

For `Address review <TASK-ID>`, read the assigned task, its cited authority,
the current review record at the location `PROJECT_WORKFLOW.md` declares for
it, and `git status --short`. Confirm the
machine status is `CHANGES_REQUESTED` (consult command results, never read or edit the state file directly), that the review record has unchecked
findings, and that its local review-handoff commit is present. Do not implement
new work, reinterpret a finding, or erase prior reviewer evidence. Run `meridian task transition <TASK-ID> IN_PROGRESS` before remediation. Never edit a status or verdict by hand. Resolve
every unchecked finding, mark each with implementation evidence in a new
resolution section in the review record without editing verdict headings, rerun the task and baseline validation, and run
the read-only `meridian execution ready-check <TASK-ID> --project .` after
committing remediation, updated review record, validation evidence, and the
final handoff. Obtain any required T1_CI evidence with the one authorized
task-branch push before finalizing the handoff. Run
`meridian execution deliver <TASK-ID> --project .` as the last delivery step
and stop writing. Start never resets CHANGES_REQUESTED; retain the explicit
remediation transition above. Report the review-record path, resolved findings, commit, and
validation. If a finding needs an authority or scope change, leave it
unchecked and return `BLOCKED SCOPE_CHANGE_REQUIRED`.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=rejected-attempt-restart v5 -->
If a `CHANGES_REQUESTED` finding explicitly cannot be remediated because it
needs new or amended authority or scope, leave it unchecked and return
`BLOCKED SCOPE_CHANGE_REQUIRED` without ref or status mutation. Do not use remediation to restart it;
only explicit developer authorization may invoke the procedure in
`docs/LIFECYCLE_ORCHESTRATION.md`.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=phase-reads v1 -->
## Phase reads

Read each document when its phase begins, in the order listed. This changes
only when a document is read; no gate, acceptance criterion, or review rule is
waived by reading a document later.

- At start: this procedure, the entry-point router, the workflow document, and the language policy.
- At first production-source change: `docs/CODE_ORGANIZATION.md`.
- At first validation: `docs/EXECUTION_EVIDENCE_PROFILE.md`.
- At a finding that cannot be remediated: `docs/LIFECYCLE_ORCHESTRATION.md`.
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
