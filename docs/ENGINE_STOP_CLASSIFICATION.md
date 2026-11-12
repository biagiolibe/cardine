# Engine stop classification

Deliverable of spike 203. It decides which refusals on the path of a task the engine resolves by itself, which need the developer, what every remaining stop must say, and how project-wide standing decisions reach an agent. It changes no source or test file; part 6 lists the tasks that do.

- **Base commit:** `c3bffd8`. Every `file:line` below refers to that commit; the task branch adds only task records.
- **Method:** all `raise` statements and `_fail(` calls in the ten modules named by the task were listed with `grep -nE '^\s*raise\b|\b_fail\(' <files>` (170 sites, of which 3 are not refusals, see part 2), read in context, and classified. Boundary names come from `receipts.boundary(...)` calls; test coverage of a boundary comes from a string search of `tests/*.py` for its name.
- **Authority:** this document is a decision record for the coordinator. It does not amend `docs/ADR_CARDINE_1_0.md`; part 6 contains the task that does.

## 1. The rule

A refusal is a point where an operation stops because its inputs, its owner, or the world around it are not what it expects. Every refusal falls into one of these classes. The class decides who acts next.

| Class | Code | What the engine does | Developer stop? |
| --- | --- | --- | --- |
| Tamper or integrity | `T` | Stops with the expected and found values. The cause is a forged or foreign receipt, owner, path, symlink or ref, or a history rewrite. | Yes |
| Developer decision | `D` | Stops. Only the developer holds the authority or the information: review verdict, textual merge conflict, rejected push, project choice, a dirty or moved primary checkout, an exhausted budget. | Yes |
| Interrupted without effect | `N` | Discards the intent (or marks it `invalidated`) and restarts the operation. No result and no external effect exists, so nothing is lost. | No |
| Interrupted after an effect | `A` | Finishes the effect from the bytes the intent stores, or reverses it with the engine principal, or, when neither is provable, stops with the exact state. | No, unless it falls back to the exact-state stop |
| Live concurrent operation | `L` | Returns `waiting` with `retry_after_seconds`. A dead holder is not live: `operation_live` and the flock guards decide. | No |
| Precondition the engine can satisfy | `P` | Satisfies it (commit its own records, run the earlier step, push `main`, fast-forward `main`, prepare the worktree) and continues, or returns `next` with the one command that does. | No |
| Failing work | `W` | Returns `iterate` with the paths or commands to fix. | No |

`W` and `D` are additions to the task's five classes. `W` is the existing `failing-work` resolution, kept so that sites already typed that way are classified too. `D` exists because a review verdict, a textual merge conflict, a rejected push or a project choice is not tamper, yet the engine cannot resolve it: folding them into `T` would label an honest stop as an attack, and leaving them out would leave the largest group of typed guardrails unclassified.

### How to decide between the classes

Apply the questions in order. The first yes wins. A site with several causes in one `or` chain is split and each disjunct is classified separately; the inventory marks such rows with `+`.

1. **Owner and authority.** Do the task, project, worker, root or receipt authority in the intent differ from the current ones, or is a path a symlink, or does a ref or file hold bytes no receipt covers? That is `T`. Recurring patterns, defined once: *owner mismatch* (task, root, worker or authority differ), *foreign bytes* (a file or ref neither matches `before` nor `after`), *symlink guard*.
2. **Live writer.** Is another process holding the guard (`operation_live`, a non-blocking `flock`)? That is `L`.
3. **Boundary.** Find the last `receipts.boundary` the intent passed. Before the first external effect (branch, worktree, commit, merge, push, file write outside the intent) the operation has no effect: `N`. After it, `A`. An intent is a record of plan, never of effect. The deciding boundary is named in the inventory row.
4. **Precondition.** Is the missing thing something the engine itself creates or may safely run (its own records, an earlier step, a fast-forward of `main`)? That is `P`.
5. **Authority only the developer holds.** `D`.
6. Otherwise the agent's own work is wrong: `W`.

Changed inputs at an interrupted operation are the most common case. They are `N` when the operation published nothing, which is why task 201 can restart validation safely. They are `A` when a lease, a staged merge, a branch or a worktree already exists: the engine then owns a reversal (`abort_owned` with `ENGINE_PRINCIPAL`, defined in `src/cardine/lifecycle/control.py` and used by `recover_task_integration`, `src/cardine/integration/merge.py:430-432`) and must use it instead of asking.

**Fail closed.** A refusal that no class claims stays a developer stop. Raising a plain `CardineError` therefore remains safe: it becomes `COMMAND_REFUSED`. A class below `T` and `D` is granted only by the site that proves it.

## 2. The inventory

Files are the ten named by the task. All 170 raise and `_fail` sites were reached: nothing is listed as not reached. Rows give the line, the refusal text (first string literal at the site), the class, and the reason with the deciding boundary.

Sites per class (a split row counts once in each class it names):

| Class | Sites |
| --- | --- |
| `T` tamper or integrity | 79 |
| `D` developer decision | 29 |
| `N` interrupted without effect | 30 |
| `A` interrupted after an effect | 26 |
| `L` live concurrent operation | 10 |
| `P` precondition the engine can satisfy | 19 |
| `W` failing work | 8 |
| `-` not a refusal | 3 |

Of the 170 sites, 106 raise a plain `CardineError` (reported as `COMMAND_REFUSED`, `human_decision: true`); the rest are typed with a registered code or are helper rows. Rows whose class set includes `N`, `A`, `L`, `P` or `W` are the ones the engine can stop asking about: 83 of 167 refusals.

### `src/cardine/lifecycle/validation.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `validation.py:81` | live foreign validation runner | `L` | Runner guard held by a live process. |
| `validation.py:108` | validation inputs changed before evidence publication | `N` | Inputs changed between the computed result and its publication, nothing published (`before_validation_evidence`); start a fresh attempt. Same file as task 201. |
| `validation.py:149` | validation requires the canonical task worktree | `L+P+T` | L: `integration_active`. P: `missing-worktree`. T: other identity errors. |
| `validation.py:157` | validation operation has foreign owner or changed authority | `T` | Intent owner, root or authority differ. |
| `validation.py:161` | validation cannot replay a foreign pending operation | `T` | A pending state operation exists that is not this validation's publish. |
| `validation.py:164` | validation pending result has foreign owner | `T` | Pending state holds a different validation result. |
| `validation.py:168` | validation inputs changed before result replay | `A` | Result staged (`after_validation_evidence` not reached) and inputs moved. Finish would attest stale inputs: discard the pending staged files and intent if receipts allow, else stop with state. |
| `validation.py:189` | VALIDATION_RETRY_LIMIT: failed runs as JSON | `D` | `VALIDATION_RETRY_LIMIT`: enforced guardrail (ADR decision 5). |
| `validation.py:192` | quick_limit_error(...) | `D` | Quick-failure limit reached; enforced guardrail. |
| `validation.py:194` | validation inputs changed during interrupted attempt | `N` | Interrupted attempt with changed inputs and no result. Resolved by task 201 (open). |
| `validation.py:203` | VALIDATION_RETRY_LIMIT: failed runs as JSON | `D` | Limit reached by a published attempt. |
| `validation.py:206` | quick_limit_error(...) | `D` | Quick limit reached by a published attempt. |
| `validation.py:213` | ACCEPTANCE_UNMET: A complete committed implementation must be delivered first | `W` | Typed `ACCEPTANCE_UNMET`; the engine could run `deliver` itself (P), but the registry says failing work. |
| `validation.py:218` | ACCEPTANCE_UNMET: Missing acceptance deliverables: | `W` | Typed `ACCEPTANCE_UNMET`; deliverable paths are missing. |
| `validation.py:232` | validation input state changed | `N` | Task state digest differs from the intent's `before` and nothing published. Adjacent to 201's change; confirm there. |
| `validation.py:266` | VALIDATION_FAILED: Validation inputs changed before the full rerun; start a fresh attempt | `N` | Typed `VALIDATION_FAILED` (`iterate`) but nothing is for the agent to fix: inputs moved before a rerun and the phase is already `invalidated`. The engine starts a fresh attempt. |
| `validation.py:283` | VALIDATION_FAILED: Validation inputs changed while commands ran; run a fresh complete attempt | `N` | Same as 266 after the commands ran. If a command itself rewrites inputs, the fresh attempt repeats it and counts toward the limit. |
| `validation.py:320` | VALIDATION_RETRY_LIMIT: failed runs as JSON | `D` | Limit reached by the attempt just published. |
| `validation.py:322` | quick_limit_error(...) | `D` | Quick limit reached by the attempt just published. |

