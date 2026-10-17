# Task Identity Policy

Status: implemented. This note defines the task-identity policy and its
current resolver behavior.

## Decision

Meridian supports two project-selected task-identity modes:

- `opaque`, the backwards-compatible default, treats the task ID as a stable
  label and assigns no meaning to its components;
- `milestone`, an opt-in structured mode, represents exactly the tuple
  `(milestone, workstream, ordinal)`.

The mode is declared once in the project-owned file
`.meridian/task-identity.json`. Absence of that file is exactly equivalent to
`{"version": 1, "mode": "opaque"}`. An upgrade must never create the file
merely to restate the default.

Create the declaration through `meridian setup --apply --task-identity
opaque|milestone`. The setup plan shows the requested write before applying it
and never overwrites an existing declaration. The choice can later be changed
by editing the project-owned file.

The declaration is deliberately not part of `.meridian/manifest.json`.
The manifest records Meridian's managed distribution and migration state;
task identity is project policy. Keeping the policy in its own un-managed
file prevents a framework upgrade from overwriting a project choice and
prevents migration history from becoming evidence of the effective choice.

The first schema is closed and minimal:

```json
{
  "version": 1,
  "mode": "milestone"
}
```

`version` must be the integer `1`, `mode` must be `opaque` or `milestone`, and
unknown properties are errors. There is no user-supplied regular expression,
delimiter, case option, workstream registry, milestone registry, or path in
this file.

The managed `PROJECT_WORKFLOW.md` execution-assets block will eventually carry
one pointer stating that `.meridian/task-identity.json` is the sole identity
declaration and that absence selects `opaque`. That pointer documents the
contract; it is not a second declaration. Shipping that pointer belongs to the
implementation follow-up and requires the normal managed-template migration
and capability-marker update.

## Opaque mode

Opaque mode preserves the current protocol: a task ID is an identifier, not a
record encoded in a string. Existing `TASK-023`, numeric shorthand accepted by
an existing project, and other project-valid IDs remain valid. The resolver
does not extract milestone, workstream, status, dependency, scope, priority,
review policy, or authority from an opaque ID.

The canonical opaque ID is the exact ID recorded by the project's task and
queue authorities. Command input may use an already supported alias, such as
the current case-insensitive `task-023`/`TASK-023` and numeric shorthand, only
when it resolves to one unambiguous canonical record. The resolver must not
invent general case folding for otherwise distinct opaque IDs. A project with
two known IDs that collapse to the same branch or filesystem key is
ambiguous and fails closed.

Artifact safety remains a separate precondition. An ID can be a valid opaque
project identifier while a requested Git-ref or filesystem operation rejects
it because it cannot be represented safely or uniquely. That diagnostic does
not retroactively assign a grammar to all opaque IDs.

## Milestone mode

### Semantic tuple and grammar

A structured ID has this canonical form:

```text
M<milestone>-<WORKSTREAM>-<ordinal>
```

Its complete grammar is:

```text
M(?P<milestone>[1-9][0-9]*)-(?P<workstream>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*)-(?P<ordinal>00[1-9]|0[1-9][0-9]|[1-9][0-9]{2})
```

The whole input must match. Therefore:

- `milestone` is a positive base-10 integer with no leading zero;
- `workstream` is one or more uppercase ASCII segments separated by `_`;
- `ordinal` is a three-digit decimal number from `001` through `999`;
- `M`, the workstream, and every delimiter are canonical only in the shown
  case and form.

For example, `M30-INSPECT-001` represents `(30, INSPECT, 1)`.
`m30-inspect-001` may be accepted as command input and normalized, but task
records, queue rows, filenames, handoffs, reviews, and machine-readable output
must use `M30-INSPECT-001`. Mixed-case records are invalid rather than a second
canonical spelling.

