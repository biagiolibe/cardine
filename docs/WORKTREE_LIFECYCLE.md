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
  creates or selects the exact branch/worktree pair and returns durable worker
  launch inputs. Only a Resume directive adds `--resume`, which accepts that
  task's existing dirty worktree, creates and changes nothing, and reports
  `dirty` with `next_action` `inspect-dirty`; `check` then reports
  `dirty-worktree` and no other error.
- `check <TASK-ID> --project <primary> --format json`
  is read-only and must be the worker's first action in the prepared directory.
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

Stage evidence records accepted and successful validation booleans, full
validated task/base object IDs, the full-validation flag, a complete advanced-
main assessment flag, and arrays for task paths, dependencies, behavioral
surfaces, and matching advanced-main identities. Candidate evidence records
the exact candidate tree, `passed: true`, the required `bounded` or `full`
scope, and the successful commands. The CLI rejects stale or incomplete
evidence, requires `git diff --check` in every candidate command list, and
never executes project-provided commands.

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
file, read by task ID, whose status is terminal (`DONE` in Lean Delivery). Table
shape, column order, and status-cell wording are not read. A row without
a state file keeps the conservative table rule: only a `###` section whose task
tables and rows are all recognized and terminal (`[x]`) is archived, and a
section that mixes both kinds of row archives only when both rules agree. An
open, invalid-state, or ambiguous row retains the entire section, and so does a
section that lists no task row of its own. `integrate stage` reports every
section as archived or retained with its reason and its open or legacy rows.
`meridian task state import --include-terminal` creates state for terminal
legacy tasks so that their sections archive by state.

## Machine task state adoption

Run `meridian task state import [<TASK-ID>...] --project <path> --format json` to preview state files for open legacy tasks and inspect the queue, record, and review evidence. Repeat with `--apply` only after resolving reported disagreements. Existing state files are never overwritten, and terminal legacy tasks are skipped unless `--include-terminal` is given; it previews and, with `--apply`, writes their state from the current texts, stops with `TASK_STATE_INVALID` when the queue, record, or review texts disagree, and never creates an approval. Imported transition history describes the bootstrap at the current HEAD and timestamp, not past implementation or review events; it never manufactures an approval. For Lean Delivery, progress remains derived from the worktree and imports as `QUEUED`. Use `meridian task transition` and `meridian review verdict` for subsequent changes; never edit statuses or verdicts by hand. Machine state files stay tracked at their original path when task records are archived.

## Candidate validation by integration outcome

Run candidate validation outside the lifecycle command. `.meridian/candidate-validation.json`
is consumer-owned and versioned. It declares non-empty required command fragments
for every outcome (`declared`), or explicitly chooses `none`; a missing file or
`undeclared` state stops `integrate stage` before any lease or merge with
`BLOCKED UNDECLARED_VALIDATION_COMMANDS`. The stop reports the task's recorded
validation commands and a proposal; review it and write declared fragments or
`none`, or use `meridian setup --apply`. `upgrade --apply` never writes this file.
For every `REUSE`, `BOUNDED`, or `FULL` outcome, run the project's declared repository check and
`git diff --check` against the staged candidate tree. A `REUSE` outcome also
requires a deterministic proof that every non-governance path is unchanged:
run `git diff --name-only "$VALIDATED_TASK_COMMIT" "$CANDIDATE_TREE"` and allow
only the task record or its exact archive rename, that task's handoff, review
record, `.meridian/tasks/<TASK-ID>.json`, the canonical execution-evidence ledger, queue,
plan, queue archive, and changelog fragment. `BOUNDED` adds the tests for
modules changed by the task and advanced `main`; `FULL` adds the full test
suite. A project may always run the full suite for any outcome. Configure
candidate-evidence command requirements per outcome; they must match this gate.

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

`meridian worktree` is the host-neutral authority for routine task worktree
creation, inspection, integration, and cleanup. Hosts may authorize these exact
commands, but host policy never changes their repository, identity, path, or
state checks. Every command exits `0` on success, `2` for a blocked lifecycle
transition, and `64` for command-line usage errors.

## Commands

