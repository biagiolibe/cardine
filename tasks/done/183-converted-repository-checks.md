# Task 183 — Convert this repository so that its own checks pass

> **ID**: `183`
> **Category**: Fix
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Adoption follow-ups, 2026-11-06
> **Origin**: findings of task 164; coordinator prototype of 2026-11-06

## Objective

The rehearsal of task 164 converts this repository, and the converted copy then fails
its audit and its baseline `python3 scripts/check_repository.py`. The coordinator
reproduced every failure on a disposable clone of `main` at `af7a7bf` and fixed them one
after another in a scratch copy of the framework, until `cardine adopt --rehearse`
returned `done`. The audit then reported no FAIL and the same (status, identity) pairs
as the reference project, and every converted task was created and started. This
task makes those fixes in the product, with tests. Each fix below names the
failure it removes.

1. **Unchanged Meridian copies keep Meridian text.** All ten files in
   `.meridian/manifest.json` `managedFiles` match their recorded digest, so every byte
   of them is Meridian's release text. Today `conversion_outputs` in
   `src/cardine/adopt/release.py` appends everything outside `MERIDIAN` markers to the
   Cardine template. As a result the converted copy contains:
   - Meridian's router prose, including `BLOCKED WORKFLOW_UNREADABLE` (AGENTS.md:25,
     PROJECT_WORKFLOW.md:70);
   - `BLOCKED CONTRACT_EXHAUSTED` (docs/EXECUTION_EVIDENCE_PROFILE.md:23);
   - a JSON file concatenated with another (`.codex/hooks.json`).

   The saved baseline is 1.4.0 while the installed text is 1.4.1, so comparing against
   the baseline cannot catch this.
2. **Project files stay the project's.** `README.md`, `.gitignore`, and
   `tasks/TASK_BLUEPRINT.md` exist, carry no Meridian markers, and are not Meridian
   managed files. Today the conversion appends them to the Cardine template.
