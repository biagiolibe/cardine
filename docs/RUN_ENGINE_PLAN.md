# Run engine — work item 8

## Scope and inherited contracts

This plan implements decisions 5, 6, 8, 11, 12, 13 and 14 of
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
`PROJECT_PLAN.md` are assigned below without editing that file in task 082.

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
normative schema; RE1a adds its JSON Schema file):

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
cwd chosen by the engine, not a caller's cwd. Implementation is agent work: `run` supplies the work request and launches the
configured host through RE4a's role-profile interface. The host performs it
and calls the same next command; repeated calls without
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
| RE3b: `EVIDENCE_INCOMPLETE` | Return `cardine run <ID> --project <absolute-primary>`; on that call execute missing/stale declared validation and persist actual exit codes, acceptance evidence references and source identity before proceeding to C6/C7. If acceptance work is missing, return implementation work instead. Never synthesize success or ask the agent to supply unverified exit codes. A subprocess test triggers missing evidence, executes the exact returned command and reaches the next gate. |
| RE2a–RE2c: mixed-code split | Audit every emitter of `WRONG_WORKTREE`, `LEASE_HELD`, `PRIMARY_DIRTY`, `CLEANUP_BLOCKED`, `COMMAND_REFUSED`, `OS_ACCESS_FAILED`, `TASK_STATUS_REJECTED`, `TASK_STATE_INVALID` and `SELF_UPDATE_*`. Add cause-specific registered recoverable/failing-work codes only with safe ownership proof; retain the existing guardrail code for ambiguous/corrupt/foreign/denied cases. Self-update remains outside the run dispatcher; its emitter classification is covered without planning new update behavior. |

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

At N counted failures emit the existing guardrail
`VALIDATION_RETRY_LIMIT` (`human_decision: true`) with the summaries and
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
approval routes to independent review; an issued review is waiting, and an
unavailable independent approval is `REVIEW_NOT_APPROVED` with its cause; the implementer cannot issue its own verdict.
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

Work items 9 and 10 are not planned here. RE4a defines the host launch
interface; work item 9 installs its profiles. Avoid shell-hook dependencies, a second console calculator, absolute paths in
tracked handoffs, and automatic legacy import: each would make host adapters
or deliberate conversion harder. Preserve structured work requests, versioned
JSON and the explicit installation boundary for those later decisions.

## Trust boundary

Decision 14 rule 2, amended on 2026-10-23, governs all rows below. RE1b
writes operation receipts through the CLI writer, including creation and
contract revisions, with project/common-directory/root identity, task ID,
operation ID, predecessor receipt, contract digest, trusted runtime/rule and
accepted-main identities, exact input/output paths and digests, source/tree,
and measured result. Intent precedes each effect; verified output completes
it. Tracked state remains portable. A fresh clone verifies portable receipts
against explicitly accepted policy or requires developer reauthorization; it
never bootstraps authority from arbitrary task JSON. Receipts are separate
from the best-effort journal, which is never a recovery authority.

RE1c makes contract/dependency, preparation, transition and state readers
reject uncovered or changed artifacts. RE3a/RE3b verify delivery and measured
validation; RE4b verifies review/cancel decisions; RE5a/RE5b verify leases,
candidate selection and finalization; RE6a/RE6b verify CI, push and cleanup
receipts. RE7a uses the same verified facts for console/flow. A valid schema,
recomputed public digest, task-branch commit or editable local tracking ref
cannot substitute for a matching operation receipt. Known stale genuine
results are rerun; unknown provenance fails closed without blessing edits.

RE4a launches the implementer and independent reviewer through a host-neutral
`hosts/launch.py` interface with distinct role profiles and session identities.
Requests bind task, attempt, contract, source and role. Implementer credentials
cannot record a verdict, mint reviewer identity, or invoke developer-only
`--owner` authority. An unavailable profile returns a configuration decision;
it never falls back to the implementer's profile. Developer decisions enter
through the host's separately authorized developer channel. These are host
permissions and session roles, not claims of OS-user isolation or signatures.

