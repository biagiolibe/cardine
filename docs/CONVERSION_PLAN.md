# Conversion plan: Meridian to Cardine (work item 10)

Authority: `docs/ADR_CARDINE_1_0.md`, decision 10 and work item 10. This plan
changes no code. It was written by task 141 from the files on `main` at commit
`4e3773d`, under the installed Meridian 1.4.1. Counts below come from those
files; they supersede the older tables of `docs/RENAME_PLAN.md`.

The coordinator generates one task record per row of section 9 and applies the
outcome of section 8 to `PROJECT_PLAN.md`. Section 10 records the developer's
decisions of 2026-11-03, and rows C3f, C4a, C4b, and C5e follow from them.

## 1. What was verified, and how

Disposable projects lived outside the repository, with a disposable `HOME`
(`cardine init`, `task new`, `worktree prepare`, `execution start`, `run`,
`review`, `cancel`, `abort`). Nothing touched the real home directory.

| Id | Observation | Kind |
| --- | --- | --- |
| O1 | `cardine adopt` does not exist. `commands/cardine-adopt.md` says conversion "returns with work item 10". | Ran and read |
| O2 | For a queued task with no worktree, three consecutive `cardine run` calls returned `step: contract`, `action: none`, and the same `next` command. No worktree and no state change followed. After `worktree prepare` by hand, `run` reached `step: implementation` and returned an implementer work request; it launched nothing and did not deliver. Validation, candidate, and landing were not exercised. | Ran |
| O3 | `cardine review <ID>` is routed to `run_preview_cli` (`cli.py` main) and printed the same envelope as `run`. The `review` step of `resolve_run` names `cardine review <ID> --project <root>` as its next command, so that command loops back into `run`. | Ran and read |
| O4 | `host_adapter()` in `lifecycle/control.py:19` always returns `None`, and `authorize()` then refuses with `COMMAND_REFUSED: host role boundary unavailable`. `cardine cancel` printed that refusal. The reviewer verdict and the `--owner` verdict reach the same `authorize()`; the owner path stopped earlier at `TASK_STATE_INVALID` (task not `in_review`), so its refusal is read from code, not run. `cardine abort` stopped earlier still (`abort requires an issued owned integration lease`), so its host refusal is also read, not run. | Ran (cancel) and read |
| O5 | `concrete_host_adapter` (`lifecycle/engine.py:204`) has no caller outside `tests/test_host_transports.py`. | Read (`grep`) |
| O6 | A Lean task created without `Expected code surface` stopped `run` with `BLOCKED SCOPE_CHANGE_REQUIRED` (`lifecycle/scope.py:69`). After the surface was frozen and the worktree rebuilt, `run` continued: a stop followed by a resume works. | Ran |
| O7 | `task new` needs `Out of scope` and named validation entries (``- `id`: `command` ``). `execution start` then demanded `- Profile revision`, which only `execution reconcile --apply` writes into the record. In one clean attempt (fresh project, complete record, `task new`, commit, `worktree prepare`, `reconcile --apply`, commit, `execution start` succeeded), the next `cardine run` stopped with `COMMAND_REFUSED: changed or missing receipt artifact: tasks/002.md`. Whether the intended sequence includes `task contract update` was not tried. The cause is unclassified. | Ran once; unclassified |
| O8 | `cardine init` output still contains `.codex/rules/meridian.rules` and a `.cardine/baselines/1.4.0/` directory. | Ran |
| O9 | `docs/ARCHITECTURE_DECISIONS.md` does not exist in this repository. Its ADRs are six standalone `docs/ADR_*.md` files with headings such as `# ADR: Stops and Denials`. `cardine adr` and `find_adr_log` read one log file whose headings start with `ADR-<n>`. | Read |

Not reproduced: a complete no-review task from queued to landed, any required
review, a spike. Row C3c builds that proof.

## 2. Adopt target

### Command surface

```text
cardine adopt --project <path> --check
cardine adopt --project <path> --rehearse [--validation <json>] [--ci <json>]
cardine adopt --project <path> --apply    [--validation <json>] [--ci <json>]
```

The output is one JSON envelope with the same exit codes as `run` (0, 2 for a
guardrail, 64 for a bad invocation). The three modes:

- `--check` is read-only. It detects the case, prints the plan: ordered
  operations, each with a path and digest; diagnostics; and every input still
  missing. It creates nothing, as `init --check` does.
- `--rehearse` implements "copies first". It clones the project
  (`git clone --no-hardlinks`) into a scratch directory under the Cardine
  worktree root, applies the plan there, and verifies the copy. It writes a
  rehearsal receipt bound to the source `HEAD`, the tree digest, and the plan
  digest. The original is never written. A rerun deletes and rebuilds the copy.
- `--apply` refuses unless a passing rehearsal receipt matches the current
  `HEAD`, tree, and plan digests; otherwise it rehearses first. It requires a
  clean tree, applies the plan to the original through the same receipt-covered
  writer as `apply_init`, and never commits, pushes, or touches `HOME`.

Verification of the copy: `cardine audit`; every converted record passes
contract parsing and `task new`; every converted task is startable without a
hand `reconcile` (O7); the count of converted tasks equals the count of open
queue rows; `cardine status` lists them; the project's own baseline commands
pass when the caller supplied them.

