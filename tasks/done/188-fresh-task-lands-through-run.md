# Task 188 — Deliver a task created by init and task new through run alone

> **ID**: `188`
> **Category**: Fix
> **Priority**: 🔴 P1
> **Estimate**: ~2h
> **Assigned to**: unassigned
> **Session**: Switch preparation, 2026-11-07
> **Origin**: coordinator prototype of 2026-11-07; open findings 1, 2, and 4 of the task 152 handoff

## Objective

A project created with `cardine init`, with one task created by `cardine task new`,
must reach `done` on `main` when an agent runs only `cardine run <ID>` and commits
its own change. This task lands before the switch: otherwise defects 2 and 3 below
stop task 178, the first delivery under Cardine, and every task after it. ADR decision 6 makes `cardine run` the only lifecycle command an agent
needs; decision 14, rule 3, makes a stop for something the tool can determine a defect.

The coordinator ran that flow in a disposable project on `main` at `f0d31ce`
(lean preset, a quick task with `Expected code surface`, a local bare `origin`). It
failed four times in a row. The proofs of tasks 147, 151, and 152 did not catch it,
because they write the project configuration directly instead of running `init`, and
their implementer runs `git add .`.

1. **The contract step loops.** `task new` publishes the record without its resolved
   execution block. The first `run` prepares the worktree from that commit, and
   `execution start` stops with `EXECUTION_CONTRACT_UNRESOLVED`. Its `next` command,
   `cardine execution reconcile 001 --apply --project .`, runs in the primary
   checkout, so the worktree keeps the old record and every later `run` returns the
   same command. Run in the worktree instead, the reconcile leaves it dirty, and the
   next `run` stops with `BLOCKED WRONG_WORKTREE`.
2. **The implementation step never delivers.** After the agent commits, `run` keeps
   returning the same work request with `next` set to `run` itself (task 152,
   finding 1). Delivery needs `cardine execution deliver`, which no output names.
3. **Delivery refuses committed work.** `execution start` leaves the task state file
   modified in the worktree. An agent that commits only its own files gets
   `COMMAND_REFUSED: implementation must be committed before delivery` (task 152,
   finding 2).
4. **The work request does not point at the task.** `acceptance_references` is empty
   for a standard task (task 152, finding 4).

With the diff below applied, the same flow runs from `queued` to `done` on `main`:
`worktree` → `implementation` (work request) → agent commit → `implementation`
(`progress`, `deliver`) → `candidate` → `landing` → `done`. See Prototype evidence.

## Prototype diff

Apply this diff as written. It is the whole change. It was written on `f0d31ce` and
applies unchanged to `main` at `2734f3d`.

- `task new` publishes the record with its resolved execution block, rendered by the
  same function as `execution reconcile` (`render_execution_contract`). A replay
  compares proposals without that block, so a changed proposal or changed published
  bytes are still refused.
- `run` commits the state transition that `execution start` writes in the worktree.
- `run` delivers a clean worktree whose commits since its base change a path Cardine
  does not own, through the existing `deliver_run_implementation` adapter, and
  returns `outcome: progress`, `action: deliver`. `next` stays `cardine run`, so the
  console's launch command is unchanged.
- A standard task's work request names `<recordPath>#acceptance-criteria`; a spike
  keeps its deliverables.
- Four test modules update expectations that this change made stale, and
  `test_execution_start_fresh_task` gains `test_fresh_record_starts_without_reconcile`.
  The reconcile tests now change the profile on `main` after task creation, which is
  the case reconcile still serves.
- `InitializedProjectDeliveryTest` in `tests/test_run_delivery_disposable.py` is the
  end-to-end regression test: `init` into an empty repository with a disposable
  `HOME`, `TMPDIR`, and worktree root and a local bare `origin`, a quick task from
  `task new`, only `run` calls, and an implementer that commits only `README.md`. It
  asserts that no result is `blocked`, that every `next` is `cardine run`, and that
  the remote `main` holds the change.

