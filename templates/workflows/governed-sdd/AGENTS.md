# [Project Name] — Agent Router

Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md` before responding or mutating. Their mode, lifecycle, language, and repository-English requirements are binding; if either is missing or contradictory, return `BLOCKED WORKFLOW_UNREADABLE`. `PROJECT_WORKFLOW.md` locks this repository to `GOVERNED_SDD`; never substitute a Lean Delivery lifecycle or queue.

Work only on a developer-assigned task or an explicitly authorized read-only request. Before a write or Git mutation, read the task and `git status --short`; preserve unrelated changes and do not discard, stage, or overwrite them. Select one route below. A mixed or unrecognized request needs clarification; do not load a universal procedure.

<!-- MERIDIAN:BEGIN capability=command-triggers v3 -->
## Command triggers

- `Proceed with <TASK-ID>` — read `docs/workflows/IMPLEMENTATION.md`.
- `Review <TASK-ID>` — read `docs/workflows/REVIEW.md`.
- `Address review <TASK-ID>` — read `docs/workflows/REMEDIATION.md`.
- `Restart rejected <TASK-ID>` — read `docs/workflows/LIFECYCLE.md`.
- `Run lifecycle <TASK-ID>` or `Accept <TASK-ID>` — read `docs/workflows/LIFECYCLE.md`.
- Status, project question, or tech-design alignment — use `docs/CONTEXT_BUDGET_POLICY.md`.
- Explicit audit — read `docs/AUDIT_PROMPT_READ_ONLY.md`.
<!-- MERIDIAN:END -->

Follow `docs/CODE_ORGANIZATION.md` for production-source changes. The routed procedure supplies all role-specific validation, review, lifecycle, and Git detail.