### Case A: a project without Cardine and without Meridian

Equivalent to `cardine init` with detected inputs. Nothing is converted. The
caller supplies name, slug, preset, language, identity mode, and validation
(the `init` flags). `adopt --check` prints the missing ones.

### Case B: a Meridian project (`.meridian/manifest.json` present)

| Source | Result |
| --- | --- |
| Open queue rows (`[ ]`) and their records | Rewritten as Cardine records and created through the `task new` machinery (state in `.cardine/tasks/<id>.json`). |
| Dependency on a closed task | Dropped from the converted record and listed in the conversion report; Cardine ignores closed tasks, so it cannot read their state. A dependency on another open task is kept. |
| `Relevant Files` | Becomes `Expected code surface` only when every entry is a repository-relative path accepted by `normalize_surface`. Otherwise the task gets a diagnostic and the developer edits the copy. Needed because of O6 and K5. |
| Validation entries | Rewritten to ``- `id`: `command` ``. A command that starts with `meridian ` is not translated; it is a diagnostic. |
| `.meridian/candidate-validation.json` | `validation.candidate` of `.cardine/project.json`. Baseline commands are prose in Meridian and have no source; the caller supplies `--validation`, or the check reports the baseline as missing. |
| Task identity | `.meridian/task-identity.json` when present, otherwise `opaque`. Written as `.cardine/task-identity.json` and the `taskIdentity` key. |
| Default assurances | `taskDefaults` of the Meridian project declaration when present; otherwise the preset's defaults. This repository declares none. |
| CI | `ci: none`, unless `--ci` supplies provider and checks (DD4). Meridian declares no CI. |
| `.meridian/flow-targets.json` | Copied to `.cardine/flow-targets.json` after schema validation (`shared/layout.py` names it). |
| ADR log | Converted only if a log file exists: headings normalized to `ADR-<n>`. Standalone ADR files are left in place and reported (DD5). |
| Managed copies of the installation | Replaced by the single template set. Text outside `MERIDIAN:BEGIN/END` blocks is kept; the router preamble is regenerated; a non-placeholder `## Commands` block is carried over. `docs/CONTEXT_BUDGET_POLICY.md` becomes `docs/CONTEXT_READING_POLICY.md`. |
| `tasks/QUEUE.md`, `PROJECT_PLAN.md` | Queue regenerated from task states; any non-open row is appended verbatim to `tasks/QUEUE_ARCHIVE.md`. |
| Shared-source files (`hooks/*`) | Not converted. They belong to the Meridian plugin source, not to an adopter. The report lists them; this repository removes them in row C7b. `.codex/hooks.json` is a managed copy of both tools and is replaced by the Cardine template. |
| `.meridian/` itself | Removed (DD3). History stays in Git. |

Archive that Cardine ignores: `tasks/done/`, `tasks/handoffs/`, review records,
`tasks/QUEUE_ARCHIVE.md`.

Refusals (guardrails, each needing a registry entry in
`capabilities/stop-codes-v1.json`, added by row C2c): dirty tree; any `[/]` row;
a registered `task-*` worktree; an active integration lease; a record the
translator cannot make complete. A Governed project is flagged: its tasks
default to required review, which cannot be recorded before row C4a (section 7).

## 3. Legacy readers

Today `cardine.legacy` holds `meridian_installation.py` (manifest, state, and
marker readers, `load_meridian_snapshot`), `meridian_locations.py`,
`snapshot.py`, and `console_workflow.py` (the prose parsers). The rule in
`docs/RENAME_PLAN.md` (group 5, "Dispatch") says no module of `src/cardine/`,
`scripts/`, or `hooks/` imports `cardine.legacy`; the test is
`test_import_graph_has_no_product_consumer_of_legacy`
(`tests/test_legacy_meridian_installation.py:327`).

- **New rule (row C1a).** Only `cardine.adopt` and tests may import
  `cardine.legacy`. The converter is a product command, so the old rule cannot
  hold; the replacement keeps the isolation to one package.
- **Importer move (rows C1b, C1c).** `tasks/importer.py` moves to
  `legacy/importer.py`; `_queue_task_rows` moves from
  `integration/projections.py` to `legacy/queue_rows.py`; the re-export in
  `scripts/cardine_cli.py` goes; `cardine task state import` leaves the product
  parser. `legacy/snapshot.py:53` imports `tasks.importer` today; that reverse
  edge disappears. `ALLOWED` in `tests/test_product_prose_readers.py` becomes
  empty, and entries T-27 and T-31 of `docs/TEXT_GATE_INVENTORY.md` leave the
  product (legacy is exempt).
- **Converter use.** `adopt` calls the legacy readers (queue rows, record
  sections, manifest, marker blocks) and nothing else in the product reads
  Meridian prose.
- **`load_meridian_snapshot`.** Its only callers are tests (two modules). It
  existed to give the coordinator a read-only snapshot of this repository while
  Meridian ran it. After the switch it has no purpose; row C7f deletes it with
  `legacy/snapshot.py`. That also removes the duplicated helpers `_worktrees`,
  `_primary_checkout`, `_read_text`, `_load_snapshot`, which exist only in
  `legacy/snapshot.py` and `console/snapshot.py`.
