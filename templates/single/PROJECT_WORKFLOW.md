# Workflow — [Project Name]

<!-- CARDINE:BEGIN capability=workflow-mode-lock v1 -->
## Workflow lock

The presence of this file selects the single Cardine lifecycle. Before any file
edit, Git mutation, task selection, or completion claim, an agent must read
this file and `AGENTS.md` or `CLAUDE.md`. Global, home-directory, remembered, or
generic agent instructions are not authority to select a lifecycle, task
status, queue format, branch procedure, or review action in this repository.

The configured preset in `.cardine/project.json` supplies option defaults
(review, authority, expected code surface), never a different lifecycle. A
request such as “update the queue” changes only the authorized record and never
authorizes a different workflow. If the local workflow documents or the project
configuration are absent, contradictory, or cannot be read before a mutation,
return `BLOCKED WORKFLOW_UNREADABLE` without changing files or Git state.
<!-- CARDINE:END -->

## Preset and options

`.cardine/project.json` declares the preset, `lean` or `governed`, and the
project defaults for each task option. Both presets install the same documents
and run the same lifecycle. A preset supplies defaults only:

| Option | `lean` default | `governed` default |
| --- | --- | --- |
| Review | `not_required` | `required` |
| Authority required | no | yes |
| Expected code surface required | no | yes |

Each task may override any option in either direction through its own contract.
A change to the project configuration affects new tasks only; an open task
keeps the options it was created with.

## Minimum task contract

Every task records an objective, acceptance criteria, relevant files or
technical context, dependencies, and validation, following
`tasks/TASK_BLUEPRINT.md`. A quick task is a minimal registered task with an
objective, acceptance and validation, dependencies, and resolved options; no
task is exempt from registration or validation. An omitted optional section
never grants permission for work outside the stated objective, relevant files,
and out-of-scope clauses.

<!-- CARDINE:BEGIN capability=document-precedence v1 -->
## Document precedence

When documents conflict, the first applicable document wins:

1. `LANGUAGE_POLICY.md` — mandatory conversation-language preference and English-only repository-text invariant.
2. `AGENTS.md` / `CLAUDE.md` — operating rules for the active agent.
3. `docs/ARCHITECTURE_DECISIONS.md` — accepted architecture decisions.
4. Project and milestone specifications.
5. The project's task queue (resolved by `cardine locations`) and atomic task files — execution scope, dependencies, review policy, and validation.
6. `docs/CODE_ORGANIZATION.md` — normative source-organization policy; it cannot change task scope, behavior, or public contracts.
7. Design/background documents.

Implementation never resolves a conflict silently: update the lower-precedence document or record an ADR.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=task-lifecycle v2 -->
## Task lifecycle

```text
review required:      queued -> in_progress -> in_review -> in_progress -> done
review not required:  queued -> in_progress -> done
spike:                queued -> in_progress (outcome ANSWERED | INCONCLUSIVE) -> done
any open state:       queued | in_progress | in_review -> cancelled
```

A task enters `in_review` only when its resolved review option is `required`.
Approval of the exact current commit and requested changes both return the
task to `in_progress`; a new implementation commit invalidates an earlier
approval. Acceptance alone is never `done`: `done` is reached only through
verified landing. Only a landed standard task, or a landed spike whose outcome
is `ANSWERED`, satisfies a dependency. `INCONCLUSIVE` and `cancelled` never do.
`done` and `cancelled` are terminal; reopening is a new task.

The tracked `.cardine/tasks/<TASK-ID>.json` file is the only status and review-verdict authority. Use `cardine task transition <TASK-ID> <STATUS>` for lifecycle transitions and `cardine review verdict <TASK-ID> APPROVE|CHANGES_REQUESTED|BLOCKED` for review. Never edit a status or verdict by hand, including the JSON file, record projection, or review attempt heading. Commands update their human-readable projections; agents never load state files as startup context. Adopt open legacy tasks explicitly with `cardine task state import --project <path> --format json`, inspect the evidence, then repeat with `--apply`. Terminal legacy tasks need no file.