### `src/cardine/lifecycle/delivery.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `delivery.py:31` | delivery {args[0]} failed: {result.stderr.strip()} | `N` | A Git command of the delivery failed (`before_delivery_add`/`before_delivery_commit`); no effect recorded. Retry once, then stop with `stderr`. |
| `delivery.py:49` | delivery source identity changed | `T` | Delivered source is no longer an ancestor of HEAD, or its tree changed: history rewrite. |
| `delivery.py:61` | delivery commit does not match the exact intended effect | `T` | The commit after the source touches more than the state file. |
| `delivery.py:66` | delivery lacks its operation receipt | `T` | Committed delivery has no `implementation-delivery` receipt. |
| `delivery.py:70` | implementation delivery is not committed | `A` | Intent exists, commit missing. Boundary: `before_delivery_commit`. The engine finishes it by running `deliver` again. |
| `delivery.py:81` | delivery worktree identity mismatch | `L+P+T` | L: `integration_active`. P: `missing-worktree`. T: any other identity error. |
| `delivery.py:90` | delivery operation owner or authority changed | `T` | Delivery intent owner, root, base or authority differ. |
| `delivery.py:96` | delivery result commit identity changed | `T` | Verified result commit differs from the recorded commit. |
| `delivery.py:98` | delivery has foreign uncommitted changes | `W` | Uncommitted files after a verified delivery: the agent's own work; iterate with the path list. |
| `delivery.py:108` | implementation delivery requires in_progress | `P` | Status is not `in_progress`; the earlier step is the answer. |
| `delivery.py:112` | delivery needs a real implementation change | `W` | No change inside the surface; iterate. |
| `delivery.py:114` | implementation must be committed before delivery | `W` | Uncommitted implementation; iterate (commit). |
| `delivery.py:138` | pending delivery belongs to another operation | `T` | Pending state operation is not this delivery. |
| `delivery.py:142` | delivery input source changed | `N+A` | Source digest differs from the intent. Boundary: `before_delivery_state` (no pending state op): discard the intent and restart (N). After it, `after_delivery_state` to `before_delivery_commit`: stop with expected and found digest (A). |
| `delivery.py:150` | delivery input state changed | `N` | HEAD or state bytes moved before the state write; restart. |
| `delivery.py:158` | delivery state belongs to another operation | `T` | State holds a delivery that is not the intent's. |
| `delivery.py:166` | delivery recovery has foreign changes | `T` | Paths beyond the state file are dirty after the state write; list them. |
| `delivery.py:177` | delivery replay found a foreign commit | `T` | HEAD is a commit that is neither the source nor the intended one. |
| `delivery.py:180` | delivery result changed | `T` | Delivered result no longer verifies after the commit. |

### `src/cardine/lifecycle/preview.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `preview.py:58` | foreign finalize operation or changed source | `T+A` | T: task, project, worker or authority differ from the finalize binding. A: `source`/`sourceDigest` moved; before `after_finalize_commit` (head still `binding.main`) nothing landed, so reverse the staged candidate and revalidate. |
| `preview.py:66` | main does not prove the intended landing | `T` | Main advanced past the finalize binding but not by the intended merge (tree or parents differ). |
| `preview.py:70` | finalize has no matching candidate | `N` | Finalize intent has no result and main has not moved (`before_finalize_commit`): no effect; discard the intent and revalidate the candidate. |
| `preview.py:76` | live foreign operation; wait for the current writer | `L` | Writer live (`operation_live`): wait with `retry_after_seconds`. |
| `preview.py:79` | foreign pending preview operation | `T` | Pending intent names another task or authority. |
| `preview.py:91` | host preview has foreign owner or changed inputs | `T+N` | T: request `root`/`task_id` differ. N: only `source` or `source_digest` moved; a host launch request has no effect, so issue a new request. |
| `preview.py:107` | pending preview source changed | `N+A` | Receipt source is not HEAD. Boundary: before the delivery commit the agent's own new commit makes it stale (N); after `after_delivery_commit` HEAD legitimately moved and `verify_delivery` decides (A). |
| `preview.py:115` | foreign pending preview output: | `T` | A pending output file matches neither its `before` nor its staged digest. |
| `preview.py:118` | pending operation requires its Stable recovery command: | `P` | A read-only preview met an operation of unknown kind; `cardine run` is its recovery, so answer `next` instead of refusing. |
| `preview.py:136` | preview requires the verified canonical worktree: | `P+T` | P: `missing-worktree` (run `worktree` step). T: any other inspection error (foreign registration, branch mismatch). |

### `src/cardine/lifecycle/control.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `control.py:63` | COMMAND_REFUSED: host role boundary unavailable: authorized channel required | `D` | No host channel and no interactive terminal: only the developer can confirm. Typed `COMMAND_REFUSED`; keep, but name the terminal command. |
| `control.py:66` | COMMAND_REFUSED | `D` | Developer typed a wrong confirmation. Typed; keep. |
| `control.py:79` | host reviewer profile boundary unavailable or changed | `T` | Reviewer or implementer profile not enforced or identical. |
| `control.py:85` | host denied bound operation | `D` | Host refused to authorize the bound action. |
| `control.py:87` | host denied foreign review session | `T` | Principal differs from the issued review session. |
| `control.py:96` | foreign control operation | `T` | Pending control intent has a foreign task or authority. |
| `control.py:116` | control inputs changed during host authorization | `N` | HEAD, source digest or state moved while waiting for the host callback; nothing written (`before_cancel_transition`): authorize again. |
| `control.py:126` | REVIEW_LOOP_EXHAUSTED: two consecutive changes-requested rounds require a new budget decision | `D` | `REVIEW_LOOP_EXHAUSTED`: budget decision belongs to the developer. |
| `control.py:141` | cancellation requires the existing canonical task worktree | `P` | Branch exists but its worktree state is missing: the command can name `cardine worktree prepare`. |
| `control.py:153` | cancellation requires a reason | `P` | Usage error on a developer command; the message should show `--reason <text>`. |
| `control.py:165` | cancellation has changed inputs or foreign owner; restart requires a new task | `A` | A cancellation is already recorded with other inputs. Boundary: `after_cancel_transition`. Return the recorded cancellation with a diagnostic instead of refusing. |
| `control.py:171` | terminal task cannot be cancelled | `P` | State is already terminal: report `done` or `cancelled` as a result, not a refusal. |

