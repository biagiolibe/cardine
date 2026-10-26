# Stop review — decision 14

## Snapshot and method

Reviewed on `main` commit `bf85ca68831acb6af28fc2c487b3182ca06f9add`
(2026-10-22), from task 076's worktree. This is a proposal, not a change to
Cardine's registry or to the installed Meridian lifecycle. Decisions 6, 12
and 14 of [the product ADR](ADR_CARDINE_1_0.md) govern the recommendations;
[Stops and Denials](ADR_STOPS_AND_DENIALS.md) explains the older gate contract.

The registry contains **51 codes: 27 guardrails, 7 recoverable and 17
failing-work**. These are registry classifications, not a count of actual
human decisions. `stops/render.py::format_stop` still formats every code as
`BLOCKED`; `cli.py:909-916` turns all remaining `CardineError` and `OSError`
exceptions into two generic guardrails. Classification without changing
these paths cannot implement decision 12.

The live journal is outside the tracked tree. Freeze its first **762 JSONL
lines**, ending at task 076's `check`, `2026-10-22T13:04:38Z`; their byte-prefix
SHA-256 is `44c074877b6789bb560362d40fc4e4e81f71b8b21e80ff701bacdaabdf63a136`.
This includes **17 blocked events**, not the ADR's earlier 15. The two later
events are task 069's conflict and task 072's candidate failure. Keep this
boundary when reproducing the review after further integrations.

Repeat from the named commit (Git reads use that commit; use a disposable
checkout to reproduce the Python source scan):

```sh
C=bf85ca68831acb6af28fc2c487b3182ca06f9add
git show "$C:capabilities/stop-codes-v1.json"
git grep -nE 'stop_error\(|format_stop\(|CardineStop\(|refuse\(' "$C" -- src/cardine
git grep -nE 'stop_reason|stop_code|CardineError|OSError' "$C" -- src/cardine
git grep -nE 'BLOCKED|WRONG_WORKTREE|COMMAND_REFUSED|LEASE_HELD|stopped with|Closure recovery' "$C" -- tasks/handoffs
git grep -nE 'VALIDATION_RETRY_LIMIT|REVIEW_REQUIRED|WORKFLOW_UNREADABLE|RULE_CONFLICT|SCOPE_CHANGE_REQUIRED|REVIEW_LOOP_EXHAUSTED' "$C" -- templates/single
python3 - <<'PY'
import ast, collections, hashlib, json, pathlib, subprocess
registry = json.loads(pathlib.Path('capabilities/stop-codes-v1.json').read_text())['stops']
print(collections.Counter(x['resolution'] for x in registry))
sites = {x['code']: [] for x in registry}
for path in sorted(pathlib.Path('src/cardine').rglob('*.py')):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in sites:
            sites[node.value].append(f'{path}:{node.lineno}')
for code, locations in sites.items():
    print(code, locations or 'check judgment/command-exit and dynamic emitters')
common = pathlib.Path(subprocess.check_output(
    ['git', 'rev-parse', '--git-common-dir'], text=True).strip()).resolve()
prefix = b''.join((common / 'meridian-journal.jsonl').read_bytes().splitlines(keepends=True)[:762])
print('prefix SHA-256', hashlib.sha256(prefix).hexdigest())
rows = [json.loads(line) for line in prefix.splitlines()]
blocked = [(i + 1, r) for i, r in enumerate(rows) if r.get('result') == 'blocked']
print(collections.Counter(r['stop_code'] for _, r in blocked))
for line, row in blocked:
    print(line, row)
PY
```

Read each match in its function, including dynamic code arguments and
`closure_status` reports; a string occurrence alone is not an emitter.
The journal records command, task, code, time and step, **not exception
details**. Causal uncertainty below is deliberate. No product command was run
to reproduce historical failures against the real repository.

For prose gates, use [Text gate inventory](TEXT_GATE_INVENTORY.md), especially
T-01–T-23, T-25–T-29, T-38–T-44, T-47 and N1–N3. This review refers to those
entries rather than repeating their parser inventory. SS6 has already landed
as task 069: archival and queue-projection recovery must not be brought back.
SS7 remains the destination for console routing. The installed lifecycle is
older and still archives this repository's task records.

## Every registered code

**G** = guardrail; the person supplies the stated authority, decision or
information. **R** = resolution/next action; **W** = bounded waiting;
**F** = implementation work within the retry budget; **D** = delete the code
when its last emitter is removed. A mixed row keeps its guardrail only for
the stated human cause; RE2 must give the other causes separate outcomes.
Paths below are relative to `src/cardine/`. Destination amendments A1–A8 and
new row SR1 are specified later; they are proposals, not existing row scope.