Read status from state, never from the queue or the plan: `cardine status`
lists the preset, the totals for all five statuses, and each open task with its
dependencies, blockers, and whether it is startable (`--all` adds terminal
tasks; `--format json` returns the versioned model that the console and the
per-turn briefing read). Only a `queued` task whose
dependencies are all satisfied is startable; `in_progress` and `in_review`
tasks are resumed, never started again. The queue file and the plan's status
region are generated views of that model. Regenerate them with `cardine status
--write`; never edit them. A stale or hand-edited view changes no task, and
`cardine audit` reports it.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=execution-assets v1 -->
## Execution assets

- `docs/CONTEXT_READING_POLICY.md` defines task-first context loading and concise communication.
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
unless `.cardine/project.json` or this section declares different locations
for this project. These are defaults: run `cardine locations` for the
resolved values. Every other document names a location by role (the queue,
the review record, the completion handoff), never by a path of its own.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=task-identity-policy v1 -->
## Task identity

`taskIdentity.mode` in `.cardine/project.json` is the sole project declaration
for task identity. Omission selects `opaque`; an explicit value selects
`opaque` or `milestone`. Preset selection does not change task IDs.
Cardine resolves task IDs through this declaration and the canonical task and
queue authorities. The preset, host configuration, and identifier spelling
do not provide a second identity policy or imply task semantics.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=roles v1 -->
## Roles

- Tech designer: defines ADRs, specifications, task scope, dependencies, and review policy. Does not implement feature code unless explicitly assigned.
- Implementer: works on exactly one task in its deterministic linked worktree, validates it, creates the task commit, pushes the task branch only to obtain `T1_CI` (at most once per review attempt, and not at all without CI), and records task status in the task record according to its review policy. It never implements in the primary checkout.
- Reviewer-integrator: independently reviews `in_review` tasks in a fresh agent session using the same dedicated task worktree after the implementer has stopped. It records review evidence in the task's review record for every verdict and never pushes the task branch. When it requests changes, it runs `cardine review verdict <TASK-ID> CHANGES_REQUESTED`; after `APPROVE`, it runs `cardine review verdict <TASK-ID> APPROVE` and commits the state and projections in the local review-and-status commit and integrates from the primary checkout when repository gates allow it.
- Orchestrator: coordinates one explicitly assigned task through distinct implementer and reviewer-integrator sessions. It uses only durable task, review, validation, and Git evidence to select the next permitted action; it never implements or reviews substantively.

The developer drives these roles with five command triggers, defined in `AGENTS.md`/`CLAUDE.md`: `Proceed with <TASK-ID>` starts implementation, `Review <TASK-ID>` starts independent review, `Address review <TASK-ID>` starts the bounded remediation recorded by the reviewer, `Run lifecycle <TASK-ID>` authorizes the orchestrated implementation-to-integration loop, and `Accept <TASK-ID>` records the owner's own review as an `APPROVE` attempt and continues the closure at C6, skipping the agent review without skipping any later gate.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=review-policy v1 -->
## Review policy

Every task resolves a review option, `required` or `not_required`, from its
own explicit override, the project defaults, and the preset, in that order.
Risk informs the contract choice, but no task class, host, or code surface
silently tightens or loosens it. A lean task may require review; a governed
task may explicitly waive it. Once snapshotted, an open task keeps its review
option until an explicit contract revision invalidates incompatible evidence.

A `SPIKE` task resolves review like any other task. When review is not
required, the implementer self-administers the close-out gate: does the
committed deliverable answer the declared `Question` within the declared
`Timebox`? If yes, record `ANSWERED`; if `Timebox` is exhausted first, record
`INCONCLUSIVE`. If the committed deliverable does not self-evidently answer
`Question`, record `INCONCLUSIVE` rather than `ANSWERED` on the strength of
author judgment. When review is required, the spike waits for an independent
reviewer like any other task.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=codex-worktree-access v1 -->
Task worktrees live below one machine-level resolved root, namespaced as
`<root>/<remote-host>/<owner>/<repository>/<canonical-task-id>`. Use `cardine
codex worktree-path` for derivation and collision checks and `cardine codex
doctor` for separate trust, permission-model, root-write, command-policy, and
Git-metadata status. Once per machine, run `cardine setup --check`, review the
bounded changes, then explicitly consent with `cardine setup --apply` and
restart Codex. Claude Code needs no host configuration. Static configuration
alone never proves effective host access.

