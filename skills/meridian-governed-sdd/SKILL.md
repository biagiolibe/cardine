---
name: meridian-governed-sdd
description: Bootstrap or operate a project using Meridian's governed spec-driven task workflow with ADRs, dependency gates, optional review, and reviewer-led integration.
---

# Meridian Governed SDD

Use this skill when the user asks to bootstrap a governed development workflow, create a governed atomic task, perform a review/integration, or audit SDD process conformance.

Read the target project's `LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, and `AGENTS.md` before acting. `LANGUAGE_POLICY.md` fixes the developer-facing language independently of the current prompt and requires English for all persistent repository text. When present, also read `docs/CONTEXT_BUDGET_POLICY.md` and the project-owned `docs/EXECUTION_EVIDENCE_PROFILE.md`; together they govern context loading, and proportionate evidence/output handling. If these documents are absent, bootstrap them from Meridian's own template source, without replacing an existing workflow unless the user explicitly requests migration.

## Workflow-mode lock

`PROJECT_WORKFLOW.md` is a mode marker as well as a source of rules. If it identifies the project as governed SDD, use only the governed-SDD lifecycle and Git procedure for every role. Before any file edit, Git mutation, task selection, or completion claim, confirm that local mode and load the local operating rules. Do not use global, home-directory, remembered, or generic Meridian/Claude/Codex instructions to select a lifecycle, task status, queue format, branch procedure, or review action.

In a governed-SDD project, Lean Delivery actions are forbidden: checkbox statuses, moving tasks to `tasks/done/`, treating `PROJECT_PLAN.md` as the canonical queue, autonomous task selection, and direct completion updates that bypass the task's review policy. A user prompt such as “update the queue” is not authority to choose an alternative workflow. If local workflow documents are missing, contradictory, or cannot be read before a mutation, stop and report `BLOCKED`; do not infer Lean Delivery as a fallback.

The Meridian template source is at `$MERIDIAN_ROOT` (an environment variable pointing at your local clone of the `meridian` repository, e.g. `export MERIDIAN_ROOT=/path/to/meridian` in your shell profile). If `$MERIDIAN_ROOT` is unset or does not point at a valid Meridian checkout, stop and ask the user for the repository path instead of guessing one — then remind them to set `MERIDIAN_ROOT` so future invocations don't need to repeat it. Ask the developer to select a conversation language and a task-identity mode: `opaque` keeps task IDs as labels, while `milestone` uses `M<milestone>-<WORKSTREAM>-<ordinal>` for new IDs. Never choose a task-identity mode by default; pass the selected value to `meridian setup --apply --task-identity <choice>` and explain that it can later be changed by editing the declaration. Then copy `$MERIDIAN_ROOT/templates/workflows/governed-sdd/` (`LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, `AGENTS.md`, `CLAUDE.md`, `docs/`, `tasks/`) into the target project and replace `[Conversation language]` in `LANGUAGE_POLICY.md`. Do not make repository text configurable: it is always English.

## Routing

- Bootstrap: ask the developer to choose `opaque` or `milestone` task identity, copy the governed overlay, fill project-specific commands/invariants, register it with `$MERIDIAN_ROOT/bin/meridian lock --project . --mode governed-sdd`, then pass that choice to `$MERIDIAN_ROOT/bin/meridian setup --apply --task-identity <choice>` only after the developer consents to setup. Create an initial ADR/task only when explicitly requested.
- Tech design: record decisions in ADRs, then create atomic tasks with explicit dependencies, authority, expected code surface, review policy, measurable acceptance criteria, validation, and out-of-scope boundary. Read `.meridian/task-identity.json` before assigning an ID: retain the existing stable-ID process for `opaque`, but in `milestone` ask for the milestone and uppercase workstream and use `meridian task identity next --milestone <N> --workstream <W> --format json`. Use its returned ID and path verbatim; never guess an ordinal, and stop and report if the command fails.
- Implement: work only on the requested task, its cited authority, and its expected code surface; follow the task lifecycle. Confirm the governed mode lock before creating or switching a branch.
- Orchestrate: on `Run lifecycle <TASK-ID>`, follow `docs/LIFECYCLE_ORCHESTRATION.md`. Coordinate separate implementer and fresh reviewer sessions through durable task, Git, validation, and review-record evidence; continue remediation automatically within its retry limit and stop on a defined blocker or unsatisfied forge gate.
- Upgrade: use `$MERIDIAN_ROOT/bin/meridian upgrade --project <path> --check` before applying a framework update. Apply only a conflict-free plan in a dedicated upgrade change; never hand-copy framework prompts, edit `.meridian/` baselines, or overwrite local workflow customizations.
- Adopt: run `$MERIDIAN_ROOT/bin/meridian adopt --project <path> --assisted --check` (omit `--mode`/`--from`; it detects them) and act as coordinator only, never as implementer or reviewer. Read its first `NEXT_ACTION` line and exit code. Codex sessions have no subagent tool, so drive the loop across separate fresh chats: on `IMPLEMENT_MIGRATION` or `ADDRESS_REVIEW`, start a new chat and paste the exact `IMPLEMENTER_PROMPT_BEGIN`/`_END` text (or fetch it alone with `--emit implementer`); on `REVIEW_MIGRATION` or the next `ADDRESS_REVIEW` pass, start another new chat that did not see the implementer's messages and paste the `REVIEWER_PROMPT_BEGIN`/`_END` text (or `--emit reviewer`) — it commits its verdict to `.meridian/adoption-review.md`. After each chat finishes, rerun the same command and act on the new `NEXT_ACTION`; never carry one chat's reasoning into the other, only the emitted prompt text and the record path. On `FINALIZE`, have the approving reviewer run `finalize-adoption` and commit the manifest/baseline diff with the approved migration. On `BLOCKED` — including two consecutive `CHANGES_REQUESTED` verdicts — stop and report the exact reason; do not retry automatically.
- Review: use `docs/CODE_REVIEW_PROMPT.md` in a fresh session that did not write the implementation; integrate only if all repository and forge gates are met. On `CHANGES_REQUESTED`, record actionable evidence in the review record (`meridian locations`), run `meridian review verdict <TASK-ID> CHANGES_REQUESTED --body <review-evidence>` on the clean reviewed HEAD, and create only the local review-handoff commit. The reviewer never pushes the task branch or edits implementation artifacts while reviewing. The implementer resumes with `Address review <TASK-ID>` and uses the durable record rather than copied chat findings.
- Owner acceptance: on `Accept <TASK-ID>`, follow `docs/workflows/LIFECYCLE.md`: run `meridian review verdict <TASK-ID> APPROVE --owner --body <owner-evidence>` on the clean task HEAD and commit the task state and projections, and continue at C6 under the `Proceed with` authority; do not re-review or revalidate, and never merge manually.
- Audit: read-only comparison of ADRs, specifications, tasks, queue, lifecycle state, and Git evidence, using `docs/AUDIT_PROMPT_READ_ONLY.md`.