Work item 9 must install the corresponding deny rules and role profiles on
**both Codex and Claude Code**: deny agent writes to state/receipt paths,
developer-only commands, self-approval and direct `main` push outside verified
integration. It must cover alternate shell/plumbing entry points, expose
profile identity to the launch interface, and test effective denials on both
hosts. Work item 8 supplies the interface, receipt checks and disposable-host
fixtures; it does not install or alter real host configuration. Until those
rules are effectively installed, report the host boundary as unavailable,
not as enforced by hashes alone.

The declared limit is the amended ADR's same-user limit. An agent that
intentionally bypasses host permissions (including another host/profile) can
rewrite receipts and data coherently. Cardine 1.0 claims no authenticity
against that agent. A protected signer outside the agent's reach is a later
extension, not a 1.0 dependency. This supersedes 075's stronger broker/store
and protected-principal proposal where it implies authenticity beyond host
permissions. F-E/FI1 installation manifest, baselines and capability/probe
authority are explicitly deferred after 1.0; they cannot authorize task
landing. SR1's repeatable installation effects do not extend that trust claim.

## Reconciled choices and existing inputs

The ordered rows consume these already assigned inputs; they are not new
implementation rows: **RX1 / 083**, **N2a / 084**, **N2b / 085** are assigned
and in progress as the work-item-8 input stream (not claimed completed by this
plan). They execute serially 083 → 084 → 085 and must be integrated before
RE1a. RX1 removes self-reported counters; N2a removes T-02/T-13/T-14/T-16
runtime reads and implements A-N2-1; N2b removes T-03/T-06/T-07/T-15/T-45
runtime reads. Their actual status comes from the task lifecycle. SS7 and
N1/079–081, G1/078 and delivery-gate removal/072 are prior inputs. Do not
reimplement them or add replacement tasks for them.

Choose the following resolutions where inventories overlap:

- Use `REVIEW_NOT_APPROVED`, causes `missing` and `stale`, instead of separate
  `REVIEW_REQUIRED`/`REVIEW_STALE` codes (076 A3/A6). Both need the same fresh
  independent review. An assigned live review is `waiting`; no automatic
  approval occurs. Keep `REVIEW_LOOP_EXHAUSTED` separate, emitted from two
  consecutive recorded `CHANGES_REQUESTED` rounds (074 A-RE4-2), because it
  requires a new budget decision rather than an ordinary verdict.
- Keep the registered `VALIDATION_RETRY_LIMIT` (074 A-RE3-1 and 076), removing
  the old plan's proposed `VALIDATION_RETRY_EXHAUSTED`. Preserve failing-work
  codes below the limit and distinguish candidate/task phases in facts.
- 073 removes prose gates and caller-declared result options; 075 supplies
  receipt coverage for their replacements. Apply both: RE3b measures actual
  results; RE5a derives dependencies, changed paths and interaction from Git
  and pinned policy, choosing FULL when independence cannot be proved. Delete
  the unconditional `interaction_assessment_complete: True`, not merely its
  prose checks. Never accept a fabricated receipt as a recovery shortcut.
- T-44's `T3_ATTESTED` file is retired as landing authority in RE6a. Human
  acceptance judgment uses a host-authorized developer decision receipt;
  arbitrary `attested_by: developer` JSON and agent-declared CI/shards are
  not an exception to decision 13.
- N3 does not add a new self-reported `execution evidence` kind after RX1.
  RE3b executes declared host-impact checks and writes typed observed proofs;
  N3 consumes them and removes the prose checks. Human-only judgments route
  to the explicit developer channel, never an agent success flag.
- Adopt 076's configuration/workflow/update-target consolidations in RE2b/2c.
  Its projected 21 guardrail codes are a snapshot expectation, not a quota:
  remove a code only after its last static, dynamic or judgment emitter is
  replaced, retaining every real authority negative.

## Ordered implementation tasks