| Code (current class) | Emitter and cause; what a person brings, or replacement | Destination |
| --- | --- | --- |
| `STALE_WORKTREE_BASE` (R) | `worktree/checkout.py::prepare_task_worktree`, `repair_task_worktree_base`, inspection and `closure_status`. No person: repair only a proven commit-less fast-forward, preserve start time, invalidate old validation, rerun it. Do not infer this from a dirty or divergent branch. | RE2 existing stale-base scope; RE1 receipts |
| `ACCEPTANCE_UNMET` (F) | `closure_status` C1 and `lifecycle/closure.py` C5. No person for unfinished authorized work: return implementation with the unmet criterion. A genuinely new criterion is `SCOPE_CHANGE_REQUIRED`. | RE3 existing implementation routing |
| `VALIDATION_RETRY_LIMIT` (G) | Managed `PROJECT_WORKFLOW.md` judgment after N counted failures; no current Python emitter. Person decides whether to change scope, abandon, or authorize another budget. Keep; move counting to the engine, never delete merely because the present emitter is prose. | RE3 existing retry state; RE7 A8 |
| `VALIDATION_FAILED` (F) | `integration/evidence.py::check_validation_evidence`, closure C5 and declared command exits. No person: unchanged rerun once, record intermittence or count failure, return repair work. | RE3; RE6 for external CI. **Task 106 (RE6a)**: `check_validation_evidence` is gone; a required check that concludes unsuccessfully for the delivered SHA returns `VALIDATION_FAILED` failing work from `integration/ci.py`. |
| `REVIEW_REQUIRED` (G) | Workflow judgment, no Python emitter. Person supplies independent review. Same missing-approval fact as `REVIEW_NOT_APPROVED`: merge into that code, retaining cause `missing`. Never synthesize approval. | RE4 A3; RE2 registry |
| `WRONG_WORKTREE` (G, mixed) | `worktree/checkout.py` prepare/check/base repair, `lifecycle/execution.py` location/cleanliness and CLI check. Ordinary cwd/project selection is R: resolve primary and canonical task root and dispatch there. Authorized task-owned dirty Resume is R, not corruption. Contradictory recorded identity, path collision, foreign writes or unproven base need owner information/authority: retain G. | RE1 root resolution; RE2 existing split |
| `EVIDENCE_INCOMPLETE` (R) | `closure_status`, `lifecycle/execution.py::delivery_readiness`, `commands.py::execution_deliver`, closure C5. No person: run missing/stale validation, finish owned delivery writes/commit, or return implementation work. Repeatedly returning the same evidence instructions without performing them does not recover. | RE3 explicit runnable recovery; A2 |
| `PRIMARY_DIRTY` (G, mixed) | `integration/merge.py::stage_task_integration`, `closure_status`. Engine-owned pending candidate/state changes are R under an operation receipt. Foreign/unattributed changes require owner authority to retain, move or commit; never stage them wholesale. Another live integration is W. | RE2 existing split; RE5 A4 |
| `MAIN_BEHIND_ORIGIN` (R) | `integration/merge.py` stage ancestry gate. No person when fast-forward is proven: fetch and fast-forward, reassess candidate/evidence. Divergence requires a decision; never reset/rebase to clear it. | RE2 existing fast-forward scope; RE5 |
| `LEASE_HELD` (G, mixed) | `integration/merge.py` retained lease/exclusive-create race; `closure_status` C6. Proven same-task interrupted operation is R (continue matching candidate or owned abort). Another valid live task is W. Unverifiable, corrupt or foreign ownership needs owner information/authority: G. Existence alone proves neither liveness nor permission to abort. | RE2 existing split; RE5 A4 |
| `INTEGRATION_CONFLICT` (G, mixed) | `integration/merge.py` tests any nonzero merge result, attempts abort, then emits this code. A verified textual conflict needs a human conflict-resolution decision. A lock/transient Git failure with no unmerged entries is R/W; inspect return status and index first. An abort failure must retain ownership and expose recovery, not claim an abort succeeded. | RE2 A1; RE5 A4 |
| `CANDIDATE_VALIDATION_FAILED` (F) | `lifecycle/closure.py` C7 aborts on nonzero supplied results. No person before budget exhaustion: owned abort, return candidate diagnostics to implementation and revalidate the new candidate. Keep separate from task validation by phase; shared F rendering can use one validation-result type. | RE5 existing candidate retry/abort; RE3 counting A2 |
| `EVIDENCE_MISMATCH` (R, mixed) | `integration/merge.py` stage/finalize checks current commit/tree, evidence shape, pass/scope/commands. Stale genuine evidence is R: rerun the appropriate validation and bind new results. Fabricated receipts or changed protected inputs require authority/information; do not bless them by regenerating from agent claims. | RE5 existing candidate execution; RE2 A1 |
| `PUSH_PENDING` (R, status) | `closure_status` C9 and closure driver. No person: normal push, then query remote ancestry after an uncertain response before repeating. Already a status, never count as a blocked event. | RE6 existing push reconciliation |
| `PUSH_REJECTED` (G, mixed) | Declared `git push origin main` exit/judgment; no Python stop emitter yet. Permission/protected-branch refusal needs authority or a landing-policy decision. A transport timeout is R/W after querying the remote; an advanced remote requires fresh ancestry/candidate checks. Preserve code for actual refusal. | RE6 existing rejected-push cases; A5 |
| `CLEANUP_BLOCKED` (G, mixed) | `integration/merge.py::cleanup_task_worktree`. Missing directory, remaining owned branch, pending push or same-task lease are R; live other integration is W. Unmerged/protected branch, denied access or foreign dirt requires authority. Never force-delete. | RE2 existing split; RE6 existing cleanup/race scope |
| `UNDECLARED_VALIDATION_COMMANDS` (G) | `integration/evidence.py` declaration gate, merge finalize and closure C7. Person supplies trusted command configuration when absent. If valid frozen configuration exists, resolve it automatically. Use this one configuration guardrail also for missing execution profile; include the missing field/source in detail. | RE5 resolved config; RE2 A1 |
| `EXECUTION_CONTRACT_UNRESOLVED` (R) | `tasks/preflight.py` missing/stale resolution. No person when declared contract inputs exist: resolve from trusted inputs. If required human inputs are absent, return the named contract decision instead of looping. | RE1 resolver; RE2 existing contract scope |
| `EXECUTION_PROFILE_MISSING` (G) | `tasks/contract.py::read_execution_profile`. Person supplies missing validation policy; tool can resolve a known installed profile. Merge this emitter-specific name into `UNDECLARED_VALIDATION_COMMANDS` with cause `execution-profile`. | RE2 A1; RE5 config |
| `VALIDATION_ENTRY_FORMAT` (F) | `tasks/evidence.py::require_named_validation_commands`. No person for formatting: validate once at task creation, return field diagnostics. Later execution reads the snapshot. Retire this Markdown gate after T-15/N2; do not retain a second runtime parser. | RE3 A2; removal with T-15 |
| `TASK_RECORD_INCOMPLETE` (F) | `tasks/preflight.py` section checks. No person for cosmetic missing sections: D with the prose gate. Missing actual contract authority remains a named creation-time decision. | RE2 A1; T-01/N1/N2 removal |
| `TASK_STATUS_REJECTED` (G, mixed) | `tasks/preflight.py`, `lifecycle/commands.py`, `execution.py`, `tasks/transitions.py`. Already-started/closed and wrong command order are R: compute next step or return already done. Pending dependency is W; a failed/cancelled dependency needs a human scope/result decision. Malformed input is F. Forbidden transition or undeclared cancellation requires authority: G. | RE2 existing split; RE1 resolver; RE4 cancel |
| `EXECUTION_EVIDENCE_ARGUMENTS` (F) | `tasks/recording.py` missing/invalid options. No person: return structured argument diagnostics; run-engine-owned validation no longer asks an agent to assemble results. Preserve for remaining Stable evidence inputs only while they have an emitter. | RE3 A2; RE2 emitter audit |
| `HANDOFF_REPORT_MISSING` (F) | `tasks/contract.py` and `tasks/transitions.py::close_task`. No person: D with handoff-as-gate; an optional readable report is not execution evidence. | T-19/N3 removal; RE4 A3 |
| `HANDOFF_FIELDS_MISSING` (F) | `tasks/contract.py::check_handoff`. No person: D, not another formatting recovery. | T-19/N3 removal |
| `HANDOFF_FIELD_FORMAT` (F) | Same emitter. No person: D. | T-19/N3 removal |
| `HANDOFF_TASK_MISMATCH` (F) | Same emitter. No person: use machine identity; D. | T-19/N3 removal |
| `HANDOFF_VALIDATION_FAILING` (F) | `tasks/contract.py::verify_validation_skips`. No person: D prose check; use actual failing validation F result. | T-20/N3 removal; RE3 A2 |
| `HANDOFF_VALIDATION_EVIDENCE_MISSING` (F) | `tasks/contract.py::verify_execution_evidence`. No person: D duplicate handoff gate; engine runs missing validation under `EVIDENCE_INCOMPLETE`. | T-21/N3 removal; RE3 |
| `HANDOFF_EXPLORATION_MISMATCH` (F) | `tasks/contract.py::verify_exploration_summary`. No person: D report comparison. | T-19/N3 removal |
| `HANDOFF_EXPLORATION_SUMMARY_MISSING` (F) | Same verifier. No person: D report comparison. | T-19/N3 removal |
| `COMMAND_REFUSED` (G, mixed) | `cli.py` catch-all `CardineError`; `hosts/codex.py:67` damaged managed markers. Wrong cwd, missing option, lifecycle ordering and owned residue are R/F/W at their source. Unknown/corrupt ownership or required host configuration changes need information/authority: G. Retain a fail-closed unknown diagnostic, but it must not swallow known causes. | RE2 existing split; RE7 adapter audit; A7 for host path |
| `OS_ACCESS_FAILED` (G, mixed) | `cli.py` catch-all `OSError`. Permission/sandbox denial needs access authority; do not retry through another surface. Missing owned parent is R; busy locks are bounded W; resource exhaustion is bounded R then an honest unavailable result. Arbitrary missing user input needs information. | RE2 existing split; A7 for non-run adapters |
| `VALIDATION_ID_UNDECLARED` (F) | `tasks/recording.py::run_validation`. No person: choose the frozen declared ID, return accepted IDs for invalid CLI input. If a genuinely new command is needed, obtain a contract amendment. | RE3 A2 |
| `HOST_IMPACT_DECLARATION_INVALID` (F) | `tasks/contract.py::task_host_impact`. No person for table shape: creation-time schema diagnostics. Missing actual host-policy choice needs information once. D runtime Markdown parser. | T-03 removal; RE2 A1 |
| `HOST_IMPACT_EVIDENCE_MISSING` (F) | `tasks/contract.py::verify_host_impact_completion_evidence`. No person: run declared checks or return implementation; D handoff gate after typed engine evidence replaces it. | T-04/N3; RE3 A2 |
| `UPGRADE_BLOCKED` (G, mixed) | `templates/upgrade_support.py` project merge conflict or router requirement. A project-owned content conflict needs a decision. A known missing generated router can be planned automatically, within upgrade authority; no automatic consent to host/home edits. | RE2 A7 classification; SR1 for effects |
| `WORKFLOW_UNREADABLE` (G) | Managed entry-document judgment, no Python emitter. Restore provably generated missing material only within existing authority; contradictory or unavailable policy requires human information/decision. Merge the remaining human policy-conflict cause into `RULE_CONFLICT`, with missing-source detail. | RE2 A1; RE7 A8 |
| `RULE_CONFLICT` (G) | Managed workflow judgment, no Python emitter. Person decides which conflicting authorities to amend. Keep and report both sources; accepted command behavior does not override a denial. Receives unresolved workflow-policy cases above. | RE7 A8 |
| `SCOPE_CHANGE_REQUIRED` (G) | Managed implementation/remediation/context judgment, no Python emitter. Person supplies new scope/authority or unknown acceptance information. Keep; RE3 adds machine path-surface enforcement, but cannot decide a new requirement. | RE3 existing scope enforcement; RE7 A8 |
| `REVIEW_LOOP_EXHAUSTED` (G) | Managed `docs/LIFECYCLE_ORCHESTRATION.md` judgment after two unresolved review rounds. Person chooses further budget, scope or abandonment. This has a real prose emitter; keep separate from validation exhaustion by budget type. | RE4 A3; RE7 A8 |
| `TASK_STATE_MISSING` (R, mixed) | `tasks/state.py`, integration state check, repeated start and console probes. Known interrupted engine creation is R from authenticated inputs/receipt. Missing untrusted legacy state is not automatically reconstructed from a record to make a gate pass: require explicit import authority/information. Read-only console probes stay diagnostics. | RE1 state resolution; RE2 A1; SS7 console |
| `TASK_STATE_INVALID` (G, mixed) | `tasks/state.py`, importer, transitions, review, integration evidence/merge and console snapshot. Bad CLI value/wrong order is F/R; intact owned unfinished write is R. Corrupt history, foreign identity, forbidden `done` or absent cancellation authority needs authority/information: G. Never rewrite invalid general state from prose. | RE2 existing split; RE1 receipts; RE4 |
| `REVIEW_NOT_APPROVED` (G) | `integration/merge.py::_integration_task_state`. Person supplies independent verdict for the exact delivered source. Keep as the one approval guardrail; missing/stale causes share routing. An already assigned review can be W until the reviewer returns; it never becomes automatic approval. | RE4 A3; SS6 already preserves review gate |
| `REVIEW_STALE` (G) | `integration/merge.py`, `review/verdict.py`. Fresh independent review is what the person brings; invalidate stale approval and route delivery/review automatically. Merge into `REVIEW_NOT_APPROVED`, cause `stale`, preserving diagnostics and stale-review negative tests. | RE4 A3; RE2 registry |
| `SELF_UPDATE_PLUGIN_CACHE` (G) | `release/update.py::run_self_update` through `refuse(code, detail)`. No new person decision merely to locate the owner: R, return the plugin-manager operation. Executing a newly unauthorized manager/home change still needs authority. | RE2 existing SELF_UPDATE classification; SR1 |
| `SELF_UPDATE_DIRTY` (G, mixed) | Same updater. User edits require an owner decision to preserve/commit; tool-owned fetch residue does not. No blanket stash or discard. | RE2 existing classification; SR1 |
| `SELF_UPDATE_BRANCH` (G) | Same updater. Person decides to leave a development branch or change the requested update strategy; do not switch away from their work automatically. Known eligible root selection itself is R. | RE2 existing classification; SR1 |
| `SELF_UPDATE_TARGET` (G, mixed) | Same updater. Invalid argument shape is F; network resolution is bounded R/W. Unpublished/mismatched release identity needs trustworthy release information or a different target decision. Keep G for the latter. | RE2 existing classification; SR1 |
| `SELF_UPDATE_NON_FF` (G) | Same updater. Person must choose an eligible target/strategy; never rewrite history. Merge into `SELF_UPDATE_TARGET`, cause `non-fast-forward`; branch ancestry remains explicit. | RE2 existing classification plus A6; SR1 |
| `SELF_UPDATE_VERIFY` (G, mixed) | Same updater catches Git/OSError and post-apply mismatch. Transient fetch is R/W with pinned target. Unexpected final HEAD/VERSION or changed release identity needs information/authority: G. Replanning latest after interruption can widen an earlier update. | RE2 existing classification; SR1 |

