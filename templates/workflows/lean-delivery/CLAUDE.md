# [Project Name]

Read `PROJECT_WORKFLOW.md` before acting. It locks this repository to
`LEAN_DELIVERY`; use its local lifecycle rather than global, home-directory,
remembered, or generic Meridian/Claude/Codex instructions. If local workflow
documents cannot be read or conflict, return `BLOCKED WORKFLOW_UNREADABLE` before mutating files or
Git state.

Read `LANGUAGE_POLICY.md` before responding or writing. Use its persisted
conversation language and write every repository artifact in English.

## Commands

```bash
# Fill in the project's run, test, lint, and format commands.
```

## Delivery rules

Work only on the task explicitly assigned by the developer. Before changing
code, read the task or quick-task description, its relevant context, and `git
status --short`; state a short plan. Do not choose a queue item autonomously.
If unrelated uncommitted changes prevent safe work, do not modify, stage,
discard, or commit them; report the conflict and stop.

- Keep the task scope bounded. Record a newly discovered requirement as a new
  task rather than silently widening the current one.
- Run the task validation and applicable project baseline checks. Do not mark a
  task `[x]`, archive it, or claim completion if required evidence is missing or
  validation fails.
- After successful verification, update the matching queue and project-plan
  records, then archive the completed task file or a fully closed queue section
  when applicable.
- For `Proceed with <TASK-ID>`, create or select the deterministic task branch
  and linked worktree required by `PROJECT_WORKFLOW.md` before changing task
  state or files. Run implementation, validation, and task-local lifecycle
  edits only there; the primary checkout is reserved for coordination and
  final integration.
- Use one writer per task worktree. A review uses the same task worktree only
  after the implementer has stopped; it never switches the primary checkout to
  the task branch.
- A requested review is read-only unless the developer separately authorizes a
  fix. Report actionable findings; do not silently correct implementation code
  during review.

<!-- MERIDIAN:BEGIN capability=git-workflow v15 -->
## Authority of `Proceed with`

`Proceed with <TASK-ID>` authorizes that task's whole lifecycle when every gate
passes: implementation and validation on the task branch; completion and
archive records; `meridian worktree integrate stage`, the selected candidate
validation, and `integrate finalize` or `abort`; one plain `git push origin
main` of the resulting integration; and `meridian worktree cleanup`. Do not ask
for confirmation at any of these steps. When a gate fails, classify the outcome
under Stops and denials and follow that class in the same turn.

It also authorizes one plain `git push origin <task-branch>`, where
`<task-branch>` is the `branch` value returned by `meridian worktree prepare`,
only when needed to obtain `T1_CI` validation for that task commit: at most once
per review attempt, never by a reviewer, and not at all when the project has no
CI. It never authorizes creating,
moving, or pushing a tag; publishing a release; a force push or a push that
deletes or mirrors references; rewriting history (amend of pushed commits,
rebase, reset, cherry-pick); deleting an unmerged branch or force-removing a
worktree; bypassing a required independent review; resolving a textual
conflict; or work on another task.

## Stops and denials

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
  attempt, fix the task's own work, and validate again. After 3 consecutive
  counted failures, stop with `BLOCKED VALIDATION_RETRY_LIMIT` and a summary
  of the failures. `VALIDATION_FAILED` has `human_decision: false`; a single
  failed validation does not stop the agent.

Guidance that no command backs is advice: follow it when you
can, and never stop on its strength alone.

Never satisfy a gate by writing false state, such as setting a status only to
pass a check. When a gate contradicts another rule, stop with `BLOCKED RULE_CONFLICT` and
report both rules.

When a Meridian command accepted a state that this text appears to forbid,
follow the command and record the difference under `Rule discrepancies:` in the
handoff. This never covers an action on the deny list and never overrides a
guardrail, including a repeated recovery failure.

## Governance-file ownership and closure

Task branches do not edit `tasks/QUEUE.md`, `tasks/QUEUE_ARCHIVE.md`, or
`PROJECT_PLAN.md`. They edit only their own task record, its exact archive under
`tasks/done/`, its handoff, and its own `.meridian/tasks/<TASK-ID>.json` state file. `integrate stage` applies queue and plan status
and phase archival once on the merged candidate tree. The queue retains `[ ]`
until then; in-progress state is derived from the canonical branch, registered
worktree, and unarchived record.

Close a validated task with `meridian worktree advance`. After validation, commit the completed task record and handoff, then run `meridian task close <TASK-ID>` in the clean task worktree. It writes DONE state and stages the exact record archive and state file without committing; commit these closure records together. Never edit status or verdict fields by hand. On explicit Resume, if the record is already archived and its state is DONE, skip `meridian execution start --resume`: commit any staged closure records, then run `meridian worktree advance` with the validation evidence. After verifying the
acceptance criteria, running validation, and committing the completion record
and handoff, run `meridian worktree advance <TASK-ID> --project
<primary-checkout> --format json` from the primary checkout, giving each result
as `--validation-command`/`--validation-exit-code` with `--accepted`. Perform
exactly its `action_required`, rerun it with the results (candidate validation
uses `--candidate-command`/`--candidate-exit-code`), and classify any `BLOCKED <CODE>`
under Stops and denials before deciding whether to stop. `docs/WORKTREE_LIFECYCLE.md` keeps the single-step commands
for diagnosis and manual recovery.
A named sandbox skip is not a validation failure only when the test itself
reports it and no acceptance criterion depends solely on that test. Record its
test name, reason, and reporting command as `Validation skips:` in the handoff.
<!-- MERIDIAN:END -->

## Command triggers

- `Proceed with <TASK-ID>` — implement only that task using Lean Delivery.
- `Review <TASK-ID>` — perform a read-only, risk-proportionate review of that
  task and report findings or approval.
