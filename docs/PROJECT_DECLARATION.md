# Project declaration

`.cardine/project.json` is the consumer-owned configuration. It is validated
by [project-v1.schema.json](../schemas/project-v1.schema.json); upgrades preserve
it. Paths are relative to the project and cannot contain `..`.

```json
{
  "version": 1,
  "preset": "lean",
  "project": { "name": "Contoso", "slug": "contoso" },
  "taskIdentity": { "mode": "opaque" },
  "taskDefaults": { "review": "required" },
  "validation": {
    "commands": { "tests": "python3 -m unittest discover -s tests" },
    "baseline": ["tests"],
    "candidate": { "REUSE": ["tests"], "BOUNDED": ["tests"], "FULL": ["tests"] }
  },
  "ci": "none"
}
```

Both `version: 1` and `preset: lean|governed` are required. Both presets install
`templates/single/`, register `workflowMode: single`, and use one state machine.
The preset supplies defaults only. Neither queue shape nor workflow prose
selects policy. Missing or malformed configuration is an error.

| Task option | `lean` | `governed` |
| --- | --- | --- |
| `review` | `not_required` | `required` |
| `authorityRequired` | false | true |
| `expectedCodeSurfaceRequired` | false | true |
| `validationRetryLimit` | 3 | 3 |
| `quickFailureLimit` | 10 | 10 |
| `landingMode` | `direct` | `direct` |
| `ciBeforeLanding` | false | false |

Optional `taskDefaults` override these defaults; explicit task options override
project defaults in either direction. Creation freezes the resolved contract,
commands, preset, and declaration digest in `.cardine/tasks/<ID>.json`.
Configuration edits affect new tasks only. Required review binds approval to
the current implementation commit. Approval leaves a task `in_progress`;
verified landing alone writes `done`. Both presets permit spikes and milestone
identity. Cancellation and inconclusive spikes never satisfy dependencies.

Initialization requires owner-selected literal validation commands. Every
baseline/candidate entry references a declared command ID, and all three
candidate outcomes must be present. An empty list is an explicit choice.
An optional `validation.retry` object maps command IDs to nonempty literal retry
variants. After a complete run fails, variants for failed commands run in
command declaration order. Exit 1 confirms failure and ends the attempt; exit
0 or any other status triggers a complete rerun. A variant never passes an
attempt: only a passing complete command set can do that. Omitted variants
retain the complete rerun behavior.

An optional `validation.preflight` list names unique declared command IDs, such
as fast inventory tests, that run before the complete set. Task and candidate
validation order each attempt the same way: first the retry variant of every
command whose last complete run of the same kind failed; then the preflight
commands; then the complete set. The first attempt of a task, and the first
candidate attempt, run no variant. A preflight command exiting non-zero, or a
variant exiting 1, ends the attempt as a quick failure and runs no complete set.
A variant exiting with another status is not a quick failure: the attempt
continues. Quick failures count in their own counter, limited by
`quickFailureLimit` (a positive integer, overridable per task like
`validationRetryLimit`), shared by task and candidate validation. They never
count toward `validationRetryLimit`. Only a passing complete set resets the
counter; a new commit does not. Reaching the limit stops with
`VALIDATION_RETRY_LIMIT`, naming the quick failure limit and the failed quick
commands. A passing attempt still requires a passing complete set in its last
round. Each quick round is recorded and listed under `Measured validation`.

Candidate validation always adds `git diff --check`. Task commands supplement
the baseline. Retry limits are positive integers. Context reading guards and evidence tiers remain available
without spend counters.

## Review sources

An optional `review` object, `{"sources": ["owner"]}`, names which sources may
record a review verdict. An absent key means `["owner"]`. The list is frozen
into each new task contract as `reviewSources`, like the other options, so a
change affects new tasks only. Use `{"sources": ["owner", "launched"], "reviewer": "codex"}`
to enable a launched reviewer (also supported: `claude`). The reviewer has no write
capability, and `cardine doctor` must report `role-launch-reviewer: ready`. The
reviewer host is read from the declaration on main at each launch; `forge` is
not yet available. When the frozen sources exclude `owner`,
`cardine review verdict --owner` stops with `REVIEW_NOT_APPROVED` and
`cause: source`. `docs/ADR_REVIEW_VERDICT_SOURCES.md` is the reference.

## Change the declaration

1. Commit the change to `.cardine/project.json` on `main` first.
   `cardine authorize` refuses while the declaration in the checkout differs
   from `main`: "project declaration differs from main; commit or restore it first".
2. Then the developer runs `cardine authorize --check --project .` and
   `cardine authorize --apply --project .` from their own terminal. Until
   reauthorization, every task operation stops with "developer reauthorization required".
3. Queued tasks keep their frozen contract. To use the new declaration, run
   `cardine task contract update <ID>`: it rebuilds the contract from the task
   record and the new declaration, preserves the status, transitions, and record
   path, and adds a `contract_history` entry. The `projectDigest` field records
   provenance only; nothing compares it.
4. Prepared tasks need no action. `authorize --check` lists each task whose
   declaration predates `main` as
   `task-policy: <ID> predates main; cardine run <ID> will merge main`.
   The next `cardine run` merges `main` into the task branch once the work is
   committed, as described in [Run commands](RUN_COMMANDS.md). Earlier receipts
   stay valid.
5. Advice: letting open tasks land first avoids merging `main` into a task
   under review and repeating its validation.

`ci` may be `none` or an object with `provider` and `requiredChecks`.
`ciBeforeLanding: true` requires a supported provider and nonempty checks.
When `main` has changed paths that the task also changed, Cardine merges `main` into the
task branch first, so CI validates the tree that will land.
Only direct landing is supported in 1.0; `pull-request` is rejected without
probing a forge.

Optional `locations` declares `queue`, `taskRoots`, `reviewRoot`, `handoffRoot`,
`adrLog`, and `plan`. The archive remains the queue's sibling `QUEUE_ARCHIVE.md`.
`validationScoping` retains bounded selection by paths and literal commands.
Use `cardine locations` and `cardine project show` to inspect resolved values.
Real Meridian installation conversion remains a separate migration; this
configuration does not activate a second state authority.