## Registry consolidation and expected guardrails

Do not equate “no Python literal” with “unused”. The source scan finds seven
codes without product literals: `VALIDATION_RETRY_LIMIT`, `REVIEW_REQUIRED`,
`PUSH_REJECTED`, `WORKFLOW_UNREADABLE`, `RULE_CONFLICT`,
`SCOPE_CHANGE_REQUIRED`, `REVIEW_LOOP_EXHAUSTED`. Six have explicit managed
judgment emitters; `PUSH_REJECTED` is the declared external command-exit
case. There is **no proven entirely unused current code** to delete merely
from that search. RE2 must check dynamic `refuse(code, ...)`, passed stop
factories, closure reports and managed emitters before removing an entry.

Delete the eight `HANDOFF_*` codes when N3 deletes their last emitters; remove
`TASK_RECORD_INCOMPLETE` and the obsolete runtime format/declaration codes
only after their creation-time diagnostics and contract replacements exist.
Do not reserve orphan codes for a future implementation: RE7 requires each
remaining entry to have a live cause and test, including human judgment paths.

Expected guardrail count: **21**, calculated from the current 27:

| Change | Guardrail reduction |
| --- | ---: |
| Merge `REVIEW_REQUIRED` and `REVIEW_STALE` into `REVIEW_NOT_APPROVED`, distinguishing causes | 2 |
| Merge `EXECUTION_PROFILE_MISSING` into `UNDECLARED_VALIDATION_COMMANDS` | 1 |
| Merge `WORKFLOW_UNREADABLE` into `RULE_CONFLICT` for unresolved human policy cases | 1 |
| Merge `SELF_UPDATE_NON_FF` into `SELF_UPDATE_TARGET` | 1 |
| Reclassify `SELF_UPDATE_PLUGIN_CACHE` as owner routing | 1 |
| Total | 6 |

