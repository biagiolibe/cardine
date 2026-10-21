# Run engine — work item 8

## Scope and inherited contracts

This plan implements decisions 5, 6, 8, 11 and 12 of
`docs/ADR_CARDINE_1_0.md`. It follows `docs/SINGLE_WORKFLOW_PLAN.md`, section 8,
and `docs/SINGLE_SOURCE_OF_TRUTH_PLAN.md` (task 059). Its implementation starts
only after SS7, the last task of work item 7. Labels below are proposals, not
queue entries or authorization to start them.

There is one engine for both presets. Task 052 supplies project configuration
and named baseline/candidate commands; task 053 supplies the immutable resolved
contract snapshot; task 054 supplies transitions and commit-bound review.
Only `.cardine/tasks/<ID>.json` supplies task status, attempts and verdicts.
Generated queue/plan text, record location and worktree existence never imply
status. Use SS2's shared status service for dependencies and SS4's renderer for
saved views. Records keep their stable paths; only verified landing writes
`done`, as SS6 requires. Invalid or missing state is diagnosed, never imported
automatically from Markdown. This supersedes the legacy `TASK_STATE_MISSING`
import remedy for product execution, while keeping explicit legacy import.

This repository continues to use installed Meridian until work item 10.
All proposed execution tests use temporary consumer repositories. No task here
runs `cardine run` on this checkout, creates its `.cardine/`, changes frozen
governance or hooks, or applies setup to the real home directory. This task
only writes this plan and task-local records. Deferred entries in
`PROJECT_PLAN.md` are assigned below without editing that file in task 062.

## State and next-step resolution

Add `cardine.lifecycle.engine` with a pure resolver and a dispatcher. Reuse
validated task state plus a CLI-owned `run` object in the same state file,
containing operation receipts, validation attempts, implementation delivery,
candidate identity and landing progress. These are progress/evidence metadata,
not new statuses. Do not create a second lifecycle database. The task state
selects the next step; Git, worktree registration and lease reads verify its
preconditions and reconcile an interrupted side effect, never infer a status.

Each receipt includes task ID, contract digest, relevant source commit/tree,
operation ID and result. Serialize writers with a task lock and update JSON
atomically through `tasks.state`; integration also takes the primary lease.
Before an external effect write an intent, then persist the verified result.
On interruption probe the exact intended effect before repeating it. A live
foreign operation is a guardrail; an owned interrupted operation is recoverable.
Never turn an unknown result into success. Run validation outside metadata
locks, then compare input identities before accepting its result.

Choose one bounded step per invocation, allowing idempotent repairs within it.
No caller supplies the current phase. Resolver precedence is terminal cleanup,
pending side-effect reconciliation, unresolved guardrail, then the earliest
unsatisfied step below. Recheck dependencies and the frozen contract before
every transition. A changed source invalidates downstream validation and review;
a changed candidate invalidates candidate evidence alone. Cancellation is
terminal and cannot accidentally resume implementation.

| Step | State predicate and result | Existing implementation to reuse |
| --- | --- | --- |
| 1. Contract check | A queued task has no current contract-check receipt. Validate contract, dependencies, policy and scope; persist digest-bound readiness. No missing-state creation. | `tasks/contract.py::resolve_task_contract` validation without replacing the stored snapshot; `tasks/preflight.py`, `tasks/state.py`, `cardine execution` preflight/contract helpers. |
| 2. Worktree preparation | Contract ready, no verified preparation receipt. Prepare the canonical task branch/worktree, verify it, and start execution, transitioning queued to in_progress once. An existing owned dirty worktree resumes without discarding changes. | `cardine worktree prepare`, `check`, `paths.py`, `checkout.py`, `cardine execution start` in `lifecycle/commands.py`. |
| 3. Implementation | in_progress without a delivered implementation for the current contract/source. Return the agent work request and bounded context; accept completion only after actual acceptance evidence and a complete committed implementation exist. | `lifecycle/execution.py::delivery_readiness`, `execution_source_digest`, `cardine execution deliver`, task evidence/recording helpers. Refactor delivery's ordering so it does not demand validation before step 4. |
| 4. Validation | Delivered implementation lacks passing current task validation. Execute the resolved task commands plus applicable baseline, record real results, and build handoff evidence. Failure returns remediation to step 3 under the counter below. | `cardine execution validate` execution/evidence helpers, `tasks/evidence.py`, `lifecycle/closure.py::advance_task_closure` C1–C5 evidence checks. |
| 5. Review | Validated source requires review and has no matching approval. Transition to in_review, hand off to the independent reviewer, then check the exact verdict. Without review policy this step is explicitly skipped. | `cardine review`, `review/verdict.py::record_review_verdict`, task 054 transitions; `cardine task close` prepares closure without setting done or moving records, as changed by SS6. |
| 6. Candidate validation | Closure ready and review satisfied; CI precondition satisfied when enabled. Stage the direct candidate, select and execute required validation, persist tree-bound evidence. | `cardine worktree advance` C6–C7, `integrate stage`, `integration/decision.py::decide_integration_validation`, `integration/evidence.py`, `integration/merge.py::stage_task_integration`; `integrate abort` on an owned failed/stale candidate. |
| 7. Merge, push, cleanup | A verified candidate is ready, or a landing/push/cleanup receipt is incomplete. Finalize once, push main, verify the remote result, remove eligible remote task branch, then clean the local worktree/branch. | `integrate finalize`, `integration/merge.py::finalize_task_integration`, `cardine worktree advance` C8–C10, `cleanup_task_worktree`, `cardine worktree cleanup`. |