### `src/cardine/worktree/preparation.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `preparation.py:40` | lifecycle state mismatch: uncovered or changed worktree preparation receipt at | `T` | Receipt covers other bytes than the lifecycle file; message already names expected and found branch. |
| `preparation.py:51` | foreign preparation lock symlink | `T` | Guard path is a symlink. |
| `preparation.py:56` | live foreign preparation operation | `L` | Preparation guard held by a live process. |
| `preparation.py:72` | foreign preparation receipt symlink | `T` | Receipt path is a symlink. |
| `preparation.py:76` | preparation input or owner changed | `T` | Binding or authority differ from the receipt. |
| `preparation.py:80` | missing covered lifecycle registration | `A` | Receipt `verified` but the lifecycle file is gone. The operation stores the exact bytes (`publish_preparation`); rewrite them from the receipt. |
| `preparation.py:84` | preparation task input changed | `N+A` | State changed since the intent. Boundary `before_branch_create`: no branch yet, restart (N). Branch at `base` exists: adopt it (A). |
| `preparation.py:86` | preparation source changed | `N+A` | Base moved. Same boundary; with a branch at the old base the registered `STALE_WORKTREE_BASE` repair applies. |
| `preparation.py:89` | nothing to resume: missing owned preparation receipt | `P` | `--resume` without a receipt means nothing to resume: run a first preparation. |
| `preparation.py:94` | foreign branch or worktree path collision; no preparation receipt | `T` | Branch or path exists without a receipt. |
| `preparation.py:108` | foreign branch changed during preparation | `T` | Branch tip is neither absent nor `base`. |
| `preparation.py:111` | foreign worktree registration during preparation | `T` | Registered worktree has another branch or HEAD. |
| `preparation.py:113` | foreign worktree path collision during preparation | `T` | Path exists without a registration. |
| `preparation.py:118` | CardineError(result.stderr.strip()) (computed) | `N` | `git branch` failed (`before_branch_create`); no effect. Retry once. |
| `preparation.py:125` | CardineError(result.stderr.strip()) (computed) | `A` | `git worktree add` failed after the branch exists (`after_branch_create`); retry the add. |
| `preparation.py:140` | preparation lifecycle input changed | `T` | Persisted lifecycle bytes differ from the new ones. |
| `preparation.py:142` | foreign lifecycle registration retained | `T` | Lifecycle file holds other bytes than the receipt. |
| `preparation.py:155` | preparation repair authority changed | `T` | Repair authority differs. |
| `preparation.py:158` | uncovered preparation repair input | `T` | Repair input is not the receipt's output. |
| `preparation.py:164` | preparation repair input changed | `A` | A repair intent exists for different before/after bytes; finish or supersede the first repair. |
| `preparation.py:167` | foreign lifecycle repair bytes | `T` | Lifecycle bytes are neither before nor after the repair. |

### `src/cardine/integration/candidate.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `candidate.py:48` | foreign candidate ownership or changed task source | `T+A` | T: lease or staged file differs from the lease keys (foreign ownership). A: `staged.task_commit` differs from the worker HEAD: the 198 case. Reverse the owned candidate (`ENGINE_PRINCIPAL`, as abort does) and restage. |
| `candidate.py:56` | EVIDENCE_MISMATCH: candidate tree or main changed | `T+A` | A: branch is not main, HEAD is not `main_commit`, or MERGE_HEAD is gone/changed (main moved or merge aborted): reverse and restage. T: `write-tree` or working diff differ from `candidate_tree` (the primary was edited). |
| `candidate.py:65` | EVIDENCE_MISMATCH: task lifecycle authority changed after staging | `A` | Status, review or transitions changed after staging, which only covered operations can do. Reverse the candidate and return to the step the state names. Registry says `recoverable`; confirm its resume runs the reversal. |
| `candidate.py:74` | EVIDENCE_MISMATCH: task source or contract changed after staging | `A` | The agent committed or the contract changed after staging: reverse and restage. |
| `candidate.py:91` | VALIDATION_RETRY_LIMIT: Task and candidate validation allowance exhausted | `D` | Task and candidate allowance exhausted; guardrail. |
| `candidate.py:96` | quick_limit_error(...) | `D` | Quick limit exhausted; guardrail. |
| `candidate.py:141` | candidate inputs changed during interrupted operation | `N` | Interrupted candidate attempt with changed binding and no result. Resolved by task 201 (open). |
| `candidate.py:146` | foreign pending candidate result | `T` | Pending state is not this candidate's publish. |
| `candidate.py:170` | candidate state changed during validation | `N` | State digest differs from the intent's `before`; nothing published (`before_candidate_result`). Same family as 141. |
| `candidate.py:206` | EVIDENCE_MISMATCH: candidate tree or main changed | `W` | A validation command dirtied the clean candidate checkout. Typed `EVIDENCE_MISMATCH` (`recoverable`) but a retry reproduces it: should be failing work. |
| `candidate.py:211` | candidate inputs changed while commands ran | `N` | Inputs changed while commands ran; nothing published. Resolved by task 201 (open). |
| `candidate.py:242` | candidate inputs changed before result write | `N` | Inputs changed before the result write (`before_candidate_result`). Same family. |
| `candidate.py:271` | LEASE_HELD: unverified competing lease | `L+T` | L: lease belongs to another task and is coherent (the caller waits first). T: lease unreadable or incoherent. |