Routine closure uses `advance`, which the managed workflow text names. The
single-step commands below remain the documented path for diagnosis and manual
recovery.

All paths are absolute after resolution. `--project`, when supplied, must name
the current repository's primary checkout. The worktree root resolves from an
explicit `--worktree-root`, then `MERIDIAN_WORKTREE_ROOT`, then
`$XDG_CONFIG_HOME/meridian/config.json` (or
`~/.config/meridian/config.json`), then `~/.meridian/worktrees`. An explicit
value that conflicts with the environment is blocked and names both sources.
The explicit option remains available for finishing a worktree in an old root.

- `meridian worktree path <TASK-ID> --project <primary> [--format json]`
  prints the canonical repository-qualified path.
- `meridian worktree prepare <TASK-ID> --project <primary> [--base main]
  --format json` creates both the canonical branch and
  worktree, or selects the exact existing pair. Partial or mismatched state is
  retained and blocked. The result contains `branch`, `worktree`,
  `worktree_root`, `base_commit`, `task_commit`, `created`, and `next_action`.
  Its lifecycle state records `started_at` as an ISO-8601 UTC timestamp when it
  first creates the worktree; repeat preparation preserves that value. Older
  state files without it remain valid and report timing as unavailable.
  With `--resume`, `prepare` also accepts an existing canonical worktree of that
  task that has uncommitted changes. Only the console's Resume directive for a
  dirty worktree uses it; ordinary preparation still refuses a dirty worktree.
  A resume never creates, moves, removes, resets, stages, or commits anything,
  and never writes lifecycle state, so it works when only reads of the shared
  Git metadata are allowed. Its non-mutation promise covers lifecycle state,
  Git, and the worktree; the best-effort diagnostic journal is the one explicit
  exception, and a failed journal write never fails a resume. It leaves
  `started_at` and `base_commit` as recorded and refuses when the task has no
  worktree, on every mismatch ordinary preparation blocks (a lifecycle state
  file that names another worktree or branch stops with `BLOCKED WRONG_WORKTREE`
  and names the file with the expected and found values), and while an
  integration lease or staged merge names the task. When the lifecycle state
  file is missing, a resume does not repair it: it derives `base_commit` from
  `git merge-base main <branch>`, adds `base_commit_source: "derived"`, `state:
  "missing"`, and a `state_repair` command, and omits `started_at`. Run that
  command once the worktree is clean; ordinary preparation then repairs the
  state. A resume adds `resumed: true`,
  `dirty`, `changed_paths`, and `untracked_paths` (counts only, never names or
  contents) to the result; a dirty result has `next_action` `inspect-dirty`, and
  `check` then reports `dirty-worktree` and no other error. The agent reads
  `git status` and the diff before continuing.
- `meridian worktree check <TASK-ID> --project <primary> --format json` is
  read-only. It succeeds only inside the exact prepared
  worker directory and reports repository, path, branch, HEAD, base, clean
  state, handoff-state consistency, active integration state, errors, and the
  next action. `wrong-worktree` is distinct from registration, branch, state,
  and cleanliness failures.
### Commit-less fast-forward recovery

After preparation, a clean task branch may have been advanced with
`git merge main --ff-only` before any task commit. Its recorded base then
attributes changes from `main` to the task. A different merge base alone is
never evidence of this condition. Detection requires an intact branch reflog:
creation from the recorded base, followed only by `merge main: Fast-forward`
entries, each advancing by ancestry; the recorded task commit must still equal
the old base, and the current HEAD must be an ancestor of current `main`.
Expired, missing, or other reflog transitions do not prove this narrow case.

`check` remains read-only and reports `BLOCKED STALE_WORKTREE_BASE` with
`meridian worktree repair-base <TASK-ID> --project <primary> --format json`.
Ordinary `prepare` and closure also stop on that proof; `prepare --resume`
continues to preserve state without mutation.

