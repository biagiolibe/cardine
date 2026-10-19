# Bounded Worktree Lifecycle

<!-- MERIDIAN:BEGIN capability=worktree-command-locations v1 -->
## Command locations

After prepare/check, switch `--project` from the primary checkout to the task
worktree for execution and closure. An explicit absolute path makes those
commands independent of the caller’s current directory; repository-relative
handoff report arguments resolve against that task worktree. Omitting
`--project` still defaults to the current directory. Agents must still launch
workers and perform their first worktree check in the prepared worktree.
Every emitted stop line still stops work; use its exact resume command
only after an explicit Resume directive.

| Lifecycle command | Where it may run | What `--project` names |
|---|---|---|
| `worktree path`, `prepare`, `advance`, `evidence`, `closure-status`, `integrate stage/finalize/abort`, `cleanup` | Primary checkout (coordination); registered task checkout where the command permits it | Primary checkout |
| `worktree repair-base` | Primary checkout or canonical task worktree | Primary checkout |
| `worktree states` | Any directory | Primary checkout |
| `worktree active` | Exact registered task worktree; no `--project` option | Not applicable |
| `worktree check` | Exact prepared task worktree for worker verification | Primary checkout |
| `execution start`, `deliver`, state-backed `ready-check` | Any directory; canonical registered task worktree verified through `--project` | Task worktree |
| `execution validate`, `preflight`, `contract`, `reconcile`, `handoff-check`, legacy `ready-check`, `evidence`, `investigate` | Any directory; existing contract/evidence checks apply. Contract preparation may also precede a worktree | Task worktree (or project being prepared for contract operations) |
| `task close` | Any directory; canonical registered task worktree, clean and without active integration | Task worktree |
| `task transition`, `review verdict` | Task worktree context; existing branch/state checks apply | Task worktree |
<!-- MERIDIAN:END -->


<!-- MERIDIAN:BEGIN capability=worktree-lifecycle v6 -->
Use the host-neutral `meridian worktree` namespace for task checkout lifecycle
operations. Commands exit `0` on success, `2` when blocked, and `64` on usage
errors. The root resolves from an explicit option, the environment, user
configuration, or `~/.meridian/worktrees`, in that order.

- `path <TASK-ID> --project <primary> [--format json]`
  derives the canonical path.
- `prepare <TASK-ID> --project <primary> --format json`
  creates or selects the exact branch/worktree pair before any worker starts.
  Only a Resume directive adds `--resume`, which accepts that
  task's existing dirty worktree, creates and changes nothing, and reports
  `dirty` with `next_action` `inspect-dirty`; `check` then reports
  `dirty-worktree` and no other error.
- `check <TASK-ID> --project <primary> --format json`
  is read-only and must be the implementer, reviewer, or remediation worker's
  first action in that same prepared directory.
- After check and minimal contract resolution, run `meridian execution start
  <TASK-ID> --project <task-worktree>` before substantive analysis, advisor
  consultation, or implementation. Only explicit Resume adds `--resume` after
  status/diff inspection. Governed start records IN_PROGRESS once; Lean start
  verifies the worktree without adding a machine state or requiring a Governed
  contract. Preparation/launch alone is not execution start.
- Review-required Governed workers commit implementation and final handoff,
  check readiness, then run `meridian execution deliver <TASK-ID> --project
  <task-worktree>` last. The command commits only state/projection and reports
  clean HEAD. Stop implementer writes; review requires committed valid delivery.
  An uncommitted ready state or later dirt is pending delivery/changes; status
  remains authoritative. Review/status requests never start work. SPIKE and
  review-not-required closure keep their existing terminal transitions.
- `integrate stage <TASK-ID> --project <primary>
  --evidence <handoff.json> --format json` owns the lease and no-commit merge
  and returns `REUSE`, `BOUNDED`, or `FULL` plus the candidate tree.
- Run the selected validation outside the lifecycle command, then use
  `integrate finalize <TASK-ID> --project <primary> --evidence
  <candidate-validation.json> --format json`, or `integrate abort` on failure.
- `cleanup <TASK-ID> --project <primary> --format json`
  removes only a clean, integrated, pushed worktree and non-force-deletes its
  merged branch.

Legacy worktrees are never moved. Finish and clean one in its old root by
passing `--worktree-root <old-root>` explicitly.

Stage evidence records acceptance, successful validation, full validated task
and base object IDs, the full-validation flag, a complete advanced-main
assessment flag, and arrays for task paths, dependencies, behavioral surfaces,
and matching advanced-main identities. Candidate evidence records the exact
candidate tree, `passed: true`, the required `bounded` or `full` scope, and the
successful commands. The CLI rejects stale or incomplete evidence and never
executes project-provided commands.

## Commit-less fast-forward recovery

A clean task branch advanced only by `git merge main --ff-only` before any
task commit may retain a stale recorded base. Detection requires an intact
branch reflog proving creation from that base followed only by fast-forward
merges from `main`, no task commits, and a HEAD that is an ancestor of current
`main`; a different merge base alone is not proof. `check`, ordinary `prepare`,
and closure report `BLOCKED STALE_WORKTREE_BASE`; `prepare --resume` preserves
state without mutation.

