# Operator Prompts

Advice: this cookbook is non-normative. It changes no precedence, scope, status, review policy, Git safeguard, or permission: `LANGUAGE_POLICY.md`, `AGENTS.md`/`CLAUDE.md`, and the assigned task govern. Use one chat per workflow, and put an implementation and its required review in separate chats. A task starts only when its dependencies are done and you assign it.

Replace every `<PLACEHOLDER>` first. Resolve the queue and task locations with `cardine locations --project .`. Chat in the language `LANGUAGE_POLICY.md` persists; repository artifacts stay English.

## Design a change or decompose a milestone

Planning only; it authorizes no implementation.

```text
Act as the project tech designer. Design <NAMED MILESTONE OR CHANGE>, or, if
none is named, find the next phase that accepted evidence justifies.

Read LANGUAGE_POLICY.md, AGENTS.md or CLAUDE.md, PROJECT_WORKFLOW.md, the
queue, and docs/CODE_ORGANIZATION.md, then only the ADRs, specifications, and
tasks this design needs. Do not implement, review, or choose an unassigned task.

Record a durable decision in an ADR. Create or revise only atomic tasks that
follow tasks/TASK_BLUEPRINT.md. For an open question that blocks scoping,
create a `Class: SPIKE` task with a bounded question, timebox, and
non-production deliverable.

Report changed files, assumptions, and the proposed change with its rationale
and dependencies.
```

## Correct a documentation inconsistency

```text
Correct this documentation inconsistency only:
<EXACT INCONSISTENCY AND TARGET FILES>.

Read LANGUAGE_POLICY.md, AGENTS.md or CLAUDE.md, PROJECT_WORKFLOW.md, the
source that establishes the correct statement, and the target files. Change no
source code, task status, queue order, or ADR intent. Verify the diff and
report the evidence.
```

Never edit a status or verdict by hand.
