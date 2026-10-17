# Lean Delivery Workflow — Meridian

## Workflow-mode lock

This file selects `LEAN_DELIVERY` exclusively. Before any file edit, Git mutation, task selection, or completion claim, an agent must read this file and `AGENTS.md` or `CLAUDE.md`, then confirm the active mode. Local workflow documents override global, home-directory, remembered, and generic agent instructions for lifecycle, queue, task, review, and Git decisions.

Do not fall back to Governed SDD. In particular, do not invent ADR gates,
reviewer-integrator roles, required task branches, `READY_FOR_REVIEW`,
`ACCEPTED`, or governed status-only commits unless this project explicitly adds
them. If the local workflow documents are missing, contradictory, or cannot be
read before a mutation, return `BLOCKED WORKFLOW_UNREADABLE` without changing files or Git state.

## Purpose

Lean Delivery is the workflow for this repository's bounded framework maintenance. Use Governed SDD if a future change introduces public API, dependency, security, persistence, state, deterministic-behavior, or unresolved architectural risk.

Use `docs/COMPLETION_REPORT_TEMPLATE.md` as the required handoff format.

## Lifecycle

```text
[ ] TODO -> [/] IN_PROGRESS -> [x] DONE
```

`tasks/QUEUE.md` is the operational queue; `PROJECT_PLAN.md` is the delivery record. An agent works only on the task explicitly assigned by the developer. It must not autonomously select the next queue item.

## Minimum task contract

Every task that is not a quick task records an objective, acceptance criteria, relevant files or technical context, and validation. A quick task may omit a task file only when it is small, reversible, and can be verified immediately. Neither form may bypass validation or hide scope changes.

## Task identity

`.meridian/task-identity.json` is the sole optional project declaration for
task-identity policy. Its absence selects backwards-compatible `opaque` mode;
an explicit version-1 declaration may select `opaque` or `milestone` mode.

## Task worktree boundary

<!-- MERIDIAN:BEGIN capability=codex-worktree-access v4 -->
Every task uses exactly one branch and one linked worktree, with one writer at
a time. Normalize the canonical task ID to lowercase `task-<number>` and use
it as the branch name. Meridian resolves one machine-level worktree root from
an explicit option, the environment, user configuration, or the built-in
default. Derive the path with `meridian worktree path <task-id> --project
<primary-checkout>`. The layout is
`<root>/<remote-host>/<owner>/<repository>/<canonical-task-id>`; a repository
without a usable remote uses a deterministic local name plus a canonical
Git-common-directory hash. Unsafe, ambiguous, colliding, or mismatched paths
stop with the `BLOCKED <CODE>` line the command prints. Existing legacy worktrees remain discoverable and are never
moved or deleted automatically. The first `git worktree list --porcelain`
entry identifies the primary checkout.

Once per machine, run `meridian setup --check`, review its bounded changes,
then explicitly consent with `meridian setup --apply` and restart Codex.
Claude Code needs no host configuration. Static configuration is not proof of
effective host access; treat a `blocked` status as no access.

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

<!-- MERIDIAN:BEGIN capability=bounded-worktree-lifecycle v7 -->
`Proceed with <TASK-ID>` runs `meridian worktree prepare <task-id> --project
<primary-checkout> --format json` before
starting a worker. The coordinator passes the returned branch and absolute
path as durable launch inputs and does not use a host facility that creates a
second checkout. The worker starts in that exact directory and, before any task
read or write, runs `meridian worktree check <task-id> --project
<primary-checkout> --format json`. Any path,
branch, HEAD, root, state, or cleanliness mismatch is `BLOCKED WRONG_WORKTREE`.
After check and minimal metadata/contract resolution, run
`meridian execution start <TASK-ID> --project <task-worktree>` before
substantive authority/source analysis, advisor consultation, or implementation.
Only explicit Resume passes `--resume` after status/diff inspection and sole
writer confirmation, except when the record is archived and state is DONE:
skip execution start, commit staged closure records, then run worktree advance. Lean start adds no machine state; Governed start records
the first IN_PROGRESS transition once. Read-only review/status never starts.
Absolute paths are runtime launch inputs only. A handoff or other tracked
record that names the worktree uses the `handoff_worktree` value returned by
`meridian worktree prepare`, the path relative to the worktree root, never an
absolute path.