Run `repair-base` from the primary checkout or canonical worktree. It requires
a clean, correctly registered canonical worktree, matching lifecycle identity,
and no integration lease or staged merge. It never advances Git or edits a
handoff. It changes only `base_commit` and `task_commit` to current task HEAD,
preserving all other state, including `started_at`. Existing validation
evidence remains byte-for-byte unchanged and is stale against the new base;
renew validation and record new evidence before closure. The result explicitly
reports `evidence_renewal_required: true`. Repeating recovery at that same
commit is a read-only no-op. Task-owned commits, unrelated branches, and
unproven transitions are rejected with `BLOCKED WRONG_WORKTREE`; recovery of
those cases is outside this contract.

- `meridian worktree evidence <TASK-ID> --project <primary>
  --validation-command <command> --validation-exit-code <code> --accepted
  --format json` records the task and base commits plus changed paths from Git
  in an untracked lifecycle-state JSON file. Repeat each validation option for
  every completed command. It records results supplied by the agent and never
  executes a validation command.
- `meridian worktree advance <TASK-ID> --project <primary> --format json
  [--validation-command <command> --validation-exit-code <code>]... [--accepted]
  [--candidate-command <command> --candidate-exit-code <code>]...`
  runs from the primary checkout. It evaluates `closure-status` and performs
  each mechanical step whose preconditions hold: C5 records evidence from the
  supplied results with the logic of `evidence` (`--accepted` and exit code `0`
  for every command are required, otherwise it stops with `ACCEPTANCE_UNMET` or
  `VALIDATION_FAILED`), C6 runs `integrate stage`, and C10 runs `cleanup`. It
  returns one JSON object with `step`, `action_required`, `commands`,
  `stop_code`, `resume`, and the `performed` steps. `action_required` is
  `run-validation` (C1-C2 and missing results), `run-candidate-validation`
  (C7; `commands` lists runnable entries, including `git diff --check`,
  while `required_fragments` lists all requirements for the staged outcome), `push` (C9; the agent runs `git push origin main`), `human`
  (a registered stop with `human_decision: true`), `resolve` (any other
  registered stop; follow `resume`), or `none` (closure is done). It exits `2`
  on a stop and `0` when the agent only has to act. It never runs a command
  that the agent supplied, never changes into the worktree, and a rerun
  continues from the derived state without repeating a completed step.
  At C7, supplied `--candidate-command` and `--candidate-exit-code` pairs are
  the agent's candidate validation results. When every exit code is `0` and
  every command that the staged outcome requires is present, `advance` writes
  the candidate-bound evidence file (the schema above, bound to the staged
  `candidate_tree`), runs `integrate finalize` (C8), and returns `push` for
  `git push origin main`. A non-zero exit code stops with
  `CANDIDATE_VALIDATION_FAILED`, and a missing required command stops with
  `UNDECLARED_VALIDATION_COMMANDS` and lists runnable commands and required fragments; both run
  `integrate abort` first and never finalize on partial evidence. A candidate
  tree that changed after stage stops with `EVIDENCE_MISMATCH` and leaves the
  staged merge for `integrate abort` and a restage. A rerun after an
  interruption between finalize and push returns `push` again.
- `meridian worktree closure-status <TASK-ID> --project <primary> [--format json]`
  is read-only. It reports the next closure `step`, any `stop_reason`, and a
  `resume` command from the registered worktree, lifecycle files, and Git
  history. Text-mode blocked results print `BLOCKED <CODE>: <detail>; resume: <command>`.
  Every CLI stop is emitted through one helper that accepts only codes listed in
  `capabilities/stop-codes-v1.json`.
  After finalization, it reports `PUSH_PENDING` at C9 when local `main` is
  ahead of the already fetched `origin/main`.
  When the recorded `<id>.evidence.json` is accepted, passed, and names the
  branch's current commit and recorded base, it reports step `C6` with the `integrate stage`
  command instead of `EVIDENCE_INCOMPLETE`.
- `integrate stage` requires the primary checkout to be clean and on `main`, with
  `main` equal to the already fetched `origin/main` or ahead of it with commits
  not yet pushed; those commits are pushed with the integration. It stops with
  `MAIN_BEHIND_ORIGIN`, naming the local and fetched commits, only when local
  `main` is behind the fetched `origin/main`.
