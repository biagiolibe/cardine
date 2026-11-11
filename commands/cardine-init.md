---
description: "Bootstrap a new project with the Cardine CLI"
---

Initialize a new project through `cardine init`.
Both presets install exactly the same files from `templates/single/`; the preset
only chooses project defaults. The CLI owns rendering, configuration, initial
views, and the upgrade manifest and baselines. Do not copy templates, replace
placeholders, write `.cardine/project.json`, or run `cardine lock` manually.
The CLI includes hidden files `.gitignore`, `.claudeignore`,
and `.codex/rules/cardine.rules`.
Report existing conflicting paths instead of overwriting user files.

## Steps

1. Run the read-only preview and show every `choice:` line with its source:

   ```bash
   cardine init --project "<project path>" --check
   ```

   The preview chooses initialization or adoption on its own. Ask the developer
   to confirm or change each choice. When it reports `missing: validation`, ask
   for the project's test command; never invent one. Repeating `--check` writes
   nothing.

2. Substitute and shell-quote the confirmed values as explicit flags:

   ```bash
   cardine init --project "<project path>" --apply --name "<project name>" --slug "<project slug>" --preset "<lean|governed>" --language "<conversation language>" --task-identity "<opaque|milestone>" --test "<test command>"
   ```

   For several validation commands, pass `--validation <JSON file>` in place of
   `--test`; see `cardine init --help`. On interruption, rerun with identical
   inputs. All committed repository text must always be English.

3. With `--apply` and no terminal, `cardine init` neither commits nor pushes.
   Show the diff, then commit and push the configuration on `main` after the
   developer approves it.

4. Offer once-per-machine host setup as a separate operation. Show its read-only plan first:

   ```bash
   cardine setup --check --project "<project path>"
   ```

   Run `cardine setup --apply` only after explicit confirmation, using the same
   project path. A decline, missing permission, or unavailable user configuration
   layer does not invalidate initialization. Report the exact check and apply
   commands for later use. Never edit host configuration implicitly or infer
   effective enforcement from policy text; use a host probe or observed decision.

5. Confirm the project name and preset. Direct the user to create the first
   task with `/cardine-task`, which registers it through `cardine task new`.
