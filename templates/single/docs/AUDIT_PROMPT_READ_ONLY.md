# Audit Prompt (Read-only)

<!-- CARDINE:BEGIN capability=audit-prompt v2 -->
Use this prompt in a fresh session for a periodic or second-opinion audit. The audit modifies nothing: no edits, write-mode formatters, commits, or implementation.

```text
Perform a read-only workflow conformance audit of this repository.

Run `cardine audit --project .` first and report its result. Then inspect only what that command cannot check: LANGUAGE_POLICY.md, PROJECT_WORKFLOW.md, AGENTS.md/CLAUDE.md, docs/ARCHITECTURE_DECISIONS.md, docs/CODE_ORGANIZATION.md, the queue (`cardine locations`), and the task files.

Report PASS/FAIL with file and line references for:
1. LANGUAGE_POLICY.md fixes one conversation language and requires English for every repository artifact, and the agent instructions load it first.
2. Document precedence is explicit and resolves conflicts without a silent choice.
3. Accepted ADRs record the binding decisions they claim, and no lower-precedence document contradicts them.
4. Each declared architectural boundary is a concrete, checkable rule, not an aspiration.
5. Every task cites its governing authority, lists exactly the dependencies it needs, and does not claim a specification it does not implement.
6. Every task has measurable acceptance criteria and an executable validation command.
7. Context discipline: task-first reading, no full-backlog or unrelated-ADR scans, concise plans and reports.
8. A `Run lifecycle` run used distinct implementer and reviewer sessions, durable repository evidence instead of copied chat, and its retry limit.

If `docs/AUDIT_PROMPT_READ_ONLY.md` has a `## Project-specific checks` section after the managed block, run each check listed there. Each must cite an accepted ADR; report one that cites none as a finding.

Output: PASS/FAIL per item, discrepancies, ambiguous requirements, stale lower-precedence text, and documentation-only follow-ups. Propose no feature work.
```
<!-- CARDINE:END -->