- `meridian worktree integrate stage <TASK-ID> --project <primary>
  --evidence <handoff.json> --format json` atomically
  verifies the task and accepted validation evidence before acquiring the
  repository integration lease and performing `git merge --no-ff --no-commit`, then
  reads the project's `PROJECT_WORKFLOW.md` mode lock, then deterministically
  completes its known queue rows. Lean Delivery also completes the matching
  `PROJECT_PLAN.md` row; Governed SDD has no plan requirement and changes a
  `NOT_REQUIRED` review row to `ACCEPTED`. For Governed SDD, the containing
  table is recognized by named `ID` and `Status` columns, in any order; stage
  changes only that status cell. If it has no `Review` column, the task record
  supplies `REQUIRED` or `NOT REQUIRED`. Missing required columns, duplicate or
  missing IDs, mismatched row cells, and unknown statuses remain blocked without
  changing lifecycle records. For adopted projects (a `.meridian/tasks/`
  directory exists), stage reads the task branch's tracked state through the
  shared reader before the lease and merge. Missing state stops with
  `TASK_STATE_MISSING`; invalid or nonterminal state stops with
  `TASK_STATE_INVALID`. Terminal state is `DONE` for Lean Delivery, `ACCEPTED`
  for Governed SDD, or `ANSWERED`/`INCONCLUSIVE` for SPIKE tasks. Required
  reviews need `review.verdict == "APPROVE"`, otherwise `REVIEW_NOT_APPROVED`.
  The reviewed commit must be an ancestor of task HEAD and its diff to HEAD
  may name only the task record or exact archive, handoff, review record,
  state file, and canonical execution-evidence ledger; otherwise `REVIEW_STALE`.
  SPIKE and review-not-required tasks skip that approval check. Stage projects
  the state status into the candidate queue cell. Projects without task state
  use the prose verdict path, labeled `legacy` in the completion result;
  missing approval stops before lease and merge with `REVIEW_NOT_APPROVED`.
  Stage never returns a non-blocking `REVIEW_PENDING` result.
  In legacy projects, a task record with `Class: SPIKE` needs no review record: stage sets its
  row to its terminal `ANSWERED` or `INCONCLUSIVE` status. A spike may integrate
  only its task record or exact archive rename, handoff, ADR log, documentation
  paths named in its deliverable, changelog fragments, and the canonical
  task's `.meridian/tasks/<TASK-ID>.json` state and the
  `.meridian/execution-evidence.json` ledger produced by `meridian execution
  validate`. This exact ledger path does not permit other `.meridian/` paths
  or relax validation evidence checks; any other task diff
  path blocks stage before a lease or merge. Any closed section moves to
  `tasks/QUEUE_ARCHIVE.md` using that
  mode's template table shape, creating it when needed; a project-shaped
  Governed section is not archived by table text. A section is closed when
  every row's task state is terminal, as the queue-section archival rule above
  states; a row without a state file keeps the `###` table rule. An open or
  ambiguous row retains the entire section. Ambiguous input
  produces a warning naming the section and reason, and the staged result
  lists every section's archival decision. Generated archive headers refer to the operational
  queue role, including projects with a custom queue location. It returns `REUSE`, `BOUNDED`, or `FULL`
  with the exact candidate tree. Unknown completion-row shapes are blocked
  without changing the candidate's lifecycle records; ambiguous archival shapes
  are retained with warnings.
- `meridian worktree integrate finalize <TASK-ID> --project <primary>
  --evidence <candidate-validation.json> --format json` creates the fixed merge
  commit only when successful evidence matches the staged candidate and
  required validation scope.
- `meridian worktree integrate abort <TASK-ID> --project <primary> --format
  json` aborts only the requested Meridian-owned merge and releases its lease.
- `meridian worktree cleanup <TASK-ID> --project <primary> --format json`
  removes the clean canonical worktree and non-force
deletes its merged branch only after local integration and, when an origin
  exists, pushed `main` are proven.

Existing worktrees in a previous root are never moved or deleted
automatically. Finish them in place and pass that old root explicitly to
`check`, integration staging, and `cleanup`; new work resolves to the current
machine-level root.

`meridian codex worktree-path` is a deprecated alias for `meridian worktree
path` for one migration window. It prints a deprecation notice to standard
error; new automation must use the host-neutral form.

