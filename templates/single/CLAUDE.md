# [Project Name]

Read `PROJECT_WORKFLOW.md` and `LANGUAGE_POLICY.md` before acting; `PROJECT_WORKFLOW.md` is the source of operational rules. If either is missing or contradictory, return `BLOCKED RULE_CONFLICT`. The shared rules below are generated from `AGENTS.md`.

## Commands

```bash
# Fill in the project's run, test, lint, and format commands.
```

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