Retain the seven public step names even when a call only polls CI or reconciles
a receipt. Record the subaction separately. On restart after finalize, inspect
the intended merge commit and ancestry: never stage a second merge. A push
whose response was lost is checked against origin before retry. `done` can
coexist with push/cleanup pending metadata; dependencies use landed state and
the engine still completes delivery. On a failed candidate, abort only the
owned integration, preserve diagnostics, and return implementation remediation.
No textual conflict is resolved automatically. Missing closure records are
written from observed results and committed through the engine before staging.

## Invocation, locations and output contract

`cardine run <ID> [--project <path>]` always emits one JSON object on stdout;
subprocess output goes to bounded log artifacts and diagnostics, not mixed JSON.
Resolve a supplied project from either checkout to Git's common directory and
the first primary worktree entry, verify project identity, then resolve the
canonical task worktree using `worktree.paths`. Without `--project`, use the
enclosing checkout or a unique registered project/task identity in the existing
machine project registry. An ambiguous ID or an unregistered invocation outside
a project requires explicit `--project`; never guess a repository from cwd or
create a second checkout. Emitted commands always include the resolved absolute
primary path, so the next call works from any directory, including after the
task worktree has been removed. Paths in tracked reports remain relative.

Version 1 has the following closed envelope (types and invariants are the
normative schema; RE1 adds its JSON Schema file):

| Field | Type / allowed values |
| --- | --- |
| `version` | integer constant 1 |
| `task_id`, `project` | canonical ID and absolute primary path strings |
| `outcome` | `progress`, `next`, `waiting`, `iterate`, `blocked`, `done` |
| `step` | `contract`, `worktree`, `implementation`, `validation`, `review`, `candidate`, `landing`; null only for an invocation diagnostic before task resolution |
| `action` | string naming the subaction actually performed, including `none` |
| `next` | null or `{command: string, argv: string[], reason: string}` |
| `stop` | null or `{code: string, resolution: "guardrail", human_decision: true, detail: string, resume: string, resume_argv: string[]}` |
| `work` | null or structured agent/reviewer request: role, worktree, contract digest, expected surface, acceptance/validation references and delivery receipt requirements |
| `evidence` | array of `{kind: string, path: string, identity: string}` references to CLI-written evidence |
| `diagnostics` | array of `{code: string, message: string}`; codes registered where they represent lifecycle outcomes |
| `retry_after_seconds` | nonnegative integer, nonzero only for polling/waiting |

`blocked` requires `stop`; all other outcomes require `stop: null`.
`done` has `next: null`; every nonterminal resolved-task response includes a
runnable next command. A blocked response's next command equals its resume
command and remains safe if the person has not yet supplied the missing input:
it returns the same guardrail. Before task resolution, diagnostics may instead
require the missing project information; do not fabricate an executable path.
Exit status is 0 for progress/next/waiting/iterate/done, 2 for blocked and 64 for
invalid invocation. Only guardrails emit the single `BLOCKED <CODE>: ...;
resume: ...` line on stderr. stdout still contains the complete JSON response.

For example, after validation a no-review task may return:

```json
{
  "version": 1,
  "task_id": "T8",
  "project": "/tmp/consumer project",
  "outcome": "next",
  "step": "validation",
  "action": "record-passing-validation",
  "next": {
    "command": "cardine run T8 --project '/tmp/consumer project'",
    "argv": ["cardine", "run", "T8", "--project", "/tmp/consumer project"],
    "reason": "Prepare closure and the direct candidate"
  },
  "stop": null,
  "work": null,
  "evidence": [],
  "diagnostics": [],
  "retry_after_seconds": 0
}
```