The absolute worktree path is a runtime value and is never written to a tracked
file. `path`, `prepare`, and `check` also return `handoff_worktree`, the path
relative to the worktree root (for example `github.com/<owner>/<repository>/task-<n>`),
which is the value completion handoffs record. Resolving it against the worktree
root yields the same path on every machine. A repository without a usable remote
uses a local name plus a Git-common-directory hash, so its value is stable only
on the machines that share that hash. `check` also accepts a legacy absolute
`Worktree:` value in an existing handoff.

## Lifecycle journal

`prepare`, `check`, `closure-status`, `advance`, `evidence`, `integrate stage`,
`integrate finalize`, `integrate abort`, and `cleanup` each append one JSON line
to `<git-common-dir>/meridian-journal.jsonl`; the Claude Code `Stop` hook
(`hook stop-audit`) appends one line per unbacked or declared stop code. The file is local and untracked,
and every worktree of the repository shares it, so the lines of concurrent tasks
interleave as whole lines. The read-only commands
(`check`, `closure-status`, and `prepare --resume`) append to it too; the journal
is not lifecycle state, so they still change no lifecycle state. It exists to measure how often the lifecycle stops
and where, not to audit an agent.

| Field | Meaning |
|-------|---------|
| `version` | Always `1`. |
| `ts` | UTC time of the result, `YYYY-MM-DDTHH:MM:SSZ`. |
| `command` | The command name, for example `integrate stage`. |
| `task` | The canonical task ID, when the argument or the result names one. |
| `step` | The closure step or `next_action` the command reported, when it reports one. |
| `result` | `ok` (exit `0`), `blocked` (a stopped lifecycle transition), or `error`; the Stop hook adds `unbacked_block` and `declared_block` (see below). |
| `stop_code` | The registered stop code, only when `result` is `blocked` and the stop carries one. |
| `exit` | The command's exit status. |
| `resume` | `true` only on a `prepare --resume` run. |

Privacy boundary: a line holds only these fields. It never contains an absolute
path, a command line or option value supplied by the agent, a message, or error
text; a stop is recorded by its registered code, never by its message.

### Unbacked stop reports

The Claude Code `Stop` hook (`hooks/stop-audit.sh`, 5 second timeout) runs
`meridian hook stop-audit`; the managed `.codex/hooks.json` registers the same
audit for Codex as `meridian hook stop-audit --host codex` (5 second timeout).
`--host claude|codex` defaults to `claude`. It reads only the final assistant message, from the
`last_assistant_message` field of the hook input (documented for `Stop`), and
falls back to the last assistant entry of `transcript_path`. For each registered
`BLOCKED <CODE>` at the start of a line it looks for a `blocked` journal line
with the same code since the session's first transcript timestamp (24 hours
when unavailable), restricted to the active task when the hook runs in a registered task worktree
(resolved as `meridian worktree active` does; from the primary checkout the
line is not task-scoped and records `task: null`). A `tool` code with no match is appended as `result:
unbacked_block`; a `command-exit` or `judgment` code is appended as
`declared_block`, because no command emits it. The line holds `stop_code`,
`task`, and `host` (`claude` or `codex`) only; a line written before the host
was recorded has no `host` and is read as `claude`. The hook ignores unregistered codes, does nothing outside a
Meridian project or without an existing journal, never blocks the stop, and
always exits `0`. The Codex `Stop` input carries `last_assistant_message`
(nullable) and `transcript_path` (nullable); the hook reads the former and
falls back to the transcript as for Claude Code. Codex user and global
configuration are not touched.

The journal is rotated to `meridian-journal.1.jsonl` when it exceeds 5 MB, and
only that one previous file is kept. A journal write that fails never changes a
command's result or exit status; the command prints one warning to standard
error.

### Flow report

