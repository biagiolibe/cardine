---
description: "Bootstrap a new project with the Meridian workflow"
---

Initialize a new project with the Meridian agentic development methodology.

The Meridian template source is at: `${CLAUDE_PLUGIN_ROOT}`

Both presets install exactly the same files from `templates/single/`. The preset
only chooses the defaults that `.cardine/project.json` records.

## Steps

1. Ask the user for the **project name** (will replace `[Project Name]` placeholders) and derive a lowercase **project slug** from it.

2. Ask the user to choose a **preset**, offering `lean` as the default when they have no preference:
   - `lean` — task review is not required, and authority and expected code surface are optional.
   - `governed` — task review is required, and authority and expected code surface are required.

   Both presets run the same lifecycle and install the same documents. Each task can still override review, authority, and expected code surface in either direction.

3. Ask the user to choose a **task-identity mode**:
   - `opaque` — task IDs remain project-defined labels; this is compatible with existing IDs.
   - `milestone` — new task IDs use `M<milestone>-<WORKSTREAM>-<ordinal>`.

   Do not choose a default for the user. Explain that the choice is recorded in `.cardine/project.json` and applies to new tasks.

4. Ask the user for the **validation commands**: the literal commands that prove the project is healthy (for example its test, lint, and build commands), each with a stable ID. Ask which of them form the baseline that every task runs, and which run for each candidate outcome (`REUSE`, `BOUNDED`, `FULL`). Do not invent commands; a task cannot execute until the owner has chosen them.

5. Ask the user to choose a **conversation language**. This preference controls every message from the agent and persists across sessions. Do not infer a language change from a prompt written in another language.

   The repository language is always English and is not configurable: all committed documentation, source code, comments, identifiers, user-facing strings, tests, configuration text, and commit messages must be in English.

6. Copy every file of `templates/single/` to the current working directory, preserving its relative path, including the hidden files `.gitignore`, `.claudeignore`, `.codex/hooks.json`, and `.codex/rules/meridian.rules`:
   - `README.md` — skip if a `README.md` already exists; merge the "Repository & Claude Code Configuration" section into it instead.
   - `.gitignore` and `.claudeignore` — merge with an existing file instead of overwriting.
   - `PROJECT_PLAN.md`, `TECH_DESIGN.md`, `tasks/QUEUE.md`, `CLAUDE.md`, `AGENTS.md`, `LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, `tasks/TASK_BLUEPRINT.md`, `docs/`, and `.codex/` — copy as they are.

   Do not copy from `templates/base/` or `templates/workflows/`. Do not overwrite an existing workflow document without showing its diff and receiving explicit confirmation.

7. Write `.cardine/project.json`, which `schemas/project-v1.schema.json` validates:

   ```json
   {
     "version": 1,
     "project": { "name": "<project name>", "slug": "<project slug>" },
     "preset": "<lean|governed>",
     "taskIdentity": { "mode": "<opaque|milestone>" },
     "validation": {
       "commands": { "<id>": "<literal command>" },
       "baseline": ["<id>"],
       "candidate": { "REUSE": ["<id>"], "BOUNDED": ["<id>"], "FULL": ["<id>"] }
     },
     "ci": "none"
   }
   ```

   Use the answers from steps 1 to 4. Add `taskDefaults` only when the user wants defaults that differ from the preset. Every candidate outcome is required; an empty list is an explicit choice, never an omission.

8. Replace all occurrences of `[Project Name]` in the copied files with the actual project name provided in step 1.

9. Replace all occurrences of `[Data]` with today's date in ISO format (YYYY-MM-DD).

10. Create the `tasks/done/` directory (empty, for archiving completed tasks).

11. Replace `[Conversation language]` in `LANGUAGE_POLICY.md` with the choice from step 5. In `CLAUDE.md`, fill in the `## Commands` block with the project's actual run/test/lint/format commands, and add a `## Conventions` block with any language/stack-specific rules (ask the user, or infer from `TECH_DESIGN.md` once it is filled in). Do not weaken or duplicate the mandatory repository-language rule from `LANGUAGE_POLICY.md`.

12. In `README.md`, fill in the "Toolchain" bullet with the pinned language/runtime version and key dependencies, and the "Claude Code — session settings" bullets with the model, advisor, and effort level currently in use for this session (ask the user via `/model`, `/advisor`, `/effort` output if not already known from context).

13. Register the initialized single distribution for deterministic framework upgrades. Both presets use the same lock:

    ```bash
    ${CLAUDE_PLUGIN_ROOT}/bin/cardine lock --project . --mode single
    ```

    This writes `.cardine/manifest.json` and an installed-template baseline.
    Do not edit the manifest or baseline snapshots manually.

14. Print the once-per-machine setup instruction. Show the read-only plan
    first:

    ```bash
    ${CLAUDE_PLUGIN_ROOT}/bin/cardine setup --check
    ```

    Run `cardine setup --apply` only after explicit confirmation. A decline,
    unavailable user configuration layer, or missing permission does not invalidate initialization.
    Claude Code needs no host setup. Report the
    exact check and apply commands so the user can run them later. Never edit
    user or Codex configuration implicitly.

15. Confirm to the user: "Meridian initialized for **[Project Name]** with preset `<preset>`. Next steps:
   - Fill in `TECH_DESIGN.md` with your actual stack details.
   - Add your first features to `PROJECT_PLAN.md`.
   - Run `/meridian-task` when you're ready to delegate the first task."
