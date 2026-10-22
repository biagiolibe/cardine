# Public surface and stability

The compatibility promise starts at **1.3.0**. The governing decisions are in
[Public Surface and Stability](ADR_PUBLIC_SURFACE_AND_STABILITY.md); release
and deprecation rules are in [CONTRIBUTING.md](../CONTRIBUTING.md#versioning-and-deprecation).

## Classification rule

- **Stable**: commands, subcommands and flags named by distributed managed
  workflow text (under `templates/`, `commands/` and `skills/`) or the README's
  adopter sections, together with their exit statuses and JSON field names.
  Container commands inherit the tier needed to reach their stable children.
- **Host-facing**: `hook` and the hook and skill entry points invoked by the
  host configuration. These are stable toward the configuration Cardine
  installs; adopters must not invoke them directly.
- **Experimental**: explicitly labelled in CLI help and the README. The console
  (including interactive keys and agent launch) and local session usage reports
  may change in any minor release; the changelog names each change.
- **Internal**: framework implementation and maintenance helpers labelled
  framework-internal in CLI help, plus everything under `scripts/` (the public
  CLI entry point is `bin/cardine`), `evals/`, and this repository's own task
  and documentation records. There is no compatibility promise.

A surface named by managed workflow text becomes stable when it ships. The
inventory below applies that rule to the current parser; internal helpers are
not promoted merely by being mentioned in this repository's maintenance docs.
Human-readable output is never stable. Tooling must use `--format json`.
The test suite checks the inventory recursively against the actual CLI parser,
including command containers and nested subcommands.

## CLI inventory

| Command | Tier |
|---------|------|
| `cardine self-check` | Stable |
| `cardine self-update` | Experimental |
| `cardine console` | Experimental |
| `cardine lock` | Stable |
| `cardine upgrade` | Stable |
| `cardine audit` | Stable |
| `cardine status` | Stable |
| `cardine locations` | Stable |
| `cardine project` | Stable |
| `cardine setup` | Stable |
| `cardine codex` | Stable |
| `cardine codex configure` | Stable |
| `cardine codex worktree-path` | Stable |
| `cardine codex doctor` | Stable |
| `cardine worktree` | Stable |
| `cardine worktree path` | Stable |
| `cardine worktree prepare` | Stable |
| `cardine worktree check` | Stable |
| `cardine worktree repair-base` | Stable |
| `cardine worktree active` | Internal |
| `cardine worktree states` | Internal |
| `cardine worktree evidence` | Internal |
| `cardine worktree closure-status` | Internal |
| `cardine worktree advance` | Stable |
| `cardine worktree integrate` | Stable |
| `cardine worktree integrate stage` | Stable |
| `cardine worktree integrate finalize` | Stable |
| `cardine worktree integrate abort` | Stable |
| `cardine worktree cleanup` | Stable |
| `cardine validation` | Internal |
| `cardine validation check` | Internal |
| `cardine review` | Stable |
| `cardine review verdict` | Stable |
| `cardine task` | Stable |
| `cardine task transition` | Stable |
| `cardine task outcome` | Stable |
| `cardine task close` | Stable |
| `cardine task state` | Stable |
| `cardine task state import` | Stable |
| `cardine task identity` | Stable |
| `cardine task identity check` | Internal |
| `cardine task identity next` | Stable |
| `cardine adr` | Stable |
| `cardine adr show` | Stable |
| `cardine adr list` | Stable |
| `cardine context` | Stable |
| `cardine context authority` | Stable |
| `cardine context size` | Stable |
| `cardine usage` | Experimental |
| `cardine usage report` | Experimental |
| `cardine execution` | Stable |
| `cardine execution start` | Stable |
| `cardine execution deliver` | Stable |
| `cardine execution preflight` | Stable |
| `cardine execution contract` | Stable |
| `cardine execution reconcile` | Stable |
| `cardine execution handoff-check` | Stable |
| `cardine execution ready-check` | Stable |
| `cardine execution validate` | Stable |
| `cardine execution evidence` | Stable |
| `cardine execution investigate` | Stable |
| `cardine hook` | Host-facing |
| `cardine hook read-guard` | Host-facing |
| `cardine hook stop-audit` | Host-facing |

## Stable registries and identities

The following also belong to the stable surface:

- Every registered stop code in [stop-codes-v1.json](../capabilities/stop-codes-v1.json),
  including its meaning and exit-status semantics.
- Every published JSON schema under [schemas/](../schemas/), including the
  capability-catalog, manifest, project-declaration, stop-code, retired-text,
  task-state, and validation-evidence contracts. Incompatible schema versions require a major release.
- The manifest and its `protocolVersion`. A protocol version that an older CLI
  refuses requires a major release.
- Capability-marker identities and managed paths, and the migration path
  between published releases. See [the capability catalog](../capabilities/catalog-v1.json).
- Plugin slash-command names in [commands/](../commands/) and skill names in
  [skills/](../skills/). Skill names are stable adopter identities; host-invoked
  skill entry points additionally have the Host-facing compatibility contract.

Registry membership is defined by these published files, rather than a copied
list of entries. Changes follow the versioning and deprecation rules above.

## Project conversion

Conversion of projects without Cardine and of existing installations returns with work item 10, using the single Cardine workflow. Until then, the CLI provides no conversion command.

Maintainer commands live under `python3 scripts/dev.py`: `profile`, `report flow`,
`generate-entry-routers`, and `agent-evals`. They are internal development
interfaces and have no compatibility promise. The generator's `--template` option
selects the single template set's shared body; without it, `--project` selects consumer routers.