`meridian report flow [--project <primary>] [--since YYYY-MM-DD] [--format
text|json]` reads the current and the rotated journal and changes nothing. It
reports, per task, the lead time from the first successful `prepare` to the
successful `integrate finalize` (falling back to the lifecycle `started_at` only
when the journal holds no `prepare` for the task), the stops by code, the
`integrate abort` runs, and the `prepare --resume` runs. It totals them with the
median lead time, counts `unbacked_block` and `declared_block` lines per host
(`blocks_by_host`), and groups stops by code and by the class in
`capabilities/stop-codes-v1.json`; a `blocked` line without `stop_code` is
`uncoded`. `--since` filters records by time; a task's lead time still uses its
whole history. Malformed lines are counted and skipped; an empty or missing
journal gives an empty report and exit status `0`.

A task may declare `> **Origin**: capability | friction | maintenance | release`
in its record or archive; the report gives each origin's share and counts a task
without it as `unknown`. `friction` means the task fixes a problem that
Meridian's own rules or tools caused.

`.meridian/flow-targets.json` (version 1) declares targets before any data
exists, so the data cannot shape them: `unbacked_blocks` (`window`, `max`),
`lead_time_regression` (`window`, `max_percent`; the median of the last `window`
integrated tasks against the `window` before them), and `friction_share`
(`window`, `max_percent`; over the last `window` integrated tasks that declare
an origin). Windows count tasks, not days, so `--since` does not change them.
Each target prints as `met`, `missed`, or `insufficient data`; a missed target
never changes the exit status, and a missing file shows only the measurements.
Change a declared value only through a separate, recorded decision.

The report also lists the registered `tool`-class stop codes not emitted in the
period, with the period length. They are candidates for removal, not a decision:
some gates guard rare but real conditions.

## Evidence boundary

### External validation evidence

`schemas/validation-evidence-v1.schema.json` defines an attestation for a
validation run that completed outside the agent host. Verify it without running
the recorded command with:

```text
meridian validation check <record.json> --project <primary> [--commit <sha>] --format json
```

The command uses only read-only Git plumbing and returns JSON with a status,
its level, and field-specific reasons. The status is one of:

- `VALIDATION_PASSED`, which exits zero.
- `VALIDATION_RUNNING`, which exits one.
- `VALIDATION_UNAVAILABLE`, which exits one.
- `VALIDATION_FAILED`, which exits two, as does an invalid record.

Every record binds its command, result, test count, commit, and commit tree.
Its state is `running`, `unavailable`, `failed`, or `passed`. The three levels
are `T1_CI` (a successful CI run for that commit), `T2_SHARDED` (a complete,
consistent shard coverage proof), and `T3_ATTESTED` (a dated developer
statement). Each level states what evidence was supplied; none is an
unforgeable proof. A passed record also requires exit code zero, a positive test
count, and level-specific evidence: CI conclusion and head SHA, complete shard
indexes and matching digest/total, or a developer/date/statement respectively.

Stage evidence is a JSON object with these required fields:

```json
{
  "accepted": true,
  "validation_passed": true,
  "validated_task_commit": "<40-hex-object-id>",
  "validated_base_commit": "<40-hex-object-id>",
  "full_validation_required": false,
  "interaction_assessment_complete": true,
  "task_paths": ["path/owned-by-task"],
  "task_dependencies": [],
  "task_behavioral_surfaces": [],
  "main_advanced_dependencies": [],
  "main_advanced_behavioral_surfaces": []
}
```

`worktree evidence` also writes `validation_commands` and
`validation_exit_codes`. These fields are optional for hand-written legacy
evidence. During staging, Git is authoritative for task paths and paths that
`main` changed since the validated base. Declared task paths can expand that
surface; typed `main_advanced_*` fields can require `FULL` validation but
cannot reduce the scope selected from Git.

Candidate validation runs outside the lifecycle command in the ordinary
sandbox. Its JSON object contains the returned `candidate_tree`, `passed:
true`, `scope` (`bounded` or `full`), and a non-empty `commands` array. The
required gate for each `REUSE`, `BOUNDED`, or `FULL` decision is defined below.
Lifecycle commands never execute shell, hook, validation, smoke, or
project-provided commands.

### Candidate validation by integration outcome