Run `meridian worktree repair-base <TASK-ID> --project <primary> --format json`
from the primary checkout or canonical worktree. It requires a clean,
correctly registered worktree, matching lifecycle identity, and no integration
lease or staged merge. It changes only recorded `base_commit` and `task_commit`
to current task HEAD, preserving identity and timing; it never advances Git or
edits a handoff. Existing validation evidence stays unchanged and becomes
stale: renew validation and record new evidence before closure. The result
reports `evidence_renewal_required: true`; repeating recovery at the same commit
is a read-only no-op. Unproven transitions report `BLOCKED WRONG_WORKTREE`.

## Queue-section archival

A section ends at the next heading of the same or a higher level and includes
its nested headings; its heading level does not restrict archival. A section
that itself lists task rows is archived when every task row in it has a state
file, read by task ID, whose status is terminal (`ACCEPTED`, `ANSWERED`, or `INCONCLUSIVE` in Governed SDD). Table
shape, column order, and status-cell wording are not read. `INCONCLUSIVE` closes its section but still does not satisfy a dependency. A row without
a state file keeps the conservative table rule: only a `###` section whose task
tables and rows are all recognized and terminal (`ACCEPTED` or `ANSWERED`) is archived, and a
section that mixes both kinds of row archives only when both rules agree. An
open, invalid-state, or ambiguous row retains the entire section, and so does a
section that lists no task row of its own. `integrate stage` reports every
section as archived or retained with its reason and its open or legacy rows.
`meridian task state import --include-terminal` creates state for terminal
legacy tasks so that their sections archive by state.

## Machine task state adoption

Run `meridian task state import [<TASK-ID>...] --project <path> --format json` to preview state files for open legacy tasks and inspect the queue, record, and review evidence. Repeat with `--apply` only after resolving reported disagreements. Existing state files are never overwritten, and terminal legacy tasks are skipped unless `--include-terminal` is given; it previews and, with `--apply`, writes their state from the current texts, stops with `TASK_STATE_INVALID` when the queue, record, or review texts disagree, and never creates an approval. Imported transition history describes the bootstrap at the current HEAD and timestamp, not past implementation or review events; it never manufactures an approval. For Lean Delivery, progress remains derived from the worktree and imports as `QUEUED`. Use `meridian task transition` and `meridian review verdict` for subsequent changes; never edit statuses or verdicts by hand. Machine state files stay tracked at their original path when task records are archived.

## Candidate validation by integration outcome

`.meridian/candidate-validation.json` is a consumer-owned, versioned declaration.
It supplies non-empty command fragments for each `REUSE`, `BOUNDED`, and `FULL`
outcome (`declared`), or explicitly selects `none`. A missing file or
`undeclared` state stops `integrate stage` before any lease, merge, or staged
state with `BLOCKED UNDECLARED_VALIDATION_COMMANDS`; its evidence names the
task's validation commands and a proposal. Review the proposal and explicitly
write declared fragments or `none`, or run `meridian setup --apply` after its
proposal is reviewed. `upgrade --apply` never writes this project file.

A task record with `Class: SPIKE` completes at stage to its terminal `ANSWERED`
or `INCONCLUSIVE` status without a review record. Its task diff may contain
only its record or exact archive rename, handoff, ADR log, documentation paths
named in its deliverable, changelog fragments, and the canonical
`.meridian/execution-evidence.json` ledger produced by `meridian execution
validate`. This exact ledger path does not permit other `.meridian/` paths
or relax validation evidence checks; another path blocks stage before a lease
or merge.

For `REUSE`, run the declared repository gate and prove with `git diff --name-only
"$VALIDATED_TASK_COMMIT" "$CANDIDATE_TREE"` that only the task record or exact
archive rename, handoff, review record, queue, plan, queue archive, and changelog
fragment changed. `BOUNDED` adds tests for modules changed by the task and
advanced `main`; `FULL` adds the declared full suite. A stricter gate is allowed.
The literal fragment check executes nothing and accepts `set -o pipefail;` and
an output-bounding pipeline when the declared fragment remains present.
Every candidate evidence record, including one under `none`, must include
`git diff --check`.

`meridian codex worktree-path` is deprecated for one migration window. New
instructions and automation use `meridian worktree path`.

The absolute worktree path is a runtime value and is never written to a tracked
file. `path`, `prepare`, and `check` also return `handoff_worktree`, the path
relative to the worktree root (for example `github.com/<owner>/<repository>/task-<n>`),
which is the value completion handoffs record. Resolving it against the worktree
root yields the same path on every machine. A repository without a usable remote
uses a local name plus a Git-common-directory hash, so its value is stable only
on the machines that share that hash. `check` also accepts a legacy absolute
`Worktree:` value in an existing handoff.
<!-- MERIDIAN:END -->