Render shell commands from argv with POSIX quoting; never interpolate task text
as shell code. Execute configured literal validation commands with an explicit
cwd chosen by the engine, not a caller's cwd. Implementation is agent work:
`run` supplies the work request, it does not embed a host-specific coding agent.
The caller performs it and calls the same next command; repeated calls without
delivery return the same request and cannot skip acceptance. Required review
similarly returns a runnable `cardine review <ID> --project <absolute-primary>`
handoff to a distinct reviewer, never self-approval. Tests execute emitted text
unchanged from unrelated directories with spaces and shell metacharacters.

## Stops, recovery and bounded work

Use `stops/registry.py` and `stops/render.py` for all outcomes. `resolution`
selects guardrail/recoverable/failing-work and `human_decision` permits a real
stop only for guardrails. Reject contradictory registry entries. Do not wrap
all old exceptions as BLOCKED: classify at the cause, with proven ownership
and authority. Keep historical journal classes intact and count new outcomes
by resolution; every new blocked event must be a guardrail.

Recoverable states either repair safely inside the current step or return
`next` with the exact command. CI pending uses `waiting` and a bounded polling
interval. Failing work uses `iterate`, diagnostics and the implementation work
request; the caller fixes it in the same turn. A judgment acceptance failure
cannot be cleared by setting a flag without evidence. Permission, corruption,
foreign ownership, conflicts, scope and missing independent approval stay
guardrails. Unknown failures fail closed with an honest registered diagnostic,
never guessed success or an unlimited automatic loop.

Assign PROJECT_PLAN's two deferred task-030 proposals as follows:

| Owner | Required recovery and proof |
| --- | --- |
| RE3: `EVIDENCE_INCOMPLETE` | Return `cardine run <ID> --project <absolute-primary>`; on that call execute missing/stale declared validation and persist actual exit codes, acceptance evidence references and source identity before proceeding to C6/C7. If acceptance work is missing, return implementation work instead. Never synthesize success or ask the agent to supply unverified exit codes. A subprocess test triggers missing evidence, executes the exact returned command and reaches the next gate. |
| RE2: mixed-code split | Audit every emitter of `WRONG_WORKTREE`, `LEASE_HELD`, `PRIMARY_DIRTY`, `CLEANUP_BLOCKED`, `COMMAND_REFUSED`, `OS_ACCESS_FAILED`, `TASK_STATUS_REJECTED`, `TASK_STATE_INVALID` and `SELF_UPDATE_*`. Add cause-specific registered recoverable/failing-work codes only with safe ownership proof; retain the existing guardrail code for ambiguous/corrupt/foreign/denied cases. Self-update remains outside the run dispatcher; its emitter classification is covered without planning new update behavior. |

RE2 owns registry/schema changes and an emitter-to-cause inventory. Ordinary
worktree selection, owned interrupted lease, engine-owned closure dirt and
partial cleanup get exact runnable recovery. Foreign dirt, live foreign leases,
corrupt identities, host-denied access and protected/unmerged branches remain
negative tests. General invalid state is never rewritten from prose. Inventory
all recoverable entries, including stale base, main fast-forward, stale candidate
evidence, pending push and unresolved contract; preserve existing safe proofs
and add engine-path subprocess proofs. Remove/replace obsolete queue/archive
recovery routes after SS7 rather than resurrecting them.

Unattended authority comes from the frozen contract. Enforce `Expected code
surface` with normalized repository-relative paths/globs against tracked,
untracked, deleted, renamed and symlink changes; reject path escapes. Separate
CLI-owned state/evidence/view writes explicitly from agent implementation paths.
Recheck before delivery, validation, review and candidate staging. Work outside
the authorized surface emits `SCOPE_CHANGE_REQUIRED`; do not silently widen it.
For unattended runs an absent surface requires a contract decision before
launch even if the Lean preset permits omission for interactive work. No queue
selection, blanket approval or agent-supplied status grants authority.

## Validation attempts

Extend the validated task-state schema with `run.validation` containing a
stable attempt ID, contract digest, source identity, command-set digest, command
results/log references, retry phase, consecutive counted failures and intermittent
records. The engine owns all writes. The limit is the stored task-053
`contract.options.validationRetryLimit`, default 3, resolved preset -> project
-> task at creation, never reread from changing defaults mid-attempt.

