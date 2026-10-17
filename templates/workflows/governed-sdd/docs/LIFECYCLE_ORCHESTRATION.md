# Autonomous Task Lifecycle Orchestration

<!-- MERIDIAN:BEGIN capability=lifecycle-orchestration v12 -->
`Run lifecycle <TASK-ID>` authorizes an orchestrator to carry one dependency-ready
task through implementation, independent review, requested-change remediation,
acceptance, and `main` integration without further developer prompts. It does
not authorize work outside that task or bypass a repository or forge gate.

The orchestrator is a coordination-only role. It does not edit implementation
artifacts, perform the substantive review, or reinterpret findings. It starts
an implementer and a reviewer-integrator as distinct sessions. The reviewer
session must be fresh and must not receive the implementer's conversation or
reasoning; it re-derives evidence from repository artifacts.

```text
Run lifecycle <TASK-ID>
  -> implementer: Proceed with <TASK-ID>
  -> reviewer: Review <TASK-ID>
       -> APPROVE: acceptance commit, validated merge commit on main, push main
       -> CHANGES_REQUESTED: implementer: Address review <TASK-ID>
                              -> reviewer: Review <TASK-ID>
       -> stop: report the `BLOCKED <CODE>` line
```

The command-maintained machine state, task record, Git commits, completion report, and the declared
review record (see `PROJECT_WORKFLOW.md`'s canonical locations) are the only
handoff interface. Worker messages
must be concise and structured as: verdict or state, task ID, commit SHA,
review-record path when present, validation result, and blocker when present.
The orchestrator passes only that information to the next worker; it never
copies findings between chats.

## Preconditions and stop conditions

Before delegation, confirm that the task is assigned and dependency-ready,
then run `meridian worktree prepare` from the primary checkout. Pass its exact
existing path, branch, primary checkout, and worktree root to every worker as
durable launch inputs. If the host cannot launch a fresh session with that path
as its effective workspace, return `BLOCKED WRONG_WORKTREE`; never use automatic isolation,
`.claude/worktrees`, the primary checkout, or a substitute path.
Do not run implementation and review concurrently in the same worktree. Every
worker's first action is `meridian worktree check` in the prepared directory,
before any task or handoff read. Stop the implementer before starting the fresh
reviewer. Implementer prompts prescribe contract resolution, then
`meridian execution start <TASK-ID> --project .` immediately after check,
before substantive analysis, advisor consultation, or implementation. Launch
alone never records execution start. After implementation and validation,
the implementer commits implementation and the final handoff, runs
`meridian execution deliver <TASK-ID> --project .` last, and stops writing.
Require a clean committed valid delivery before launching review; pending
delivery/changes is availability information, not a replacement status.
The reviewer then runs the handoff preflight in
`docs/workflows/REVIEW.md`; it performs no substantive review unless the
absolute path, branch, HEAD, clean state, validated commits, and stopped
implementer all verify. If launched from the primary checkout, it roots every
review read and command in the verified task worktree and never switches the
primary checkout.

Never edit a status or verdict by hand. Workers use `meridian task transition` for lifecycle transitions and `meridian review verdict` (with `--owner` for owner acceptance) for verdicts. Continue automatically only while the command-reported machine state permits the
next transition. Stop with the `BLOCKED <CODE>` line of the failing gate when validation fails, authority is
ambiguous, the task branch or required local handoff commit is unavailable,
the worktree becomes dirty with unrelated changes, its registered branch/path
mapping changes, validation evidence is missing or stale, independence from an
advanced `main` cannot be established, serialized integration conflicts or
fails its selected integration gate, or an external forge approval is required
but unavailable.

After two consecutive `CHANGES_REQUESTED` verdicts, stop and report `BLOCKED REVIEW_LOOP_EXHAUSTED`
with the review-record path and unresolved findings. A developer may explicitly
restart the lifecycle after resolving the underlying scope or authority issue.

## Integration and forge gates

The `Run lifecycle` authorization includes each attempt's task-branch push when
`T1_CI` needs it (at most once per attempt, by the implementer only, and none
without CI), the local review-and-status commit,
`meridian worktree integrate stage`, separately executed candidate validation,
`integrate finalize` or `integrate abort`, and the single `main` push only after
`APPROVE` and all repository checks pass. The validated task commit must be an ancestor of task
HEAD, its intervening diff may contain only permitted lifecycle records, and
the validated base must be an ancestor of the validated commit. When current `main` still equals that
base, reuse the successful task evidence. When `main` advanced, use the
deterministic material-interaction comparison in `PROJECT_WORKFLOW.md`; use the
bounded gate only after independence is recorded, full validation for an
interaction or explicit requirement, and `BLOCKED EVIDENCE_MISMATCH` when independence cannot
be established. A dirty or unavailable primary checkout blocks integration
without changing the task worktree. A merge conflict or bounded/full gate
failure uses `integrate abort` and preserves the task branch and worktree. Only
successful integration and required push permit `meridian worktree cleanup`.
These reuse
rules do not weaken independent review, acceptance evidence, or forge gates,
and do not fabricate an external approval. If the
forge requires an approval from a distinct authorized identity, leave the PR
open and report `BLOCKED REVIEW_REQUIRED` unless that independent identity has actually
approved it.

## Token discipline

The orchestrator uses command-reported state, the latest commit, and the latest
review-record evidence. It never loads state files as startup context or infers acceptance from headings. Workers use task-first context loading. Do not recreate
prior chat context, repeat successful validation without a changed relevant
surface, or add a summarization agent between workers.
<!-- MERIDIAN:END -->

Candidate validation follows the consumer-owned `.meridian/candidate-validation.json`:
`REUSE` proves the governance-only candidate path set and runs its declared repository
gate, `BOUNDED` adds affected-module tests, and `FULL` adds the declared full suite. An
undeclared project stops before staging, lease, or merge; `none` deliberately retains a
non-empty command-list gate.

<!-- MERIDIAN:BEGIN capability=rejected-attempt-restart v5 -->
## Rejected-attempt restart after authority change

Use this procedure only when a `CHANGES_REQUESTED` finding explicitly cannot be
remediated without new or amended authority or task scope, and the developer
explicitly authorizes restart. Before any ref or status mutation, verify the
original branch, rejected exact tip, review record, handoff, validation evidence,
clean checkout, and available target names; also verify a separate tech-design
change amended authority and scope, received required independent review, is
`ACCEPTED`, and is integrated into `main`. Otherwise return `BLOCKED SCOPE_CHANGE_REQUIRED` with no
ref or status mutation.

In one atomic ref transaction, retain `archive/rejected/<normalized-task-id>-<attempt>`
at the rejected tip and create `retry/<normalized-task-id>-<attempt>` from accepted
`main`. Retain the archive and original branch with the review record, handoff, and
validation evidence. The retry's restart-handoff commit contains only that governance
evidence, the task record's `IN_PROGRESS` state, the archive ref/tip, accepted
design commit, and an explicit statement that no rejected implementation artifact was
copied. Implement and validate afresh: never reset, rebase, amend, force-push,
cherry-pick, merge, or copy rejected implementation commits or artifacts. Independently
review the retry against its main base; resolve the authority finding only with the
accepted design commit and independently recreated implementation. Retain archive and
original branch after integration; only the retry branch has ordinary cleanup.

### Operator sequence

The reviewer first completes its local review-handoff commit on the rejected
task branch and leaves that branch intact. Once the checkout is clean, switch
to the current `main` with `git switch main`. Create the separate tech-design
branch from that current `main`, review and integrate its authority/scope
amendment, then invoke `Restart rejected <TASK-ID>` from the updated `main`.
The retry therefore starts from the accepted design base, not from the rejected
task branch.
<!-- MERIDIAN:END -->