This is the single implementation table. All estimates include the listed
focused tests and are at most three hours. All rows depend transitively on
SS7 and integrated 083–085. **Run every row serially in table order**, even
when its logical dependencies are smaller. This prevents parallel edits to
shared files, fixtures, registries and the ratchet. No future task record
needs to choose a split or design a missing trust mechanism.

Paths in the table use `src/cardine/` unless prefixed `tests/`, `schemas/`,
`capabilities/`, `scripts/` or `templates/`. New modules and focused test files
are named explicitly. `R` means `tests/test_text_gates.py`, including its
shared known-violation table; `C` means `cli.py`; `E` means
`lifecycle/engine.py`; `S` means `tasks/state.py` and
`schemas/task-state-v1.schema.json`; `K` means `capabilities/stop-codes-v1.json`
and `schemas/stop-codes-v1.schema.json`. These abbreviations are exact shared
files, not separate resources. Each row's shared-file column names its peers;
**all rows share this plan as context, not as an implementation output**.

Every effect test kills the operation immediately before and after each
listed boundary, invokes the identical command again, and checks convergence
without duplicate commits, verdicts, counters or deletion of foreign work.
Pure rows test repeated resolution with no writes. Every effectful row uses
RE1b receipts and checks changed-input and foreign-owner negatives. Every row
runs its named tests plus applicable repository baseline and clean-clone
checks in temporary consumers; no real-home setup or checkout `.cardine/`.
`None` in the ratchet column means assert no new key, not enlarge the allowlist.
Delete exact keys for the named T-ID and function only when the reader goes;
retain unrelated keys with the same T-ID. Sources/tests stay below 1,500 lines.

