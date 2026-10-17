# Design: Versioned Capability Markers and Protected Regions

Status: phases 1-4 shipped (markers on capabilities 001/002, version-aware
detection, cosmetic-vs-real conflict resolution in `upgrade`, and
`meridian audit`'s protected-region integrity check). Phase 5 (process
discipline) is documented in `CONTRIBUTING.md`/`migrations/README.md`.
Migrations 007-012 additionally shipped markers for 004/005, the v2,
path-parameterized canon for 001/002, baseline capabilities for
`PROJECT_WORKFLOW.md`'s eight sections, baseline capabilities for four
whole-file policies, and baseline capabilities for `AGENTS.md`/`CLAUDE.md`'s
remaining sections — every managed governed-SDD file now has capability
tracking except the two intentionally excluded ones. Migration 013 then
corrected a real defect found while starting the consumer project A retrofit:
`language-policy`'s v1 marker wrongly enclosed the per-project conversation-
language declaration that `meridian-init.md` fills in during initialization,
which would have failed `meridian audit` for every correctly initialized
project, not just consumer project A — moved that line outside the protected region
in v2. Only the full consumer project A retrofit remains — see
"Addendum: expanded retrofit plan" near the end of this document for the
current, authoritative state; treat the original Phase 1-5 plan below as
historical design reasoning, not the up-to-date task list. This document
integrates two ideas
discussed while adopting Meridian onto a heavily customized project
(consumer project A): capability detection that survives a project rewriting
Meridian's prose in its own voice, and a way to stop that same rewriting from
silently swallowing a framework-mandated rule. Both problems have the same
root cause and the same fix.

## The problem, precisely

`meridian upgrade` compares managed files byte-for-byte via a three-way merge.
That works while a project's wording stays close to the template. It breaks
permanently once a project restates the same rule in its own structure and
voice — not a bug, a mismatch between what the tool checks (exact text) and
what actually matters (behavior). Two concrete failures from this session:

1. **False negatives in detection.** `detect_mode()` and parts of
   `detect_capabilities()` look for literal tokens (`GOVERNED_SDD`, `Address
   review`, `Run lifecycle`). A project whose `PROJECT_WORKFLOW.md` predates
   the exact `GOVERNED_SDD` token — genuinely governed-SDD in substance —
   fails detection (`consumer project B`, then `consumer project A`, both this session).
2. **Permanent merge conflicts with no way to tell real gaps from cosmetic
   ones.** consumer project A's `AGENTS.md`/`CLAUDE.md`/four docs files conflict on
   every upgrade because their wording diverged from the template long ago,
   even after every rule was correctly, manually incorporated in consumer project A's
   own voice. `upgrade --check` cannot distinguish "this project doesn't have
   the rule" from "this project has the rule, phrased differently" — so the
   only tool-supported outcome was `--owner-reconciled`, an act of faith by
   the operator, not a verified fact.

There's also a related, unaddressed gap: **a migration that modifies an
existing capability** (not adds a new one) is invisible to a presence-only
check. If `detect_capabilities()` only asks "is `Address review` mentioned
anywhere," it can never tell v1 of that capability's rule from v2 — the
phrase can still be there while the actual rule text it governs is stale.

## The fix: a versioned marker that also protects its own content

A short, invisible marker pair wraps the framework-owned text for one
capability:

```markdown
<!-- MERIDIAN:BEGIN capability=validation-scoping v1 -->
Before running validation, classify the diff by surface: *documentation/policy
text* ... [exact canonical text] ...
<!-- MERIDIAN:END -->
```

Three rules, each independently checkable:

1. **Detection is version-aware, not boolean.** A migration that changes
   `validation-scoping` declares the version it requires
   (`capabilityVersion: 2`). Detection reads the marker's version and
   compares it to what's required — present-but-stale is a real, distinct
   state from absent, and both route to the same remediation loop
   (`IMPLEMENT_MIGRATION` distinguishes "add" from "update" only in its
   generated prompt text, not in the state machine).
