# Meridian Self-Hosting Capability Profile

Status: implemented profile contract. Tasks 058–061 provide the manifest,
catalog, audit semantics, managed templates, adapters, conservative host
probes, and the clean-checkout dogfooding gate described here.

## Decision

Meridian keeps `lean-delivery` as its workflow lifecycle and declares a
separate, versioned `meridian-self-hosting` capability profile. A workflow
mode answers how work moves through project states. A capability profile
answers which operational safeguards the project consumes, where their
canonical policy and adapters are installed, and what evidence exists that
they are effective.

The two axes are independent:

```text
workflowMode: lean-delivery
capabilityProfiles: [meridian-self-hosting]
```

Enabling the profile must not add Governed SDD states, roles, task classes,
owner acceptance, review ceremony, or status-only commits. A project can use
the same capability under either lifecycle only when the capability catalog
declares that lifecycle applicable. Risk-based escalation to Governed SDD
remains a human workflow decision and is not a profile side effect.

`meridian-self-hosting` is an overlay for the Meridian repository, not a third
workflow mode. The design also permits consumer-defined profiles later, but
does not require that generalization for the first implementation.

## Current gap

The current manifest's `mode` is `lean-delivery`, its `managedFiles` contains
only the three workflow entry documents, and `appliedMigrations` includes
historical migrations for capabilities that were never installed for Lean
Delivery. Current capability detection and protected-region audit are gated
to `governed-sdd`. Consequently, an audit of Meridian can return exit zero
with `No capability markers found to audit.`

Those observations are three different facts:

- migration history says which upgrade records the installation traversed;
- effective capability state says what the project currently declares and
  installs;
- host evidence says whether an installed adapter is active and effective in
  a named host profile.

None is proof of either of the others.

## Capability catalog and applicability

Each released capability has one catalog record owned by the framework. The
record contains:

- a stable capability ID and version;
- the canonical policy blocks and adapter artifacts for that version;
- applicable workflow modes: `lean-delivery`, `governed-sdd`, or both;
- whether it is eligible for `meridian-self-hosting`;
- supported host profiles and the evidence kind required for each;
- allowed installation forms: `managed-copy`, `shared-source`, or
  `declaration-only`;
- dependencies on other capabilities, if any.

The manifest references these records by ID and version. It does not copy
canonical policy text or restate applicability rules. Protected markers
remain content-integrity anchors for managed policy blocks; catalog metadata
decides whether a block is applicable. Template presence is installation
evidence at most and never host-activation evidence.

Applicability is an intersection, not an inference:

1. the catalog must allow the project's `workflowMode`;
2. the selected profile must include the capability;
3. the named host profile must be supported when activation is host-specific.

An exclusion must be explicit in the profile definition. `NOT_APPLICABLE` is
valid only when the catalog excludes the workflow, self-hosting profile, or
host and the result names that reason. Missing installation or evidence for
an applicable declaration is never `NOT_APPLICABLE`.

## Manifest model

A protocol-versioned manifest eventually uses `workflowMode` as the canonical
field. During compatibility migration, readers accept legacy `mode` as its
equivalent, reject manifests that contain conflicting values, and writers
emit only `workflowMode` after the protocol upgrade.

The effective declaration is separate from `appliedMigrations`. The following
shape is illustrative; exact JSON-schema spelling belongs to the bounded
schema follow-up.

```json
{
  "workflowMode": "lean-delivery",
  "capabilityProfiles": {
    "meridian-self-hosting": {
      "profileVersion": 1,
      "capabilities": {
        "read-guard": {
          "requiredVersion": 1,
          "managedSurface": [
            {"path": "docs/CONTEXT_BUDGET_POLICY.md", "form": "managed-copy"},
            {"path": ".codex/hooks.json", "form": "managed-copy"},
            {"path": "hooks/read-guard.sh", "form": "shared-source"}
          ],
          "installation": {"state": "INSTALLED", "evidence": ["sha256:..."]},
          "hostActivation": {
            "codex-project": {
              "state": "UNVERIFIED",
              "evidence": [],
              "notApplicableRationale": null
            }
          },
          "verification": {
            "state": "UNVERIFIED",
            "evidence": [],
            "verifiedAt": null,
            "verifierVersion": null,
            "notApplicableRationale": null
          }
        }
      }
    }
  },
  "appliedMigrations": ["..."]
}
```

