---
description: "Register a Cardine task through the existing task protocol"
---

Create only the task the user requests. Do not select another queue item.

## Workflow-mode gate

Read `PROJECT_WORKFLOW.md`, the local `AGENTS.md` or `CLAUDE.md`, and
`LANGUAGE_POLICY.md` before taking action. Follow the project's local rules.
A legacy `GOVERNED_SDD` or `LEAN_DELIVERY` mode lock is not the single Cardine
lifecycle: return `BLOCKED` without changing repository state and report that
conversion returns with work item 10. Missing or contradictory workflow
instructions also return `BLOCKED`; do not infer a lifecycle from global rules.

For a Cardine project, read `.cardine/project.json`. The `lean` and `governed`
presets supply defaults; task options may override them. Do not impose a
separate lifecycle based on the preset.

## Steps

1. Resolve the configured task roots and queue location:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/cardine" locations --project .
   ```

2. Read `taskIdentity.mode` in `.cardine/project.json`. In `opaque` mode, ask
   the user for a unique ID consistent with the project's naming convention.
   In `milestone` mode, ask for a positive milestone number and canonical
   uppercase workstream, then run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/cardine" task identity next --project . --milestone "<milestone>" --workstream "<workstream>" --format json
   ```

   Show the returned canonical ID and `task_path` and get confirmation. Use
   those values verbatim; never guess an ordinal. Stop on a command error.

3. Gather the title, category, priority, objective, measurable acceptance
   criteria, dependencies, and literal validation commands. Read the project's
   `tasks/TASK_BLUEPRINT.md` and applicable local requirements. Resolve review,
   authority and expected code surface from the project defaults and explicit
   task choices. A quick task still needs objective, criteria, validation and
   dependencies. All repository artifacts must be English.

4. Prepare the complete proposed UTF-8 record in a temporary file outside the
   project. The CLI owns registration of the record and queued state; do not
   write `.cardine/tasks/` or install a task record manually. Substitute and
   shell-quote the agreed inputs:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/cardine" task new "<task ID>" --project . --record "<proposed record path>" --format json
   ```

   Use `--quick` only for a quick task. If interrupted, inspect the reported
   operation and use the same inputs with `--recover` when the CLI requests
   it. Do not repair journal or state files manually or overwrite user files.

5. Regenerate the configured queue and plan views from state:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/cardine" status --project . --write
   ```

   Do not add checkbox status or queue rows by hand, archive a new record, or
   overwrite adopter overlays. Confirm the registered ID and record path in
   the persisted conversation language. Task execution remains a separate
   `Proceed with <TASK-ID>` instruction through the project's local workflow.
