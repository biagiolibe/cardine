# ADR: Shared Generated Entry Routers for Consumer Projects

Status: Proposed

## Context

Tasks 023–025 made Meridian's generic governed-SDD procedures routable and
safe to relocate. The consumer project A preflight in task 026 exposed a separate
consumer concern: its project-owned `AGENTS.md` is a 31,619-byte monolith.
An explicit `CLAUDE.md` pointer is safe and avoids duplicate capability
markers, but it still requires Claude to read that monolith. It therefore
does not deliver route-specific initial context.

Meridian must preserve consumer-owned rules rather than infer that they are
duplicates. Consumer adoption needs a deliberate architecture mapping, a
two-release move, and verification that both hosts start from the same compact
router.

## Decision

### One canonical router, two generated entry points

Each adopting consumer owns one canonical source at
`docs/workflows/ENTRY_ROUTER.md`. Meridian generates both `AGENTS.md` and
`CLAUDE.md` from that source. The generated content must be byte-identical
except for an optional, documented host overlay that contains no routing,
authority, lifecycle, validation, review, Git, or domain rule.

The canonical router and each generated entry point have a maximum UTF-8 size
of 2,048 bytes. `wc -c` is the normative measurement. The generator and audit
must reject drift between the source and either generated output.

An explicit `MERIDIAN:CLAUDE-AGENTS-POINTER v1` remains a supported migration
input only. It is not the target architecture for a consumer that adopts this
ADR, because a pointer adds a second mandatory read and cannot establish
equal initial context for Claude and Codex.

### Router contents and routing contract

The shared router contains only language and governed-workflow mode locks,
developer-assigned/read-only scope and working-tree preservation rules, the
command-to-document map, and the smallest consumer invariants that every route
must know before it can select a document. It must not contain an
implementation, review, remediation, lifecycle, validation, evidence, branch,
commit, merge, or broad domain procedure.

Every consumer maps at least these requests to one primary document:

| Request | Required document |
|---|---|
| Status or technical-design question | `docs/workflows/STATUS_DESIGN.md` |
| `Proceed with <TASK-ID>` | `docs/workflows/IMPLEMENTATION.md` |
| `Review <TASK-ID>` | `docs/workflows/REVIEW.md` |
| `Address review <TASK-ID>` | `docs/workflows/REMEDIATION.md` |
| `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` | `docs/workflows/LIFECYCLE.md` |
| Explicit audit | `docs/AUDIT_PROMPT_READ_ONLY.md` |

Role documents name the consumer architecture or domain-invariant documents
that their route needs. A status/design request must not load implementation
or review procedure text merely because it exists in the repository.

### Consumer-owned rules and safe adoption

Before changing an entry point, the consumer records an ADR map from every
existing entry-point section to exactly one of: router, status/design,
implementation, review, remediation, lifecycle, or an existing authoritative
project document. The map identifies rules that are intentionally always
loaded and explains why each fits within the router budget.

Adoption has two releases:

1. **Additive extraction.** Create the mapped documents and copy each local
   rule verbatim. Keep the existing entry points unchanged. Protected Meridian
   blocks use declared capability moves; unmarked consumer text is copied only
   through the consumer's explicit ADR map.
2. **Retirement and generation.** After route fixtures pass, generate compact
   `AGENTS.md` and `CLAUDE.md` from `ENTRY_ROUTER.md`, remove only copies whose
   additive evidence is accepted, and record before/after byte measurements.

Meridian never removes unmarked consumer text automatically. A conflict,
missing map, changed protected marker, or failed generated-router audit stops
the retirement without partial writes.

### Meridian support and evidence

Meridian will provide a generator, a check/audit for generated-router drift,
the byte-budget guard, and route-fixture helpers. It will preserve the current
capability-move checks for framework markers, including customized files and
legacy Claude pointers.

An adoption is accepted only when it records before/after byte counts for both
entry points; one status/design, implementation, and review fixture showing
the expected primary routed read; proof that lifecycle, validation, evidence,
review, and Git safeguards are reachable through role documents; and a
passing `meridian audit` with no retained retired marker or generated-file
drift.

## Consequences

Claude and Codex begin with equal, bounded instructions. A consumer retains
full control over its domain language and architecture rules, but must make
their routing explicit. Adoption costs two deliberate releases rather than a
single destructive rewrite; that cost is the safety boundary protecting local
semantics.

## Rollout Plan

1. Implement and test the generic generated-router contract in Meridian.
2. Complete task 026's compatibility upgrade only when explicitly authorized;
   it is a safe prerequisite, not the compact-router result.
3. Use consumer project A as the first mapped additive/retirement pilot.
4. Publish the validated consumer playbook and apply it project by project.

## Out of Scope

This ADR does not authorize a consumer project A edit, change a consumer's lifecycle
or domain semantics, remove its project-owned rules automatically, or replace
the existing compatibility rollout in task 026.