- **What stays.** The importer, the prose parsers of `console_workflow.py`, and
  the installation readers stay while `adopt` exists (DD2; K2 is resolved by the
  ADR amendment of 2026-11-03).

## 4. Inventory of this repository (at `4e3773d`)

916 tracked files; 169 have `meridian` in their path.

### `.meridian/` (154 tracked files)

| Part | Files | Disposition |
| --- | --- | --- |
| `manifest.json` | 1 | Removed (DD3). `.cardine/manifest.json` replaces it. |
| `baselines/1.4.0/` | 9 | Removed (DD3). |
| `probes/meridian-self-hosting/` | 3 | Removed (DD3); `scripts/check_repository.py:77-79` requires them today (C5a). |
| `candidate-validation.json` | 1 | Converted to `validation.candidate`. |
| `flow-targets.json` | 1 | Converted (copied). |
| `tasks/<id>.json` | 139 | Closed-task state; ignored by Cardine; removed (DD3). |

### Paths the installation owns (13)

The 10 `managedFiles` digests plus 3 shared-source hooks. `WORKTREE_LIFECYCLE.md`
is in `managedFiles` but in no capability `managedSurface`.

| Path | Disposition |
| --- | --- |
| `CLAUDE.md`, `AGENTS.md`, `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md` | Converted by `adopt` (template replaces the managed block; unmarked text kept). |
| `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md` | Converted (template copies). |
| `docs/CONTEXT_BUDGET_POLICY.md` | Converted to `docs/CONTEXT_READING_POLICY.md`. |
| `.codex/rules/meridian.rules` | Replaced by the rules file the template set installs (O8: still Meridian-named; row C2d checks the name). |
| `hooks/hooks.json`, `hooks/queue-briefing.sh`, `hooks/read-guard.sh` | Removed (row C7b). Replaced by the user-level `cardine hook` entries of `cardine setup`. |
| `.codex/rules/local.rules` (the `meridian worktree` line) | Removed (row C7c); the project's validation allowances stay in the project's own host configuration. |

### Guards of those paths

| Guard | What it reads | Disposition |
| --- | --- | --- |
| `scripts/check_repository.py:73-79, 405-413, 905-930` | Hook files, three probe files, manifest `managedFiles` digests | Conditional on the installation (C5a), then deleted (C7a). `.cardine/manifest.json` digests replace them. |
| `tests/test_check_repository.py` (lines 849-1087) | Synthetic manifests | Updated with C5a. |
| `tests/test_no_meridian_identifiers.py` (groups 3 and 5, lines 100-170) | Allowlist; fails on an entry matching nothing | Entries conditional on presence (C5b); the guard is restricted to the shipped surfaces and the entries outside them are deleted (C7c, developer decision of 2026-11-07). |
| `tests/test_legacy_meridian_installation.py:222, 278-283`, `tests/test_template_manifest.py:322` | The live checkout's `.meridian/` | Fixture-based (C5c). |
| Tests naming the shell hooks (`test_queue_briefing.py`, `test_read_guard.py`, `test_codex_worktree_hooks.py`, `test_codex_read_guard.py`, others in the `grep` list) | `hooks/*.sh`, `.codex/hooks.json` | Run only while the files exist (C5d); removed with them (C7b). Which of them execute this checkout's copy is confirmed in C5d. |
| `load_meridian_snapshot` | Manifest, queue, records | Deleted (C7f). |
| CI | `validate.yml` runs `cardine --version`, `check_repository.py`, `run_tests.py --parallel`; `release.yml` names no Meridian command | No change. |

Every open task's `Validation` also names `meridian profile doctor` and
`meridian audit`; post-switch records name Cardine commands instead.

## 5. The switch

### Principles

1. The installed Meridian owns `.meridian/` and the 13 paths until the switch.
   No pre-switch row edits them (their own acceptance criteria and
   `meridian audit` forbid it).
2. The switch commit is the unedited output of `cardine adopt --apply`.
   Therefore every guard that names a released path is made conditional on the
   path's presence in pre-switch rows, so that the commit passes CI untouched.
   Dead branches are deleted afterwards under Cardine.
3. The switch cannot be a Meridian task: the commit removes the files
   `meridian task close` and `worktree advance` read. The last task Meridian
   closes is C6a. The first Cardine delivery is C7a.

### Order

| Boundary | Tool | State of `main`, CI, queue |
| --- | --- | --- |
| B0 now | Meridian | Meridian-run. CI green. Queue holds rows `[ ]`. |
| Rows C1a to C6a | Meridian (`Proceed with <ID>`) | Product code and tests only. C6a is the last task Meridian closes. The coordinator writes the records of C7a onward in Meridian format before B1 so that `adopt` converts real open tasks. |
| B1 | none | `main` equals `origin/main`, CI green, no `[/]` row, no `task-*` worktree, no lease. |
| CS | developer | Steps S1 to S6 below. |
| B2 | none | Switch commit on `main`, CI green. No Cardine task has landed. |
| S7 | developer | Machine steps. |
| Rows C7a onward | Cardine (`Proceed with <ID>` routes to `cardine run`) | First delivery C7a. |