All other mixed codes retain their human negative cases. Their safe subcases
receive nonhuman cause codes/results, adding **zero guardrail codes**. A
permission denial reached after plugin routing uses the existing access
code; an uncertain legacy import uses the retained state-invalid/authority
cause, not silent import. The total registry size is not fixed here because
RE2 must enumerate the new nonhuman causes. A count reduction alone is not
success: acceptance is zero mechanical blocked events, with every safety
negative still refusing. Do not merge differently owned remedies simply
because messages sound similar (`PRIMARY_DIRTY` vs `SELF_UPDATE_DIRTY`, for
example). Consolidate generic fallback messages by **cause**, not by guessing
that every `COMMAND_REFUSED` is recoverable.

## Every recorded journal stop

Line numbers refer to the frozen JSONL prefix, not task IDs. All times are
UTC. “Could resolve” means using existing authority and trustworthy inputs;
it never means writing a false state. RE1/RE2 handle routing, RE3 unfinished
work, RE5 integration and RE6 push/cleanup unless specified otherwise.

| Line; time; task; command | Code | Situation and replacement; confidence |
| --- | --- | --- |
| 37; 10-17 17:37:23; 005; prepare | `COMMAND_REFUSED` | Missing task record for already requested work, explicitly described by ADR decision 12. Return coordinator record-creation next action, then prepare; yes, with that existing authority, not arbitrary queue selection. RE1/RE2. |
| 71; 10-17 20:13:29; 009; check | `WRONG_WORKTREE` | Dirty Resume, identified in decision 12 and handoff 009. Resolve registered task location, inspect owned changes, continue the authorized Resume. Yes. RE1/RE2. |
| 130; 10-17 22:16:30; 015; advance C6 | `TASK_STATE_MISSING` | Decision 12 says closure was skipped; return/perform the missing owned close operation, then advance. Yes under the historical contract; product now verifies stable records and lands state instead of restoring archival. RE1/RE4, SS6 already landed. |
| 181; 10-17 23:25:47; 019; check | `WRONG_WORKTREE` | Dirty Resume per decision 12. Same owned-location/Resume remedy as 009, not a new decision. RE1/RE2. |
| 212; 10-18 10:16:56; 021; check | `WRONG_WORKTREE` | Handoff 021 records exactly `dirty-worktree` after `prepare --resume`. Authorized Resume should return ready-dirty. Yes. RE2. |
| 214; 10-18 10:49:03; 021; check | `WRONG_WORKTREE` | Second occurrence of that check defect, not a second human decision. Same remedy, same ownership checks. RE2. |
| 226; 10-18 11:16:18; 028; check | `WRONG_WORKTREE` | Task 028 implements the dirty-Resume fix; surrounding prepare/check sequence and its handoff support the same mismatch. Journal lacks error details: likely the same defect, not proof of every individual error field. Route authorized dirty work; otherwise preserve identity guardrail. RE2. |
| 228; 10-18 11:17:48; 028; check | `WRONG_WORKTREE` | Repeated check in the same fix session; same evidence limitation and remedy as line 226. No separate human input recorded. RE2. |
| 246; 10-18 20:37:11; 022; check | `WRONG_WORKTREE` | Handoff 022 records accepted dirty Resume then check without a Resume option, exactly `dirty-worktree`. Resolve/accept that authorized state. Yes. RE1/RE2. |
| 258; 10-18 21:08:53; 023; check | `WRONG_WORKTREE` | Handoff 023 records the same exact dirty-worktree-only exception. Yes. RE1/RE2. |
| 518; 10-19 18:49:18; 051; advance C6 | `TASK_STATE_MISSING` | Missing closure state; later evidence/stage/finalize succeeded. No missing human information is recorded. Likely owned closure ordering, but journal omits the state contents: recover only with a verifiable receipt, otherwise request import authority. RE1/RE2. |
| 549; 10-19 21:02:41; 054; advance | `COMMAND_REFUSED` | Followed ten seconds later by successful evidence and then stage. Consistent with a mechanical evidence/order precondition; exact exception absent from handoff and journal. Return the resolved evidence step if proven. Cannot assert a particular missing argument. RE2; telemetry A8. |
| 568; 10-20 08:04:55; 056; evidence | `COMMAND_REFUSED` | Followed one second later by successful advance C5. Mechanical invocation/order is likely; exact cause unrecorded. Return a typed missing-input/next-step diagnostic; no evidence of a new human decision. RE2; A8. |
| 599; 10-21 22:43:22; 060; advance | `COMMAND_REFUSED` | Same advance succeeds five seconds later at C5, evidence follows. Likely satisfiable precondition; exact cause unknown. Resolve next step, retain a guardrail if ownership cannot be proved. RE2; A8. |
| 678; 10-22 08:25:22; 067; advance | `COMMAND_REFUSED` | 071 and 067 had both reached C7; 071 finalizes at 08:25:34. This is the concurrent integration lease described in the task/ADR. Wait for 071, then recompute 067's candidate on current main; never abort 071. Yes: W then R. RE5 A4. |
| 727; 10-22 11:21:44; 069; advance C6 | `INTEGRATION_CONFLICT` | Handoff 069 identifies a textual conflict in the identifier-guard allowance and explicit developer authorization on Resume. Genuine guardrail: a person supplied conflict-resolution authority. No automatic resolution. RE5 negative case. |
| 742; 10-22 11:49:20; 072; advance C7 | `CANDIDATE_VALIDATION_FAILED` | Handoff 072 identifies a missing historical-document allowance after 074 landed. Return failing work, abort owned candidate, fix under task authority and revalidate within N. No new human decision before retry exhaustion; do not report this as a merge conflict. RE5/RE3. |

