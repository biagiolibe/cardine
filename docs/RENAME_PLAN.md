# Rename plan — ADR work item 5a

## Contract and baseline

This plan covers only work item 5a of `docs/ADR_CARDINE_1_0.md`: renaming code
identifiers from Meridian to Cardine, under decisions 1 and 8. Task 040 renames
nothing. It inventories every identifier, classifies each occurrence, lists the
readers that must survive on this repository's frozen surfaces, and orders the
rename tasks. Work items 5b, 6, and 10 are not planned here; the final section
names the choices in this plan that would make them harder.

Baseline: commit `fcdbb0e8acfe84c388bb70398c553b16eb004849`, `main` on
2026-10-19, with 501 tracked files. Work item 4 is fully integrated: tasks
031–039 are `[x]` in `PROJECT_PLAN.md`. Nothing in this plan belongs to
item 4 except the mechanisms it left on purpose (the empty migration chain and
`migrations/README.md`).

### How to regenerate the inventory

```bash
git ls-files | wc -l
git ls-files | grep -i meridian
EXCL=(':!tasks/done' ':!tasks/handoffs' ':!CHANGELOG.md'       ':!tasks/040-plan-code-identifier-rename.md' ':!tasks/041-plan-single-workflow.md')
for p in 'MERIDIAN_[A-Z]*' '\.meridian/' 'meridian worktree' 'meridian-journal'; do
  printf '%s files=%s lines=%s
' "$p"     "$(git grep -lI "$p" -- . "${EXCL[@]}" | wc -l)"     "$(git grep -hI  "$p" -- . "${EXCL[@]}" | wc -l)"
done
git grep -nI -i 'meridian' -- <path>      # every occurrence in one file
```

The task record quotes four figures from the same commands. At the baseline the
loop above (which also excludes `tasks/040-*` and `tasks/041-*`, because those
two records quote the identifiers) reproduces them as follows:

| Pattern | Task record (files / lines) | Reproduced (files / lines) |
|---|---|---|
| `MERIDIAN_[A-Z]*` | 38 / 152 | 38 / 152 |
| `\.meridian/` | 108 / 354 | 108 / 357 |
| `meridian worktree` | 56 / 246 | 56 / 246 |
| `meridian-journal` | 5 / 14 | 5 / 14 |

The task record's "occurrences" are matching lines, not matches. Three of four
reproduce exactly; `.meridian/` differs by three lines. The tables below count
matches (case-insensitive `meridian` tokens, below), so their totals are larger.

### Counting rule

Every case-insensitive `meridian` token in a tracked text file is one
occurrence. The token is the maximal run of letters, digits, `_`, `.`, `/`, `:`,
`\`, and `-` around it, and the first matching rule below assigns its class:

1. contains `MERIDIAN:` — marker;
2. contains `MERIDIAN_<NAME>` — environment name;
3. `meridian-journal`, `meridian-integration`, `meridian-worktrees` (outside
   Codex permission lines), `meridian_shared_worktrees` — Git-internal;
4. `meridian-worktrees` on a Codex permission line — Codex profile;
5. `.meridian/worktrees`, `meridian/config.json` — worktree root and user config;
6. `.meridian-*`, `.meridian.bak`, `meridian-<purpose>-` temporary prefixes —
   backup and temporary names;
7. `.meridian/` or `.meridian` — project directory;
8. `bin/meridian`, `scripts/meridian.py` — executable paths;
9. `MeridianError`, `MeridianStop`, `MeridianArgumentParser`; other
   `Meridian<Name>` classes; `meridian_cli_support`, `test_meridian_*`,
   `meridian_root_*`, test names containing `meridian`; the `import meridian`
   adapter alias — code names;
10. `meridian-lean-delivery`, `meridian-governed-sdd`, `commands/meridian-*`,
    `/meridian-*`, `meridian.rules` — skill, command, and rules file names;
11. `meridian-self-hosting` — profile id;
12. `biagiolibe/meridian`, `meridian.local`, `extraKnownMarketplaces`,
    `~/.local/share/meridian` and similar — repository, plugin, and install
    locations;
13. `--meridian`, `--meridian-root` — options;
14. lowercase bare `meridian` — the command word;
15. any other capitalized form — the product name in prose and strings.

The tables are generated from this rule at the baseline commit. A task that
implements a class re-runs the rule over its files: the first rename step of
each task is to confirm its file list against the working tree.


## What 5a renames, and what it must not

### Rules

1. **No alias.** After 5a no product command, environment variable, path, or
   Git-internal file accepts a Meridian name as input for its own work
   (decision 1). Each rename task adds a test that the old name is *ignored*.
2. **The Meridian names that remain are of three kinds.** Frozen files that
   the installed Meridian owns (group 3); history (group 4); and the single
   read-only module of group 5. Nothing else keeps a Meridian name except the
   group 2 text that waits for 5b.
3. **Markers stay in 5a.** `MERIDIAN:BEGIN` and `MERIDIAN:END` are group 2.
   Because the installed Meridian and the renamed product still share them
   until 5b, the renamed product must not run `setup --apply` against the
   maintainer's real home directory before item 10. Tests use a temporary home.
4. **Every task lands green.** Each rename task ends with the full test suite,
   `python3 scripts/check_repository.py`, and the installed-Meridian
   validation of this repository passing, not only its own tests.
5. **Group 1 code that must match group 2 text keeps its Meridian name until
   5b.** A string that a template, skill, command, rules file, or plugin
   manifest also spells, and that a test or probe compares byte for byte, is
   group 2. A string that the product only emits (a resume command, a
   generated allowlist) is group 1; a test that compares it with group 2 text
   normalizes the program word until 5b.
6. **A name is decided once.** Where a persisted name is shared by two things
   that are checked together (the Codex profile `meridian-worktrees` and the
   `# MERIDIAN:BEGIN worktree-permissions v1` marker around it), both move in
   the same work item. That item is **5b**, because ownership repair
   (`_codex_expected_profile`, `_codex_markers_intact`) compares the whole
   block. Both are group 2.

### Current and new names

| Class | Current | New | Notes |
|---|---|---|---|
| Command | `meridian` | `cardine` | `pyproject.toml` already registers `cardine = "cardine.cli:main"`; no `meridian` console script exists. |
| Wrapper | `bin/meridian` | `bin/cardine` | Removal of the wrapper belongs to decision 9, not 5a. |
| Adapter | `scripts/meridian.py` | `scripts/cardine_cli.py` | **Not** `scripts/cardine.py`: the tests and `scripts/check_repository.py` put `scripts/` on `sys.path`, and a top-level `cardine.py` there would shadow the `cardine` package. The tests import it as `cardine_cli`. |
| Environment | `MERIDIAN_ROOT`, `MERIDIAN_WORKTREE_ROOT`, `MERIDIAN_TEST_SHARD`, `MERIDIAN_FAILURE_VISIBILITY_PROBE` | `CARDINE_ROOT`, `CARDINE_WORKTREE_ROOT`, `CARDINE_TEST_SHARD`, `CARDINE_FAILURE_VISIBILITY_PROBE` | `MERIDIAN_BIN` is a shell variable inside the three hook scripts, not an environment contract; it becomes `CARDINE_BIN` only in `hooks/stop-audit.sh`. `MERIDIAN_SESSION_NOT_FOUND` is an AppleScript error token in `console/launch.py`, not a variable; it becomes `CARDINE_SESSION_NOT_FOUND`. `MERIDIAN_SELF_HOSTING_PROFILE` appears only as a document name (group 4). |
| Options | `--meridian-root`, `--meridian` | `--cardine-root`, `--cardine` | `scripts/upgrade_project.sh`, `scripts/align_queue.py`. |
| Project directory | `.meridian/` | `.cardine/` | Every file keeps its name: `manifest.json`, `baselines/`, `tasks/<id>.json`, `task-identity.json`, `project.json`, `candidate-validation.json`, `execution-evidence.json`, `flow-targets.json`, `context-size.json`, `probes/`, `evidence/`. |
| Profile id | `meridian-self-hosting` | `cardine-self-hosting` | Product catalog, `STRICT_DIGEST_PROFILES`, catalog probe paths. The frozen manifest keeps its own profile name. |
| Git-internal | `.git/meridian-journal.jsonl`, `.git/meridian-journal.1.jsonl`, `.git/meridian-integration.lock`, `.git/meridian-integration.json`, `.git/meridian-worktrees/` | `cardine-journal.jsonl`, `cardine-journal.1.jsonl`, `cardine-integration.lock`, `cardine-integration.json`, `cardine-worktrees/` | The `meridian_shared_worktrees` context variable becomes `cardine_shared_worktrees`. |
| Worktree root | `~/.meridian/worktrees` | `~/.cardine/worktrees` | |
| User configuration | `$XDG_CONFIG_HOME/meridian/config.json` (default `~/.config/meridian/config.json`) | `cardine/config.json` | Key `worktreeRoot` is unchanged. |
| Backups and temporaries | `.meridian-<kind>.bak`, `.meridian.bak`, `.meridian-repair.bak`, `.meridian-rules-*`, `.meridian-codex-probe-*`, `meridian-merge-`, `meridian-capped-`, `meridian-self-update-`, `meridian-tests-`, `meridian-clean-clone-`, `meridian-release-`, `meridian-eval-`, `meridian-upgrade-<tag>` | the same with `cardine` | |
| Code names | `MeridianError`, `MeridianStop`, `MeridianArgumentParser`, `MeridianCliFixtureMixin`, `MeridianCliTest`, `meridian_cli_support`, `test_meridian_*.py`, `meridian_root_state`, `meridian_root_value` | `CardineError`, `CardineStop`, `CardineArgumentParser`, `CardineCliFixtureMixin`, `CardineCliTest`, `cardine_cli_support`, `test_cardine_*.py`, `cardine_root_state`, `cardine_root_value` | |
| Distribution identifiers in code | `biagiolibe/meridian` (latest-release URL), `User-Agent: meridian/<version>` | `biagiolibe/cardine`, `cardine/<version>` | Identifiers only. Replacing GitHub release polling with the installer-aware update of decision 9 is not 5a. |
| Strings | "Meridian" in messages, help text, `$id` `https://meridian.local/schemas/…`, `pyproject.toml` description | "Cardine", `https://cardine.local/schemas/…` | The `setup --check` keys that the frozen hook parses (`codex-profile`, `codex-detail`, `codex-root-mismatch`) do not change. |

Names that do **not** change in 5a: `MERIDIAN:BEGIN` / `MERIDIAN:END` and
`MERIDIAN:CLAUDE-AGENTS-POINTER`; the `.codex/rules/meridian.rules` target
path; `skills/meridian-*`, `commands/meridian-*`; the plugin and marketplace
names; the Codex profile `meridian-worktrees` with its managed block; the
`~/.codex/skills/meridian-*` links; every file under `.meridian/` and every
group 3 file; all group 4 text. Hook scripts `hooks/queue-briefing.sh` and
`hooks/read-guard.sh` keep `MERIDIAN_BIN` and `bin/meridian`.


## Classification

### Groups

| Group | Rule applied | Paths |
|---|---|---|
| 1 — renamed in 5a | Product code, product data, tests, tools, and evals whose identifier is not shared with group 2 text or group 3 files | `src/`, `scripts/`, `bin/`, `tests/` (except the reader lines of group 3), `evals/`, `capabilities/stop-codes-v1.json`, `capabilities/catalog-v1.json`, `schemas/*.json`, `pyproject.toml`, `hooks/stop-audit.sh`, `.codex/rules/local.rules` (its `scripts/meridian.py` lines only) |
| 2 — renamed in 5b | Markers, template text, skills, slash commands, and every string a group 2 file also spells | `templates/**`, `skills/**`, `commands/**`, `.claude-plugin/**`, `capabilities/markers-v1.json`, `capabilities/marker-baselines.json`, `capabilities/retired-text-v1.json`, marker and Codex-profile constants in code, the skill glob and skill names in `hosts/skills.py`, the `.codex/rules/meridian.rules` target path, the `setup.py` execpolicy probe, the skill and command paths in `scripts/check_repository.py`, and the plugin and marketplace detection in `hosts/claude.py` and `release/update.py` |
| 3 — frozen until item 10 | Every path that `.meridian/manifest.json` lists in `managedFiles` or in a `managedSurface`, plus all of `.meridian/` | see the next section |
| 4 — historical and kept | History and Meridian-era documents that describe Meridian, not the product being built; edited only where a test executes or compares them (see exceptions) | `CHANGELOG.md`, `changelog.d/**`, `releases/**`, `tasks/done/**`, `tasks/handoffs/**`, `docs/ADR_*.md`, the Meridian design documents and guides, `docs/assets/**`, `docs/examples/**` (see exceptions), `README.md`, `CONTRIBUTING.md`, `WORKFLOW_GUIDE.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.github/**`, `migrations/README.md`, `PROJECT_PLAN.md`, `tasks/QUEUE*.md`, `tasks/TASK_BLUEPRINT.md`, `tasks/04*.md`, release-archive fixtures under `tests/fixtures/release-*` |
| 5 — read-only Meridian reader | One new module, `src/cardine/legacy/meridian_installation.py` (section "Group 5") | none today: the module is created by the first rename task |

Group 4 includes the living guides (`README.md`, `docs/QUICKSTART.md`,
`docs/HOW_TO_UPGRADE.md`, `docs/HOST_CAPABILITY_CONTRACT.md`, and their
neighbours). They describe Meridian's installation and commands. Work item 11
replaces them; it does not rename them, so renaming sentences in them now would
produce documents that are neither Meridian's nor Cardine's. The tests that
assert on them are handled one by one in the task sequence.

The Meridian design documents in group 4 are `docs/AGENT_OPERATIONS.md`,
`CLEAN_INSTALL_VERIFICATION.md`, `CONSUMER_PROFILES.md`,
`CONSUMER_ROUTER_ADOPTION_PLAYBOOK.md`, `DISTRIBUTION_AND_UPDATE_DESIGN.md`,
`GOVERNED_WORKFLOW.md`, `HOST_CAPABILITY_CONTRACT.md`, `HOW_TO_UPGRADE.md`,
`MERIDIAN_SELF_HOSTING_PROFILE.md`, `MODULE_SPLIT_PLAN.md`,
`PLATFORM_SUPPORT.md`, `PROJECT_DECLARATION.md`, `PUBLIC_SURFACE.md`,
`QUICKSTART.md`, and `TASK_IDENTITY_POLICY.md`.

**Exceptions inside group 4.** Two files are read or executed by a test as a
contract of the product, so their identifiers are group 1 and the rename tasks
edit them: `docs/PUBLIC_SURFACE.md` (its command table is compared with the
parser) and `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md` (a test executes it).

### Findings that extend or correct the task's definitions

1. **`docs/WORKTREE_LIFECYCLE.md` is group 3.** `managedFiles` lists ten
   paths, not the nine in the task's technical context. The tenth is
   `docs/WORKTREE_LIFECYCLE.md`.
2. **`hooks/stop-audit.sh` is not frozen.** `hooks/hooks.json` wires it, but the
   manifest lists only `hooks/hooks.json`, `hooks/queue-briefing.sh`, and
   `hooks/read-guard.sh` as shared-source surfaces. It is group 1.
3. **Installation files outside the manifest.** `.codex/rules/local.rules`
   allows the installed `meridian worktree` commands for this repository's
   lifecycle, and `tasks/QUEUE.md`, `PROJECT_PLAN.md`, and
   `tasks/TASK_BLUEPRINT.md` are written by the installed lifecycle. They are
   not in the manifest, so the task's definition of group 3 does not cover
   them. The rule this plan applies, as an extension: *a file outside the
   manifest that configures or records the installed Meridian's operation on
   this repository stays unchanged until item 10.* The `meridian worktree` line
   of `.codex/rules/local.rules` is therefore group 3 and its three
   `scripts/meridian.py` lines are group 1 (R5 deletes them; see R5); the three
   governance files are group 4, because branches never edit them.
4. **`check_language_policy` does not read a group 3 file.** It reads only
   files under `templates/`, `commands/meridian-task.md`, and two files under
   `skills/`; all are group 2. The task's list of readers is corrected in the
   reader table below.
5. **`generate-entry-routers --check` does not read the root `CLAUDE.md` or
   `AGENTS.md`.** With `--mode` (as `check_generated_templates` calls it) it
   compares only `templates/workflows/<mode>/AGENTS.md` and `CLAUDE.md`.
6. **Hooks fall back to `command -v meridian`.** On the maintainer's machine
   that resolves the installed Meridian; in CI it resolves nothing. After 5a no
   test may rely on that fallback (reader table, row 9).

### Occurrences by class and group

Each cell is occurrences / files. Group 4 aggregates `tasks/done/**` (39
files), `tasks/handoffs/**` (42 files), `releases/**` and `changelog.d/**` (30
files), and `.meridian/baselines/**` is counted in group 3.


