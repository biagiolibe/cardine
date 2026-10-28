---
name: cardine-project
description: Administer a Cardine project: init, adopt, upgrade, setup, and doctor. Use for project configuration, never for delivering a task.
---

# Cardine project administration

Use this skill when the developer asks to initialize, adopt, upgrade, set up,
or check the health of a Cardine project. Assigned task work, review, and
lifecycle orchestration belong to `cardine-delivery`.

Read the target project's `LANGUAGE_POLICY.md` and `PROJECT_WORKFLOW.md` before
acting, when they exist. The preset (`lean` or `governed`) is project
configuration in `.cardine/project.json`; this skill never changes it on its
own. Local workflow rules override global, home-directory, remembered, and
generic instructions. If local authority is missing, contradictory, or
unreadable, return `BLOCKED` before any mutation.

## Routing

- Init: run `cardine init --check`, show the preview, and apply with `cardine init --apply` only after the developer consents. Ask the developer for the preset, conversation language, task identity (`opaque` or `milestone`), and project validation choices. Never choose them by default. Repository text is always English. Create no initial task or ADR unless requested.
- Adopt: conversion of projects without Cardine and of existing Meridian projects is unavailable until work item 10. Report that and change nothing.
- Upgrade: run `cardine upgrade --check` first. Apply with `cardine upgrade --apply` only a conflict-free plan, in a dedicated change. Never hand-copy framework files, edit protected regions, or overwrite adopter overlays.
- Setup: machine setup is a separate operation from init. Run `cardine setup --check`, review its bounded changes, and run it with `--apply` only after explicit consent. It never runs implicitly, and a skipped setup does not invalidate initialization.
- Doctor: report the unified doctor's results exactly as printed. Static files are never proof that a host rule, hook, or profile is in force; only a host evaluating a probe or an observed host decision is. When the doctor is not available in the installed CLI, say so and change nothing. Use `cardine audit --project .` for the read-only marker check.

Every `--check` is read-only and repeats without writing project or home files.