**Counterfactual counts.** The earlier 15-event sample is 8 wrong-worktree +
5 command-refused + 2 missing-state. Under the documented mechanical causes
it becomes **14 resolution/next-action outcomes + 1 bounded wait + 0 human
stops**. On this review's 17-event sample: **14 resolution/next-action +
1 waiting + 1 failing-work + 1 guardrail**, down from 17 blocked events to
**1 blocked event**. These count events, not distinct tasks or all retries.
The original code totals remain 8/5/2/1/1 in the historical journal; never
rewrite history to make telemetry look compliant.

This is an expected replay under the proposals, not a proven replay trace.
Lines 518/549/568/599 lack cause details. If any of these four turns out to
require unknown authority, guardrail count would be 1–5 (earlier sample
0–4), with correspondingly fewer recoveries. Record this bound rather than
claiming that the generic journal proves every refusal safe. The confident
minimum is 10 resolution events, 1 wait, 1 failing-work, 1 guardrail and 4
unresolved causes in the 17-event sample. A8 removes this ambiguity in future.

## Stops recorded in task handoffs

The pinned-commit search above covers all `tasks/handoffs/`, including JSON
mapping files. Actual incident statements are below; do not add an incident
again when it duplicates a journal event.

| Handoff | Code/situation | Could the tool resolve it? Destination |
| --- | --- | --- |
| 009 | Resumed uncommitted task work (decision 12 supplies its check code); also records successful final validation. | Yes, owned Resume routing; journal line 71. RE1/RE2. |
| 021 | Explicit `BLOCKED WRONG_WORKTREE` with only dirty-worktree. | Yes; journal lines 212/214. RE2. |
| 022 | Explicit `BLOCKED WRONG_WORKTREE` on accepted dirty Resume. | Yes; line 246. RE2. |
| 023 | `WRONG_WORKTREE`, dirty-worktree only. | Yes; line 258. RE2. |
| 028 | Local regression proof returns ready-dirty and start succeeds; earlier missing import/path expectation fixed during validation. | This is proof of recovery, not an additional pasted stop. RE2 must preserve its negatives. |
| 050 | Explicit `BLOCKED VALIDATION_FAILED` after three counted attempts: fixture cwd/allowed-Git errors, later fixed. | Before exhaustion, return F; at exhausted budget a person supplies continuation authority. Product emits `VALIDATION_RETRY_LIMIT`, not the generic failure code. Keep a guardrail for the recorded exhaustion; this incident is absent from the lifecycle journal's blocked rows. RE3. |
| 058 | Dirty close reported `WRONG_WORKTREE` because sandbox-denied Git writes left the report uncommitted; authorized escalation committed it and close succeeded. | Split causes: missing commit/order is R, but actual host access denial needs authority and remains G until granted. Not proof that all dirty-close stops are autonomous. RE2/RE4; no matching journal row. |
| 069 | Integration conflict, then explicit authorization to resolve the identifier-guard line. | No; genuine human conflict decision. Duplicate of journal line 727. RE5. |
| 072 | `CANDIDATE_VALIDATION_FAILED` after 074 integration; missing identifier-guard allowance. | Yes, F and owned candidate abort/retry; duplicate of line 742. RE5. |

