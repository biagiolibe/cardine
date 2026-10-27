# Workflow — [Project Name]

<!-- CARDINE:BEGIN capability=workflow-mode-lock v3 -->
## Workflow lock

This file selects the single Cardine lifecycle. Read it and the router (`AGENTS.md` or `CLAUDE.md`) before any edit, Git mutation, or completion claim.

`.cardine/project.json` sets the preset, `lean` or `governed`. A preset supplies option defaults only: review (`not_required` or `required`), authority required (no or yes), and expected code surface required (no or yes). A task overrides any option; the order is task, project default, preset, and nothing tightens silently. A project change affects new tasks only.
<!-- CARDINE:END -->

## Task contract

Every task, including a quick task, is registered with an objective, acceptance criteria, validation, dependencies, and resolved options (`tasks/TASK_BLUEPRINT.md`). An omitted optional section grants nothing. `cardine locations` prints the resolved task, review-record, and queue locations; other documents name a location by role.

When documents conflict, the first wins (advice): the language policy, the router, `docs/ARCHITECTURE_DECISIONS.md`, specifications, the frozen task contract, `docs/CODE_ORGANIZATION.md`, background. Never resolve a conflict silently.

<!-- CARDINE:BEGIN capability=task-lifecycle v3 -->
## Task lifecycle

```text
review required:      queued -> in_progress -> in_review -> in_progress -> done
review not required:  queued -> in_progress -> done
spike:                queued -> in_progress (outcome ANSWERED | INCONCLUSIVE) -> done
any open state:       queued | in_progress | in_review -> cancelled
```

`in_review` exists only when review is required. Requested changes return the task to `in_progress`, and a new commit invalidates an approval. `done` is reached only through verified landing; only a landed standard task, or a landed spike with outcome `ANSWERED`, satisfies a dependency. `done` and `cancelled` are terminal; reopening is a new task.

`.cardine/tasks/<TASK-ID>.json` is the only status and verdict authority: never edit it, or a verdict, by hand. Read status with `cardine status`; the queue and the plan are generated views.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=review-policy v2 -->
## Review policy

The reviewer is a separate session from the implementer and records its verdict with `cardine review verdict`; nobody approves their own work. A spike without review is `ANSWERED` only when its committed deliverable answers its `Question` within its `Timebox`, otherwise `INCONCLUSIVE`.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=git-workflow v4 -->
## Running a task

`Proceed with <TASK-ID>` means: run `cardine run <TASK-ID> --project <primary-checkout>` and follow the JSON it prints. Do the `work` it names inside `work.worktree`, never in the primary checkout; run `next.command` unchanged; stop only for `stop`. The stable lifecycle commands are `run`, `status`, `review`, `cancel`, and `abort`.

It authorizes the whole lifecycle when every gate passes, through landing, one plain `git push origin main`, and cleanup. Do not ask for confirmation within it. It never authorizes: creating, moving, or pushing a tag; publishing a release; a force, deleting, or mirroring push; a history rewrite (amend of pushed commits, rebase, reset, cherry-pick); deleting an unmerged branch or force-removing a worktree; bypassing a required independent review; resolving a textual conflict; work outside the expected code surface or on another task. Do not merge `main` or push a task branch by hand; `cardine run` pushes only what the project's CI needs.

## Stops and denials

Stop only for a denied action, a scope change, or `outcome: blocked` with `stop.human_decision: true`; report the code and `stop.resume`. Every other outcome is not a stop: run `next.command` in the same turn, wait `retry_after_seconds` when `waiting`, and repair the work when `iterate`. `RULE_CONFLICT` and `VALIDATION_RETRY_LIMIT` are guardrails.

Failing validation is work on the task: fix it and call `cardine run` again. The engine reruns once, records an intermittent pass, and counts failures; after the task's `validationRetryLimit` counted failures it stops with `VALIDATION_RETRY_LIMIT`. Record no counter yourself.

Guidance that no command backs is advice: follow it when you can, and never stop on its strength alone. Never satisfy a gate by writing false state. When a gate contradicts another rule, stop with `BLOCKED RULE_CONFLICT` and report both rules.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=validation-scoping v2 -->
## Validation and completion

Validation scope comes from the frozen `validationScoping`: documentation-only changes may skip unrelated build, test, or lint commands, and source, build, runtime, or CI changes run every task-required check plus the baseline. `cardine run` records any skip. Scope never weakens an acceptance criterion. Advice: verify each criterion before delivery; incomplete evidence keeps the task `in_progress`.
<!-- CARDINE:END -->
