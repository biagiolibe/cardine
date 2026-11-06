# Task 177 — Translate Validation sections as the Cardine contract reads them

> **ID**: `177`
> **Category**: Fix
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Adoption follow-ups, 2026-11-06
> **Origin**: finding of task 164 (rehearsal stopped with `ADOPT_RECORD`)

## Objective

`translate_record` in `src/cardine/adopt/records.py` refuses two things that every open
record of this repository contains, so `cardine adopt --rehearse` stops with
`ADOPT_RECORD` on records 164 and 176:

1. **Prose in the Validation section.** The translator treats every non-empty line as an
   entry and refuses a paragraph after the list ("cannot translate"). The Cardine
   contract does not: `require_named_validation_commands` and `validation_commands` in
   `src/cardine/tasks/evidence.py` treat only lines that start with `- ` as entries and
   accept other lines. The translator must apply the same rule as its target.
2. **Meridian commands.** A `meridian ...` entry is refused as "requires replacement".
   These commands check the Meridian installation, which the conversion removes, so after
   conversion they can never run. Mapping them is wrong too: `cardine audit` exits 1 on
   the UNVERIFIED results that a bootstrapped capability profile has by design, so a
   mapped audit would fail every task. Drop them and report each drop to the caller, as
   the translator already does for dependencies on closed tasks.

## Acceptance Criteria

- [ ] **Entries as the contract reads them.** Only a line of the Validation section
  that starts with `- ` is an entry. Every other line, prose or blank, is kept verbatim
  and in place in the translated section. An entry that is neither ``- `id`: `command` ``
  nor ``- `command` `` is still a diagnostic, as today.
- [ ] **Meridian entries dropped and reported.** An entry whose command starts with the
  program `meridian` is removed from the translated section and recorded in a new field
  `RecordTranslation.dropped_validation`, a tuple of the dropped commands in record
  order. It is no longer a diagnostic. A section left with no command at all is still
  the diagnostic `Validation: no translatable commands`.
- [ ] **Visible in the plan.** `AdoptPlan` in `src/cardine/adopt/plan.py` gains
  `dropped_validation: dict[str, tuple[str, ...]]`, keyed by task ID like
  `dropped_dependencies`, with an empty default so that existing constructors keep
  working. `AdoptPlan.bytes()` and the plan saved in the adoption receipt by
  `encode_plan` and `decode_plan` in `src/cardine/adopt/apply.py` include it; decoding a
  saved plan without the key yields an empty dictionary.
- [ ] **Tests.** `tests/test_adopt_records.py` covers: a section with a list and a
  following paragraph translates with the paragraph unchanged; a `meridian` entry among
  others is dropped and reported while the others keep their IDs; a section of only
  `meridian` entries gives the no-commands diagnostic; an indented or malformed entry is
  still a diagnostic. `tests/test_adopt_plan.py` covers a Meridian project whose open
  record has both kinds, planned without `ADOPT_RECORD`, with the drop listed under
  `dropped_validation` for that task. The translated record of that test passes
  `require_named_validation_commands`.
- [ ] Only the files under Relevant Files are edited, together with this
  task's own record and its archive, handoff, and state file. A test file
  outside that list may change only to update an expectation that this change
  made stale, without new behavior, and the handoff lists it. Any other file,
  or new behavior beyond this record, stops the task before editing it and
  names the file.
- [ ] Tests that need a home directory create a disposable one themselves. Run the
  validation commands with the inherited environment, as written; never wrap them in a
  temporary home, and a run that inherited the real home is not a stop. No step runs
  `setup --apply` against the real home directory or writes real host configuration.
- [ ] The subprocess ceilings of `tests/test_command_context.py` still hold.
- [ ] Every source and test file stays below 1,500 lines.
- [ ] This repository's own lifecycle keeps running on the installed Meridian
  1.4.1.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the
  checkout's `setup --apply` against the real home directory or creates
  `.cardine/` in this repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/177.json`, which only
  the installed `meridian task close 177` writes.
- [ ] A test expectation that this task makes stale is updated in this task
  without weakening any other assertion. The parallel suite reports the
  same coverage `total` before and after the task, except for new or
  deliberately removed tests, which the handoff lists with their reason.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `src/cardine/adopt/records.py`, `src/cardine/adopt/plan.py`, `src/cardine/adopt/apply.py` | The translator, the plan, and the saved plan encoding. |
| `tests/test_adopt_records.py`, `tests/test_adopt_plan.py` | The translation and planning tests. |

## Technical Context

- Authority: task 164's handoff of 2026-11-06 and the developer's approval of this
  record. Row C2b of `docs/CONVERSION_PLAN.md` introduced the translator.
- The records of this repository end their Validation section with a paragraph that
  explains the clean-clone run, after the list. Records 164 and 176 are the open
  examples; read their Validation sections for the exact shape.
- `src/cardine/tasks/evidence.py` is the reference for what an entry is. Do not edit it.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.
- During development, run only what the change touches: `python3
  scripts/run_tests.py --parallel --module <name>` for a module, class, or
  test, and `python3 scripts/run_tests.py --parallel --last-failed` after a
  failed full run. Both print only failures. Do not run `python3 -m unittest`
  directly, and run the full suite once, as the counted clean-clone
  validation.
- Other tasks share this machine. Stop only your own processes, by process ID;
  never `pkill` test runs by pattern.

## Out of scope

Mapping other Meridian vocabulary in records, the rehearsal itself (task 164), and the
records of rows C7a onward. Other rows of the queue.

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
