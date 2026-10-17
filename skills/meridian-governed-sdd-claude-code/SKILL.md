---
name: meridian-governed-sdd-claude-code
description: Bootstrap or operate a project using Meridian's governed spec-driven task workflow (ADRs, dependency gates, optional review, reviewer-led integration) from Claude Code. Use when the user asks to bootstrap governed SDD, design/scope a governed task, implement an assigned TASK-ID, run a review/integration pass, or audit governed-workflow conformance in a Claude Code session.
---

# Meridian Governed SDD (Claude Code)

Claude Code counterpart of the Codex `meridian-governed-sdd` skill (`skills/meridian-governed-sdd/`). Same governed lifecycle and documents; this version is written for a Claude Code session and its plugin commands instead of Codex's `AGENTS.md`-only, `$name`-invoked skills.

Read the target project's `LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, and `CLAUDE.md` before acting. `LANGUAGE_POLICY.md` fixes the developer-facing language independently of the current prompt and requires English for all persistent repository text. When present, also read `docs/CONTEXT_BUDGET_POLICY.md` and the project-owned `docs/EXECUTION_EVIDENCE_PROFILE.md`; together they govern context loading, and proportionate evidence/output handling. If the project was also generated for Codex, it will additionally have `AGENTS.md` — the two must not drift; treat `PROJECT_WORKFLOW.md` as the shared source of truth and update both instruction files together when the process changes.

If governed documents are absent, bootstrap them rather than working ad hoc:

- Prefer running this plugin's `/meridian-init` command with workflow mode `governed-sdd` — it also handles the base templates (`PROJECT_PLAN.md`, `TECH_DESIGN.md`, etc.) and the persistent conversation-language setting in one pass.
- Fall back to asking the developer for a conversation language and a task-identity choice, then copying `templates/workflows/governed-sdd/` (`LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, `CLAUDE.md`, `AGENTS.md`, `docs/`, `tasks/`) directly and replacing `[Conversation language]` in `LANGUAGE_POLICY.md` only if `/meridian-init` is not installed in this session. Explain that `opaque` keeps IDs as labels while `milestone` uses `M<milestone>-<WORKSTREAM>-<ordinal>` for new IDs; never choose for the developer, pass the answer to `meridian setup --apply --task-identity <choice>`, and state that the declaration can later be edited. Repository text remains English in all cases.

Never overlay the governed workflow onto an existing project without showing the diff and getting an explicit migration decision — the project may already have its own task queue, agent instructions, or branch policy.

## Routing

- **Bootstrap**: run `/meridian-init` (mode `governed-sdd`) when available; otherwise ask the developer to choose `opaque` or `milestone`, copy the governed overlay, fill in project-specific commands/invariants, run `${CLAUDE_PLUGIN_ROOT}/bin/meridian lock --project . --mode governed-sdd`, and after setup consent pass the choice to `${CLAUDE_PLUGIN_ROOT}/bin/meridian setup --apply --task-identity <choice>`. Create an initial ADR/task only when explicitly requested.
- **Tech design**: record decisions in `docs/ARCHITECTURE_DECISIONS.md`, then create atomic tasks — via `/meridian-task` (it detects `PROJECT_WORKFLOW.md` and switches to governed mode automatically) or directly from `tasks/TASK_BLUEPRINT.md` — with explicit dependencies, authority, expected code surface, review policy, measurable acceptance criteria, validation, and out-of-scope boundary. Read `.meridian/task-identity.json` before assigning an ID: retain the existing stable-ID process for `opaque`, but in `milestone` ask for the milestone and uppercase workstream and use `meridian task identity next --milestone <N> --workstream <W> --format json`. Use its returned ID and path verbatim; never guess an ordinal, and stop and report if the command fails. Do not pick the next task to work on automatically.
- **Implement**: work only on the one assigned `TASK-ID`, in its own branch/worktree (`task-NNN`, no provider prefix). After verified execution start, read the task, its cited authority, its expected code surface, and `git status --short`; state a short plan (max three bullets) and stop if unrelated changes or an unresolved higher-precedence conflict exist. Run the task's validation plus the project baseline checks from `CLAUDE.md`. Use final `execution deliver` for required review, or `task transition ... ACCEPTED` for review-not-required closure; never edit the primary queue on the task branch — never claim completion when required validation fails.
- **Orchestrate**: on `Run lifecycle <TASK-ID>`, use `docs/LIFECYCLE_ORCHESTRATION.md` as the coordinator-only procedure. Create separate implementer and fresh reviewer sessions, exchange only durable task, Git, validation, and review-record evidence, repeat remediation within the documented retry limit, and stop on a defined blocker or unsatisfied forge gate.
- **Upgrade**: run `${CLAUDE_PLUGIN_ROOT}/bin/meridian upgrade --project <path> --check` before applying an installed-framework update. Apply only a conflict-free plan in a dedicated upgrade change; never hand-copy prompts, edit `.meridian/` baselines, or overwrite local workflow customizations.
- **Adopt** (`/meridian-adopt`, or a request to migrate an existing project onto Meridian): run `${CLAUDE_PLUGIN_ROOT}/bin/meridian adopt --project <path> --assisted --check` — omit `--mode`/`--from` and let it detect them. Read only its first `NEXT_ACTION` line and exit code, then act as the coordinator, never as the implementer or reviewer: on `IMPLEMENT_MIGRATION` or `ADDRESS_REVIEW`, start a fresh Task-tool subagent and send it the exact `IMPLEMENTER_PROMPT_BEGIN`/`_END` text (or fetch it alone with `--emit implementer`); on `REVIEW_MIGRATION` or the next `ADDRESS_REVIEW` pass, start a second, distinct Task-tool subagent that did not implement the migration and send it the `REVIEWER_PROMPT_BEGIN`/`_END` text (or `--emit reviewer`) — it commits its verdict to `.meridian/adoption-review.md`. After each subagent finishes, rerun the same command and act on the new `NEXT_ACTION`; never forward one subagent's transcript or reasoning into the other, only the emitted prompt text and the record path. On `FINALIZE`, have the approving reviewer run `finalize-adoption` and commit the manifest/baseline diff with the approved migration. On `BLOCKED` — including two consecutive `CHANGES_REQUESTED` verdicts — stop and report the exact reason; do not retry automatically. If this session cannot start independent Task-tool subagents, fall back explicitly: tell the developer, then drive the same loop across separate fresh chats they open, pasting each emitted block verbatim.
- **Review/integrate**: use `docs/CODE_REVIEW_PROMPT.md`. Run the review from a context independent of the implementer's — a fresh chat, or a Task-tool subagent when this session has one — so the reviewer-integrator isn't anchored on the implementer's own reasoning. Read `PROJECT_WORKFLOW.md`, `CLAUDE.md`/`AGENTS.md`, the task, its governing documents, and the exact diff; report `APPROVE`, `CHANGES_REQUESTED`, or `BLOCKED`. On `CHANGES_REQUESTED`, record evidence in the review record (`meridian locations`), run `meridian review verdict <TASK-ID> CHANGES_REQUESTED --body <review-evidence>` on the clean reviewed HEAD, and create only the local review-handoff commit; the implementer resumes with `Address review <TASK-ID>` rather than copied chat findings. After `APPROVE` only, verify `git merge-base --is-ancestor main <task-branch>`, append approval evidence to the review record, create the local review-and-status `ACCEPTED` commit with the project-scoped reviewer author override, then fast-forward and push `main` exactly once and delete the local task branch. Never push the task branch; remote cleanup is optional and never blocks accepted `main` integration; follow `docs/PULL_REQUEST_POLICY.md` for ancestry, checkout, and forge-gate conditions.
- **Owner acceptance**: on `Accept <TASK-ID>` from the developer, follow `docs/workflows/LIFECYCLE.md` — confirm the task record is `READY_FOR_REVIEW`, run `meridian review verdict <TASK-ID> APPROVE --owner --body <owner-evidence>` on the clean task HEAD and commit the task state and projections, commit those two edits, and continue at C6 under the `Proceed with` authority. Do not re-review or revalidate, and never merge manually.
- **Audit**: read-only comparison of ADRs, specifications, tasks, queue, lifecycle state, and Git evidence against `PROJECT_WORKFLOW.md`, using `docs/AUDIT_PROMPT_READ_ONLY.md`. Report drift; do not fix it silently.

Keep domain-specific architecture in the target project, not in Meridian's generic workflow assets. `docs/CODE_ORGANIZATION.md` states generic ownership/dependency-direction rules only; the project's own module map belongs in its architecture documentation.

## Context discipline

Apply `docs/CONTEXT_BUDGET_POLICY.md` and `docs/EXECUTION_EVIDENCE_PROFILE.md` when they exist. Start with the assigned task, then load only its authority and expected code surface; expand context only for a blocker, insufficient acceptance evidence, or an authoritative conflict. Run the profile's literal declared validation command strings, output bound included, rather than a bare command summarized afterwards, and when authoring a task declare every command that proves an acceptance criterion or `Evidence needed` item under its own validation ID (one command per ID, fixed task-scoped output paths, no `mktemp`, `$(...)`, or time-based paths), and use its progressive-diagnostic procedures without omitting required validation. For an explicitly read-only status request, use the context policy's minimal status profile instead of task-first loading or audit scope. Use `docs/COMPLETION_REPORT_TEMPLATE.md` for concise handoffs. Review only when the task policy requires it, and prefer a dedicated subagent (Task tool) over widening the current context whenever a step calls for isolation (review, audit) rather than continuity with the implementer.

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