| Label / hours | Scope and files | Tests (under `tests/`) | Logical dependencies | Ratchet keys deleted | Rule 4 boundaries and interruption proof | Other rows sharing a file |
| --- | --- | --- | --- | --- | --- | --- |
| RE1a / 2h | Seven-step pure resolver, primary/common-dir/root resolution, closed output envelope and quoted argv; E, `lifecycle/model.py`, `schemas/run-v1.schema.json`, C | `test_run_resolution.py`, `test_run_output.py`: both presets, all steps, unrelated cwd/metacharacters, missing/ambiguous identity | SS7, RX1, N2a, N2b | None | Pure preview repeated byte-equivalently; no state/log writes or subprocess effects | E: RE1c, RE2d, RE3a, RE3b, RE4a, RE4b, RE5a, RE5b, RE6a, RE6b, RE7a; C: RE2d, RE4b, N3, RE5a, RE5b, RE6a, RE7b |
| RE1b / 3h | Durable intent/result writer, chaining, artifact verifier, schema and task locking; new `lifecycle/receipts.py`, S, `tasks/creation.py`; pin authorized main/runtime/policy and clone reauthorization | `test_run_receipts.py`, `test_task_creation.py`: coherent/incoherent state/contract/policy edits, receipt-less clone, concurrent writers and runtime override (F01–03/F12/F19/F20) | RE1a | None (creation remains allowed) | Intent, staged record/state pair, state replace and result receipt: replay finishes exact pair once; changed staged bytes fail closed | S: RE1c, RE3a, RE3b, RE4b; receipts: RE1c, RE3a, RE3b, RE4b, RE5a, RE5b, RE6a, RE6b, SR1a, SR1b |
| RE1c / 3h | Wire verified receipts into state/contract/dependency readers and transitions; preparation recovery with root binding; E, S, `tasks/transitions.py`, `tasks/contract.py`, `worktree/checkout.py`, receipt module | `test_run_preparation.py`, machine-state/worktree tests: F01/F02/F09, dirty owned Resume, path collision and dependency forgery | RE1b | None; input N2 removals stay removed | Branch create, worktree registration, lifecycle JSON, start transition: repeat exact owned partial pair; preserve unknown collision; never infer status from disk location | E/S/receipts peers above; transitions: RE4b; contract: N3; checkout: N3, RE6b |
| RE2a / 3h | Cause inventory and typed classification for worktree/state/lease/order/cleanup errors; `stops/{registry,render}.py`, K, checkout, transitions, `integration/merge.py`, `lifecycle/{commands,closure}.py`; enumerate dynamic/judgment emitters | `test_run_recovery.py`, registry tests: safe owned recovery versus corrupt identity, dirty foreign paths, protected branches, denied access | RE1c | None | Formatting/classification adds no effects; inject failure after each existing owned effect and assert classification preserves receipt/owner and no accidental retry | K/stops: RE2b, RE2c, RE2d, RE3b, RE4b, N3, RE7b; checkout: RE1c, N3, RE6b; transitions: RE1c, RE4b; merge: RE5a, RE5b, RE6b; commands: RE3a; closure: N3, RE5a, RE5b |
| RE2b / 2h | Consolidate approval/configuration/workflow codes; retain RULE_CONFLICT, approval causes and explicit authority negatives; K, stops, `review/verdict.py`, `tasks/{contract,preflight}.py` | `test_stop_registry.py`, `test_run_recovery.py`: last-emitter audit, missing policy versus resolvable installed profile | RE2a | None | No new effects; repeated diagnostics stable; verify consolidation never records approval or rewrites invalid state | K/stops: RE2a, RE2c, RE2d, RE3b, RE4b, N3, RE7b; verdict: RE4b; contract/preflight: N3 |
| RE2c / 3h | Cause audit for self-update, upgrade, host/OS catches; merge NON_FF into TARGET, plugin-cache owner routing; K, stops, `release/update.py`, `templates/upgrade_support.py`, `hosts/codex.py`; no new update behavior | `test_run_nonrun_causes.py`, updater/upgrade tests: target mismatch, plugin owner, missing generated output, busy/missing path versus permission denial | RE2b | None | Existing effects interrupted in disposable roots; classify residue without applying update/setup or bypassing consent; SR1 owns new reconciliation | K/stops: RE2a, RE2b, RE2d, RE3b, RE4b, N3, RE7b; update: SR1a; upgrade/host: SR1b |
| RE2d / 2h | Dispatch typed outcomes through shared renderer; C, E, stops; progress/next/waiting/iterate never print BLOCKED, journal resolution preserved | `test_run_output.py`, `test_run_recovery.py`: executable exact recovery commands, unknown failures fail closed | RE2c | None | Diagnostic output interruption cannot change operation state; rerun same owned next action rather than duplicating effect | C/E peers RE1a; stops peers RE2a |
| RE3a / 3h | Scope enforcement and committed delivery identity; E, S, receipt module, `lifecycle/{execution,commands}.py`, new `lifecycle/scope.py`; delivery precedes validation without self-certified acceptance | `test_run_scope.py`, `test_run_delivery.py`: rename/delete/untracked/symlink escapes, F15, real deliverables, forged delivery | RE2d | None | Delivery state write, add, commit and receipt: commit only owned paths, recognize existing commit once, preserve original source identity | E/S/receipts peers above; execution: N3; commands: RE2a |
| RE3b / 3h | Automatic task command runner on the per-task `.cardine/evidence/<TASK-ID>.json` layout (096), frozen scoping/skips, host-impact observations, retry/intermittence counters and EVIDENCE_INCOMPLETE recovery; new `lifecycle/validation.py`, `tasks/{evidence,recording}.py`, S, E, K, receipt module, R | `test_run_validation.py`: actual exits, N failures, one unchanged full rerun, changed environment/source, stale ledger, F04/F05/F15; run emitted recovery to C6/C7 | RE3a | None yet for T-38/39 adapters (RE5a removes them); replace T-20 fact dependency, N3 deletes prose gate | Intent, process start/exit, log/evidence writes, counter/result: interrupted unknown process reruns without invented success or double count; compare inputs before/after | E/S/receipts/K peers above; evidence: RE5a, RE5b, RE6a; R: N3, RE5a, RE5b, RE6a, RE7b |
| N3 / 3h | Delete handoff/report gates and HANDOFF codes; `tasks/{contract,preflight,transitions}.py`, `lifecycle/{execution,closure}.py`, checkout, C, K, R; product completion/review templates, catalog/baselines; typed host proof from RE3b replaces prose | `test_run_handoff.py`, execution/review/worktree tests: paraphrased/absent handoff fields change no gate; missing actual observation reruns checks | RE3b | T-04, T-19, T-20, T-21, T-23 (including CLI/import references); T-22 already gone | Removing prose reads is pure; template regeneration interrupted before/after baseline write converges; real delivery still uses RE3a transaction | C/K/R peers above; contract/preflight: RE1c, RE2b; transitions: RE1c, RE2a, RE4b; execution: RE3a; closure: RE2a, RE5a, RE5b; checkout: RE1c, RE2a, RE6b; templates/catalog/baselines: TR1a, TR1b, TR2a, TR2b |
| RE4a / 3h | Host-neutral implementer/reviewer launch with distinct profile and role/session request identities; new `hosts/launch.py`, E; injected Codex/Claude profile adapters, no real-home installation | `test_run_host_roles.py`: both fake hosts, missing profile refuses fallback, implementer denied verdict/developer/push paths | N3 | None | Request persistence, session spawn, response receipt: restart polls/reconciles same session; never spawn a second reviewer or exchange role tokens | E peers RE1a; launch: RE7a |
| RE4b / 3h | Bind verdict/cancel/owned abort to issued roles and operations; two changes-requested loop budget; `review/verdict.py`, transitions, E, S, C, K, receipt module, `integration/merge.py`, new `lifecycle/control.py` | `test_run_review.py`, `test_run_control.py`: F01/F11 owner spoof, stale review, loop limit, cancel retains branch/new task restart, repeated owned abort | RE4a | None (T-25 projection/import residue assigned to RE7b/W10 below) | Verdict state write then Markdown projection; cancel transition; abort merge/state/lease unlink: resume missing output once with unchanged verdict/time, preserve foreign lease | E/S/C/K/receipts peers above; verdict: RE2b; transitions: RE1c, RE2a, N3; merge abort implementation: RE2a, RE5a, RE5b, RE6b |
| RE5a / 3h | Landing interface/direct strategy, pinned policy/Git interaction assessment, remove caller acceptance/dependency/surface authority; new `integration/{landing,direct}.py`, `integration/{decision,evidence,merge}.py`, closure, C, E, receipt module, R | `test_run_integration_decision.py`: REUSE/BOUNDED/FULL, F06–F10/F16, changed main, empty declarations cannot assert independence | RE4b | T-38, T-39, T-41, T-42 including advance/evidence accepted/exit/surface options and record_task_evidence readers | Lease create, merge, landed-state/view regeneration, integration JSON: recover exact owned candidate or restore pre-stage tree; no foreign abort | C/E/receipts/R peers above; merge: RE2a, RE4b, RE5b, RE6b; closure: RE2a, N3, RE5b; direct: RE5b, RE6a, RE6b; evidence: RE3b, RE5b, RE6a |
| RE5b / 3h | Execute candidate commands using RE3b runner, verified tree evidence, finalize/abort reconciliation and bounded competing lease wait; direct, merge, evidence, closure, C, E, receipts, R | `test_run_integration.py`: changed tree/config, concurrent tasks, textual conflict versus transient Git error, candidate failure shares task allowance | RE5a | T-40, T-43 (candidate exit options and passed/commands file authority) | Candidate result write, merge commit, integration JSON and lease unlink: repeat returns same landed commit; wait ≤60s/poll ≥5s then waiting, release recomputes main; abort only own candidate | Shared direct/merge/evidence/closure/C/E/receipts/R: peers RE5a and above |
| RE6a / 3h | Exact-repository/SHA CI provider queries and authenticated cache; new `integration/ci.py`, direct, evidence, C, E, receipt module, R | `test_run_ci.py`: fake gh, no-gh default, one task push per delivered head/review attempt, pending/failed/wrong SHA, fabricated CI/shard/developer JSON and local tracking refs | RE5b | T-44, retiring external attestations as authority | Task push accepted before response, CI query before cache/result: query actual remote/provider before retry; no second blind push or wrong-head cache use | direct/evidence/C/E/receipts/R peers above |
| RE6b / 3h | Main push verification, expected-old-OID remote deletion and local cleanup; direct, merge, checkout, E, receipt module | `test_run_cleanup.py`, bare-origin subprocess tests: remote advancement, protected refusal, uncertain transport, compare-delete race, reused path/branch negatives | RE6a | None | Main push accepted, remote compare-delete, worktree remove/placeholder, local branch delete, lifecycle removal: prove exact remote and landed tip at every retry; never force cleanup | direct/merge/checkout/E/receipts peers above |
| SR1a / 3h | Non-run self-update operation identity and pinned target across retries; `release/update.py`, receipt module | `test_update_repeatability.py`: fetch/apply/verify injection, new latest release during retry, dirty/plugin ownership negatives | RE6b, RE2c | None | Fetch, pinned fast-forward/switch, final verification: resume original target, recognize applied HEAD/VERSION; no history rewrite or plugin bypass | update: RE2c; receipts peers RE1b |
| SR1b / 3h | Non-run upgrade/host write reconciliation in disposable roots; `templates/{upgrade,upgrade_support}.py`, `hosts/{codex,claude,setup}.py`, receipt module; enumerate each writer before wiring it | `test_upgrade_repeatability.py`, `test_host_repeatability.py`: multi-file partial apply, user edit/symlink/denied home and consent negatives | SR1a | None | Each managed-file replace, host block write and verification: repeat exact authorized outputs, preserve changed user regions; no real-home apply or installation-authenticity claim | upgrade/host: RE2c; receipts peers RE1b |
| TR1a / 3h | Rewrite product always-read templates: routers, workflow, role procedures, orchestration/context policy; fold CODE_REVIEW_PROMPT and INTEGRATION_POLICY into REVIEW; `templates/single/`, catalog/baselines, `scripts/check_repository.py` (replace CX-13 prose pins in this same row) | `test_template_word_budget.py`, template/marker tests: 074 entry actions, enforced/advice/delete classification, no orphan instructions | SR1b, RE6b | None | Template and marker-baseline replacements: interrupt generation, rerun matches fresh generation and preserves project overlays | templates/catalog/baselines: N3, TR1b, TR2a, TR2b; script: TR1b, TR2b |
| TR1b / 3h | Guard real word/byte budgets, command existence and nonhuman-stop prose; fix 074 defects 1 (relative-reference resolution) and 2 (ineffective ceilings); `shared/context.py`, `scripts/check_repository.py`, template tests, catalog/baselines, templates | `test_template_word_budget.py`, `test_template_commands.py`: argparse R4 check, full role read sets and negative over-budget/missing command fixtures | TR1a | None | Check is read-only; repeat from unrelated cwd. Capability/baseline regeneration interruption yields identical verified output | script: TR1a, TR2b; templates/catalog/baselines: N3, TR1a, TR2a, TR2b |
| TR2a / 3h | Condense product WORKTREE_LIFECYCLE, TASK_BLUEPRINT, COMPLETION_REPORT_TEMPLATE, EXECUTION_EVIDENCE_PROFILE, REVIEW_RECORD_TEMPLATE to 074 budget; templates and catalog/baselines | template/marker and word-budget tests: free-form report never required, creation skeleton retained, no lost enforced rule | TR1b, N3 | None | Regeneration before/after every file replace converges; no consumer host apply | templates/catalog/baselines: N3, TR1a, TR1b, TR2b |
| TR2b / 2h | Condense product AUDIT_PROMPT_READ_ONLY, OPERATOR_PROMPTS, CODE_ORGANIZATION; delete folded documents and stale pins; templates, catalog/baselines, `scripts/check_repository.py` | template commands/word-budget/marker tests: links resolve, all 074 moved entries have a destination | TR2a | None | Delete/regenerate/baseline boundaries repeat safely in fixture; user-owned files remain | templates/catalog/baselines: N3, TR1a, TR1b, TR2a; script: TR1a, TR1b |
| RE7a / 3h | Console read-only preview/actions and authenticated flow observations; `console/{snapshot,state,launch,render}.py`, `shared/flow.py`, `hosts/launch.py`, E; preserve explicit legacy installation reader | console/legacy fixtures, `test_run_console.py`: stale/forged F13/F18 telemetry labelled unverifiable, no policy/identity prose fallback or rendering effects | TR2b | None | Preview performs no writes; launch interruption resumes issued operation/session through RE4a; never reexecutes step on render | E peers RE1a; host launch: RE4a |
| RE7b / 3h | Final Internal adapter/judgment-emitter audit, complete recovery/forgery matrix and product command docs; C, stops/K, R, `tests/test_run_end_to_end.py`, `tests/test_run_recovery.py`, new `docs/RUN_COMMANDS.md` | Both presets/all seven steps, every then-current registry entry and F01–F20 within declared boundary; execute recovery unchanged from unrelated cwd; legacy isolation; only authority/decision/info events blocked | RE7a, all preceding rows | T-25 only remaining nonlegacy append/projection access (remove unused read or narrow integrity allowance with proof); assert residual set below, no new exceptions | Replay matrix crashes every preceding listed effect, interleaves integrations; journal event write contains cause/resolution/owner/operation/next; historical unverifiable events never gate progress | C/K/stops/R peers above; recovery tests: RE2a–RE2d; command docs: no template ownership |