Other matches are **not additional stop incidents**: 029 quotes a future
retry instruction; 030's classification tables and subprocess fixtures
exercise wrong-worktree/lease cases; 034/035 discuss removed adoption/budget
codes; 047/051 describe registry metadata; 020's `BLOCKED:` is console
display, 060's `BLOCKED` is a review verdict; 068 describes emitter changes;
074 quotes inventory findings and its own checks. JSON test-ID maps name
lease tests, not operational events. No new code should be invented for any
of these matches. Decision 12 additionally mentions an intermittent test on
009 and task-owned whitespace/import failures on 021; these are F, not new
journal entries or independently counted stops.

The 17 journal events plus **two distinct handoff-only incidents** (050 and
058) form 19 incident records after deduplication. Expected human incidents
are 3: the 069 conflict, 050's exhausted budget, and 058's access grant;
058 also contains a mechanical continuation after that grant. With the four
uncertain generic/state causes, the evidential range is 3–7. This combined
number is separate from the requested journal counterfactual.

## Location resolution and lease waiting

RE1 must resolve task identity, Git common directory, registered branch and
canonical primary/task roots before dispatch. A primary-only action executes
in primary; implementation, validation and review execute in the registered
task checkout. A caller's unrelated cwd is not a new decision. Quoted absolute
paths are runtime arguments; tracked handoffs retain relative paths. If the
roots disagree, preserve all work and report the exact identities to the
owner. A dirty Resume is accepted only for task-owned paths and authorized
continuation, not by automatically adding `--resume` to hide unknown writes.