One attempt is a complete declared validation set on a committed implementation
delivered as complete. Development tests are not attempts. A failure automatically
reruns the same entire set once with unchanged source, commands and environment
identity. Passing on that rerun records the actual failing commands/tests as
intermittent in CLI evidence and generated handoff, without counting a failure.
If the rerun also fails, increment once, summarize both runs, and return repair
work. Each command failure is not a separate attempt. If inputs change before
the rerun, invalidate it and require a fresh complete attempt; do not call the
old run intermittent. Persist intent/results so a crash or repeated `run`
cannot double count. Repair commits start new attempt IDs but retain the
consecutive failure count; a successful full set resets it. Only an explicit
authorized contract revision can reset an exhausted allowance without success.

At N counted failures register a new guardrail
`VALIDATION_RETRY_EXHAUSTED` (`human_decision: true`) with the summaries and
the runnable resume command. Keep `VALIDATION_FAILED` and
`CANDIDATE_VALIDATION_FAILED` as failing-work outcomes below the limit; do not
change their registry class to make them stop. Candidate failures use the same
task allowance when attributable to task work, keyed separately by candidate
tree and command set; abort the owned candidate before repair. A changed main
requires fresh candidate evidence, never reuse of a prior successful tree.
The agent records no counter, budget spend or intermittent classification.

## Review and Stable commands

`cardine run` reuses task 054's in_progress -> in_review transition. Review
requests carry the validated implementation commit, contract digest and role.
`cardine review` records reviewer provenance and verdict bound to that commit;
reports explain it but are never the authority. Approval continues to closure.
Requested changes return in_progress and implementation work, invalidate stale
validation, and require a new review of the changed commit. Missing/stale
approval stays a human guardrail; the implementer cannot issue its own verdict.
Lifecycle-only evidence commits may preserve approval only under the existing
proven unchanged-relevant-tree rule; uncertain changes require another review.
Keep external reviewer provenance independent of presets and landing strategy.

The Stable lifecycle surface is `run`, read-only `status` (explicit `--write`
regenerates views), `review`, `cancel` and `abort`. `cancel` records authorized
reason/history and terminal cancelled state without deleting work or satisfying
dependencies. `abort` restores only the caller-owned candidate/lease and leaves
the task resumable; it is not task cancellation. Both are idempotent and reject
foreign ownership. They accept `--project` with the same root resolver.

`worktree prepare/check/repair-base/advance/integrate stage|finalize|abort/cleanup`,
`execution start/preflight/validate/deliver`, state transition/import helpers,
evidence/closure commands and `task close` become Internal diagnostic surfaces.
Reuse their library functions, not recursive CLI orchestration or a second
resolver. Their retained CLI adapters use the same outcome classification.
`console` remains Experimental; do not promote it or change host installation.

## Direct landing and CI

Add a landing strategy interface in `cardine.integration`: prepare candidate,
read readiness, validate candidate, finalize landing, reconcile landing and
cleanup. Return structured receipts and needs to the same resolver. Ship only
`direct`; reject `pull-request` at configuration resolution in 1.0 without any
forge call. Preset never selects an integration implementation. Future 1.1 can
implement the interface using remote candidate/review facts without another
engine, extra statuses or changing Stable run output.

Direct uses the existing lease, no-commit merge, tree-bound evidence and
finalize/abort functions. Task 052's resolved command IDs select REUSE, BOUNDED
or FULL via `integration.decision`; always include `git diff --check`, the
baseline and required scoped/full checks. No hardcoded self-hosting command
or agent-chosen subset replaces configuration. Regenerate status views once
on the candidate from the landed JSON state; abort restores state and views
together. Finalize verifies the candidate identity and lease again before
committing. A later main change requires restaging and revalidation.

If `ciBeforeLanding` is false, direct has no `gh` dependency. If true, require
the resolved supported provider and nonempty required checks. Push the exact
validated task commit once per delivered head/review attempt with a plain
non-force task-branch push; persist the remote ref/SHA and receipt. Reconcile
a lost response by reading the ref before any retry. New repair commits are
new delivered heads, never history rewrites. Poll through `gh` for the exact
SHA and named required checks, with bounded time per call and `waiting` plus
the unchanged run command while checks are pending/missing. Checks on another
SHA cannot pass the gate; failed checks return failing work, authentication or
branch protection refusal is a guardrail. Do not open a pull request in 1.0.

After main is pushed, the engine can delete only the remote task branch it
recorded pushing. Fetch/read the current ref, verify that its exact tip is
contained in pushed main, and delete with a server-side expected-old-OID
compare-and-delete operation. A branch that advanced concurrently is preserved;
do not use an unconditional delete after a racy ancestry check. An absent ref
is idempotent success, an unrelated ref is not owned cleanup. This narrow
lifecycle capability does not authorize agents to delete branches. Then reuse
local cleanup's clean/merged/inactive checks; preserve any unmerged or foreign
work. A failed main push never triggers remote task deletion.