Keep domain-specific architecture in the target project, not in Meridian's generic workflow assets. `docs/CODE_ORGANIZATION.md` states generic ownership/dependency-direction rules only; the project's own module map belongs in its architecture documentation.

## Context discipline

Apply `docs/CONTEXT_BUDGET_POLICY.md` and `docs/EXECUTION_EVIDENCE_PROFILE.md` when they exist. Start with the assigned task, then load only its authority and expected code surface; expand context only for a blocker, insufficient acceptance evidence, or an authoritative conflict. Run the profile's literal declared validation command strings, output bound included, rather than a bare command summarized afterwards, and when authoring a task declare every command that proves an acceptance criterion or `Evidence needed` item under its own validation ID (one command per ID, fixed task-scoped output paths, no `mktemp`, `$(...)`, or time-based paths), and use its progressive-diagnostic procedures without omitting required validation. For an explicitly read-only status request, use the context policy's minimal status profile instead of task-first loading or audit scope. Use `docs/COMPLETION_REPORT_TEMPLATE.md` for concise handoffs. Review only when the task policy requires it. A remote task-branch cleanup is optional and never blocks an accepted `main` integration; follow `docs/PULL_REQUEST_POLICY.md`.

For `Class: SPIKE`, use the managed task blueprint's separate branch roles:
the canonical task branch and worktree carry the deliverable and permitted
lifecycle/evidence records through ordinary governed closure. An optional
local throwaway probe branch is separate and is never merged or pushed; probe
code never ships. Do not commit SPIKE deliverables directly to `main`.

Use `meridian task transition <TASK-ID> <STATUS>` for lifecycle state changes and `meridian review verdict` for verdicts. Never edit a status or verdict by hand. Review commits include the task state file and its task/review projections. Adopt open legacy tasks with `meridian task state import --project <path> --format json`, inspect the evidence, then repeat with `--apply`. Review headings are human-readable only.

Before switching from prepare/check to execution start, consult the project’s
command location table in `docs/WORKTREE_LIFECYCLE.md#command-locations`
([framework reference](../../docs/WORKTREE_LIFECYCLE.md#command-locations)).

<!-- MERIDIAN:BEGIN capability=execution-boundaries v1 -->
After successful worktree verification, resolve only the task metadata and
execution contract needed for `meridian execution start <TASK-ID> --project .`.
For a nonterminal legacy Governed task, reconcile its contract first with
`meridian execution reconcile <TASK-ID> --apply --project .`; commit that
reconciliation before start. Run start before substantive authority/source
analysis, advisor consultation, or implementation. A repeated IN_PROGRESS
start preserves the first transition and its UTC timestamp. Only an explicitly
authorized Resume may pass `--resume`, after inspecting status and diff and
confirming the assigned task's changes and sole writer. Review/status requests
never start work. Meridian does not intercept advisor or host tool calls.
For Review: REQUIRED, commit implementation and validation evidence, then
finalize and commit the handoff, run read-only ready-check, and run
`meridian execution deliver <TASK-ID> --project .` last. Stop writing after
its clean committed result. Console-launched/manual/orchestrated workers use
this same sequence. SPIKE and review-not-required tasks retain existing closure.
<!-- MERIDIAN:END -->