### `src/cardine/integration/finalize.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `finalize.py:24` | foreign integration output preserved during finalize | `T` | Lease or staged file digest differs from the finalize binding. |
| `finalize.py:68` | EVIDENCE_MISMATCH: no current measured candidate validation | `N` | No passed candidate when starting finalize: no intent, no effect. Go back to the `candidate` step. |
| `finalize.py:73` | missing committed worker state before finalize | `T` | HEAD of the worker has no committed state file. |
| `finalize.py:88` | foreign finalize operation or changed authority | `T+D` | T: owner or authority differ. D: the primary checkout is not on main (the developer moved it). |
| `finalize.py:94` | finalize task inputs changed | `A` | Contract, source or digest moved after the intent. Boundary `before_finalize_commit`: nothing landed, reverse the candidate, revalidate. |
| `finalize.py:106` | advanced main does not prove the completed owned landing | `T` | Main moved past the intent without proving the owned landing. |
| `finalize.py:112` | landed main was moved backwards | `T` | Main is at the pre-landing commit although a result is recorded. |
| `finalize.py:115` | EVIDENCE_MISMATCH: candidate validation changed before commit | `A` | Candidate evidence changed before the commit; same reversal as 94. |
| `finalize.py:120` | candidate changed immediately before commit | `A` | Candidate changed in the window `before_finalize_commit`; same reversal. |
| `finalize.py:123` | CardineError(committed.stderr.strip() or 'integration commit failed; intent retained') (compute... | `N` | `git commit` failed before the merge commit exists; intent retained. Retry once, then stop with `stderr`. |
| `finalize.py:132` | main does not match the intended landed commit | `T` | Main does not match tree and parents of the intended commit. |
| `finalize.py:134` | landed commit changed | `T` | Recorded result commit differs from HEAD. |
| `finalize.py:152` | foreign worker output preserved during finalize | `T` | Foreign dirt in the worker after landing. |
| `finalize.py:156` | foreign worker state changed before restore | `T` | Worker state bytes are neither `before` nor `measured`. |

### `src/cardine/integration/records.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `records.py:20` | closure records | `N` | A Git command of the closure commit failed (`before_closure_add`/`before_closure_commit`). Retry once. |
| `records.py:31` | foreign pending operation before closure commit | `A` | A pending state operation is the engine's own: replay it (`replay_operation`), or wait if live (L). |
| `records.py:50` | foreign changes before closure records commit | `T` | Dirty paths beyond the record files; list them. |
| `records.py:56` | uncovered closure output: | `T` | A record file is not covered by any receipt. |
| `records.py:67` | closure commit inputs or owner changed | `T+N` | T: task, root or authority differ. N: contract or source digest moved while `head == saved.source` (`before_closure_add`): discard and recompute. |
| `records.py:69` | foreign dirt during closure recovery | `T` | Dirty paths beyond the intent's files. |
| `records.py:72` | closure output changed before commit | `N` | A record file changed before the commit (`before_closure_commit` not reached); recompute. |
| `records.py:80` | closure output changed immediately before commit | `N` | Same, in the window before the commit. |
| `records.py:87` | closure result is not the intended commit | `T` | Commit parent or file set differs from the intent. |

### `src/cardine/integration/cleanup.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `cleanup.py:30` | stop_error(code, detail, task_id=locations.task_id, project=locations.primary, resume=resu (com... | `-` | Helper `_fail`: the raise for every `_fail` site below; not a refusal of its own. |
| `cleanup.py:49` | main push not observed | `N+D` | N: push not observed and not refused (`GIT_OPERATION_FAILED`, `cleanup_push` effect): retry once. D: `PUSH_REJECTED`. |
| `cleanup.py:64` | foreign cleanup owner or changed landing inputs | `T+D` | T: binding task, project, worker, common, authority or origin differ, or main is not a descendant. D: primary not on main or dirty. |
| `cleanup.py:67` | landing receipt changed | `T` | Finalize receipt digest differs from the cleanup binding. |
| `cleanup.py:79` | cleanup is blocked while an integration lease or staged merge is active | `A+L+T` | Typed `LEASE_INTERRUPTED` when the lease is ours and idle: reverse it (A). Else `CLEANUP_BLOCKED`: live writer (L) or foreign lease (T). |
| `cleanup.py:93` | local main is not proven pushed to origin/main: remote does not contain the exact landed tip | `P+D` | P: `PUSH_PENDING`, remote is behind: the engine pushes `main`. D: remote advanced beyond what is known. |
| `cleanup.py:99` | foreign cleanup symlink | `T` | Cleanup path is a symlink. |
| `cleanup.py:112` | reused or changed task branch preserved | `T` | Branch tip is not the task tip, or the branch returned after its deletion effect. |
| `cleanup.py:115` | reused task branch reflog preserved | `T` | Branch reflog differs. |
| `cleanup.py:123` | foreign or dirty task worktree preserved | `T+D` | T: registration differs. D: dirty worktree after landing (data loss risk). |
| `cleanup.py:128` | reused worktree path preserved | `T` | Worktree path contains something other than OS metadata. |
| `cleanup.py:132` | foreign lifecycle registration preserved | `T` | Lifecycle file bytes differ. |
| `cleanup.py:141` | locations, done.stderr.strip() or 'branch deletion refused', code) (computed) | `A+D` | `cleanup_branch_stop_code`: `CLEANUP_PARTIAL` is A (retry); unmerged branch is D. |
| `cleanup.py:146` | locations, detail) (computed) | `A+D` | `worktree remove` partial (A, the message already says `registered-directory-present`/`missing`), or no write access to `.git` (D). |
| `cleanup.py:157` | changed CI push ownership | `T` | CI push binding differs. |
| `cleanup.py:168` | primary checkout must be clean | `D` | Primary checkout dirty. Engine-owned residue is already recovered by `recover_landing_residue`; anything else is the developer's. |
| `cleanup.py:175` | cleanup preflight failed: | `T+P` | P: `missing-worktree`/`unregistered-worktree` are filtered out as recoverable. T: any other inspection error. |
| `cleanup.py:177` | reused worktree path preserved | `T` | Worktree path is occupied. |
| `cleanup.py:186` | nonterminal tracked task state | `-` | Internal raise caught at 188; not a refusal. |
| `cleanup.py:188` | branch already deleted; tracked task state on main must be done: | `T+D` | Branch is gone and main holds no `done` state: unreadable state is T, wrong status is D. |
| `cleanup.py:191` | task commit is not integrated into main | `T` | Task tip is not an ancestor of main. |
| `cleanup.py:196` | landing has not completed | `P` | Cleanup was asked before landing finished; run `finalize` first (`finish_delivery` does when no cleanup intent exists). |
| `cleanup.py:201` | pending task operation before delivery | `A+L` | A pending state operation: replay it if ours, wait if live. |
| `cleanup.py:232` | remote task branch advanced or is unrelated; preserved | `T` | Remote task branch moved or unrelated (`PUSH_REJECTED`). |
| `cleanup.py:242` | remote compare-delete refused; branch preserved | `N+D` | Compare-delete refused: transient (`GIT_OPERATION_FAILED`, `cleanup_remote` effect) is N; `PUSH_REJECTED` is D. |
| `cleanup.py:269` | main delivery requires origin | `D` | No `origin` configured. Registered as `PUSH_REJECTED`, a misfit: the developer must configure a remote. |
| `cleanup.py:310` | worktree cleanup must run from the canonical primary checkout | `P` | Experimental `worktree cleanup` run from another directory; the engine knows the primary and can change directory. |

### `src/cardine/integration/merge.py`