### Developer steps (CS)

All steps are the developer's. No row runs `setup --apply` against the real
home directory.

- **S1** Check B1 conditions; `git branch pre-cardine-switch main` and push it.
  No tag is created.
- **S2** Rerun `cardine adopt --rehearse` on the exact `HEAD` (the receipt is
  bound to it).
- **S3** `git switch -c cardine-switch`; `cardine adopt --apply`; review
  `git diff --stat`; run `python3 scripts/check_repository.py` and
  `python3 scripts/run_tests.py --parallel`; commit.
- **S4** `validate.yml` runs only on `pull_request` and on pushes to `main`, so
  pushing the branch alone starts no CI. Open a pull request for CI only (not
  merged through GitHub).
- **S5** After CI is green: `git switch main`,
  `git merge --ff-only cardine-switch`, `git push origin main`.
- **S6** Verify: `cardine status`, `cardine doctor`.
- **S7** Machine, after S6: install Cardine (`pipx install --editable <clone>`
  until PyPI carries a release); `cardine setup --check`, review, then `cardine
  setup --apply`; disable the Meridian plugin for this repository only, by the
  means row C5e proves; restart Codex. The Meridian checkout, its `PATH` lines,
  and the user-level plugin stay, because other projects on this machine run on
  Meridian until their conversion. Their removal is ADR decision 10, after the
  last conversion. Until S7 the plugin hooks still call `meridian` in this
  repository; until then work stays with the developer.

### Interrupted or failed conversion

`--apply` is receipt-covered: killing it leaves a partial working tree on the
`cardine-switch` branch only. Rerun converges to the same tree
(rule 4 of decision 14), or the developer deletes the branch. `main` never holds
a partial conversion, because the merge follows a complete, validated, CI-green
branch.

### Return to Meridian

Valid until the first Cardine delivery is pushed to `main`. If C7a fails
before landing: `git revert --no-edit <switch commit>` (history stays intact; no
reset), then re-enable the plugin for this repository. The revert
restores `.meridian/`, the managed copies, and the original open records,
because the switch is one commit. After C7a lands, the repository moves forward
with Cardine tasks; a return would need the developer to revert the delivery
too.

### Constraint from section 7

Reviewer sessions still cannot record a verdict, and row C4a gives the developer
the channel. The first Cardine task needs no review, so that the first delivery
exercises the shortest path.

## 6. Proof before touching the originals

C6a runs `adopt --rehearse` on a clone of this repository (139 closed task
states, the open rows of that moment) and attaches the receipt, the verifier
output, and the before/after tree digest of the original to its handoff. S2
repeats it at the switch `HEAD`. Every test of section 9 runs against disposable
projects and disposable `HOME` directories.

## 7. Review without role launches

What the code does today (O2 to O5):

- `cardine run` resolves the step and, for the earliest steps, returns it without
  performing it (O2). `docs/RUN_COMMANDS.md` says `run` "performs" the step;
  the `run` help in `cli.py` says "preview ... (read-only)"; the behavior matches
  the help for the contract, worktree, and implementation steps.
- For a task with `review: required`, once validation passes, `run` names
  `cardine review <ID>` as next, which is the same preview (O3). No code
  launches a reviewer: `concrete_host_adapter` has no caller (O5); role launches
  are `unsupported (D3)` on both hosts (`docs/HOST_CAPABILITY_CONTRACT.md`).
- `cardine review verdict` (also with `--owner`), `cancel`, and `abort` all call
  `authorize()`, which refuses without an adapter (O4).

Field-trial cases of decision 10, step 5:

| Case | Path that can deliver it | State |
| --- | --- | --- |
| Required review, one round of requested changes | None today. Developer channel (DD1). | C4a, C4b |
| No review | `run` skips the review step (`resolve_run`); proof absent (O2) | C3b, C3c |
| Spike | `Class: SPIKE` and `task outcome` exist; not exercised | C3e |
| `Authority` citing an ADR, declared code surface | Contract fields and `enforce_scope` exist; `adr show` needs a log (O9) | C3e, DD5 |
| Stop, then resume with `cardine run` | Worked in O6 | C3e proves it with an interrupted effect |

## 8. Deferred items

### Rows of `PROJECT_PLAN.md` targeting work item 10

A deferred row assigned to a lettered family (`C8`) is delivered by every row of
the family and closes with the last one.

| Deferred row | Assigned to |
| --- | --- |
| Rename the managed copy of `CONTEXT_BUDGET_POLICY.md` | C2d (the converter renames it; executed at CS) |
| Call product functions in-process; 38 tests start the CLI as a subprocess | Family C8, after 0.9 |
| Import product modules directly in 64 adapter modules; merge duplicate helpers | Family C8, after 0.9 (helpers: C7f, verified in C8j) |
| Move `task state import` and `_queue_task_rows` | C1b, C1c |

Current counts differ from the quoted ones. Adapter importers: 66 modules
(`grep -lE "^\s*(import cardine_cli|from cardine_cli )|cardine_cli_support" tests/*.py`).
Subprocess tests that start the CLI: 40 modules (`grep -lE "subprocess\.(run|Popen|check_output|call)" tests/*.py`
filtered by `grep -lE "bin/cardine|cardine_cli\.py|CARDINE_BIN|-m\", \"cardine|\"cardine\""`).
The union is 83 files. 83 files cannot fit one row of at most 10 files; hence
the family and appendix A.

