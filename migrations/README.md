# Framework Migrations

The chain is empty. Cardine 1.0 starts with no migration records; the records
Meridian accumulated before 1.0 were deleted with the history they described.
Until 1.0, template changes follow the no-migration rule in
[CONTRIBUTING.md](../CONTRIBUTING.md#managed-copies-of-this-repository). An
empty chain is valid: the upgrade CLI applies nothing, and a release that
changes no template is a CLI-only release.

A record is added only when a published release changes managed templates.
Records are named `NNN-slug.json`, numbered contiguously from `001`. Each
JSON record describes one released workflow transition. The framework
upgrade CLI uses the records to determine which migrations a project has
received and uses the installed baseline plus the target templates to perform
their managed-file transformation deterministically.

A migration record must declare a stable `id`, contiguous `from` and `to`
versions, a concise description, its managed paths, and post-upgrade
verification. It must be append-only after release. Do not replace a migration
to rewrite historical behavior; add a corrective migration instead.

The records do not authorize an overwrite. `meridian upgrade --apply` first
plans a three-way merge for every managed file and applies nothing if any file
conflicts.

A migration may declare `adoptExistingPaths` as a list containing a subset of
its normalized relative `managedPaths`. This is an explicit exception for a
framework-owned file that becomes managed for the first time after consumers
may already have received a copy. When the installed baseline lacks a declared
path, upgrade keeps an existing copy that already matches the target. If the
copy differs, the plan reports that it will be replaced and names the adjacent
backup written first: `<filename>.meridian-pre-adoption.bak`, followed by `.1`,
`.2`, and so on when earlier backups exist. The apply output repeats that plan.
Either case records the target baseline so later upgrades return to the normal
three-way merge. An undeclared path retains the blocking missing-baseline
conflict, and a declared path with no local copy remains an ordinary `ADD`.

A migration record declares `capability` and `capabilityVersion` when it
introduces or changes a rule the framework tracks and verifies by behavior
rather than by file hash — required whenever the migration modifies
already-tracked capability text, not just when adding one; a migration with
neither field is never checked for that capability's presence.
Presence-only, phrase-based detection stops working once a project's wording
diverges from the template, so the marker catalog in
[capabilities/](../capabilities/) is the source of truth. A version-bump
migration also declares a `delta` describing only what changed, so an
implementer's job stays scoped instead of implying a from-scratch rewrite.
`meridian audit` mechanically verifies a project's protected capability
regions still match the framework's released text.

A migration may declare `restructures`, a list of `{path, retiredMarkers,
replacedBy}` entries, when a standalone block replaces inline markers that sit
inside prose. Unlike `removes`, the scope is one managed path, so a capability
that another file still carries stays required. When a three-way merge of that
path conflicts around a retired inline marker, upgrade writes the current file
to an adjacent `<filename>.meridian-pre-restructure.bak` (numeric suffix when the
name exists), installs the template, carries the project's own level-2 sections
after it, and reports the backup.

A migration may declare `wraps`, a list of `{path, capability, capabilityVersion}`
entries, when a new block wraps text the file already carried unmarked. If the
three-way merge conflicts and the local file lacks the block, the plan reports a
conflict instead of adding a second copy of the wrapped text.

`.meridian/baselines/<version>/` in a generated project is a snapshot of the
templates installed at that version — the merge base for the next upgrade's
three-way merge. Only the snapshot matching the manifest's current
`workflowBaselineVersion` is ever read again, so a completed `upgrade --apply`
prunes every other baseline snapshot automatically.
Do not rely on an old snapshot surviving past its upgrade; keep a Git tag or
branch instead if a project needs to inspect a historical baseline.

## Removed packaged legacy baselines

Task 034 removed `release-baselines/1.0.0/` and historical-version adoption
from Cardine. The immutable Governed SDD snapshot remains in
[Meridian v1.4.0](https://github.com/biagiolibe/meridian/tree/v1.4.0/release-baselines/1.0.0),
the version from which Cardine was imported. Conversion of projects without
Cardine and of existing Meridian projects returns with work item 10 on the
single Cardine workflow. Until then, the CLI has no conversion command.
