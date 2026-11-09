# Task identity policy

Cardine supports `opaque` and `milestone` task identities. The project selects
`taskIdentity.mode` in `.cardine/project.json`; its default is `opaque`. The
choice is set during initialization or adoption. See the
[project declaration](PROJECT_DECLARATION.md).

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
workstream labels. Cardine reserves none of them and assigns them no task
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

## Resolution

The resolver derives task, branch, worktree, handoff, and review identities
from the canonical ID. Project locations come from `.cardine/project.json`;
use `cardine locations` to inspect them. Task state, rather than an ID's
components, determines status and dependencies.

Inspect an existing identity with the read-only diagnostic:

```text
cardine task identity check <TASK-ID> --project <path> --format json
```