### Rows to reconcile

| Row | Status | Task and proof |
| --- | --- | --- |
| Runnable recovery for `EVIDENCE_INCOMPLETE` | Open | Registry marks it `recoverable` with resume `cardine run`; the test `test_closure_status_text_reports_incomplete_evidence_through_the_registry` checks the text only. Target C3c. |
| Split mixed guardrail codes | Resolved | Tasks 089 to 092 (RE2a to RE2d). The registry has 47 codes, 21 guardrails (ADR: 51 and 27); `tests/test_run_end_to_end.py` `RegistryAuditTest` requires `blocked` exactly for guardrails. Each code's cause was not re-derived. |
| Budget lines in the briefing | Resolved for the product | Task 118; `hosts/briefing.py` has none. `hooks/queue-briefing.sh:245-251` keeps them until C7b. |
| Apostrophe in titles | Resolved for the product | Task 118; `tests/test_host_briefing.py` uses titles with apostrophes and quotes. The shell hook keeps the defect until C7b. |
| Add `cardine init` | Resolved | Tasks 122 and 123; `commands/cardine-init.md` calls `cardine init`; `tests/test_init.py`. |
| Repository scripts out of allowlists | Partly open | Task 132; `grep` finds no `check_repository` in `src/cardine/hosts/`. `integration/evidence.py:83` still proposes this repository's script as a product default. Target C7e. |
| Defer heavy imports | Resolved (imports only) | Task 121; `-X importtime` shows no `http.client`, `ssl`, or `email` at startup. Startup measured 0.15 s against 0.04 s for bare Python; no claim is made about that. |
| Accept route | Resolved | Task 125; `skills/cardine-delivery/SKILL.md:30` routes to `docs/LIFECYCLE_ORCHESTRATION.md`, which `templates/single/docs/` installs. |

## 9. Rows

Hours are estimates; rows are sized by files. Each row lists its files, at most
10, and one or two areas. "Under" is the first word of the scope.