RE5 needs a concrete waiting policy (A4): retry a valid other-task lease
with a monotonic deadline, e.g. **60 seconds, poll at most every 5 seconds**;
at expiry return `waiting` with owner, operation identity, observed progress,
next poll time and unchanged `cardine run <ID> --project <primary>` command.
The caller continues bounded polling in the same authorized run; timeout is
not automatically `BLOCKED LEASE_HELD`. On release, refetch/re-resolve main,
invalidate any candidate tied to an older tree, and stage again. If ownership
or liveness cannot be established, retain a guardrail; never delete a lease
by age alone. An owned interrupted operation has a different recovery route
using its receipt. Waiting must not hold another integration lock or a dirty
primary on behalf of the waiter. Tests must interleave two tasks and prove
that neither loses its candidate or aborts the other.

## Repeatability and interruption boundaries (decision 14 rule 4)

Atomic file replacement is not transaction idempotence. The current source
has useful partial protections: repeated start, matching staged candidate
reuse, byte-identical review-output retry, stale-base repair and partial
cleanup. The following remaining boundaries require operation-level proofs;
these are static findings, not claims that crash-injection tests were run.

| Effect boundary and current source | Why the same invocation may not converge today | Required invariant and destination |
| --- | --- | --- |
| `worktree/checkout.py::prepare_task_worktree`: branch/worktree creation before lifecycle JSON write | A crash can leave only part of the pair/state. Next prepare can report partial task state or path collision through `COMMAND_REFUSED`; Resume deliberately does not recreate missing state. | Persist intent before creation; reconcile only the exact expected branch/root/common-dir pair. Preserve unknown collisions. RE1 A1, RE2. |
| `repair_task_worktree_base`: base write before validation renewal | Repair itself is repeatable, but old evidence is still on disk; an agent must renew it. | Evidence is keyed by source/base identity, so repeated run never treats stale results as current. RE3, RE5 existing scope. |
| `tasks/transitions.py` start/cancel/outcome state write | A single JSON write is atomic, but direct repeated cancel/transition can reject a terminal status or duplicate a logical request without an operation key. | Same authorized request returns its recorded result once; a different authority/reason is a different request and cannot replace history. RE1 receipts; RE4 existing repeat-call tests. |
| `lifecycle/commands.py::execution_deliver`: state becomes in_review before add/commit | Failure after the state write leaves dirty in_review. Readiness then rejects dirty output or missing committed delivery; the same deliver does not itself commit that residue. Some later handoff corrections have special redelivery support, not general crash recovery. | Commit only receipt-owned paths; reconcile already committed delivery, retain original validation/source identity, never make a second submission. RE3 A2. |
| `review/verdict.py::record_review_verdict`: state write before review text write | Full byte-identical projections have retry support. A crash between outputs leaves only one, so dirty retry comparison fails. | Record one verdict operation and finish its exact missing projection without inventing a new verdict, attempt or timestamp. RE4 A3. |
| `integration/merge.py::stage_task_integration`: exclusive lease before merge; merge before state/view regeneration and integration JSON | A lease-only crash is a stop; merge-only or changed-state-without-integration JSON cannot reuse the matching-candidate path. Current matching JSON/tree/MERGE_HEAD reuse is good but covers only a completed stage. | Receipts identify pre-merge main, task HEAD, staged tree and owned outputs. Resume exact owned candidate or restore pre-stage tree; never abort another task. RE5 A4. |
| `finalize_task_integration`: merge commit before deleting integration JSON/lease | A crash after commit leaves stale staged metadata while MERGE_HEAD is gone. Repeating finalize can reject it rather than recognize the already-landed merge. | Prove ancestry/parents/tree against receipt, return same landed commit and finish metadata removal; no second merge commit. RE5 A4. |
| `abort_task_integration`: merge abort, integration JSON unlink, lease unlink | Crash after removing integration JSON leaves lease-only state. After both unlinks, repeated abort reads a missing lease and can refuse instead of returning already aborted. | An owned abort receipt survives until reconciliation; repeated abort is a no-op only after ownership and unchanged primary are proven. RE4 existing owned-abort scope; A3. |
| `lifecycle/closure.py` C7: candidate evidence write before finalize; C5 supplied evidence rewrite | Results are supplied by an agent, lack an engine operation identity, and may survive changed source/config or interruption. | Record actual process result once for the exact tree/config; resume missing work; never copy pass flags forward. RE3/RE5; T-38–T-43 amendments already proposed by inventory. |
| Push accepted remotely before local result/receipt, then CI/remote branch cleanup | No current run engine owns these operations. Repeating blindly can double-push, poll wrong HEAD or delete a ref that advanced. | Query exact remote ref and CI HEAD before retry; one push per source head; compare-delete observed remote SHA. RE6 existing scope plus A5. |
| `cleanup_task_worktree`: worktree removed, branch deleted, lifecycle file removed | Several partial states already recover. Remaining removal/branch-delete race and access failure still share `CLEANUP_BLOCKED`; without a receipt, a newly reused branch/path can be confused with the old one. | Persist observed task tip and ownership; prove landed/pushed ancestry before each effect, compare refs again, preserve reused/foreign paths. Test interruption after every effect, including directory placeholder creation. RE6 existing cleanup/race scope. |
| `release/update.py::run_self_update`: fetch before pinned merge/switch, then final verify | Within one call target is pinned. A repeat without `--to` resolves latest again and can choose another release after interruption; error types combine transport and changed identity. | Pin operation intent across retries; recognize already-applied HEAD/VERSION; no force switch or history rewrite. Outside current run rows: SR1. |
| Upgrade multi-file application and non-run host adapters | RE1's run receipts do not automatically cover upgrade/host operations. Missing generated output vs project edits vs denied home writes must stay distinct. | Inventory effect boundaries before claiming decision 14 globally; test interruption and ownership per adapter. RE2 A7 classification; SR1 effect work. |

