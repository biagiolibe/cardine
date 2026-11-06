# Task 174 — Declare the capability profile at init

> **ID**: `174`
> **Category**: Fix
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Adoption follow-ups, 2026-11-06
> **Origin**: coordinator finding during task 157

## Objective

`plan_init` in `src/cardine/templates/init.py` writes a manifest with no
`capabilityProfiles`, so `cardine audit` on every freshly initialized project, and on
every project that `adopt` converts, reports the single result
`declaration/legacy-compatibility` (UNVERIFIED) and audits no capability at all. Make
`init` declare the consumer profile of its preset, built exactly as
`bootstrap_capability_profile` in `src/cardine/templates/adoption.py` builds it, so that
the audit checks the project's capabilities from the first commit.

The coordinator checked this on 2026-11-06 in a scratch directory: after `plan_init` and
`apply_init` with each preset, `bootstrap_capability_profile(..., apply=True)` succeeds
and `cardine audit` reports PASS=33, UNVERIFIED=7, FAIL=0. The seven UNVERIFIED results
are capability verification and host activation without probe evidence, which is the
intended starting state. This task makes `init` produce that manifest directly.

## Acceptance Criteria

- [ ] **Profile by preset.** `plan_init` with preset `lean` declares
  `lean-delivery-consumer`, and with preset `governed` declares `governed-sdd-consumer`,
  in the manifest it plans. No other profile is declared.
- [ ] **One builder.** The declaration is produced by the same code that
  `bootstrap_capability_profile` uses (`_capability_declaration` today), applied to the
  bytes the plan writes. The builder may take the file contents from a mapping instead of
  the disk, but there is one implementation of the declaration, not a copy.
- [ ] **Equality, not text.** Tests apply `init` with each preset and assert that the
  written manifest equals the manifest that `bootstrap_capability_profile(root,
  framework, profile, apply=False)` returns for the written tree. A Meridian conversion
  applied through `apply_adopt` is checked the same way, in
  `tests/test_adopt_interruption.py`, on its existing conversion fixture. If the
  conversion edits a profile surface after `plan_init` (for example, by appending project
  prose to `docs/CONTEXT_READING_POLICY.md`), the converted manifest still equals the
  bootstrap result for the converted tree.
- [ ] **Audit outcome.** In the same tests, the audit of the initialized project and of
  the converted project has no FAIL result and no `declaration/legacy-compatibility`
  result. The test compares statuses and result identities, never detail text.
- [ ] **No protocol change.** `PROTOCOL_VERSION` and
  `CAPABILITY_DECLARATION_REQUIRED_PROTOCOL` in `src/cardine/shared/constants.py` stay as
  they are, and a manifest without profiles keeps its current audit result.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/174.json`, which only
  the installed `meridian task close 174` writes.
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
| `src/cardine/templates/init.py`, `src/cardine/templates/adoption.py` | Plan the profile declaration; share the builder. |
| `src/cardine/adopt/release.py` | Only if the conversion must rebuild the declaration after it edits a profile surface. |
| `tests/test_init.py`, `tests/test_adopt_interruption.py` | The equality and audit tests. |

## Technical Context

- Authority: the developer's approval of 2026-11-06 of the coordinator's proposal after
  task 157. The rehearsal verifier of task 157 compares a converted copy's audit with
  the audit of a freshly initialized reference project. With this task the reference
  audits real capabilities, so the rehearsal becomes stricter without a change to
  `src/cardine/adopt/verify.py`. Do not edit that file.
- Surfaces of both consumer profiles: `docs/CONTEXT_READING_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/COMPLETION_REPORT_TEMPLATE.md`,
  `LANGUAGE_POLICY.md`, and `PROJECT_WORKFLOW.md`, all managed copies. Every one either
  carries a capability marker or is in `PROJECT_EDITABLE_MANAGED_PATHS`, so
  `_digest_exempt` applies and its evidence is `path:<file>`, not a digest.
- `adopt` builds its outputs through `plan_init` in `src/cardine/adopt/release.py`
  (`conversion_outputs`), so a converted project gets the manifest from the same plan.
- Task 175 edits `src/cardine/adopt/rehearsal.py`, `src/cardine/adopt/apply.py`,
  `src/cardine/lifecycle/receipts.py`, and `tests/test_adopt_rehearsal.py`, and task 158
  edits `src/cardine/cli.py`. Do not edit them.
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

Raising the protocol version, so that a manifest without profiles fails the audit: a
compatibility decision for existing projects, not needed for 1.0. Probe evidence that
would turn the UNVERIFIED results into PASS. Other rows of the queue.

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
