# [Project Name] — Agent Router

Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md` before responding or mutating. Their lifecycle, language, and repository-English requirements are binding; if either is missing or contradictory, return `BLOCKED WORKFLOW_UNREADABLE`. The preset configured in `.cardine/project.json` supplies option defaults only; never substitute another lifecycle or queue.

Work only on a developer-assigned task or an explicitly authorized read-only request. Before a write or Git mutation, read the task and `git status --short`; preserve unrelated changes and do not discard, stage, or overwrite them. Select one route below. A mixed or unrecognized request needs clarification; do not load a universal procedure.

<!-- CARDINE:BEGIN capability=command-triggers v1 -->
## Command triggers

- `Proceed with <TASK-ID>` — read `docs/workflows/IMPLEMENTATION.md`.
- `Review <TASK-ID>` — read `docs/workflows/REVIEW.md`.
- `Address review <TASK-ID>` — read `docs/workflows/REMEDIATION.md`.
- `Restart rejected <TASK-ID>` — read `docs/LIFECYCLE_ORCHESTRATION.md`.
- `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` — read `docs/LIFECYCLE_ORCHESTRATION.md`.
- Status, project question, or tech-design alignment — use `docs/CONTEXT_READING_POLICY.md`.
- Explicit audit — read `docs/AUDIT_PROMPT_READ_ONLY.md`.
<!-- CARDINE:END -->

Follow `docs/CODE_ORGANIZATION.md` for production-source changes. The routed procedure supplies all role-specific validation, review, lifecycle, and Git detail.
