# [Project Name] — Agent Router

Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md` before responding or acting; both are binding. If either is missing or they contradict, return `BLOCKED RULE_CONFLICT`.

Work only on assigned tasks or authorized read-only requests. Read the task and `git status --short`; preserve unrelated changes. For mixed requests, ask.

<!-- CARDINE:BEGIN capability=command-triggers v3 -->
## Command triggers

- `Proceed with <TASK-ID>` or `Address review <TASK-ID>` — use `cardine-delivery` for the engine action.
- `Review <TASK-ID>` — use `cardine-delivery` for review.
- `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` — use `cardine-delivery` and `docs/LIFECYCLE_ORCHESTRATION.md`.
- Init, adopt, upgrade, setup, or doctor — use `cardine-project`.
- Status, project question, or tech-design alignment — use `docs/CONTEXT_READING_POLICY.md`.
- Explicit audit — read `docs/AUDIT_PROMPT_READ_ONLY.md`.
<!-- CARDINE:END -->

Advice: follow `docs/CODE_ORGANIZATION.md` for production-source changes.
