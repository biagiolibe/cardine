# Run commands

Product reference for the commands that drive a task from a queued contract to
a landed, cleaned-up branch. The design authority is [the 1.0 ADR](ADR_CARDINE_1_0.md);
this page states only what a person or an agent types and what comes back. It
is not a template: no installed router or role read set includes it.

## Stable commands

| Command | Effect |
| --- | --- |
| `cardine run <TASK-ID> [--project <path>]` | Resolve the earliest unsatisfied step from the task state, perform it (it changes the repository: worktree, commits, state, merge, push), and print one JSON object. It is not a preview. `cardine review <TASK-ID>` runs the same step. |
| `cardine status [--project <path>] [--all] [--write] [--format text\|json]` | Read-only view of every task; `--write` regenerates the status views. |
| `cardine review verdict <TASK-ID> {APPROVE,CHANGES_REQUESTED,BLOCKED} [--request-id <id>] [--owner] [--body <markdown>] [--project <path>]` | Record a verdict bound to the issued reviewer request. `--owner` is the developer channel: it needs an interactive terminal and a typed confirmation (see below). |
| `cardine cancel <TASK-ID> --reason <text> [--project <path>]` | Record a terminal cancelled state. It deletes no work and satisfies no dependency. |
| `cardine abort <TASK-ID> [--project <path>]` | Restore only the caller-owned integration candidate and lease. The task stays resumable. |

`cardine console [--project <path>] [--interval <seconds>]` is experimental.
It displays project state and can launch agents to run task actions.

Pass `--project` as either checkout of the repository. The command resolves the
primary checkout and the canonical task worktree itself, so every emitted
command works from any directory, including after the worktree is removed.

## The seven steps

`run` chooses the earliest unsatisfied step; a caller never names the phase.
Both presets (`lean` and `governed`) use the same steps.

| Step | Meaning |
| --- | --- |
| `contract` | Validate the frozen contract, dependencies, policy and scope. |
| `worktree` | Prepare and verify the task branch and worktree, then start execution. |
| `implementation` | Return the agent work request; accept delivery only after a complete committed implementation. |
| `validation` | Execute the declared and baseline commands and record their real exit codes. |
| `review` | Return the reviewer work request and an owner verdict command for the validated commit. Choose `APPROVE`, `CHANGES_REQUESTED`, or `BLOCKED` after review; run the command from an interactive terminal. Skipped when the contract requires no review. |
| `candidate` | Stage the direct candidate, validate it, and persist tree-bound evidence. |
| `landing` | Finalize, push `main`, verify the remote result, and clean up. |

## Output

`run` always prints one JSON object on stdout (`version` 1). Fields: `version`,
`task_id`, `project`, `outcome`, `step`, `action`, `next`, `stop`, `work`,
`evidence`, `diagnostics`, `retry_after_seconds`.

| Outcome | Exit status | Meaning |
| --- | --- | --- |
| `progress` | 0 | A step advanced; continue with `next`. |
| `next` | 0 | Another command or agent work is needed. |
| `done` | 0 | The task is landed; there is no `next`. |
| `waiting` | 0 | A check is pending. Rerun `next` after `retry_after_seconds`. |
| `iterate` | 0 | Failing work. Fix it in the same turn using `work` and the diagnostics, then rerun `next`. |
| `blocked` | 2 | A guardrail needs a human decision. `stop` names the code; stderr carries one `BLOCKED <CODE>: ...; resume: ...` line. |
| invalid invocation | 64 | The arguments were wrong; no task was touched. |

For direct landing with required CI, `run` waits up to 900 seconds for checks.
With required review, CI runs on the delivered head before the review step, and `APPROVE` requires the pass.
A clean refresh from main after approval keeps the approval and runs CI again on the merged head before preparing the candidate.
Use `--ci-wait-seconds <seconds>` to change the nonnegative budget; zero
queries once. On timeout, `next.command` retains the budget. Rerunning it
starts a fresh wait on the same published SHA when the delivery is unchanged.
An expired wait of at least 300 seconds with no check run for the delivered commit
stops with `CI_NOT_STARTED`; pushing the same commit to another branch that
triggers the workflow lets the resumed command accept its checks.
A competing integration lease has a separate 180-second default; use
`--lease-wait-seconds <seconds>` to override it or zero to check once.
After release, the same invocation rechecks state and continues. A timeout
returns a retry without altering the competing lease. Explicit budgets are
retained in continuations. Both options are runtime settings and do not
change the task contract.

### Bringing the task branch up to date with main