`VERIFY`, `SPIKE`, `PRESENT`, and similar words are ordinary project-selected
workstream labels. Meridian reserves none of them and assigns them no task
class, lifecycle, evidence, review, or checkpoint behavior. A project may use
different labels, or reuse one label across milestones, without extending the
schema. Any behavior associated with such a label must be declared in the
authoritative task or project policy.

### Opt-in without historical renaming

Opting in governs creation of new task IDs; it does not rename history. In a
`milestone` project:

- a new task must use the structured grammar;
- a pre-existing non-matching task that resolves from the project task/queue
  authorities remains a `legacy-opaque` identity;
- an unknown non-matching ID is rejected, so the legacy exception cannot be
  used to create a new opaque task after opt-in;
- an existing matching ID is structured even if it predates the declaration.

This rule needs no copied legacy-ID list and no Git-history cutoff. Existence
in the current project authorities is the compatibility evidence. Ambiguous
or contradictory task/queue records fail closed.

## Mechanical derivations

The identity resolver returns one canonical identity. Location resolution
then applies the project's canonical-location policy. Commands must not parse
the ID again.

For a structured identity, the derivations are:

| Surface | Derivation from canonical `M30-INSPECT-001` |
|---|---|
| Semantic tuple | `(30, INSPECT, 1)` |
| Task filename | `<task-root>/M30-INSPECT-001.md` |
| Queue row | canonical ID in the ID column and a link to the resolved task filename |
| Branch name | `m30-inspect-001` |
| Worktree leaf | `m30-inspect-001` below the repository-qualified worktree root |
| Handoff path | `<handoff-root>/M30-INSPECT-001.md` |
| Review path | `<review-root>/M30-INSPECT-001.md` |
| Budget state key | `M30-INSPECT-001:<attempt>` |

For `opaque` and `legacy-opaque` identities, the same surfaces derive from the
single resolved canonical ID without interpreting its components. Existing
numeric alias normalization and existing safe branch spelling remain
backwards compatible. New code must centralize those compatibility rules in
the resolver instead of preserving the current numeric-only parser beside a
second structured parser.

The project-location resolver remains responsible for `<task-root>`, the
queue, `<handoff-root>`, and `<review-root>`. Defaults are the paths declared
by the managed workflow, while a project-specific canonical-locations
extension in `PROJECT_WORKFLOW.md` may replace them. The identity declaration
contains no paths. Consequently, a consumer with a customized queue or nested
milestone task tree is resolved by composing the identity resolver with the
existing location declaration; neither setting is copied into the other.

These are mechanical derivations only. The task record and queue/workflow
authorities remain the sources of truth for status, dependencies, scope,
priority, review policy, validation, and authority. A changed ID token never
changes those values. In particular, `M30`, `INSPECT`, or `001` cannot prove
that a milestone exists, that another task is a dependency, that a task is
small, first, startable, important, complete, or subject to review.

## Resolver contract

Task 056's host-neutral `meridian worktree` namespace consumes one resolver
with the following logical interface:

```text
resolve_task_identity(project_root, supplied_id, intent) -> ResolvedTaskIdentity
```

`intent` is `existing` or `new`. The result contains:

```text
policy_version
mode                 # opaque | milestone
kind                 # opaque | structured | legacy-opaque
canonical_id
branch_name
artifact_stem
semantic_tuple       # null or {milestone, workstream, ordinal}
task_path
queue_path
handoff_path
review_path
budget_key(attempt)
```

The resolver performs these steps in order:

1. find the canonical project root and read the one optional declaration;
2. resolve canonical project locations from `PROJECT_WORKFLOW.md`;
3. resolve the supplied ID against task and queue authorities, rejecting
   unknown or ambiguous existing identities;
4. apply the selected identity policy and the historical exception described
   above;
5. derive and validate all filesystem and Git-ref components, rejecting
   traversal, separators, reserved Git forms, case-fold collisions, and
   mismatched existing artifacts;
6. return the complete result, without reading status or other task semantics
   into the identity.