## Destinations and scope gaps

The existing [single-source plan](SINGLE_SOURCE_OF_TRUTH_PLAN.md) SS6 names
stable records, candidate/abort and exact review gates; task 069 has done
that work. Its old archive/queue recovery is removal, not a new implementation
request. SS7 already names shared facts and console/briefing fallbacks; use it
for display and routing based on state, not for changing stop renderers.

The [run-engine plan](RUN_ENGINE_PLAN.md) already covers RE1 root resolution
and atomic receipts; RE2's listed mixed codes; RE3 automatic validation,
implementation and EVIDENCE_INCOMPLETE; RE4 review and owned abort; RE5
candidate retry/abort; RE6 push reconciliation and cleanup interruptions;
RE7 console and recovery matrix. It does **not** explicitly cover every
finding above. Apply these one-sentence amendments when writing the work-item-8
records; this task changes neither plan:

| Proposal | One-sentence amendment; scope gap it closes |
| --- | --- |
| A1 — RE1/RE2 | “Enumerate every registry entry and dynamic emitter, including prepare creation gaps, integration merge/evidence/state failures, profile/creation diagnostics and judgment emitters; reconcile proven partial creation through receipts, split nonhuman causes, and remove or merge codes only after replacing their last live emitter.” |
| A2 — RE3 | “Resume an interrupted delivery through its state-write/add/commit boundaries without duplicate submissions, retire runtime Markdown validation gates and agent-declared results per Text gate inventory, and count task and candidate failures by recorded source/input identity rather than invocation.” |
| A3 — RE4 | “Use REVIEW_NOT_APPROVED with missing/stale causes, enforce the review-loop budget, retire close's handoff gate with N3, and recover partial verdict writes and repeated owned abort/cancel from one durable operation identity.” |
| A4 — RE5 | “Wait boundedly for valid competing integrations, distinguish textual conflicts from transient merge errors, and prove convergence after lease creation, merge, landed-state/view writes, merge commit and each metadata removal, without aborting a foreign operation.” |
| A5 — RE6 | “Classify push rejection by permission, remote advancement or uncertain transport, and query the exact remote result before retrying any push/CI/remote-delete effect.” |
| A6 — RE2 | “Merge equivalent approval, configuration, workflow-policy and self-update-target codes as specified in Stop review, preserving detailed causes and a projected 21 human guardrail codes.” |
| A7 — RE2 | “Include upgrade and host/OS catch-all emitters in the cause audit without making the run dispatcher execute updates or host setup.” |
| A8 — RE7 | “Replace remaining judgment prose emitters with engine or explicit human-decision routes, record cause, resolution, operation/owner identity and next action in journal events, and assert that every new blocked event needs authority, a decision or information.” |

**SR1 — non-run effect repeatability, proposed new row (~3h)**: place after
RE7, before work item 9's adapter consolidation. Inventory and implement
receipts/reconciliation for self-update and upgrade/host operations that
perform effects, with crash injection at fetch/apply/write/verification
boundaries and pinned target/ownership negatives. RE2 explicitly excludes new
self-update behavior and RE6 covers task landing, not product updates;
neither current row already covers SR1. If the boundary inventory cannot fit
~3h, split SR1 before implementation; do not silently expand RE2/RE6. Host
consent and plugin-manager ownership remain absolute. This is a proposed
planning row only, not authorization to run updates on the real home.

N3 is the proposed row already specified by Text gate inventory (~3h, after
RE3), not a second new handoff-removal task. The decisions about trusted
artifacts belong with the companion forgery inventory; this review's receipt
recommendations require those proofs and never treat task-branch JSON as
self-authenticating. RE7 must test the complete then-current registry, run
returned recovery commands unchanged from unrelated cwd, crash after each
listed effect, and keep human/foreign/denied negatives. No registry edits,
code changes or historical journal rewrites are delivered by this review.
