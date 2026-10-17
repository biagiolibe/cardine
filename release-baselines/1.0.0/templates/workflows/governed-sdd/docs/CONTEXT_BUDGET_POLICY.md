# Context Budget and Reasoning Policy

This policy reduces context and reasoning overhead while preserving governed-SDD authority and review quality.

## Task-first loading

For an implementation or review:

1. Read `AGENTS.md` or `CLAUDE.md`, then the assigned task.
2. Read only the task's `Authority` entries and the minimum files needed to verify its `Expected code surface`.
3. Do not scan the repository, full backlog, unrelated ADRs/specifications, prior chats, or generic design documents without a task-specific need.
4. Expand context only when the task is blocked, an acceptance criterion cannot be verified, or an authoritative conflict is discovered. Record the reason in the completion or review report.

Dependencies establish readiness; they do not automatically require rereading their entire implementation history.

## Planning and communication

- Keep execution plans to three bullets or fewer.
- Report only state changes, material findings, validation results, or blockers.
- Keep routine completion and review reports concise; include detail only for deviations or unresolved risk.
- Do not use parallel agents or repeated inspections when they add no independent evidence.

## Reasoning profile

Use the lowest profile that can reliably satisfy the task:

| Work | Default profile | Escalate when |
|---|---|---|
| Implementation, review, task decomposition, and routine SDD work | `medium` | Evidence is insufficient or the task is materially ambiguous |
| Design or complex architecture | `high` | Cross-layer trade-offs or unresolved authority interactions require it |
| Exceptional high-complexity work | `xhigh` | Only with explicit justification and only if active tooling/configuration supports it |

Never hardcode an unsupported model, reasoning level, or tool option. If escalation is unavailable, keep the task scoped and report the limitation rather than widening the task.
