---
description: "Bootstrap a new project with the Cardine CLI"
---

Initialize a new project through `${CLAUDE_PLUGIN_ROOT}/bin/cardine init`.
Both presets install exactly the same files from `templates/single/`; the preset
only chooses project defaults. The CLI owns rendering, configuration, initial
views, and the upgrade manifest and baselines. Do not copy templates, replace
placeholders, write `.cardine/project.json`, or run `cardine lock` manually.
The CLI includes hidden files `.gitignore`, `.claudeignore`, `.codex/hooks.json`,
and `.codex/rules/meridian.rules`. Do not copy from `templates/base/` or `templates/workflows/`.
Report existing conflicting paths instead of overwriting user files.

## Steps

1. Ask for the **project path**, **project name**, and lowercase **project slug**.

2. Ask for a **preset**, offering `lean` as the default when the user has no preference:
   - `lean` — task review is not required; authority and expected code surface are optional.
   - `governed` — task review, authority, and expected code surface are required.
   Each task can override these defaults in either direction.

3. Ask for the **task-identity mode**, without choosing a default:
   - `opaque` — project-defined labels, compatible with existing IDs.
   - `milestone` — new IDs use `M<milestone>-<WORKSTREAM>-<ordinal>`.

4. Ask for literal **validation commands**, their stable IDs, the baseline,
   and commands for each candidate outcome (`REUSE`, `BOUNDED`, `FULL`).
   Do not invent commands. Save the agreed validation object in a temporary JSON
   file outside the target project and pass its path as `--validation`:

   ```json
   {
     "commands": { "<id>": "<literal command>" },
     "baseline": ["<id>"],
     "candidate": { "REUSE": ["<id>"], "BOUNDED": ["<id>"], "FULL": ["<id>"] }
   }
   ```

   Every outcome is required. Empty maps and lists must be explicit user choices.

5. Ask for the **conversation language**. It persists across sessions; a prompt
   in another language does not change it. All committed repository text must
   always be English.

6. Substitute and shell-quote the agreed values in this read-only preview:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/cardine" init --project "<project path>" --check --name "<project name>" --slug "<project slug>" --preset "<lean|governed>" --language "<conversation language>" --task-identity "<opaque|milestone>" --validation "<validation JSON path>"
   ```

   Inspect the plan and conflicts. Repeating `--check` must not write anything.
   After the user accepts the preview, run the same inputs with `--apply`:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/cardine" init --project "<project path>" --apply --name "<project name>" --slug "<project slug>" --preset "<lean|governed>" --language "<conversation language>" --task-identity "<opaque|milestone>" --validation "<validation JSON path>"
   ```

   On interruption, rerun with identical inputs; do not manually repair outputs.

7. Offer once-per-machine host setup as a separate operation. Show its read-only plan first:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/cardine" setup --check --project "<project path>"
   ```

   Run `cardine setup --apply` only after explicit confirmation, using the same
   project path. A decline, missing permission, or unavailable user configuration
   layer does not invalidate initialization. Report the exact check and apply
   commands for later use. Never edit host configuration implicitly or infer
   effective enforcement from policy text; use a host probe or observed decision.

8. Confirm the project name and preset. Direct the user to fill in
   `TECH_DESIGN.md` and plan their first features in `PROJECT_PLAN.md`.
