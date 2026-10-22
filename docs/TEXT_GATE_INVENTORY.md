# Text gate inventory

Authority: decision 13 of [`ADR_CARDINE_1_0.md`](ADR_CARDINE_1_0.md) ("Gates
read facts, not prose"); work items 7 and 8 of the same ADR; task 073.

- **Taken on `main` commit**: `9dc36b94223557c6f3e9316dfbe4aaa919c96954`
  (`Add decision 13 and plan task 073: gates read facts, not prose`), on
  2026-10-22. Every file and line below refers to that commit.
- **Scope**: `src/cardine/` and the product helpers under `scripts/` that
  product code imports. Nothing else was read for entries.
- **Changes**: this file only. No code, template, or test was changed.

## How to read this inventory

An *entry* is one place where product code takes a gate, verdict, status,
eligibility, or stop decision from text instead of from the task state and its
contract snapshot, Git, or the results of commands Cardine executed itself.
Each entry has a stable ID (`T-nn`, integrity `I-nn`, legacy `L-nn`) so that
tasks 072 and the work item 8 records can cite it.

Exactly one class of decision 13 per entry:

| Code | Class | Destination rule |
|------|-------|------------------|
| **AP** | Agent prose as evidence: text an agent writes, used as a gate | Replaced by a fact from state, Git, or a command Cardine runs, or removed |
| **HC** | Human contract input: intent a person writes in the record | Read once by `cardine task new` into the contract snapshot (tasks 053, 066), then read from state |
| **MI** | Managed text integrity: bytes Cardine installs and checks | Kept |
| **GV** | Generated view: queue or plan text, or a projection of state | Never read by a gate (task 067) |

"Written by" names the actor that produces the text. Where an entry reads text
that Cardine itself writes as a projection of state (the record `Status:`
line, review attempt headings), it is class **GV** or **AP** by how the
reader uses it, and the entry says so.

## Search commands (repeatable)

All searches run against the pinned commit with `git grep`, which does not
depend on the shell or on a `grep` alias:

```bash
C=9dc36b94223557c6f3e9316dfbe4aaa919c96954
# S1  field readers on Markdown records
git grep -nE 'read_task_field\(' $C -- src/cardine scripts
# S2  every regular expression in product code (filter by file afterwards)
git grep -nE 're\.(compile|search|match|fullmatch|findall|finditer|sub)\(' $C -- src/cardine scripts
# S3  agent-reported results passed as options or arguments
git grep -nE -- '--(validation|candidate)-exit-code|validation_exit_codes|candidate_exit_codes|--accepted' $C -- src/cardine scripts
# S4  text of records, handoffs, reviews, queue, plan read from disk
git grep -nE '(task_path|handoff_path|review_path|queue_path|plan_path|report)\.read_text|read_text\(encoding="utf-8"\)' $C -- src/cardine scripts
# S5  record, handoff, queue, and review vocabulary in patterns
git grep -nE 'Status:|Current task commit|Completion Report|## Attempt|\[x\]|## Dependencies|## Validation|## Host impact' $C -- src/cardine scripts
# S6  scripts that product code imports (through the SCRIPTS_ROOT path insert in cli.py)
git grep -nE '^\s*(from|import) (codex_read_guard|stop_audit|console_workflow|cardine_cli|align_queue|ci_evidence)' $C -- src
# S7  legacy boundary: nothing outside cardine.legacy imports it
git grep -nE 'cardine\.legacy' $C -- src scripts
```

Each hit of S1 to S5 was read in context and either became an entry or was
excluded in the section [Examined and excluded](#examined-and-excluded).

Results on the commit:

- **S1**: 23 matches. That is 22 calls plus the definition in
  `src/cardine/shared/text.py:8`; 21 of the calls are outside
  `cardine.legacy`. This is the ADR's "23 calls": the ADR counted the
  definition. The calls read `Class` (14, 13 outside `cardine.legacy`),
  `Status` (5), `Review` (1), `Deliverable` (1), and the spike fields
  `Question`, `Timebox`, and `Deliverable` through one comprehension (1).
- **S2**: 164 matches in product files outside `cardine.legacy`,
  `templates/`, `hosts/`, and `release/`. Most match identifiers, versions,
  digests, and paths. The regular expressions that read record, handoff,
  review, queue, or plan text are the ones in the entries below, mostly in
  T-03 to T-12, T-19 to T-21, T-23 to T-29, and T-32 to T-35. The ADR's
  "about a dozen" is the same order of magnitude; this inventory lists every
  site rather than counting patterns.
- **S3**: 23 matches, which form the paths T-38 to T-44 plus the prose
  `exit N` check of T-20. The ADR's "8 code paths" is those eight: T-38,
  T-39, T-40, T-41, T-42, T-43, T-44, and T-20. T-44 (`cardine validation`)
  consumes an exit code from a JSON file rather than an option.
- **S6**: product code imports exactly two scripts, `codex_read_guard`
  (`src/cardine/cli.py:851`) and `stop_audit` (`src/cardine/cli.py:855`).
  `scripts/console_workflow.py` and `scripts/cardine_cli.py` are
  compatibility adapters that tests and `check_repository.py` import; no
  product command imports them. Other scripts run as separate programs and
  are outside this scope.
- **S7**: nothing in `src/` or `scripts/` imports `cardine.legacy`. The
  import-graph test `tests/test_legacy_meridian_installation.py:304-324`
  (`test_import_graph_has_no_product_consumer_of_legacy`) enforces it for
  `src/cardine`, `scripts`, and `hooks`.

## Summary

| Class | Entries | Destination |
|-------|---------|-------------|
| AP, agent prose as evidence | 18 | Replace by facts or remove (rows listed per entry) |
| HC, human contract input | 17 (T-01 is the creation read, kept) | Freeze in the contract snapshot, then read state |
| GV, generated view | 11 | Never read by a gate |
| MI, managed text integrity | 6 (T-05 and I-01 to I-05) | Kept |
| Total product entries | 52 (T-01 to T-47 plus I-01 to I-05) | |
| `cardine.legacy` | 8 (L-01 to L-08) | Kept until work item 10 |

Of the 47 `T-` entries, one is kept as the creation path (T-01) and one as
integrity (T-05); the other 45 need a removal or a move, and each names its
row.

## Product entries

### A. Task record fields

The record is `tasks/NNN.md`, written by a person (or by `cardine task new`
from a person's text) and edited by agents afterwards.

| ID | Where (`file::function:line`) | Text read | Written by | Decision driven | Class | Destination |
|----|-------------------------------|-----------|------------|-----------------|-------|-------------|
| T-01 | `tasks/contract.py::_contract_field:23`, `task_contract_options:38`, `resolve_task_contract:62-132`; called from `tasks/creation.py:126` and `cli.py:759` (`task new`) | Every blueprint field: `ID`, `Class`, `Category`, `Review`, `Options`, `Dependencies`, `Objective`, `Acceptance Criteria`, `Validation`, `Authority`, spike fields | A person | Builds the contract snapshot once, at creation | HC | **Kept**: this is the contract creation path of decision 13. Allowlisted by the guard (G1). |
| T-02 | `tasks/transitions.py::transition_task_state:43-45` (backfills a missing `contract`), `lifecycle/commands.py::execution_start:50-51` (re-resolves the options for preflight), `tasks/importer.py::import_task_states:97` | The whole record, through `resolve_task_contract` | A person | Options that gate preflight, and a snapshot invented after creation | HC | **N2** removes the first two (a task without a registered contract is `TASK_STATE_MISSING`, per SS3). The third moves with T-31. |
| T-03 | `tasks/contract.py::host_impact_section:184`, `host_impact_field:195`, `host_impact_required_profiles:200`, `validate_host_impact_declaration:246`; reached after creation from `tasks/preflight.py::execution_preflight:53` (every `execution validate`, `execution start`, and `ready-check`) | `## Host impact` declaration and profile table | A person | `HOST_IMPACT_DECLARATION_INVALID` before every validation run | HC | **N2**: creation already validates it (`contract.py:102`); freeze the classification in the snapshot and stop re-reading. |
| T-04 | `tasks/contract.py::verify_host_impact_completion_evidence:264-281`; called by `tasks/preflight.py::readiness_check:197` | `- [<profile>]: <evidence>` lines in the record's host-impact section | The implementing agent | `HOST_IMPACT_EVIDENCE_MISSING` blocks `in_review` | AP | **N3**: replace by an evidence entry written by a Cardine command (extend `cardine execution evidence`); no row of SS5 to SS7 or RE1 to RE7 names it. |
| T-05 | `tasks/contract.py::contract_digest:146`, `contract_requires_execution_commands:151`; read by `tasks/preflight.py::execution_preflight:55-78` | The generated block `- Profile revision: sha256:…` and `- Execution commands: …` | `cardine execution contract` (`preflight.py::execution_contract:27-40`) | `EXECUTION_CONTRACT_UNRESOLVED` | MI | **Kept**: Cardine writes the block and compares its digest with the profile byte for byte. A defect sits next to it, see [Defects found](#defects-found). |
| T-06 | `tasks/preflight.py::execution_preflight:85-111` | Headings `## Authority`, `## Validation`, `## Expected code surface`; spike fields `Question`, `Timebox`, `Deliverable` | A person | `TASK_RECORD_INCOMPLETE` | HC | **N2**: creation already requires the same fields (`contract.py:84-101`). Remove the second read. |
| T-07 | Reads: `tasks/preflight.py::execution_preflight:112` and `reconcile_execution_contract:162`; `worktree/checkout.py::registered_worktree_task_states:385`; `tasks/audit.py::audit_task_state_projections:59`; `tasks/importer.py::import_task_states:89`; `shared/console_workflow.py::record_status:169`. Writes: `tasks/transitions.py::transition_task_state:74`; `review/verdict.py::record_review_verdict:75,114`; `integration/merge.py::stage_task_integration:352`; `lifecycle/execution.py::_execution_worktree:82` (expects the projected text) | The record's `Status:` line | The current blueprint no longer seeds it; Cardine commands rewrite the line only where an older record has it (`re.sub` is a no-op otherwise) | `TASK_STATUS_REJECTED`; the state listing of `worktree states`; repeated-start tolerance | GV | **SS5** ("Record `Status:`") removes the preflight, reconcile, audit, importer, and transition and verdict writes; **SS6** removes the merge write. `checkout.py:385` and `execution.py:82` are named by no SS row scope text: **N2** takes them. Class GV because Cardine writes the line from state; no gate may read a projection of the state it already holds. |
| T-08 | `tasks/preflight.py::execution_preflight:121-154` | The queue row's `Status` cell compared with the record `Status:` | A person (legacy queues) | `QUEUE_STATUS_MISMATCH` | GV | **SS5** ("Record/queue agreement as a gate"). |
| T-09 | `tasks/preflight.py::check_dependencies:203-229`, called by `tasks/transitions.py:53-55` on `queued` to `in_progress` | `## Dependencies` section, `Depends on` line | A person | Whether a task may start (`TASK_STATUS_REJECTED`) | HC | **N1**: dependencies are not in the contract schema (`schemas/task-state-v1.schema.json`), so SS5, which removes status gates, does not cover them. SS plan "Duplicates to remove" even says dependencies must not be satisfied by prose, yet this reads them from prose. |
| T-10 | `tasks/status.py::_field:14`, `_dependencies:31-47`, `load_task_snapshot:95-132` (record scan by `ID`, `title`, `Phase`), `order:156-158` (`Priority`) | `ID`, `## Dependencies`, first heading, `Phase`, `Priority` | A person | **Startable** (eligibility) and its blocked-by list; ordering; labels | HC | **N1**. SS2 delivered this reader; no later SS row reassigns it. |
| T-11 | `tasks/identity.py::_task_record_id:183-203` | `> **ID**:` or `ID:` line of every Markdown file under the task roots | A person | Identity resolution of every command: which file is the record, ambiguity stops | HC | **N1** (store the record path in the snapshot, or derive it from the stable path of SS6) so identity resolution stops scanning record text. SS5 names `identity.py` only for queue links and status. |
| T-12 | `tasks/identity.py::_task_authorities:224-257` and `resolve_task_identity:375-390` | Queue table rows and links | A person or older tooling | "ambiguous authoritative artifacts", "queue and task authorities disagree", "queue link … does not resolve" stops | GV | **SS5/SS6** ("Archive path as closure evidence" names `identity.py` and queue links); **SS7** for the console side. |
| T-13 | `Class` field, 13 product sites: `tasks/audit.py:48`, `tasks/transitions.py:31`, `tasks/preflight.py:92,101`, `lifecycle/execution.py::_execution_state:110`, `lifecycle/commands.py::execution_start:32`, `review/verdict.py:32`, `integration/merge.py:59,132,584`, `integration/projections.py::_queue_state_resolver:317`, `console/snapshot.py::_read_console_state:344`, `tasks/importer.py:161` | `Class: SPIKE` | A person | The `spike=` argument of `read_task_state`, which selects the state machine and spike landing rules | HC | **N2**: `contract.class` is already in the snapshot (`task-state-v1.schema.json`); read it. Row scope text: SS5 names the first four files, SS6 `commands.py`, `merge.py`, `projections.py`, SS7 the console, RE3 `execution.py`; none states that the `Class` read must go, so each task would otherwise keep it. **Task 069 removed** `_queue_state_resolver`; the remaining class readers stay in N2. |
| T-14 | `shared/console_workflow.py::record_review:176`, reached from `integration/merge.py::_integration_task_state:95-96`, `integration/projections.py::_governed_completion_row:184,193`, `console/snapshot.py::_build_snapshot:748`, `tasks/importer.py:101,161`; creation read in T-01 | `Review:` line | A person | Whether a review is required (legacy path) | HC | `contract.options.review` already holds it. **SS6** (merge, projections), **SS7** (console), **SS5** (importer isolation). **Task 069 removed** `_governed_completion_row` and its obsolete merge import; the other readers remain. |
| T-15 | `tasks/evidence.py::validation_commands:9`, `require_named_validation_commands:21`; after-creation callers: `tasks/preflight.py::execution_contract:31-32`, `execution_preflight:52`; `tasks/contract.py::verify_execution_evidence:331`; `lifecycle/execution.py::delivery_readiness:232`; `tasks/recording.py::run_validation:41-43` | `## Validation` bullets ``- `id`: `command` `` | A person | Which commands the runner executes and which must have passed before `in_review` | HC | `contract.validation.commands` holds them since task 053. **N2** switches these readers. **RE3** (`lifecycle/validation.py`, "execute missing/stale declared validation") builds the runner but its scope text never says to read the declarations from the snapshot: state it there. |
| T-16 | `integration/merge.py::_spike_disallowed_paths:46-79` (line 70) | `Deliverable` of a SPIKE record, and the backticked `docs/…` paths inside it | A person | Stops landing when the diff touches other paths | HC | **N1** adds `contract.deliverables`; **N2** reads it. Not covered by SS6, whose scope names `merge.py` only for candidate and review gates. |
| T-17 | `shared/flow.py::_flow_origin:83` | `> **Origin**:` header | A person | Nothing: it labels rows of the flow report (`scripts/dev.py`) | HC | **N1** freezes `origin` in the snapshot, or the label is dropped. The guard flags it either way. |
| T-18 | `shared/authority.py::authority_entries:117`, `context_authority:172`; `shared/context.py::context_size_report:206`; `scripts/codex_read_guard.py::is_exempt:126` (parses the `### <path> —` headings of the generated excerpt) | `## Authority` citations | A person | Which files the Codex read guard exempts from blocking (an allow/deny decision) | HC | **N1** freezes the citations in the snapshot; the read guard then reads state. No SS or RE row covers it (work item 9 rebuilds the hook but does not mention the exemption). |

### B. Handoff and completion report

The handoff is `tasks/handoffs/<ID>.md`, written by the implementing agent.

| ID | Where | Text read | Written by | Decision driven | Class | Destination |
|----|-------|-----------|------------|-----------------|-------|-------------|
| T-19 | `tasks/contract.py::check_handoff:388-432`, `HANDOFF_FIELDS:164-172`; regexes at lines 398, 400, 403, 422 | Seven field labels of the form `- <Field>: <value>`, and the heading `Completion Report — <ID>` | The implementing agent | `HANDOFF_FIELDS_MISSING`, `HANDOFF_FIELD_FORMAT`, `HANDOFF_TASK_MISMATCH`; gate to `in_review` through `readiness_check` and `delivery_readiness` | AP | **N3**: delete the check. The handoff stays an explanation for people. |
| T-20 | `tasks/contract.py::verify_validation_skips:299-324`; regexes at lines 301, 304, 306 | `Validation skips` and the `Validation` line, searched for `exit <non-zero>` | The implementing agent | `HANDOFF_VALIDATION_FAILING` | AP | **N3** removes the check; **RE3** supplies the fact (the runner records actual exit codes). RE3's scope text does not say the prose check goes. |
| T-21 | `tasks/contract.py::verify_execution_evidence:327-385`; regexes at lines 351 and 355; substring match at 372-377 | `Isolated exploration` (`none`/`no`), and the exact question and finding text inside the report | The implementing agent | `HANDOFF_EXPLORATION_MISMATCH`, `HANDOFF_EXPLORATION_SUMMARY_MISSING` | AP | **N3**. The half that reads `.cardine/execution-evidence.json` (`exitStatus == 0`, lines 331-348) is a fact from a Cardine command and duplicates `delivery_readiness:231-239`. |
| T-22 | `lifecycle/execution.py::_delivery_current_commit:143-163` (regex at 146, called at 226) | `- Current task commit:` line | The implementing agent | `EVIDENCE_INCOMPLETE` on `execution deliver` and `ready-check` | AP | **Task 072, rescoped** (see [Task 072](#task-072)). **Removed by task 072**: `_delivery_current_commit` and its call no longer exist. |
| T-23 | `worktree/checkout.py::inspect_task_worktree:263-275` (regex at 271) | `- Branch:`, `- Worktree:`, ``- Base `main` commit:`` lines | The implementing agent, who copies the values `worktree prepare` returned | `handoff-mismatch`, which makes `worktree check` report `WRONG_WORKTREE` | AP | **N3**: the facts are in the lifecycle state file (`checkout.py:244-262`) and Git. |
| T-24 | `shared/console_workflow.py::handoff_status:183` (`HANDOFF_STATUS:15`), via `console/snapshot.py::_branch_facts:453` and `effective_state:313-315` | A `Status:` line in the handoff | The implementing agent | Console "queue `[x]`, handoff …" mismatch | AP | **SS7** (console switch to shared facts). |

### C. Review record

The review record is `tasks/reviews/<ID>.md`.

| ID | Where | Text read | Written by | Decision driven | Class | Destination |
|----|-------|-----------|------------|-----------------|-------|-------------|
| T-25 | `shared/console_workflow.py::latest_review_verdict:188` (`REVIEW_ATTEMPT:18`), via `integration/projections.py::_governed_completion_row:206`, `console/snapshot.py::_branch_facts:454`, `tasks/importer.py:109-112` | `## Attempt N — <VERDICT>` headings | Cardine appends the heading when a reviewer runs `cardine review verdict` (`verdict.py::_review_attempt_text:137`); older reviews were typed by people | The verdict of a queue-driven completion; console readiness | AP | **SS5** ("Review display": "no status reader may recover a verdict from report headings"), which covers it. **Task 069 removed** the `_governed_completion_row` caller; the other readers remain. |
| T-26 | `integration/merge.py::_integration_task_state:91-110` (the branch taken when the project has no state directory) | Record `Review:`, the queue row, the latest review heading | People and agents | `REVIEW_NOT_APPROVED` on landing, instead of `TASK_STATE_MISSING` | AP | **SS6** (exact-commit review gates in `merge.py`). The scope text does not say that the prose fallback is removed; the SS6 tests must cover a project without states stopping instead of reading prose. |

### D. Queue, plan, and console

| ID | Where | Text read | Written by | Decision driven | Class | Destination |
|----|-------|-----------|------------|-----------------|-------|-------------|
| T-27 | `integration/projections.py::_queue_task_rows:36-61`, `_QUEUE_TASK_ROW:67`; callers `tasks/audit.py:33`, `tasks/importer.py:43`, `projections.py:364,391,465,524` | Queue checkbox and `Status` cells | A person, or older tooling | Which rows exist and what status they hold | GV | **SS6** (projection mutation route), **SS5** (audit, importer). **Task 069 removed** the projection mutation callers; `_queue_task_rows` remains for the explicit importer. |
| T-28 | `integration/projections.py::_governed_completion_row:106-232`, called by `projections.py:526` and `merge.py:101` | `ID`, `Status`, and `Review` columns, the record, and the review record | People | Accepts or refuses completion of a queue row; rewrites its status cell | GV | **SS6**. **Removed by task 069**: `_governed_completion_row` and its callers no longer exist. |
| T-29 | `integration/projections.py::_apply_task_completion_rows:508-566` (plan row pattern at 541-551), `_completed_task_row:25`, `_queue_section_completion:249`, `_queue_section_decisions:354`, `_archive_completed_queue_sections:418`, `_relink_archived_task_row:479` | Queue and plan rows (`[x]`, `done`), section tables | People | `integrate stage` edits and archives queue sections and plan rows | GV | **SS6** ("remove phase archival as lifecycle machinery"); the renderer of SS4 supplies the replacement. **Removed by task 069**: queue/plan status mutation, relinking, and phase archival no longer exist. |
| T-30 | `tasks/audit.py::audit_task_state_projections:19-67` | Queue and archive rows, record `Status:` | People | `ADVISORY` drift results in `cardine audit` | GV | **SS5** ("Projection drift and import"). |
| T-31 | `tasks/importer.py::import_task_states:26-178`, reached from `cli.py:776` (`cardine task state`) | Queue rows, record `Status`, `Review`, `Class`, review attempt headings | People and agents | Infers a task's status and verdict and writes a state file | AP | **SS5** ("isolate importer"). Recommendation: move it to `cardine.legacy` and remove it from the product `task` namespace, so the guard keeps only three allowlist categories. |
| T-32 | `console/snapshot.py::_branch_facts:418,443`, `_build_snapshot:667-668`; `shared/console_workflow.py::parse_queue:75-123` | Queue table | People | Console task list and lifecycle | GV | **SS7**. |
| T-33 | `console/snapshot.py::_branch_facts:431,452`, `_build_snapshot:724,749,842` (the `legacy` flag); `shared/console_workflow.py::record_status:169` | Record `Status:` when no state exists | Cardine (projection) | Console status when `state is None` | GV | **SS7** ("prose fallbacks"). |
| T-34 | `console/snapshot.py::_build_snapshot:748`; `console/models.py:100,145-147` | Record `Review:` string `REQUIRED`/`NOT REQUIRED` | A person | Whether the console offers `Review <ID>` | HC | **SS7**; state holds it. |
| T-35 | `shared/console_workflow.py::effective_state:223-321` (branches taken without a state snapshot) | Queue row, record status, handoff status | Mixed | Effective lifecycle of a task | GV | **SS7**. |
| T-36 | `console/snapshot.py::_task_path:146-147`, `_section:159-163`, `_closing_task:556`, `_build_snapshot:819`; `shared/console_workflow.py::heading_title:163` | First heading of the record, level-two headings | A person | Display title and record lookup | HC | **N1** (store `title` in the snapshot), **SS7** (display). |
| T-37 | `hosts/briefing.py::render_briefing:24-30` | Heading lines `[Meridian … Queue]` of the frozen hook's payload | The frozen copied hook | None (strips lines for display) | GV | **SS7** ("Briefing payload" row of the plan). |

### E. Results that an agent declares

An exit code or a flag that an agent passes is not evidence (decision 13).
These are the eight code paths of the ADR, plus the options that feed them.

| ID | Where | Declared input | Decision driven | Class | Destination |
|----|-------|----------------|-----------------|-------|-------------|
| T-38 | `cli.py:259-266,678-685` (`worktree evidence` options); `integration/evidence.py::record_task_evidence:270-332` (`validation_passed = all(code == 0)` at 310; `interaction_assessment_complete: True` hard-coded at 314) | `--validation-command`, `--validation-exit-code`, `--accepted`, `--task-dependency`, `--task-behavioral-surface`, `--main-advanced-*`, `--full-validation-required` | The `.evidence.json` file that drives landing | AP | **RE3** persists actual exit codes (covers validation results); **RE5** covers the decision. Neither scope text says the options and the declared lists disappear: amend both. |
| T-39 | `cli.py:281-285,713-720` (`worktree advance` options); `lifecycle/closure.py::advance_task_closure:75-76,139-163` (step C5) | Same options; `--accepted` | `VALIDATION_FAILED`, `ACCEPTANCE_UNMET`, then evidence recording. The call passes empty dependency and surface lists and `full_validation_required=False` (lines 152-156), so the declared integration surface is constant on this path | AP | **RE3** (amend as T-38). |
| T-40 | `lifecycle/closure.py::advance_task_closure:205-208,240-272` (step C7); candidate file written with `"passed": True` (lines 265-272) | `--candidate-command`, `--candidate-exit-code` | Aborts the integration on a non-zero code, otherwise writes the candidate evidence that `finalize` trusts | AP | **RE5** ("candidate execution from resolved config; candidate retry/abort"): the engine runs the commands. |
| T-41 | `integration/merge.py::stage_task_integration:243-300`; `integration/decision.py::decide_integration_validation:30-97` | `accepted`, `validation_passed`, `full_validation_required`, `interaction_assessment_complete`, `task_dependencies`, `task_behavioral_surfaces`, `main_advanced_*` read from `.evidence.json` | Chooses REUSE, BOUNDED, or FULL validation and whether staging proceeds | AP | **RE5**. Scope gap: the row names the REUSE/BOUNDED/FULL tests, not the removal of the agent-declared lists. Derive the decision from Git paths only. |
| T-42 | `worktree/closure_status.py::closure_status:111-125` | Same `.evidence.json` fields | Whether step C5 or C6 is next | AP | **RE5/RE1** (the resolver replaces `closure-status`). |
| T-43 | `integration/merge.py::finalize_task_integration:415-455` | `candidate_tree`, `passed`, `commands` of the candidate evidence file | Whether the merge candidate is finalized | AP | **RE5**. |
| T-44 | `integration/evidence.py::check_validation_evidence:86-135`, via `cli.py:786-792` (`cardine validation`) | A JSON attestation: `exit_code`, `ci`, `shards`, `attested_by`, `statement` | `VALIDATION_PASSED`, `VALIDATION_FAILED`, pending | AP | **RE6** (exact-head CI through a command Cardine runs). Open question for RE6: `T3_ATTESTED` is a developer's own attestation (`attested_by: developer`); either it stays as an explicit human override outside decision 13's sources or it goes. Record that choice when RE6 is written. |

### F. Configuration and telemetry read from prose

| ID | Where | Text read | Written by | Decision driven | Class | Destination |
|----|-------|-----------|------------|-----------------|-------|-------------|
| T-45 | `tasks/identity.py::read_execution_assets:57-66`, `resolve_project_locations:68-104` | Sentences of `PROJECT_WORKFLOW.md` such as "task files live at", "Completion handoffs live at", "ADR log is", and queue paths in backticks | A person | Locations of queue, task roots, handoffs, reviews, ADR log, used when `.cardine/project.json` is absent (prints `DEPRECATED`) | HC | **N2** removes the prose fallback; `.cardine/project.json` (`shared/project.py`) is the source. No SS or RE row covers it. |
| T-46 | `scripts/codex_read_guard.py::threshold_for:107` | `` `Read-guard threshold`: N `` in `docs/EXECUTION_EVIDENCE_PROFILE.md` | A person | How many lines the Codex read guard allows | HC | Removed by decision 5's single automatic limit (work item 4, "budget counters", and work item 9 for the hook rebuild). |
| T-47 | `scripts/stop_audit.py::BLOCKED_LINE:22`, `final_message:27-50`, `audit:73-` | `BLOCKED <CODE>` lines in the agent's final message | The agent | Writes `unbacked_block` or `declared_block` journal lines; no stop or status depends on them | AP | **Work item 9** (one Python implementation of each hook). Once stops come only from the engine and its journal (decision 12, RE7), prose matching has nothing to audit. RE7 does not name the hook. |

## Managed text integrity entries (kept)

Cardine installs this text and compares it byte for byte or by digest. None
of it is a record, handoff, report, queue, or plan.

| ID | Where | What is checked | Note |
|----|-------|-----------------|------|
| T-05 | `tasks/contract.py:146-152`, `tasks/preflight.py:55-78` | Execution-contract block of a record against the profile digest | Listed above for its record context. |
| I-01 | `templates/markers.py`, `marker_audit.py`, `marker_history.py`, `merge.py`, `upgrade.py`, `upgrade_support.py`, `migrations.py:246`, `migration_audit.py:53` | `CARDINE:BEGIN`/`END` capability blocks and their baselines | The product is the text. |
| I-02 | `templates/audit.py:48,470`, `manifest.py:33`, `files.py`, `generator.py` | Manifest digests, retired-text registry patterns | Same. |
| I-03 | `templates/router.py:27,117,120` | Entry-router overlay and trigger rows | Installed router text. |
| I-04 | `hosts/codex.py:62-165` | `# CARDINE:BEGIN`/`END` blocks in the Codex configuration and rules | Managed blocks in user files. |
| I-05 | `shared/context.py::_context_routed_workflow:79-88`, `context_size_report:173-206` (router paths, byte counts) | Sizes and cited paths of installed router documents | A measurement, not a gate on any task. Decision 5 replaces the threshold. |

## `cardine.legacy` (kept until work item 10)

Counted as entries, not as matching lines: **8 entries**, found by S1 to S5
restricted to `src/cardine/legacy/` (32 matching lines: 7 in
`meridian_installation.py`, 25 in `snapshot.py`).

| ID | Where | Text read |
|----|-------|-----------|
| L-01 | `legacy/meridian_installation.py::read_meridian_execution_assets:43-44` | Execution-assets block of `PROJECT_WORKFLOW.md` |
| L-02 | `legacy/meridian_installation.py::detect_meridian_mode:86` | Workflow text, to detect the mode |
| L-03 | `legacy/meridian_installation.py:31-32` | `MERIDIAN:BEGIN` capability markers |
| L-04 | `legacy/snapshot.py::_task_path:151-152`, `_section:164-168` | Record heading, level-two headings |
| L-05 | `legacy/snapshot.py::_read_console_state:345-349` | `Class` of the record |
| L-06 | `legacy/snapshot.py::_branch_facts:423,448,457-459` | Queue rows, record status, handoff status, review verdict |
| L-07 | `legacy/snapshot.py::_build_snapshot:672-673,753-754,824` | Queue and archive rows, review policy, record status, title |
| L-08 | `legacy/snapshot.py::_closing_task:561` | Record heading as the title |

**No product command reaches them.** S7 finds no importer outside
`cardine.legacy`, and `tests/test_legacy_meridian_installation.py:304-324`
fails if one appears. Caveat: the parsers they call live in
`shared/console_workflow.py` (`parse_queue`, `record_status`, `record_review`,
`handoff_status`, `latest_review_verdict`, `heading_title`), which the product
console imports today. SS7 should move them into `cardine.legacy` when the
product console stops using them; until then they are product entries
(T-24, T-25, T-32 to T-36).

## Template text that asks an agent to write a literal string a gate checks

Paths are under `templates/single/`.

| ID | File and line | Text | Gate | Change needed |
|----|---------------|------|------|---------------|
| TPL-01 | `docs/COMPLETION_REPORT_TEMPLATE.md:8` | `## Completion Report — <TASK-ID>` | T-19 (`HANDOFF_TASK_MISMATCH`) | Stop requiring it; keep the heading as a suggested outline only. |
| TPL-02 | `docs/COMPLETION_REPORT_TEMPLATE.md:10,36-42` | The seven labels `Files changed`, `Validation`, `Validation skips`, `Manual verification`, `Acceptance criteria`, `Isolated exploration`, `Blockers/deviations` in the form `- <Field>: <value>` | T-19, T-20, T-21 | Same: the report becomes free-form. |
| TPL-03 | `docs/COMPLETION_REPORT_TEMPLATE.md:14-15` and the `task-worktree-handoff` block | `- Branch:`, `- Worktree:` copied from `worktree prepare` | T-23 | Remove the instruction to copy values the state file already holds. |
| TPL-04 | `docs/COMPLETION_REPORT_TEMPLATE.md:16-19,23-35` | `Implementation commit`, `Validated task commit`, ``Validated base `main` commit``, `Current task commit`, and the paragraph about the descriptive form | T-22 | Remove the three commit lines the gate cannot use and the paragraph (task 072 rescoped). **Removed by task 072** from the product completion template. |
| TPL-05 | `docs/COMPLETION_REPORT_TEMPLATE.md:44-50` | The subject `Deliver <TASK-ID> for review` of the re-delivery commit | `execution deliver` creates it (`lifecycle/commands.py:70,84`), and `_delivery_later_commits:188` compares subjects | Cardine writes it, so no agent instruction is needed; keep only the explanation of the command. **Task 072 removed** the agent-facing delivery-subject requirement; Cardine still creates its delivery commit. |
| TPL-06 | `docs/COMPLETION_REPORT_TEMPLATE.md:36-37`, `docs/workflows/IMPLEMENTATION.md:85`, `PROJECT_WORKFLOW.md:303` | `Validation skips: <test name — test-reported reason; reported by command>`; the `exit` status in `Validation` | T-20 | Becomes explanatory once the check is removed. |
| TPL-07 | `docs/COMPLETION_REPORT_TEMPLATE.md:40` | `Isolated exploration: none` or question text | T-21 | Same. |
| TPL-08 | `docs/workflows/REVIEW.md:26-32` | The reviewer must resolve the handoff's commit field to `HEAD`, accept `Deliver <TASK-ID> for review`, and compare subjects | T-22, T-23 | Replace with the facts `execution deliver` and `worktree check` report. **Task 072 removed** the handoff commit-field steps; T-23 remains for N3. |
| TPL-09 | `docs/REVIEW_RECORD_TEMPLATE.md:14` | `## Attempt <N> — <VERDICT>` | T-25 | Written by `cardine review verdict`, not by the agent; no change except that no reader parses it. |
| TPL-10 | `tasks/TASK_BLUEPRINT.md:177-180` | ``- Execution commands: `required via cardine execution` `` | T-05 | The code expects `meridian execution` (see Defects found). Fix the code to use the product name. |
| TPL-11 | `tasks/TASK_BLUEPRINT.md` (Validation, Dependencies, Host impact sections) | ``- `id`: `command` ``, `- **Depends on**:`, the host-impact table | T-01 reads them once (kept), T-03, T-09, T-15 re-read them | Text stays: it is contract creation input. Only the later reads go. |
| TPL-12 | `PROJECT_WORKFLOW.md:93,103` | Sentences "Completion handoffs live at …", "durable review records at …" | T-45 | Keep for people; the code stops parsing them. |

## Destination coverage and proposed rows

A row "covers" an entry only when its **scope text** says the removal, not
because the row lists the file. Where that fails the entry says so above. The
gaps and the rows that close them (all proposals; none is written here):

| Row | Title | Size | Closes | Placement |
|-----|-------|------|--------|-----------|
| **G1** | Add the text-gate static guard as a ratchet | ~2h | Makes the rule enforceable now; every entry gets a known-violation key | First: depends only on 073. Any task may run it in parallel because it adds only a test. |
| **N1** | Extend the contract snapshot with the remaining human contract fields | ~3h | T-09, T-10, T-11, T-16, T-17, T-18, T-36 | Work item 7, before SS7 (070). Adds `dependencies`, `title`, `priority`, `phase`, `origin`, `deliverables`, `authority` citations, and the record path to `task-state-v1`, written by `cardine task new`. Status, `check_dependencies`, flow, the read guard, and identity resolution then read state. |
| **N2** | Read the frozen contract after creation | ~3h (split in two if needed) | T-02, T-03, T-06, T-07 (`checkout.py:385`, `execution.py:82`), T-13, T-14, T-15, T-16, T-45 | After N1. Replaces record reads of `Class`, `Review`, `## Validation`, host-impact declaration, required headings, and the `PROJECT_WORKFLOW.md` location fallback with `state["contract"]` and `.cardine/project.json`. |
| **N3** | Retire the handoff and report gates | ~3h | T-04, T-19, T-20, T-21, T-23, TPL-01 to TPL-08 | Work item 8, after RE3. Deletes `check_handoff`, `verify_*`, the handoff `Branch`/`Worktree`/`Base` check, and the `HANDOFF_*` stop codes. Adds an `execution evidence` kind for host-impact proofs. |
| **072′** | Remove the `Current task commit` gate | ~2h | T-22, TPL-04, TPL-05, TPL-08 (partly) | The existing task 072, rescoped (see below). Independent of N3. |
| RE3, RE5, RE6 | Scope amendments | | T-20, T-38, T-39 (RE3); T-40 to T-43 (RE5); T-44 (RE6) | Add one sentence each: remove the agent-declared options and files, and derive the decision from Git and engine results. |
| SS5, SS6, SS7 | No change | | T-07 (most), T-08, T-12, T-13 (their files), T-14, T-25, T-26 to T-37 | Their scope texts already name the removal. SS6 should add the removal of the prose fallback of T-26; SS7 should move the parsers listed under `cardine.legacy` into it. |
| Work item 9 | Hooks | | T-46, T-47 | As stated in the entries. |

Entries with a destination inside an existing row are not repeated here.

## Task 072

**Question**: does any product code other than `_delivery_current_commit` read
the handoff's commit fields, and is the delivered commit already recorded in
the task state transition?

Verified on `9dc36b9`:

1. `Current task commit` is read only at
   `src/cardine/lifecycle/execution.py:146`, inside
   `_delivery_current_commit`, which `delivery_readiness` calls at line 226.
   `git grep -n 'Current task commit' src scripts` finds that line and the
   error text at line 160.
2. `Implementation commit` and `Validated task commit` are read by no product
   code. `Validated base main commit` is read by none either; line 160 only
   names it in a message.
3. `src/cardine/worktree/checkout.py:271` reads three other labels: `Branch`,
   `Worktree`, and ``Base `main` commit``. It does not read a commit field of
   the delivery (T-23).
4. The integration evidence path does not read the handoff. `validated_task_commit`
   and `validated_base_commit` come from Git inspection and the lifecycle
   state file in `record_task_evidence` (`evidence.py:302-312`), and
   `stage_task_integration` compares them with Git (`merge.py:257-269`).
5. The state transition does **not** record the delivered commit. The
   `in_review` transition stores `HEAD` taken before the `Deliver … for
   review` commit exists (`transitions.py:61`; `commands.py:76` transitions, line 84 commits). `review.reviewed_commit` is `HEAD` at the verdict
   (`verdict.py:123-128`, called at 107). The delivered commit is nevertheless derivable
   from Git: it is the first commit of `git rev-list --reverse
   <transition.commit>..HEAD`, which is what `_delivery_later_commits` already
   walks (`execution.py:176-190`).
6. `delivery_readiness` already proves, from Git and command results, every
   fact the handoff line claimed: a clean canonical worktree, a committed
   handoff (`cat-file -e HEAD:…`, line 224), at least one committed change
   after the prepared base (line 221), every declared validation recorded by
   `execution validate` against the exact source digest and an ancestor of
   `HEAD` (lines 231-239), and no later commit except the handoff (lines
   176-190). The `Current task commit` check adds no fact; it compares what
   an agent wrote with `HEAD`.

**Recommendation**: do not cancel task 072; rescope it. Its current text
(make the stop copyable) keeps the gate and makes it easier to satisfy, which
decision 13 forbids. New scope, **"Remove the delivery commit gate"**:

- Delete `_delivery_current_commit` and its call in `delivery_readiness`
  (`execution.py:143-163,226`) and its tests.
- Remove the `Implementation commit`, `Validated task commit`, `Validated
  base main commit`, and `Current task commit` lines and the paragraph about
  the descriptive form from `templates/single/docs/COMPLETION_REPORT_TEMPLATE.md:16-35`,
  and the commit-field steps of `templates/single/docs/workflows/REVIEW.md:26-32`.
  Follow the pre-1.0 rule of task 031: raise the capability version, rewrite
  its baseline, add no migration.
- Keep `Deliver <TASK-ID> for review` as the subject Cardine itself creates;
  no agent writes it.
- Leave `Branch`/`Worktree`/`Base main commit` (T-23) to N3 and the stored
  delivery SHA to RE3, whose scope says the engine "records the delivered
  commit itself". Optionally RE3 adds `delivery_commit` to the transition.

## Static guard (decision 13) {#static-guard}

**Row**: G1, "Add the text-gate static guard as a ratchet", ~2h, depends on 073.
It lands first so that no entry can be added while the removals proceed, and it
needs no production change.

**File**: `tests/test_text_gates.py`, with the known-violation and allowlist
tables as constants in the test module.

**What it scans**: every `src/cardine/**/*.py` plus the two scripts product code
imports (`scripts/codex_read_guard.py`, `scripts/stop_audit.py`), parsed with
`ast`. Rules:

1. **Named readers.** Any reference to `read_task_field`, `_contract_field`,
   `task_contract_options`, `validation_commands`,
   `require_named_validation_commands`, the `host_impact_*` functions,
   `contract_digest`, `record_status`, `record_review`, `handoff_status`,
   `latest_review_verdict`, `parse_queue`, `_queue_task_rows`,
   `_governed_completion_row`, `check_handoff`, `authority_entries`, or
   `context_authority`.
2. **Text from disk.** A call to `.read_text(`, `open(`, or a Git `show` of a
   path whose expression contains `task_path`, `handoff_path`, `review_path`,
   `queue_path`, `plan_path`, `report`, or `record`.
3. **Declared results.** An `add_argument` whose option string matches
   `*-exit-code`, `--accepted`, `--*behavioral-surface`, `--*-dependency`, or
   `--full-validation-required`.

**Key**: `(file, qualified function, rule, name)`.

**Permanent allowlist** (the three classes of decision 13):

- Contract creation path: `tasks/creation.py`, the functions of
  `tasks/contract.py` reachable only from `resolve_task_contract`, and the
  `task new` branch of `cli.py`.
- Integrity checks: `templates/**`, `hosts/codex.py`, the digest check of
  T-05, and `shared/context.py` router reads.
- `cardine.legacy.**`, including the importer once T-31 moves there.

**Known violations**: a table keyed by the above and mapped to the T-ID of this
file. The test fails when (a) a violation appears that is in neither list,
(b) a known violation disappears without being deleted from the table (the
list can only shrink), or (c) a T-ID in the table is missing from this
document, so the document and the test cannot drift apart. It reuses the
existing import-graph test for `cardine.legacy`.

**Closure**: each removal row (SS5, SS6, SS7, N1 to N3, 072′, RE3, RE5, RE6)
deletes its entries from the known-violations table as an acceptance
criterion. The last row to run (RE7) asserts the table is empty and that the
allowlist holds only the three classes.

## Defects found

1. **Literal mismatch.** `src/cardine/tasks/contract.py:152` and
   `src/cardine/tasks/preflight.py:39,76` require the line ``- Execution
   commands: `required via meridian execution` ``, while
   `templates/single/tasks/TASK_BLUEPRINT.md:180` and the generated block say
   `required via cardine execution`. A record copied from the template fails
   `EXECUTION_CONTRACT_UNRESOLVED`. Not fixed here (no code changes).
2. **Fabricated declaration.** `record_task_evidence` writes
   `"interaction_assessment_complete": True` unconditionally
   (`integration/evidence.py:314`), and `advance` passes empty dependency and
   surface lists (`closure.py:152-156`). The declared integration surface is
   therefore not real input on the `advance` path.

## Examined and excluded

These reads were examined and are not entries, so that an exclusion is
visibly different from a miss.

| Read | Why it is not an entry |
|------|-----------------------|
| `.cardine/tasks/*.json`, `.cardine/execution-evidence.json`, `.cardine/project.json`, `schemas/*.json`, `capabilities/stop-codes-v1.json`, journal and lease JSON | Task state, project configuration, and Cardine-written files: source 1 or 3 of decision 13. |
| `tasks/recording.py::record_validation:21-35`, `run_validation:38-57` outcome | The runner executes the command and records its exit status: a fact from a command Cardine executed. (Its command text comes from T-15.) |
| Existence of a handoff file (`transitions.py:96`, `execution.py:224`, `closure_status.py:54`) | A file or Git object fact, not its text. |
| `review/verdict.py::record_review_verdict:112` | Reads the review file only to append the next attempt; no decision depends on its text. |
| `shared/flow.py::_flow_read_journal:55-80`, `scripts/dev.py` | The journal is a JSON file Cardine writes. |
| `shared/authority.py::adr_entries`, `ADR_STATUS_LINE:46`, `adr_list` | ADR log status filters a listing; the ADR log is not a record, handoff, report, queue, or plan, and no gate depends on it. |
| `console/launch.py:34,43`, `console/state.py:21`, `hosts/*`, `release/*` | Host and user configuration, framework version; not task text. |
| `console/render.py:312,324`, `shared/errors.py`, `stops/render.py` | Presentation of Cardine's own output. |
| `scripts/console_workflow.py`, `scripts/cardine_cli.py`, `scripts/align_queue.py`, `scripts/check_repository.py`, `scripts/run_agent_evals.py`, `scripts/release.py` | Not imported by product code (S6), so outside this scope. They are adapters or maintenance tools. |

## To repeat the inventory

Run S1 to S7 above on the commit you take, read every hit in context, and
compare with the IDs here. A hit that fits no ID is a new entry; an ID whose
line no longer matches is removed from the guard's table (G1) when its row
lands.
