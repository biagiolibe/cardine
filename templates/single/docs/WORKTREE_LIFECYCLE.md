# Bounded Worktree Lifecycle

<!-- CARDINE:BEGIN capability=worktree-command-locations v1 -->
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
<!-- CARDINE:END -->


<!-- CARDINE:BEGIN capability=worktree-lifecycle v2 -->
Use the host-neutral `cardine worktree` namespace for task checkout lifecycle
operations. Commands exit `0` on success, `2` when blocked, and `64` on usage
errors. The root resolves from an explicit option, the environment, user
configuration, or `~/.cardine/worktrees`, in that order.

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
- After check and minimal contract resolution, run `cardine execution start
  <TASK-ID> --project <task-worktree>` before substantive analysis, advisor
  consultation, or implementation. Only explicit Resume adds `--resume` after
  status/diff inspection. Start records `queued -> in_progress` once for
  either preset, using the task's resolved contract. Preparation/launch alone is not execution start.
- Workers whose resolved review option is `required` commit implementation and final handoff,
  check readiness, then run `cardine execution deliver <TASK-ID> --project
  <task-worktree>` last. The command commits only state/projection and reports
  clean HEAD. Stop implementer writes; review requires committed valid delivery.
  An uncommitted ready state or later dirt is pending delivery/changes; status
  remains authoritative. Review/status requests never start work. Spikes
  follow the same review option; no-review tasks proceed to validated landing.
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

Run `cardine worktree repair-base <TASK-ID> --project <primary> --format json`
from the primary checkout or canonical worktree. It requires a clean,
correctly registered worktree, matching lifecycle identity, and no integration
lease or staged merge. It changes only recorded `base_commit` and `task_commit`
to current task HEAD, preserving identity and timing; it never advances Git or
edits a handoff. Existing validation evidence stays unchanged and becomes
stale: renew validation and record new evidence before closure. The result
reports `evidence_renewal_required: true`; repeating recovery at the same commit
is a read-only no-op. Unproven transitions report `BLOCKED WRONG_WORKTREE`.

## Machine task state adoption

Run `cardine task state import [<TASK-ID>...] --project <path> --format json` to preview state files for open legacy tasks and inspect the queue, record, and review evidence. Repeat with `--apply` only after resolving reported disagreements. Existing state files are never overwritten, and terminal legacy tasks are skipped unless `--include-terminal` is given; it previews and, with `--apply`, writes their state from the current texts, stops with `TASK_STATE_INVALID` when the queue, record, or review texts disagree, and never creates an approval. Imported transition history describes the bootstrap at the current HEAD and timestamp, not past implementation or review events; it never manufactures an approval. Both presets use the same state vocabulary and retain the resolved contract snapshot. Conversion of existing installations is explicit, never inferred from table shape. Use `cardine task transition` and `cardine review verdict` for subsequent changes; never edit statuses or verdicts by hand. Machine state files stay tracked at their original path when task records are archived.

## Candidate validation by integration outcome

The consumer-owned `.cardine/project.json` declares validation command IDs,
baseline commands, and candidate commands for `REUSE`, `BOUNDED`, and `FULL`.
Task commands supplement the baseline. Empty lists must be explicit; unknown
IDs and missing candidate outcomes are configuration errors. Every candidate
also runs `git diff --check`. The task's CLI-written contract snapshot freezes
the resolved commands; changing project defaults does not alter an open task.

A task record with `Class: SPIKE` records `ANSWERED` or `INCONCLUSIVE` as
its outcome while status remains `in_progress`. It follows its resolved
review option, including commit-bound approval when required, and becomes
`done` only after validated landing. Its task diff may contain
only its record or exact archive rename, handoff, ADR log, documentation paths
named in its deliverable, changelog fragments, and the canonical
`.cardine/execution-evidence.json` ledger produced by `cardine execution
validate`. This exact ledger path does not permit other `.cardine/` paths
or relax validation evidence checks; another path blocks stage before a lease
or merge.

For `REUSE`, run the declared repository gate and prove with `git diff --name-only
"$VALIDATED_TASK_COMMIT" "$CANDIDATE_TREE"` that only the task record, handoff, review record, the generated queue and plan status
views, and changelog fragment changed. `BOUNDED` adds tests for modules changed by the task and
advanced `main`; `FULL` adds the declared full suite. A stricter gate is allowed.
The literal fragment check executes nothing and accepts `set -o pipefail;` and
an output-bounding pipeline when the declared fragment remains present.
Every candidate evidence record, including one under `none`, must include
`git diff --check`.

`cardine codex worktree-path` is deprecated for one migration window. New
instructions and automation use `cardine worktree path`.

The absolute worktree path is a runtime value and is never written to a tracked
file. `path`, `prepare`, and `check` also return `handoff_worktree`, the path
relative to the worktree root (for example `github.com/<owner>/<repository>/task-<n>`),
which is the value completion handoffs record. Resolving it against the worktree
root yields the same path on every machine. A repository without a usable remote
uses a local name plus a Git-common-directory hash, so its value is stable only
on the machines that share that hash. `check` also accepts a legacy absolute
`Worktree:` value in an existing handoff.
<!-- CARDINE:END -->