```diff
diff --git a/src/cardine/lifecycle/engine.py b/src/cardine/lifecycle/engine.py
index 3ae2dee..7afcaaa 100644
--- a/src/cardine/lifecycle/engine.py
+++ b/src/cardine/lifecycle/engine.py
@@ -362,6 +362,13 @@ def run_worktree_step(locations: RunLocations, active: dict) -> dict | None:
             receipts.boundary('after_run_prepare')
     with _inside(worktree):
         started = execution_start(worktree, task_id, context=locations)
+        # Commit the state transition Cardine just wrote, so the implementer's
+        # own commit leaves a clean worktree (ADR decision 14, rule 3).
+        from cardine.shared.git import git_output
+        from cardine.tasks.state import state_path
+        relative = state_path(worktree, task_id).relative_to(worktree).as_posix()
+        if git_output(worktree, 'status', '--porcelain', '--', relative):
+            git_output(worktree, 'commit', '-q', '-m', f'Start task {task_id}', '--', relative)
     receipts.boundary('after_run_execution_start')
     argv = ['cardine', 'run', task_id, '--project', str(locations.primary)]
     return envelope(task_id, str(locations.primary), step='worktree', action='execution-start',
@@ -388,7 +395,7 @@ def run_validation_step(locations: RunLocations) -> dict | None:
     contract = state['contract'] if state else {}
     request = WorkRequest('implementer', root,
         receipts.digest(receipts.encoded(contract)),
-        tuple(contract.get('expectedCodeSurface', [])), tuple(contract.get('deliverables', [])),
+        tuple(contract.get('expectedCodeSurface', [])), _acceptance_references(contract),
         tuple(contract.get('validation', {}).get('baseline', [])), ('committed implementation delivery',))
     failed_candidate = state.get('run', {}).get('candidateValidation') if state else None
     if failed_candidate and failed_candidate['phase'] == 'failed':
@@ -401,6 +408,15 @@ def run_validation_step(locations: RunLocations) -> dict | None:
             result['diagnostics'] = [dict(code='CANDIDATE_VALIDATION_FAILED', message=json.dumps(failed_candidate['runs']))]
             return result
     pending = operation_path(root, task_id).exists()
+    if not pending and implementation_delivery(locations) is None and _committed_implementation(locations, state):
+        # A clean, committed change in scope is a delivery the tool can perform
+        # itself, so the agent needs no command beyond run (ADR decisions 6 and 14).
+        delivered = deliver_run_implementation(locations)
+        return envelope(task_id, str(locations.primary), step='implementation', outcome='progress',
+                        action='deliver', next_command=command_reference(
+                            ['cardine', 'run', task_id, '--project', str(locations.primary)],
+                            'Run the complete current validation command set'),
+                        evidence=[dict(kind='delivery', path=str(root), identity=str(delivered['commit']))])
     if not pending and implementation_delivery(locations) is None:
         return resolve_run(RunFacts(task_id, locations.primary, 'in_progress',
                            contract_ready=True, worktree_ready=True, implementation_work=request,
@@ -419,7 +435,7 @@ def run_validation_step(locations: RunLocations) -> dict | None:
     if not contract:
         contract = state['contract']
         request = WorkRequest('implementer', root, receipts.digest(receipts.encoded(contract)),
-            tuple(contract.get('expectedCodeSurface', [])), tuple(contract.get('deliverables', [])),
+            tuple(contract.get('expectedCodeSurface', [])), _acceptance_references(contract),
             tuple(contract['validation']['baseline']), ('committed implementation delivery',))
     passed = progress['phase'] == 'passed'
     from cardine.tasks.validation import host_observations_complete
@@ -574,7 +590,7 @@ def run_integration_step(locations: RunLocations, *, prepare=False) -> dict | No
     from cardine.lifecycle import receipts
     contract = state['contract']
     request = WorkRequest('implementer', locations.worktree, receipts.digest(receipts.encoded(contract)),
-        tuple(contract['expectedCodeSurface']), tuple(contract['deliverables']),
+        tuple(contract['expectedCodeSurface']), _acceptance_references(contract),
         tuple(contract['validation']['baseline']), ('repair candidate validation failure',))
     return envelope(task_id, str(root), step='implementation', outcome='iterate',
         action='abort-failed-candidate', work=request.as_json(),
@@ -588,3 +604,21 @@ def _candidate_finalize_next(locations):
         action='validate-candidate', next_command=command_reference(
             ['cardine', 'run', locations.task_id, '--project', str(locations.primary)],
             'Finalize the measured candidate'))
+
+
+def _acceptance_references(contract):
+    """Spike deliverables, or the record's criteria for a standard task."""
+    return tuple(contract.get('deliverables') or ()) or (contract['recordPath'] + '#acceptance-criteria',)
+
+
+def _committed_implementation(locations, state):
+    """A clean worktree whose commits since its base change a path Cardine does not own."""
+    from cardine.lifecycle.execution import _execution_location, _execution_owned_paths
+    from cardine.shared.git import git_output
+    root = locations.worktree
+    if state is None or state['status'] != 'in_progress' or git_output(root, 'status', '--porcelain'):
+        return False
+    base = str(_execution_location(root, locations.task_id, context=locations)['base_commit'])
+    owned = _execution_owned_paths(root, locations.task_id, context=locations)
+    changed = set(git_output(root, 'diff', '--name-only', base, 'HEAD').splitlines())
+    return bool(changed - owned)
diff --git a/src/cardine/tasks/creation.py b/src/cardine/tasks/creation.py
index 2b94954..2df3196 100644
--- a/src/cardine/tasks/creation.py
+++ b/src/cardine/tasks/creation.py
@@ -67,7 +67,7 @@ def create_task(project_root: Path, task_id: str, text: str, *, recover: bool =
                 intent = _load_intent(_intent_path(root, canonical))
                 name = str(record.relative_to(root))
                 proposal = intent['files'].get(name, {}).get('content')
-                if proposal is None or base64.b64decode(proposal) != text.encode('utf-8'):
+                if proposal is None or _proposal_text(base64.b64decode(proposal)) != _proposal_text(text.encode("utf-8")):
                     raise CardineError('changed creation input; replay requires the identical record')
                 replay_operation(root, canonical, kind='creation')
                 return {'id': canonical, 'record': name,
@@ -93,6 +93,7 @@ def create_task(project_root: Path, task_id: str, text: str, *, recover: bool =
                     raise CardineError('developer reauthorization required for existing task states')
                 authorize_project(root, accepted=observed_authority(root), new=True)
             require_authority(root)
+            text = _with_resolved_execution_contract(root, contract, text)
             write_operation(root, canonical, state, kind='creation',
                             files={str(record.relative_to(root)): text.encode('utf-8')})
             return {'id': canonical, 'record': str(record.relative_to(root)),
@@ -113,3 +114,18 @@ def validate_dependencies(root, task_id, contract):
                             stop_factory=lambda code, detail, **kwargs: CardineError(detail))
         except CardineError as error:
             raise CardineError(f"unknown or invalid dependency {dependency}: {error}") from error
+
+
+def _with_resolved_execution_contract(root, contract, text):
+    """Publish the record with its resolved execution block, so a worktree
+    prepared from the creation commit starts without a reconcile."""
+    from cardine.tasks.contract import contract_digest
+    from cardine.tasks.preflight import render_execution_contract
+    if contract_digest(text) is not None:
+        return text
+    return text.rstrip() + "\n\n" + render_execution_contract(root, contract["validation"]["baseline"]) + "\n"
+
+
+def _proposal_text(published: bytes) -> str:
+    """The proposal a published record came from, without its generated block."""
+    return published.decode("utf-8").split("\n\n## Execution contract — resolved\n", 1)[0].rstrip()
diff --git a/src/cardine/tasks/preflight.py b/src/cardine/tasks/preflight.py
index 4bb31a4..177b0ef 100644
--- a/src/cardine/tasks/preflight.py
+++ b/src/cardine/tasks/preflight.py
@@ -19,7 +19,12 @@ import re
 
 def execution_contract(project_root: Path, task_id: str) -> str:
     """Render the profile-derived execution block placed in a task at design time."""
-    commands = ", ".join(frozen_validation_commands(project_root, task_id)) or "none"
+    return render_execution_contract(project_root, frozen_validation_commands(project_root, task_id))
+
+
+def render_execution_contract(project_root: Path, baseline) -> str:
+    """Render the execution block for the given baseline validation IDs."""
+    commands = ", ".join(baseline) or "none"
     source = "docs/EXECUTION_EVIDENCE_PROFILE.md" if (project_root / "docs/EXECUTION_EVIDENCE_PROFILE.md").is_file() else ".cardine/project.json"
     return "\n".join((
         "## Execution contract — resolved",
diff --git a/tests/test_contract_snapshot_readers.py b/tests/test_contract_snapshot_readers.py
index a5e1943..66ea44d 100644
--- a/tests/test_contract_snapshot_readers.py
+++ b/tests/test_contract_snapshot_readers.py
@@ -102,7 +102,7 @@ class ContractSnapshotReadersTest(unittest.TestCase):
         from cardine.tasks.preflight import execution_contract, execution_preflight
         record = self.root / 'tasks/002.md'
         (self.root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_text('profile\n')
-        record.write_text(record.read_text() + execution_contract(self.root, '002') + '\n')
+        record.write_text(record.read_text().split('\n\n## Execution contract — resolved\n')[0] + '\n\n' + execution_contract(self.root, '002') + '\n')
         execution_preflight(self.root, '002')
         record.write_text(record.read_text() + '\nClass: spike\nReview: required\nDeliverable: docs/edited.md\n')
         execution_preflight(self.root, '002')
@@ -189,7 +189,7 @@ class ContractSnapshotReadersTest(unittest.TestCase):
         from cardine.tasks.recording import run_validation
         (self.root / 'docs/EXECUTION_EVIDENCE_PROFILE.md').write_text('profile\n')
         record = self.root / 'tasks/002.md'
-        record.write_text(record.read_text() + execution_contract(self.root, '002') + '\n')
+        record.write_text(record.read_text().split('\n\n## Execution contract — resolved\n')[0] + '\n\n' + execution_contract(self.root, '002') + '\n')
         before = frozen_validation_commands(self.root, '002')
         self.assertEqual(frozen_validation_commands(self.root, 'task-002'), before)
         self.assertEqual(execution_contract(self.root, 'task-002'), execution_contract(self.root, '002'))
diff --git a/tests/test_execution_start_fresh_task.py b/tests/test_execution_start_fresh_task.py
index 89bf605..dd9570f 100644
--- a/tests/test_execution_start_fresh_task.py
+++ b/tests/test_execution_start_fresh_task.py
@@ -100,7 +100,21 @@ class FreshTaskStartTest(unittest.TestCase):
             self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
         return result
 
+    def change_profile(self, worktree):
+        profile = worktree / "docs" / "EXECUTION_EVIDENCE_PROFILE.md"
+        profile.write_text(profile.read_text(encoding="utf-8") + "\nChanged after task creation.\n", encoding="utf-8")
+        self.git("add", "-A", cwd=worktree)
+        self.git("commit", "-q", "-m", "Change the execution profile", cwd=worktree)
+
+    def test_fresh_record_starts_without_reconcile(self):
+        self.assertIn("- Profile revision:", (self.project / "tasks" / "001.md").read_text(encoding="utf-8"))
+        prepared = json.loads(self.cardine("worktree", "prepare", "001", "--project", str(self.project),
+                                           "--format", "json").stdout)
+        started = self.cardine("execution", "start", "001", "--project", ".", cwd=Path(prepared["worktree"]))
+        self.assertTrue(json.loads(started.stdout)["started"])
+
     def test_reconciled_record_starts_and_run_continues(self):
+        self.change_profile(self.project)
         prepared = json.loads(self.cardine("worktree", "prepare", "001", "--project", str(self.project),
                                            "--format", "json").stdout)
         worktree = Path(prepared["worktree"])
@@ -130,6 +144,7 @@ class FreshTaskStartTest(unittest.TestCase):
         self.assertIn("already current", again.stdout)
 
     def test_interrupted_reconcile_converges_on_rerun(self):
+        self.change_profile(self.project)
         prepared = json.loads(self.cardine("worktree", "prepare", "001", "--project", str(self.project),
                                            "--format", "json").stdout)
         worktree = Path(prepared["worktree"])
diff --git a/tests/test_run_delivery_disposable.py b/tests/test_run_delivery_disposable.py
index 37fd4ae..031efc2 100644
--- a/tests/test_run_delivery_disposable.py
+++ b/tests/test_run_delivery_disposable.py
@@ -88,3 +88,91 @@ class DisposableDeliveryTest(unittest.TestCase):
 
 if __name__ == '__main__':
     unittest.main()
+
+
+INIT_RECORD = """# Task 001 — Document the defaults
+
+> **ID**: `001`
+> **Category**: Quick
+
+## Objective
+
+Document the defaults.
+
+## Acceptance Criteria
+
+- README.md lists the defaults.
+
+## Expected code surface
+
+- `README.md`
+
+## Dependencies
+
+None.
+
+## Validation
+
+- `whitespace`: `git diff --check HEAD~1`
+"""
+
+
+class InitializedProjectDeliveryTest(unittest.TestCase):
+    """A project from `init`, a task from `task new`, and an agent that only calls `run`."""
+
+    def test_quick_task_lands_through_run_alone(self):
+        import json, os, subprocess, sys, tempfile
+        from pathlib import Path
+        cardine = Path(__file__).resolve().parents[1] / 'bin' / 'cardine'
+        with tempfile.TemporaryDirectory() as temporary:
+            base = Path(temporary)
+            project, origin = base / 'project', base / 'origin.git'
+            for name in ('home', 'tmp', 'project'):
+                (base / name).mkdir()
+            env = {**os.environ, 'HOME': str(base / 'home'), 'TMPDIR': str(base / 'tmp'),
+                   'CARDINE_WORKTREE_ROOT': str(base / 'worktrees'),
+                   'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
+                   'GIT_AUTHOR_NAME': 'Init Test', 'GIT_AUTHOR_EMAIL': 'init@example.invalid',
+                   'GIT_COMMITTER_NAME': 'Init Test', 'GIT_COMMITTER_EMAIL': 'init@example.invalid'}
+
+            def call(*argv, cwd=project):
+                return subprocess.run(list(argv), cwd=cwd, env=env, text=True, capture_output=True, check=True).stdout
+
+            def commit(message, *paths, cwd=project):
+                call('git', 'add', *(paths or ('-A',)), cwd=cwd)
+                call('git', 'commit', '-q', '-m', message, cwd=cwd)
+
+            call('git', 'init', '-q', '--bare', '-b', 'main', str(origin), cwd=base)
+            call('git', 'init', '-q', '-b', 'main')
+            call('git', 'remote', 'add', 'origin', str(origin))
+            validation = base / 'validation.json'
+            validation.write_text(json.dumps({'commands': {'whitespace': 'git diff --check HEAD~1'},
+                'baseline': ['whitespace'], 'candidate': {'REUSE': [], 'BOUNDED': ['whitespace'],
+                                                          'FULL': ['whitespace']}}))
+            call(sys.executable, str(cardine), 'init', '--project', '.', '--apply', '--name', 'Example',
+                 '--slug', 'example', '--preset', 'lean', '--language', 'English',
+                 '--task-identity', 'opaque', '--validation', str(validation))
+            commit('Initialize Cardine')
+            record = base / 'proposal.md'
+            record.write_text(INIT_RECORD)
+            call(sys.executable, str(cardine), 'task', 'new', '001', '--quick', '--record', str(record),
+                 '--project', '.')
+            commit('Add task 001')
+            call('git', 'push', '-q', 'origin', 'main')
+            outcomes = []
+            for _ in range(10):
+                result = json.loads(call(sys.executable, str(cardine), 'run', '001', '--project', str(project)))
+                outcomes.append((result['step'], result['outcome']))
+                self.assertNotEqual(result['outcome'], 'blocked', result)
+                if result['outcome'] == 'done':
+                    break
+                self.assertEqual(result['next']['argv'][:2], ['cardine', 'run'], result)
+                work = result['work']
+                if work and work['role'] == 'implementer':
+                    worktree = Path(work['worktree'])
+                    readme = worktree / 'README.md'
+                    if 'Defaults' not in readme.read_text():
+                        readme.write_text(readme.read_text() + '\n## Defaults\n\n- `timeout`: 30 seconds.\n')
+                        commit('Document the defaults', 'README.md', cwd=worktree)
+            self.assertEqual(outcomes[-1], ('landing', 'done'), outcomes)
+            self.assertIn('## Defaults', call('git', '--git-dir', str(origin), 'show', 'main:README.md'))
diff --git a/tests/test_run_receipts.py b/tests/test_run_receipts.py
index 0227f34..3b69697 100644
--- a/tests/test_run_receipts.py
+++ b/tests/test_run_receipts.py
@@ -24,6 +24,13 @@ POINTS = ('before_intent', 'after_intent', 'before_staged_pair', 'after_staged_p
           'before_state_replace', 'after_state_replace', 'before_result_receipt', 'after_result_receipt')
 
 
+def proposal_of(record):
+    """The proposal part of a published record, before its resolved execution block."""
+    head, _, block = record.partition('\n\n## Execution contract — resolved\n')
+    assert '- Profile revision: `sha256:' in block
+    return head.rstrip()
+
+
 class RunReceiptsTest(unittest.TestCase):
     def setUp(self):
         self.temp = tempfile.TemporaryDirectory()
