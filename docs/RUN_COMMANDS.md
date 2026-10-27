# Run commands

Product reference for the commands that drive a task from a queued contract to
a landed, cleaned-up branch. The design authority is `docs/RUN_ENGINE_PLAN.md`;
this page states only what a person or an agent types and what comes back. It
is not a template: no installed router or role read set includes it.

## Stable commands

| Command | Effect |
| --- | --- |
| `cardine run <TASK-ID> [--project <path>]` | Resolve the next bounded step from the task state, perform it, and print one JSON object. |
| `cardine status [--project <path>] [--all] [--write] [--format text\|json]` | Read-only view of every task; `--write` regenerates the status views. |
| `cardine review verdict <TASK-ID> {APPROVE,CHANGES_REQUESTED,BLOCKED} [--request-id <id>] [--owner] [--body <markdown>] [--project <path>]` | Record a verdict bound to the issued reviewer request. `--owner` is the developer-only channel. |
| `cardine cancel <TASK-ID> --reason <text> [--project <path>]` | Record a terminal cancelled state. It deletes no work and satisfies no dependency. |
| `cardine abort <TASK-ID> [--project <path>]` | Restore only the caller-owned integration candidate and lease. The task stays resumable. |

`cardine console [--project <path>] [--interval <seconds>]` is Experimental. It
renders the same verified facts as `run` and never executes a step.

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
| `review` | Hand the validated commit to an independent reviewer and check the exact verdict. Skipped when the contract requires no review. |
| `candidate` | Stage the direct candidate, validate it, and persist tree-bound evidence. |
| `landing` | Finalize, push `main`, verify the remote result, and clean up. |

## Output

`run` always prints one JSON object on stdout (`version` 1). Fields: `version`,
`task_id`, `project`, `outcome`, `step`, `action`, `next`, `stop`, `work`,
`evidence`, `diagnostics`, `retry_after_seconds`.

| Outcome | Exit status | Meaning |
| --- | --- | --- |
| `progress`, `next`, `done` | 0 | A step advanced, or the task is landed (`done` has no `next`). |
| `waiting` | 0 | A check is pending. Rerun `next` after `retry_after_seconds`. |
| `iterate` | 0 | Failing work. Fix it in the same turn using `work` and the diagnostics, then rerun `next`. |
| `blocked` | 2 | A guardrail needs a human decision. `stop` names the code; stderr carries one `BLOCKED <CODE>: ...; resume: ...` line. |
| invalid invocation | 64 | The arguments were wrong; no task was touched. |

Run `next.command` unchanged. It is rendered from `next.argv` with POSIX
quoting and names the absolute primary path.

## Stops and recovery

Every outcome code comes from `capabilities/stop-codes-v1.json`.

- `guardrail` entries are the only ones with `human_decision: true`. Stop,
  report the code and the `resume` text, and wait for the developer.
- `recoverable` entries carry a `next` command. Run it once; rerunning the
  identical command converges without duplicating a commit, verdict, counter or
  foreign file.
- `failing-work` entries return `iterate` with the failure.

An interrupted effect is resumed by the same command that was interrupted. A
live foreign operation, a corrupt or foreign state, denied access and an
unmerged or protected branch stay guardrails.

## Internal diagnostic surfaces

`worktree prepare|check|repair-base|advance|integrate stage|finalize|abort|cleanup`,
`execution start|preflight|validate|deliver`, `task transition|state import` and
`task close` remain available for diagnosis and manual recovery. They are not
the supported path: `run` uses their library functions and the same outcome
classification.

## What the receipts do and do not prove

Operation receipts detect inconsistent, stale and incomplete state. They are
written by the same user that runs the agent, so Cardine 1.0 claims no
authenticity against an agent that deliberately bypasses host permissions. The
host boundary is reported as unavailable until its deny rules are installed.
