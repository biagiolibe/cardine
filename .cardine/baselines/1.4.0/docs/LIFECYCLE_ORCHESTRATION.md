# Lifecycle Orchestration

Use this procedure for `Run lifecycle <TASK-ID>` and `Accept <TASK-ID>`.

<!-- CARDINE:BEGIN capability=lifecycle-orchestration v3 -->
## Run lifecycle

`cardine run <TASK-ID> --project <primary-checkout>` is the orchestrator: it returns the next step as JSON, and `PROJECT_WORKFLOW.md` says how to follow it. Start the implementer and the reviewer as distinct fresh sessions; the reviewer does not see the implementer's reasoning (advice). A task whose review is `not_required` needs no reviewer. After two consecutive `CHANGES_REQUESTED` verdicts the engine stops with `REVIEW_LOOP_EXHAUSTED`, which needs a developer decision.
<!-- CARDINE:END -->

<!-- CARDINE:BEGIN capability=owner-acceptance-workflow v2 -->
## Accept

`Accept <TASK-ID>` is the developer's own review of a `required` task, run by the developer and never by an agent. On the clean reviewed HEAD, record `cardine review verdict <TASK-ID> APPROVE --owner --body <owner-evidence>`, then continue with `cardine run`. A manual merge is never permitted.
<!-- CARDINE:END -->
