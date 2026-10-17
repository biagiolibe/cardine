---
description: "Check or apply a deterministic Meridian framework upgrade"
---

Upgrade a project initialized by Meridian without overwriting local workflow
customizations.

Run the CLI from this plugin source. First inspect the plan:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/meridian upgrade --project . --check
```

If this is a project created before framework locking, use a packaged baseline
to preview adoption first (`--mode` and `--from` are detected automatically
when unambiguous):

```bash
${CLAUDE_PLUGIN_ROOT}/bin/meridian adopt --project . --check
```

Run the same command with `--apply` only after a conflict-free plan and explicit
developer authorization. The CLI refuses to infer an unrecorded baseline.

When the generic plan conflicts because the project has an intentional local
workflow adaptation, use `/meridian-adopt` instead. It detects which framework
capabilities are already present, scopes an agent migration to only the missing
ones, and finalizes the lockfile after an independent review.

If the plan has no `CONFLICT` entries and the developer authorizes the update,
apply it:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/meridian upgrade --project . --apply
```

The CLI uses `.meridian/manifest.json` and installed baseline snapshots for a
three-way merge. It applies no files when any managed-file conflict exists.
After a successful apply, inspect the diff, run the project's baseline checks,
and create a dedicated framework-upgrade commit. Never resolve conflict markers
or edit `.meridian/` baselines automatically; report `BLOCKED` with the exact
paths instead.

When `docs/workflows/ENTRY_ROUTER.md` exists, `AGENTS.md` and `CLAUDE.md` are
derived outputs rather than three-way-merge inputs. The plan reports them as
`ROUTER`. If a pending `command-triggers` migration introduces a command that
the router does not expose, add that command to the route line that already
names its target document; do not add a second line for the same target. Apply
remains blocked until the canonical router covers every required command. A
successful apply regenerates both entry points and runs the entry-router audit
before recording their generated hashes in the manifest.

For a project customized enough that the automatic merge will conflict on
every future upgrade — not a one-off conflict to resolve, but a structural
mismatch (for example, an entirely rewritten `AGENTS.md`/`CLAUDE.md`) — manually
reconcile each conflicting file's content with the target version's intent,
preserving the project's own structure and terminology, then register the
result without touching any file automatically:

```bash
${CLAUDE_PLUGIN_ROOT}/bin/meridian upgrade --project . --apply --owner-reconciled
```

This registers the new manifest and baseline but writes nothing to the
project's managed files — it trusts that the developer already reconciled
every one of them by hand. Use it only after that manual reconciliation, never
as a way to skip doing it.

In an entry-router project, `--owner-reconciled` does not waive a missing
router trigger. Reconcile the canonical router first; generated entry points
are then regenerated even though ordinary managed-file changes remain skipped.