Every capability entry records its required version, complete managed
surface, installation state, per-host activation state, and verification
state. Every state includes evidence references appropriate to the claim. A
`NOT_APPLICABLE` state additionally requires a non-empty rationale tied to a
catalog applicability rule. `managedFiles` remains the content-hash inventory
for managed copies; `managedSurface` also names shared sources and activation
surfaces that are not copied.

Persisted states are evidence snapshots, not timeless truth. Installation,
host-probe, bootstrap, and upgrade operations may update them. Read-only audit
recomputes what it can, reports stale or contradictory snapshots, and never
silently promotes a state. Host evidence names the host, version, invocation
mode, configuration layer, evidence artifact, and observation time. A hash,
migration ID, config file, trust record, or successful static test cannot by
itself set host activation to active or verification to `PASS`.

### State dimensions

Installation state is one of:

- `INSTALLED`: every declared surface for the selected installation form is
  present and its integrity is verified;
- `MISSING`: at least one required surface is absent;
- `DRIFTED`: a surface exists but does not match the declared version or
  integrity record;
- `NOT_APPLICABLE`: permitted only with the catalog-backed rationale above.

Host activation state follows the host contract and is one of `ENFORCED`,
`ADVISORY`, `UNSUPPORTED`, `UNVERIFIED`, or `NOT_APPLICABLE`. An adapter must
be installed, configured, trusted, and observed effective before it is
`ENFORCED`.

Verification state is one of `PASS`, `ADVISORY`, `UNVERIFIED`,
`NOT_APPLICABLE`, or `FAIL`. It is derived from applicability, installation,
activation, and capability-specific checks; it is not an operator-selected
summary.

## First self-hosted capability set

The first profile is deliberately smaller than the Governed SDD template.
Shared policy blocks may be factored into a workflow-neutral canonical source
and rendered into workflow documents, but the source text remains singular.

| Capability | Decision | Rationale and self-hosted surface |
|---|---|---|
| Language policy | Include | Language selection and English-only repository artifacts do not depend on lifecycle. Manage `LANGUAGE_POLICY.md`; optionally brief it through a host adapter without treating the reminder as enforcement. |
| Minimal read-only status | Include after neutralization | The context-minimizing behavior applies to either queue shape. The canonical block must say “current workflow status,” not “governed-SDD status,” and use the mode's own terminal states. Install it in `docs/CONTEXT_BUDGET_POLICY.md`. |
| Context budgeting | Include a neutral core | Include task-first loading, bounded exploration, evidence tiers, context reuse, and planning/communication limits. Exclude Governed-only orchestration, role, acceptance, and task-blueprint requirements. Install the selected canonical blocks in `docs/CONTEXT_BUDGET_POLICY.md`. |
| Queue briefing | Include, host-dependent | `hooks/queue-briefing.sh` already parses Lean and Governed queues. For Meridian, reference that repository-owned shared source and `hooks/hooks.json`; do not duplicate the script. Claude plugin activation can be probed. Codex remains `UNSUPPORTED` or `NOT_APPLICABLE` until a prompt-submit adapter exists. |
| Read guard | Include, host-dependent | The read boundary is workflow-neutral, but adapters differ. Reference `hooks/read-guard.sh` as shared source. Reference `hooks/hooks.json` for Claude. Install a local `.codex/hooks.json` for the Codex Bash adapter; installation and project trust remain distinct from enforcement. |
| Validation scoping | Include | Diff-surface-based validation is independent of lifecycle and prevents waste without weakening task criteria. Install its canonical block in `docs/CONTEXT_BUDGET_POLICY.md` and refer to it from Lean completion rules without importing Governed gates. |
| Execution-evidence discipline | Include with a configured profile | Bounded output, progressive diagnostics, diff inspection, and evidence-tier rules apply to Lean work. Manage the neutral policy block plus a repository-owned `docs/EXECUTION_EVIDENCE_PROFILE.md`; placeholder fields cannot receive `PASS`. Governed-only review and orchestration clauses are excluded. |
| Worktree safety | Include | One writer, deterministic branch/worktree identity, doctor checks, protected Git metadata, integration lease, and evidence-aware integration are already Lean policy. Manage their marked policy blocks and `.codex/rules/meridian.rules`; rules prove prompt policy only, not sandbox or Git access. |

The initial profile excludes authority excerpts, task blueprints, lifecycle
orchestration, owner acceptance, implementer/reviewer identities, remediation
records, review prompts, and Governed task states. Some may later qualify as
workflow-neutral, but adding one requires its own rationale and versioned
profile change rather than copying the rest of the Governed template.

## Minimum managed repository surface

The first implementation must make these surfaces explicit:

