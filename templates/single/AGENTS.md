# [Project Name] — Agent Router

Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md` before responding or acting; both are binding. If either is missing or they contradict, return `BLOCKED RULE_CONFLICT`.

Work only on a developer-assigned task or an authorized read-only request. Read the task and `git status --short` first, and preserve unrelated changes. Select one route below; ask when the request is mixed.

<!-- CARDINE:BEGIN capability=command-triggers v2 -->
## Command triggers

- `Proceed with <TASK-ID>` — read `docs/workflows/IMPLEMENTATION.md`.
- `Review <TASK-ID>` — read `docs/workflows/REVIEW.md`.
- `Address review <TASK-ID>` — read `docs/workflows/REMEDIATION.md`.
- `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` — read `docs/LIFECYCLE_ORCHESTRATION.md`.
- Status, project question, or tech-design alignment — use `docs/CONTEXT_READING_POLICY.md`.
- Explicit audit — read `docs/AUDIT_PROMPT_READ_ONLY.md`.
<!-- CARDINE:END -->

Advice: follow `docs/CODE_ORGANIZATION.md` for production-source changes.
