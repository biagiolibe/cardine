# Governed SDD Workflow — [Project Name]

<!-- MERIDIAN:BEGIN capability=workflow-mode-lock v2 -->
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
be read before a mutation, return `BLOCKED WORKFLOW_UNREADABLE` without changing files or Git
state.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=document-precedence v2 -->
## Document precedence

When documents conflict, the first applicable document wins:

1. `LANGUAGE_POLICY.md` — mandatory conversation-language preference and English-only repository-text invariant.
2. `AGENTS.md` / `CLAUDE.md` — operating rules for the active agent.
3. `docs/ARCHITECTURE_DECISIONS.md` — accepted architecture decisions.
4. Project and milestone specifications.
5. The project's task queue (resolved by `meridian locations`) and atomic task files — execution scope, dependencies, review policy, and validation.
6. `docs/CODE_ORGANIZATION.md` — normative source-organization policy; it cannot change task scope, behavior, or public contracts.
7. Design/background documents.

Implementation never resolves a conflict silently: update the lower-precedence document or record an ADR.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=task-lifecycle v4 -->
## Task lifecycle

```text
Review: REQUIRED
QUEUED -> IN_PROGRESS -> READY_FOR_REVIEW -> ACCEPTED
                         |                    ^
                         +-> CHANGES_REQUESTED -> IN_PROGRESS

Review: NOT_REQUIRED
QUEUED -> IN_PROGRESS -> ACCEPTED

Class: SPIKE
QUEUED -> IN_PROGRESS -> ANSWERED | INCONCLUSIVE
```

Only `ACCEPTED` tasks satisfy dependencies. `ANSWERED` also satisfies a
dependency — it is a `SPIKE`'s completion state and records that its
deliverable (an ADR or a documented reference value; see `tasks/TASK_BLUEPRINT.md`'s
spike shape) answered the declared `Question`. `INCONCLUSIVE` does not
satisfy a dependency: it records that the spike's `Budget` was exhausted
without answering `Question`, and the dependent task stays blocked until a
follow-up spike or a redesign removes the dependency.

Tooling that tallies queue entries by `Review: REQUIRED`/`NOT_REQUIRED` lifecycle
states (for example, the queue-briefing hook) does not recognize
`ANSWERED`/`INCONCLUSIVE`; a `SPIKE` entry is invisible to those counts by
design, since it never merges production code for them to track.

The tracked `.meridian/tasks/<TASK-ID>.json` file is the only status and review-verdict authority. Use `meridian task transition <TASK-ID> <STATUS>` for lifecycle transitions and `meridian review verdict <TASK-ID> APPROVE|CHANGES_REQUESTED|BLOCKED` for review. Never edit a status or verdict by hand, including the JSON file, record projection, or review attempt heading. Commands update their human-readable projections; agents never load state files as startup context. Adopt open legacy tasks explicitly with `meridian task state import --project <path> --format json`, inspect the evidence, then repeat with `--apply`. Terminal legacy tasks need no file. A task branch never edits the
queue, the queue archive, or the plan: `meridian worktree integrate stage`
applies the queue's status on the merged candidate tree, and in-progress state
is derived from the task branch, its registered worktree, and its unarchived
record.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=execution-assets v4 -->
## Execution assets

- `docs/CONTEXT_BUDGET_POLICY.md` defines task-first context loading and concise communication.
- `tasks/TASK_BLUEPRINT.md` defines the canonical atomic-task shape.
- `docs/COMPLETION_REPORT_TEMPLATE.md` defines the implementation and review handoff.
- Completion handoffs live at `tasks/handoffs/<TASK-ID>.md`.
- `docs/REVIEW_RECORD_TEMPLATE.md` defines the durable reviewer-to-implementer handoff for requested changes.
- `docs/LIFECYCLE_ORCHESTRATION.md` defines the autonomous orchestration of one task through implementation, review, remediation, and integration.
- `docs/CODE_ORGANIZATION.md` defines module ownership, dependency direction, and visibility rules for production code.
- `docs/AUDIT_PROMPT_READ_ONLY.md` defines a read-only conformance audit for this workflow.
- `docs/OPERATOR_PROMPTS.md` provides non-normative, focused prompts for operating the workflow.

For a task or review, start with `AGENTS.md` or `CLAUDE.md`, then read only the assigned task and sources it cites. These assets are operational guidance and do not supersede the precedence order above.

**Canonical locations.** Task files live at `tasks/<TASK-ID>.md`, the queue at
`tasks/QUEUE.md`, and durable review records at `tasks/reviews/<TASK-ID>.md`,
unless `.meridian/project.json` or this section declares different locations
for this project. These are defaults: run `meridian locations` for the
resolved values. Every other document names a location by role (the queue,
the review record, the completion handoff), never by a path of its own.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=task-identity-policy v1 -->
## Task identity