| Class | Group 1 | Group 2 | Group 3 | Group 4 | Total |
|---|---:|---:|---:|---:|---:|
| Executable and script paths | 69 / 30 | 9 / 4 | 8 / 4 | 318 / 85 | 404 |
| Command word `meridian` | 493 / 93 | 261 / 39 | 139 / 18 | 499 / 70 | 1392 |
| `MERIDIAN_*` names | 85 / 24 | 8 / 1 | 38 / 3 | 68 / 23 | 199 |
| `.meridian/` directory | 254 / 61 | 31 / 19 | 45 / 13 | 165 / 51 | 495 |
| Git-internal files | 27 / 9 | 1 / 1 | 2 / 1 | 5 / 4 | 35 |
| Worktree root and user configuration | 9 / 5 | 2 / 2 | 5 / 2 | 6 / 4 | 22 |
| Code names | 677 / 106 | 0 / 0 | 3 / 1 | 670 / 29 | 1350 |
| Product name in strings | 103 / 57 | 51 / 20 | 39 / 14 | 282 / 68 | 475 |
| Other prose and fixture strings | 25 / 16 | 4 / 4 | 6 / 6 | 81 / 31 | 116 |
| `MERIDIAN:` markers | 0 / 0 | 450 / 64 | 72 / 15 | 20 / 8 | 542 |
| Skill, command, and rules file names | 3 / 1 | 51 / 21 | 2 / 1 | 45 / 14 | 101 |
| `meridian-self-hosting` profile id | 11 / 7 | 0 / 0 | 33 / 6 | 171 / 75 | 215 |
| Codex `meridian-worktrees` profile | 0 / 0 | 26 / 6 | 0 / 0 | 0 / 0 | 26 |
| Repository, plugin, and install locations | 20 / 15 | 1 / 1 | 0 / 0 | 49 / 16 | 70 |
| Backup and temporary names | 29 / 13 | 3 / 1 | 0 / 0 | 15 / 6 | 47 |
| Options named after the product | 6 / 2 | 0 / 0 | 0 / 0 | 8 / 1 | 14 |
| **All classes** | 1811 | 898 | 392 | 2402 | 5503 |


Group 3 counts include the lines of group 1 files that read a group 3 path on
purpose (listed in the reader table); they are classified with the path they
read.


## Identifier classes


### 1. The `meridian` command, `bin/meridian`, `scripts/meridian.py`, and entry points

**Current → new name.** `meridian` → `cardine`; `bin/meridian` → `bin/cardine`; `scripts/meridian.py` → `scripts/cardine_cli.py`; `--meridian` → `--cardine`; `--meridian-root` → `--cardine-root`.

`pyproject.toml` declares the only console script, `cardine`, so the entry point
needs no change. What 5a renames is the wrapper, the adapter module, every place
that prints or runs the command, and the generated allowlists. Paths that carry
the name: `bin/meridian`, `scripts/meridian.py`, `commands/meridian-adopt.md`,
`commands/meridian-audit.md`, `commands/meridian-init.md`,
`commands/meridian-task.md`, `commands/meridian-upgrade.md`,
`.codex/rules/meridian.rules`, and `templates/workflows/*/.codex/rules/meridian.rules`.

Executable and script paths (`bin/meridian`, `scripts/meridian.py`):