3. **The manifest lists what was written.** The conversion drops some `plan_init`
   outputs (`docs/ARCHITECTURE_DECISIONS.md`, and the project's own files of point 2).
   The Cardine manifest still lists them in `managedFiles` ("missing managed-copy
   surface").
4. **Queue links resolve.** `render_queue` in `src/cardine/tasks/status_render.py`
   writes each record link relative to the project root (`tasks/164-....md`), but the
   queue lives in `tasks/`, so every link is broken. This affects every Cardine project,
   not only conversions.
5. **The repository check of the Cardine state.** Two defects:
   - In `scripts/check_repository.py`, the `.cardine/manifest.json` entry of
     `INSTALLATION_STATES` requires `hooks/*` and `.cardine/probes/cardine-self-hosting/*`.
     A conversion creates neither, and row C7b deletes the hooks.
   - `managed_digest_diagnostics` compares raw digests without the exemptions of the
     product audit: capability markers, `PROJECT_EDITABLE_MANAGED_PATHS`, and declared
     surfaces. On the same converted copy, `cardine audit` reports no FAIL while the
     check reports 14.

## Acceptance Criteria

- [x] **Unchanged copies.** When a file that a `plan_init` output replaces is a Meridian
  managed file whose bytes match its `managedFiles` digest, the output is the Cardine
  template alone. A `## Commands` block of that file is carried over only when it
  contains no `[` placeholder, as row C2d requires.
- [x] **Edited copies.** When the digest does not match, the carried text is the text
  outside `MERIDIAN` blocks minus every blank-line-separated block that equals a block of
  the Meridian baseline copy of the same file. Before comparing, whitespace runs are
  collapsed, and the baseline's `[Project Name]` matches any text. When no baseline
  copy exists, today's behavior applies. This one rule replaces the AGENTS.md and
  CLAUDE.md preamble special case and also applies to `docs/CONTEXT_BUDGET_POLICY.md`.
- [x] **Project files.** An existing file that is not a Meridian managed file and has no
  `MERIDIAN` marker is left byte-for-byte unchanged: the conversion writes no output
  for it.
- [x] **Manifest.** `managedFiles` of the converted `.cardine/manifest.json` lists only
  paths the conversion writes. A capability `managedSurface` keeps every path it
  declares. A declared surface that the conversion did not write is a refusal with a
  diagnostic, never a silent drop.
- [x] **Queue links.** `render_queue` takes the queue's project-relative path, and each
  record link is relative to that file's directory. Its three callers
  (`status_render.py`, `adopt/apply.py`, `templates/init.py`) pass the path they write.
  A test renders a queue under `tasks/` and resolves every link to an existing record.
- [x] **Repository check, Cardine state.** The `.cardine/manifest.json` state requires
  no records beyond its manifest. For that state, `managed_digest_diagnostics` reports
  only the FAIL results of the product's checks in `src/cardine/templates/audit.py`
  (`audit_managed_copy_digests` and the installation results of
  `audit_declared_capabilities`), so it applies the same exemptions as `cardine audit`.
  The Meridian state keeps its current comparison unchanged.
- [x] **Tests.**
  - `tests/test_adopt_apply.py` covers points 1 to 4 on a synthetic Meridian
    installation whose managed copies match their digests: no `MERIDIAN` text and no
    unregistered stop code in any converted file; an unchanged project file; an edited
    copy that keeps exactly its own block; and a manifest without paths that were not
    written.
  - `tests/test_check_repository.py` covers the Cardine state on a synthetic root: a
    managed copy with appended project prose under a capability marker passes, and a
    drifted markerless copy fails.
- [x] **Rehearsal evidence.** On a disposable clone of the implementation commit, with a
  disposable `HOME`, `TMPDIR`, and `CARDINE_WORKTREE_ROOT`, run `python3 -m cardine.cli
  adopt --project <clone> --rehearse --name Cardine --slug cardine --language Italian
  --validation <file>`, with `PYTHONPATH` set to the worktree's `src`. The validation
  file declares `python3 scripts/check_repository.py` as baseline and candidate `FULL`.
  The command returns outcome `done`, and the handoff records its result line and the
  audit summary. Its `diagnostics` are empty. If it stops on a further defect, fix it
  in the files listed here, rerun, and list it in the handoff. A defect in another file
  is a change of scope.
- [x] Only the files under Relevant Files are edited, together with this
  task's own record and its archive, handoff, and state file. A test file
  outside that list may change only to update an expectation that this change
  made stale, without new behavior, and the handoff lists it. Any other file,
  or new behavior beyond this record, stops the task before editing it and
  names the file.
- [x] Tests that need a home directory create a disposable one themselves. Run the
  validation commands with the inherited environment, as written; never wrap them in a
  temporary home, and a run that inherited the real home is not a stop. No step runs
  `setup --apply` against the real home directory or writes real host configuration.
- [x] The subprocess ceilings of `tests/test_command_context.py` still hold.
- [x] Every source and test file stays below 1,500 lines.
- [x] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1.
- [x] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [x] `.meridian/` is unchanged, except `.meridian/tasks/183.json`, which only
  the installed `meridian task close 183` writes.
- [x] A test expectation that this task makes stale is updated in this task
  without weakening any other assertion. The parallel suite reports the
  same coverage `total` before and after the task, except for new or
  deliberately removed tests, which the handoff lists with their reason.
- [x] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [x] Every command under Validation passes.


## Relevant Files

| File | Role |
|------|------|
| `src/cardine/adopt/release.py`, `src/cardine/tasks/status_render.py`, `src/cardine/adopt/apply.py`, `src/cardine/templates/init.py` | Conversion outputs and the queue view. |
| `scripts/check_repository.py` | The Cardine installation state of the repository check. |
| `tests/test_adopt_apply.py`, `tests/test_check_repository.py` | The tests. |
| `tests/test_adopt_interruption.py`, `tests/test_no_meridian_identifiers.py` | Fixture and identifier allowance added by coordinator scope amendment. |

## Technical Context

- Authority: task 164's handoffs and the developer's approval of 2026-11-06. Rows C2d
  and C5a of `docs/CONVERSION_PLAN.md` introduced the two behaviors that this task
  corrects.
- The coordinator's prototype changed only those files, so the record names no other.
  Point 5 is a repository script. Under rule 2 of section 5 of the plan, the switch
  commit must pass this repository's check untouched, which is why the fix belongs
  before the switch.
- The rehearsal's verifier runs `cardine audit` and expects exit 0 or 1. The seven
  UNVERIFIED results of a bootstrapped profile are the intended state, as in task 174.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.
- During development, run only what the change touches: `python3
  scripts/run_tests.py --parallel --module <name>` for a module, class, or
  test, and `python3 scripts/run_tests.py --parallel --last-failed` after a
  failed full run. Do not run `python3 -m unittest` directly, and run the full
  suite once, as the counted clean-clone validation.
- Other tasks share this machine. Stop only your own processes, by process ID;
  never `pkill` test runs by pattern.

## Out of scope

The rehearsal record of task 164, the switch steps, and rows C7a onward. Renaming the
Cardine template `.codex/rules/meridian.rules`. Other rows of the queue.

## Dependencies

- **Depends on**: none
- **Blocks**: 164

## Developer decisions given in advance

The developer records these decisions in the task contract, so that they
hold however the task is launched, including a bare `Proceed with <TASK-ID>`
from the project console (ADR decision 12). None of these situations needs a
new decision from the developer. After fixing a failure, continue with
revalidation in the same turn; do not stop to report the fix.

- A required command that exits non-zero because of a precondition the agent
  can satisfy (command order, an uncommitted worktree, a missing argument):
  satisfy it and run the command again, once.
- A validation failure caused by this task's own changes, including a name
  collision, a stale reference, a broken link, or a test expectation that the
  task made obsolete: fix it and revalidate, at most 3 counted attempts. A
  test that fails once and passes on an identical unchanged rerun is
  intermittent, recorded in the handoff, and does not count. Only after 3
  counted failures stop with `BLOCKED VALIDATION_FAILED` and a summary of the
  failures.
- A counted attempt is one run of the whole Validation section on a
  committed implementation that the agent considers complete. Test runs
  during implementation are development, not attempts, however many fail.
  An unfinished implementation is never a reason to stop: finish it first.
- Before the first clean-clone, run `python3 scripts/check_repository.py` and one
  `python3 scripts/run_tests.py --parallel` with `--module` for each edited test module
  and for the repository guards: `test_module_inventory`, `test_layout`,
  `test_no_meridian_identifiers`, `test_text_gates`, `test_stop_registry`,
  `test_command_word`, and `test_run_end_to_end.ReplayInventoryTest`. The guards take
  under a minute and catch most failures that a clean-clone would find.
- Let a started clean-clone finish; do not interrupt it to restart after a change. Its
  failure record lists every failure at once, so fix them all together.
- After a failed clean-clone, do not start another one at once. Fix, commit, and run
  `python3 scripts/run_tests.py --parallel --last-failed`, which reads the failures that
  clean-clone recorded for this worktree, and a `--module` run for each module the fix
  touched. Only when both pass, run the clean-clone again as the next counted attempt.
  Judge whether a failure is intermittent with `--last-failed` on the unchanged tree,
  not with a new clean-clone.
- A `BLOCKED <CODE>` from a Meridian command whose entry in
  `capabilities/stop-codes-v1.json` of the primary checkout's `main` has
  `human_decision: false`: run the command the stop names, once. If it stops
  again with the same code, stop.
- A test outside the files this record lists that inventories what the
  repository contains (boundary modules, stop codes, allowances, markers, module
  bindings) and fails only because this task added an item: add that one item, naming
  the real test or owner the inventory asks for, and list the file in the handoff. This
  is not a change of scope. Removing an item, or widening a pattern beyond the new
  item, is.
- A measurement the record asks the handoff to report: use in-process Python
  (wrap `subprocess.Popen` to count, read `resource.getrusage(RUSAGE_CHILDREN)` for
  CPU), never a tool that needs privileges. If one still cannot be obtained, say so in
  the handoff; that is not a stop.
- Before stopping for a change of scope, finish everything else, commit it, and run
  the repository check and the affected tests, so that one stop names every file
  needed. Do not stop once per file.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope
  remain stops.

## Validation

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone run executes `scripts/check_repository.py` and the parallel
suite on a clone of the committed HEAD, so the task does not run them again
in the worktree as counted validation.
