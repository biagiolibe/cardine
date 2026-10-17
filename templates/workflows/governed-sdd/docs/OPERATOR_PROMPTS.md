# Governed SDD Operator Prompts

This non-normative cookbook provides focused prompts for starting Meridian chats. It does not change document precedence, task scope, task status, review policy, Git safeguards, or tool permissions. `LANGUAGE_POLICY.md`, `AGENTS.md`/`CLAUDE.md`, the assigned task, and the canonical workflow documents always govern the result.

For a repository containing `PROJECT_WORKFLOW.md`, these prompts operate only
in `GOVERNED_SDD` mode. They never authorize a fallback to Meridian Lean Delivery or
to any global/home-directory workflow instruction. If the local workflow files
are missing or contradictory, the agent must return `BLOCKED WORKFLOW_UNREADABLE` before a mutation.

Replace every `<PLACEHOLDER>` before sending a prompt. Use one workflow per chat. An implementation and its required review must use separate chats, except that `Run lifecycle <TASK-ID>` is a coordinator chat that delegates each role to a separate session. Before starting an implementation, remediation, or review, confirm the project's `docs/EXECUTION_EVIDENCE_PROFILE.md` is configured for the task's stack and evidence channels.

The agent must communicate in the language persisted in `LANGUAGE_POLICY.md`, even if a prompt uses another language. Any repository artifact produced by a prompt must remain in English.

Resolve the canonical queue, task, and review-record locations from
`PROJECT_WORKFLOW.md` before using a prompt. `meridian locations --project .`
may report them when available. Do not substitute a template path for a
project-declared location.

## 1. Report project status (read-only)

Use this before deciding what to do next.

```text
Report the current governed-SDD status without modifying files.

Use the minimal read-only status profile in docs/CONTEXT_BUDGET_POLICY.md.
Confirm only the active workflow mode and local status rules, non-terminal
queue entries, their direct dependency readiness, the current Git state, the
next permitted governance action, and blockers.

Do not load completed milestones, broad file inventories, full specifications,
ADRs, audit prompts, review records, or Git history unless a concrete
discrepancy, blocker, or requested handoff requires them. State the specific
evidence gap before every expanded read. Do not select a task, implement code,
review code, change files, create commits, or reconstruct prior chat context.
```

## 1a. Align tech design for questions and future work (read-only)

Use this to prepare a tech-design chat to answer project questions or scope a
later explicitly requested change, without starting work.

```text
Act as the project tech designer. Align to the current project state and
prepare to answer design, scope, architecture, and roadmap questions.

Read LANGUAGE_POLICY.md, AGENTS.md or CLAUDE.md, PROJECT_WORKFLOW.md, and
docs/CONTEXT_BUDGET_POLICY.md. Resolve the canonical queue and inspect only
its non-terminal entries, their direct dependencies, the current Git state,
and the active milestone's governing ADRs and specification. Load additional
reports, task records, source, or history only when a specific question
requires them; state the evidence gap first.

Return a concise readiness brief: established architectural and product
constraints; active work, dependency state, and the next permitted governance
action; open design questions, risks, and evidence gaps; and what is known
versus what must be verified before a decision.

Do not modify files, create ADRs or tasks, select implementation work, review
code, run implementation validation, create commits, or infer a new roadmap
item. Remain available to answer project questions or design a specifically
requested change.
```

## 2. Design a change, decompose a milestone, or select the next phase

Use this for planning and governance only; it does not authorize implementation.

```text
Act as the project tech designer. Design <NAMED MILESTONE OR CHANGE>, or, if
none is named, determine the next appropriate phase from accepted evidence.

Read LANGUAGE_POLICY.md, AGENTS.md or CLAUDE.md, PROJECT_WORKFLOW.md,
docs/CONTEXT_BUDGET_POLICY.md, the canonical queue,
docs/PULL_REQUEST_POLICY.md, and docs/CODE_ORGANIZATION.md. Load only the
ADRs, specifications, accepted verification evidence, and tasks needed for
this design. Use repository files as the source of truth.

For a named change, do not assume a solution beyond its stated scope. When no
phase is named, identify the highest-value next governed step permitted by
accepted dependencies, documented goals, unresolved risks, and architectural
boundaries. If no next phase is justified, report that explicitly.

Do not implement code, perform a code review, or choose an unassigned task.
Record durable decisions in an ADR and a normative specification only when
needed. Create or materially revise only atomic tasks that follow the
canonical task blueprint: declare dependencies,
review policy, authority, expected code surface, measurable acceptance
criteria, validation, and out-of-scope boundaries. When an unresolved question
must be answered before a task can be scoped or verified, create a `Class:
SPIKE` task with a bounded `Question`, `Budget`, and non-production
`Deliverable`; do not investigate it inside a normal task.

Verify the documentation diff. Create a commit only if the governing workflow
and current authorization permit it. Report changed files, assumptions, and
the proposed phase or change, its rationale, dependencies, and the next
permitted governance action.
```

## 3. Analyze an accepted result

Use this to interpret evidence without turning the chat into a review or implementation task.