| Row / hours | Scope | Files | Tests | Interruption boundaries | Depends on |
| --- | --- | --- | --- | --- | --- |
| C1a / 2h | Meridian: replace the no-import rule by "only `cardine.adopt` and tests import `cardine.legacy`"; create the empty package. | `tests/test_legacy_meridian_installation.py`, `src/cardine/adopt/__init__.py`, `tests/test_module_inventory.py` | Import-graph test; negative fixture: another product module importing legacy fails. | None (no effect). | 141 |
| C1b / 3h | Meridian: move the importer and `_queue_task_rows` under legacy; drop `task state import` from the parser. | `src/cardine/legacy/importer.py` (moved), `src/cardine/legacy/queue_rows.py`, `src/cardine/integration/projections.py`, `src/cardine/cli.py`, `scripts/cardine_cli.py`, `src/cardine/legacy/snapshot.py`, `tests/test_queue_archival_state.py`, `tests/test_single_workflow_contract.py`, `tests/test_task_status_gates.py`, `docs/RUN_COMMANDS.md` | The three suites pass from the new import path; the parser lists no `task state`. | None (code move). | C1a |
| C1c / 1h | Meridian: ratchets to zero. | `tests/test_product_prose_readers.py`, `tests/test_text_gates.py`, `docs/TEXT_GATE_INVENTORY.md` | `ALLOWED` is empty and the static search has no hit; no stale T-27 or T-31 key. | None. | C1b |
| C2a / 3h | Meridian: read model `LegacyProject` (open rows, closed ids, ADR log, configuration). | `src/cardine/legacy/conversion_reader.py`, `tests/conversion_fixture.py`, `tests/test_conversion_reader.py` | Synthetic Lean and Governed projects: `[ ]`, `[x]`, `[/]`, duplicate ids, no queue, ADR log with and without ids. | None (read-only; the reader opens only declared paths). | C1c |
| C2b / 3h | Meridian: record translator (section 2), diagnostics instead of invented fields. | `src/cardine/adopt/records.py`, `tests/test_adopt_records.py` | Output passes contract parsing, `task new`, and a start without hand `reconcile` in a disposable project. | None (pure). | C2a, C3a |
| C2c / 3h | Meridian: `plan_adopt` (pure), `project.json` mapping, refusals, stop-registry entries. | `src/cardine/adopt/plan.py`, `src/cardine/adopt/config.py`, `capabilities/stop-codes-v1.json`, `tests/test_adopt_plan.py`, `tests/test_stop_registry.py` | Same bytes on repeat; both cases; refusals (dirty, `[/]`, worktree, lease). | `before_adopt_plan` (nothing written). | C2b |
| C2d / 3h | Meridian: `apply_adopt` on the `apply_init` writer; release of managed copies and removal of `.meridian/` (DD3); rename of the budget policy. | `src/cardine/adopt/apply.py`, `src/cardine/adopt/release.py`, `tests/test_adopt_apply.py`, `tests/test_adopt_interruption.py` | Idempotent rerun; interrupt at every boundary then rerun gives the same tree; unmarked text kept. | `before_adopt_declare`, `before_adopt_write:<path>` (each file), `before_adopt_state:<id>` (each task), `before_adopt_release:<path>` (each removal), `before_adopt_result`, `after_adopt_result`. | C2c |
| C2e / 3h | Meridian: rehearsal on a clone, verifier, receipt; `--apply` requires it. | `src/cardine/adopt/rehearsal.py`, `src/cardine/adopt/verify.py`, `tests/test_adopt_rehearsal.py` | Original tree digest unchanged; failing rehearsal blocks apply; scratch under a disposable home. | `before_rehearsal_clone`, `after_rehearsal_clone`, `before_rehearsal_verify`, `before_rehearsal_receipt`; rerun rebuilds the copy. | C2d |
| C2f / 2h | Meridian: `cardine adopt` parser, exit codes, docs, slash command. | `src/cardine/cli.py`, `commands/cardine-adopt.md`, `docs/PUBLIC_SURFACE.md`, `docs/ADOPT_COMMANDS.md`, `tests/test_adopt_cli.py` | Parser, envelope, exit codes 0, 2, 64; `--check` writes nothing. | None beyond C2d and C2e. | C2e |
| C3a / 2h | Meridian: classify O7 (record, receipt, start sequence) and fix it. | `tests/test_execution_start_fresh_task.py`, plus files the failing test names (at most 9) | A fresh task created by `task new` starts and `run` continues without a hand edit. | Per file the fix touches. | 141 |
| C3b / 3h | Meridian: `run` performs the `contract` and `worktree` steps (prepare, `execution start`, resume on rerun). | `src/cardine/lifecycle/engine.py`, `tests/test_run_worktree_step.py`, plus at most 7 files | From a queued task, `run` creates the worktree once; a rerun after a kill converges. | After prepare; after execution start. | C3a |
| C3c / 3h | Meridian: disposable end-to-end run of a no-review task to landing with a local bare remote; the test plays the implementer. Fixes what it exposes. | `tests/test_run_delivery_disposable.py`, `tests/run_delivery_support.py`, plus at most 8 files | Queued to landed and cleaned; `EVIDENCE_INCOMPLETE` recovered through `run`. | Commit, state write, merge, push, cleanup. | C3b |
| C3d / 1h | Meridian: align the `run` help with the behavior. | `src/cardine/cli.py`, `docs/RUN_COMMANDS.md`, `tests/test_cli_help.py` | Help states what `run` performs. | None. | C3b |
| C3e / 3h | Meridian: disposable runs of the spike, Authority with declared surface, and stop-then-resume cases. | `tests/test_run_field_cases.py`, plus at most 4 files | Each case reaches its documented outcome or is recorded as a finding. | Kill and rerun at the resume case. | C3c |
| C5a / 3h | Meridian: installation checks of `check_repository.py` run only when `.meridian/manifest.json` exists; add the `.cardine/manifest.json` equivalent. | `scripts/check_repository.py`, `tests/test_check_repository.py` | Both states, on synthetic roots. | None. | C1c |
| C5b / 2h | Meridian: group 3 and 5 allowance entries bind only while the path exists. | `tests/test_no_meridian_identifiers.py` | Present and absent states; unrelated stale entries still fail. | None. | C5a |
| C5c / 2h | Meridian: tests that read the live checkout's `.meridian/` use fixtures. | `tests/test_legacy_meridian_installation.py`, `tests/test_template_manifest.py`, `tests/test_status_legacy_boundary.py` | Same assertions on a synthetic installation. | None. | C1a |
| C5d / 2h | Meridian: tests that execute this checkout's shell hooks run only while the files exist. | `tests/test_queue_briefing.py`, `tests/test_read_guard.py`, `tests/test_codex_worktree_hooks.py`, `tests/test_codex_read_guard.py` | Present and absent states. | None. | C1a |
| C3f / 3h | Meridian: agent-driven delivery in a disposable project. The agent executing this task follows only what `cardine run` prints, from queued to landed, with a local bare remote. Every point where it needed knowledge the output did not give is a finding. | `tasks/handoffs/<id>.md` | No test file. The handoff records the sequence of `run` outputs, the landed commit, and the findings. | None in this repository; the disposable run is repeated from scratch if interrupted. | C3c, C3d, C3e, C4b |
| C4a / 3h | Meridian: developer channel in `authorize()` for the owner verdict, `cancel`, and `abort`: interactive terminal on stdin and stdout, explicit confirmation of task and commit, refused otherwise. Reviewer-session verdicts stay refused. | `src/cardine/lifecycle/control.py`, `src/cardine/lifecycle/control_abort.py`, `src/cardine/review/verdict.py`, `src/cardine/cli.py`, `docs/RUN_COMMANDS.md`, `docs/HOST_CAPABILITY_CONTRACT.md`, `tests/test_developer_channel.py`, `tests/test_review_verdict.py` | Each action under a pseudo-terminal: accepted, wrong confirmation, no terminal, reviewer session refused. Host rule probes still deny the three commands to agents. | Before and after the confirmation; the existing receipts of verdict, cancel, and abort stay the durable effects, and a rerun converges. | C3b |
| C4b / 3h | Meridian: the `review` step of `run` stops looping into the preview (O3): it returns the reviewer work request and the developer's verdict command. A disposable required-review task reaches landing through one round of requested changes. | `src/cardine/lifecycle/engine.py`, `src/cardine/cli.py`, `docs/RUN_COMMANDS.md`, `tests/test_run_required_review.py`, `tests/run_delivery_support.py`, plus at most 3 files | Queued to landed with `CHANGES_REQUESTED`, a fix, then `APPROVE`; a verdict on a stale commit is refused. | Each verdict; rerun after a kill before and after each one. | C3c, C4a |
| C5e / 3h | Meridian: coexistence on one machine. `cardine setup` no longer removes the known Meridian block from the Codex user rules while Meridian stays installed; it reports it. In a disposable home with both tools, a converted project and a Meridian project each get only their own tool's hooks and briefing; the plugin's local-scope disable is proved or replaced. | `src/cardine/hosts/codex.py`, `src/cardine/hosts/setup.py`, `tests/test_host_coexistence.py`, `tests/test_codex_user_rules.py`, `docs/HOST_CAPABILITY_CONTRACT.md` | Both homes and both projects; Meridian's rules byte-identical after `setup --apply`; a Meridian hook defect in a converted project is recorded for S7, not fixed in Meridian. | The existing setup write boundaries; a rerun converges. | C1a |
| C6a / 2h | Meridian: rehearsal on a clone of this repository; evidence in the handoff. The last task Meridian closes. | `tasks/handoffs/<id>.md` | Receipt, verifier output, unchanged original digest. | None. | C2f, C3f, C4b, C5a, C5b, C5c, C5d, C5e |
| CS / developer | Neither tool: the switch, steps S1 to S7. | None in a task | See section 5. | Section 5. | C6a |
| C7a / 2h | Cardine: first delivery. Delete the installation-conditional branches that the switch made unreachable. | `scripts/check_repository.py`, `tests/test_check_repository.py` | Full suite and repository check. | Cardine's own (rule 4). | CS |
| C7b / 2h | Cardine: remove the shell hooks and their tests. | `hooks/hooks.json`, `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, `tests/test_queue_briefing.py`, `tests/test_read_guard.py`, `tests/test_codex_worktree_hooks.py`, `tests/test_codex_read_guard.py` | Suite passes without them. | Cardine's own. | C7a |
| C7c / 2h | Cardine: restrict the identifier guard to the shipped surfaces (`src/`, `bin/`, `capabilities/`, `schemas/`, `skills/`, `commands/`, `.claude-plugin/`, `pyproject.toml`) and delete every allowance outside them, with groups 3 to 6 and the tags; remove the `meridian worktree` line of `local.rules`. | `tests/test_no_meridian_identifiers.py`, `.codex/rules/local.rules` | The guard passes; a seeded occurrence in a shipped file fails, one under `docs/` or `tasks/` passes. | Cardine's own. | C7b |
| C7e / 2h | Cardine: stop `integration/evidence.py` proposing this repository's script. | `src/cardine/integration/evidence.py`, `tests/test_ci_evidence.py` | Proposal is empty without that script, unchanged with it. | Cardine's own. | C7a |
| C7f / 3h | Cardine: delete `legacy/snapshot.py`, `load_meridian_snapshot`, and their tests; the rest of legacy stays (DD2). | `src/cardine/legacy/snapshot.py`, `src/cardine/legacy/meridian_installation.py`, `tests/test_status_legacy_boundary.py`, `tests/test_legacy_meridian_installation.py` | Suite passes; helper pairs defined once. | Cardine's own. | C7c |
| C8a to C8i / 3h each | Cardine, after 0.9: tests call product functions in-process and import product modules directly (appendix A). Support modules last. | The batch of appendix A (10 files each; C8i has 3). | The batch passes unchanged in meaning. | Cardine's own. | C7f |
| C8j / 1h | Cardine, after 0.9: confirm each helper is defined once; delete `scripts/cardine_cli.py` if no importer remains. | `scripts/cardine_cli.py`, `tests/test_cardine_cli_entry.py` | `grep` finds no importer. | Cardine's own. | C8i |

Row identifiers keep their family when a row is added, so C4 and C3f appear out
of order; dependencies, not the table's order, fix the sequence.

## 10. Developer decisions

Decided by the developer on 2026-11-03. The ADR records the amendments.

**DD1: the review path while role launches stay unsupported.** Option (a): a
developer channel, from an interactive terminal, with an explicit confirmation of
the task and the commit. It covers the owner verdict, `cancel`, and `abort`, all
of which O4 shows refused. A reviewer session can still review, but only the
developer records the verdict. This is presence, not authenticity (ADR decision
14, rule 2). Rows C4a and C4b.

**DD2: `cardine.legacy` and the private projects.** Converting the private
projects belongs to item 13, as part of the field trial. The readers and `adopt`
stay, because decision 7 has `adopt` handle Meridian projects. Row C7f deletes
only the snapshot path.

**DD3: `.meridian/` at the switch.** Removed. History stays in Git; closed records
stay in `tasks/done/`. `adopt` then no longer detects a Meridian project, and
group 3 allowances disappear with row C7c.

**DD4: CI declaration.** `ci: none`, consistent with task 027 and with decision
11, where CI before landing is an option. `validate.yml` keeps running on `main`.
S4 still uses a pull request to obtain CI on the switch commit.

**DD5: ADR log.** The six standalone files stay in place and are cited by path in
`Authority`. No renumbering. The field trial proves `adr show` on a project that
has a log.

**Family C8.** Outside the path to 0.9, because it unblocks neither 0.9 nor 1.0.
Its rows stay in this plan and are written as records after 0.9.

## 11. Cross-check against the other plans

Conflicts are named, not resolved.

- **K1** `docs/RENAME_PLAN.md` group 5: no product import of `cardine.legacy`
  and the module "removed by item 10". The converter is a product command;
  C1a replaces the rule.
- **K2** ADR decision 14 (legacy deleted after item 10) against decision 10,
  step 5 (conversion of Contoso and Fabrikam on 0.9). Resolved: DD2 and the ADR
  amendment of 2026-11-03.
- **K3** `docs/RUN_COMMANDS.md` ("performs") against the `run` help and O2.
  `docs/RUN_ENGINE_PLAN.md` row RE1a is a pure preview; no later row is shown to
  add the worktree and start steps. C3b, C3d.
- **K4** `docs/HOST_INTEGRATION_PLAN.md` H5c (task 135, transports "wired to
  issued roles") against O4, O5, and D3 ("no guarded transport adapter is
  built"). Consistent only if "wired" means injectable in tests.
- **K5** `docs/PROJECT_DECLARATION.md` (Lean: `expectedCodeSurfaceRequired`
  false) against `enforce_scope`, which rejects an empty surface for all
  unattended work (O6).
- **K6** `docs/RENAME_PLAN.md` item 9 handling of the Codex rules name against
  O8 (`init` still writes `.codex/rules/meridian.rules`). C2d decides the name
  only after the maintainer confirms the intended one.
- **K8** The first version of step S7 removed Meridian from the whole machine,
  against ADR decision 10 ("Projects stay on Meridian 1.4.x until their
  conversion"). Resolved: S7 and the ADR amendment of 2026-11-03, row C5e.
- **K9** `src/cardine/hosts/codex.py` plans to remove the known Meridian block
  from the Codex user rules (`legacy_proposed`, task 129), which would break
  Meridian projects on the same machine. Row C5e.
- **K7** ADR work item 10 says items 11 and 12 run on Cardine; both depend on
  the first Cardine delivery succeeding (section 5, return to Meridian).

## Appendix A: batches of family C8

Snapshot at `4e3773d`, from the union of the two commands of section 8, sorted,
support modules last. The coordinator regenerates it when writing each record,
because C1b and C7 rows change the set.

```text
C8a: installation_fixture.py, test_authority_excerpt.py, test_cardine_adoption_audit.py, test_cardine_cli_entry.py, test_cardine_cli.py, test_cardine_manifest_protocol.py, test_cardine_migration_retirement.py, test_cardine_upgrade_lifecycle.py, test_cardine_upgrade_merge.py, test_check_repository.py
C8b: test_ci_evidence.py, test_cli_install.py, test_codex_read_guard.py, test_codex_rules.py, test_codex_user_rules.py, test_codex_worktree_hooks.py, test_command_word.py, test_context_size.py, test_dev_commands.py, test_execution_boundaries.py
C8c: test_execution_evidence.py, test_host_briefing.py, test_host_codex_access.py, test_host_codex_repair.py, test_host_distribution.py, test_host_doctor.py, test_host_hooks.py, test_host_permissions.py, test_host_repeatability.py, test_host_worktree_setup.py
C8d: test_human_contract_snapshot.py, test_init.py, test_launcher_task_audit.py, test_lean_walkthrough.py, test_legacy_marker_syntax.py, test_lifecycle_journal_flow.py, test_machine_task_state.py, test_marker_structure_audit.py, test_module_inventory.py, test_no_meridian_identifiers.py
C8e: test_product_prose_readers.py, test_public_surface.py, test_queue_archival_state.py, test_read_guard.py, test_release_self_check.py, test_release.py, test_review_verdict.py, test_run_end_to_end.py, test_run_nonrun_causes.py, test_run_review.py
C8f: test_self_update.py, test_single_workflow_capabilities.py, test_single_workflow_contract.py, test_status_render.py, test_stop_audit.py, test_stop_registry.py, test_synthetic_upgrade.py, test_task_close.py, test_task_creation.py, test_task_identity_project.py
C8g: test_task_integration_state.py, test_task_state_import.py, test_task_state_lookups.py, test_task_status.py, test_template_cookbook_actions.py, test_template_entry_actions.py, test_template_manifest.py, test_template_marker_heading.py, test_template_reference_actions.py, test_template_replacement.py
C8h: test_template_retirement.py, test_template_router.py, test_template_surface_upgrade.py, test_template_word_budget.py, test_update_repeatability.py, test_upgrade_repeatability.py, test_usage_report.py, test_worktree_checkout.py, test_worktree_cleanup.py, test_worktree_lifecycle.py
C8i: cardine_cli_support.py, stop_recovery_support.py, synthetic_upgrade_support.py
```
