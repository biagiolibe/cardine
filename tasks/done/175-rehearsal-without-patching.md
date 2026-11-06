# Task 175 — Rehearse the adoption without patching the process

> **ID**: `175`
> **Category**: Fix
> **Priority**: 🔴 P1
> **Estimate**: ~1.5h
> **Assigned to**: unassigned
> **Session**: Adoption follow-ups, 2026-11-06
> **Origin**: coordinator finding during task 157

## Objective

`rehearse_adoption` in `src/cardine/adopt/rehearsal.py` imports `unittest.mock` in product
code. While it applies the plan to the copy, it replaces the whole `os.environ` with
`patch.dict(..., clear=True)` and replaces `receipts.host_path` with
`patch.object`. This changes state shared by the whole process, and anything that runs
in that window sees it. Pass the disposable locations as explicit parameters instead,
and add a guard so that no product module imports `unittest`.

## Acceptance Criteria

- [ ] **Process isolation.** Keep `receipts.host_path` and `apply_adopt` signatures
  and Git behavior unchanged. Extract receipt-compatible `encode_plan` and
  `decode_plan` functions. Apply the encoded plan in a child process using the
  disposable home, worktree root, and temporary directory; pass that environment
  to the verifier. The parent never modifies `os.environ` or another module's
  attributes. A failed child raises `CardineError` with its stderr.
- [ ] **Tests.** In `tests/test_adopt_rehearsal.py`:
  - `os.environ` is equal before and after a passing rehearsal, and before and after a
    rehearsal interrupted at each of its four boundaries;
  - while the copy is being applied, its `adopt` host receipt lies under the scratch temporary
    directory, and no receipt for the copy exists under `tempfile.gettempdir()`.
- [ ] **Guard.** `tests/test_module_inventory.py` gains a test that parses every module
  under `src/` with `ast` and fails if any `import` or `from ... import` names `unittest`
  or a submodule of it. The test names the offending module and line.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/175.json`, which only
  the installed `meridian task close 175` writes.
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
| `src/cardine/adopt/rehearsal.py`, `src/cardine/adopt/apply.py`, `src/cardine/lifecycle/receipts.py` | Pass the disposable locations explicitly. |
| `tests/test_adopt_rehearsal.py`, `tests/test_module_inventory.py` | The rehearsal tests and the import guard. |

## Technical Context

- Authority: the developer's approval of 2026-11-06 of the coordinator's proposal after
  task 157.
- Today `host_path` places receipts under `tempfile.gettempdir()` in
  `cardine-operations/`. `apply_adopt` calls it once, at the start, and the receipt
  path is then passed to `operation(...)` in `src/cardine/lifecycle/file_operation.py`.
  The Git calls in `apply_adopt` are `_run_git(root, 'rev-parse', '--show-toplevel')`
  and `git_output(root, 'status', ...)`. `_run_git` in `src/cardine/shared/git.py`
  already takes `env`, so replace the `git_output` call with a `_run_git` call and its
  error check inside `apply.py`. Do not edit `src/cardine/shared/git.py` or
  `file_operation.py`.
- Task 174 edits `src/cardine/templates/init.py`, `src/cardine/templates/adoption.py`,
  `src/cardine/adopt/release.py`, `tests/test_init.py`, and
  `tests/test_adopt_interruption.py`, and task 158 edits `src/cardine/cli.py`. Do not
  edit them.
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

Changing where receipts go for any caller other than the rehearsal. The verifier's audit
rule. Other rows of the queue.

## Dependencies

- **Depends on**: 157
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
