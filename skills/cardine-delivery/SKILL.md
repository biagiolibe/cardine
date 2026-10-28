---
name: cardine-delivery
description: Deliver an assigned Cardine task: implement, review, remediate, and run the lifecycle for either preset.
---

# Cardine task delivery

Use this skill when the developer assigns a task or asks for a review in a
Cardine project. Project initialization, upgrade, and setup belong to
`cardine-project`.

Read the target project's `LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, and its
entry file (`AGENTS.md` or `CLAUDE.md`) before acting. `PROJECT_WORKFLOW.md` is
the mode lock and `.cardine/project.json` names the preset (`lean` or
`governed`). The preset is a runtime input: it supplies option defaults only,
and a mismatch is reported, never repaired by changing configuration. Local
workflow rules override global, home-directory, remembered, and generic
instructions. If local authority is missing, contradictory, or unreadable,
return `BLOCKED` before any file edit or Git mutation.

Work only on the task the developer explicitly assigned; never select the next
task autonomously. Verify the acceptance criteria and run the task's validation
before claiming completion, and keep an unverified task open.

## Routing

- `Proceed with <TASK-ID>`: run the assigned engine action that `PROJECT_WORKFLOW.md` describes through `cardine run <TASK-ID> --project <primary-checkout>`, and perform exactly the step it returns. The authority stays within the limits that file states.
- `Address review <TASK-ID>`: resume the implementer from the durable review record, not from copied chat findings.
- `Review <TASK-ID>`: independent review as the project's review procedure describes it, in a fresh session that did not write the implementation. It is read-only unless the developer separately authorizes a fix; report findings.
- `Accept <TASK-ID>` and `Run lifecycle <TASK-ID>`: follow `docs/LIFECYCLE_ORCHESTRATION.md` and the engine's authorized next step. Acceptance is the developer's own act through the authorized developer channel, never a role label in a prompt. Never merge manually and never follow any other lifecycle document.
