# Operator Prompts

Advice: this cookbook is non-normative. It changes no precedence, scope, status, review policy, Git safeguard, or permission: `LANGUAGE_POLICY.md`, `AGENTS.md`/`CLAUDE.md`, and the assigned task govern. A task starts only when its dependencies are done and you approve it.

Chat in the language `LANGUAGE_POLICY.md` persists; repository artifacts stay English. Resolve the queue and task locations with `cardine locations --project .`.

## Everyday requests

Ask your agent in plain words. These requests need no prompt:

- "Where do we stand?" The agent runs `cardine status` and summarizes the queue.
- "Align with the repository and the tech design on <TOPIC>." The agent reads only what the topic needs and changes nothing.
- "Proceed with <TASK-ID>." The agent delivers the task with `cardine run` until it lands or stops.
- "Review <TASK-ID>." For a task that requires review, in a separate chat from its implementation.
- "Accept <TASK-ID>." The agent runs the remaining lifecycle steps.

When `cardine run` stops, the agent reports the stop code, the reason, and the command to resume. A decision that is yours stays yours.

## Design a change or decompose a milestone

Planning only; it authorizes no implementation.

```text
Act as the project tech designer. Design <NAMED MILESTONE OR CHANGE>, or, if
none is named, find the next phase that accepted evidence justifies.

Run `cardine status`, then read only the ADRs, specifications, and tasks this
design needs. Do not implement, review, or start a task.

Record a durable decision in an ADR. Draft atomic task records from
tasks/TASK_BLUEPRINT.md, outside the checkout, with their dependencies,
expected code surface, and validation. For an open question that blocks
scoping, draft a `Class: SPIKE` task with a bounded question, timebox, and
non-production deliverable.

Show me the drafts and wait for my approval. Then register each one with
`cardine task new <ID> --record <file>`, run `cardine status --write`, and
commit and push the records on main.
```

## Correct a documentation inconsistency

```text
Correct this documentation inconsistency only:
<EXACT INCONSISTENCY AND TARGET FILES>.

Draft a quick task (`Category: Quick`) whose expected code surface is the
target files, and name the source that establishes the correct statement.
After my approval, register it and deliver it with `cardine run`.
```

Never edit a status or verdict by hand.