2. **The bracketed content is not to be reworded.** Between `BEGIN` and
   `END` is the framework's exact canonical text for that capability version.
   A project extends by writing its own material *outside* the markers —
   referencing the protected rule, adding project-specific detail beneath it
   — never by rewriting what's inside.
3. **The marker is also an integrity anchor.** Because the protected content
   is supposed to be byte-identical to a known release of that capability
   version, a verifier can hash it and confirm it matches *some* released
   version of `validation-scoping` — not necessarily the latest, just a real
   one that was never hand-edited.

This does not make the region technically unmodifiable — nothing does, for
plain text an agent can write to. It makes an unauthorized edit **immediately
and mechanically detectable**, which is the practical equivalent as long as
detection is wired into a gate someone actually has to pass (see
Verification below). The same self-report problem that motivated migration
005 (CI-verified validation) applies here too: a bumped version number next
to unchanged (or wrongly changed) text is exactly as untrustworthy as a bare
"tests passed," so a reviewer verifying a capability-version bump must
re-derive that the protected text actually matches the claimed version — not
trust the marker any more than migration 005 trusts a self-reported pass.

## Migration record shape

```json
{
  "id": "006-validation-scoping-v2",
  "capability": "validation-scoping",
  "capabilityVersion": 2,
  "from": "1.1.2",
  "to": "1.1.3",
  "description": "Adds a third diff-surface category (configuration-only) between documentation and source.",
  "delta": "Insert one clause distinguishing configuration-only changes from documentation-only ones; the rest of the rule is unchanged from v1.",
  "managedPaths": ["docs/CONTEXT_BUDGET_POLICY.md"],
  "verification": ["..."]
}
```

`capability` and `capabilityVersion` are new, optional fields — a migration
that only touches the mechanical upgrade CLI (like today's 004/005 wrapper
logic) or that isn't naturally expressible as one marked region can omit
them and fall back to today's file-hash-only tracking. `delta` replaces the
implicit assumption in today's `assisted_implementer_prompt` that "missing
capability" always means "write it from scratch" — for a version bump, the
implementer's job is the delta only, the same atomic-task discipline Meridian
already asks of every other kind of work.

## Detection and remediation, unified

`detect_capabilities()` changes from "does this phrase appear anywhere" to:
for each migration with a `capability` field, find its marker in the
project, compare `capabilityVersion`; `MISSING` covers both "no marker" and
"marker below the required version," each reported with which case it is.

The genuinely new payoff is for `upgrade`, not just `adopt --assisted`: when
the three-way merge reports `CONFLICT` on a file that also carries a
capability marker, check the marker before asking the operator for
`--owner-reconciled`. Marker at the required version — the conflict is
cosmetic (the project already has the rule, worded its own way); register
the baseline with no agent involved, no act of faith. Marker missing or
stale — the conflict is real; dispatch the same implementer/reviewer loop
already built for adoption, scoped to `delta`, not a full rewrite.

## Verification: the part that makes protection more than a comment

Detection alone doesn't stop drift, it just measures it after the fact. Add
one deterministic check — inside the `meridian audit` command from
`QUALITY_COMPLIANCE_ROADMAP.md`'s Tier 2, not a new top-level command — that,
for every marker found in a project, hashes the bracketed content and
confirms it matches the exact text of *some* released version of that
capability (checked against every historical version shipped in Meridian's
own migration records, not only the latest). No match: report drift with the
capability id, claimed version, and the fact that its content doesn't match
any released text for it. This turns an edited protected region into an
audit finding a reviewer has to address, not a fact nobody notices until the
next upgrade conflicts for a reason nobody can explain.

## What this does not solve

- It doesn't stop an agent from deleting the markers entirely, or editing
  inside them, in the moment. Nothing can, for a plain file with write
  access. It stops that edit from going unnoticed past the next audit or
  review.
- It doesn't retroactively fix consumer project A's existing prose — the framework
  rules there are still interleaved with project-specific text in the same
  sentences in places. Introducing markers there is a one-time, manual
  separation job, the same kind of work already done by hand this session,
  done once so future drift becomes visible instead of accumulating again.
