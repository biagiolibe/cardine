# Task 176 — Keep the legacy worktree root in the Codex permission profile

> **ID**: `176`
> **Category**: Fix
> **Priority**: 🔴 P1
> **Estimate**: ~3h
> **Assigned to**: unassigned
> **Session**: Coexistence follow-ups, 2026-11-06
> **Origin**: finding of task 163

## Objective

Codex selects one permission profile for every project on the machine, through the
top-level `default_permissions` key of `~/.codex/config.toml`. Today `cardine setup
--apply` migrates the known legacy block (`# MERIDIAN:BEGIN worktree-permissions v1`,
profile `meridian-worktrees`, `plan_codex_configuration` in
`src/cardine/hosts/codex.py`) into the Cardine block (profile `cardine-worktrees`), whose
only workspace root is the Cardine worktree root. After step S7, Codex could then no
longer write in the task worktrees of projects that still run on the legacy tool. This
is the same defect as the Codex user rules (K9, row C5e), but for permissions.

While the legacy tool stays installed, the Cardine profile must also list the legacy
worktree root, and later setup runs must recognize that root exactly, without guessing.

## Acceptance Criteria

- [ ] **Two roots while the legacy tool is installed.** When the legacy tool is
  installed (the check that task 163 added in `src/cardine/hosts/setup.py`), migrating
  the known legacy block produces the Cardine block with `default_permissions =
  "cardine-worktrees"` and a `workspace_roots` table that holds exactly two keys set to
  `true`: the Cardine worktree root and the legacy worktree root. Text outside the two
  blocks stays byte-identical, as today.
- [ ] **The legacy root is resolved, not remembered.** The legacy root is computed with
  the legacy tool's own precedence: the `MERIDIAN_WORKTREE_ROOT` variable of the
  environment passed in; otherwise `worktreeRoot` from
  `<XDG_CONFIG_HOME or home/.config>/meridian/config.json`; otherwise
  `<home>/.meridian/worktrees`. The function reads only the home and environment it is
  given, like task 163's check. Migration refuses with a "reconcile it manually" error,
  and writes nothing, when the root in the legacy block differs from the resolved one.
- [ ] **Ownership checks know the second root.** Every check that compares the
  Cardine block with its expected content uses the same expected profile, so a
  second run of `setup --check` reports the profile as ready and `setup --apply`
  changes nothing. This covers `_codex_profile_divergence`, the marker and ownership
  repair paths, and `codex_profile_root_mismatch`. While the legacy tool is installed,
  the expected profile has both roots. Otherwise it has only the Cardine root. Any
  other extra root is divergence, as today.
- [ ] **Removal after the legacy tool.** When the legacy tool is no longer installed
  and the Cardine block still lists the resolved legacy root, `setup --check` proposes
  removing it, and `setup --apply` removes it (approval required, like every profile
  change). A rerun then converges.
- [ ] **Re-added legacy block.** If the known legacy block is present again next to an
  intact Cardine block, for example because `meridian setup --apply` ran after Cardine's
  setup, `setup --check` reports both profiles and the exact remedy, and `setup --apply`
  removes the known legacy block and restores the expected Cardine block. A legacy block
  that is not the known one keeps today's refusal.
- [ ] **Tests** in `tests/test_host_codex_repair.py`, each in a disposable home:
  - migration with the legacy tool installed (two roots) and without it (one root,
    today's result);
  - a rerun is a no-op;
  - a legacy block whose root differs from the resolved root is refused with no write;
  - `MERIDIAN_WORKTREE_ROOT` and the user configuration each select the legacy root;
  - an unknown extra root is reported as divergence;
  - the legacy root is removed after the legacy tool is uninstalled;
  - the re-added known legacy block is resolved.

  In `tests/test_host_coexistence.py`: after `setup --apply` in a home with both tools,
  the Cardine profile lists both roots, so a Meridian project's worktree root and a
  converted project's worktree root are both writable roots of the selected profile.
- [ ] **Documentation.** `docs/HOST_CAPABILITY_CONTRACT.md` records the two-root
  profile and that the legacy tool's own `codex doctor` and `setup --check` then report
  a divergence on its profile, which is expected. It also records that
  `meridian setup --apply` must not be run after `cardine setup --apply` during
  coexistence, and that Cardine's setup repairs it if it happens.
- [ ] **Recorded for S7.** The handoff states the exact `cardine setup --check`
  output expected on the developer's machine for step S7, derived from the tests,
  without running setup against the real home directory.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/176.json`, which only
  the installed `meridian task close 176` writes.
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
| `src/cardine/hosts/codex.py`, `src/cardine/hosts/setup.py` | Expected profile, migration, repair, and the legacy root. |
| `src/cardine/hosts/skills.py` | Coordinator scope amendment: compare the optional legacy root in the existing mismatch helper. |
| `tests/test_host_codex_repair.py`, `tests/test_host_coexistence.py` | The tests. |
| `docs/HOST_CAPABILITY_CONTRACT.md` | The coexistence note. |

## Technical Context

- Authority: the developer's approval of 2026-11-06 to analyze and plan this finding
  of task 163. The coordinator's analysis:
  - Codex has one `default_permissions` for all projects. The Codex documentation does
    not say whether a project's `.codex/config.toml` may select a permission profile,
    so per-project selection is not used.
  - `workspace_roots` is a table, so one profile can list several roots.
  - In the legacy tool 1.4.1 (`scripts/meridian.py` of the installed copy), the profile
    is read only by `setup` and `codex doctor`. No lifecycle command (`worktree`,
    `execution`, `profile doctor`, `audit`) reads it, so the legacy tool's projects
    keep working when the default selects the Cardine profile.
  - The legacy root precedence above is its `resolve_worktree_root` and
    `user_configuration_path`. A `--worktree-root` flag of the legacy CLI has no
    equivalent here.
- Task 163 adds the legacy-tool check and the coexistence tests. This task starts
  after it lands and reuses that check; do not add a second one.
- The real machine today has `default_permissions = "meridian-worktrees"` with the
  root `~/.meridian/worktrees`. Never read or write the real home directory; tests build
  that state in a disposable home.
- Never run the checkout's `setup --apply` against the real home directory.
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

Per-project permission profiles. Changes to the legacy tool. The Codex user rules and
the Claude hooks, which belong to task 163. Removing the legacy tool from the machine,
which is ADR decision 10, after the last conversion.

## Dependencies

- **Depends on**: 163
- **Blocks**: the switch (step S7)

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