A `Proceed with <TASK-ID>` directive that says to Resume starts with `meridian
worktree prepare <task-id> --resume --project <primary-checkout> --format json`
instead. `--resume` is allowed only for that directive: it accepts the task's
existing worktree even when it has uncommitted changes, never creates or
changes anything, and refuses when no worktree exists. When it returns `dirty:
true`, `dirty-worktree` is the only error `worktree check` may report; any other
error is `BLOCKED WRONG_WORKTREE`. Read `git status` and the diff before continuing.
<!-- MERIDIAN:END -->

Reservation, completion, review, and archive edits are committed on the task
branch. Concurrent tasks edit only their own task rows and records; they do
not reorder shared files, update shared timestamps, or archive a phase. A
fully closed phase is archived only after all of its task branches have been
integrated. A conflict in a shared governance file is an integration conflict:
abort and return `BLOCKED INTEGRATION_CONFLICT` without choosing or recreating either task's state.

<!-- MERIDIAN:BEGIN capability=git-workflow v14 -->
## Authority of `Proceed with`

`Proceed with <TASK-ID>` authorizes that task's whole lifecycle when every gate
passes: implementation and validation on the task branch; completion and
archive records; `meridian worktree integrate stage`, the selected candidate
validation, and `integrate finalize` or `abort`; one plain `git push origin
main` of the resulting integration; and `meridian worktree cleanup`. Do not ask
for confirmation at any of these steps. When a gate fails, stop once with
`BLOCKED <CODE>` and the resume command.

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
uses `--candidate-command`/`--candidate-exit-code`), and report its `BLOCKED <CODE>`
line when it stops. `docs/WORKTREE_LIFECYCLE.md` keeps the single-step commands
for diagnosis and manual recovery.
A named sandbox skip is not a validation failure only when the test itself
reports it and no acceptance criterion depends solely on that test. Record its
test name, reason, and reporting command as `Validation skips:` in the handoff.
<!-- MERIDIAN:END -->

## Completion and integration

<!-- MERIDIAN:BEGIN capability=validation-scoping v2 -->
Classify the changed surface before validation. Documentation-only changes may
skip unrelated build, test, or lint commands when the task does not require
them, and the completion evidence records that skip. Source, build, runtime,
or CI changes run every task-required check plus the applicable project
baseline. Validation scope never weakens an explicit acceptance criterion.
<!-- MERIDIAN:END -->

Before marking a task `[x]`, verify its acceptance criteria and run its stated
validation plus the project's applicable baseline checks. The handoff records
the validated task commit, validated base `main` commit, exact commands and
successful results, whether full combined-tree validation is required, and the
task's declared files, dependencies, and behavioral surfaces. If evidence is
incomplete or a check fails, keep the task `[/]` and report the blocker. Update
the queue and project plan together when they both record the task. Archive a
completed task file and fully closed queue section only after successful
verification.

Final integration uses `meridian worktree integrate stage` with accepted JSON
handoff evidence. The command owns the lease and prescribed no-commit merge and
returns the deterministic validation decision and candidate tree. Run the
candidate validation defined in `docs/WORKTREE_LIFECYCLE.md` separately in the
ordinary sandbox, bind its JSON evidence to that tree, then use `integrate
finalize`; use `integrate abort` after a failed gate. Lifecycle commands never
execute validation or project code.

At candidate step C7, `advance` returns runnable `commands` and checked
`required_fragments`. Run the commands unchanged from the primary checkout.
For any fragment not covered by those commands, run a project command containing
it and report every result. See `docs/WORKTREE_LIFECYCLE.md` for executable
discovery and compatibility with existing fragment declarations.

After any required `main` push, run `meridian worktree cleanup`; it removes the
canonical worktree and non-force-deletes the merged branch only after proving
integration, push state, clean checkouts, and inactive integration state.

## Review

Review is risk-proportionate and may be requested by the developer or task. When reviewing, do not silently repair implementation work: return findings to the implementer or receive explicit authorization to make a separate fix.