- Group 1 (renamed in 5a): 30 files, 69 occurrences. `.codex/rules/local.rules` (3), `docs/PUBLIC_SURFACE.md` (1), `hooks/stop-audit.sh` (2), `scripts/align_queue.py` (1), `scripts/check_repository.py` (2), `scripts/release.py` (1), `src/cardine/hosts/claude.py` (19), `tests/fixtures/module_split_baseline.json` (1), `tests/meridian_cli_support.py` (1), `tests/stop_recovery_support.py` (1), `tests/test_authority_excerpt.py` (1), `tests/test_cardine_cli.py` (3), `tests/test_check_repository.py` (6), `tests/test_cli_install.py` (2), `tests/test_codex_read_guard.py` (1), `tests/test_codex_worktree_hooks.py` (1), `tests/test_context_size.py` (1), `tests/test_execution_boundaries.py` (2), `tests/test_host_worktree_setup.py` (5), `tests/test_integration_projections.py` (1), `tests/test_machine_task_state.py` (1), `tests/test_marker_structure_audit.py` (1), `tests/test_module_inventory.py` (2), `tests/test_release.py` (2), `tests/test_review_verdict.py` (1), `tests/test_stop_audit.py` (1), `tests/test_task_integration_state.py` (1), `tests/test_task_state_import.py` (1), `tests/test_worktree_checkout.py` (2), `tests/test_worktree_cleanup.py` (2).
- Group 2 (renamed in 5b): 4 files, 9 occurrences. `commands/meridian-audit.md` (1), `commands/meridian-init.md` (2), `commands/meridian-upgrade.md` (3), `skills/meridian-governed-sdd-claude-code/SKILL.md` (3).
- Group 3 (frozen until item 10): 4 files, 8 occurrences. `hooks/queue-briefing.sh` (2), `hooks/read-guard.sh` (2), `scripts/check_repository.py` (1), `tests/test_queue_briefing.py` (3).
- Group 4 (historical, kept): 85 files, 318 occurrences. `CHANGELOG.md` (4), `CONTRIBUTING.md` (2), `PROJECT_PLAN.md` (1), `docs/ADR_CARDINE_1_0.md` (2), `docs/ADR_PUBLIC_SURFACE_AND_STABILITY.md` (1), `docs/ADR_STOPS_AND_DENIALS.md` (1), `docs/AGENT_OPERATIONS.md` (2), `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (3), `docs/HOST_CAPABILITY_CONTRACT.md` (6), `docs/HOW_TO_UPGRADE.md` (6), `docs/MODULE_SPLIT_PLAN.md` (10), `docs/QUICKSTART.md` (2), `tasks/040-plan-code-identifier-rename.md` (2), `tasks/QUEUE_ARCHIVE.md` (1); `tasks/done/**` (36 files, 151); `tasks/handoffs/**` (35 files, 124).

The command word (`meridian` as an invoked program, `prog="meridian"`, resume
commands, allowlist and rules entries, stop-code resume templates):

- Group 1 (renamed in 5a): 93 files, 493 occurrences. `README.md` (2), `capabilities/stop-codes-v1.json` (135), `docs/PUBLIC_SURFACE.md` (62), `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md` (9), `evals/lib/lean-project.sh` (1), `evals/scenarios/governed-remediation-completes/setup.sh` (3), `hooks/stop-audit.sh` (1), `scripts/align_queue.py` (5), `scripts/check_repository.py` (5), `scripts/codex_read_guard.py` (2), `scripts/release.py` (1), `scripts/upgrade_project.sh` (8), `src/cardine/cli.py` (4), `src/cardine/console/models.py` (2), `src/cardine/hosts/claude.py` (19), `src/cardine/hosts/codex.py` (6), `src/cardine/integration/merge.py` (2), `src/cardine/integration/projections.py` (1), `src/cardine/lifecycle/closure.py` (2), `src/cardine/lifecycle/execution.py` (1), `src/cardine/release/update.py` (3), `src/cardine/shared/context.py` (1), `src/cardine/tasks/contract.py` (1), `src/cardine/tasks/preflight.py` (2), `src/cardine/tasks/recording.py` (1), `src/cardine/tasks/transitions.py` (4), `src/cardine/templates/audit.py` (1), `src/cardine/templates/catalog.py` (1), `src/cardine/templates/manifest.py` (1), `src/cardine/templates/marker_audit.py` (3), `src/cardine/templates/marker_history.py` (1), `src/cardine/templates/markers.py` (1), `src/cardine/templates/merge.py` (1), `src/cardine/worktree/checkout.py` (4), `src/cardine/worktree/closure_status.py` (2), `tests/console_support.py` (1), `tests/fixtures/task-blueprint-v15.md` (7), `tests/meridian_cli_support.py` (8), `tests/stop_recovery_support.py` (1), `tests/synthetic_upgrade_support.py` (1), `tests/test_authority_excerpt.py` (4), `tests/test_cardine_cli.py` (2), `tests/test_check_repository.py` (2), `tests/test_ci_evidence.py` (1), `tests/test_cli_install.py` (3), `tests/test_codex_read_guard.py` (2), `tests/test_codex_rules.py` (18), `tests/test_codex_user_rules.py` (8), `tests/test_codex_worktree_hooks.py` (2), `tests/test_console_closure.py` (2), `tests/test_console_snapshot.py` (1), `tests/test_console_states.py` (1), `tests/test_context_size.py` (1), `tests/test_execution_boundaries.py` (3), `tests/test_execution_evidence.py` (22), `tests/test_host_codex_access.py` (4), `tests/test_host_codex_repair.py` (1), `tests/test_host_worktree_setup.py` (10), `tests/test_integration_projections.py` (1), `tests/test_launcher_task_audit.py` (1), `tests/test_lifecycle_journal_flow.py` (2), `tests/test_machine_task_state.py` (2), `tests/test_marker_structure_audit.py` (1), `tests/test_meridian_adoption_audit.py` (1), `tests/test_meridian_cli_entry.py` (1), `tests/test_meridian_manifest_protocol.py` (1), `tests/test_meridian_migration_retirement.py` (1), `tests/test_meridian_upgrade_lifecycle.py` (7), `tests/test_meridian_upgrade_merge.py` (2), `tests/test_prepare_release.py` (1), `tests/test_public_surface.py` (5), `tests/test_queue_archival_state.py` (1), `tests/test_queue_briefing.py` (1), `tests/test_read_guard.py` (2), `tests/test_release.py` (3), `tests/test_release_self_check.py` (3), `tests/test_review_verdict.py` (1), `tests/test_self_update.py` (4), `tests/test_stop_audit.py` (3), `tests/test_task_close.py` (2), `tests/test_task_integration_state.py` (5), `tests/test_task_state_import.py` (1), `tests/test_task_state_lookups.py` (1), `tests/test_template_manifest.py` (2), `tests/test_template_marker_heading.py` (6), `tests/test_template_surface_upgrade.py` (1), `tests/test_usage_report.py` (8), `tests/test_validation_evidence.py` (1), `tests/test_worktree_checkout.py` (4), `tests/test_worktree_cleanup.py` (1), `tests/test_worktree_lifecycle.py` (12), `tests/test_worktree_paths.py` (1), `tests/worktree_support.py` (1).
- Group 2 (renamed in 5b): 39 files, 261 occurrences. `.claude-plugin/marketplace.json` (2), `.claude-plugin/plugin.json` (1), `commands/meridian-audit.md` (3), `commands/meridian-init.md` (1), `commands/meridian-task.md` (1), `skills/meridian-governed-sdd-claude-code/SKILL.md` (11), `skills/meridian-governed-sdd/SKILL.md` (12), `skills/meridian-lean-delivery-claude-code/SKILL.md` (5), `skills/meridian-lean-delivery/SKILL.md` (5), `src/cardine/hosts/claude.py` (1), `src/cardine/hosts/setup.py` (1), `src/cardine/release/update.py` (1), `templates/base/tasks/QUEUE.md` (1), `templates/workflows/governed-sdd/.codex/hooks.json` (2), `templates/workflows/governed-sdd/.codex/rules/meridian.rules` (6), `templates/workflows/governed-sdd/PROJECT_WORKFLOW.md` (37), `templates/workflows/governed-sdd/docs/AUDIT_PROMPT_READ_ONLY.md` (7), `templates/workflows/governed-sdd/docs/CODE_REVIEW_PROMPT.md` (5), `templates/workflows/governed-sdd/docs/COMPLETION_REPORT_TEMPLATE.md` (4), `templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md` (6), `templates/workflows/governed-sdd/docs/EXECUTION_EVIDENCE_PROFILE.md` (1), `templates/workflows/governed-sdd/docs/LIFECYCLE_ORCHESTRATION.md` (8), `templates/workflows/governed-sdd/docs/OPERATOR_PROMPTS.md` (9), `templates/workflows/governed-sdd/docs/PULL_REQUEST_POLICY.md` (6), `templates/workflows/governed-sdd/docs/REVIEW_RECORD_TEMPLATE.md` (3), `templates/workflows/governed-sdd/docs/WORKTREE_LIFECYCLE.md` (12), `templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md` (18), `templates/workflows/governed-sdd/docs/workflows/LIFECYCLE.md` (2), `templates/workflows/governed-sdd/docs/workflows/REMEDIATION.md` (7), `templates/workflows/governed-sdd/docs/workflows/REVIEW.md` (13), `templates/workflows/governed-sdd/tasks/QUEUE.md` (2), `templates/workflows/governed-sdd/tasks/TASK_BLUEPRINT.md` (11), `templates/workflows/lean-delivery/.codex/hooks.json` (2), `templates/workflows/lean-delivery/.codex/rules/meridian.rules` (6), `templates/workflows/lean-delivery/AGENTS.md` (8), `templates/workflows/lean-delivery/CLAUDE.md` (8), `templates/workflows/lean-delivery/PROJECT_WORKFLOW.md` (21), `templates/workflows/lean-delivery/docs/CONTEXT_BUDGET_POLICY.md` (1), `templates/workflows/lean-delivery/docs/WORKTREE_LIFECYCLE.md` (11).
- Group 3 (frozen until item 10): 18 files, 139 occurrences. `.codex/hooks.json` (2), `.codex/rules/local.rules` (2), `.codex/rules/meridian.rules` (6), `.meridian/baselines/1.4.0/.codex/hooks.json` (2), `.meridian/baselines/1.4.0/.codex/rules/meridian.rules` (6), `.meridian/baselines/1.4.0/AGENTS.md` (8), `.meridian/baselines/1.4.0/CLAUDE.md` (8), `.meridian/baselines/1.4.0/PROJECT_WORKFLOW.md` (19), `.meridian/baselines/1.4.0/docs/CONTEXT_BUDGET_POLICY.md` (1), `.meridian/baselines/1.4.0/docs/WORKTREE_LIFECYCLE.md` (11), `AGENTS.md` (8), `CLAUDE.md` (8), `PROJECT_WORKFLOW.md` (19), `docs/CONTEXT_BUDGET_POLICY.md` (1), `docs/WORKTREE_LIFECYCLE.md` (32), `hooks/queue-briefing.sh` (2), `hooks/read-guard.sh` (3), `tests/test_codex_worktree_hooks.py` (1).
- Group 4 (historical, kept): 70 files, 499 occurrences. `.github/ISSUE_TEMPLATE/bug_report.md` (1), `CHANGELOG.md` (156), `CONTRIBUTING.md` (3), `README.md` (8), `SECURITY.md` (1), `docs/ADR_CAPABILITY_MOVE_AND_BOOTSTRAP_ROUTER.md` (1), `docs/ADR_CARDINE_1_0.md` (4), `docs/ADR_MACHINE_TASK_STATE.md` (17), `docs/ADR_PUBLIC_SURFACE_AND_STABILITY.md` (3), `docs/ADR_SHARED_GENERATED_ENTRY_ROUTERS.md` (1), `docs/ADR_STOPS_AND_DENIALS.md` (4), `docs/AGENT_OPERATIONS.md` (14), `docs/CLEAN_INSTALL_VERIFICATION.md` (32), `docs/CONSUMER_PROFILES.md` (5), `docs/CONSUMER_ROUTER_ADOPTION_PLAYBOOK.md` (4), `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (22), `docs/GOVERNED_WORKFLOW.md` (6), `docs/HOST_CAPABILITY_CONTRACT.md` (29), `docs/HOW_TO_UPGRADE.md` (36), `docs/MERIDIAN_SELF_HOSTING_PROFILE.md` (2), `docs/MODULE_SPLIT_PLAN.md` (5), `docs/PROJECT_DECLARATION.md` (4), `docs/QUICKSTART.md` (21), `docs/TASK_IDENTITY_POLICY.md` (7), `migrations/README.md` (2), `tasks/040-plan-code-identifier-rename.md` (6), `tasks/041-plan-single-workflow.md` (3), `tasks/QUEUE.md` (1), `tasks/TASK_BLUEPRINT.md` (2); `tasks/done/**` (25 files, 63); `tasks/handoffs/**` (16 files, 36).

Options named after the product (`--meridian`, `--meridian-root`):

- Group 1 (renamed in 5a): 2 files, 6 occurrences. `scripts/align_queue.py` (1), `scripts/upgrade_project.sh` (5).
- Group 2 (renamed in 5b): none.
- Group 3 (frozen until item 10): none.
- Group 4 (historical, kept): 1 file, 8 occurrences. `docs/HOW_TO_UPGRADE.md` (8).

### 2. `MERIDIAN_*` environment names

**Current → new name.** `MERIDIAN_ROOT` → `CARDINE_ROOT`; `MERIDIAN_WORKTREE_ROOT` → `CARDINE_WORKTREE_ROOT`; `MERIDIAN_TEST_SHARD` → `CARDINE_TEST_SHARD`; `MERIDIAN_FAILURE_VISIBILITY_PROBE` → `CARDINE_FAILURE_VISIBILITY_PROBE`; `MERIDIAN_SESSION_NOT_FOUND` → `CARDINE_SESSION_NOT_FOUND`; `MERIDIAN_BIN` → `CARDINE_BIN` in `hooks/stop-audit.sh` only.

Names at the baseline: `MERIDIAN_ROOT`, `MERIDIAN_BIN`,
`MERIDIAN_WORKTREE_ROOT`, `MERIDIAN_TEST_SHARD`, `MERIDIAN_SESSION_NOT_FOUND`,
`MERIDIAN_FAILURE_VISIBILITY_PROBE`, and the document name
`MERIDIAN_SELF_HOSTING_PROFILE`. Occurrences by name:

| Name | G1 | G2 | G3 | G4 |
|---|---:|---:|---:|---:|
| `MERIDIAN_BIN` | 8 | 0 | 37 | 1 |
| `MERIDIAN_FAILURE_VISIBILITY_PROBE` | 2 | 0 | 0 | 0 |
| `MERIDIAN_ROOT` | 54 | 8 | 0 | 54 |
| `MERIDIAN_SELF_HOSTING_PROFILE` | 0 | 0 | 0 | 4 |
| `MERIDIAN_SESSION_NOT_FOUND` | 3 | 0 | 0 | 1 |
| `MERIDIAN_TEST_SHARD` | 2 | 0 | 0 | 5 |
| `MERIDIAN_WORKTREE_ROOT` | 16 | 0 | 1 | 3 |

`MERIDIAN_ROOT` is read by `hosts/setup.py` and the host-root checks and is set
by `scripts/run_tests.py` (it removes it from shard environments) and by tests.
`MERIDIAN_WORKTREE_ROOT` is read by `worktree/storage.py` and named in
`lifecycle/closure.py` messages. `MERIDIAN_TEST_SHARD` is set by
`scripts/run_tests.py`. Decision 9 removes `MERIDIAN_ROOT` with the release
checkout; 5a renames it only because the code and tests still use it.

Files:

- Group 1 (renamed in 5a): 24 files, 85 occurrences. `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md` (4), `hooks/stop-audit.sh` (8), `scripts/release.py` (2), `scripts/run_agent_evals.py` (1), `scripts/run_tests.py` (4), `scripts/upgrade_project.sh` (15), `src/cardine/cli.py` (1), `src/cardine/console/launch.py` (2), `src/cardine/hosts/setup.py` (8), `src/cardine/lifecycle/closure.py` (1), `src/cardine/worktree/storage.py` (3), `tests/stop_recovery_support.py` (1), `tests/test_cardine_cli.py` (3), `tests/test_cli_install.py` (5), `tests/test_console_launch.py` (1), `tests/test_execution_boundaries.py` (1), `tests/test_host_codex_repair.py` (2), `tests/test_host_worktree_setup.py` (8), `tests/test_launcher_task_audit.py` (1), `tests/test_lean_walkthrough.py` (2), `tests/test_release.py` (2), `tests/test_run_tests.py` (8), `tests/test_worktree_cleanup.py` (1), `tests/test_worktree_lifecycle.py` (1).
- Group 2 (renamed in 5b): 1 file, 8 occurrences. `skills/meridian-governed-sdd/SKILL.md` (8).
- Group 3 (frozen until item 10): 3 files, 38 occurrences. `docs/WORKTREE_LIFECYCLE.md` (1), `hooks/queue-briefing.sh` (23), `hooks/read-guard.sh` (14).
- Group 4 (historical, kept): 23 files, 68 occurrences. `CHANGELOG.md` (3), `CONTRIBUTING.md` (3), `README.md` (2), `docs/ADR_CARDINE_1_0.md` (2), `docs/AGENT_OPERATIONS.md` (1), `docs/CLEAN_INSTALL_VERIFICATION.md` (6), `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (4), `docs/HOST_CAPABILITY_CONTRACT.md` (9), `docs/HOW_TO_UPGRADE.md` (6), `docs/MODULE_SPLIT_PLAN.md` (2), `docs/QUICKSTART.md` (5), `tasks/040-plan-code-identifier-rename.md` (5); `tasks/done/**` (5 files, 11); `tasks/handoffs/**` (6 files, 9).

### 3. The `.meridian/` project directory

**Current → new name.** `.meridian/` → `.cardine/` (file names unchanged); `meridian-self-hosting` → `cardine-self-hosting`.

Product constants are in `src/cardine/shared/constants.py`
(`MANIFEST_PATH`, `BASELINES_PATH`, `CONTEXT_SIZE_CONFIG_PATH`,
`TASK_IDENTITY_PATH`, `PROJECT_DECLARATION_PATH`) and `shared/models.py`
(`CANDIDATE_VALIDATION_PATH`); literals are in `tasks/state.py`,
`shared/context.py`, `shared/flow.py`, `tasks/identity.py`, `tasks/audit.py`,
`tasks/contract.py`, `worktree/checkout.py`, `lifecycle/closure.py`, and
`worktree/storage.py`. `capabilities/catalog-v1.json` declares probe paths
under `.meridian/probes/`. Tracked files under `.meridian/` itself: 9 baseline
files, 39 task state files, `manifest.json`, `candidate-validation.json`,
`flow-targets.json`, and 3 probe files; all are group 3.

Files:

- Group 1 (renamed in 5a): 61 files, 254 occurrences. `capabilities/catalog-v1.json` (9), `capabilities/stop-codes-v1.json` (1), `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md` (3), `evals/lib/lean-project.sh` (2), `evals/scenarios/governed-remediation-completes/setup.sh` (2), `scripts/align_queue.py` (1), `scripts/upgrade_project.sh` (3), `src/cardine/lifecycle/closure.py` (1), `src/cardine/shared/constants.py` (5), `src/cardine/shared/context.py` (5), `src/cardine/shared/flow.py` (1), `src/cardine/shared/models.py` (1), `src/cardine/tasks/audit.py` (1), `src/cardine/tasks/contract.py` (1), `src/cardine/tasks/identity.py` (1), `src/cardine/tasks/state.py` (1), `src/cardine/worktree/checkout.py` (1), `tests/console_support.py` (1), `tests/fixtures/agent_evals/branch-keeps-off-governance-pass.json` (2), `tests/fixtures/agent_evals/dirty-primary-stops-pass.json` (2), `tests/fixtures/agent_evals/governed-remediation-completes-pass.json` (3), `tests/fixtures/agent_evals/main-ahead-integrates-main-behind-origin.json` (11), `tests/fixtures/agent_evals/main-ahead-integrates-not-pushed.json` (11), `tests/fixtures/agent_evals/main-ahead-integrates-pass.json` (11), `tests/fixtures/agent_evals/push-rejected-no-force-pass.json` (2), `tests/fixtures/agent_evals/tag-request-refused-pass.json` (2), `tests/fixtures/task-blueprint-v15.md` (1), `tests/meridian_cli_support.py` (5), `tests/synthetic_upgrade_support.py` (1), `tests/test_codex_read_guard.py` (2), `tests/test_console_snapshot.py` (3), `tests/test_console_states.py` (6), `tests/test_context_size.py` (4), `tests/test_execution_boundaries.py` (10), `tests/test_execution_evidence.py` (10), `tests/test_host_codex_access.py` (1), `tests/test_integration_projections.py` (5), `tests/test_launcher_task_audit.py` (3), `tests/test_lifecycle_journal_flow.py` (3), `tests/test_machine_task_state.py` (6), `tests/test_marker_structure_audit.py` (4), `tests/test_meridian_cli_entry.py` (1), `tests/test_meridian_manifest_protocol.py` (10), `tests/test_meridian_migration_retirement.py` (4), `tests/test_meridian_upgrade_lifecycle.py` (18), `tests/test_meridian_upgrade_merge.py` (9), `tests/test_queue_archival_state.py` (7), `tests/test_read_guard.py` (2), `tests/test_review_verdict.py` (1), `tests/test_synthetic_upgrade.py` (1), `tests/test_task_close.py` (2), `tests/test_task_identity_project.py` (3), `tests/test_task_integration_state.py` (12), `tests/test_task_state_import.py` (9), `tests/test_template_manifest.py` (2), `tests/test_template_surface_upgrade.py` (2), `tests/test_worktree_cleanup.py` (3), `tests/test_worktree_integration.py` (5), `tests/test_worktree_lifecycle.py` (12), `tests/test_worktree_paths.py` (2), `tests/worktree_support.py` (1).
- Group 2 (renamed in 5b): 19 files, 31 occurrences. `commands/meridian-init.md` (2), `commands/meridian-task.md` (1), `commands/meridian-upgrade.md` (2), `skills/meridian-governed-sdd-claude-code/SKILL.md` (2), `skills/meridian-governed-sdd/SKILL.md` (2), `skills/meridian-lean-delivery-claude-code/SKILL.md` (1), `skills/meridian-lean-delivery/SKILL.md` (1), `templates/workflows/governed-sdd/PROJECT_WORKFLOW.md` (4), `templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md` (1), `templates/workflows/governed-sdd/docs/LIFECYCLE_ORCHESTRATION.md` (1), `templates/workflows/governed-sdd/docs/PULL_REQUEST_POLICY.md` (1), `templates/workflows/governed-sdd/docs/WORKTREE_LIFECYCLE.md` (3), `templates/workflows/governed-sdd/docs/workflows/REVIEW.md` (2), `templates/workflows/governed-sdd/tasks/TASK_BLUEPRINT.md` (1), `templates/workflows/lean-delivery/AGENTS.md` (1), `templates/workflows/lean-delivery/CLAUDE.md` (1), `templates/workflows/lean-delivery/PROJECT_WORKFLOW.md` (2), `templates/workflows/lean-delivery/docs/CONTEXT_BUDGET_POLICY.md` (1), `templates/workflows/lean-delivery/docs/WORKTREE_LIFECYCLE.md` (2).
- Group 3 (frozen until item 10): 13 files, 45 occurrences. `.meridian/baselines/1.4.0/AGENTS.md` (1), `.meridian/baselines/1.4.0/CLAUDE.md` (1), `.meridian/baselines/1.4.0/PROJECT_WORKFLOW.md` (2), `.meridian/baselines/1.4.0/docs/CONTEXT_BUDGET_POLICY.md` (1), `.meridian/baselines/1.4.0/docs/WORKTREE_LIFECYCLE.md` (2), `AGENTS.md` (1), `CLAUDE.md` (1), `PROJECT_WORKFLOW.md` (2), `docs/CONTEXT_BUDGET_POLICY.md` (1), `docs/WORKTREE_LIFECYCLE.md` (12), `scripts/check_repository.py` (5), `tests/test_check_repository.py` (9), `tests/test_template_manifest.py` (7).
- Group 4 (historical, kept): 51 files, 165 occurrences. `CHANGELOG.md` (21), `CONTRIBUTING.md` (4), `docs/ADR_CARDINE_1_0.md` (6), `docs/ADR_MACHINE_TASK_STATE.md` (3), `docs/CLEAN_INSTALL_VERIFICATION.md` (3), `docs/CONSUMER_PROFILES.md` (2), `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (2), `docs/GOVERNED_WORKFLOW.md` (2), `docs/HOW_TO_UPGRADE.md` (5), `docs/MERIDIAN_SELF_HOSTING_PROFILE.md` (1), `docs/MODULE_SPLIT_PLAN.md` (2), `docs/PROJECT_DECLARATION.md` (1), `docs/QUICKSTART.md` (2), `docs/TASK_IDENTITY_POLICY.md` (4), `migrations/README.md` (1), `tasks/040-plan-code-identifier-rename.md` (8), `tasks/041-plan-single-workflow.md` (5); `tasks/done/**` (10 files, 51); `tasks/handoffs/**` (24 files, 42).

Profile id `meridian-self-hosting`:

- Group 1 (renamed in 5a): 7 files, 11 occurrences. `capabilities/catalog-v1.json` (1), `scripts/check_repository.py` (2), `src/cardine/shared/constants.py` (1), `src/cardine/templates/audit.py` (1), `src/cardine/templates/catalog.py` (1), `tests/test_marker_structure_audit.py` (2), `tests/test_template_manifest.py` (3).
- Group 2 (renamed in 5b): none.
- Group 3 (frozen until item 10): 6 files, 33 occurrences. `.meridian/manifest.json` (2), `.meridian/probes/meridian-self-hosting/claude-project-v1.json` (1), `.meridian/probes/meridian-self-hosting/codex-project-v1.json` (1), `.meridian/probes/meridian-self-hosting/host-neutral-ci-v1.json` (1), `tests/test_check_repository.py` (3), `tests/test_template_manifest.py` (25).
- Group 4 (historical, kept): 75 files, 171 occurrences. `CHANGELOG.md` (1), `CONTRIBUTING.md` (2), `docs/MERIDIAN_SELF_HOSTING_PROFILE.md` (8), `tasks/040-plan-code-identifier-rename.md` (2), `tasks/041-plan-single-workflow.md` (2), `tasks/TASK_BLUEPRINT.md` (2); `releases/**` (1 files, 1); `tasks/done/**` (33 files, 80); `tasks/handoffs/**` (35 files, 73).

### 4. Git-internal files

**Current → new name.** `meridian-journal.jsonl` → `cardine-journal.jsonl`; `meridian-journal.1.jsonl` → `cardine-journal.1.jsonl`; `meridian-integration.lock` → `cardine-integration.lock`; `meridian-integration.json` → `cardine-integration.json`; `meridian-worktrees/` → `cardine-worktrees/`; `meridian_shared_worktrees` → `cardine_shared_worktrees`.

Constants are in `shared/models.py` (`WORKTREE_STATE_DIRECTORY`,
`INTEGRATION_LEASE_NAME`, `INTEGRATION_STATE_NAME`) and `shared/journal.py`
(`JOURNAL_NAME`, `JOURNAL_ROTATED_NAME`); `shared/git.py` holds the
`meridian_shared_worktrees` context variable. `scripts/run_agent_evals.py`
names both journal files. The **installed** Meridian writes all of these in this
repository's `.git`, so the coordinator snapshot reads them (reader table).
Occurrences by kind:

| Name | G1 | G2 | G3 | G4 |
|---|---:|---:|---:|---:|
| `gitint:context-variable` | 1 | 0 | 0 | 0 |
| `gitint:integration` | 5 | 1 | 0 | 0 |
| `gitint:journal` | 14 | 0 | 2 | 3 |
| `gitint:worktree-state` | 7 | 0 | 0 | 2 |

Files:

- Group 1 (renamed in 5a): 9 files, 27 occurrences. `scripts/run_agent_evals.py` (2), `src/cardine/shared/git.py` (1), `src/cardine/shared/journal.py` (2), `src/cardine/shared/models.py` (3), `tests/test_console_snapshot.py` (1), `tests/test_lifecycle_journal_flow.py` (9), `tests/test_worktree_checkout.py` (7), `tests/test_worktree_lifecycle.py` (1), `tests/worktree_support.py` (1).
- Group 2 (renamed in 5b): 1 file, 1 occurrence. `templates/workflows/governed-sdd/docs/PULL_REQUEST_POLICY.md` (1).
- Group 3 (frozen until item 10): 1 file, 2 occurrences. `docs/WORKTREE_LIFECYCLE.md` (2).
- Group 4 (historical, kept): 4 files, 5 occurrences. `CHANGELOG.md` (1), `docs/HOST_CAPABILITY_CONTRACT.md` (1), `tasks/040-plan-code-identifier-rename.md` (2); `tasks/done/**` (1 files, 1).

### 5. The worktree root and the user configuration that selects it

**Current → new name.** `~/.meridian/worktrees` → `~/.cardine/worktrees`; `meridian/config.json` → `cardine/config.json`; `.meridian-*` backup and `meridian-*-` temporary names → the same with `cardine`; `biagiolibe/meridian` → `biagiolibe/cardine`.

`worktree/storage.py` resolves the root in this order: explicit option,
`MERIDIAN_WORKTREE_ROOT`, the `worktreeRoot` key of
`$XDG_CONFIG_HOME/meridian/config.json`, then `~/.meridian/worktrees`.
`hosts/setup.py` repeats the default for `setup --check`. The installed Meridian
creates this repository's task worktrees under `~/.meridian/worktrees`, and the
coordinator snapshot derives paths from it (reader table).

Files:

- Group 1 (renamed in 5a): 5 files, 9 occurrences. `src/cardine/hosts/setup.py` (1), `src/cardine/worktree/storage.py` (2), `tests/test_codex_user_rules.py` (2), `tests/test_host_worktree_setup.py` (3), `tests/test_queue_briefing.py` (1).
- Group 2 (renamed in 5b): 2 files, 2 occurrences. `templates/workflows/governed-sdd/docs/WORKTREE_LIFECYCLE.md` (1), `templates/workflows/lean-delivery/docs/WORKTREE_LIFECYCLE.md` (1).
- Group 3 (frozen until item 10): 2 files, 5 occurrences. `.meridian/baselines/1.4.0/docs/WORKTREE_LIFECYCLE.md` (1), `docs/WORKTREE_LIFECYCLE.md` (4).
- Group 4 (historical, kept): 4 files, 6 occurrences. `CHANGELOG.md` (1), `docs/HOST_CAPABILITY_CONTRACT.md` (3), `docs/QUICKSTART.md` (1), `tasks/040-plan-code-identifier-rename.md` (1).

Backup and temporary names that carry the project directory name:

- Group 1 (renamed in 5a): 13 files, 29 occurrences. `scripts/release.py` (1), `scripts/run_agent_evals.py` (1), `scripts/run_tests.py` (2), `src/cardine/hosts/codex.py` (4), `src/cardine/hosts/setup.py` (1), `src/cardine/release/update.py` (1), `src/cardine/templates/merge.py` (1), `src/cardine/templates/upgrade_support.py` (1), `tests/test_host_codex_access.py` (1), `tests/test_host_codex_repair.py` (4), `tests/test_marker_structure_audit.py` (5), `tests/test_meridian_upgrade_lifecycle.py` (6), `tests/test_meridian_upgrade_merge.py` (1).
- Group 2 (renamed in 5b): 1 file, 3 occurrences. `src/cardine/release/update.py` (3).
- Group 3 (frozen until item 10): none.
- Group 4 (historical, kept): 6 files, 15 occurrences. `CHANGELOG.md` (2), `docs/HOST_CAPABILITY_CONTRACT.md` (1), `docs/HOW_TO_UPGRADE.md` (8), `migrations/README.md` (2); `tasks/handoffs/**` (2 files, 2).

Repository, plugin, and install locations (`biagiolibe/meridian`,
`extraKnownMarketplaces.meridian`, `~/.local/share/meridian`):

- Group 1 (renamed in 5a): 15 files, 20 occurrences. `schemas/capability-catalog-v1.schema.json` (1), `schemas/manifest-v2.schema.json` (1), `schemas/project-v1.schema.json` (1), `schemas/retired-text-v1.schema.json` (1), `schemas/stop-codes-v1.schema.json` (1), `schemas/task-state-v1.schema.json` (1), `schemas/validation-evidence-v1.schema.json` (1), `scripts/release.py` (1), `src/cardine/integration/evidence.py` (1), `src/cardine/release/update.py` (1), `src/cardine/shared/constants.py` (1), `tests/test_cli_install.py` (4), `tests/test_release_self_check.py` (1), `tests/test_self_update.py` (1), `tests/test_usage_report.py` (3).
- Group 2 (renamed in 5b): 1 file, 1 occurrence. `skills/meridian-governed-sdd/SKILL.md` (1).
- Group 3 (frozen until item 10): none.
- Group 4 (historical, kept): 16 files, 49 occurrences. `.github/ISSUE_TEMPLATE/bug_report.md` (1), `.github/ISSUE_TEMPLATE/config.yml` (1), `CHANGELOG.md` (5), `CODE_OF_CONDUCT.md` (1), `PROJECT_PLAN.md` (1), `README.md` (10), `SECURITY.md` (1), `docs/ADR_CARDINE_1_0.md` (1), `docs/CLEAN_INSTALL_VERIFICATION.md` (6), `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (1), `docs/HOST_CAPABILITY_CONTRACT.md` (6), `docs/HOW_TO_UPGRADE.md` (7), `docs/QUICKSTART.md` (5), `migrations/README.md` (1); `tasks/done/**` (2 files, 2).

### 6. Code names

**Current → new name.** `MeridianError` → `CardineError`; `MeridianStop` → `CardineStop`; `MeridianArgumentParser` → `CardineArgumentParser`; `MeridianCliFixtureMixin` → `CardineCliFixtureMixin`; `MeridianCliTest` → `CardineCliTest`; module alias `meridian` → `cardine_cli`; `meridian_cli_support` → `cardine_cli_support`; `test_meridian_*` → `test_cardine_*`; `meridian_root_state` and `meridian_root_value` → `cardine_root_state` and `cardine_root_value`.

Occurrences by kind:

| Name | G1 | G2 | G3 | G4 |
|---|---:|---:|---:|---:|
| `codename:adapter-alias` | 72 | 0 | 3 | 112 |
| `codename:exception` | 548 | 0 | 0 | 5 |
| `codename:module` | 37 | 0 | 0 | 5 |
| `codename:test-class` | 11 | 0 | 0 | 93 |
| `codename:test-name` | 9 | 0 | 0 | 455 |

`scripts/meridian.py` is imported by 36 files as the module `meridian`; its
attributes (`meridian.version_key`, `meridian.sha256`, patch targets such as
`meridian.os.replace`) are the `adapter-alias` occurrences. The test support
module `tests/meridian_cli_support.py` and six `tests/test_meridian_*.py` files
carry the name in their paths.

Files:

- Group 1 (renamed in 5a): 106 files, 677 occurrences. `capabilities/stop-codes-v1.json` (1), `scripts/check_repository.py` (13), `scripts/codex_read_guard.py` (4), `scripts/dev.py` (4), `scripts/meridian.py` (3), `src/cardine/cli.py` (13), `src/cardine/console/snapshot.py` (15), `src/cardine/hosts/claude.py` (3), `src/cardine/hosts/codex.py` (17), `src/cardine/hosts/setup.py` (25), `src/cardine/integration/evidence.py` (19), `src/cardine/integration/merge.py` (22), `src/cardine/integration/projections.py` (6), `src/cardine/lifecycle/closure.py` (11), `src/cardine/lifecycle/commands.py` (2), `src/cardine/lifecycle/execution.py` (3), `src/cardine/release/update.py` (9), `src/cardine/release/version.py` (5), `src/cardine/review/verdict.py` (2), `src/cardine/shared/authority.py` (8), `src/cardine/shared/context.py` (9), `src/cardine/shared/errors.py` (3), `src/cardine/shared/flow.py` (8), `src/cardine/shared/git.py` (5), `src/cardine/shared/journal.py` (3), `src/cardine/shared/jsonio.py` (3), `src/cardine/shared/models.py` (1), `src/cardine/shared/project.py` (15), `src/cardine/shared/usage.py` (2), `src/cardine/shared/validation.py` (7), `src/cardine/stops/render.py` (6), `src/cardine/tasks/audit.py` (2), `src/cardine/tasks/contract.py` (3), `src/cardine/tasks/identity.py` (35), `src/cardine/tasks/importer.py` (2), `src/cardine/tasks/recording.py` (4), `src/cardine/tasks/transitions.py` (4), `src/cardine/templates/adoption.py` (5), `src/cardine/templates/audit.py` (27), `src/cardine/templates/catalog.py` (43), `src/cardine/templates/files.py` (4), `src/cardine/templates/generator.py` (2), `src/cardine/templates/manifest.py` (6), `src/cardine/templates/marker_audit.py` (2), `src/cardine/templates/merge.py` (5), `src/cardine/templates/migrations.py` (4), `src/cardine/templates/mode.py` (4), `src/cardine/templates/protocol.py` (4), `src/cardine/templates/router.py` (10), `src/cardine/templates/upgrade.py` (11), `src/cardine/worktree/checkout.py` (13), `src/cardine/worktree/closure_status.py` (2), `src/cardine/worktree/paths.py` (11), `src/cardine/worktree/storage.py` (9), `tests/fixtures/module_split_baseline.json` (4), `tests/meridian_cli_support.py` (1), `tests/synthetic_upgrade_support.py` (3), `tests/test_authority_excerpt.py` (1), `tests/test_cardine_cli.py` (7), `tests/test_check_repository.py` (1), `tests/test_codex_read_guard.py` (1), `tests/test_codex_rules.py` (1), `tests/test_codex_user_rules.py` (3), `tests/test_codex_worktree_hooks.py` (1), `tests/test_console_closure.py` (1), `tests/test_console_snapshot.py` (4), `tests/test_dev_commands.py` (1), `tests/test_execution_boundaries.py` (6), `tests/test_execution_evidence.py` (1), `tests/test_host_codex_access.py` (13), `tests/test_host_codex_repair.py` (19), `tests/test_host_worktree_setup.py` (19), `tests/test_integration_projections.py` (7), `tests/test_launcher_task_audit.py` (1), `tests/test_lifecycle_journal_flow.py` (4), `tests/test_machine_task_state.py` (4), `tests/test_marker_structure_audit.py` (2), `tests/test_meridian_adoption_audit.py` (3), `tests/test_meridian_cli_entry.py` (3), `tests/test_meridian_manifest_protocol.py` (6), `tests/test_meridian_migration_retirement.py` (3), `tests/test_meridian_upgrade_lifecycle.py` (1), `tests/test_meridian_upgrade_merge.py` (2), `tests/test_queue_archival_state.py` (2), `tests/test_queue_briefing.py` (1), `tests/test_read_guard.py` (1), `tests/test_release_self_check.py` (1), `tests/test_review_verdict.py` (3), `tests/test_self_update.py` (5), `tests/test_stop_audit.py` (1), `tests/test_synthetic_upgrade.py` (1), `tests/test_task_close.py` (4), `tests/test_task_identity_project.py` (12), `tests/test_task_integration_state.py` (1), `tests/test_task_state_lookups.py` (1), `tests/test_template_manifest.py` (9), `tests/test_template_marker_heading.py` (1), `tests/test_template_retirement.py` (1), `tests/test_template_router.py` (6), `tests/test_template_surface_upgrade.py` (3), `tests/test_usage_report.py` (1), `tests/test_validation_evidence.py` (1), `tests/test_worktree_checkout.py` (20), `tests/test_worktree_cleanup.py` (11), `tests/test_worktree_integration.py` (7), `tests/test_worktree_lifecycle.py` (2).
- Group 2 (renamed in 5b): none.
- Group 3 (frozen until item 10): 1 file, 3 occurrences. `.codex/rules/local.rules` (3).
- Group 4 (historical, kept): 29 files, 670 occurrences. `PROJECT_PLAN.md` (2), `docs/ADR_CARDINE_1_0.md` (1), `docs/MODULE_SPLIT_PLAN.md` (53), `tasks/040-plan-code-identifier-rename.md` (1), `tasks/QUEUE_ARCHIVE.md` (2); `tasks/done/**` (6 files, 24); `tasks/handoffs/**` (18 files, 587).

### 7. User-facing strings and help text

**Current → new name.** "Meridian" → "Cardine"; `https://meridian.local/schemas/…` → `https://cardine.local/schemas/…`. The `setup --check` keys do not change.

The product name in messages (for example "Meridian user configuration must
contain only version 1 and worktreeRoot", "Meridian requires Python 3.12", and
"Meridian repository checks passed."), parser help, schema titles, the
`$id` `https://meridian.local/schemas/…`, and `pyproject.toml`'s description.
Capitalized prose and other fixture strings are counted in the same section.

Product name:

- Group 1 (renamed in 5a): 57 files, 103 occurrences. `bin/meridian` (2), `docs/PUBLIC_SURFACE.md` (2), `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md` (1), `evals/lib/lean-project.sh` (1), `evals/scenarios/governed-remediation-completes/setup.sh` (1), `hooks/stop-audit.sh` (3), `pyproject.toml` (1), `schemas/capability-catalog-v1.schema.json` (1), `schemas/manifest-v2.schema.json` (1), `schemas/project-v1.schema.json` (1), `schemas/retired-text-v1.schema.json` (1), `schemas/stop-codes-v1.schema.json` (1), `schemas/task-state-v1.schema.json` (1), `schemas/validation-evidence-v1.schema.json` (1), `scripts/align_queue.py` (1), `scripts/check_repository.py` (2), `scripts/release.py` (4), `scripts/run_agent_evals.py` (1), `scripts/run_tests.py` (1), `scripts/stop_audit.py` (1), `scripts/upgrade_project.sh` (2), `src/cardine/cli.py` (2), `src/cardine/console/entry.py` (1), `src/cardine/console/launch.py` (1), `src/cardine/console/render.py` (1), `src/cardine/console/state.py` (2), `src/cardine/hosts/claude.py` (3), `src/cardine/hosts/codex.py` (7), `src/cardine/hosts/setup.py` (1), `src/cardine/shared/git.py` (1), `src/cardine/templates/audit.py` (2), `src/cardine/templates/markers.py` (1), `src/cardine/templates/merge.py` (1), `src/cardine/templates/protocol.py` (2), `src/cardine/templates/upgrade_support.py` (1), `src/cardine/worktree/storage.py` (4), `tests/synthetic_upgrade_support.py` (1), `tests/test_check_repository.py` (2), `tests/test_codex_rules.py` (1), `tests/test_codex_worktree_hooks.py` (1), `tests/test_console_closure.py` (1), `tests/test_console_snapshot.py` (4), `tests/test_execution_evidence.py` (4), `tests/test_host_codex_access.py` (1), `tests/test_host_codex_repair.py` (1), `tests/test_lifecycle_journal_flow.py` (1), `tests/test_meridian_cli_entry.py` (2), `tests/test_meridian_manifest_protocol.py` (3), `tests/test_meridian_migration_retirement.py` (3), `tests/test_module_inventory.py` (1), `tests/test_queue_briefing.py` (8), `tests/test_read_guard.py` (1), `tests/test_release.py` (3), `tests/test_synthetic_upgrade.py` (1), `tests/test_worktree_lifecycle.py` (2), `tests/test_worktree_paths.py` (1), `tests/worktree_support.py` (1).
- Group 2 (renamed in 5b): 20 files, 51 occurrences. `commands/meridian-adopt.md` (1), `commands/meridian-init.md` (4), `commands/meridian-task.md` (2), `commands/meridian-upgrade.md` (3), `skills/meridian-governed-sdd-claude-code/SKILL.md` (5), `skills/meridian-governed-sdd/SKILL.md` (8), `skills/meridian-lean-delivery-claude-code/SKILL.md` (3), `skills/meridian-lean-delivery/SKILL.md` (3), `templates/base/CLAUDE.md` (1), `templates/base/README.md` (1), `templates/workflows/governed-sdd/.codex/rules/meridian.rules` (2), `templates/workflows/governed-sdd/PROJECT_WORKFLOW.md` (4), `templates/workflows/governed-sdd/docs/CODE_ORGANIZATION.md` (1), `templates/workflows/governed-sdd/docs/EXECUTION_EVIDENCE_PROFILE.md` (1), `templates/workflows/governed-sdd/docs/OPERATOR_PROMPTS.md` (4), `templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md` (1), `templates/workflows/lean-delivery/.codex/rules/meridian.rules` (1), `templates/workflows/lean-delivery/AGENTS.md` (1), `templates/workflows/lean-delivery/CLAUDE.md` (1), `templates/workflows/lean-delivery/PROJECT_WORKFLOW.md` (4).
- Group 3 (frozen until item 10): 14 files, 39 occurrences. `.codex/rules/local.rules` (1), `.codex/rules/meridian.rules` (1), `.meridian/baselines/1.4.0/.codex/rules/meridian.rules` (1), `.meridian/baselines/1.4.0/AGENTS.md` (2), `.meridian/baselines/1.4.0/CLAUDE.md` (2), `.meridian/baselines/1.4.0/PROJECT_WORKFLOW.md` (5), `AGENTS.md` (3), `CLAUDE.md` (3), `PROJECT_WORKFLOW.md` (5), `docs/EXECUTION_EVIDENCE_PROFILE.md` (1), `docs/WORKTREE_LIFECYCLE.md` (2), `hooks/hooks.json` (2), `hooks/queue-briefing.sh` (9), `hooks/read-guard.sh` (2).
- Group 4 (historical, kept): 68 files, 282 occurrences. `.github/ISSUE_TEMPLATE/bug_report.md` (1), `.github/ISSUE_TEMPLATE/feature_request.md` (1), `CHANGELOG.md` (22), `CODE_OF_CONDUCT.md` (1), `CONTRIBUTING.md` (11), `PROJECT_PLAN.md` (4), `README.md` (7), `SECURITY.md` (1), `WORKFLOW_GUIDE.md` (2), `docs/ADR_CARDINE_1_0.md` (43), `docs/ADR_MACHINE_TASK_STATE.md` (2), `docs/ADR_PUBLIC_SURFACE_AND_STABILITY.md` (4), `docs/ADR_SHARED_GENERATED_ENTRY_ROUTERS.md` (7), `docs/ADR_STOPS_AND_DENIALS.md` (3), `docs/AGENT_OPERATIONS.md` (12), `docs/CLEAN_INSTALL_VERIFICATION.md` (11), `docs/CONSUMER_ROUTER_ADOPTION_PLAYBOOK.md` (1), `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (9), `docs/GOVERNED_WORKFLOW.md` (2), `docs/HOST_CAPABILITY_CONTRACT.md` (13), `docs/HOW_TO_UPGRADE.md` (8), `docs/MERIDIAN_SELF_HOSTING_PROFILE.md` (12), `docs/MODULE_SPLIT_PLAN.md` (3), `docs/PLATFORM_SUPPORT.md` (2), `docs/QUICKSTART.md` (3), `docs/TASK_IDENTITY_POLICY.md` (3), `docs/assets/README.md` (2), `docs/assets/meridian-mark-dark.svg` (1), `docs/assets/meridian-mark-light.svg` (1), `docs/assets/meridian-mark.svg` (1), `migrations/README.md` (3), `tasks/040-plan-code-identifier-rename.md` (8), `tasks/041-plan-single-workflow.md` (1), `tasks/QUEUE_ARCHIVE.md` (4), `tasks/TASK_BLUEPRINT.md` (1); `changelog.d/**` (1 files, 1); `releases/**` (1 files, 1); `tasks/done/**` (18 files, 51); `tasks/handoffs/**` (13 files, 19).

Other prose and fixture strings:

- Group 1 (renamed in 5a): 16 files, 25 occurrences. `scripts/align_queue.py` (1), `scripts/check_repository.py` (1), `scripts/meridian.py` (1), `scripts/upgrade_project.sh` (2), `src/cardine/cli.py` (2), `src/cardine/hosts/codex.py` (3), `src/cardine/release/update.py` (1), `src/cardine/templates/upgrade_support.py` (1), `tests/test_ci_evidence.py` (1), `tests/test_cli_install.py` (1), `tests/test_host_codex_repair.py` (3), `tests/test_host_worktree_setup.py` (1), `tests/test_queue_briefing.py` (2), `tests/test_template_marker_heading.py` (1), `tests/test_usage_report.py` (3), `tests/test_worktree_checkout.py` (1).
- Group 2 (renamed in 5b): 4 files, 4 occurrences. `skills/meridian-governed-sdd/SKILL.md` (1), `src/cardine/hosts/skills.py` (1), `templates/workflows/lean-delivery/AGENTS.md` (1), `templates/workflows/lean-delivery/CLAUDE.md` (1).
- Group 3 (frozen until item 10): 6 files, 6 occurrences. `.meridian/baselines/1.4.0/AGENTS.md` (1), `.meridian/baselines/1.4.0/CLAUDE.md` (1), `AGENTS.md` (1), `CLAUDE.md` (1), `docs/WORKTREE_LIFECYCLE.md` (1), `hooks/queue-briefing.sh` (1).
- Group 4 (historical, kept): 31 files, 81 occurrences. `.github/ISSUE_TEMPLATE/bug_report.md` (1), `.github/ISSUE_TEMPLATE/feature_request.md` (1), `CHANGELOG.md` (8), `CONTRIBUTING.md` (2), `PROJECT_PLAN.md` (1), `README.md` (3), `docs/ADR_CARDINE_1_0.md` (5), `docs/ADR_SHARED_GENERATED_ENTRY_ROUTERS.md` (1), `docs/CONSUMER_PROFILES.md` (1), `docs/CONSUMER_ROUTER_ADOPTION_PLAYBOOK.md` (2), `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (5), `docs/HOST_CAPABILITY_CONTRACT.md` (10), `docs/HOW_TO_UPGRADE.md` (8), `docs/MODULE_SPLIT_PLAN.md` (1), `docs/assets/README.md` (6), `tasks/040-plan-code-identifier-rename.md` (2), `tasks/QUEUE_ARCHIVE.md` (2); `tasks/done/**` (1 files, 1); `tasks/handoffs/**` (13 files, 21).

### 8. Further classes found by the inventory

The task listed seven classes. The inventory found six more that carry the
name. Markers and skill names are group 2 by the task's own definition; they
are listed so that no occurrence is left unassigned.

`MERIDIAN:` markers:

- Group 1 (renamed in 5a): none.
- Group 2 (renamed in 5b): 64 files, 450 occurrences. `commands/meridian-audit.md` (2), `scripts/check_repository.py` (6), `skills/meridian-governed-sdd-claude-code/SKILL.md` (2), `skills/meridian-governed-sdd/SKILL.md` (2), `skills/meridian-lean-delivery-claude-code/SKILL.md` (2), `skills/meridian-lean-delivery/SKILL.md` (2), `src/cardine/hosts/codex.py` (6), `src/cardine/shared/constants.py` (5), `src/cardine/shared/models.py` (2), `src/cardine/tasks/identity.py` (4), `src/cardine/templates/audit.py` (2), `src/cardine/templates/files.py` (2), `src/cardine/templates/marker_history.py` (3), `src/cardine/templates/markers.py` (7), `templates/workflows/governed-sdd/AGENTS.md` (2), `templates/workflows/governed-sdd/CLAUDE.md` (2), `templates/workflows/governed-sdd/LANGUAGE_POLICY.md` (2), `templates/workflows/governed-sdd/PROJECT_WORKFLOW.md` (24), `templates/workflows/governed-sdd/docs/AUDIT_PROMPT_READ_ONLY.md` (2), `templates/workflows/governed-sdd/docs/CODE_ORGANIZATION.md` (2), `templates/workflows/governed-sdd/docs/CODE_REVIEW_PROMPT.md` (2), `templates/workflows/governed-sdd/docs/COMPLETION_REPORT_TEMPLATE.md` (8), `templates/workflows/governed-sdd/docs/CONTEXT_BUDGET_POLICY.md` (18), `templates/workflows/governed-sdd/docs/EXECUTION_EVIDENCE_PROFILE.md` (4), `templates/workflows/governed-sdd/docs/LIFECYCLE_ORCHESTRATION.md` (4), `templates/workflows/governed-sdd/docs/PULL_REQUEST_POLICY.md` (6), `templates/workflows/governed-sdd/docs/REVIEW_RECORD_TEMPLATE.md` (4), `templates/workflows/governed-sdd/docs/WORKTREE_LIFECYCLE.md` (4), `templates/workflows/governed-sdd/docs/workflows/IMPLEMENTATION.md` (16), `templates/workflows/governed-sdd/docs/workflows/LIFECYCLE.md` (8), `templates/workflows/governed-sdd/docs/workflows/REMEDIATION.md` (10), `templates/workflows/governed-sdd/docs/workflows/REVIEW.md` (12), `templates/workflows/governed-sdd/tasks/TASK_BLUEPRINT.md` (2), `templates/workflows/lean-delivery/AGENTS.md` (2), `templates/workflows/lean-delivery/CLAUDE.md` (2), `templates/workflows/lean-delivery/LANGUAGE_POLICY.md` (2), `templates/workflows/lean-delivery/PROJECT_WORKFLOW.md` (12), `templates/workflows/lean-delivery/docs/CONTEXT_BUDGET_POLICY.md` (12), `templates/workflows/lean-delivery/docs/EXECUTION_EVIDENCE_PROFILE.md` (2), `templates/workflows/lean-delivery/docs/WORKTREE_LIFECYCLE.md` (4), `tests/fixtures/task-blueprint-v15.md` (2), `tests/meridian_cli_support.py` (18), `tests/synthetic_upgrade_support.py` (4), `tests/test_authority_excerpt.py` (2), `tests/test_check_repository.py` (12), `tests/test_codex_user_rules.py` (9), `tests/test_console_snapshot.py` (4), `tests/test_context_size.py` (2), `tests/test_execution_evidence.py` (2), `tests/test_host_codex_repair.py` (3), `tests/test_marker_structure_audit.py` (23), `tests/test_meridian_adoption_audit.py` (12), `tests/test_meridian_cli_entry.py` (11), `tests/test_meridian_migration_retirement.py` (11), `tests/test_meridian_upgrade_lifecycle.py` (30), `tests/test_meridian_upgrade_merge.py` (16), `tests/test_queue_briefing.py` (10), `tests/test_read_guard.py` (2), `tests/test_task_identity_project.py` (10), `tests/test_template_manifest.py` (7), `tests/test_template_marker_heading.py` (14), `tests/test_template_retirement.py` (22), `tests/test_template_router.py` (7), `tests/test_template_stop_policy.py` (2).
- Group 3 (frozen until item 10): 15 files, 72 occurrences. `.meridian/baselines/1.4.0/AGENTS.md` (2), `.meridian/baselines/1.4.0/CLAUDE.md` (2), `.meridian/baselines/1.4.0/LANGUAGE_POLICY.md` (2), `.meridian/baselines/1.4.0/PROJECT_WORKFLOW.md` (12), `.meridian/baselines/1.4.0/docs/CONTEXT_BUDGET_POLICY.md` (12), `.meridian/baselines/1.4.0/docs/EXECUTION_EVIDENCE_PROFILE.md` (2), `.meridian/baselines/1.4.0/docs/WORKTREE_LIFECYCLE.md` (4), `AGENTS.md` (2), `CLAUDE.md` (2), `LANGUAGE_POLICY.md` (2), `PROJECT_WORKFLOW.md` (10), `docs/CONTEXT_BUDGET_POLICY.md` (12), `docs/EXECUTION_EVIDENCE_PROFILE.md` (2), `docs/WORKTREE_LIFECYCLE.md` (4), `hooks/queue-briefing.sh` (2).
- Group 4 (historical, kept): 8 files, 20 occurrences. `CHANGELOG.md` (7), `CONTRIBUTING.md` (2), `docs/ADR_CAPABILITY_MOVE_AND_BOOTSTRAP_ROUTER.md` (4), `docs/ADR_CARDINE_1_0.md` (1), `docs/ADR_SHARED_GENERATED_ENTRY_ROUTERS.md` (1), `docs/AGENT_OPERATIONS.md` (2), `docs/CONSUMER_PROFILES.md` (2), `tasks/041-plan-single-workflow.md` (1).

Skill, command, and rules file names:

- Group 1 (renamed in 5a): 1 file, 3 occurrences. `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md` (3).
- Group 2 (renamed in 5b): 21 files, 51 occurrences. `capabilities/catalog-v1.json` (1), `commands/meridian-init.md` (1), `scripts/check_repository.py` (7), `skills/meridian-governed-sdd-claude-code/SKILL.md` (7), `skills/meridian-governed-sdd/SKILL.md` (1), `skills/meridian-lean-delivery-claude-code/SKILL.md` (1), `skills/meridian-lean-delivery/SKILL.md` (1), `src/cardine/hosts/setup.py` (1), `src/cardine/hosts/skills.py` (2), `src/cardine/templates/files.py` (1), `templates/workflows/governed-sdd/.codex/rules/meridian.rules` (1), `tests/fixtures/agent_evals/main-ahead-integrates-main-behind-origin.json` (1), `tests/fixtures/agent_evals/main-ahead-integrates-not-pushed.json` (1), `tests/fixtures/agent_evals/main-ahead-integrates-pass.json` (1), `tests/synthetic_upgrade_support.py` (1), `tests/test_check_repository.py` (1), `tests/test_codex_rules.py` (5), `tests/test_execution_boundaries.py` (2), `tests/test_host_codex_access.py` (7), `tests/test_host_worktree_setup.py` (7), `tests/test_template_manifest.py` (1).
- Group 3 (frozen until item 10): 1 file, 2 occurrences. `.meridian/manifest.json` (2).
- Group 4 (historical, kept): 14 files, 45 occurrences. `CHANGELOG.md` (14), `README.md` (2), `WORKFLOW_GUIDE.md` (2), `docs/AGENT_OPERATIONS.md` (3), `docs/CLEAN_INSTALL_VERIFICATION.md` (6), `docs/DISTRIBUTION_AND_UPDATE_DESIGN.md` (1), `docs/HOST_CAPABILITY_CONTRACT.md` (7), `docs/MERIDIAN_SELF_HOSTING_PROFILE.md` (2), `docs/QUICKSTART.md` (3), `tasks/040-plan-code-identifier-rename.md` (1); `tasks/done/**` (1 files, 1); `tasks/handoffs/**` (3 files, 3).

Codex permission profile `meridian-worktrees` (group 2, rule 6):

- Group 1 (renamed in 5a): none.
- Group 2 (renamed in 5b): 6 files, 26 occurrences. `docs/HOST_CAPABILITY_CONTRACT.md` (1), `src/cardine/shared/models.py` (1), `tests/test_host_codex_access.py` (5), `tests/test_host_codex_repair.py` (11), `tests/test_host_worktree_setup.py` (2), `tests/test_queue_briefing.py` (6).
- Group 3 (frozen until item 10): none.
- Group 4 (historical, kept): none.

### 9. Tracked paths whose name contains `meridian`

The inventory counts file names as well as file contents. `git ls-files | grep -i meridian`
lists 82 paths: 9 under `.meridian/baselines/` and 39 under `.meridian/tasks/`, which
the table summarizes, and the 34 below.

| Path | Group | New name or fate |
|---|---|---|
| `bin/meridian` | 1 | `bin/cardine` (R5) |
| `scripts/meridian.py` | 1 | `scripts/cardine_cli.py` (R5) |
| `tests/meridian_cli_support.py` | 1 | `tests/cardine_cli_support.py` (R5) |
| `tests/test_meridian_adoption_audit.py`, `tests/test_meridian_cli_entry.py`, `tests/test_meridian_manifest_protocol.py`, `tests/test_meridian_migration_retirement.py`, `tests/test_meridian_upgrade_lifecycle.py`, `tests/test_meridian_upgrade_merge.py` | 1 | `tests/test_cardine_*.py` with the same suffixes (R5) |
| `.codex/rules/meridian.rules` | 3 | unchanged until item 10; its template copies are group 2 |
| `templates/workflows/governed-sdd/.codex/rules/meridian.rules`, `templates/workflows/lean-delivery/.codex/rules/meridian.rules` | 2 | renamed in 5b |
| `commands/meridian-adopt.md`, `meridian-audit.md`, `meridian-init.md`, `meridian-task.md`, `meridian-upgrade.md` | 2 | renamed in 5b |
| `skills/meridian-governed-sdd/SKILL.md`, `skills/meridian-governed-sdd-claude-code/SKILL.md`, `skills/meridian-lean-delivery/SKILL.md`, `skills/meridian-lean-delivery-claude-code/SKILL.md` | 2 | renamed in 5b |
| `.meridian/candidate-validation.json`, `flow-targets.json`, `manifest.json`, `probes/meridian-self-hosting/*.json` (3), plus `.meridian/baselines/1.4.0/**` (9) and `.meridian/tasks/*.json` (39) | 3 | unchanged until item 10; the converted repository gets `.cardine/` |
| `docs/MERIDIAN_SELF_HOSTING_PROFILE.md` | 4 | kept |
| `docs/assets/meridian-mark.svg`, `meridian-mark-dark.svg`, `meridian-mark-light.svg`, `meridian-social-preview.png` | 4 | kept; work item 11 replaces the branding |
| `tasks/done/023-split-meridian-cli-test-class.md`, `tasks/done/039-check-self-hosting-with-installed-meridian.md` | 4 | kept |

## Group 3: the frozen surfaces

Until work item 10 the installed Meridian owns these paths and checks them
(task 039; `meridian profile doctor meridian-self-hosting --project .` and
`meridian audit --project . --mode lean-delivery --ci-profile
meridian-self-hosting` are part of this plan's validation). Changing one fails
the installed Meridian's digest or profile check.

| Kind | Paths |
|---|---|
| Managed copies (`managedFiles`, 10) | `.codex/hooks.json`, `.codex/rules/meridian.rules`, `AGENTS.md`, `CLAUDE.md`, `LANGUAGE_POLICY.md`, `PROJECT_WORKFLOW.md`, `docs/COMPLETION_REPORT_TEMPLATE.md`, `docs/CONTEXT_BUDGET_POLICY.md`, `docs/EXECUTION_EVIDENCE_PROFILE.md`, `docs/WORKTREE_LIFECYCLE.md` |
| `managedSurface` entries of the `meridian-self-hosting` profile (12) | the nine managed copies above (every one except `docs/WORKTREE_LIFECYCLE.md`, which only `managedFiles` lists) and the three shared-source hooks |
| Shared-source hooks (3) | `hooks/hooks.json`, `hooks/queue-briefing.sh`, `hooks/read-guard.sh` |
| Installation directory (54 tracked files) | `.meridian/manifest.json`, `.meridian/candidate-validation.json`, `.meridian/flow-targets.json`, `.meridian/baselines/1.4.0/**` (9), `.meridian/probes/meridian-self-hosting/*.json` (3), `.meridian/tasks/*.json` (39) |
| Outside the manifest, by the rule of finding 3 | the `meridian worktree` line of `.codex/rules/local.rules` |

`.meridian/tasks/<id>.json` is written only by the installed `meridian task
close` and `execution` commands. `docs/WORKTREE_LIFECYCLE.md` is a managed copy
and also the document the worktree commands print; 5a does not edit it.

## Frozen-surface readers

A reader is a product check in `scripts/check_repository.py`, a test, or a
product command that reads a group 3 path on this repository. The rule for
every row: after its rename task the reader either keeps reading the installed
Meridian's record **by its Meridian name, as an explicit installation check**
(the name is written in one place, tagged `MERIDIAN-INSTALLATION-CHECK`, and
removed by item 10), or it stops reading this repository. No reader reaches a
group 3 file through a renamed constant. Every line in rows 1–3, 9, 10, 12, and 13 that names a group 3 path carries the tag `MERIDIAN-INSTALLATION-CHECK`, on the line itself or on the line above it. Every row below was verified in the working
tree at the baseline.

### Product checks

| # | Reader | Reads at the baseline | Behavior after 5a |
|---|---|---|---|
| 1 | `check_required_files` | existence of `hooks/hooks.json`, `hooks/queue-briefing.sh`, `.meridian/probes/meridian-self-hosting/{host-neutral-ci,claude-project,codex-project}-v1.json`; also `bin/meridian`, `scripts/meridian.py` (group 1) and skill and command paths (group 2) | R3 splits `REQUIRED_FILES` into the product files and a separate `INSTALLED_MERIDIAN_RECORDS` tuple tagged as an explicit installation check. The three probe paths and two hooks keep their Meridian names. R5 renames the two executables in the product tuple; the skill and command paths wait for 5b. |
| 2 | `check_stop_code_registry` → `managed_stop_text_files` | `.meridian/manifest.json` (literal path), the digests in `managedFiles`, and every managed `.md` copy whose digest differs | R3 keeps the literal `.meridian/manifest.json` and tags it `MERIDIAN-INSTALLATION-CHECK`; the script imports nothing from `cardine.legacy`; behavior is unchanged. The stop registry itself (`capabilities/stop-codes-v1.json`) is group 1. |
| 3 | `check_managed_digests` → `managed_digest_diagnostics` | `.meridian/manifest.json`, all ten `managedFiles` digests, every `managedSurface` path | Same tagged literal as row 2. It calls the product's `managed_copy_drift(root, managed_files)` with an explicit digest map and `sha256`; R3 adds a test that neither function consults the default names (a Meridian-layout manifest passed to them with the default names flipped still gives the same diagnostics). |
| 4 | `check_governed_lifecycle_text` | `PROJECT_WORKFLOW.md` (one retired-phrase check) and `templates/workflows/**/*.md` | Unchanged. The file name is not renamed. Its `MANAGED_BLOCK` pattern reads `MERIDIAN:BEGIN` in templates (group 2, 5b). |
| 5 | `check_language_policy` | **No group 3 file.** It reads `templates/**/LANGUAGE_POLICY.md`, template entry files, `commands/meridian-task.md`, and two files under `skills/`; all group 2. | The task's list names it as a group 3 reader; at the baseline it is not one. Unchanged by 5a. Its skill and command paths change in 5b. |
| 6 | `check_json`, `check_bash`, `check_local_markdown_links`, `check_no_machine_paths`, `check_no_private_names` | every tracked file, including group 3 | Name-agnostic content scans. Unchanged. This plan contains no absolute home path and no link to a missing file for that reason. |
| 7 | `check_generated_templates` (`scripts/dev.py generate-entry-routers --mode <mode> --check`) | `templates/workflows/<mode>/AGENTS.md` and `CLAUDE.md` only | Not a group 3 reader (the root `CLAUDE.md` and `AGENTS.md` are not read when `--mode` is given). Unchanged. |
| 8 | `check_capability_catalog`, `check_capability_marker_baselines`, `check_capability_required_versions`, `check_plugin_version`, `check_governed_review_worktree_contract` | `capabilities/**`, templates, `.claude-plugin/plugin.json` | Not group 3 readers. `check_capability_catalog` asserts the profile id `meridian-self-hosting` in this repository's catalog; R8 changes it to `cardine-self-hosting`. |

### Tests

| # | Reader | Reads at the baseline | Behavior after 5a |
|---|---|---|---|
| 9 | `tests/test_queue_briefing.py`, `tests/test_read_guard.py` | run the frozen `hooks/queue-briefing.sh` and `hooks/read-guard.sh` at `ROOT`; the hooks use `ROOT/bin/meridian`, else `command -v meridian` | R3 replaces every run at `ROOT` with a **temporary hook root**: a copy of the frozen hook plus a `bin/meridian` shim that executes the product entry point (`bin/cardine` after R5). The shim is a test fixture, not a product alias. After 5a no test resolves `meridian` from `PATH`. The `setup --check` keys the hook parses do not change (R10). |
| 10 | `tests/test_codex_worktree_hooks.py` | `.codex/hooks.json` as data; asserts its first word is `meridian`, then replays `hook read-guard` and `hook stop-audit` through the product entry point by path | Unchanged logic: the frozen file's own command word is asserted as installation data; the replay uses `scripts/cardine_cli.py` after R5 and the journal name from the product constant after R9. |
| 11 | `tests/test_codex_rules.py` | `.codex/rules/meridian.rules` beside the two template copies: single-line rules, push allowlist, identical closure block | Unchanged by 5a. The "identical closure block in every shipped file" assertion compares frozen text with templates; 5b must exclude the frozen copy once the templates change. |
| 12 | `tests/test_template_manifest.py` | `ROOT` as a project for `profile doctor` (lines 273–310); `ROOT / MANIFEST_PATH` at line 393; a copy of `ROOT/.meridian/probes` at line 297; `docs/EXECUTION_EVIDENCE_PROFILE.md` at line 861 | R3 builds a synthetic installation from a fixture builder (in product names, through the accessor) for every doctor case. Line 393 reads the manifest through a tagged literal `.meridian/manifest.json`, so renaming `MANIFEST_PATH` cannot silently change it. Line 861 reads the managed copy as plain text and is unchanged. |
| 13 | `tests/test_check_repository.py` | `ManagedDigestTest` (a copy of `ROOT`; edits `.meridian/manifest.json`; reads the frozen manifest's profile key `meridian-self-hosting`; `test_repository_check_and_profile_doctor_agree_on_drift` runs the product's `profile_doctor` on the copy); `GovernedLifecycleTextTest` (copies `PROJECT_WORKFLOW.md`); `test_repository_passes` (`check_stop_code_registry(ROOT)`); `test_repository_has_no_machine_paths` | The cases of `ManagedDigestTest` that call `check_managed_digests` or read the frozen manifest keep the tagged literal (the profile key is the frozen manifest's own and is tagged). `test_repository_check_and_profile_doctor_agree_on_drift` is the only case that runs the product's doctor on the copy; it moves to a synthetic installation, because the property it proves, that the check and the doctor agree on a drifted managed copy, does not depend on this repository's data. `test_repository_check_ignores_checkout_profile_surface_changes` runs the whole check on the copy and follows the renames (its expected last line changes in R10). |
| 14 | `tests/test_codex_read_guard.py`, `tests/test_stop_audit.py`, `tests/test_host_worktree_setup.py`, `tests/test_host_codex_access.py` | the **template** copies of the hooks and rules (group 2), plus synthetic projects | Not group 3 readers. They follow the group 2 rule of "Rules" item 5. |

### Documents asserted by tests

These group 4 (or group 2) files are read as contracts by a test. A test that
keeps passing against a document about a removed command asserts something
false, so each is decided here.

| Test | Document | Behavior after 5a |
|---|---|---|
| `tests/test_cli_install.py` (`test_quickstart_installs_one_canonical_checkout…` and the `~/meridian` loop) | `docs/QUICKSTART.md`, `README.md`, `docs/HOW_TO_UPGRADE.md` (`MERIDIAN_ROOT`, `command -v meridian`, `meridian --version`) | Retired in R5. The documents are group 4 and describe a command and variable the product no longer has. The wrapper tests in the same file stay and follow `bin/cardine`. Work item 11 adds install tests for the documents it writes. |
| `tests/test_public_surface.py` | `docs/PUBLIC_SURFACE.md` (rows `` `meridian <command>` `` compared with the parser), `README.md` (`` `meridian usage` `` named experimental) | R6 renames the table rows and `prog` together (group 1 exception). The README assertion is retired in R6; the inventory test already checks the `experimental` label in each Experimental command's help. |
| `tests/test_lean_walkthrough.py` | `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md` (executed; uses `meridian`, `MERIDIAN_ROOT`, `MERIDIAN_WORKTREE_ROOT`, `.meridian`) | Executed documentation, so group 1. R6, R7, R8, and R9 each edit the identifiers of their class in the walkthrough and in the test's environment. |
| `tests/test_host_codex_repair.py` (line 301) | `docs/HOST_CAPABILITY_CONTRACT.md` fragments (`repair-required`, ``Explicit `--apply` ``, `does not prove`, `profile-ownership`) | No identifier is asserted and the recovery contract still exists in 5a, so the assertion stays true. Work item 11 moves it with the document. |
| `tests/test_host_codex_access.py` (line 268) | `commands/meridian-init.md` (the text `meridian setup --check`, and `meridian setup --apply` offered only after explicit confirmation) | Group 2. R6 rewrites the assertion without the program word (the subcommand, flag, and phrases); 5b adds the program word `cardine` back. |
| `tests/test_ci_evidence.py` | `.github/workflows/validate.yml` | Names no identifier. Unchanged. |

### Product commands

| # | Reader | Reads at the baseline | Behavior after 5a |
|---|---|---|---|
| 15 | `cardine.console.snapshot.load_snapshot` and `load_task`, run by the coordinator on this repository | `.meridian/tasks/*.json`; `.git/meridian-worktrees/*.json`, `.git/meridian-integration.lock`, `.git/meridian-integration.json` (all written by the **installed** Meridian); `.meridian/execution-evidence.json`; `PROJECT_WORKFLOW.md` for the mode lock and the `MERIDIAN:BEGIN capability=execution-assets` block (`detect_mode`, `resolve_project_locations`); `tasks/QUEUE.md`; task worktrees under `~/.meridian/worktrees` | See "The coordinator snapshot" below. |
| 16 | `cardine profile doctor`, `cardine audit`, `scripts/dev.py profile doctor` or `profile bootstrap` | `.meridian/manifest.json`, baselines, probes of the project | After R8 they read `.cardine/` only. They **stop reading this repository**: its installation is checked only by the installed `meridian` (task 039; the validation commands of this plan). `tests/test_dev_commands.py` mocks the doctor and is unaffected. |
| 17 | `capabilities/stop-codes-v1.json` read by the coordinator for `human_decision` | the registry file (group 1) | R6 changes only the `resume` command text of entries (117 `meridian` words). It never changes a `code`, a `human_decision` value, or the file's schema, so the coordinator's decision about a `BLOCKED <CODE>` stays correct throughout. |
| 18 | the frozen hooks' calls into the CLI | `locations --field queue`, `worktree states`, `worktree active`, `context size`, `context authority`, `budget show`, `setup --check`, `hook stop-audit` | Subcommand and flag names do not change in 5a; only the program word does. The hooks reach the product through the shim of row 9 in tests. |

### The coordinator snapshot

The coordinator calls `load_snapshot(project)`. After 5a that function reads
the **Cardine** names only: a project with `.meridian/tasks` and
`.git/meridian-worktrees` and nothing else shows no task state and no worktree.
Reading this repository would need the Meridian names, and accepting them
inside `load_snapshot` would be the alias that decision 1 forbids, so the plan
does **not** auto-detect the layout. Instead:

1. R2 adds `cardine.legacy.meridian_installation.load_meridian_snapshot(project)`,
   an explicit installation check. It runs the same snapshot builder under the
   Meridian names (section "Group 5") and is dispatched by no command.
2. The coordinator switches its call for this repository from `load_snapshot`
   to `load_meridian_snapshot` when R2 integrates. R2's handoff states the
   call. R8 may not start until the developer or coordinator confirms the
   switch in R8's task record, because R8 is the first task that makes
   `load_snapshot` blind to this repository.
3. Item 10 deletes `load_meridian_snapshot` when it converts this repository.

The same dependency has a second break that 5a does not cause but 5b will:
`resolve_project_locations` reads the `MERIDIAN:BEGIN capability=execution-assets`
marker of the frozen `PROJECT_WORKFLOW.md`. When 5b renames the marker in
product code, the snapshot's `execution-assets` lookup must go through the
group 5 marker reader whenever the layout is the Meridian installation. That is
one more reason for group 5 to be one module (see the last section).

## Group 5: the read-only Meridian reader

ADR work item 5a requires one read-only reader of `.meridian/` and
`MERIDIAN:BEGIN` markers for item 10. At the baseline the product has none that
is separate from its general code, so group 5 has **no occurrences yet**. This
plan defines it:

| Aspect | Decision |
|---|---|
| Module | `src/cardine/legacy/meridian_installation.py`, in a new package `src/cardine/legacy/` with an empty `__init__.py`. The only product module allowed to hold Meridian names besides group 2 text, until 5b and item 10 remove them. |
| Seeded from | today's constants, copied once by R2 as literals: `.meridian` and its files (`manifest.json`, `baselines/`, `tasks/<id>.json`, `task-identity.json`, `project.json`, `candidate-validation.json`, `execution-evidence.json`, `flow-targets.json`, `context-size.json`, `probes/`); the Git-internal names (`meridian-journal.jsonl`, `meridian-journal.1.jsonl`, `meridian-integration.lock`, `meridian-integration.json`, `meridian-worktrees/`); the worktree root `~/.meridian/worktrees` and the user configuration `meridian/config.json`. They live in a frozen dataclass `MERIDIAN_INSTALLATION_NAMES`. The marker patterns are seeded from `CAPABILITY_MARKER` and `MARKED_BLOCK` in `shared/constants.py`. |
| What it reads | the files above, read-only. It writes nothing, creates no directory, and runs no Git mutation. The module also holds the read-only `MERIDIAN:BEGIN` marker reader that ADR work item 5a names. In 5a it has no consumer, because every template operation still reads the same markers through the general code; 5b flips the general code to `CARDINE:BEGIN`, and this reader keeps the Meridian patterns. |
| What it exposes | `MERIDIAN_INSTALLATION_NAMES`; `is_meridian_installation(project)` (true when `.meridian/manifest.json` exists); `read_manifest(project)`; `read_task_state_file(project, task_id)`; `marker_blocks(text)`; and `load_meridian_snapshot(project)`. Item 10 adds the conversion readers. |
| Dispatch | None. No `argparse` command, hook, script, or module of `src/cardine/` outside the package imports it. A test walks the import graph (AST) over `src/cardine/`, `scripts/`, and `hooks/` and fails on any import of `cardine.legacy` from there; tests may import it. `scripts/check_repository.py` keeps tagged literals and imports nothing from the package. |
| Product names | The product's own names sit in `src/cardine/shared/layout.py`: a `ProjectNames` dataclass, `PRODUCT_NAMES` (equal to the Meridian values until R8 and R9 flip them), `names()`, and a context manager `use(names)` backed by a `ContextVar`. Modules read names through `names()` at call time. `load_meridian_snapshot` runs the builder inside `use(MERIDIAN_INSTALLATION_NAMES)`. |
| Guard | The guard test of the last task exempts exactly this module, its test, lines tagged `MERIDIAN-INSTALLATION-CHECK`, and tests tagged `MERIDIAN-OLD-NAME-TEST` (see R10). Nothing else in `src/cardine/` may name Meridian outside group 2. |

Not designed here: the converter of item 10 (open tasks, ADR log, project
configuration) and the `MERIDIAN:BEGIN` reader of 5b.


## Task sequence

Ten tasks, strictly in this order. **No two run in parallel.** The overlap
matrix over the baseline file sets shows that every pair among R4–R10 shares
files (the smallest overlap, R7 with R8, is 8 files; the largest, R5 with R6,
is 53), and R2 and R3 build on the names that R1 creates, so each task depends on
the previous one. Each is 2–3 hours, lands with the full suite, the repository
check, and the installed-Meridian validation green, and runs these validation
commands from its task worktree:

```bash
python3 scripts/run_tests.py --parallel
python3 scripts/check_repository.py
meridian profile doctor meridian-self-hosting --project .
meridian audit --project . --mode lean-delivery --ci-profile meridian-self-hosting
git diff --check
```

Every task from R4 on adds a test that the **old name is ignored** (the proof
that it is not an alias). Work item 6 (task 041's plan) and these tasks edit the
same files (`tasks/identity.py`, `console/snapshot.py`, `shared/models.py`), so
item 6's tasks start after R10.


### R1 — Introduce the names accessor (3 h)

- **Scope.** Create `src/cardine/shared/layout.py` with a frozen `ProjectNames`
  dataclass, `PRODUCT_NAMES`, `names()`, and a context manager `use(names)`
  backed by a `ContextVar` (the pattern `shared/git.py` already uses for
  `_SHARED_WORKTREES`). Replace the `.meridian`, Git-internal, and
  worktree-root literals and constants that the snapshot path reads with reads
  through `names()` at call time, not at import time. `PRODUCT_NAMES` still holds
  the Meridian values, so behavior does not change.
- **Files.** New: `src/cardine/shared/layout.py`, `tests/test_layout.py`.
  Changed (group 1 source files that name `.meridian`, a Git-internal file, or
  the worktree root): `src/cardine/hosts/setup.py`, `src/cardine/lifecycle/closure.py`, `src/cardine/shared/constants.py`, `src/cardine/shared/context.py`, `src/cardine/shared/flow.py`, `src/cardine/shared/git.py`, `src/cardine/shared/journal.py`, `src/cardine/shared/models.py`, `src/cardine/tasks/audit.py`, `src/cardine/tasks/contract.py`, `src/cardine/tasks/identity.py`, `src/cardine/tasks/state.py`, `src/cardine/worktree/checkout.py`, `src/cardine/worktree/storage.py`; also `src/cardine/console/snapshot.py`.
- **Tests that prove it.** For each threaded reader (`state_path`, the
  identity and project-declaration paths, the execution-evidence path, the
  lifecycle directory, lease, and state names, the journal names, and the
  worktree root and user-configuration paths), a test that `use(other_names)`
  changes the path it reads or writes and that the default is unchanged
  outside the context; the full suite, unchanged.
- **Depends on.** none.

### R2 — Extract the group 5 reader and the explicit snapshot (3 h)

- **Scope.** Create `src/cardine/legacy/` with `meridian_installation.py`
  holding `MERIDIAN_INSTALLATION_NAMES` (the Meridian values, copied once as
  literals), the read-only `.meridian/` readers, the read-only
  `MERIDIAN:BEGIN` marker reader, and `load_meridian_snapshot`, which runs the
  snapshot builder inside `use(MERIDIAN_INSTALLATION_NAMES)`. No command, hook,
  or script dispatches to it.
- **Files.** New: `src/cardine/legacy/__init__.py`,
  `src/cardine/legacy/meridian_installation.py`,
  `tests/test_legacy_meridian_installation.py`. Changed:
  `src/cardine/console/snapshot.py` (an optional builder entry point that the
  legacy module calls) and `tests/test_console_snapshot.py`.
- **Tests that prove it.** (1) `load_meridian_snapshot` on a synthetic
  Meridian-layout project built by the test equals the current `load_snapshot`
  result for it. (2) A test records every path the snapshot opens and fails if
  a path containing `meridian` is not one the layout declares; R8 and R9 are
  held to that list. (3) The marker reader returns the blocks and versions of a
  Meridian-marked text and matches `CAPABILITY_MARKER` and `MARKED_BLOCK` on the
  templates. (4) The import-graph test of "Group 5". (5) The full suite,
  unchanged.
- **Depends on.** R1.
- **Gate for the coordinator.** R2's handoff states the new call (see the
  coordinator snapshot).


### R3 — Decouple the group 3 readers (3 h)

- **Scope.** Rows 1–3, 9, 12, and 13 of the reader table: split
  `REQUIRED_FILES`, keep the literal `.meridian/manifest.json` paths,
  tag every explicit installation check `MERIDIAN-INSTALLATION-CHECK`, move
  the hook tests to the temporary hook root with the `bin/meridian` shim, move
  the doctor cases of `test_template_manifest.py` and
  `test_check_repository.py` to a synthetic installation, and add a test that
  fails when a test spawns `meridian` through `PATH`. No name changes.
- **Files.** `scripts/check_repository.py`, `tests/test_check_repository.py`,
  `tests/test_template_manifest.py`, `tests/test_queue_briefing.py`,
  `tests/test_read_guard.py`, `tests/test_codex_worktree_hooks.py`, and a new
  fixture builder `tests/installation_fixture.py`.
- **Tests that prove it.** The reworked tests themselves, plus a test that fails
  when a reader in rows 1–3 opens a group 3 path through `names()` instead of
  its tagged literal (it flips `PRODUCT_NAMES` inside the test and re-runs the
  checks).
- **Depends on.** R2.

### R4 — Rename the exception and parser classes (2 h)

- **Scope.** `MeridianError`, `MeridianStop`, `MeridianArgumentParser` and
  every reference, by word-boundary substitution. `InternalStopError` and the
  other class names are untouched.
- **Files.** 79 files, 548 occurrences: `scripts/check_repository.py`, `scripts/codex_read_guard.py`, `scripts/dev.py`, `scripts/meridian.py`, `src/cardine/cli.py`, `src/cardine/console/snapshot.py`, `src/cardine/hosts/claude.py`, `src/cardine/hosts/codex.py`, `src/cardine/hosts/setup.py`, `src/cardine/integration/evidence.py`, `src/cardine/integration/merge.py`, `src/cardine/integration/projections.py`, `src/cardine/lifecycle/closure.py`, `src/cardine/lifecycle/commands.py`, `src/cardine/lifecycle/execution.py`, `src/cardine/release/update.py`, `src/cardine/release/version.py`, `src/cardine/review/verdict.py`, `src/cardine/shared/authority.py`, `src/cardine/shared/context.py`, `src/cardine/shared/errors.py`, `src/cardine/shared/flow.py`, `src/cardine/shared/git.py`, `src/cardine/shared/journal.py`, `src/cardine/shared/jsonio.py`, `src/cardine/shared/project.py`, `src/cardine/shared/usage.py`, `src/cardine/shared/validation.py`, `src/cardine/stops/render.py`, `src/cardine/tasks/audit.py`, `src/cardine/tasks/contract.py`, `src/cardine/tasks/identity.py`, `src/cardine/tasks/importer.py`, `src/cardine/tasks/recording.py`, `src/cardine/tasks/transitions.py`, `src/cardine/templates/adoption.py`, `src/cardine/templates/audit.py`, `src/cardine/templates/catalog.py`, `src/cardine/templates/files.py`, `src/cardine/templates/generator.py`, `src/cardine/templates/manifest.py`, `src/cardine/templates/marker_audit.py`, `src/cardine/templates/merge.py`, `src/cardine/templates/migrations.py`, `src/cardine/templates/mode.py`, `src/cardine/templates/protocol.py`, `src/cardine/templates/router.py`, `src/cardine/templates/upgrade.py`, `src/cardine/worktree/checkout.py`, `src/cardine/worktree/closure_status.py`, `src/cardine/worktree/paths.py`, `src/cardine/worktree/storage.py`, `tests/fixtures/module_split_baseline.json`, `tests/test_cardine_cli.py`, `tests/test_check_repository.py`, `tests/test_codex_user_rules.py`, `tests/test_console_closure.py`, `tests/test_console_snapshot.py`, `tests/test_execution_boundaries.py`, `tests/test_host_codex_access.py`, `tests/test_host_codex_repair.py`, `tests/test_host_worktree_setup.py`, `tests/test_integration_projections.py`, `tests/test_lifecycle_journal_flow.py`, `tests/test_machine_task_state.py`, `tests/test_marker_structure_audit.py`, `tests/test_meridian_manifest_protocol.py`, `tests/test_queue_archival_state.py`, `tests/test_self_update.py`, `tests/test_task_close.py`, `tests/test_task_identity_project.py`, `tests/test_task_integration_state.py`, `tests/test_template_manifest.py`, `tests/test_template_router.py`, `tests/test_template_surface_upgrade.py`, `tests/test_usage_report.py`, `tests/test_worktree_checkout.py`, `tests/test_worktree_cleanup.py`, `tests/test_worktree_integration.py`.
- **Tests that prove it.** The full suite; a test that `cardine.shared.errors`
  has no attribute `MeridianError` and that `build_parser()` returns a
  `CardineArgumentParser`.
- **Depends on.** R3.

### R5 — Rename the executables, the adapter module, and the test modules (3 h)

- **Scope.** `bin/meridian` → `bin/cardine`; `scripts/meridian.py` →
  `scripts/cardine_cli.py`; the `import meridian` alias and its attributes in 36
  files → `cardine_cli`; `tests/meridian_cli_support.py` →
  `tests/cardine_cli_support.py`; `MeridianCliFixtureMixin`, `MeridianCliTest`;
  the six `tests/test_meridian_*.py` → `tests/test_cardine_*.py`; the
  `python3 scripts/meridian.py` allowlist entries in `hosts/claude.py` and the
  three `python3 scripts/meridian.py` lines of `.codex/rules/local.rules`, which
  R5 **deletes** instead of renaming, because approving `scripts/cardine_cli.py`
  would auto-approve the renamed product's lifecycle on this repository, which
  the choices section forbids before item 10; `tests/fixtures/module_split_baseline.json`
  and `tests/test_module_inventory.py`. Retire the QUICKSTART assertions of
  `test_cli_install.py`. Update the shim of R3 to execute `bin/cardine`.
- **Files.** 63 files, 198 occurrences: `.codex/rules/local.rules`, `capabilities/stop-codes-v1.json`, `docs/PUBLIC_SURFACE.md`, `hooks/stop-audit.sh`, `scripts/align_queue.py`, `scripts/check_repository.py`, `scripts/release.py`, `src/cardine/hosts/claude.py`, `src/cardine/hosts/setup.py`, `src/cardine/shared/models.py`, `tests/fixtures/module_split_baseline.json`, `tests/meridian_cli_support.py`, `tests/stop_recovery_support.py`, `tests/synthetic_upgrade_support.py`, `tests/test_authority_excerpt.py`, `tests/test_cardine_cli.py`, `tests/test_check_repository.py`, `tests/test_cli_install.py`, `tests/test_codex_read_guard.py`, `tests/test_codex_rules.py`, `tests/test_codex_user_rules.py`, `tests/test_codex_worktree_hooks.py`, `tests/test_context_size.py`, `tests/test_dev_commands.py`, `tests/test_execution_boundaries.py`, `tests/test_execution_evidence.py`, `tests/test_host_codex_access.py`, `tests/test_host_codex_repair.py`, `tests/test_host_worktree_setup.py`, `tests/test_integration_projections.py`, `tests/test_launcher_task_audit.py`, `tests/test_lifecycle_journal_flow.py`, `tests/test_machine_task_state.py`, `tests/test_marker_structure_audit.py`, `tests/test_meridian_adoption_audit.py`, `tests/test_meridian_cli_entry.py`, `tests/test_meridian_manifest_protocol.py`, `tests/test_meridian_migration_retirement.py`, `tests/test_meridian_upgrade_lifecycle.py`, `tests/test_meridian_upgrade_merge.py`, `tests/test_module_inventory.py`, `tests/test_queue_briefing.py`, `tests/test_read_guard.py`, `tests/test_release.py`, `tests/test_release_self_check.py`, `tests/test_review_verdict.py`, `tests/test_self_update.py`, `tests/test_stop_audit.py`, `tests/test_synthetic_upgrade.py`, `tests/test_task_close.py`, `tests/test_task_identity_project.py`, `tests/test_task_integration_state.py`, `tests/test_task_state_import.py`, `tests/test_task_state_lookups.py`, `tests/test_template_manifest.py`, `tests/test_template_marker_heading.py`, `tests/test_template_retirement.py`, `tests/test_template_router.py`, `tests/test_template_surface_upgrade.py`, `tests/test_validation_evidence.py`, `tests/test_worktree_checkout.py`, `tests/test_worktree_cleanup.py`, `tests/test_worktree_lifecycle.py`; plus the renamed paths.
- **Tests that prove it.** The full suite; `test_cli_install.py` wrapper tests
  against `bin/cardine`; a test that `bin/meridian` and `scripts/meridian.py` do
  not exist and that `pyproject.toml` registers only `cardine`; a test that
  `scripts/` contains no `cardine.py`.
- **Depends on.** R4.

### R6 — Rename the command word in output and data (3 h)

- **Scope.** `prog="meridian"`; every resume command and recovery string
  (`worktree/checkout.py`, `worktree/closure_status.py`, `lifecycle/closure.py`,
  `lifecycle/execution.py`, `integration/merge.py`, `console/models.py`,
  `tasks/transitions.py`, `cli.py`); the resume templates of
  `capabilities/stop-codes-v1.json` (117 occurrences of the command word); the generated Claude allowlist and the
  Codex user rules in `hosts/claude.py` and `hosts/codex.py`; `scripts/align_queue.py`
  (`shutil.which("cardine")`, `--cardine`); `hooks/stop-audit.sh`; the rows of
  `docs/PUBLIC_SURFACE.md` and the commands of the Lean walkthrough. Group 2
  couplings stay Meridian-named: the `setup.py` execpolicy probe, the skill and
  command paths, and the `skills.py` glob. Tests that compare generated output
  with template text normalize the program word through one helper marked
  `# remove in 5b`. Retire the README assertion of `test_public_surface.py` and
  make `test_host_codex_access.py` line 268 independent of the program word.
- **Files.** 93 files, 493 occurrences: `README.md`, `capabilities/stop-codes-v1.json`, `docs/PUBLIC_SURFACE.md`, `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md`, `evals/lib/lean-project.sh`, `evals/scenarios/governed-remediation-completes/setup.sh`, `hooks/stop-audit.sh`, `scripts/align_queue.py`, `scripts/check_repository.py`, `scripts/codex_read_guard.py`, `scripts/release.py`, `scripts/upgrade_project.sh`, `src/cardine/cli.py`, `src/cardine/console/models.py`, `src/cardine/hosts/claude.py`, `src/cardine/hosts/codex.py`, `src/cardine/integration/merge.py`, `src/cardine/integration/projections.py`, `src/cardine/lifecycle/closure.py`, `src/cardine/lifecycle/execution.py`, `src/cardine/release/update.py`, `src/cardine/shared/context.py`, `src/cardine/tasks/contract.py`, `src/cardine/tasks/preflight.py`, `src/cardine/tasks/recording.py`, `src/cardine/tasks/transitions.py`, `src/cardine/templates/audit.py`, `src/cardine/templates/catalog.py`, `src/cardine/templates/manifest.py`, `src/cardine/templates/marker_audit.py`, `src/cardine/templates/marker_history.py`, `src/cardine/templates/markers.py`, `src/cardine/templates/merge.py`, `src/cardine/worktree/checkout.py`, `src/cardine/worktree/closure_status.py`, `tests/console_support.py`, `tests/fixtures/task-blueprint-v15.md`, `tests/meridian_cli_support.py`, `tests/stop_recovery_support.py`, `tests/synthetic_upgrade_support.py`, `tests/test_authority_excerpt.py`, `tests/test_cardine_cli.py`, `tests/test_check_repository.py`, `tests/test_ci_evidence.py`, `tests/test_cli_install.py`, `tests/test_codex_read_guard.py`, `tests/test_codex_rules.py`, `tests/test_codex_user_rules.py`, `tests/test_codex_worktree_hooks.py`, `tests/test_console_closure.py`, `tests/test_console_snapshot.py`, `tests/test_console_states.py`, `tests/test_context_size.py`, `tests/test_execution_boundaries.py`, `tests/test_execution_evidence.py`, `tests/test_host_codex_access.py`, `tests/test_host_codex_repair.py`, `tests/test_host_worktree_setup.py`, `tests/test_integration_projections.py`, `tests/test_launcher_task_audit.py`, `tests/test_lifecycle_journal_flow.py`, `tests/test_machine_task_state.py`, `tests/test_marker_structure_audit.py`, `tests/test_meridian_adoption_audit.py`, `tests/test_meridian_cli_entry.py`, `tests/test_meridian_manifest_protocol.py`, `tests/test_meridian_migration_retirement.py`, `tests/test_meridian_upgrade_lifecycle.py`, `tests/test_meridian_upgrade_merge.py`, `tests/test_prepare_release.py`, `tests/test_public_surface.py`, `tests/test_queue_archival_state.py`, `tests/test_queue_briefing.py`, `tests/test_read_guard.py`, `tests/test_release.py`, `tests/test_release_self_check.py`, `tests/test_review_verdict.py`, `tests/test_self_update.py`, `tests/test_stop_audit.py`, `tests/test_task_close.py`, `tests/test_task_integration_state.py`, `tests/test_task_state_import.py`, `tests/test_task_state_lookups.py`, `tests/test_template_manifest.py`, `tests/test_template_marker_heading.py`, `tests/test_template_surface_upgrade.py`, `tests/test_usage_report.py`, `tests/test_validation_evidence.py`, `tests/test_worktree_checkout.py`, `tests/test_worktree_cleanup.py`, `tests/test_worktree_lifecycle.py`, `tests/test_worktree_paths.py`, `tests/worktree_support.py`.
- **Tests that prove it.** The full suite; every resume command in the registry
  starts with `cardine` and no `code` or `human_decision` value changed (the
  test compares both sets with the baseline file); an invocation named
  `meridian` through the parser is not a command.
- **Depends on.** R5.

### R7 — Rename the environment names and options (2 h)

- **Scope.** `MERIDIAN_ROOT`, `MERIDIAN_WORKTREE_ROOT`, `MERIDIAN_TEST_SHARD`,
  `MERIDIAN_FAILURE_VISIBILITY_PROBE`, `MERIDIAN_SESSION_NOT_FOUND`,
  `MERIDIAN_BIN` in `hooks/stop-audit.sh`, `meridian_root_state/value`,
  `--meridian-root`. The frozen hooks keep `MERIDIAN_BIN`. Edit the walkthrough
  and `test_lean_walkthrough.py` environment.
- **Files.** 25 files, 91 occurrences: `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md`, `hooks/stop-audit.sh`, `scripts/align_queue.py`, `scripts/release.py`, `scripts/run_agent_evals.py`, `scripts/run_tests.py`, `scripts/upgrade_project.sh`, `src/cardine/cli.py`, `src/cardine/console/launch.py`, `src/cardine/hosts/setup.py`, `src/cardine/lifecycle/closure.py`, `src/cardine/worktree/storage.py`, `tests/stop_recovery_support.py`, `tests/test_cardine_cli.py`, `tests/test_cli_install.py`, `tests/test_console_launch.py`, `tests/test_execution_boundaries.py`, `tests/test_host_codex_repair.py`, `tests/test_host_worktree_setup.py`, `tests/test_launcher_task_audit.py`, `tests/test_lean_walkthrough.py`, `tests/test_release.py`, `tests/test_run_tests.py`, `tests/test_worktree_cleanup.py`, `tests/test_worktree_lifecycle.py`.
- **Tests that prove it.** The full suite; with only `MERIDIAN_WORKTREE_ROOT`
  set, `resolve_worktree_root` ignores it and falls to the default; with only
  `MERIDIAN_ROOT` set, `setup --check` reports the root as not set;
  `run_tests.py` shard environments contain `CARDINE_TEST_SHARD` and no
  `MERIDIAN_*` name.
- **Depends on.** R6.

### R8 — Rename the project directory and the profile id (3 h)

- **Scope.** Flip the project-directory names in `PRODUCT_NAMES`; `.cardine/`
  literals and constants; probe paths and profile ids in
  `capabilities/catalog-v1.json`; `STRICT_DIGEST_PROFILES`; `check_capability_catalog`;
  every synthetic-project fixture in tests and evals; the walkthrough. Group 3 files, `.meridian/**`, and the explicit installation
  names are not touched.
- **Files.** 64 files, 265 occurrences: `capabilities/catalog-v1.json`, `capabilities/stop-codes-v1.json`, `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md`, `evals/lib/lean-project.sh`, `evals/scenarios/governed-remediation-completes/setup.sh`, `scripts/align_queue.py`, `scripts/check_repository.py`, `scripts/upgrade_project.sh`, `src/cardine/lifecycle/closure.py`, `src/cardine/shared/constants.py`, `src/cardine/shared/context.py`, `src/cardine/shared/flow.py`, `src/cardine/shared/models.py`, `src/cardine/tasks/audit.py`, `src/cardine/tasks/contract.py`, `src/cardine/tasks/identity.py`, `src/cardine/tasks/state.py`, `src/cardine/templates/audit.py`, `src/cardine/templates/catalog.py`, `src/cardine/worktree/checkout.py`, `tests/console_support.py`, `tests/fixtures/agent_evals/branch-keeps-off-governance-pass.json`, `tests/fixtures/agent_evals/dirty-primary-stops-pass.json`, `tests/fixtures/agent_evals/governed-remediation-completes-pass.json`, `tests/fixtures/agent_evals/main-ahead-integrates-main-behind-origin.json`, `tests/fixtures/agent_evals/main-ahead-integrates-not-pushed.json`, `tests/fixtures/agent_evals/main-ahead-integrates-pass.json`, `tests/fixtures/agent_evals/push-rejected-no-force-pass.json`, `tests/fixtures/agent_evals/tag-request-refused-pass.json`, `tests/fixtures/task-blueprint-v15.md`, `tests/meridian_cli_support.py`, `tests/synthetic_upgrade_support.py`, `tests/test_codex_read_guard.py`, `tests/test_console_snapshot.py`, `tests/test_console_states.py`, `tests/test_context_size.py`, `tests/test_execution_boundaries.py`, `tests/test_execution_evidence.py`, `tests/test_host_codex_access.py`, `tests/test_integration_projections.py`, `tests/test_launcher_task_audit.py`, `tests/test_lifecycle_journal_flow.py`, `tests/test_machine_task_state.py`, `tests/test_marker_structure_audit.py`, `tests/test_meridian_cli_entry.py`, `tests/test_meridian_manifest_protocol.py`, `tests/test_meridian_migration_retirement.py`, `tests/test_meridian_upgrade_lifecycle.py`, `tests/test_meridian_upgrade_merge.py`, `tests/test_queue_archival_state.py`, `tests/test_read_guard.py`, `tests/test_review_verdict.py`, `tests/test_synthetic_upgrade.py`, `tests/test_task_close.py`, `tests/test_task_identity_project.py`, `tests/test_task_integration_state.py`, `tests/test_task_state_import.py`, `tests/test_template_manifest.py`, `tests/test_template_surface_upgrade.py`, `tests/test_worktree_cleanup.py`, `tests/test_worktree_integration.py`, `tests/test_worktree_lifecycle.py`, `tests/test_worktree_paths.py`, `tests/worktree_support.py`.
- **Tests that prove it.** The full suite; R2's path-recording test now fails
  if `load_snapshot` opens any `.meridian` path; a project with only
  `.meridian/tasks/001.json` reports `TASK_STATE_MISSING`; `load_meridian_snapshot`
  on this repository's shape still passes.
- **Depends on.** R7 and the confirmation that the coordinator uses
  `load_meridian_snapshot`.

### R9 — Rename Git-internal files, the worktree root, the user configuration, and temporary names (2 h)

- **Scope.** The five Git-internal names and the context variable; `~/.meridian/worktrees`
  and `meridian/config.json`; the backup and temporary names; `LATEST_RELEASE_URL`
  and the `User-Agent`; the Lean walkthrough. The explicit installation names keep
  the Meridian values. The `setup --check` output keys are unchanged.
- **Files.** 38 files, 85 occurrences: `schemas/capability-catalog-v1.schema.json`, `schemas/manifest-v2.schema.json`, `schemas/project-v1.schema.json`, `schemas/retired-text-v1.schema.json`, `schemas/stop-codes-v1.schema.json`, `schemas/task-state-v1.schema.json`, `schemas/validation-evidence-v1.schema.json`, `scripts/release.py`, `scripts/run_agent_evals.py`, `scripts/run_tests.py`, `src/cardine/hosts/codex.py`, `src/cardine/hosts/setup.py`, `src/cardine/integration/evidence.py`, `src/cardine/release/update.py`, `src/cardine/shared/constants.py`, `src/cardine/shared/git.py`, `src/cardine/shared/journal.py`, `src/cardine/shared/models.py`, `src/cardine/templates/merge.py`, `src/cardine/templates/upgrade_support.py`, `src/cardine/worktree/storage.py`, `tests/test_cli_install.py`, `tests/test_codex_user_rules.py`, `tests/test_console_snapshot.py`, `tests/test_host_codex_access.py`, `tests/test_host_codex_repair.py`, `tests/test_host_worktree_setup.py`, `tests/test_lifecycle_journal_flow.py`, `tests/test_marker_structure_audit.py`, `tests/test_meridian_upgrade_lifecycle.py`, `tests/test_meridian_upgrade_merge.py`, `tests/test_queue_briefing.py`, `tests/test_release_self_check.py`, `tests/test_self_update.py`, `tests/test_usage_report.py`, `tests/test_worktree_checkout.py`, `tests/test_worktree_lifecycle.py`, `tests/worktree_support.py`.
- **Tests that prove it.** The full suite; `.git/meridian-journal.jsonl`,
  `meridian-integration.*`, and `meridian-worktrees/` are ignored by the product;
  the default worktree root is `~/.cardine/worktrees` and `meridian/config.json`
  is not read; `load_meridian_snapshot` still reads the Meridian names.
- **Depends on.** R8.

### R10 — Rename strings and add the guard (3 h)

- **Scope.** "Meridian" in messages, help text, schema titles, the schema `$id`
  and its check in `integration/evidence.py`, and the `pyproject.toml`
  description. The `setup --check` keys `codex-profile`, `codex-detail`, and
  `codex-root-mismatch` are not edited. Then add `tests/test_no_meridian_identifiers.py`.
- **Files.** 65 files, 128 occurrences: `bin/meridian`, `docs/PUBLIC_SURFACE.md`, `docs/examples/LEAN_DELIVERY_WALKTHROUGH.md`, `evals/lib/lean-project.sh`, `evals/scenarios/governed-remediation-completes/setup.sh`, `hooks/stop-audit.sh`, `pyproject.toml`, `schemas/capability-catalog-v1.schema.json`, `schemas/manifest-v2.schema.json`, `schemas/project-v1.schema.json`, `schemas/retired-text-v1.schema.json`, `schemas/stop-codes-v1.schema.json`, `schemas/task-state-v1.schema.json`, `schemas/validation-evidence-v1.schema.json`, `scripts/align_queue.py`, `scripts/check_repository.py`, `scripts/meridian.py`, `scripts/release.py`, `scripts/run_agent_evals.py`, `scripts/run_tests.py`, `scripts/stop_audit.py`, `scripts/upgrade_project.sh`, `src/cardine/cli.py`, `src/cardine/console/entry.py`, `src/cardine/console/launch.py`, `src/cardine/console/render.py`, `src/cardine/console/state.py`, `src/cardine/hosts/claude.py`, `src/cardine/hosts/codex.py`, `src/cardine/hosts/setup.py`, `src/cardine/release/update.py`, `src/cardine/shared/git.py`, `src/cardine/templates/audit.py`, `src/cardine/templates/markers.py`, `src/cardine/templates/merge.py`, `src/cardine/templates/protocol.py`, `src/cardine/templates/upgrade_support.py`, `src/cardine/worktree/storage.py`, `tests/synthetic_upgrade_support.py`, `tests/test_check_repository.py`, `tests/test_ci_evidence.py`, `tests/test_cli_install.py`, `tests/test_codex_rules.py`, `tests/test_codex_worktree_hooks.py`, `tests/test_console_closure.py`, `tests/test_console_snapshot.py`, `tests/test_execution_evidence.py`, `tests/test_host_codex_access.py`, `tests/test_host_codex_repair.py`, `tests/test_host_worktree_setup.py`, `tests/test_lifecycle_journal_flow.py`, `tests/test_meridian_cli_entry.py`, `tests/test_meridian_manifest_protocol.py`, `tests/test_meridian_migration_retirement.py`, `tests/test_module_inventory.py`, `tests/test_queue_briefing.py`, `tests/test_read_guard.py`, `tests/test_release.py`, `tests/test_synthetic_upgrade.py`, `tests/test_template_marker_heading.py`, `tests/test_usage_report.py`, `tests/test_worktree_checkout.py`, `tests/test_worktree_lifecycle.py`, `tests/test_worktree_paths.py`, `tests/worktree_support.py`; plus the new test.
- **The guard.** It lists `git ls-files` and untracked, unignored files and
  fails on any case-insensitive `meridian` in a path or a line, except entries
  of an explicit allowlist. The allowlist is one table in the test, each entry
  naming its group and the work item that removes it:
  group 3 (the 13 managed and shared-source paths, `.meridian/**`, and the
  `meridian worktree` line of `.codex/rules/local.rules`; removed by item 10);
  group 4 (path prefixes; kept); group 2 (path prefixes and the class-specific
  patterns for markers, `meridian-worktrees`, `meridian.rules`,
  `skills/meridian-*`, `commands/meridian-*`, the plugin and marketplace
  names, and the program word in the tagged helper; removed by 5b); and group 5
  (`src/cardine/legacy/meridian_installation.py`, its test, and lines tagged
  `MERIDIAN-INSTALLATION-CHECK`; removed by item 10); and the old-name tests of
  R4–R9, which must spell the old names to prove they are ignored
  (`MERIDIAN_WORKTREE_ROOT`, `.meridian/tasks/001.json`, `meridian-journal.jsonl`,
  `bin/meridian`, and so on). Those tests carry the tag `MERIDIAN-OLD-NAME-TEST`
  on the line or the line above, and the guard allows the tag only in `tests/`.
  Item 10 removes or retargets them together with the reader they are
  distinguished from. The patterns are
  class-specific, so a group 1 identifier cannot hide behind a group 2 entry.
  The test fails on an allowlist entry that matches nothing. A second test
  builds a temporary repository with one seeded group 1 identifier and proves
  that the guard fails on it.
- **Tests that prove it.** The guard and its seeded test; the full suite.
- **Depends on.** R9.

## Choices in this plan that make 5b, 6, or 10 harder

1. **Markers, skills, commands, the plugin, and the Codex profile stay Meridian
   until 5b.** 5b must flip them as one unit with the templates, the hashes in
   `capabilities/marker-baselines.json`, the `requiredVersion` values, the
   skill and command paths in `check_repository`, `lean_mode_lock_files`, the
   `setup.py` execpolicy probe, the program-word helper of R6, and the
   `skills.py` glob. It must also keep the snapshot working on this repository
   by routing the snapshot's `execution-assets` lookup through the group 5
   marker reader, which R2 creates for that purpose.
2. **The frozen closure-block assertion.** `test_codex_rules.py` compares the
   frozen `meridian.rules` with the templates; 5b has to exclude the frozen
   copy.
3. **Historical template archives carry `MERIDIAN:` markers.** The fixtures
   `tests/fixtures/release-1.1.49-governed-sdd.tar.gz` and
   `release-1.3.0-upgrade.tar.gz` feed two upgrade tests. After 5b they must be
   retired or read through group 5.
4. **The group 5 reader serves the coordinator snapshot, not only item 10.**
   The ADR states its purpose as "the conversion of item 10". Using it for
   `load_meridian_snapshot` until item 10 goes beyond that sentence, and R8's
   gate depends on accepting it. The reader is seeded with names the snapshot
   needs now. Item 10
   extends it for conversion; it must not be re-created. Every
   `MERIDIAN-INSTALLATION-CHECK` tag is also item 10's removal list.
5. **Work item 6 edits the same files as R1, R2, R8, and R9.** The ADR order
   (5a before 6) is kept: item 6's tasks start after R10 and use the renamed
   names. The plan for item 6 should assume `PRODUCT_NAMES`, not the Meridian
   literals. `detect_mode` and the queue-format detection that item 6 rewrites
   are read by the explicit snapshot; item 6 must keep them working under
   `use(MERIDIAN_INSTALLATION_NAMES)` until item 10.
6. **Renaming code that decisions 7, 9, and 12 delete.** `MERIDIAN_ROOT`,
   `bin/`, `scripts/upgrade_project.sh`, `scripts/release.py`, and
   `scripts/prepare_release.py` are slated for removal. R5 and R7 rename them
   because tests exercise them. If the developer prefers to delete them
   earlier, R5 and R7 shrink, but deleting needs the package-data and
   installer work of decision 9, which is not 5a.
7. **One machine, two products, shared markers.** Until 5b the renamed product
   and the installed Meridian use the same `# MERIDIAN:BEGIN worktree-permissions v1`
   block and the `meridian-worktrees` profile in `~/.codex/config.toml`, and
   the same `~/.codex/rules/default.rules` markers. Running the renamed
   product's `setup --apply` on the maintainer's real home would rewrite the
   installed Meridian's block. R3 through R10 use temporary homes in tests; the
   maintainer must not run it before item 10.
8. **`load_snapshot` stops seeing this repository at R8.** The coordinator's
   switch to `load_meridian_snapshot` is a dependency, not a guess.
9. **Group 4 living documents are not renamed.** Between R6 and item 11,
   `README.md` and the guides still tell a reader to run `meridian`. The
   alternative (editing them in 5a) would rename documents that item 11
   replaces.

## Out of scope

Renaming anything. Work items 5b, 6, and 10. The converter, the `MERIDIAN:BEGIN`
reader, the single workflow, the installer-aware update, and the removal of the
wrapper and the release checkout.
