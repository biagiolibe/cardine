# Task 186 — Make the switch commit pass the repository checks

> **ID**: `186`
> **Category**: Fix
> **Priority**: 🔴 P1
> **Estimate**: ~1h
> **Assigned to**: unassigned
> **Session**: Switch preparation, 2026-11-07
> **Origin**: developer's first switch attempt; coordinator prototype of 2026-11-07

## Objective

Rule 2 of section 5 of `docs/CONVERSION_PLAN.md` requires the switch commit, the
unedited output of `cardine adopt --apply`, to pass this repository's checks. The
coordinator converted a disposable clone of `main` at `ae56eb9` and ran the full suite
on the result. It failed for four reasons, none of them in the conversion itself:

1. **Receipt authority is tracked.** `adopt --apply` writes
   `.cardine/receipt-authority.json` with this checkout's absolute paths, and a
   `git add -A` tracks it. `check_no_machine_paths` then fails. The file is
   machine-local, so this repository ignores it.
2. **Task state records its authority.** Each `.cardine/tasks/<id>.json` copies the
   same authority, including absolute paths. Task state must stay tracked, so the
   machine-path check exempts exactly that pattern.
3. **The identifier guard has no allowance for Cardine state.** The converted
   `.cardine/baselines/<version>/.codex/rules/meridian.rules`, the
   `.codex/rules/meridian.rules` key of `.cardine/manifest.json`, and the task state of
   tasks 180 and 182 contain the old name. Group 6 covers them. Like groups 3 and 5, it
   is required only while a matching file exists. Unlike them, row C7c does not delete
   it: it lasts until the rules template is renamed.
4. **Three tests read the Meridian installation unconditionally.** They are
   `ManagedDigestTest` (`.meridian/manifest.json`), the live execution-profile test,
   and the Codex hook-definition test (the converted `.codex/hooks.json` calls
   `cardine`). Each now runs only while `.meridian/` exists. Rows C7a and C7b delete
   the first and the third.

With the diff below applied, the coordinator measured:
- before the switch: the full suite (`OK ran=2163`) and the repository check pass;
- after a fresh `adopt --apply` on a clone of that commit: the outcome is `done`, and
  the repository check, `test_check_repository`, `test_no_meridian_identifiers`, and
  the full suite pass.

The coordinator fixed the dependency of record 178 on `main` before this task.

## Prototype diff

Apply this diff as written. It is the whole change.

```diff
--- a/.gitignore
+++ b/.gitignore
@@ -4,3 +4,6 @@
 # Python bytecode caches
 __pycache__/
 *.py[cod]
+
+# Machine-local Cardine receipt authority (absolute paths of this checkout)
+.cardine/receipt-authority.json
--- a/scripts/check_repository.py
+++ b/scripts/check_repository.py
@@ -979,6 +979,8 @@ def check_managed_digests(root: Path = ROOT) -> None:
 MACHINE_PATH_ALLOWED_FILES: frozenset[str] = frozenset()
+# Cardine task state records the receipt authority of the checkout that wrote it.
+MACHINE_PATH_ALLOWED_PATTERN = re.compile(r"\.cardine/tasks/[^/]+\.json")
 MACHINE_PATH_PATTERN = re.compile(
@@ -998,7 +1000,7 @@ def check_no_machine_paths(
-        if not name or name in allowed or not path.is_file():
+        if not name or name in allowed or MACHINE_PATH_ALLOWED_PATTERN.fullmatch(name) or not path.is_file():
--- a/tests/test_check_repository.py
+++ b/tests/test_check_repository.py
@@ -829,10 +829,19 @@ class MachinePathTest(unittest.TestCase):
+    def test_cardine_task_state_may_record_its_authority_paths(self) -> None:
+        self.track(".cardine/tasks/178.json", self.FORBIDDEN["linux"].encode())
+        cr.check_no_machine_paths(self.root)
+
+        self.track(".cardine/project.json", self.FORBIDDEN["linux"].encode())
+        self.assert_fails(".cardine/project.json:1")
+
     def test_repository_has_no_machine_paths(self) -> None:
         cr.check_no_machine_paths()
 
 
+# MERIDIAN-INSTALLATION-CHECK
+@unittest.skipUnless((ROOT / ".meridian").is_dir(), "reads the Meridian installation removed at the switch; deleted by task 178")
 class ManagedDigestTest(unittest.TestCase):
--- a/tests/test_codex_worktree_hooks.py
+++ b/tests/test_codex_worktree_hooks.py
@@ -64,6 +64,8 @@ class CodexWorktreeHooksTest(unittest.TestCase):
     @unittest.skipUnless(hooks_config_present(), ".codex/hooks.json is absent from this checkout")
+    # MERIDIAN-INSTALLATION-CHECK
+    @unittest.skipUnless((ROOT / ".meridian").is_dir(), "reads the Meridian hook definitions replaced at the switch; removed by task 179")
     def test_primary_project_definitions_process_worktree_payloads(self) -> None:
--- a/tests/test_no_meridian_identifiers.py
+++ b/tests/test_no_meridian_identifiers.py
@@ -126,6 +126,19 @@ ALLOWLIST = (
         3, "10",
         r"\." + OLD + r"/.*",
     ),
+    Allowance(
+        6, "kept: Cardine baselines and manifest name the rules template until it is renamed",
+        r"\.cardine/baselines/[^/]+/\.codex/rules/" + OLD + r"\.rules",
+    ),
+    Allowance(
+        6, "kept: Cardine baselines and manifest name the rules template until it is renamed",
+        r"\.cardine/manifest\.json",
+        r"\.codex/rules/" + OLD + r"\.rules",
+    ),
+    Allowance(
+        6, "kept: task state repeats record paths and titles, like the records of group 4",
+        r"\.cardine/tasks/[^/]+\.json",
+    ),
@@ -223,7 +236,7 @@ def scan_repository(root: Path, allowlist=ALLOWLIST)
-        if not used[index] and (entry.group not in (3, 5) or index in present):
+        if not used[index] and (entry.group not in (3, 5, 6) or index in present):
@@ -233,7 +246,7 @@ class IdentifierGuardTest(unittest.TestCase):
-            for group in (3, 5):
+            for group in (3, 5, 6):
--- a/tests/test_template_manifest.py
+++ b/tests/test_template_manifest.py
@@ -804,6 +804,8 @@ class CapabilityProfileManifestTest(unittest.TestCase):
+    # MERIDIAN-INSTALLATION-CHECK
+    @unittest.skipUnless((ROOT / ".meridian").is_dir(), "reads the Meridian-era profile replaced at the switch")
     def test_live_execution_profile_has_no_unresolved_configuration_placeholder(self) -> None:
```