TR1/TR2 edit **product templates only**, never the frozen installed governance
of this repository. Follow the pre-1.0 capability version/baseline rule without
migrations or VERSION changes. The combined budget is 5,600 words/40,000 bytes;
router+workflow+language ≤1,100/8,000, any role start ≤1,400/10,000,
role with later phases ≤2,700/20,000, workflow ≤750/5,400 and every other
single document ≤650/4,700. Measure both Codex and Claude routes, retaining
language-policy content. Use 074's per-file destination/Keep table, not a new
editorial policy. These separate rows replace the oversized TR1/TR2 proposals.

At RE7b the ratchet's known-violation table must hold **only** work item 9's
T-46/T-47 and work item 10's T-27/T-31 plus importer-only T-25 references
(review append reads are removed or justified as non-gating projection, never
silently deferred). Move importer and its remaining queue/review readers to
`cardine.legacy` in work item 10; until then keep their exact keys, never allow
them in product dispatch. All runtime input keys assigned to 083–085 must be
gone. The permanent allowlist still has only creation, managed integrity and
isolated legacy classes. The table is **not required to be empty**. Recovery
coverage, by contrast, has no deferred live nonhuman outcome: each remaining
recoverable code has an executable progress proof or its last emitter is gone.

## Amendment disposition

IDs below are inventory proposal IDs, not task authorization. This mapping is
exhaustive for the requested inventories; split labels refer to the table.