Every path, branch, handoff, review, and budget consumer uses this result.
`meridian worktree path`, `prepare`, `check`, integration, cleanup, execution
budget commands, context commands, hooks, and audits must not maintain
host-specific or command-specific task-ID parsers. The deprecated
`meridian codex worktree-path` alias calls the same resolver and may not retain
its current numeric-only implementation.

Resolution is deterministic and read-only. Invalid declaration JSON,
unsupported versions, unsafe derivations, ambiguity, disagreement between
task and queue identities, and structured-mode violations are `BLOCKED`; no
consumer may guess or silently fall back to opaque mode when a declaration is
present.

## First implementation verification

The first implementation includes a CLI check because documentation alone
cannot prove that Task 056, budget handling, customized locations, and
historical compatibility share one resolver. The exact diagnostic command is:

```text
meridian task identity check <TASK-ID> --project <path> --format json
```

It is read-only. On success it writes one JSON object containing all scalar
result fields above plus the resolved paths, writes no files, and exits `0`.
On invalid policy, unknown or ambiguous identity, unsafe/colliding derivation,
or authority disagreement it writes a diagnostic to standard error, emits no
success object, and exits `2`. Usage errors exit `64`.

For an `opaque` project, including every project with no declaration, the
command applies current aliases and existing location rules and succeeds for
every unambiguous project-valid historical ID; it does not require or suggest
conversion to the milestone grammar. In a `milestone` project it reports
`structured` or `legacy-opaque` explicitly. Tests must compare its output with
the values consumed by worktree and budget operations so the diagnostic
cannot drift from runtime resolution.

The first implementation does not add a repository-wide hook or make the
general `meridian audit` command infer identity errors. The explicit check and
resolver-backed lifecycle calls provide the bounded mechanical gate. A later
audit may enumerate authorities only after its ambiguity, cost, and legacy
behavior are separately designed.

## Bounded implementation follow-ups

### Task 063 — Implement the task-identity declaration and resolver

Bounded surface:

- add the closed schema and parser for `.meridian/task-identity.json`;
- expand project-location resolution to return task, queue, handoff, and
  review locations once;
- replace numeric-only task canonicalization with the resolver contract;
- add `meridian task identity check` with the exact behavior above;
- route task lookup, review/handoff lookup, and budget keys through it;
- add deterministic fixtures for absent/explicit opaque policy, structured
  grammar and case, historical non-matching tasks, aliases, custom locations,
  ambiguity, collisions, traversal, and malformed declarations.

This task changes managed workflow guidance, so it requires a versioned
capability marker, a migration that adds only the managed pointer and schema
support, and updated release baselines. The migration must not create a
project declaration, opt a project in, rename tasks, or rewrite queues.
Validation is the repository checker, the complete unit suite, fixture-level
CLI assertions including exit codes and JSON shape, and `git diff --check`.

### Task 056 — Consume the resolver in bounded worktree lifecycle commands

Task 056 remains responsible for the host-neutral worktree state machine. Its
identity surface is limited to calling Task 063's resolver result for path,
branch, handoff, review, and budget identities and proving that the deprecated
Codex alias is equivalent. It must not add another grammar or compatibility
path. Its existing template, migration, capability-marker, host-probe, and
full validation requirements remain unchanged.

No hook or repository-wide audit follow-up is required for the first delivery.
If operational evidence later shows that task creation bypasses both the CLI
check and resolver-backed lifecycle, a separately authorized task may add an
enumerating audit; it must preserve opaque defaults and bound legacy scanning
before changing hooks.

## Consequences and non-goals

- Projects that do nothing remain opaque and unchanged.
- Structured IDs improve navigation and mechanical consistency without
  becoming an ontology for project work.
- A project can adopt structured IDs incrementally while retaining historical
  references.
- Identity policy remains independent of workflow mode and host adapter.
- This design does not create Task 063, modify Task 056, or authorize template,
  migration, schema, CLI, hook, audit, consumer, or capability changes.
