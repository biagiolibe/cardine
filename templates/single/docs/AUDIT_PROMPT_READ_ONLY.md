# Audit Prompt (Read-only)

<!-- CARDINE:BEGIN capability=audit-prompt v1 -->
Use this prompt in a fresh session for a periodic or second-opinion audit of process conformance. The audit must not modify files, run formatters in write mode, create commits, or implement code.

```text
Perform a read-only workflow conformance audit of this repository.

Scope: inspect LANGUAGE_POLICY.md, PROJECT_WORKFLOW.md, AGENTS.md/CLAUDE.md, docs/ARCHITECTURE_DECISIONS.md, docs/CODE_ORGANIZATION.md, docs/CONTEXT_READING_POLICY.md, docs/INTEGRATION_POLICY.md, docs/CODE_REVIEW_PROMPT.md, the project's queue (`cardine locations`), and every atomic task file. Inspect the project's build/dependency manifests only if present. Do not edit files or implement code.

Verify and report, with file/line references:
1. `LANGUAGE_POLICY.md` establishes one persistent conversation language, requires English for all repository artifacts, and the agent instructions load it before responding or writing.
2. Document precedence is explicit and resolves conflicts without silent implementation choices.
3. Accepted ADRs record the binding technical/platform decisions they claim to lock in, and no lower-precedence document contradicts them.
4. Any declared architectural boundary (e.g. a dependency-free core, a layer separation, a module ownership map) is stated as a concrete, checkable rule rather than an aspiration.
5. Specifications and their task decomposition are consistent: every task cites its governing authority, and no task claims to satisfy a specification it does not implement.
6. Every atomic task's declared `Dependencies` list is exactly the set of tasks it actually requires, and only landed `done` standard tasks or landed `done` spikes with outcome `ANSWERED` are treated as satisfying a dependency.
7. Every atomic task has measurable acceptance criteria and, where applicable, executable validation commands.
8. Every task has a CLI-written contract snapshot with resolved options and validation commands. Review and the two scope requirements follow preset defaults and explicit project/task overrides in either direction; a preset change never silently revises an open task.
9. Token/context discipline is followed: task-first context loading, no full-backlog or unrelated-ADR scans without a task-specific need, concise plans and reports, and reviewer independence used only when the task's review policy requires it.
10. The implementation-to-review-to-integration handoff matches `docs/INTEGRATION_POLICY.md`: the task branch is the `branch` value returned by `cardine worktree prepare`, one sequential writer in its linked worktree, a task-branch push only to obtain `T1_CI` (at most once per review attempt, never by the reviewer, none without CI), task branches that never edit the queue, queue archive, or plan, statuses changed only by `cardine task transition` and `cardine review verdict`, with tracked state as authority and record fields as projections, durable review records for requested changes, recorded-base ancestry verification, the reviewer author printed by `cardine project show --field reviewer-author` used only on the acceptance commit, queue and plan status applied once by `integrate stage`, serialized combined-tree validation and `main` merge commits, and cleanup only after successful integration without rebase/amend/cherry-pick/force recovery shortcuts.
11. The owner-acceptance workflow (an explicit `Accept <TASK-ID>` trigger from the project owner) is either absent or, if present, runs `cardine review verdict <TASK-ID> APPROVE --owner`, commits the task state and projections, and continues at C6 under the `Proceed with` authority without a source change; a manual merge is never permitted.
12. Git history shows no task marked `done` without either a commit-bound `APPROVE` verdict in machine state from a reviewer-integrator or the owner (for `Review: required`) or complete self-reported validation evidence (for `Review: not_required`); every review that requests changes has an evidence-backed record and a return to `in_progress` retaining the verdict and prior attempt before remediation.
13. When `Run lifecycle <TASK-ID>` is used, its implementer and reviewer sessions are distinct, all handoffs use durable repository evidence rather than copied chat context, the retry limit is respected, and integration occurs only after the required repository and forge gates.

If `docs/AUDIT_PROMPT_READ_ONLY.md` has a `## Project-specific checks` section after the managed block, also run each check listed there. Each such check must cite an accepted ADR; report a check that cites none as a finding instead of running it.

Output: a concise audit report with PASS/FAIL per item, discrepancies, ambiguous requirements, stale lower-precedence text, and recommended documentation-only follow-ups. Do not propose feature implementation.
```
<!-- CARDINE:END -->