| Inventory / amendment | Destination and disposition |
| --- | --- |
| 074 A-RE1-1 | RE1b/RE1c: output/state digests and coverage checks within amended host boundary |
| 074 A-RE3-1 | RE3b: VALIDATION_RETRY_LIMIT; reject duplicate EXHAUSTED spelling |
| 074 A-RE3-2 | RE3b: engine resolves frozen validationScoping, records real skips |
| 074 A-RE4-1 | RE4a/RE4b: distinct issued reviewer profile, developer-only owner channel |
| 074 A-RE4-2 | RE4b: two consecutive changes-requested rounds produce REVIEW_LOOP_EXHAUSTED |
| 074 A-RE4-3 | RE4b, TR1a/TR2b: preserve cancelled branch, restart as new task; delete rejected archive/retry-ref ritual |
| 074 A-RE7-1 | RE7b product command docs only; TR1a–TR2b own template prose |
| 074 RX1 | Assigned input 083; no new row |
| 074 TR1 | TR1a/TR1b: rewrite then budget/command/stop guards and prerequisite defect fixes |
| 074 TR2 | TR2a/TR2b: reference documents, folded-file deletion and stale checks |
| 074 A-N2-1; A-SS7-1 | Input 084; input SS7 plus TR1a/TR2a for remaining obsolete template sentences respectively |
| 075 F-A; RE1 amendment | RE1b/RE1c and downstream receipt consumers; reject stronger protected signer/store requirement for 1.0 in favor of amended ADR host permissions and declared limit |
| 075 F-B | RE1b pins accepted main/runtime/rules/policy; RE5a derives candidate needs; policy changes cannot authorize themselves |
| 075 F-C; RE3 amendment | RE3a/RE3b: measured command/acceptance evidence and changed-input checks; N3 retires prose checks |
| 075 F-D; RE4 amendment | RE4a/RE4b role-profile authority and bound verdicts; RE6a provider facts; no claim of same-user cryptographic authorship |
| 075 RE5 amendment | RE5a/RE5b: covered leases/candidate outputs, no caller scope/interaction/pass authority; FULL if independence unknown |
| 075 RE6 amendment | RE6a/RE6b: actual provider/remote facts and receipt-covered reusable results |
| 075 RE7 amendment | RE7a/RE7b: verified console facts, unverifiable history labelled, legacy identity fallback absent and forgery matrix |
| 075 F-E / FI1 | Deferred after 1.0 by developer: installation authority excluded; SR1 does not implement FI1 |
| 076 A1 | RE1c partial creation; RE2a–RE2d enumerate all static/dynamic/judgment emitters and cause splits |
| 076 A2 | RE3a delivery interruption; RE3b measured retries; N3/RE5a–RE5b remove declared-result authority |
| 076 A3 | RE4b review/cancel/abort repeatability and loop limit; RE2b consolidated approval causes; N3 handoff removal |
| 076 A4 | RE5a/RE5b lease waiting, transient/textual merge distinction and every stage/finalize boundary |
| 076 A5 | RE6a/RE6b remote/CI/push/delete query and reconciliation |
| 076 A6 | RE2b/RE2c consolidation; retain real negatives, 21 is snapshot expectation rather than hardcoded target |
| 076 A7 | RE2c non-run upgrade/host/OS cause audit; dispatcher does not run setup/update |
| 076 A8 | RE2d resolution rendering; RE7b judgment routes and cause/owner/operation/next telemetry, no historical rewrite |
| 076 SR1 | SR1a/SR1b split updater from upgrade/host effect reconciliation, each ≤3h |
| 073 N3 | N3 after measured RE3b facts; reject new self-reported evidence kind because RX1 removes that authority |
| 073 RE3 amendment: T-20, T-38, T-39 | RE3b supplies actual task results; N3 deletes T-20 prose check; RE5a deletes T-38/T-39 adapters when candidate consumer switches |
| 073 RE5 amendment: T-40–T-43 | RE5a deletes interaction declarations and resolver reads T-41/42; RE5b removes T-40/43 candidate claims |
| 073 RE6 amendment: T-44 | RE6a provider-measured CI/shards, T3_ATTESTED JSON retired; explicit human decisions use RE4b channel |
| PROJECT_PLAN deferred EVIDENCE_INCOMPLETE recovery | RE3b end-to-end exact returned command runs missing validation or returns unfinished acceptance work, then reaches C6/C7 |
| PROJECT_PLAN deferred mixed guardrail split | RE2a/RE2b/RE2c audit and RE2d dispatch; integration/push cause proofs in RE5b/RE6b |

No row authorizes paid weak/strong-model evaluations. RE7b provides the
scenarios and metrics (completion, stops by class, denied actions and
shortcuts) for separately authorized runs after work item 8.