| Ref | Refusal | Class | Reason and deciding boundary |
| --- | --- | --- | --- |
| `merge.py:81` | TASK_STATE_INVALID: {relative}: expected readable UTF-8 JSON; found {error} | `T` | Task state at the task commit is not UTF-8 JSON. |
| `merge.py:86` | TASK_STATE_MISSING: {relative}: expected tracked state at {task_commit}; found missing | `T` | No tracked state at the task commit. |
| `merge.py:102` | TASK_STATE_INVALID: {relative}: status expected {terminal}; found {state['status']!r} | `T` | State at the task commit is not `in_progress`. |
| `merge.py:107` | TASK_STATE_INVALID: spike landing requires an outcome | `W` | A landed spike needs an `outcome`; the agent records it. |
| `merge.py:110` | REVIEW_NOT_APPROVED: cause: missing; {relative}: review.verdict expected APPROVE; found {review... | `D` | `REVIEW_NOT_APPROVED`: verdict missing. |
| `merge.py:121` | REVIEW_NOT_APPROVED: cause: missing; no issued review decision receipt | `T` | Verdict has no issued decision receipt. |
| `merge.py:125` | REVIEW_NOT_APPROVED: cause: stale; | `T` | Reviewed commit is not an ancestor of the task commit. |
| `merge.py:138` | REVIEW_NOT_APPROVED: cause: stale; | `D` | Changes after approval touch more than governance paths: needs a new review. |
| `merge.py:157` | CardineError(staged.stderr.strip() or "could not stage the regenerated views") (computed) | `-` | Internal raise caught at 160; becomes a `STALE` warning, not a refusal. |
| `merge.py:197` | staged integration state is mismatched or stale at {integration_path} | `A+T` | Staged integration exists but does not match: the 198 family. A when lease and staged name this task: abort the owned candidate and restage. T otherwise. |
| `merge.py:199` | an interrupted integration lease is retained at {lease_path}; use `cardine worktree integrate a... | `A+L+T` | Retained lease: `lease_stop_code` splits idle owned (A), live writer (L), foreign (T). |
| `merge.py:211` | task worktree is not ready: {', '.join(inspection['errors'])} | `P+T` | P: `missing-worktree`. T: other inspection errors. |
| `merge.py:213` | primary checkout must be on main | `D` | Primary is not on main. |
| `merge.py:216` | PRIMARY_DIRTY: primary checkout must be clean | `D` | `PRIMARY_DIRTY`; engine residue is recovered first. |
| `merge.py:229` | MAIN_BEHIND_ORIGIN: local main is behind the already fetched origin/main | `P` | `MAIN_BEHIND_ORIGIN`: fast-forward main to the fetched origin (no history rewrite). |
| `merge.py:242` | undeclared_validation_commands_error(...) | `D` | Project has not chosen candidate validation commands. |
| `merge.py:250` | EVIDENCE_INCOMPLETE: no passing measured validation covers the delivered source | `P` | No passing measured validation covers the delivery: run the `validation` step. |
| `merge.py:259` | EVIDENCE_MISMATCH: validated base {validated_base} differs from recorded base {inspection['base... | `P` | Validated base differs from the recorded base: renew validation. |
| `merge.py:276` | paths changed after validation: {', '.join(offending)} | `P` | Commits after validation touch paths outside governance: revalidate. |
| `merge.py:285` | SPIKE task changes disallowed path(s): | `W` | Spike changed disallowed paths: revert them. |
| `merge.py:305` | EVIDENCE_MISMATCH | `P` | Integration-validation decision is BLOCKED: renew validation. |
| `merge.py:317` | LEASE_HELD: integration lease already exists: {lease_path} | `L+A` | Exclusive lease create failed: a live writer (L) or an idle leftover (A, `lease_stop_code`). |
| `merge.py:328` | INTEGRATION_CONFLICT: GIT_OPERATION_FAILED | `D+N` | D: textual conflict. N: transient Git failure after the engine removed its lease. |
| `merge.py:348` | CardineError(staged_state.stderr.strip() or "could not stage landed task state") (computed) | `N` | Staging the landed state failed; the `except` aborts the merge and removes the lease (lines 349-352). Retry once. |
| `merge.py:353` | CardineError(str(error)) from error (computed) | `N` | Re-raise after the reversal at 349-352; the effect is undone, so the operation restarts. |


### Findings from the inventory

**Split rows.** Many untyped raises join an owner check with a changed-input check. They must be split before conversion, because `T` and `A` need different actions. The ones that matter most: `candidate.py:48` (the task 198 case: the lease and staged file are intact and owned, only `staged.task_commit` differs from the worker HEAD, which is `A`), `candidate.py:56`, `merge.py:197`, `preview.py:58`, `finalize.py:88` and `:94`, `delivery.py:81` and `:142`, `cleanup.py:64`.

**Registry resolutions that disagree with the class.**

| Site | Registered | Class here | Consequence today |
| --- | --- | --- | --- |
| `candidate.py:56`, `:65`, `:74`, `finalize.py:68`, `:115` (`EVIDENCE_MISMATCH`) | `recoverable` | `A`, `N` or `T` by disjunct | The resume template must run the reversal; otherwise the rerun hits the same refusal. `candidate.py:56` second disjunct is tamper and must not be `recoverable`. |
| `candidate.py:206` (`EVIDENCE_MISMATCH`) | `recoverable` | `W` | A validation command dirtied the candidate checkout. Rerunning reproduces it. |
| `validation.py:266`, `:283` (`VALIDATION_FAILED`) | `failing-work` | `N` | The agent has nothing to fix; the attempt is already `invalidated`. |
| `validation.py:213` (`ACCEPTANCE_UNMET`) | `failing-work` | `P` | The engine could run delivery itself. |
| `cleanup.py:269` (`PUSH_REJECTED`) | `guardrail` | `D` | Right class, wrong code: no push was rejected; `origin` is missing. |
| `candidate.py:271` (`LEASE_HELD`) | `guardrail` | `L` or `T` | A coherent lease of another task is a wait, not a stop. |
| `cleanup.py:79` (`CLEANUP_BLOCKED`) | `guardrail` | `A`, `L` or `T` | One code covers an idle owned lease, a live writer and a foreign lease. |

**Crash-test coverage of the boundaries.** A string search for each boundary name in `tests/*.py` (a name built in a loop would be missed, so the gaps are an upper bound). Covered: all delivery boundaries (`tests/test_run_delivery.py`), all preparation boundaries (`tests/test_run_preparation.py`), staging (`tests/test_run_recovery.py`), `before_finalize_commit` and `after_finalize_commit` and `after_finalize_intent` (`tests/test_run_integration.py`), `after_candidate_logs` and `before_candidate_result`, `after_closure_intent`, and `after_validation_evidence`, `after_validation_logs`, `after_validation_process`. Not found: `before_validation_intent`, `after_validation_intent`, `before_validation_counter`, `after_validation_counter`, `before_validation_result`, `after_validation_result`, `before_validation_evidence`, `before_validation_logs`, `before_candidate_intent`, `after_candidate_intent`, `before_candidate_logs`, `after_candidate_result`, `before_finalize_intent`, `before_finalize_result`, `after_finalize_result`, `before_finalize_worker_restore`, `after_finalize_worker_restore`, the finalize unlink boundaries, and every closure boundary except `after_closure_intent`. A conversion that turns an `N` or `A` row into a restart must add the crash test for its deciding boundary; part 6 repeats this as an acceptance criterion.

**Overlap with task 201.** Task 201 is queued and edits `lifecycle/validation.py`, `integration/candidate.py` and `tasks/validation.py`. Rows `validation.py:194`, `candidate.py:141`, `:211`, `:242` are resolved by 201 and are marked so; `validation.py:108`, `:232` and `candidate.py:170` are the same family and need 201's landing before they are touched. Follow-ups that edit those files depend on 201.

**Out-of-module helpers.** These are called from the ten modules and reach dispatch as `COMMAND_REFUSED` too: `receipts.require_authority`, `receipts.verify_receipts`, `receipts.safe_path`, `receipts.write_operation`/`replay_operation`, `read_task_state`, `enforce_scope`, `inspect_task_worktree`, `check_dependencies`. They are not inventoried here. Follow-up F11 inventories and classifies them with the same rule.

**Not refusals.** `cleanup.py:30` is the raise inside the `_fail` helper (every `_fail` row above is its caller); `cleanup.py:186` is caught at `:188`; `merge.py:157` is caught at `:160` and becomes a `STALE` warning.

## 3. The proposal

### Where untyped errors become developer stops today

1. `dispatch_run` (`src/cardine/lifecycle/engine.py:307-312`): `except CardineStop` goes to `diagnostic_result`; `except Exception` turns everything else into `stop_error("COMMAND_REFUSED", str(error))`.
2. `preview_run` (`src/cardine/lifecycle/preview.py:23-25`): the same for `CardineError`, `OSError`, `ValueError`, `KeyError`.
3. `diagnostic_result` (`engine.py:506-511`): an unregistered code, or a `CardineStop` without `detail` or `resume`, is replaced by `COMMAND_REFUSED`.
4. `outcome_for_code` (`src/cardine/stops/render.py`) maps `guardrail`, `recoverable` and `failing-work` to `blocked`, `next` and `iterate`. It has no mapping for `waiting`, and `envelope` allows `retry_after_seconds > 0` only for `waiting`.

`COMMAND_REFUSED` is `human_decision: true`, so every class in part 1 other than `T` and `D` is mislabelled as a developer stop.

### Decision: one code per class, no new exception types

The smallest change that keeps tamper as a developer stop: leave the exception hierarchy and the two `except` clauses as they are (fail closed), and let a site that has proved its class raise `stop_error(<code>, ...)` with a registered code for that class. `diagnostic_result` already requires a registered code and derives the outcome from the registry `resolution`. Typed exception subclasses would add a second classification path next to the registry, and `test_stop_registry` and the journal already count by code.

Five registry entries, one new resolution value and one new registry field:

| Code | Class | `resolution` | `human_decision` | Resume |
| --- | --- | --- | --- | --- |
| `OPERATION_INTERRUPTED` | `N`, `A` | `recoverable` | false | `cardine run {task_id} --project {project}` |
| `OPERATION_LIVE` | `L` | `waiting` (new) | false | the same command, after `retry_after_seconds` (new registry field, default 10 as for pending review) |
| `PRECONDITION_PENDING` | `P` | `recoverable` | false | the site passes `resume=` with the one command that satisfies it |
| `INTEGRITY_MISMATCH` | `T` | `guardrail` | true | the command that rechecks after the developer resolved it |
| `RECOVERY_NOT_ADVANCING` | loop guard | `guardrail` | true | the stop message names the repeated code |

- `INTEGRITY_MISMATCH` separates known tamper from `COMMAND_REFUSED`, which stays the fallback for refusals nobody classified. The journal (ADR decision 12: count stops per class) then measures how many classifications remain to do.
- A site that raises `OPERATION_INTERRUPTED` must already have made the next `cardine run` take a different path (intent discarded or `invalidated`, candidate reversed). Where the owning function can continue in place, as task 201 does for validation, it does so and raises nothing.
- `RECOVERY_NOT_ADVANCING` is raised by `dispatch_run` when the same recoverable code with the same detail is returned twice in a row for one task. It replaces the prose rule "if it stops again with the same code, stop" (part 5).
- The envelope stays `version: 1`. `waiting` and `next` results already carry `diagnostics: [{code, message}]` (`schemas/run-v1.schema.json`), so the new codes need no new top-level key. `outcome_for_code` gains `waiting`; `diagnostic_result` fills `retry_after_seconds` from the registry for it.
- The registry adds the field `retry_after_seconds` to `STOP_REGISTRY_FIELDS` (`src/cardine/stops/registry.py`) and `test_stop_registry` must accept it. ADR decision 12 requires, for every recoverable code, a test proving that the command it returns runs unchanged and advances the task; the plumbing task and each conversion carry that test.

## 4. Stop messages

Every remaining developer stop (`T` and `D` rows, plus the fallback of an `A` row) carries four facts in `detail`, in this order, and a resume command:

```text
<what> | expected <value> | found <value> | <why it matters> | resolve: <command or action>
```

- **what changed**, with the expected and the found value. Digests and commits are shortened to 12 characters; paths are repo-relative. For a multi-cause check, the message names the disjunct that failed, not the whole chain.
- **why it matters**, one clause: what the engine would otherwise have attested or destroyed.
- **resolve**: the exact command, or the exact action with the path to compare. A message may not say only "inspect"; where no safe command exists it names the two things to compare and the terminal option (`cardine cancel <id> --reason <text>`).

One helper in `src/cardine/stops/render.py`, `refusal(what, expected, found, why, resolve)`, builds the string, so the format has one owner. `diagnostic_result` already puts `detail` and the resume in the envelope; no schema change.

Worked example, the task 198 stop at `candidate.py:48`:

```text
candidate source moved after staging | expected task commit 3f1a9c2b7d40 (staged) | found worker HEAD 8be04e11c9a2 | the staged merge would land a commit the candidate validation never measured | resolve: cardine abort 198 --project <primary>, then cardine run 198 --project <primary>
```

With the `A` fix this stop disappears (the engine runs the abort itself); the same message is the fallback when the abort cannot be proven safe.

Families of remaining developer stops and what each message must carry:

| Family | Rows | Expected and found | Resolve |
| --- | --- | --- | --- |
| Owner or authority mismatch | `preview.py:79`, `control.py:96`, `delivery.py:90`, `:138`, `:158`, `validation.py:157`, `:161`, `:164`, `preparation.py:76`, `:155`, `candidate.py:48` (first disjunct), `:146`, `finalize.py:88`, `cleanup.py:64`, `cleanup.py:157`, `records.py:67` | the binding fields that differ, by name, with both values shortened | restore the recorded value, or `cardine cancel <id> --reason <text>` |
| Foreign bytes or paths | `preparation.py:94`, `:108`, `:111`, `:113`, `:142`, `:167`, `finalize.py:24`, `:152`, `:156`, `records.py:50`, `:56`, `:69`, `cleanup.py:112`, `:115`, `:123`, `:126`, `:128`, `:132`, `:177` | the path and both digests (or branch and both tips) | the `git` command that shows the difference; never a delete |
| Symlink guard | `preparation.py:51`, `:72`, `cleanup.py:99` | the path and its link target | remove the link after review: the path to remove |
| Receipt or evidence missing or altered | `delivery.py:49`, `:61`, `:66`, `:96`, `:177`, `:180`, `merge.py:121`, `:125`, `finalize.py:73`, `:106`, `:112`, `:132`, `:134`, `records.py:87`, `cleanup.py:67`, `:191`, `preparation.py:40`, `:140`, `:158` | the receipt kind and the commit or tree it should cover, and what was found | the command that regenerates the receipt if one exists, else cancel and restart |
| Primary checkout state | `merge.py:213`, `:216`, `finalize.py:88` (second disjunct), `cleanup.py:64` (second disjunct), `:168` | current branch or the dirty paths, versus `main` and clean | `git switch main`, or commit or stash the listed paths; the engine never does it |
| Budget and review | `validation.py:189`, `:192`, `:203`, `:206`, `:320`, `:322`, `candidate.py:91`, `:96`, `control.py:126`, `merge.py:110`, `:138` | counted failures against the limit; for review, the rounds and verdicts | `VALIDATION_RETRY_LIMIT` lists, per failed command, the id, exit status and last 20 lines of the log (today it prints `json.dumps(runs)`); the resolve names `cardine task contract update` to raise the limit, or cancel |
| Host or terminal authorization | `control.py:63`, `:66`, `:79`, `:85`, `:87` | the channel required (an enforced host profile, or stdin and stdout both a terminal) and what was found; for a wrong confirmation, the expected `<task-id> <commit>` and the typed text; for a profile failure, both profile ids | run the command from an interactive terminal and type the confirmation, or fix the host profile named |
| State at the task commit | `merge.py:81`, `:86`, `:102`, `cleanup.py:188` | the tracked state file, valid UTF-8 JSON with status `in_progress` (on main: `done`), at the named commit, and the status or error found | `git show <commit>:<state path>` to read it |
| Worktree identity | `delivery.py:81`, `validation.py:149`, `preview.py:136`, `merge.py:211`, `cleanup.py:175` (the `T` part; `missing-worktree` is `P`) | each inspection error with the expected canonical path, branch and base | `cardine worktree check <id> --project <primary>` |
| Pending operation or landing mismatch | `preview.py:58`, `:66`, `:91`, `:115`, `delivery.py:166`, `candidate.py:56` (tree and working diff), `:271`, `merge.py:197`, `:199`, `cleanup.py:79` | the bound main commit, tree, parents or lease keys against the ones found, and the paths that are dirty | `cardine abort <id> --project <primary>` for a candidate or lease this task owns; for another task's lease, its task id and the instruction to wait for it or abort that task |
| Project choice and merge conflict | `merge.py:242`, `:328` | for the missing validation declaration, the proposed declaration the message already prints and the file to write; for a conflict, the unmerged paths from `git ls-files --unmerged` | write the declaration to its path; resolve the conflict by hand on the task branch and rerun |
| Remote and branch deletion | `cleanup.py:49`, `:93`, `:141`, `:146`, `:232`, `:242`, `:269` | remote tip against the local landed tip, or the missing `origin` | `git fetch origin`, `git remote add origin <url>`; for an unmerged branch, the `git log main..<branch>` that shows what would be lost |

## 5. Project decisions

### The problem, measured

`tasks/201.md` lines 361-401 carry a "Developer decisions given in advance" block of about 40 lines. Every implementer reads it up front; most of it is not needed in most tasks. It exists because ADR decision 12 requires standing decisions to hold "however the task is launched", and the only carrier the contract had was the task record. The table at the end of this part classifies each line.

### Mechanism: standing decisions, frozen in the contract, delivered at the step

**Source.** A new key `decisions` in `.cardine/project.json`, an array of `{ "id": "<kebab-case>", "steps": ["iterate", ...], "text": "<one rule, at most 400 characters>" }`. Allowed `steps` are the run steps (`contract`, `worktree`, `implementation`, `validation`, `review`, `candidate`, `landing`) plus `iterate`, `blocked` and `always`. It is data, not prose to parse (ADR decision 13): the engine reads the structured entries, and the text is shown, never matched. `parse_project_declaration` in `src/cardine/shared/project.py` rejects unknown keys (`allowed` at line 119), so the key is added there with a validator that checks id uniqueness, steps and text length. Limits, commands and scope are not decisions; they stay where the engine enforces them (`taskDefaults`, `validation`).

**Frozen.** `resolve_task_contract` (`src/cardine/tasks/contract.py`) adds a contract field `decisions`:

```json
{ "digest": "sha256:<canonical JSON of entries>", "entries": [ { "id": "...", "steps": ["..."], "text": "..." } ] }
```

The content is frozen, not only its digest. The execution profile is frozen as a digest alone (`profile_digest`, `contract_digest`), which means the text in force cannot be shown after the file changes; `validation` is frozen as content (`deepcopy` into the contract) and can. Decisions follow `validation`. A later change reaches a task only through `cardine task contract update` (`src/cardine/tasks/contract_update.py`), which re-resolves the contract and records the change in `contract_history.changedFields` (`decisions`). The existing `projectDigest` is written but never compared, so it is not relied on. The `contract` step of `cardine run` compares the frozen digest with the current declaration and, when they differ, adds a non-stopping diagnostic `{code: "DECISIONS_CHANGED", message: "run cardine task contract update <id> to adopt"}`.

**Delivered at the step.** `cardine run` output keeps its closed v1 shape. The decisions that apply to the step it reports travel in two existing places:

- `work.decisions` (new optional property of `work` in `schemas/run-v1.schema.json`, `WorkRequest.decisions` in `src/cardine/lifecycle/model.py`): an array of `{id, text}` for the `implementation` and `review` steps. For outcome `iterate` the entries tagged `iterate` are added. Host launch records are rebuilt in `preview.py:92-96`; the new field defaults to empty for records written before it.
- `diagnostics`: for every result without `work` (steps `validation`, `candidate`, `landing`, any `waiting` or `blocked` result, and the `iterate` results that `diagnostic_result` builds, which carry no `work`), each applicable entry is one `{code: "DECISION", message: "<id>: <text>"}` item.

`diagnostic_result` takes `step="contract"` by default and `dispatch_run` and `preview_run` never pass another, so a stop raised in `validation` or `landing` reports step `contract` today. Delivering by step needs the real step, so `dispatch_run` records which stage (`run_integration_step`, `run_worktree_step`, `run_validation_step`) raised and passes it. An implementer who never meets a validation failure never receives the entries tagged `iterate`. The additive `work.decisions` property is a minor change under `docs/ADR_PUBLIC_SURFACE_AND_STABILITY.md` (additive stable surface), recorded under `Added` in the changelog.

**Readable in one place.** `cardine execution contract <id>` (`src/cardine/cli.py:471`, `execution_contract` in `src/cardine/tasks/preflight.py:20`) prints the resolved contract block of the record; it is extended to print, after it, the frozen validation policy and the frozen decisions with their step tags. That one output is the full effective contract: record plus frozen decisions.

**Enforced before written.** A decision the engine can check is a check, not a line. The table at the end of this part names, per old line, the existing check or the check to add. Only rules that need judgment stay as entries. The session briefing (`cardine hook briefing`, `src/cardine/hosts/briefing.py`) is extended to print the entries tagged `always`. It is a salience aid and not an authority: `docs/HOST_CAPABILITY_CONTRACT.md` marks the Codex briefing `unverified`, and `render_briefing` ignores the caller payload today. The frozen contract is the authority; the briefing repeats it. The two do not compete. Delivery at the step carries each entry at the moment it applies. The briefing fires every turn, so it prints only the short list tagged `always` (the rules that need judgment and have no single step), as a reminder. A host where the briefing is unavailable loses a reminder, not a rule.

### ADR decisions changed or relied on

| Decision | Treatment |
| --- | --- |
| 12 Stops are for people | **Changed.** "Decisions given in advance are carried by the task record" becomes "carried by the frozen contract". The classes of part 1 are added to its table; `waiting` joins `recoverable` as an outcome that is not a stop. The loop guard replaces the prose rule. |
| 13 Gates read facts, not prose | **Relied on.** Standing decisions are structured entries frozen in the contract; the text is explanation for the agent and no gate parses it. The one comparison, the digest, reads data. |
| 4 Task state only in its JSON file | **Relied on.** The contract snapshot is where `decisions` live. |
| 5 Context budget: one automatic limit | **Relied on** (the validation retry limit).  `validationRetryLimit` and `quickFailureLimit` remain typed `taskDefaults`; they are enforced, not decided in text. |
| 6 One lifecycle entry point | **Relied on.** The decisions arrive in the output of the one command the agent already runs. |
| 14 Robust against weak and strong agents | **Relied on.** The engine enforces and the briefing only reminds. |

### Classification of the current block

The block is `tasks/201.md` lines 361-401: an intro paragraph (three sentences) and nine bullets. Each sentence is classified; the compound bullets are split. Labels: **removed by the stop fixes** (the class in part 1 resolves it), **enforced by the engine** (an existing or added check), **project decision** (a `decisions` entry with its step), **task-specific** (stays in the record).

| Ref | Rule (verbatim from `tasks/201.md`) | Label | Mechanism |
| --- | --- | --- | --- |
| intro.1 | The developer records these decisions in the task contract, so that they hold however the task is launched, including a bare `Proceed with <TASK-ID>` from the project console (ADR decision 12). | project decision | Describes the mechanism. Not repeated per record once the contract carries the entries; deleted from the blueprint (F16). |
| intro.2 | None of these situations needs a new decision from the developer. | removed by the stop fixes | True once the classes in part 1 resolve the situations (F1-F9). |
| intro.3 | After fixing a failure, continue with revalidation in the same turn; do not stop to report the fix. | project decision | Entry `continue-after-fix`, steps `iterate`. Delivered in `work.decisions` of an `iterate` result. |
| bullet 1.1 | A required command that exits non-zero because of a precondition the agent can satisfy (command order, an uncommitted worktree, a missing argument): satisfy it and run the command again, once. | removed by the stop fixes | Class `P`: the engine satisfies the precondition or returns `next` with the one command (`PRECONDITION_PENDING`). |
| bullet 2.1 | A validation failure caused by this task's own changes: fix it and revalidate, at most 3 counted attempts. | enforced by the engine | `validationRetryLimit` (`taskDefaults`): `validation.py:189`, `:203`, `:320`, `candidate.py:91`. The `iterate` outcome is the instruction to fix and revalidate. |
| bullet 2.2 | A test that fails once and passes on an identical unchanged rerun is intermittent, recorded in the handoff, and does not count. | enforced by the engine | Rerun once and record as intermittent: the round logic in `run_task_validation` (`progress["intermittent"]`, `## Measured validation` in the handoff). |
| bullet 2.3 | Only after 3 counted failures stop and summarize the failures. | enforced by the engine | `VALIDATION_RETRY_LIMIT` guardrail; the summary is its `detail`, to be made readable by F8. |
| bullet 3.1 | A counted attempt is one run of the whole Validation section on a committed implementation that the agent considers complete. | enforced by the engine | The engine runs the Validation section itself and counts attempts (`run_task_validation`); the agent no longer spends attempts. |
| bullet 3.2 | Test runs during implementation are development, not attempts. | project decision | Entry `development-runs`, steps `implementation`. |
| bullet 4.1 | Before the first clean-clone, run `python3 scripts/check_repository.py` and one `python3 scripts/run_tests.py --parallel` with one `--module` flag for each edited test module and for the repository guards: | enforced by the engine | Project `validation.baseline` and `validation.preflight` in `.cardine/project.json` plus the task Validation section. Superseded for task records by the 2026-11-08 validation change. |
| bullet 4.2 | `test_module_inventory`, `test_layout`, the identifier guard (the `tests/test_no_*_identifiers.py` module), `test_text_gates`, `test_stop_registry`, and `test_command_word`. | enforced by the engine | The guard modules become one project baseline command (`repository-guards`), so no record lists them (F16). |
| bullet 4.3 | Repeat `--module`; a comma-separated list is refused. | project decision | Command syntax, entry `module-flag`, steps `implementation`, `iterate`. Drop it if `scripts/run_tests.py` already refuses a comma list; not verified here. |
| bullet 5.1 | Let a started clean-clone finish; do not interrupt it. | project decision | Entry `let-runs-finish`, steps `implementation`, `iterate` (process hygiene for the agent's own development runs). |
| bullet 5.2 | After a failed clean-clone, fix, commit, and run `python3 scripts/run_tests.py --parallel --last-failed` and a `--module` run for each module the fix touched before the next counted attempt. | enforced by the engine | Failed commands and their `retry` variants run first (`quick_plan`, `lastFailed`); delivery requires a committed implementation (`delivery.py:114`). |
| bullet 6.1 | A stop printed by `cardine run` whose code in `capabilities/stop-codes-v1.json` has `human_decision: false`: run the command the stop names, once. | removed by the stop fixes | Recoverable classes return `next`; `PROJECT_WORKFLOW.md` "Stops and denials" already says to run `next.command`. |
| bullet 6.2 | If it stops again with the same code, stop. | enforced by the engine | New loop guard `RECOVERY_NOT_ADVANCING` (F2). |
| bullet 7.1 | A test outside the listed files that fails only because it changed an arbitrary environment variable and expected a measured result to become stale, or expected an interrupted attempt with changed inputs to stop: change the environment the way `shadowed_path` in `tests/test_run_validation.py` does, or expect the fresh attempt, and list the file in the handoff. | task-specific | Concerns the environment-identity defect of task 201 only. |
| bullet 7.2 | Any other change outside the listed files is a change of scope. | enforced by the engine | `enforce_scope` raises `SCOPE_CHANGE_REQUIRED` for any path outside the frozen Expected code surface. |
| bullet 8.1 | Before stopping for a change of scope, finish everything else, commit it, and run the repository check and the affected tests, so that one stop names every file needed. | project decision | Entry `finish-before-scope-stop`, steps `blocked`: finish, commit and check everything else before a scope stop. Delivered with the scope stop. |
| bullet 8.2 | "...so that one stop names every file needed" (second clause of the sentence above) | enforced by the engine (to add) | F10: `enforce_scope` reports all out-of-surface paths at once; it rejects at the first today (`scope.py` line 84). |
| bullet 9.1 | A change of scope, a guardrail, and every action the project's workflow denies remain stops. | enforced by the engine | Guardrail codes with `human_decision: true`; the same rule is in `PROJECT_WORKFLOW.md`. |

Result: of the block's sentences, the rules that remain as `decisions` entries are the six marked *project decision*, about ten lines in total, and each is delivered at one step. Everything else is a stop fix, an engine check, or specific to task 201.

## 6. The follow-up tasks

Each task is one implementer session. IDs are assigned by the coordinator with `cardine task new`; `F<n>` names them here. Every conversion task adds, for each `N`/`A` row it converts, the crash test for the deciding boundary and the ADR 12 test that the returned command advances the task. Per the project rule that no two open tasks edit one line, all registry and render changes are in F1; conversions depend on it and never edit the registry.

| Id | Task | Files it would touch | Depends on |
| --- | --- | --- | --- |
| F1 | Stop class plumbing: five codes, `waiting` resolution, `retry_after_seconds` field, `refusal()` helper, `diagnostic_result` waiting branch | `capabilities/stop-codes-v1.json`, `src/cardine/stops/registry.py`, `src/cardine/stops/render.py`, `src/cardine/lifecycle/engine.py`, `tests/test_stop_registry.py`, `docs/RUN_COMMANDS.md` | none |
| F2 | Recovery loop guard `RECOVERY_NOT_ADVANCING` in `dispatch_run`, counted in the stop journal | `src/cardine/lifecycle/engine.py`, `src/cardine/shared/journal.py` (`stopped`, line 78), `tests/test_run_recovery.py` | F1 |
| F3 | Convert delivery and preparation rows (`delivery.py` N/A/P/W/L rows, `preparation.py` N/A/L/P rows) | `src/cardine/lifecycle/delivery.py`, `src/cardine/worktree/preparation.py`, `tests/test_run_delivery.py`, `tests/test_run_preparation.py` | F1 |
| F4 | Reverse an owned stale candidate and restage (`candidate.py:48,56,65,74,271`, `merge.py:197,199,317`, `finalize.py:94,115,120`, `preview.py:58,70,91`), reusing the `ENGINE_PRINCIPAL` abort; `candidate.py:170,206` | `src/cardine/integration/candidate.py`, `src/cardine/integration/merge.py`, `src/cardine/integration/finalize.py`, `src/cardine/lifecycle/preview.py`, `tests/test_run_integration.py` | 201, F1 |
| F5 | Closure and cleanup recoveries (`records.py` N/A rows, `finalize.py:68,123`, `cleanup.py:79,93,141,146,196,201,242,310`) | `src/cardine/integration/records.py`, `src/cardine/integration/cleanup.py`, `tests/test_run_integration.py` | F1, F4 (shares `finalize.py` and the test file; sequence after it) |
| F6 | Remaining validation rows (`validation.py:108,168,232,266,283`) | `src/cardine/lifecycle/validation.py`, `tests/test_run_validation.py` | 201, F1 |
| F7 | Control and preview rows (`control.py:116,141,153,165,171`, `preview.py:76,107,118,136`) | `src/cardine/lifecycle/control.py`, `src/cardine/lifecycle/preview.py`, `tests/test_run_control.py` | F1, F4 (shares `preview.py`) |
| F8 | Stop message pass, lifecycle modules: apply `refusal()` to every remaining `T`/`D` stop and make `VALIDATION_RETRY_LIMIT` list the failed commands | `src/cardine/lifecycle/delivery.py`, `validation.py`, `preview.py`, `control.py`, `tests/test_run_validation.py` | F3, F6, F7 |
| F9 | Stop message pass, worktree and integration modules (same, for the remaining `T`/`D` stops of part 4) | `src/cardine/worktree/preparation.py`, `src/cardine/integration/candidate.py`, `finalize.py`, `cleanup.py`, `records.py`, `merge.py`, `tests/test_run_integration.py` | F4, F5 |
| F10 | `enforce_scope` reports every out-of-surface path in one `SCOPE_CHANGE_REQUIRED` stop (it rejects at the first today, `scope.py` loop near line 84) | `src/cardine/lifecycle/scope.py`, `tests/test_execution_boundaries.py` | none |
| F11 | Inventory and classify the out-of-module helpers named in part 2 (a docs spike) | `docs/ENGINE_STOP_CLASSIFICATION.md` | none |
| F12 | Standing decisions: declaration key and validator, frozen `decisions` in the contract, digest comparison diagnostic at the `contract` step | `src/cardine/shared/project.py`, `src/cardine/tasks/contract.py`, `src/cardine/lifecycle/engine.py` (`contract` step only), `tests/test_single_workflow_config.py`, `tests/test_contract_snapshot_readers.py` | F1 |
| F13 | Deliver decisions at the step: pass the raising stage as `step` to `diagnostic_result`, `WorkRequest.decisions`, `work.decisions` in the schema, `DECISION` diagnostics, `preview.py:92-96` rebuild | `src/cardine/lifecycle/model.py`, `src/cardine/lifecycle/engine.py`, `src/cardine/lifecycle/preview.py`, `schemas/run-v1.schema.json`, `docs/RUN_COMMANDS.md`, `tests/test_run_*.py` | F12, F7 (shares `preview.py`), F2 (shares `dispatch_run`) |
| F14 | `cardine execution contract` prints frozen validation policy and decisions | `src/cardine/tasks/preflight.py`, `tests/test_execution_boundaries.py` | F12 |
| F15 | Briefing delivers `always` entries | `src/cardine/hosts/briefing.py`, `tests/test_host_briefing.py` | F12 |
| F16 | Move the project-wide block out of the task blueprint: add the `decisions` and a repository-guards baseline command to `.cardine/project.json`, remove the block from `tasks/TASK_BLUEPRINT.md`, amend ADR decisions 12 and 13 | `.cardine/project.json`, `tasks/TASK_BLUEPRINT.md`, `docs/ADR_CARDINE_1_0.md` | F2, F10, F13, F14, F15 |

F1 comes first: nothing else can edit the registry. F3, F6 and F10 can then run in parallel with F12. F4 waits for task 201 because both edit `candidate.py`.