`run` returns `action: refresh-from-main` as an ordinary `next` when it merged
`main` into the task branch. This happens before CI is requested, in two cases.
With `ciBeforeLanding` and direct landing, it happens when `main` has changed
paths that the task also changed, so the integration decision would be `FULL`.
Cardine runs `git merge --no-ff` of the current `main`, with the message
`Merge main into task-<ID>`, and records the merged `main` commit as the task's
base. It never rebases or rewrites the branch. The diagnostic names the merged
`main` commit and the task paths that interacted with it. Task validation then
runs again on the new head, followed by CI on that head, and the candidate is
`REUSE`. A refresh is progress, not a retry, and consumes no validation retry.
A textual conflict aborts the merge, leaves the branch unchanged, and stops with
`INTEGRATION_CONFLICT`: merge `main` into the task branch in the task
worktree, resolve and commit, then run `cardine run <ID>` again.

Independently of CI, the same refresh runs when the task worktree's policy
differs from the accepted policy, `main` holds the accepted policy, and the task
did not change `.cardine/project.json`. The diagnostic is "the task branch
predates the policy accepted on main; merging main". With uncommitted changes,
nothing is merged and `run` returns `action: commit-before-refresh`: commit the
implementation and run `cardine run <ID>` again. A policy written on the task
branch is never accepted, and keeps the stop. `cardine authorize --check` prints
`task-policy: <ID> predates main; cardine run <ID> will merge main` for each
prepared task worktree in that state.

Run `next.command` unchanged. It is rendered from `next.argv` with POSIX
quoting and names the absolute primary path.

## Stops and recovery

Every outcome code comes from `capabilities/stop-codes-v1.json`.

- Entries with `human_decision: true` stop: report the code and the `resume`
  text, and wait for the developer. This includes `CI_NOT_STARTED`, whose
  recoverable provider condition requires a human to trigger CI.
- Other `recoverable` entries carry a `next` command. Run it once; rerunning the
  identical command converges without duplicating a commit, verdict, counter or
  foreign file.
- `failing-work` entries return `iterate` with the failure.

An interrupted effect is resumed by the same command that was interrupted. A
live foreign operation, a corrupt or foreign state, denied access and an
unmerged or protected branch stay guardrails.

### Scope change recovery

When `SCOPE_CHANGE_REQUIRED` lists ordinary paths outside the frozen surface,
the developer may approve an expansion, including the precise task record
revision in the initial approval. Add only the approved paths to Expected code
surface in the task worktree, update Validation if needed, and run the printed
worktree-specific `cardine task contract update` command. This freezes the
revised contract before validation resumes. If the expansion is declined,
restore the changes to the approved surface. In either case, retry using the
printed primary-checkout `cardine run` command. Unsafe paths and missing or
invalid surfaces require their own correction and receive no expansion proposal.

Before changing a necessary file outside the frozen surface, the implementer
requests one approval identifying the exact paths, why they are needed, and any
validation change. After approval, update the task record in the task worktree
and run `cardine task contract update <TASK-ID> --project <task-worktree>`
before modifying the approved files. Then resume `cardine run <TASK-ID>
--project <primary-checkout>` in the same session.

## Developer channel

The owner verdict (`review verdict --owner`), `cancel` and `abort` are
confirmed by the developer at an interactive terminal. Both stdin and stdout
must be a terminal. The command prints the action, the task and the commit,
and proceeds only when the developer types `<task-id> <commit>` exactly. A
missing terminal, a wrong or empty answer, or end of input is refused as
`COMMAND_REFUSED` before any state is written. A reviewer-session verdict is
never confirmed this way. There is no flag or environment variable that skips
the prompt. Agents run without a terminal, so they are refused. The
confirmation happens before the effect; the existing receipts stay the durable
record, and rerunning the same command after an interruption converges.
An agent that deliberately obtains a terminal is the declared limit of ADR
decision 14, rule 2.

## Internal diagnostic surfaces

`worktree prepare|check|repair-base|advance|integrate stage|finalize|abort|cleanup`,
`execution start|preflight|validate|deliver`, `task transition` and
`task close` remain available for diagnosis and manual recovery. They are not
the supported path: `run` uses their library functions and the same outcome
classification.

## What the receipts do and do not prove

Operation receipts detect inconsistent, stale and incomplete state. They are
written by the same user that runs the agent, so Cardine 1.0 claims no
authenticity against an agent that deliberately bypasses host permissions. The
host boundary is reported as unavailable until its deny rules are installed.

### Registration not committed on main

For a queued task whose record or state is absent from committed `main`,
`run` and its read-only preview return `action: publish-registration` before
preparation. The diagnostic identifies the paths; `next` gives an explicit Git
step and the reason includes the exact retry command. Follow each returned
step, publish `main` when the project workflow requires it, and retry. Cardine
does not commit or push the registration itself. Status reports the paths in
`registration_missing` and marks the task not startable until both are on
`main`; this is separate from dependency blocking.