`.meridian/task-identity.json` is the sole optional project declaration for
task-identity policy. Its absence selects backwards-compatible `opaque` mode;
an explicit version-1 declaration may select `opaque` or `milestone` mode.
Meridian resolves task IDs through this declaration and the canonical task and
queue authorities. Workflow mode, host configuration, and identifier spelling
do not provide a second identity policy or imply task semantics.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=roles v4 -->
## Roles

- Tech designer: defines ADRs, specifications, task scope, dependencies, and review policy. Does not implement feature code unless explicitly assigned.
- Implementer: works on exactly one task in its deterministic linked worktree, validates it, creates the task commit, pushes the task branch only to obtain `T1_CI` (at most once per review attempt, and not at all without CI), and records task status in the task record according to its review policy. It never implements in the primary checkout.
- Reviewer-integrator: independently reviews `READY_FOR_REVIEW` tasks in a fresh agent session using the same dedicated task worktree after the implementer has stopped. It records review evidence in the task's review record for every verdict and never pushes the task branch. For `CHANGES_REQUESTED`, it runs `meridian review verdict <TASK-ID> CHANGES_REQUESTED`; after `APPROVE`, it runs `meridian review verdict <TASK-ID> APPROVE` and commits the state and projections in the local review-and-status commit and integrates from the primary checkout when repository gates allow it.
- Orchestrator: coordinates one explicitly assigned task through distinct implementer and reviewer-integrator sessions. It uses only durable task, review, validation, and Git evidence to select the next permitted action; it never implements or reviews substantively.

The developer drives these roles with five command triggers, defined in `AGENTS.md`/`CLAUDE.md`: `Proceed with <TASK-ID>` starts implementation, `Review <TASK-ID>` starts independent review, `Address review <TASK-ID>` starts the bounded remediation recorded by the reviewer, `Run lifecycle <TASK-ID>` authorizes the orchestrated implementation-to-integration loop, and `Accept <TASK-ID>` records the owner's own review as an `APPROVE` attempt and continues the closure at C6, skipping the agent review without skipping any later gate.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=review-policy v3 -->
## Review policy

Every task declares `Review: REQUIRED`, `Review: NOT_REQUIRED`, or is a
`Class: SPIKE` task governed by its own gate below. `Review: NOT_REQUIRED` is
restricted to low-risk documentation, mechanical configuration, simple
scaffolding, or focused tests that add no production behavior. It is
prohibited for public APIs, dependencies, security, state transitions,
deterministic rules, persistence/history, or unresolved design questions —
unless the task itself is a `SPIKE`, whose entire purpose is investigating one
unresolved design question and whose deliverable is never production code.

A `SPIKE` task does not declare `Review: REQUIRED` or `NOT_REQUIRED`; the
queue's `Review` column carries `SPIKE` for it instead. At close-out
the implementer self-administers this gate: does the committed
deliverable answer the declared `Question` within the declared `Budget`? If
yes, record `ANSWERED`; if `Budget` is exhausted first, record
`INCONCLUSIVE`. No separate reviewer pass is required — a spike's bounded
blast radius (it integrates only its deliverable, never merges production
code, and has a declared budget) is what justifies skipping full review. If the
committed deliverable does not self-evidently answer `Question`, record
`INCONCLUSIVE` rather than `ANSWERED` on the strength of author judgment.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=codex-worktree-access v4 -->
Task worktrees live below one machine-level resolved root, namespaced as
`<root>/<remote-host>/<owner>/<repository>/<canonical-task-id>`. Use `meridian
codex worktree-path` for derivation and collision checks and `meridian codex
doctor` for separate trust, permission-model, root-write, command-policy, and
Git-metadata status. Once per machine, run `meridian setup --check`, review the
bounded changes, then explicitly consent with `meridian setup --apply` and
restart Codex. Claude Code needs no host configuration. Static configuration
alone never proves effective host access.

