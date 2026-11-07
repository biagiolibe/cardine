# Task 187 — Check path aliases only where the platform resolves them

> **ID**: `187`
> **Category**: Fix
> **Priority**: 🔴 P1
> **Estimate**: ~30min
> **Assigned to**: unassigned
> **Session**: Switch preparation, 2026-11-07
> **Origin**: CI of the switch pull request; coordinator diagnosis of 2026-11-07

## Objective

Rule 2 of section 5 of `docs/CONVERSION_PLAN.md` requires the switch commit to pass CI.
The `validate.yml` suite step has failed on every push to `main` since at least
2026-11-04, on one test only:
`test_host_permissions.PathActionMatrixTest.test_aliases_symlinks_and_dot_dot_resolve_to_the_protected_destination`.
The job is marked `continue-on-error: true`, so the run still showed as successful.

The defect is in the test, not in the permission check. The test checks three spellings
of the protected task state: `real`, `bare` (without `/private`), and `"/private" +
bare`. On macOS, `/tmp` and `/var` are aliases of `/private/tmp` and `/private/var`, so
all three name the same file. On the Linux runner, `real` is `/tmp/...` and
`/private/tmp/...` is a different path that does not exist. The permission check
correctly allows an edit there, and the test wrongly expects a denial. The CI output
names that spelling:
`AssertionError: True is not false : /private/tmp/cardine-tests-.../elsewhere/task-001`.

The fix is mechanical: assert the denial only for the spellings that resolve to the
same directory as `real` on the running platform. macOS keeps all three checks, and
Linux keeps the real one.

## Prototype diff

The coordinator applied this diff to a scratch clone of `main` at `21a257b`, and
`python3 scripts/run_tests.py --parallel --module test_host_permissions` reported
`ran=32 failures=0 errors=0` on macOS.

```diff
--- a/tests/test_host_permissions.py
+++ b/tests/test_host_permissions.py
@@ -115,8 +115,11 @@ class PathActionMatrixTest(Fixture):
                 self.assertFalse(self.decide("implementer", f"echo x > {path}"))
         real = str(self.external)
         bare = real.removeprefix("/private") if real.startswith(("/private/var/", "/private/tmp/")) else real
-        for spelling in (real, bare, "/private" + bare if not real.startswith("/private/") else real):
-            self.assertFalse(self.native("implementer", "Edit", file_path=f"{spelling}/{STATE}"), spelling)
+        # Check only the spellings that this platform resolves to the same directory:
+        # /tmp aliases /private/tmp on macOS, while on Linux /private/tmp is another path.
+        for spelling in {real, bare, "/private" + bare}:
+            if Path(spelling).resolve() == Path(real).resolve():
+                self.assertFalse(self.native("implementer", "Edit", file_path=f"{spelling}/{STATE}"), spelling)
         self.assertFalse(self.decide("implementer", "ln -s .cardine/tasks/001.json src/alias2"))
 
     def test_shell_writers_chains_pipes_and_redirects(self) -> None:
```

## Acceptance Criteria

- [ ] The prototype diff is applied to `tests/test_host_permissions.py`, and nothing
  else changes in it.
- [ ] `python3 scripts/run_tests.py --parallel --module test_host_permissions` passes.
- [ ] Only `tests/test_host_permissions.py` is edited, together with this task's own
  record and its archive, handoff, and state file. Any other file, or new behavior
  beyond this record, stops the task before editing it and names the file.
- [ ] No source file under `src/` changes: the permission check is correct.
- [ ] This repository's own lifecycle keeps running on the installed Meridian 1.4.1.
- [ ] The frozen files stay unchanged: `CLAUDE.md`, `AGENTS.md`,
  `PROJECT_WORKFLOW.md`, `LANGUAGE_POLICY.md`,
  `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`,
  `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md`,
  `.codex/hooks.json`, `.codex/rules/meridian.rules`, `hooks/hooks.json`,
  `hooks/queue-briefing.sh`, `hooks/read-guard.sh`, and the `meridian
  worktree` line of `.codex/rules/local.rules`. No task runs the checkout's
  `setup --apply` against the real home directory or creates `.cardine/` in this
  repository.
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/187.json`, which only the
  installed `meridian task close 187` writes.
- [ ] The parallel suite reports coverage `total=2164`, unchanged.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task worktree
  and record its result line in the handoff.
- [ ] Every command under Validation passes.

The Linux result is not part of task acceptance: the CI suite step on `main` after the
integration push shows it, and the developer reads it at step S1 of the switch.

## Relevant Files

| File | Role |
|------|------|
| `tests/test_host_permissions.py` | The alias assertions of `PathActionMatrixTest`. |

## Technical Context

- Authority: rule 2 and condition B1 of section 5 of `docs/CONVERSION_PLAN.md`.
- `Path.resolve()` is non-strict: on Linux, `/private/tmp/...` does not exist and
  resolves to itself, which differs from `real`, so that spelling is skipped. On macOS
  every spelling resolves to `/private/...`, so all three are asserted.
- The set removes duplicate spellings, which the old conditional expression handled.
- Run only what the change touches during development: `python3 scripts/run_tests.py
  --parallel --module test_host_permissions`. Do not run `python3 -m unittest`
  directly. Run the full suite once, as the counted clean-clone validation.
- Run validation suites one at a time, never two in parallel. Redirect each suite's
  output to a log file and append its exit code, so the result survives a lost
  process handle. Report only exit codes read from a finished run.
- Close with `meridian worktree advance` from the primary checkout. Never call
  `meridian worktree evidence` directly: it requires the task worktree as current
  directory.
- Other tasks share this machine. Stop only your own processes, by process ID; never
  `pkill` test runs by pattern.

## Out of scope

The switch steps, which belong to the developer. Removing `continue-on-error` from
`validate.yml`, which the coordinator plans after the switch. Changes to the
permission check.

## Dependencies

- **Depends on**: none
- **Blocks**: the switch (steps S1 to S7)

## Developer decisions given in advance

The developer records these decisions in the task contract, so that they hold however
the task is launched, including a bare `Proceed with <TASK-ID>` from the project
console (ADR decision 12). None of these situations needs a new decision from the
developer. After fixing a failure, continue with revalidation in the same turn; do not
stop to report the fix.

- A required command that exits non-zero because of a precondition the agent can
  satisfy (command order, an uncommitted worktree, a missing argument, the wrong
  current directory): satisfy it and run the command again, once.
- A validation failure caused by this task's own change: fix it and revalidate, at
  most 3 counted attempts. A test that fails once and passes on an identical unchanged
  rerun is intermittent, recorded in the handoff, and does not count. Only after 3
  counted failures stop with `BLOCKED VALIDATION_FAILED` and a summary of the failures.
- A counted attempt is one run of the whole Validation section on a committed
  implementation that the agent considers complete. Test runs during implementation
  are development, not attempts.
- Let a started clean-clone finish; do not interrupt it. After a failed clean-clone,
  fix, commit, and run `python3 scripts/run_tests.py --parallel --last-failed` before
  the next counted clean-clone.
- A clean-clone failure that this task's diff does not cause is a change of scope:
  report the command, its output, and the file it names.
- A `BLOCKED <CODE>` from a Meridian command whose entry in
  `capabilities/stop-codes-v1.json` of the primary checkout's `main` has
  `human_decision: false`: run the command the stop names, once. If it stops again
  with the same code, stop.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope remain stops.

## Validation

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel --module test_host_permissions`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone run executes `scripts/check_repository.py` and the parallel suite on a
clone of the committed HEAD, so the task does not run them again in the worktree as
counted validation.