@@ -98,7 +105,7 @@ else:
                 self.assertEqual(state['transitions'], [])
                 if before is not None:
                     self.assertEqual(state, before)
-                self.assertEqual(self.record.read_text(), self.text)
+                self.assertEqual(proposal_of(self.record.read_text()), self.text.rstrip())
                 self.assertFalse(intent.exists())
                 self.assertEqual(list(self.root.rglob('*.stage')), [])
 
diff --git a/tests/test_task_creation.py b/tests/test_task_creation.py
index 5bddf17..069d1f6 100644
--- a/tests/test_task_creation.py
+++ b/tests/test_task_creation.py
@@ -22,6 +22,9 @@ from task_contract_support import contract_record, VALIDATION
 ROOT = Path(__file__).resolve().parents[1]
 
 
+from test_run_receipts import proposal_of
+
+
 class TaskCreationTest(unittest.TestCase):
     def setUp(self):
         self.temp = tempfile.TemporaryDirectory()
@@ -57,7 +60,7 @@ class TaskCreationTest(unittest.TestCase):
         before = self.state.read_bytes()
         write_project_config(self.root, 'governed', validation=deepcopy(VALIDATION))
         self.assertEqual(self.state.read_bytes(), before)
-        self.assertEqual(self.record.read_text(), self.text)
+        self.assertEqual(proposal_of(self.record.read_text()), self.text.rstrip())
         self.assertNotIn('Status:', self.record.read_text())
         self.assertEqual(load_task_status(self.root)['totals']['queued'], 1)
 