If `meridian codex configure --check` reports `repair-required`, the effective
profile is identical and only Meridian's ownership markers were damaged, for
example by a Codex app rewrite. Review the printed diff and run `--apply` only
after explicit confirmation. A `blocked` status names the diverging fields and
requires manual reconciliation. Repair never proves that a running session
loaded the profile; start a fresh session and probe it.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=worktree-command-locations v1 -->
Before switching from worktree prepare/check to execution start, consult the
[command location table](docs/WORKTREE_LIFECYCLE.md#command-locations).
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=bounded-worktree-lifecycle v5 -->
For coordinator-launched implementation, review, or remediation work, the
coordinator runs `meridian worktree prepare` before creating the worker and
passes the returned existing path, branch, primary checkout, and worktree root
as durable launch inputs. Every such worker starts in that exact directory and
runs read-only `meridian worktree check` before any task, handoff,
implementation, or diff read. A manually typed `Proceed with <TASK-ID>` with
no coordinator launch inputs follows the manual-start rule in
`docs/workflows/IMPLEMENTATION.md`: it prepares exactly the triggered task and
then checks the returned worktree before reading task material. Hosts must not
create a substitute checkout. Integration uses `meridian worktree integrate
stage`, separately recorded candidate validation, and `integrate finalize` or
`integrate abort`; verified post-push cleanup uses `meridian worktree cleanup`.
See `docs/WORKTREE_LIFECYCLE.md`.
After check and minimal metadata/contract resolution, run
`meridian execution start <TASK-ID> --project <task-worktree>` before
substantive authority/source analysis, advisor consultation, or implementation.
Only explicit Resume passes `--resume` after status/diff inspection and sole
writer confirmation. Lean start adds no machine state; Governed start records
the first IN_PROGRESS transition once. Read-only review/status never starts.
Absolute paths are runtime launch inputs only. A handoff or other tracked
record that names the worktree uses the `handoff_worktree` value returned by
`meridian worktree prepare`, the path relative to the worktree root, never an
absolute path.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=git-workflow v14 -->
## Git workflow

### Authority of `Proceed with`

`Proceed with <TASK-ID>` authorizes that task's whole lifecycle when every gate
passes: implementation and validation on the task branch; completion and
archive records; `meridian worktree integrate stage`, the selected candidate
validation, and `integrate finalize` or `abort`; one plain `git push origin
main` of the resulting integration; and `meridian worktree cleanup`. Do not
ask for confirmation at any of these steps. When a gate fails, stop once with
`BLOCKED <CODE>` and the resume command.

After `APPROVE`, `Review <TASK-ID>` carries the same authority for C6 through
C10, including the one plain `git push origin main` and cleanup, subject to the
same gates and prohibitions.

It also authorizes, for the first review attempt, one plain `git push origin
<task-branch>`, where `<task-branch>` is the `branch` value returned by
`meridian worktree prepare`, only when needed to obtain `T1_CI` validation for
that task commit. `Address review <TASK-ID>` authorizes the one push for the
next attempt. A task-branch push is never made by the reviewer, at most once per
review attempt, and not at all when the project has no CI. `Proceed with` never authorizes creating,
moving, or pushing a tag; publishing a release; a force push or a push that
deletes or mirrors references; rewriting history (amend of pushed commits,
rebase, reset, cherry-pick); deleting an unmerged branch or force-removing a
worktree; bypassing a required independent review; resolving a textual
conflict; or work on another task.

- `Review: REQUIRED` is a gate, not a request for authorization: after C3,
  stop at `REVIEW_REQUIRED`. A fresh reviewer-integrator must approve before
  continuing at C4, and performs C6 through C10 after approval.
- `Review: NOT_REQUIRED` tasks proceed through C10 after their validation and
  accepted-status commit. No reviewer session is required.

- One writer at a time owns each task worktree. `meridian worktree prepare` consumes the shared task-identity resolver and repository-qualified path derivation, rejects partial or mismatched state, and returns the only branch and path workers may use.
- Before any task read or mutation, the worker runs `meridian worktree check` from the exact prepared path. A host-created checkout, the primary checkout, or any sibling path is `BLOCKED WRONG_WORKTREE` even when its branch and HEAD appear correct.
- After validation, the implementer creates the task commit and, only when `T1_CI` validation is needed, pushes the task branch at most once for each review attempt; a project without CI never pushes it. Its completion handoff records the task branch, the machine-independent worktree value (the `handoff_worktree` field returned by `meridian worktree prepare`: the path relative to the worktree root, never an absolute path), implementation commit, validated task commit, validated base `main` commit, exact successful validation commands or CI evidence, the declared integration surface, and whether full combined-tree validation is required. It stops writing before review and leaves the dedicated worktree clean.
- The reviewer-integrator's first review action in a fresh session is a fail-closed preflight against the completion handoff: before reading the task, implementation files, or diff, resolve the recorded `handoff_worktree` value against the worktree root at runtime, then locate the resulting absolute path and the recorded branch in `git worktree list --porcelain`, confirm the implementer has stopped, and verify the registered path, branch, HEAD, cleanliness, validated task commit, and validated base commit. Any missing or mismatched evidence is `BLOCKED WRONG_WORKTREE` and preserves all state. A session launched from the primary checkout roots every review read and Git command in the verified task worktree; it never switches or treats the primary checkout as the task checkout.
- For `Review: REQUIRED`, the reviewer-integrator must never push the task branch. On `CHANGES_REQUESTED`, it runs `meridian review verdict <TASK-ID> CHANGES_REQUESTED --body <review-evidence>` on the clean reviewed HEAD, then creates a local review-handoff commit containing only the state file, review record, and task record projection; it does not edit implementation artifacts. The implementer resolves that record, creates the next implementation commit, and, only to obtain `T1_CI`, pushes the branch once for the next review attempt. After `APPROVE`, run `meridian review verdict <TASK-ID> APPROVE --body <review-evidence>` on the clean reviewed HEAD and commit its state file and projections on the task branch.
- For `Review: NOT_REQUIRED`, the implementer runs `meridian task transition <TASK-ID> ACCEPTED` after validation and commits its state file and record projection. Neither path rebases, amends, cherry-picks, or force-pushes reviewed task commits.
- Final integration is serialized in the primary checkout through `meridian worktree integrate stage`. That command verifies accepted evidence, owns the lease and prescribed no-commit merge, and returns the deterministic decision and candidate tree without running project code. Run the selected bounded or full gate separately in the ordinary sandbox, bind successful evidence to that tree, and call `integrate finalize`; call `integrate abort` after failure. Stale or mismatched evidence is `BLOCKED EVIDENCE_MISMATCH`; missing or incomplete evidence is `BLOCKED EVIDENCE_INCOMPLETE`.
- Task branches never edit the project's queue, queue archive, or plan (`meridian locations` resolves them). They edit only their own task record, its exact archive, its review record, its handoff, and its own `.meridian/tasks/<TASK-ID>.json` state file. `integrate stage` applies queue and plan status and phase archival once on the merged candidate tree. A shared-governance conflict aborts integration; never choose one task's state over another.
- Only after successful validated integration and any required `main` push, use `meridian worktree cleanup`. Failure, requested changes, cancellation, or blocked integration retains both; exceptional cleanup remains explicitly authorized and outside the bounded command.
- `Accept <TASK-ID>` runs `meridian review verdict <TASK-ID> APPROVE --owner --body <owner-evidence>` on the clean reviewed HEAD, commits the state file and projections, and continues at C6 under the `Proceed with` authority. A manual merge is never permitted.
- A forge approval cannot be supplied by the same identity that authored the PR. If an external approval is required but unavailable, leave the PR open and report `BLOCKED REVIEW_REQUIRED`.

### Stops and denials

The deny list above stays in force without a supporting command. A stop is
valid only when it is backed by a `BLOCKED <CODE>` line from a Meridian
command, a non-zero exit of a required command, an acceptance criterion you
can name as unmet, or a judgment stop that this workflow names with its code. Guidance that no command backs is advice: follow it when you
can, and never stop on its strength alone.

Never satisfy a gate by writing false state, such as setting a status only to
pass a check. When a gate contradicts another rule, stop with `BLOCKED RULE_CONFLICT` and
report both rules.

When a Meridian command accepted a state that this text appears to forbid,
follow the command and record the difference under `Rule discrepancies:` in the
handoff. This never covers an action on the deny list and never overrides a
stop that a command printed.

### Closure

Close a validated task with `meridian worktree advance`. After verifying the
acceptance criteria, running validation, and committing the completion record
and handoff, run `meridian worktree advance <TASK-ID> --project
<primary-checkout> --format json` from the primary checkout, giving each result
as `--validation-command`/`--validation-exit-code` with `--accepted`. Perform
exactly its `action_required`, rerun it with the results (candidate validation
uses `--candidate-command`/`--candidate-exit-code`), and report its `BLOCKED <CODE>`
line when it stops. `docs/WORKTREE_LIFECYCLE.md` keeps the single-step commands
for diagnosis and manual recovery.
A named sandbox skip is not a validation failure only when the test itself
reports it and no acceptance criterion depends solely on that test. Record its
test name, reason, and reporting command as `Validation skips:` in the handoff.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=execution-discipline v1 -->
## Execution discipline

Apply `docs/CONTEXT_BUDGET_POLICY.md`. The review-policy restrictions above remain authoritative; use parallel agents only when their scopes and worktrees are independent.
<!-- MERIDIAN:END -->

<!-- MERIDIAN:BEGIN capability=worktree-budget-retirement v1 -->
## Budget attempts after worktree retirement

Retiring a worktree does not reset its budget. If preparation reports
`BLOCKED BUDGET_ATTEMPT_REQUIRES_AUTHORIZATION`, the agent stops and reports
the inherited counters and resume command. Only the developer may authorize
`meridian worktree prepare <TASK-ID> --new-attempt --reason "<text>" --format json`,
as with a budget overrun. A general Proceed directive does not authorize this
option. It requires no registered task worktree, records the reason and prior
counters in the journal, and starts the next attempt at zero while preserving
history, task status, and caps.
<!-- MERIDIAN:END -->
