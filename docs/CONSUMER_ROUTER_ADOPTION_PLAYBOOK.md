# Consumer Router Adoption Playbook

This playbook applies the shared generated-entry-router ADR to one consumer
project at a time. It is a safe adoption procedure, not authorization to edit
an arbitrary consumer. Each consumer needs its own ADR, task records,
migration evidence, and passing audit before it can claim adoption.

## Outcome and non-negotiable boundaries

The target architecture has one consumer-owned canonical router at
`docs/workflows/ENTRY_ROUTER.md`. Meridian generates both `AGENTS.md` and
`CLAUDE.md` from it. The router selects a single primary procedure for each
recognized request; role procedures retain the detailed workflow and
consumer-domain rules.

The router and each generated entry point must be at most 2,048 UTF-8 bytes,
measured with `wc -c`. Generated entry points must match the canonical router
byte-for-byte, except for an explicitly documented and permitted host overlay.
A Claude-to-AGENTS pointer is a supported upgrade input, not the target
architecture.

Never infer that consumer-owned prose is duplicated. A Meridian-managed marker
is movable only through its declared capability-move evidence. An unmarked
consumer rule is copied and later retired only through the consumer's accepted
ADR map. Missing map entries, changed markers, generated-file drift, or a
consumer-content conflict stop the retirement without a partial write.

## 1. Inventory and consumer ADR

Before changing either entry point, inventory every existing section in
`AGENTS.md` and `CLAUDE.md`, including wrappers around managed markers. The
consumer ADR maps every section to exactly one destination:

| Destination | Use |
|---|---|
| Router | An invariant that every request must know before route selection. |
| Status/design | Read-only product, architecture, or domain context. |
| Implementation | `Proceed with <TASK-ID>` procedure and its required authorities. |
| Review | `Review <TASK-ID>` procedure and its required authorities. |
| Remediation | `Address review <TASK-ID>` procedure. |
| Lifecycle | `Run lifecycle <TASK-ID>` and `Accept <TASK-ID>` procedure. |
| Existing authoritative document | A rule already owned by a documented consumer authority. |

The ADR must explain why each always-loaded rule belongs in the router budget
and identify the canonical destination for every other rule. It must also
separate the following categories explicitly:

- Meridian-managed marker blocks, with their capability names, versions, and
  required move declarations.
- Unmarked consumer rules, copied verbatim only through the map.
- Rules intentionally retained in the router, with the size rationale.

The ADR is the proof boundary for consumer prose. Do not use semantic
similarity, a heading name, or an agent judgment as authority to delete it.

## 2. Release A: additive extraction

Create the mapped status/design, implementation, review, remediation, and
lifecycle documents. Copy every mapped rule to its canonical destination while
leaving both entry points unchanged. Preserve managed markers exactly and use
the framework's declared additive capability moves for them.

Do not create a generated router, delete old copies, compact an entry point,
or change lifecycle, validation, review, Git, or domain semantics in this
release. Complete the consumer's review and acceptance process before moving
to retirement.

Record these Release A evidence items:

- the accepted ADR map and the accepted additive task/review record;
- a clean `meridian upgrade --project <consumer> --check` result;
- a passing `meridian audit --project <consumer> --mode governed-sdd` result;
- proof that every mapped consumer rule was copied to its declared destination
  and that both original entry points remain present.

## 3. Route fixtures

Before retirement, exercise the router contract with fixtures or fresh
sessions. Each route starts with the router plus the mandatory local workflow
and language-policy reads, then loads only its primary role procedure; it must
not preload another role procedure merely because it exists.

| Request | Primary document |
|---|---|
| Status or technical-design question | `docs/workflows/STATUS_DESIGN.md` |
| `Proceed with <TASK-ID>` | `docs/workflows/IMPLEMENTATION.md` |
| `Review <TASK-ID>` | `docs/workflows/REVIEW.md` |
| `Address review <TASK-ID>` | `docs/workflows/REMEDIATION.md` |
| `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` | `docs/workflows/LIFECYCLE.md` |
| Explicit audit | `docs/AUDIT_PROMPT_READ_ONLY.md` |

At minimum, record passing status/design, implementation, and review fixtures.
They must show that lifecycle, validation, evidence, review, and Git safeguards
remain reachable through the routed documents. A directory listing is not
evidence that an unrelated procedure was loaded.

## 4. Release R: generation and retirement

Only after Release A is accepted and the route fixtures pass:

1. Create `docs/workflows/ENTRY_ROUTER.md` and the consumer's route map.
2. Generate both entry points with `meridian generate-entry-routers --project
   <consumer> --write`.
3. Retire only copies whose accepted additive evidence and ADR-map destinations
   are recorded.
4. Stop on any route, marker, generated-file, or consumer-content conflict;
   resolve it with a forward, explicitly reviewed change rather than deleting
   around it.

After adoption, framework upgrades treat `AGENTS.md` and `CLAUDE.md` as
generated outputs. An upgrade plan reports them as `ROUTER` and never merges
the framework templates into them. When a pending `command-triggers` migration
adds a command, the canonical router must expose that exact command and its
target document before apply can start. If the target already has a route,
append the command to that existing line: the route audit requires every target
document to appear exactly once. Successful apply regenerates both entry
points, audits the result immediately, and records the generated-file hashes.

The final router contains bootstrap invariants and the route map, not role
procedures. It must not emit a Claude pointer.

## 5. Measurable exit criteria

An adoption is complete only when its durable evidence records all of the
following:

- `wc -c docs/workflows/ENTRY_ROUTER.md AGENTS.md CLAUDE.md` shows each file
  at or below 2,048 bytes;
- `meridian generate-entry-routers --project <consumer> --check` passes;
- `meridian audit --project <consumer> --mode governed-sdd` passes with no
  generated-router drift or retained retired marker;
- `meridian upgrade --project <consumer> --check` is clean, and `git -C
  <consumer> diff --check` passes;
- before/after byte counts for both entry points are recorded;
- the accepted ADR map, Release A evidence, retirement evidence, and route
  fixtures identify the canonical destinations and the safeguards reached.

## 6. Rollback and recovery boundary

Release A is the compatibility boundary: if evidence is incomplete, retain
both copies and issue a forward corrective change. Do not begin retirement.

After Release R, do not attempt an automatic downgrade or reconstruct an old
consumer entry point. Recover through a forward additive migration or an
explicitly reviewed consumer change that restores a verified rule or corrects
the route. The installed baseline and accepted ADR map remain the evidence for
what may be moved or restored.
