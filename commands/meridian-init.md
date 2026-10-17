---
description: "Bootstrap a new project with the Meridian workflow"
---

Initialize a new project with the Meridian agentic development methodology.

The Meridian template source is at: `${CLAUDE_PLUGIN_ROOT}`

## Steps

1. Ask the user for the **project name** (will replace `[Project Name]` placeholders).

2. Ask the user to choose a **workflow mode**:
   - `lean-delivery` — a complete lightweight workflow for small projects, POCs, demos, experiments, and reversible low-risk changes.
   - `governed-sdd` — ADRs, dependency gates, review policy, task worktrees, and reviewer-led integration.

   Accept `classic` only as a backwards-compatible alias for `lean-delivery`.
   Persist and report the canonical name `lean-delivery`.

3. Ask the user to choose a **task-identity mode**:
   - `opaque` — task IDs remain project-defined labels; this is compatible with existing IDs.
   - `milestone` — new task IDs use `M<milestone>-<WORKSTREAM>-<ordinal>`.

   Do not choose a default for the user. Explain that the choice is recorded in
   `.meridian/task-identity.json` and can be changed later by editing that file.

4. Ask the user to choose a **conversation language**. This preference controls every message from the agent and persists across sessions. Do not infer a language change from a prompt written in another language.

   The repository language is always English and is not configurable: all committed documentation, source code, comments, identifiers, user-facing strings, tests, configuration text, and commit messages must be in English.

5. Copy the following files from the template source to the current working directory:
   - From `templates/base/PROJECT_PLAN.md` → `PROJECT_PLAN.md`
   - From `templates/base/tasks/TASK_BLUEPRINT.md` → `tasks/TASK_BLUEPRINT.md`
   - From `templates/base/tasks/QUEUE.md` → `tasks/QUEUE.md`
   - From `templates/base/TECH_DESIGN.md` → `TECH_DESIGN.md`
   - From `templates/base/CLAUDE.md` → `CLAUDE.md`
   - From `templates/base/LANGUAGE_POLICY.md` → `LANGUAGE_POLICY.md`
   - From `templates/base/README.md` → `README.md` (skip if a `README.md` already exists — merge the "Repository & Claude Code Configuration" section into it instead)
   - From `templates/base/.gitignore` → `.gitignore` (merge with an existing `.gitignore` instead of overwriting)
   - From `templates/base/.claudeignore` → `.claudeignore` (merge with an existing `.claudeignore` instead of overwriting)

6. Overlay the files for the selected workflow after copying the base templates:
   - For `lean-delivery`:
     - `templates/workflows/lean-delivery/PROJECT_WORKFLOW.md` → `PROJECT_WORKFLOW.md`
     - `templates/workflows/lean-delivery/AGENTS.md` → `AGENTS.md`
     - `templates/workflows/lean-delivery/CLAUDE.md` → `CLAUDE.md`
     - `templates/workflows/lean-delivery/LANGUAGE_POLICY.md` → `LANGUAGE_POLICY.md`
     - `templates/workflows/lean-delivery/docs/` → `docs/`
     - `templates/workflows/lean-delivery/.codex/` → `.codex/`
   - For `governed-sdd`:
     - `templates/workflows/governed-sdd/PROJECT_WORKFLOW.md` → `PROJECT_WORKFLOW.md`
     - `templates/workflows/governed-sdd/AGENTS.md` → `AGENTS.md`
     - `templates/workflows/governed-sdd/CLAUDE.md` → `CLAUDE.md`
     - `templates/workflows/governed-sdd/LANGUAGE_POLICY.md` → `LANGUAGE_POLICY.md`
     - `templates/workflows/governed-sdd/tasks/TASK_BLUEPRINT.md` → `tasks/TASK_BLUEPRINT.md`
     - `templates/workflows/governed-sdd/tasks/QUEUE.md` → `tasks/QUEUE.md`
     - `templates/workflows/governed-sdd/docs/` → `docs/`
     - `templates/workflows/governed-sdd/.codex/` → `.codex/`
   Do not overwrite an existing workflow document without showing its diff and receiving explicit confirmation.

7. Replace all occurrences of `[Project Name]` in the copied files with the actual project name provided in step 1.

8. Replace all occurrences of `[Data]` with today's date in ISO format (YYYY-MM-DD).

9. Create the `tasks/done/` directory (empty, for archiving completed tasks) only in `lean-delivery` mode. Governed SDD retains accepted task files as causal project records.

10. Replace `[Conversation language]` in `LANGUAGE_POLICY.md` with the choice from step 4. In `CLAUDE.md`, fill in the `## Commands` block with the project's actual run/test/lint/format commands, and the `## Conventions` block with any language/stack-specific rules (ask the user, or infer from `TECH_DESIGN.md` once it is filled in). Do not weaken or duplicate the mandatory repository-language rule from `LANGUAGE_POLICY.md`.

11. In `README.md`, fill in the "Toolchain" bullet with the pinned language/runtime version and key dependencies, and the "Claude Code — session settings" bullets with the model, advisor, and effort level currently in use for this session (ask the user via `/model`, `/advisor`, `/effort` output if not already known from context).

12. Register the initialized workflow for deterministic framework upgrades:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/bin/meridian lock --project . --mode <workflow-mode>
   ```

   This writes `.meridian/manifest.json` and an installed-template baseline.
   Do not edit the manifest or baseline snapshots manually.

13. Print the once-per-machine setup instruction. Show the read-only plan
    first:

    ```bash
    ${CLAUDE_PLUGIN_ROOT}/bin/meridian setup --check --task-identity <opaque|milestone>
    ```

    Run `meridian setup --apply` only after explicit confirmation, using
    `--task-identity <chosen-mode>` for this initialization. A decline,
    unavailable user configuration layer, or missing permission does not invalidate initialization.
    Claude Code needs no host setup. Report the
    exact check and apply commands so the user can run them later. Never edit
    user or Codex configuration implicitly.

14. Confirm to the user: "Meridian initialized for **[Project Name]** with workflow `<workflow-mode>`. Next steps:
   - Fill in `TECH_DESIGN.md` with your actual stack details.
   - Add your first features to `PROJECT_PLAN.md`.
   - Run `/meridian-task` when you're ready to delegate the first task."
