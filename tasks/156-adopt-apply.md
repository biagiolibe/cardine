# Task 156 — Apply the adoption and release the managed copies (C2d)

> **ID**: `156`
> **Category**: Feature
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Work item 10 records, 2026-11-03
> **Origin**: maintenance

## Objective

Implement row C2d of `docs/CONVERSION_PLAN.md`, work item 10 of
`docs/ADR_CARDINE_1_0.md`. The row fixes the scope, the files, the tests, and
the interruption boundaries; this record adds the developer's decisions and no
design.

`apply_adopt` on the `apply_init` writer; release of managed copies and removal of `.meridian/` (DD3); rename of the budget policy.

## Acceptance Criteria

- [ ] Row C2d is implemented as its line in the excerpt describes it.
- [ ] Only the files in the row's files column are edited, together with
  this task's own record and its archive, handoff, and state file. A test
  file outside the column may change only to update an expectation that this
  change made stale, without new behavior, and the handoff lists it. A
  repository check, test helper, or product module outside the column that
  fails only because this row's rename or route made its expectation stale
  is adapted to the new name or route in this task, minimally and without
  loosening it: no check is removed, skipped, or widened, and a route a gate
  cannot resolve still fails. The handoff lists each such file with the
  check that required it. Any other file, or a change that adds behavior
  beyond that adaptation, stops the task before editing it and names the
  file, so that the coordinator splits the row.
- [ ] The row's tests exist and pass: Idempotent rerun; interrupt at every boundary then rerun gives the same tree; unmarked text kept.
- [ ] Rule 4 of decision 14: `before_adopt_declare`, `before_adopt_write:<path>` (each file), `before_adopt_state:<id>` (each task), `before_adopt_release:<path>` (each removal), `before_adopt_result`, `after_adopt_result`.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/156.json`, which only
  the installed `meridian task close 156` writes.
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
| `src/cardine/adopt/apply.py`, `src/cardine/adopt/release.py`, `tests/test_adopt_apply.py`, `tests/test_adopt_interruption.py` | The files this row edits, as the plan lists them. |

## Authority excerpt

The parts of the plan this task needs, extracted from the file on `main` when
the record was written, so that the task reads them here instead of the whole
document:

> From `docs/CONVERSION_PLAN.md`, row C2d:
>
> | C2d / 3h | Meridian: `apply_adopt` on the `apply_init` writer; release of managed copies and removal of `.meridian/` (DD3); rename of the budget policy. | `src/cardine/adopt/apply.py`, `src/cardine/adopt/release.py`, `tests/test_adopt_apply.py`, `tests/test_adopt_interruption.py` | Idempotent rerun; interrupt at every boundary then rerun gives the same tree; unmarked text kept. | `before_adopt_declare`, `before_adopt_write:<path>` (each file), `before_adopt_state:<id>` (each task), `before_adopt_release:<path>` (each removal), `before_adopt_result`, `after_adopt_result`. | C2c |

## Technical Context

- This task depends on 155; the plan's own dependency cell reads:
  C2c.
- Developer decisions of 2026-11-03, binding on every row: DD1: a developer
  channel from an interactive terminal covers the owner verdict, `cancel`, and
  `abort`; reviewer sessions stay refused. DD2: the private projects are converted
  in item 13; `cardine.legacy` and `adopt` stay. DD3: `.meridian/` is removed at
  the switch. DD4: `ci: none`. DD5: the standalone ADR files stay and are cited by
  path.
- Sections 1, 5, and 7 of `docs/CONVERSION_PLAN.md` hold the observations (O1 to
  O9) and the switch that this row serves; read only the parts the row cites.
- The plan estimates this row at 3h. If it turns out larger, finish the
  scope; do not stop for the size alone.
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

## Out of scope

Other rows of the plan, the switch steps that belong to the developer, the
documentation of work item 11, the release script of work item 12, and the
installation surface deferred after 1.0.

## Dependencies

- **Depends on**: 155
- **Blocks**: 157

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