| Surface | Treatment |
|---|---|
| `LANGUAGE_POLICY.md` | Local managed copy with project-owned conversation-language value outside the protected canonical block. |
| `docs/CONTEXT_BUDGET_POLICY.md` | Local managed document composed only from the selected workflow-neutral blocks; do not copy the whole Governed document. |
| `docs/EXECUTION_EVIDENCE_PROFILE.md` | Local managed and configured profile; unresolved placeholders are `UNVERIFIED` or `FAIL` when the profile requires them. |
| `PROJECT_WORKFLOW.md`, `AGENTS.md`, `CLAUDE.md` | Existing Lean managed copies; add or preserve markers only for profile capabilities actually carried there. |
| `.codex/rules/meridian.rules` | Local managed copy for command-approval policy used by worktree safety. Its presence does not prove trust, sandbox access, or effective decisions. |
| `.codex/hooks.json` | Local managed copy for the Codex read-guard adapter. Required only for the declared Codex project profile and audited separately from activation. |
| `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, `hooks/hooks.json` | Repository-owned shared sources because Meridian is their distribution source. The manifest records their exact shared-source paths and hashes; no second local copy is created. |

If a supported installation cannot use `shared-source`, bootstrap must select a
catalog-supported managed-copy form and record the resulting paths. A missing
required form is `MISSING`, not an implicit exclusion.

## Bootstrap and upgrade compatibility

Existing manifests remain readable. On first profile-aware bootstrap or
upgrade:

1. read legacy `mode` as `workflowMode` and retain `lean-delivery`;
2. preserve `appliedMigrations` unchanged as migration history;
3. construct no effective capability claim from those entries;
4. evaluate the selected profile's current catalog against the repository;
5. record each capability as observed `INSTALLED`, `MISSING`, `DRIFTED`, or
   justified `NOT_APPLICABLE`, and record host activation as `UNVERIFIED`
   until a matching probe exists;
6. plan additions and merges through the ordinary baseline machinery; never
   overwrite customized files merely because a historical migration is
   present;
7. emit the new profile declaration only after its schema and managed-surface
   plan validate.

A Lean manifest that lists migrations such as minimal status, queue briefing,
execution evidence, or reasoning budgets therefore gains no capability merely
from those IDs. If the surface was not installed under Lean, bootstrap reports
it missing and the upgrade plan explicitly installs it. If it was installed
manually and matches canonical content, bootstrap may record `INSTALLED`, but
activation still requires separate host evidence.

Profile versions and capability versions advance independently of migration
IDs. A migration may install or update a capability, but its completion is
historical provenance, not effective-state truth. Downgrades or profile
removal must retain migration history and remove effective declarations only
through an explicit plan that identifies the surfaces left behind or removed.

## Non-vacuous audit semantics

Audit begins from the manifest declaration and catalog, in every workflow
mode. It never begins by scanning for whatever markers happen to exist.

For each declared capability and host profile, audit must emit at least one
named result:

- `PASS`: applicable surfaces match the required version and all evidence
  required for the claimed level is current;
- `ADVISORY`: policy or adapter intentionally provides guidance that can be
  bypassed, with evidence confirming that advisory path;
- `UNVERIFIED`: an applicable claim lacks current activation or verification
  evidence, or a persisted snapshot is stale;
- `NOT_APPLICABLE`: the catalog excludes this workflow/profile/host and the
  report prints the required rationale;
- `FAIL`: a required declaration or surface is absent, drifted, contradictory,
  below version, falsely claims activation, or exposes no auditable surface.

`No capability markers found to audit.` is never a successful result for a
locked project. A locked project with no `capabilityProfiles` receives a
named compatibility result: `UNVERIFIED` while legacy manifests are supported,
then `FAIL` once the protocol version requires explicit declarations. A
declared capability with an empty or unresolvable `managedSurface` is `FAIL`.
An audit containing only justified `NOT_APPLICABLE` rows may succeed, but it
must print those rows and the aggregate count; it is not an empty audit.

Exit codes are deterministic:

| Aggregate result | Exit code |
|---|---:|
| All applicable rows `PASS`, with any explicit `NOT_APPLICABLE` rows | 0 |
| At least one `ADVISORY` or `UNVERIFIED`, and no `FAIL` | 1 |
| At least one `FAIL`, invalid declaration, or unauditable required surface | 2 |

The command prints counts for every state and the worst aggregate result.
CI treats both 1 and 2 as non-success for the required self-hosting profile;
interactive callers may distinguish evidence still needed from definitive
drift. Marker-integrity checks, installation hashes, configuration presence,
host activation probes, and capability-specific behavior checks remain
separate report items so a passing static check cannot mask missing runtime
evidence.

## Dogfooding verification

Local verification for Meridian runs the profile-aware audit from the
repository root and a read-only profile doctor that resolves every declared
surface and host profile. CI runs the same checks in a clean checkout. Both
must confirm:

- `workflowMode` remains `lean-delivery`;
- the `meridian-self-hosting` profile and required capability versions are
  declared;
- managed copies and shared sources match their integrity records;
- every applicable capability has a non-empty auditable surface;
- host-dependent results are no stronger than the recorded host evidence;
- no Governed-only lifecycle capability entered the profile.

The concrete commands are:

```bash
python3 scripts/meridian.py --framework-root . profile doctor meridian-self-hosting --project .
python3 scripts/meridian.py --framework-root . audit --project . --mode lean-delivery --ci-profile meridian-self-hosting
```

The doctor resolves catalog declarations, managed copies, shared sources,
manifest evidence references, and every profile-required probe without
writing. The CI audit continues to print host-dependent `UNVERIFIED` rows, but
its CI gate requires every static installation row and every global audit
failure condition to pass. The separately executed unit suite supplies the
behavior checks named by the host-neutral probe. This does not promote an
interactive host state.

Versioned probe records live under
`.meridian/probes/meridian-self-hosting/`. Each names the exact host profile,
host version or explicit unverified scope, invocation mode, configuration
layer, observation time, evidence artifact, behaviors and dimensions, state,
and fallback. The Codex record keeps hook configuration, project trust,
filesystem access, execpolicy decisions, command results, and read-guard
behavior separate. The Claude record separately covers shared-source
integrity, plugin activation, permission behavior, queue briefing, and
read-guard behavior. Until a probe is run in a matching Meridian host session,
its observation and evidence fields remain null and manifest activation stays
`UNVERIFIED`.

Deterministic fixtures cover at least:

1. the complete self-hosting declaration, producing the expected per-item
   results and aggregate code;
2. a declared managed policy file removed from disk, producing `FAIL` and
   exit 2;
3. a declared `.codex/hooks.json` or shared hook source removed, producing
   `FAIL` rather than `No capability markers found`;
4. an installed adapter with no activation proof, producing `UNVERIFIED` and
   exit 1 rather than `PASS`;
5. a valid catalog-backed host exclusion, producing a visible
   `NOT_APPLICABLE` row;
6. a legacy Lean manifest whose `appliedMigrations` names a capability but
   whose surface is absent, proving that history is not activation.

Repository tests can establish parsing, integrity, state derivation, and exit
codes. An `ENFORCED` host claim additionally requires the versioned real-host
probe defined by `docs/HOST_CAPABILITY_CONTRACT.md`; CI without that host
evidence must retain `UNVERIFIED` rather than fabricate parity.

## Bounded implementation follow-ups

Implementation is split in this order. These are follow-up task definitions,
not tasks created or started by this design.

1. **Manifest and catalog support** — define the protocol/schema changes,
   `workflowMode` compatibility, profile/catalog records, state validation,
   and legacy-manifest projection. Add a schema migration, but no capability
   migration or activation claim.
2. **Cross-mode audit semantics** — drive audit from declarations, implement
   the result lattice and exit codes, retain marker integrity checks, and add
   positive, negative, legacy, and empty-surface fixtures. This changes audit
   behavior but installs no project surface.
3. **Managed self-hosting surfaces** — factor the selected canonical blocks,
   add the local documents/configuration and shared-source declarations, then
   bootstrap Meridian's manifest. This requires capability-marker versions or
   moves wherever canonical protected text changes, plus migrations whose
   `managedPaths` exactly name installed copies. Shared sources receive
   integrity records without duplicate policy markers.
4. **Host probes and CI dogfooding gate** — implement named-host activation
   probes, record their evidence, and make CI reject aggregate exit 1 or 2 for
   the required profile. Host state remains `UNVERIFIED`, `ADVISORY`, or
   `UNSUPPORTED` until each probe satisfies the host contract.

Each follow-up must preserve existing Lean and Governed consumers. The first
two may ship without enabling Meridian's profile. The third depends on both;
the fourth depends on the installed surfaces. A marker migration records a
canonical content/version transition only. It must not be used as an
activation or verification record.

## Non-goals

This design does not switch Meridian to Governed SDD, automatically choose a
workflow based on risk, install or enable hooks, alter current audit output,
generalize every Governed capability, or claim host enforcement. It does not
create the follow-up tasks named above.