```text
Analyze the accepted result of <MILESTONE OR CHANGE> as tech-design and
governance input.

Read the relevant specification, accepted tasks, completion or verification
reports, governing ADRs, the canonical queue, and only the Git history needed
to establish the result. Use repository files as the source of truth.

Explain what the evidence demonstrates, what remains bounded or unproven, and
which documented claims are inconsistent with the evidence, if any. Do not
perform a formal code review, change files, create future work, select a task,
or implement a remedy. End with the next permitted governance state.
```

## 4. Implement exactly one task

Use this in a dedicated implementation chat only after the task is dependency-ready.

```text
Proceed with <TASK-ID>.
```

The trigger delegates the detailed implementation procedure to `AGENTS.md` or `CLAUDE.md`. Do not append unrelated work to this prompt.

## 4a. Run one autonomous required-review lifecycle

Use this when the task is dependency-ready and you authorize implementation,
all remediation cycles, acceptance, and the final `main` push. The coordinator
must use distinct implementer and reviewer sessions; it must not turn its own
chat into either role.

```text
Run lifecycle <TASK-ID>.
```

The trigger delegates the full procedure to
`docs/LIFECYCLE_ORCHESTRATION.md`. It continues from durable repository state,
uses the declared review record instead of copied chat findings, and stops
only at its retry limit or a real repository, validation, authority, or forge
blocker.

## 5. Independently review a required-review task

Use this in a fresh chat that did not implement the task.

```text
Review <TASK-ID>.
```

The trigger delegates the detailed review and integration procedure to `AGENTS.md` or `CLAUDE.md` and `docs/CODE_REVIEW_PROMPT.md`.

## 6. Record owner acceptance after personal review

Use this only after personally reviewing a `Review: REQUIRED` task whose task record is `READY_FOR_REVIEW`.

```text
Accept <TASK-ID>.
```

The trigger runs `meridian review verdict <TASK-ID> APPROVE --owner --body <owner-evidence>` on the clean task HEAD, commits the state and projections, and continues at C6 under the `Proceed with` authority, as defined in `docs/workflows/LIFECYCLE.md`; it does not authorize a review, a source change, or a manual merge.

## 6a. Address requested review changes

Use this after an independent reviewer returns `CHANGES_REQUESTED`. The
reviewer has already recorded the scope, evidence, and state transition in
the declared review record; do not copy the findings into this prompt.

```text
Address review <TASK-ID>.
```

The trigger limits implementation to the unchecked findings in the durable
review record, validates them, runs `meridian task transition <TASK-ID> IN_PROGRESS` before remediation and any authorized T1_CI-only push before finalizing delivery. It commits remediation,
validation evidence, and the final handoff, then runs `meridian execution deliver
<TASK-ID> --project .` last and stops writing. It does not authorize unrelated work or a
reinterpretation of a finding.

## 7. Run the established read-only audit

```text
Perform the repository's read-only governed-SDD audit using
docs/AUDIT_PROMPT_READ_ONLY.md. Do not modify files, run write-mode formatters,
create commits, or implement code. Report PASS/FAIL findings with file and line
evidence only.
```

## 8. Inspect a Meridian framework upgrade (read-only)

Use this before deciding whether a managed workflow upgrade is needed.

```text
Check whether this project's Meridian baseline can be upgraded.

Run `meridian upgrade --project . --check`. Report the detected version, the
complete plan, conflicts, and the next permitted action. Do not run
`meridian upgrade --apply`, `meridian adopt`, or `finalize-adoption`; do not
edit files or create commits.
```

## 9. Correct a bounded documentation inconsistency

Use this when a source claim is demonstrably stale or inconsistent. Name the exact target; do not silently widen scope into a redesign.

```text
Correct this documentation inconsistency only:
<EXACT INCONSISTENCY AND TARGET FILES>.

Read LANGUAGE_POLICY.md, AGENTS.md or CLAUDE.md, PROJECT_WORKFLOW.md,
docs/CONTEXT_BUDGET_POLICY.md, the canonical source that establishes the
correct statement, and the target files. Do not change source code, task
acceptance states, queue ordering, ADR intent, or unrelated documentation.
Verify the resulting documentation diff. Create a commit only if the governing
workflow and current authorization permit it. Report the evidence and any
commit created.
```

## 10. Ask a bounded repository question

Use this for explanation or diagnosis without granting modification authority.

```text
Answer this repository question using repository files only:
<QUESTION>

Read only the authoritative documents, task records, reports, and source files
needed to answer. Cite exact repository paths. Do not change files, implement
work, review a task, or infer a new roadmap item.
```

## Useful short forms

```text
Proceed with <TASK-ID>.
Run lifecycle <TASK-ID>.
Review <TASK-ID>.
Address review <TASK-ID>.
Accept <TASK-ID>.
Analyze <MILESTONE> as governance only; do not modify files.
Report the current SDD handoff state; do not modify files.
```

## What a prompt cannot authorize

- A task may start only when its dependencies are `ACCEPTED` and the developer explicitly assigns it.
- A required-review task needs a separate reviewer-integrator chat unless the owner uses the explicit `Accept <TASK-ID>` path.
- `Run lifecycle <TASK-ID>` may coordinate the required-review loop only through distinct implementer and reviewer sessions, as defined by `docs/LIFECYCLE_ORCHESTRATION.md`.
- A task, review, audit, or analysis does not authorize unrelated code, future milestones, destructive Git recovery, or external publication.

Never edit a status or verdict by hand; use `meridian task transition` and `meridian review verdict` for task state and verdicts.