## Console and later boundaries

Rebuild the product console on SS2's status snapshot plus the resolver's
read-only preview of receipts and next actions. Display preset, totals,
startability, current step, review/CI waits and guardrails from the same facts
as run. Start/resume invokes the Stable engine; cancel/abort invoke their
Stable commands. Rendering never executes a step, writes state or parses the
generated queue. Keep SS1's explicit Meridian installation reader and its
coordinator fixtures intact; missing product state never selects that reader.

Work items 9 and 10 are not planned here. Avoid host-specific agent launch
logic, shell-hook dependencies, a second console calculator, absolute paths in
tracked handoffs, and automatic legacy import: each would make host adapters
or deliberate conversion harder. Preserve structured work requests, versioned
JSON and the explicit installation boundary for those later decisions.

## Ordered implementation tasks

Every row explicitly depends on SS7 (task 059's final work-item-7 label).
Execute all rows serially in this order: rows sharing cli.py, state, registry,
integration or test support must never run in parallel. Each row runs named
tests plus the applicable repository baseline and clean-clone checks required
by its eventual task contract. No row changes this repository's delivery mode.

| Label / estimate | Scope and files | Tests | Dependencies |
| --- | --- | --- | --- |
| RE1 / 3h | Versioned run response schema, root resolution, pure resolver and atomic operation receipts; new `lifecycle/engine.py`, `lifecycle/model.py`, `schemas/run-v1.schema.json`, task-state schema, `tasks/state.py`, `cli.py` | New `test_run_resolution.py`, `test_run_output.py`: all seven steps, invalid/missing state, cwd independence, quoting, lock contention and crash boundaries | SS7 |
| RE2 / 3h | Split mixed stop emitters by cause, registry/schema/rendering and Internal adapter classification; `capabilities/stop-codes-v1.json`, stop schema, `stops/`, affected worktree/lifecycle/task/self-update emitters, recovery test support | Existing registry/recovery tests plus new `test_run_recovery.py`: execute every recoverable emitted command unchanged; denied-access, foreign lease, corrupt identity and protected branch negatives | SS7, RE1 |
| RE3 / 3h | Implementation delivery, expected-surface enforcement, automatic validation/retry state and runnable EVIDENCE_INCOMPLETE recovery; `lifecycle/execution.py`, `commands.py`, new `lifecycle/validation.py`, `tasks/evidence.py`, state schema, retry registry entry | New `test_run_validation.py`, `test_run_scope.py`: N failures, identical rerun/intermittent, changed inputs, restart without double count, rename/untracked escapes, emitted evidence recovery reaches C6/C7 | SS7, RE2 |
| RE4 / 2h | Review/closure routing and Stable cancel/abort adapters; `review/verdict.py`, `tasks/transitions.py`, `lifecycle/engine.py`, `closure.py`, `cli.py` | New `test_run_review.py`, existing review/state tests: independent approval, changes requested, stale commit, cancellation, owned abort and repeat-call safety | SS7, RE3 |
| RE5 / 3h | Direct landing strategy and candidate execution from resolved config; new `integration/landing.py`, `integration/direct.py`, `merge.py`, `decision.py`, `evidence.py`, engine dispatch | New `test_run_integration.py`, integration decision/projection tests: REUSE/BOUNDED/FULL, changed main/tree, candidate retry/abort, landed-only done and view restoration | SS7, RE4 |
| RE6 / 3h | Optional exact-head CI, main push reconciliation, remote branch cleanup and local cleanup; new `integration/ci.py`, direct strategy, worktree cleanup helpers | New `test_run_ci.py`, `test_run_cleanup.py`: fake gh plus bare-origin subprocess fixtures, one push per head, pending/failed/wrong SHA checks, no-gh default, rejected push, ancestry and compare-delete race, interruption after each effect | SS7, RE5 |
| RE7 / 3h | Console preview/actions, final Internal surface audit and end-to-end recovery matrix; `console/snapshot.py`, `state.py`, `launch.py`, `render.py`, `cli.py`, lifecycle diagnostic adapters and product command documentation | Existing console/legacy fixtures plus new `test_run_end_to_end.py`: both presets, all seven steps, every current recoverable code's returned command executed unchanged from unrelated cwd, journal has only guardrail stops, no writes on preview, stable record paths | SS7, RE6 |

At RE7, compare the recovery matrix against the actual registry, not a frozen
list of examples. Every recoverable entry must have an executable progress
proof or be removed with its obsolete emitter; no deferred exception remains.
Keep each source/test file under 1,500 lines. Future task records can subdivide
an oversized row before work starts, preserving the serial dependency chain.
