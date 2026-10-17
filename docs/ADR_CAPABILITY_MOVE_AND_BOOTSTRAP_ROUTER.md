# ADR: Capability Moves and Compact Bootstrap Routers

Status: Accepted

## Context

The governed-SDD host entry points currently carry implementation, review,
remediation, and lifecycle procedures before a session can know which one it
needs. The routing spike in `AGENT_INSTRUCTION_ROUTING_SPIKE.md` established
that this unconditional read is large and that moving a protected marker is
unsafe unless an upgrade can prove both its old and new homes.

This ADR defines the contract for the two follow-on releases. It is deliberately
an architecture and migration contract: it does not move a marker, modify a
template, or change upgrader behavior.

## Decision

### Bootstrap contract and budget

`AGENTS.md` and a non-pointer `CLAUDE.md` are compact bootstrap routers. Their
complete UTF-8 files, including Markdown, comments, and marker delimiters, may
not exceed **4,096 bytes** each. `wc -c` is the normative measurement, and the
repository guard must enforce it for the governed-SDD templates. An explicit
`MERIDIAN:CLAUDE-AGENTS-POINTER v1` pointer is a bootstrap router too and has a
stricter **1,024-byte** limit.

A bootstrap router contains only these always-loaded invariants:

1. Read the local workflow and language-policy files before a mutation; use
   their mode, lifecycle, language, and repository-language requirements. A
   missing or contradictory local contract is `BLOCKED`.
2. Work only on a developer-assigned task or an explicitly authorized
   read-only request. Do not select work autonomously.
3. Before a write or Git mutation, inspect the assigned task and working-tree
   state; preserve unrelated changes and never discard, stage, or overwrite
   them without explicit direction.
4. Select exactly one routed procedure for a recognized request. A mixed or
   unrecognized request is `BLOCKED` or clarified; it must not fall through to
   a universal procedure.
5. Keep the command-trigger authorization map and the host-specific pointer
   rule needed to reach the same router. No role procedure, validation
   sequence, review record, lifecycle algorithm, or project architecture text
   belongs in the bootstrap.

The `command-triggers` marker remains in the bootstrap because it is the
authorization and routing map, not a role procedure. The compact wording may
be a new marker version in the implementation release; this ADR does not
prescribe that version number.

### Request routing and managed homes

The router loads the following single role procedure after applying the
bootstrap contract. The procedure then names any additional task authority it
requires; a router must not preload that authority.

| Request | Role procedure | Managed path | Resulting role |
|---|---|---|---|
| `Proceed with <TASK-ID>` | Implementation | `docs/workflows/IMPLEMENTATION.md` | Implementer |
| `Review <TASK-ID>` | Review | `docs/workflows/REVIEW.md` | Independent reviewer-integrator |
| `Address review <TASK-ID>` | Remediation | `docs/workflows/REMEDIATION.md` | Implementer resolving the durable record |
| `Run lifecycle <TASK-ID>` | Lifecycle | `docs/workflows/LIFECYCLE.md` | Coordinator |
| `Accept <TASK-ID>` | Lifecycle | `docs/workflows/LIFECYCLE.md` | Owner-acceptance handoff |
| Status, project question, or tech-design alignment | Read-only profile | `docs/CONTEXT_BUDGET_POLICY.md` | Read-only reporter or analyst |
| Explicit audit | Audit prompt | `docs/AUDIT_PROMPT_READ_ONLY.md` | Read-only auditor |

`AGENTS.md` is the compact router for hosts that auto-load it. A non-pointer
`CLAUDE.md` has equivalent bootstrap text and the same map. An explicit Claude
pointer delegates to the compact `AGENTS.md`; it does not restore a full
`AGENTS.md` read by pointing at a role procedure. The pointer fixture remains
valid only when the delegated router and its routed documents are present.

The additive release assigns the existing procedural text to these canonical
homes, preserving every marker's content and version exactly:

| Canonical home | Entry-point material copied there in the additive release |
|---|---|
| `docs/workflows/IMPLEMENTATION.md` | The full Implementation workflow, including `manual-verification-precondition`, `spike-routing`, `validation-scoping`, and `execution-command-gate` blocks. |
| `docs/workflows/REVIEW.md` | `review-mode-boundary`, `implementer-reviewer-handoff`, and `reviewer-integrator-identity`, plus their surrounding review procedure. |
| `docs/workflows/REMEDIATION.md` | `review-remediation-record` and its surrounding remediation procedure. |
| `docs/workflows/LIFECYCLE.md` | `lifecycle-orchestration`, `owner-acceptance-workflow`, and their surrounding coordinator/owner-acceptance procedure. |

The new documents are managed governed-SDD paths. Their complete documents,
not merely their markers, participate in the normal three-way upgrade. A
marker block has exactly one canonical role home after retirement; a marker
that remains deliberately bootstrap-only, such as `command-triggers`, has no
move declaration.

### Machine-readable capability-move declaration

A migration that relocates a protected marker adds a top-level
`capabilityMoves` array. Each entry has this shape (the hashes below are
placeholders and must be the actual SHA-256 of the complete marked block):

