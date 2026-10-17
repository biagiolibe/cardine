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
  host configuration. These are stable toward the configuration Meridian
  installs; adopters must not invoke them directly.
- **Experimental**: explicitly labelled in CLI help and the README. The console
  (including interactive keys and agent launch) and local session usage reports
  may change in any minor release; the changelog names each change.
- **Internal**: framework implementation and maintenance helpers labelled
  framework-internal in CLI help, plus everything under `scripts/` (the public
  CLI entry point is `bin/meridian`), `evals/`, and this repository's own task
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
| `meridian self-check` | Stable |
| `meridian self-update` | Experimental |
| `meridian console` | Experimental |
| `meridian lock` | Stable |
| `meridian upgrade` | Stable |
| `meridian adopt` | Stable |
| `meridian finalize-adoption` | Stable |
| `meridian audit` | Stable |
| `meridian profile` | Internal |
| `meridian profile doctor` | Internal |
| `meridian profile bootstrap` | Internal |
| `meridian locations` | Stable |
| `meridian project` | Stable |
| `meridian setup` | Stable |
| `meridian codex` | Stable |
| `meridian codex configure` | Stable |
| `meridian codex worktree-path` | Stable |
| `meridian codex doctor` | Stable |
| `meridian worktree` | Stable |
| `meridian worktree path` | Stable |
| `meridian worktree prepare` | Stable |
| `meridian worktree check` | Stable |
| `meridian worktree repair-base` | Stable |
| `meridian worktree active` | Internal |
| `meridian worktree states` | Internal |
| `meridian worktree evidence` | Internal |
| `meridian worktree closure-status` | Internal |
| `meridian worktree advance` | Stable |
| `meridian worktree integrate` | Stable |
| `meridian worktree integrate stage` | Stable |
| `meridian worktree integrate finalize` | Stable |
| `meridian worktree integrate abort` | Stable |
| `meridian worktree cleanup` | Stable |
| `meridian validation` | Internal |
| `meridian validation check` | Internal |
| `meridian review` | Stable |
| `meridian review verdict` | Stable |
| `meridian task` | Stable |
| `meridian task transition` | Stable |
| `meridian task close` | Stable |
| `meridian task state` | Stable |
| `meridian task state import` | Stable |
| `meridian task identity` | Stable |
| `meridian task identity check` | Internal |
| `meridian task identity next` | Stable |
| `meridian adr` | Stable |
| `meridian adr show` | Stable |
| `meridian adr list` | Stable |
| `meridian context` | Stable |
| `meridian context authority` | Stable |
| `meridian context size` | Stable |
| `meridian usage` | Experimental |
| `meridian usage report` | Experimental |
| `meridian report` | Internal |
| `meridian report flow` | Internal |
| `meridian budget` | Internal |
| `meridian budget show` | Internal |
| `meridian budget spend` | Internal |
| `meridian execution` | Stable |
| `meridian execution start` | Stable |
| `meridian execution deliver` | Stable |
| `meridian execution preflight` | Stable |
| `meridian execution contract` | Stable |
| `meridian execution reconcile` | Stable |
| `meridian execution handoff-check` | Stable |
| `meridian execution ready-check` | Stable |
| `meridian execution validate` | Stable |
| `meridian execution evidence` | Stable |
| `meridian execution investigate` | Stable |
| `meridian generate-claude-md` | Internal |
| `meridian generate-entry-routers` | Internal |
| `meridian hook` | Host-facing |
| `meridian hook read-guard` | Host-facing |
| `meridian hook stop-audit` | Host-facing |

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
  between published releases. See [CAPABILITY_MARKERS.md](../migrations/CAPABILITY_MARKERS.md)
  and [the capability catalog](../capabilities/catalog-v1.json).
- Plugin slash-command names in [commands/](../commands/) and skill names in
  [skills/](../skills/). Skill names are stable adopter identities; host-invoked
  skill entry points additionally have the Host-facing compatibility contract.

Registry membership is defined by these published files, rather than a copied
list of entries. Changes follow the versioning and deprecation rules above.
