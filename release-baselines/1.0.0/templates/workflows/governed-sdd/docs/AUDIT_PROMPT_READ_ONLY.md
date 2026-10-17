# Governed SDD Audit Prompt (Read-only)

Use this prompt in a fresh session for a periodic or second-opinion audit of process conformance. The audit must not modify files, run formatters in write mode, create commits, or implement code.

```text
Perform a read-only governed-SDD conformance audit of this repository.

Scope: inspect LANGUAGE_POLICY.md, PROJECT_WORKFLOW.md, AGENTS.md/CLAUDE.md, docs/ARCHITECTURE_DECISIONS.md, docs/CODE_ORGANIZATION.md, docs/CONTEXT_BUDGET_POLICY.md, docs/PULL_REQUEST_POLICY.md, docs/CODE_REVIEW_PROMPT.md, tasks/QUEUE.md (or docs/TASK_QUEUE.md), and every atomic task file. Inspect the project's build/dependency manifests only if present. Do not edit files or implement code.

Verify and report, with file/line references:
1. `LANGUAGE_POLICY.md` establishes one persistent conversation language, requires English for all repository artifacts, and the agent instructions load it before responding or writing.
2. Document precedence is explicit and resolves conflicts without silent implementation choices.
3. Accepted ADRs record the binding technical/platform decisions they claim to lock in, and no lower-precedence document contradicts them.
4. Any declared architectural boundary (e.g. a dependency-free core, a layer separation, a module ownership map) is stated as a concrete, checkable rule rather than an aspiration.
5. Specifications and their governed task decomposition are consistent: every task cites its governing authority, and no task claims to satisfy a specification it does not implement.
6. Every atomic task's declared `Dependencies` list is exactly the set of tasks it actually requires, and only `ACCEPTED` tasks are treated as satisfying a dependency.
7. Every atomic task has measurable acceptance criteria and, where applicable, executable validation commands.
8. Every task declares `Review: REQUIRED` or `Review: NOT_REQUIRED` explicitly, and `NOT_REQUIRED` is used only for low-risk, self-contained work (documentation, mechanical configuration, simple scaffolding, or focused tests with no production behavior) — never for public APIs, dependency/boundary changes, security, state transitions, persistence/history, or unresolved design questions.
9. Token/context discipline is followed: task-first context loading, no full-backlog or unrelated-ADR scans without a task-specific need, concise plans and reports, and reviewer independence used only when the task's review policy requires it.
10. The implementation-to-review-to-integration handoff matches `docs/PULL_REQUEST_POLICY.md`: task branches, single push per branch, fast-forward ancestry check before acceptance, reviewer-integrator author override used only on the acceptance commit, and `main` integration procedure followed without fetch/rebase/force recovery shortcuts.
11. The owner-acceptance workflow (an explicit `Accept <TASK-ID>` trigger from the project owner) is either absent or, if present, is scoped to a status-only handoff without a source change, validation rerun, or automatic merge.
12. Git history shows no task marked `ACCEPTED` without either an `APPROVE` verdict from a reviewer-integrator (for `Review: REQUIRED`) or complete self-reported validation evidence (for `Review: NOT_REQUIRED`).

Output: a concise audit report with PASS/FAIL per item, discrepancies, ambiguous requirements, stale lower-precedence text, and recommended documentation-only follow-ups. Do not propose feature implementation.
```