The consumer-owned `.meridian/candidate-validation.json` declares command
fragments per `REUSE`, `BOUNDED`, and `FULL` outcome. It has `version: 1` and
one state: `declared` with a non-empty fragment array for every outcome, `none`
to accept any non-empty successful command list, or `undeclared`. A missing
file is also `undeclared`. The comparison is literal and executes nothing; it
accepts a `set -o pipefail;` prefix and output-bounding pipelines because the
declared fragment remains in the command entry.

Complete commands are valid declaration entries; legacy fragments remain valid.
At C7, `advance` returns `commands` that can be run unchanged from the primary
checkout and `required_fragments` containing every checked entry, including
`git diff --check`. For each fragment not covered by `commands`, run a project
command containing that exact fragment and report it with its exit code.
Runnable discovery parses POSIX shell tokens with `shlex.split`: the first
token must resolve to an executable file on `PATH` or name an existing
executable file. Relative file paths and relative `PATH` entries resolve from
the primary checkout. Empty entries and invalid quoting are not runnable.
Discovery uses local file metadata only, with no network access or execution;
it does not validate arguments or shell syntax. Setup proposes complete commands
(`python3 scripts/check_repository.py` and, when tests exist,
`python3 -m unittest discover -s tests`), shows them under `--check`, and only
writes a proposed declaration under `--apply`; existing declared entries are preserved.

An undeclared project stops at `integrate stage`, before a lease, merge, or
staged state exists, with `BLOCKED UNDECLARED_VALIDATION_COMMANDS`. The stop
shows the task validation commands and a detected-stack proposal. Explicitly
write declared fragments, choose `none`, or use `meridian setup --apply` after
reviewing its proposal, then rerun stage. `upgrade --apply` never writes this
consumer-owned file. This repository's own fragments live only in its
`.meridian/candidate-validation.json`.

- `REUSE` runs the project's declared repository gate and proves that the staged candidate differs
  from the validated task commit only in governance paths. Use the deterministic
  command `git diff --name-only "$VALIDATED_TASK_COMMIT" "$CANDIDATE_TREE"` and
  verify that every emitted path is the task record (active or its exact archive
  rename), that task's handoff, review record, `.meridian/tasks/<TASK-ID>.json`,
  `.meridian/execution-evidence.json`, `tasks/QUEUE.md`, `PROJECT_PLAN.md`,
  `tasks/QUEUE_ARCHIVE.md`, or that task's changelog fragment. Any other path
  requires a `BOUNDED` or `FULL` outcome; it is not a valid `REUSE` proof.
- `BOUNDED` runs the `REUSE` gate and the tests for modules changed by both the
  task and advanced `main`. Select those tests from the staged candidate's
  changed-path evidence; the independent-change decision never permits omitting
  either side's affected modules.
- `FULL` runs the `REUSE` gate and the project's declared full suite. Its candidate evidence
  therefore records both the repository check and full-suite command.

A stricter gate is always permitted: an agent may run the full suite for any
outcome, and neither the lifecycle command nor this policy rejects it.
Missing, failed, stale, or mismatched evidence is blocked without creating a
merge commit. Every candidate evidence record, including one under a `none`
declaration, must include `git diff --check`.

Lifecycle state is stored under the repository's absolute Git common
directory. Interruptions retain enough ownership and candidate identity for
`check`, `integrate abort`, or an idempotent retry. Stale leases, force deletes,
abandoned branches, and arbitrary paths have no routine command and require an
explicitly authorized exceptional recovery outside the allowlisted surface.

When integration reports `PRIMARY_DIRTY`, it lists the staged or modified paths
(bounded to ten). A sole `.meridian/budget.json` entry is identified as the
legacy budget file; commit its deletion before rerunning stage.

After validation, `integrate stage` permits lifecycle changes only to the task
record, its queue row, handoff, review record, its state file,
the canonical execution-evidence ledger, `PROJECT_PLAN.md`, and
`tasks/QUEUE_ARCHIVE.md`. A task record may be archived only as an exact
100%-similarity Git rename from its active path to `tasks/done/` with the same
file name. A task already archived at validation needs no rename; an active
task may otherwise change only its active record path. Deletions, separate
additions, changed-content renames, other destinations, and records belonging
to another task are blocked before lifecycle state is written.
