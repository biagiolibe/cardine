# ADR: Public Surface and Stability

Status: Accepted

*Proposed and accepted on 2026-10-14, with option A: the stable line starts at `1.3.0`.*

## Context

Meridian is already published: the repository is public under the MIT
License, every release has a tag and a GitHub Release, and adopters pin the
Claude Code marketplace or a Codex checkout to `v<version>`. The support policy
in `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (Decision 6) defines an upgrade
window, but nothing defines what an adopter may rely on between releases.

Observed on 2026-10-14 at `v1.2.15`:

- The README says the project is "early-stage / experimental" and that its
  public API and templates may evolve before a stable release. The version is
  `1.2.15`, and SemVer gives a `1.x` version a stable public API. The two
  signals contradict each other.
- Version numbers carry no compatibility meaning. `release.py prepare
  --bump patch` is used for every kind of release. `1.2.15` is a patch, but it
  adds a command (`meridian adr list`) and changes the workflow baseline
  (`baselineChanged: true`, migration `068-adr-list-discovery`).
- The CLI has 25 top-level commands. Some are adopter-facing (`upgrade`,
  `worktree`, `task`, `review`), one is host-facing (`hook`), and one is
  labelled framework-internal (`generate-claude-md`). Nothing classifies the
  rest.
- Other surfaces an adopter's tooling or managed text depends on are versioned
  separately and are not tied to the release number:
  - 48 registered stop codes in `capabilities/stop-codes-v1.json`;
  - 7 JSON schemas in `schemas/`;
  - the manifest `protocolVersion` (currently 2);
  - capability markers and their migrations;
  - the `--format json` outputs of lifecycle commands.
- Five releases shipped between 2026-10-08 and 2026-10-14 (`1.2.11` to
  `1.2.15`). An adopter cannot tell from the number which of them need action.

An adopter who evaluates Meridian therefore cannot answer "what will break me
on the next release", which is the first question of public adoption.

## Decision

### 1. Classify every surface

Each surface belongs to exactly one tier. The classification is a rule, so it
can be checked, not a list that drifts:

| Tier | Rule | Compatibility |
|------|------|---------------|
| Stable | A CLI command, subcommand, or flag that managed workflow text or the README's adopter sections name; its exit status and `--format json` field names. Every registered stop code. Every published schema. The manifest and its `protocolVersion`. Capability-marker identities, managed paths, and the migration path between published releases. The names of the plugin's slash commands and skills. | Changes only as Decision 2 allows. |
| Host-facing | `meridian hook` and the hook and skill entry points that the host configuration invokes. | Stable toward the host configuration that Meridian itself installs. Adopters must not call it directly. |
| Experimental | A surface explicitly labelled experimental in `--help` and in the README, for example the console's interactive keys and agent launch, and `usage`. | May change in any minor release. The changelog names the change. |
| Internal | A surface labelled framework-internal (for example `generate-claude-md`), everything under `scripts/` except `bin/meridian`, `evals/`, and this repository's own `tasks/` and `docs/` records. | No compatibility promise. |

Human-readable text output is never stable. Tooling must use `--format json`.

### 2. Give the version number a meaning

From the first release after this ADR is accepted:

- **Patch**: fixes only. No migration (`baselineChanged: false`), and no new
  stable surface.
- **Minor**: additive stable surface, or a template-changing release whose
  migrations apply through `meridian upgrade --apply` with no adopter action
  beyond resolving conflicts in adapted managed text, or an experimental
  change.
- **Major**: any of the following:
  - removing or renaming a stable command, flag, or JSON field;
  - changing the meaning of an exit status or stop code;
  - removing a stop code;
  - an incompatible schema version;
  - a `protocolVersion` that an older CLI refuses;
  - narrowing the upgrade window of Decision 6;
  - any change that requires adopter action beyond `upgrade --apply`.

### 3. Deprecate before removing

A stable surface is deprecated in a minor release. That release lists it in
the changelog under `Deprecated`, and the CLI prints a warning on stderr when
the surface is used. It is removed only in the next major release, under
`Removed`. An experimental surface may be removed in a minor release and is
listed under `Changed`, marked experimental.

### 4. Enforce the meaning at release time

`scripts/release.py prepare` refuses a bump that is smaller than the release
requires, using facts it already has:

- **Patch** is refused when the release adds a migration or a fragment has an
  `Added`, `Deprecated`, or `Removed` subsection.
- **Minor** is refused when a fragment has a `Removed` subsection.
- `--version X.Y.Z` is checked the same way.

The check cannot prove that an `Added` bullet is additive or that a `Changed`
bullet is not breaking. Classifying a bullet remains the author's duty and the
reviewer's check.

### 5. State the status

Once Decisions 1–4 are implemented, the README replaces the "experimental"
status line with a link to the surface classification and the versioning
rules.

## Consequences

- An adopter can read the version difference and know whether the next
  release needs action, and tooling has a defined set of fields it may parse.
- Template-changing releases become minor releases, so minor numbers advance
  much faster than they do today. That is the intended signal.
- Removing an unwanted stable surface takes two releases and a major bump.
  The experimental tier is the escape hatch for surfaces still being shaped.
- The release check adds a gate to `release.py prepare` and nothing to the
  task lifecycle.
- Limitation: the tier of a new surface is decided when it is introduced. A
  surface that managed text names becomes stable as soon as it ships.

## Starting version

| Option | For | Against |
|--------|-----|---------|
| **A. Next minor, `1.3.0` (recommended)** | No breaking change is needed to declare stability. Existing pins and the upgrade window stay untouched. A `2.0.0` would announce a break that did not happen. | Earlier `1.x` releases did not follow these rules. The changelog must say from which release the promise holds. |
| B. `2.0.0` | A clean boundary: everything before `2.0.0` is read as pre-stable. | It signals a breaking change to every adopter. The upgrade window and its tests must cover a major boundary with no actual break. |

Decided on acceptance, 2026-10-14: option A. The stable line starts at
`1.3.0`.

## Rejected alternatives

| Alternative | Reason rejected |
|-------------|-----------------|
| Keep the "experimental" status and promise nothing | It contradicts the `1.x` number. Adopters cannot plan upgrades. |
| A hand-maintained list of stable commands | It drifts from the code and the managed text. A rule that names its sources can be checked. |
| Version each surface independently and make no release-level promise | Schemas and `protocolVersion` already do that. Adopters still need a single number to decide whether to move their pin. |
| Infer the bump from the diff | Breaking-change detection over Markdown templates and CLI behavior is not deterministic. The fragment headings and the ledger are. |

## Rollout Plan

1. Accepted on 2026-10-14; the starting version is `1.3.0`.
2. Task 210 publishes `docs/PUBLIC_SURFACE.md`, derived by the Decision 1
   rule, and labels experimental surfaces in `--help`. It also adds the
   Decision 4 check to `release.py`, the versioning and deprecation rules to
   `CONTRIBUTING.md`, and the README status line. CLI-only; it ships in the
   starting release.
3. The first release after task 210 is `1.3.0`, and its changelog
   states that the promise holds from that release forward.

## Out of Scope

This ADR does not:

- change the support policy, the upgrade window, or backport rules
  (`docs/DISTRIBUTION_AND_UPDATE_DESIGN.md`, Decision 6);
- decide which files the distributed tree contains;
- submit Meridian to any marketplace directory or package index;
- add a Codex plugin channel;
- set a release cadence.
