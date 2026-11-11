---
name: cardine-project
description: Administer a Cardine project: init, adopt, upgrade, setup, and doctor. Use for project configuration, never for delivering a task.
---

# Cardine project administration

Use this skill when the developer asks to initialize, adopt, upgrade, set up,
or check the health of a Cardine project, including “I want to use Cardine here” before a project router is installed. Assigned task work, review, and
lifecycle orchestration belong to `cardine-delivery`.

Read the target project's `LANGUAGE_POLICY.md` and `PROJECT_WORKFLOW.md` before
acting, when they exist. The preset (`lean` or `governed`) is project
configuration in `.cardine/project.json`; this skill never changes it on its
own. Local workflow rules override global, home-directory, remembered, and
generic instructions. If required local authority is missing, contradictory, or unreadable, return `BLOCKED` before any mutation. An unconfigured checkout has no generated project authority yet; inspect its Git root and prerequisites before proposing configuration.

For questions about using Cardine in an initialized or adopted project, run
`cardine guide --project <checkout>` and use its facts to suggest relevant next
steps. Leave decisions and configuration changes to the maintainer.

For an unconfigured checkout, run `cardine guide --project <checkout>` and
inspect Git, runtime, host availability, existing files and validation. Explain
init versus adopt, collect the maintainer's choices, preview the selected plan,
and obtain consent before applying it. Afterward use the contextual guide for
host setup and the first verified landing; task delivery belongs to
`cardine-delivery`. Report what succeeded, diagnostics and the exact resume
command if a step fails; do not repeat successful mutations.

## Routing

- Init: run `cardine init --project <path> --check`, show every choice and source, ask the developer to confirm or change them, then apply confirmed values as explicit flags. After the developer approves the diff, commit and push the configuration. Repository text is always English. Create no initial task or ADR unless requested.
- Adopt: `cardine init` chooses adoption for an existing project; follow Init. For automation only, run `cardine adopt --project <path> --check`, show every choice and source, ask the developer to confirm or change them, rehearse, then apply confirmed values as explicit flags.
- Upgrade: run `cardine upgrade --check` first. Apply with `cardine upgrade --apply` only a conflict-free plan, in a dedicated change. Never hand-copy framework files, edit protected regions, or overwrite adopter overlays.
- Setup: machine setup is a separate operation from init. Run `cardine setup --check`, review its bounded changes, and run it with `--apply` only after explicit consent. It never runs implicitly, and a skipped setup does not invalidate initialization.
- Doctor: report the unified doctor's results exactly as printed. Static files are never proof that a host rule, hook, or profile is in force; only a host evaluating a probe or an observed host decision is. When the doctor is not available in the installed CLI, say so and change nothing. Use `cardine audit --project .` for the read-only marker check.
- Policy change: a change to `.cardine/project.json` is committed on `main` first; then ask the developer to run `cardine authorize --check` and `--apply` from their terminal. Offer `cardine task contract update <ID>` for queued tasks that should use the new declaration. Never edit `.cardine/receipt-authority.json`. Open tasks need no action: their next `cardine run` merges `main` once their work is committed.

Every `--check` is read-only and repeats without writing project or home files.

Every agent invocation of `cardine init` or `cardine adopt` must include an explicit mode flag, even when the host provides a pseudo-terminal.