```json
{
  "stage": "additive",
  "source": {
    "path": "AGENTS.md",
    "capability": "review-mode-boundary",
    "capabilityVersion": 1,
    "markerSha256": "<sha256-of-BEGIN-through-END-UTF-8-bytes>"
  },
  "target": {
    "path": "docs/workflows/REVIEW.md",
    "capability": "review-mode-boundary",
    "capabilityVersion": 1,
    "markerSha256": "<sha256-of-BEGIN-through-END-UTF-8-bytes>"
  }
}
```

`stage` is either `additive` or `retirement`. `source.path` and `target.path`
are repository-relative managed paths. Both objects are required and each
names one marker occurrence: its capability, version, and SHA-256 hash over
the complete `<!-- MERIDIAN:BEGIN ... -->` through `<!-- MERIDIAN:END -->`
block as UTF-8 bytes. A record's `managedPaths` must include both paths. A
schema or repository check rejects unknown keys, an unsupported stage, a
non-managed path, equal source and target locations, a duplicate declaration
for the same source marker, or a hash that does not match the release template.

The source and target hashes are intentionally separate. A role document may
need a different surrounding heading or line placement even when the protected
rule is identical; exact evidence is about the complete marked block in its
declared home, not an inference from a capability name.

For one capability copied from both host entry points, declare one move per
source path. A Claude pointer has no source marker to move; its fixture proves
that the delegated AGENTS router supplies the route instead. A migration may
contain multiple entries when a procedure contains multiple protected blocks.

### Upgrade and audit safety rules

Before applying a declared move, the upgrader counts the referenced marker in
the installed baseline, local project, and target release template. The source
and target each must occur exactly once in the relevant artifact. It never
chooses among multiple occurrences.

For an **additive** declaration:

1. The local source block must byte-match the installed baseline and the
   declared source hash. A changed source is a blocking conflict.
2. The target release block must match the declared target hash. If a local
   target already exists, it must either be absent at the target marker
   location or contain the exact declared target block; any divergent target
   marker is a blocking conflict.
3. The resulting project must contain exact source and target blocks. The old
   entry-point block is retained for the compatibility release.

For a **retirement** declaration:

1. The local source and target blocks must each byte-match their respective
   installed-baseline blocks and their declared hashes.
2. Only after both checks pass may the upgrader delete the declared source
   block. It must leave the exact target block in place.
3. Any missing, duplicated, stale, or locally modified source or target is a
   blocking conflict with no partial write. In particular, an edited source is
   never deleted, replaced, or silently duplicated in the target.

`meridian audit` verifies the declaration against the current template,
reports an undeclared or stale duplicate as `FAIL`, and accepts the declared
cross-file duplication only during the additive compatibility release. Once a
retirement migration is current, a retained old source marker is a `FAIL` and
the audit identifies the declared move and source path. Existing whole-file
three-way conflicts remain conflicts; move handling is a narrower additional
safety gate, not an overwrite path.

### Release sequence, rollback boundary, and fixtures

Release A (task 024) adds all four role documents, their exact canonical
marker blocks, compact routing links, and `stage: additive` declarations. It
retains every entry-point procedure. Release R (task 025), at least one
framework release later, changes the entry points into compact routers and
declares the corresponding `stage: retirement` entries. A source block must
not be added and retired in the same migration or release.

There is no automatic downgrade or destructive rollback across this boundary.
Before Release R, recovery means leaving both copies in place and issuing a
forward corrective migration if needed. After Release R, recovery means a
forward additive migration that restores a verified source or adjusts routing;
the upgrader never reconstructs or deletes a customized historical source.
The installed baseline is the proof boundary for every operation.

Task 024 and task 025 must cover at least these fixtures:

1. A vanilla governed-SDD project upgrades and audits successfully through
   Release A and then Release R.
2. A project with a locally modified source marker blocks before any write in
   both stages; its source text remains present and unchanged.
3. A project with a locally modified target marker blocks retirement before
   any source deletion.
4. A manually pre-created target is accepted only when its complete marker
   block exactly matches the declared target hash; a divergent or duplicated
   target blocks.
5. An explicit `MERIDIAN:CLAUDE-AGENTS-POINTER v1` project upgrades and audits
   without adding duplicate Claude marker blocks, and its router reaches the
   same managed role documents through `AGENTS.md`.
6. Repository checks enforce both entry-point byte budgets and reject a move
   record whose paths, marker count, or hashes are not exact.

Task 026 additionally measures both host entry points before and after the
retirement release and exercises the status, implementation, and review routes
on a clean consumer checkout.

## Consequences

The initial-entry cost becomes bounded and role-specific procedures remain
managed and auditable. The additive release intentionally duplicates protected
text for one compatibility release, so the byte reduction arrives only with
the later retirement release. That delay is required to make a local edit a
visible conflict rather than a lost rule.

## Out of Scope

This ADR does not define changes to task lifecycle, review policy, validation,
evidence, Git semantics, consumer projects, or the content of existing
capability markers. It does not implement the schema or alter template files.