- It doesn't apply to Lean Delivery, which has no capability-tracked rules
  today; scope this to governed-SDD's managed docs only unless a concrete
  need for Lean Delivery capability tracking shows up later.

## Implementation plan

Sequenced so each phase is independently useful and testable; do not start a
phase before the previous one has tests passing.

**Phase 1 — Marker syntax and backfill (migration 006). Shipped.**
Define the exact marker grammar (regex Meridian's own tooling will parse),
retrofit `<!-- MERIDIAN:BEGIN capability=... v1 --> ... <!-- MERIDIAN:END -->`
around the existing capability text for `review-remediation-record` (001)
and `lifecycle-orchestration` (002) in `templates/workflows/governed-sdd/`.
This is itself a migration (touches managed files) — version bump, migration
record, tests, exactly like 004/005. Does not yet change any detection or
verification code; it only makes the markers exist so the next phases have
something to read.

**Phase 2 — Version-aware `detect_capabilities()`. Shipped.**
Added the `capability`/`capabilityVersion` fields to the migration record
schema (backfilled onto 001/002); `detect_capabilities()` parses markers with
a version comparison. A legacy fallback (`LEGACY_CAPABILITY_EVIDENCE`) was
added beyond the original plan: without it, every project adopted before
migration 006 has no marker at all and would have regressed to fully
`MISSING` under marker-only detection — caught by testing against two real
projects (consumer project B, consumer project A) before shipping, not by the unit tests alone.
The fallback proves only v1, never a later version. `assisted_implementer_prompt`
surfaces a migration's `delta` field when present.

**Phase 3 — Cosmetic-vs-real conflict resolution in `upgrade`. Shipped.**
When `plan_from_baseline` reports a merge conflict for a file, and that
file's *own* content already carries a satisfied marker for every capability
it manages, the conflict downgrades to a new `VERIFIED` plan action (file
left untouched, does not block the upgrade) instead of a blocking
`CONFLICT`. The check had to be scoped to the file's own text, not
project-wide capability presence — an earlier version checked project-wide
and produced a false positive (a conflict on an unrelated file was wrongly
downgraded because a different file's marker happened to satisfy the
capability), caught by the existing conflict regression tests.
`--owner-reconciled` remains the fallback for a conflict with no marker at
all (unmarked legacy content, or a file no migration tracks as a capability).

**Phase 4 — Integrity verification in `meridian audit`. Shipped, narrower
than originally scoped.**
`meridian audit --project <path>` compares each marker's bracketed content
against the framework's *current* template for that same file and capability
version — not "every released version ever," since Meridian keeps no
separate historical archive of past capability text outside the current
templates. A marker naming a version the current template no longer carries
reports `SKIP` (a staleness question for `upgrade`) rather than a false
`FAIL`. Extending this to genuinely check against every historical version
would need a durable per-version text archive that does not exist yet — left
for a future revision if it turns out to matter in practice.

**Phase 4b — Supersession-aware insertion. Shipped.**
Migration 019's marker-aware insertion (`append_only_new_markers`) originally
compared `(capability, version)` pairs to decide what was "new." That cannot
distinguish a version bump from an unrelated new capability: a bumped pair is
absent from both the local and base pair sets exactly like a genuinely new
one is, so a template raising `manual-verification-precondition` from v1 to
v2 got appended as if v2 were a brand-new capability, leaving the stale v1
block — the one still read in place — untouched. Observed for real upgrading
consumer project A to 1.1.19; corrected there by hand, in consumer project A's own history
(commit `a83d88b`), before this framework fix landed. The function now groups by capability *name*: a name
absent from the local file (and never present in the base either) is still a
pure addition, appended as before; a name whose local version is lower than
the template's is a supersession, and its old block is replaced in place
*only* when it still matches the base byte-for-byte — otherwise the function
refuses and the file falls through to a blocking `CONFLICT` for manual
reconciliation, the same conservative default Phase 3 established. `meridian
audit` additionally reports `FAIL` when a single file carries more than one
version of the same capability, so a project already damaged by the old
behavior is found rather than left to accumulate a growing set of
contradictory pairs.

**Phase 5 — Process discipline. Documentation shipped; retrofit ongoing.**
`CONTRIBUTING.md` and `migrations/README.md` now require: a migration that
modifies existing framework-mandated prose (not just adds a new file) must
declare `capability`/`capabilityVersion` and wrap the affected text in
markers if it doesn't already have them, with a `delta` scoped to the actual
change. Migrations 003, 004, and 005 do not carry markers yet, and neither
`consumer project B` nor `consumer project A` (both real, already-adopted projects) have adopted
any marker — both are intentionally deferred to each one's next real change
rather than a dedicated migration or session with no other purpose.

Each phase after Phase 1 is optional to do immediately — the design holds
together even if only markers + version-aware detection ship and the
integrity audit lands later once `meridian audit` itself exists.

**Phase 6 — Retirement path (task 007). Shipped.** Every phase above is
additive: `capability`/`capabilityVersion` only ever introduces or bumps a
marker. Nothing could delete, merge, or supersede one, so the only way to
retire a rule was to leave a stale marker in place forever or edit it by
hand outside the protected mechanism entirely — Phase 4's own integrity
check would then flag that hand edit as unauthorized drift.

A migration record gains an optional `removes` list, the mirror of
`capabilities`:

```json
"removes": [
  { "capability": "old-rule", "capabilityVersion": 1, "supersededBy": "new-rule" }
]
```

`supersededBy` is optional and documentation-only — named in `meridian
upgrade`'s plan and `meridian audit` output, never written into a managed
file as a cross-reference line. A slot left behind inside a block the merge
keeps reconciling is the same protected-content-with-an-editable-hole
tension task 014 recorded as out of scope for `execution-assets`; retirement
does not reopen it. If a human wants a pointer left behind for readers, that
is ordinary unprotected prose added in the same migration, outside any
marker — the framework enforces nothing about it.

`capability_requirements()` processes migrations in order and drops a
capability the moment a `removes` entry retires it, so `meridian audit`
stops requiring it project-wide — the same requirements map `upgrade` and
`detect_capabilities` already share, not a second one. `meridian upgrade`
deletes the marker block from every managed path a migration's `removes`
entry applies to (scoped by that migration's own `managedPaths`, exactly
like the additive case), but only when the project's local copy still
matches its own locked baseline for that capability+version byte-for-byte —
`remove_retired_markers`, the structural mirror of the existing
supersession path in `append_only_new_markers`: safe to mutate only what
provably was not customized, refuse otherwise. A block the operator edited
under a marker the upgrade is about to delete is not silently discarded; the
file falls through to a blocking three-way-merge conflict for manual
reconciliation, the same conservative default every other unsafe case in
this mechanism already uses. Retiring an already-absent capability (never
adopted, or already removed by hand) is a no-op, not an error — running the
same retiring migration twice, or upgrading a project that skipped straight
to a later version, must never fail on that account.

The repository's own integrity guard (`scripts/check_repository.py`'s
`check_capability_marker_baselines`, added by task 014 to catch the
framework's own templates drifting silently — see commit `aaa1d57`) reuses
this exact requirements/removals data rather than a second record of "what
was this capability's content": a capability recorded in
`migrations/marker-baselines/CAPABILITY_MARKER_BASELINES.json` that is now
absent from the live templates is only accepted when
`retired_capability_ids()` confirms some migration actually declared it
`removes`; an unexplained absence still fails the guard exactly as before.
That baseline file itself carries no history — it is a snapshot of the
templates' *current* content, not an archive of every version ever
released (Phase 4's own "would need a durable per-version text archive
that does not exist yet" gap, still open); retirement's "was this modified"
check instead uses the project's own `.meridian/baselines/<version>/`
snapshot, already the reference `plan_from_baseline`'s three-way merge and
`append_only_new_markers` use for the identical question.

`meridian audit` also gains a structural duplication check,
`audit_duplicate_headings`: a capability whose marker sits under more than
one distinct heading *within the same managed file* is flagged, the
mechanical signature of an accidental duplicate paste. It is deliberately
scoped to one file at a time — the same capability legitimately appears
under different heading names in different consuming documents by design
(`ci-verified-validation` in both `docs/CODE_REVIEW_PROMPT.md` and
`docs/COMPLETION_REPORT_TEMPLATE.md`, for one), and a cross-file version of
this check produced five false positives against exactly that pattern
before this narrower scope was chosen. It cannot catch a *paraphrased*
duplicate with no shared marker at all, such as the reviewer-integrator-identity
triplication that originally motivated this task (task 007's Technical
Context) — that has no marker to compare and remains a human review
concern, invisible to any mechanical check, diff tool included.

## Addendum: expanded retrofit plan

Decided while bringing consumer project A to full compliance: consumer project A's own
directory conventions (`docs/TASK_QUEUE.md`, `docs/tasks/<milestone>/`,
`docs/tasks/reviews/`) are hardcoded inline inside 001/002's canonical text,
so wrapping consumer project A's actual wording in a marker would be a false claim
(it isn't the canonical text) and would fail `meridian audit`. Bringing
consumer project A to genuine compliance without changing its real file layout
requires the canonical text itself to stop hardcoding paths — a framework
change, not a consumer project A-only one. Separately: `PROJECT_WORKFLOW.md` — the
single most important managed file, since it carries the `GOVERNED_SDD`
mode lock itself — has no capability tracking at all today, the same gap
001/002 had before migration 006, just not yet hit by a real incident.

**Migration 007 (shipped).** Markers + capability fields for
`validation-scoping` and `ci-verified-validation`, matching what 006 did for
001/002. Required relaxing `extract_marker_block`'s grammar to accept an
inline, mid-sentence marker (not just a marker on its own line), since
`validation-scoping`'s text in `AGENTS.md`/`CLAUDE.md` is one clause inside a
larger numbered step, not a standalone section.

**Migrations 008 and 009 (shipped).** Split into two migrations, not one —
the schema attaches only one `capability`/`capabilityVersion` pair per
migration record, matching every migration shipped so far. `008` bumps
`review-remediation-record` to `capabilityVersion: 2`: the canonical text in
`AGENTS.md`/`CLAUDE.md`/`docs/REVIEW_RECORD_TEMPLATE.md` stops hardcoding
`tasks/reviews/<TASK-ID>.md` inline and instead references a new "Canonical
locations" paragraph added to `PROJECT_WORKFLOW.md`'s Execution assets
section. `009` does the same for `lifecycle-orchestration` in
`docs/LIFECYCLE_ORCHESTRATION.md`, and relabels the unchanged
`AGENTS.md`/`CLAUDE.md` marker from v1 to v2 to match — every occurrence of
one capability's marker must agree on version, or the lowest one found
reports the whole capability stale.

Real, verified-live consequence, not a bug: `consumer project B` and `consumer project A` — the
two real projects adopted so far — now report `review-remediation-record`
and `lifecycle-orchestration` as `MISSING` (stale at v1) rather than
`PRESENT`, since `LEGACY_CAPABILITY_EVIDENCE` only ever proves v1. Both need
another assisted-adoption pass to reach `1.1.6`. This is the correct
trade-off: the alternative (not bumping the version) would mean the same
version label pointing at two different canonical texts, which breaks
`meridian audit`'s entire premise.

**Migrations 010-012: baseline capabilities for everything else that's
binding but untracked.** One capability per genuinely independent rule, not
one per file — a composite file keeps the same precision Phase 3 relies on.
Two files are deliberately excluded: `docs/ARCHITECTURE_DECISIONS.md` is a
scaffold the project is meant to fill in, and `docs/OPERATOR_PROMPTS.md` is
an explicitly non-normative cookbook (`check_repository.py` already enforces
that it stays one) — protecting either would fight its purpose.

- **010 — `PROJECT_WORKFLOW.md` (shipped).** One capability per `##` section:
  `workflow-mode-lock`, `document-precedence`, `task-lifecycle`,
  `execution-assets`, `roles`, `review-policy`, `git-workflow` (folding in
  its `Reviewer-integrator identity` subsection), `execution-discipline`.
  Introduced the migration schema's `capabilities` list field (alongside the
  existing singular `capability`/`capabilityVersion`) so one migration
  record could declare all eight at once, rather than eight near-duplicate
  records — the same one-capability-per-record constraint that forced 008
  and 009 apart would otherwise have applied eight times over. Verified
  live: a fresh vanilla project passes `meridian audit` on all 20 marker
  occurrences across every migration with markers so far.
- **011 — whole-file capabilities (shipped)** for single-purpose files:
  `language-policy` (`LANGUAGE_POLICY.md`), `task-blueprint`
  (`tasks/TASK_BLUEPRINT.md`), `code-organization`
  (`docs/CODE_ORGANIZATION.md`), `audit-prompt`
  (`docs/AUDIT_PROMPT_READ_ONLY.md`). Verified live: a fresh vanilla project
  passes `meridian audit` on all 24 marker occurrences across every
  migration with markers so far.
- **012 — `AGENTS.md`/`CLAUDE.md` residual sections (shipped)**: `command-triggers`
  (the trigger-phrase list itself), `review-mode-boundary`,
  `owner-acceptance-workflow`, `implementer-reviewer-handoff`,
  `reviewer-integrator-identity`. `review-mode-boundary` was introduced
  already path-parameterized (no hardcoded `tasks/reviews/<TASK-ID>.md`),
  since a brand-new capability has no reason to ship with a defect a later
  migration would just have to fix again. `### Implementation workflow`'s
  steps 1-4 and 6-8 stay untracked: the marker grammar has no nesting, and
  step 5 already carries `validation-scoping`'s marker inside that same
  numbered section — wrapping the whole section would nest markers, which
  the parser does not support. Extending the grammar to support nesting is
  possible but deferred; it would mean revising a grammar already shipped in
  006. Verified live: a fresh vanilla project passes `meridian audit` on all
  34 marker occurrences — every managed governed-SDD file except the two
  intentionally excluded ones now has capability tracking.

**consumer project A retrofit (planned, after 007-012 land).** Every managed file
except the two excluded ones gets the protected-region + extension pattern:
canonical text byte-identical to the (parameterized, where applicable)
framework version, consumer project A's own material — explicit `cargo` commands,
the domain-crate dependency boundary, project terminology, milestone
`*-VERIFY` PR gating, the reviewer-identity override — moved to clearly
labeled extension text immediately outside the marker, never inside it.
Verification: `meridian audit` all `PASS`, `meridian upgrade --check` zero
conflicts across all previously-conflicting files, and a manual line-by-line
diff confirming no existing consumer project A rule was dropped, only relocated.

**Migration 065 — 1.2.12 lifecycle documentation.** The unreleased migration
keeps `task-blueprint` v16 and also registers `worktree-lifecycle` v3 for both
workflow modes. The lifecycle documents add proven commit-less fast-forward
base recovery with renewed validation, conservative `###` queue-section
archival, and, in Governed SDD only, the canonical SPIKE execution-evidence
ledger exception. Other lifecycle template text is unchanged.

**Migration 066 — 1.2.13 machine task state adoption.** The per-mode capability versions and managed paths in `066-machine-task-state-adoption.json` deliver command-owned review, remediation, closure, and owner acceptance. Status and verdict headings are projections only. Task branches own their state file. Run `meridian task state import --project <path> --format json`, inspect the evidence, then repeat with `--apply`; terminal tasks and existing state files are skipped.

## Migration 070 — 1.4.0 template delivery

`worktree-command-locations` v1 manages the command location link in both
`PROJECT_WORKFLOW.md` templates and the table in both
`docs/WORKTREE_LIFECYCLE.md` templates. Governed SDD additionally gains
`worktree-budget-retirement` v1 in `PROJECT_WORKFLOW.md` and
`handoff-correction-redelivery` v1 in `docs/COMPLETION_REPORT_TEMPLATE.md`.
These blocks version the previously unmarked additions from tasks 227–229,
so upgrade cannot treat an older handoff template as already satisfied merely
because its other markers are current. Per-file marker baselines record each
new block; the existing wording is unchanged.