## Acceptance Criteria

- [x] The prototype diff is applied to the six files under Relevant Files, and nothing
  else changes in them.
- [x] Before the switch, the new test and the guard pass, and no test is skipped by the
  new conditions, because `.meridian/` exists.
- [x] **Conversion evidence.** Use a disposable clone of the implementation commit,
  with a disposable `HOME`, `TMPDIR`, and `CARDINE_WORKTREE_ROOT`. Run `python3 -m
  cardine.cli adopt --project <clone> --apply --name Cardine --slug cardine --language
  Italian --validation <file>` with `PYTHONPATH` set to the worktree's `src`. The
  validation file is `{"commands": {"repository-check": "python3
  scripts/check_repository.py"}, "baseline": ["repository-check"], "candidate":
  {"FULL": ["repository-check"]}}`. Then, in the clone:
  - the outcome is `done` and `diagnostics` is empty;
  - after `git add -A` and a commit, `git ls-files .cardine/receipt-authority.json`
    prints nothing;
  - `python3 scripts/check_repository.py` passes, and so does `python3
    scripts/run_tests.py --parallel`.

  The handoff records the outcome and both result lines. Never run `--apply` on this
  repository or on the task worktree.
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
- [x] `.meridian/` is unchanged, except `.meridian/tasks/186.json`, which only
  the installed `meridian task close 186` writes.
- [x] The parallel suite reports coverage `total=2164`, which is the 2163 tests of
  `main` plus the new test.
- [x] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean
  task worktree and record its result line in the handoff.
- [x] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `.gitignore` | Ignore the machine-local receipt authority. |
| `scripts/check_repository.py`, `tests/test_check_repository.py` | Machine-path exemption for task state; conditional digest test. |
| `tests/test_no_meridian_identifiers.py` | Group 6 allowances for Cardine state. |
| `tests/test_codex_worktree_hooks.py`, `tests/test_template_manifest.py` | Installation-conditional tests. |

## Technical Context

- Authority: rule 2 of section 5 of `docs/CONVERSION_PLAN.md`. The switch commit is not
  edited, so every check it must pass is fixed before it.
- The skip conditions read `ROOT / ".meridian"`, matching the presence tests of rows
  C5a to C5d. Each new line that names the old identifier carries the
  `MERIDIAN-INSTALLATION-CHECK` tag, on the line or the line before, as the group 5
  allowance requires.
- Group 6 is not group 3 because row C7c (task 180) deletes groups 3 and 5, while
  these allowances stay as long as the template ships `.codex/rules/meridian.rules`.
- During development, run only what the change touches: `python3
  scripts/run_tests.py --parallel --module <name>` for a module, class, or
  test, and `python3 scripts/run_tests.py --parallel --last-failed` after a
  failed full run. Do not run `python3 -m unittest` directly, and run the full
  suite once, as the counted clean-clone validation.
- If `worktree advance` stops because another task holds the integration lease
  in the primary checkout, that is not a decision for the developer: wait
  until the other integration finalizes or aborts, then rerun the same
  `advance` command.
- Other tasks share this machine. Stop only your own processes, by process ID;
  never `pkill` test runs by pattern.

## Out of scope

The switch steps, which belong to the developer. Rows C7a onward. Changes to
`cardine adopt`, including:
- recognizing archived queue rows as closed dependencies;
- writing receipt authority without absolute paths;
- ignoring `receipt-authority.json` in projects that Cardine initializes or adopts.

The coordinator plans those separately.

## Dependencies

- **Depends on**: none
- **Blocks**: the switch (steps S1 to S7)

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
- If the conversion evidence fails, first check whether this task's diff causes the
  failure. If it does, fix it within the listed files. If it does not, the failure is a
  change of scope: report the command, its output, and the file it names.
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
- Before stopping for a change of scope, finish everything else, commit it, and run
  the repository check and the affected tests, so that one stop names every file
  needed. Do not stop once per file.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope
  remain stops.

## Validation

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel --module test_no_meridian_identifiers`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone run executes `scripts/check_repository.py` and the parallel
suite on a clone of the committed HEAD, so the task does not run them again
in the worktree as counted validation.