If `cardine codex configure --check` reports `repair-required`, the effective
profile is identical and only Cardine's ownership markers were damaged, for
example by a Codex app rewrite. Review the printed diff and run `--apply` only
after explicit confirmation. A `blocked` status names the diverging fields and
requires manual reconciliation. Repair never proves that a running session
loaded the profile; start a fresh session and probe it.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=worktree-command-locations v2 -->
Before switching from worktree prepare/check to execution start, consult the
[command location table](docs/WORKTREE_LIFECYCLE.md#command-locations).
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=bounded-worktree-lifecycle v2 -->
`Proceed with <TASK-ID>` runs `cardine worktree prepare <task-id> --project
<primary-checkout> --format json` before
starting a worker. The coordinator passes the returned branch and absolute
path as durable launch inputs and does not use a host facility that creates a
second checkout. The worker starts in that exact directory and, before any task
read or write, runs `cardine worktree check <task-id> --project
<primary-checkout> --format json`. Any path,
branch, HEAD, root, state, or cleanliness mismatch is `BLOCKED WRONG_WORKTREE`.
After check and minimal metadata/contract resolution, run
`cardine execution start <TASK-ID> --project <task-worktree>` before
substantive authority/source analysis, advisor consultation, or implementation.
Only explicit Resume passes `--resume` after status/diff inspection and sole
writer confirmation, except when `cardine task close` already succeeded:
skip execution start, then run worktree advance. Start records the first `queued -> in_progress` transition once for either
preset and preserves the resolved task contract. Read-only review/status never starts.
Absolute paths are runtime launch inputs only. A handoff or other tracked
record that names the worktree uses the `handoff_worktree` value returned by
`cardine worktree prepare`, the path relative to the worktree root, never an
absolute path.

A `Proceed with <TASK-ID>` directive that says to Resume starts with `cardine
worktree prepare <task-id> --resume --project <primary-checkout> --format json`.
`--resume` is allowed only for that directive. It accepts the task's existing
worktree even when it has uncommitted changes,
never creates or changes anything, and refuses when no worktree exists. Run
`cardine worktree check <task-id> --resume --project <primary-checkout> --format
json` from that exact worktree. Accept `status: ready-dirty`, read `git status`
and the diff, confirm sole writer ownership, then run `cardine execution start
<TASK-ID> --resume --project <task-worktree>`. Classify any other result under
Stops and denials; never treat an unrelated check error as accepted dirt.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=git-workflow v2 -->
## Git workflow

### Authority of `Proceed with`

`Proceed with <TASK-ID>` authorizes that task's whole lifecycle when every gate
passes: implementation and validation on the task branch; completion and
archive records; `cardine worktree integrate stage`, the selected candidate
validation, and `integrate finalize` or `abort`; one plain `git push origin
main` of the resulting integration; and `cardine worktree cleanup`. Do not
ask for confirmation at any of these steps. When a gate fails, classify the outcome
under Stops and denials and follow that class in the same turn.

After `APPROVE`, `Review <TASK-ID>` carries the same authority for C6 through
C10, including the one plain `git push origin main` and cleanup, subject to the
same gates and prohibitions.

It also authorizes, for the first review attempt, one plain `git push origin
<task-branch>`, where `<task-branch>` is the `branch` value returned by
`cardine worktree prepare`, only when needed to obtain `T1_CI` validation for
that task commit. `Address review <TASK-ID>` authorizes the one push for the
next attempt. A task-branch push is never made by the reviewer, at most once per
review attempt, and not at all when the project has no CI. `Proceed with` never authorizes creating,
moving, or pushing a tag; publishing a release; a force push or a push that
deletes or mirrors references; rewriting history (amend of pushed commits,
rebase, reset, cherry-pick); deleting an unmerged branch or force-removing a
worktree; bypassing a required independent review; resolving a textual
conflict; or work on another task.

- `Review: required` is a gate, not a request for authorization: after C3,
  stop at `REVIEW_REQUIRED`. A fresh reviewer-integrator must approve before
  continuing at C4, and performs C6 through C10 after approval.
- `Review: not_required` tasks proceed through C10 after their validation and
  completion handoff and closure records. No reviewer session is required.

- One writer at a time owns each task worktree. `cardine worktree prepare` consumes the shared task-identity resolver and repository-qualified path derivation, rejects partial or mismatched state, and returns the only branch and path workers may use.
- Before any task read or mutation, the worker runs `cardine worktree check` from the exact prepared path. A host-created checkout, the primary checkout, or any sibling path is `BLOCKED WRONG_WORKTREE` even when its branch and HEAD appear correct.
- After validation, the implementer creates the task commit and, only when `T1_CI` validation is needed, pushes the task branch at most once for each review attempt; a project without CI never pushes it. Its completion handoff records the task branch, the machine-independent worktree value (the `handoff_worktree` field returned by `cardine worktree prepare`: the path relative to the worktree root, never an absolute path), implementation commit, validated task commit, validated base `main` commit, exact successful validation commands or CI evidence, the declared integration surface, and whether full combined-tree validation is required. It stops writing before review and leaves the dedicated worktree clean.
- The reviewer-integrator's first review action in a fresh session is a fail-closed preflight against the completion handoff: before reading the task, implementation files, or diff, resolve the recorded `handoff_worktree` value against the worktree root at runtime, then locate the resulting absolute path and the recorded branch in `git worktree list --porcelain`, confirm the implementer has stopped, and verify the registered path, branch, HEAD, cleanliness, validated task commit, and validated base commit. Any missing or mismatched evidence is `BLOCKED WRONG_WORKTREE` and preserves all state. A session launched from the primary checkout roots every review read and Git command in the verified task worktree; it never switches or treats the primary checkout as the task checkout.
- For `Review: required`, the reviewer-integrator must never push the task branch. When it requests changes, it runs `cardine review verdict <TASK-ID> CHANGES_REQUESTED --body <review-evidence>` on the clean reviewed HEAD, then creates a local review-handoff commit containing only the state file, review record, and task record projection; it does not edit implementation artifacts. The implementer resolves that record, creates the next implementation commit, and, only to obtain `T1_CI`, pushes the branch once for the next review attempt. After `APPROVE`, run `cardine review verdict <TASK-ID> APPROVE --body <review-evidence>` on the clean reviewed HEAD and commit its state file and projections on the task branch.
- For `Review: not_required`, the implementer commits validation evidence and proceeds to closure and integration; status remains `in_progress` until landing writes `done`. Neither path rebases, amends, cherry-picks, or force-pushes reviewed task commits.
- Final integration is serialized in the primary checkout through `cardine worktree integrate stage`. That command verifies accepted evidence, owns the lease and prescribed no-commit merge, and returns the deterministic decision and candidate tree without running project code. Run the selected bounded or full gate separately in the ordinary sandbox, bind successful evidence to that tree, and call `integrate finalize`; call `integrate abort` after failure. Stale or mismatched evidence is `BLOCKED EVIDENCE_MISMATCH`; missing or incomplete evidence is `BLOCKED EVIDENCE_INCOMPLETE`.
- Task branches edit only their own task record, its review record, its handoff, and its own `.cardine/tasks/<TASK-ID>.json` state file; they do not regenerate the queue or the plan's status region. `integrate stage` regenerates those generated views once on the merged candidate tree and stages them with the landed state. A failed regeneration is reported as a stale view with `cardine status --write`; it never undoes the landed state. A shared-file conflict aborts integration; never choose one task's state over another.
- Only after successful validated integration and any required `main` push, use `cardine worktree cleanup`. Failure, requested changes, cancellation, or blocked integration retains both; exceptional cleanup remains explicitly authorized and outside the bounded command.
- `Accept <TASK-ID>` runs `cardine review verdict <TASK-ID> APPROVE --owner --body <owner-evidence>` on the clean reviewed HEAD, commits the state file and projections, and continues at C6 under the `Proceed with` authority. A manual merge is never permitted.
- A forge approval cannot be supplied by the same identity that authored the PR. If an external approval is required but unavailable, leave the PR open and report `BLOCKED REVIEW_REQUIRED`.

### Stops and denials

The deny list above stays in force without a supporting command. Classify
outcomes using `capabilities/stop-codes-v1.json` in the framework: its
`human_decision` field determines whether a code needs a person.

- **Guardrail.** Stop on a `BLOCKED <CODE>` whose registry entry has
  `human_decision: true`, on a denied action, or on a scope change. Report
  the code and the resume command. `BLOCKED RULE_CONFLICT` and
  `BLOCKED VALIDATION_RETRY_LIMIT` are guardrails.
- **Recoverable state.** For a code without `human_decision: true`, run the
  recovery command the outcome names in the same turn and continue. Never
  run a recovery twice. If it returns the same code again, report that
  `BLOCKED <CODE>` and its recovery history to the person.
- **Failing work.** A non-zero validation exit or an unmet acceptance
  criterion calls for work on the assigned task. Rerun a failed validation
  once without changes. If the rerun passes, record the test as intermittent
  in the handoff; the attempt does not count. If the rerun fails, count the
  attempt, fix the task's own work, and validate again. After the resolved `validationRetryLimit` consecutive
  counted failures, stop with `BLOCKED VALIDATION_RETRY_LIMIT` and a summary
  of the failures. `VALIDATION_FAILED` has `human_decision: false`; a single
  failed validation does not stop the agent.

Guidance that no command backs is advice: follow it when you
can, and never stop on its strength alone.

Never satisfy a gate by writing false state, such as setting a status only to
pass a check. When a gate contradicts another rule, stop with `BLOCKED RULE_CONFLICT` and
report both rules.

When a Cardine command accepted a state that this text appears to forbid,
follow the command and record the difference under `Rule discrepancies:` in the
handoff. This never covers an action on the deny list and never overrides a
guardrail, including a repeated recovery failure.

### Closure

Close a validated task with `cardine worktree advance`. After validation, commit the completed task record and handoff, then run `cardine task close <TASK-ID>` in the clean task worktree. It verifies the committed record and handoff, leaves the record at its path, and leaves the status `in_progress` until landing writes `done`. Never edit status or verdict fields by hand. On explicit Resume, if `cardine task close` already succeeded, skip `cardine execution start --resume` and run `cardine worktree advance` with the validation evidence. After verifying the
acceptance criteria, running validation, and committing the completion record
and handoff, run `cardine worktree advance <TASK-ID> --project
<primary-checkout> --format json` from the primary checkout, giving each result
as `--validation-command`/`--validation-exit-code` with `--accepted`. Perform
exactly its `action_required`, rerun it with the results (candidate validation
uses `--candidate-command`/`--candidate-exit-code`), and classify any `BLOCKED <CODE>`
under Stops and denials before deciding whether to stop. `docs/WORKTREE_LIFECYCLE.md` keeps the single-step commands
for diagnosis and manual recovery.
A named sandbox skip is not a validation failure only when the test itself
reports it and no acceptance criterion depends solely on that test. Record its
test name, reason, and reporting command as `Validation skips:` in the handoff.
<!-- CARDINE:END -->

## Completion and integration

<!-- CARDINE:BEGIN capability=validation-scoping v1 -->
Classify the changed surface before validation. Documentation-only changes may
skip unrelated build, test, or lint commands when the task does not require
them, and the completion evidence records that skip. Source, build, runtime,
or CI changes run every task-required check plus the applicable project
baseline. Validation scope never weakens an explicit acceptance criterion.
<!-- CARDINE:END -->

Before marking a task done, verify its acceptance criteria and run its stated
validation plus the project's applicable baseline checks. The handoff records
the validated task commit, validated base `main` commit, exact commands and
successful results, whether full combined-tree validation is required, and the
task's declared files, dependencies, and behavioral surfaces. If evidence is
incomplete or a check fails, keep the task in progress and report the blocker.

<!-- CARDINE:BEGIN capability=execution-discipline v1 -->
## Execution discipline

Apply `docs/CONTEXT_READING_POLICY.md`. The review-policy restrictions above remain authoritative; use parallel agents only when their scopes and worktrees are independent.
<!-- CARDINE:END -->