@@ -262,7 +265,7 @@ class TaskCreationTest(unittest.TestCase):
         result = create_task(self.root, 'm1-core-001', text)
         self.assertEqual(result['id'], 'M1-CORE-001')
         self.assertTrue((self.root / result['record']).is_relative_to(self.root / 'work/items'))
-        self.assertEqual((self.root / result['record']).read_text(), text)
+        self.assertEqual(proposal_of((self.root / result['record']).read_text()), text.rstrip())
         self.assertTrue((self.root / result['state']).exists())
 
 
```

## Prototype evidence

- On the prototype, `InitializedProjectDeliveryTest` passes. With `src/` reset to
  `f0d31ce` and the new test kept, it fails: `['cardine', 'execution'] !=
  ['cardine', 'run']` (the reconcile loop of defect 1).
- `python3 scripts/check_repository.py` passes.
- A parallel run of 37 modules (the repository guards plus every module that imports the
  changed code) reports `ran=602 total=2165 failures=0 errors=0`.
- A conversion rehearsal of the patched tree on `2734f3d`, run as the Conversion
  evidence criterion describes, returned `done` with no diagnostics. On the converted
  commit, `python3 scripts/check_repository.py` passed and `python3 scripts/run_tests.py
  --parallel` reported `OK workers=8 ran=2166 failures=0 errors=0 skipped=12`. Run the
  suite with the inherited environment: exporting the rehearsal `HOME`, `TMPDIR`, or
  `CARDINE_WORKTREE_ROOT` into it makes host and worktree-root tests fail.

## Acceptance Criteria

- [ ] The prototype diff is applied to the files under Relevant Files, and nothing
  else changes in them.
- [ ] `InitializedProjectDeliveryTest` fails when only its test file is applied to
  the base, and passes with the whole diff. The handoff records both result lines.
- [ ] Only the files under Relevant Files are edited, together with this task's own
  record and its archive, handoff, and state file. A test file outside that list may
  change only to update an expectation that this change made stale, without new
  behavior, and the handoff lists it. Any other file, or new behavior beyond this
  record, stops the task before editing it and names the file.
- [ ] **Conversion evidence.** The diff changes `task new` and the renderer that
  `cardine adopt` shares with `execution reconcile`, so the switch commit must still
  pass. Use a disposable clone of the implementation commit, with a disposable `HOME`,
  `TMPDIR`, and `CARDINE_WORKTREE_ROOT`. Run `python3 -m cardine.cli adopt --project
  <clone> --apply --name Cardine --slug cardine --language Italian --validation
  <file>` with `PYTHONPATH` set to the worktree's `src`. The validation file is
  `{"commands": {"repository-check": "python3 scripts/check_repository.py"},
  "baseline": ["repository-check"], "candidate": {"FULL": ["repository-check"]}}`.
  Then, in the clone, after `git add -A` and a commit, `python3
  scripts/check_repository.py` passes, and so does `python3 scripts/run_tests.py
  --parallel`. The handoff records both result lines. Never run `--apply` on this
  repository or on the task worktree.
- [ ] Every source and test file stays below 1,500 lines.
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
- [ ] `.meridian/` is unchanged, except `.meridian/tasks/188.json`, which only the
  installed `meridian task close 188` writes.
- [ ] **Clean-clone validation.** After the implementation commit, run
  `python3 scripts/run_tests.py --parallel --clean-clone` from the clean task
  worktree and record its result line in the handoff. The parallel suite
  reports coverage `total=2166`: the 2164 tests of `main` at `2734f3d` plus the two
  new tests.
- [ ] Every command under Validation passes.

## Relevant Files

| File | Role |
|------|------|
| `src/cardine/tasks/creation.py`, `src/cardine/tasks/preflight.py` | Publish the resolved block at creation; one renderer. |
| `src/cardine/lifecycle/engine.py` | Commit the start state; deliver committed work; acceptance references. |
| `tests/test_task_creation.py`, `tests/test_run_receipts.py`, `tests/test_contract_snapshot_readers.py` | Stale expectations about the published record. |
| `tests/test_execution_start_fresh_task.py` | A fresh task starts without reconcile; reconcile after a profile change. |
| `tests/test_run_delivery_disposable.py` | The end-to-end regression test. |

## Technical Context

- Authority: ADR decisions 6 (one lifecycle entry point), 12 (a recoverable code
  never stops the agent), 13 (gates read facts), and 14, rule 3 (the tool resolves
  what it knows).
- `_committed_implementation` reads only Git facts: a clean worktree, the base commit
  from `_execution_location`, and the paths `_execution_owned_paths` owns. It reads no
  record or handoff text.
- Every Git call in product code goes through `cardine.shared.git`
  (`test_command_context` enforces it).
- During development, run only what the change touches: `python3
  scripts/run_tests.py --parallel --module <name>` for a module, class, or test, and
  `python3 scripts/run_tests.py --parallel --last-failed` after a failed full run.
  Do not run `python3 -m unittest` directly, and run the full suite once, as the
  counted clean-clone validation.
- Run validation suites one at a time, never two in parallel. Redirect each suite's
  output to a log file and append its exit code, so the result survives a lost
  process handle. Report only exit codes read from a finished run.
- Close with `meridian worktree advance` from the primary checkout. Never call
  `meridian worktree evidence` directly: it requires the task worktree as current
  directory.
- Task 187 edits only `tests/test_host_permissions.py`; the two tasks share no file
  and can land in either order.
- Other tasks share this machine. Stop only your own processes, by process ID; never
  `pkill` test runs by pattern.

## Out of scope

The switch steps, which belong to the developer. The coordinator plans these separately:
- The reconcile path when the profile changes after the worktree exists: a reconcile
  in the worktree still leaves it dirty, and the next `run` stops with `BLOCKED
  WRONG_WORKTREE`.
- `cardine init` keeps its receipt under the system temporary directory, keyed by the
  project path. Deleting a project and running `init` again at the same path fails
  with `owned init output changed`.
- `cardine init` refuses an existing repository that contains any file it would
  write, such as `README.md`, and points to adoption. That is the intended behavior;
  only its documentation changes, in row D1 or D2.
- Finding 3 of the task 152 handoff (`developer reauthorization required` without a
  cause); the prototype run did not reach it.

## Dependencies

- **Depends on**: none
- **Blocks**: the switch (steps S1 to S7) and task 178

## Developer decisions given in advance

The developer records these decisions in the task contract, so that they hold however
the task is launched. None of these situations needs a new decision from the
developer. After fixing a failure, continue with revalidation in the same turn; do not
stop to report the fix.

- A required command that exits non-zero because of a precondition the agent can
  satisfy (command order, an uncommitted worktree, a missing argument): satisfy it and
  run the command again, once.
- A validation failure caused by this task's own changes, including a stale test
  expectation: fix it and revalidate, at most 3 counted attempts. A test that fails
  once and passes on an identical unchanged rerun is intermittent, recorded in the
  handoff, and does not count. Only after 3 counted failures stop with the failures
  summarized.
- A counted attempt is one run of the whole Validation section on a committed
  implementation that the agent considers complete. Test runs during implementation
  are development, not attempts.
- Before the first clean-clone, run `python3 scripts/check_repository.py` and one
  `python3 scripts/run_tests.py --parallel` with `--module` for each edited test module
  and for the repository guards: `test_module_inventory`, `test_layout`,
  `test_no_meridian_identifiers`, `test_text_gates`, `test_stop_registry`,
  `test_command_word`, `test_command_context`, `test_product_prose_readers`, and
  `test_run_end_to_end.ReplayInventoryTest`.
- Let a started clean-clone finish. After a failed clean-clone, fix, commit, and run
  `--last-failed` plus a `--module` run for each module the fix touched before the
  next clean-clone.
- A test outside the files this record lists that inventories what the repository
  contains and fails only because this task added an item: add that one item and list
  the file in the handoff. This is not a change of scope. Removing an item, or
  widening a pattern beyond the new item, is.
- Before stopping for a change of scope, finish everything else, commit it, and run
  the repository check and the affected tests, so that one stop names every file
  needed.
- If the conversion evidence fails, first check whether this task's diff causes the
  failure. If it does, fix it within the listed files. If it does not, the failure is
  a change of scope: report the command, its output, and the file it names.
- A `BLOCKED <CODE>` from a Meridian command whose entry in
  `capabilities/stop-codes-v1.json` of the primary checkout's `main` has
  `human_decision: false`: run the command the stop names, once. If it stops again
  with the same code, stop.
- The deny list, `RULE_CONFLICT`, every guardrail, and a change of scope remain stops.

## Validation

- `meridian profile doctor meridian-self-hosting --project .`
- `meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting`
- `python3 scripts/run_tests.py --parallel --module test_run_delivery_disposable`
- `python3 scripts/run_tests.py --parallel --clean-clone`
- `git diff --check`

The clean-clone run executes `scripts/check_repository.py` and the parallel suite on a
clone of the committed HEAD, so the task does not run them again in the worktree as
counted validation.

## Completion evidence

The prototype was applied and validated as recorded in `tasks/handoffs/188.md`.
