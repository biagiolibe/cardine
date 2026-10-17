# Clean install verification — v1.2.15

Current installations use `~/.local/share/meridian`; paths below preserve the historical commands tested.

Verification date: 2026-10-14. This is a recorded experiment, including failed
steps and explicit recoveries, rather than a corrected quick start.

## Release and result

`gh release view --json tagName,publishedAt,url` exited 0 and selected
[`v1.2.15`](https://github.com/biagiolibe/meridian/releases/tag/v1.2.15), published
2026-10-14 at 09:17:40 UTC. The cloned tag resolved to
`fb76d6e0dd34247cbb5bd875727c996a8fb63b68`. `git diff v1.2.15 -- README.md`
exited 0 with no output in the verification task checkout: the README examined
matches the published tag.

The Codex shell installation, skill links, and online version check passed.
A CLI-driven Lean Delivery task reached integration, local-origin push, and
cleanup after the recoveries below. The README alone did not provide this
complete path. Claude Code marketplace installation and slash-command execution
remain manual, unexecuted procedures; this report does **not** certify that
interactive route or a fresh Codex session's effective filesystem permissions.

## Environment and isolation

| Item | Observed value |
|---|---|
| OS | macOS 27.0.1, build 26A434 (`sw_vers`, exit 0) |
| Python | 3.14.7 (`python3 --version`, exit 0); already available, so Homebrew installation was not run |
| Git | 2.54.0 (Apple Git-157), `git --version`, exit 0 |
| Claude Code | 2.1.300 (`claude --version`, exit 0); binary inventory only |
| Codex CLI | 0.162.1 (`codex --version`, exit 0); warned that PATH aliases could not be created in the sandbox |
| Host sessions | No authenticated Claude session, plugin install, Codex restart, or live skill discovery exercised |
| Origin | A new local bare Git repository, never a hosted remote |

All temporary paths below use semantic substitutions: `$LAB` is the directory
returned by `mktemp -d` (exit 0), `$HOME=$LAB/home`, `$PROJECT=$LAB/project`,
and `$TASK_WORKTREE` is the absolute `worktree` returned by `prepare`.
These substitutions remove machine-specific paths; commands otherwise preserve
their executed spelling. `$MERIDIAN_ROOT=$HOME/meridian`. The local repository
hash in returned paths is deliberately omitted. No credentials or real user
identity are included. The Git name and address below are synthetic fixtures.

The subprocess runner used a newly constructed environment, not inherited host
configuration: fresh `HOME`, `XDG_CONFIG_HOME=$HOME/.config`,
`XDG_CACHE_HOME=$HOME/.cache`, `CODEX_HOME=$HOME/.codex`, and
`CLAUDE_CONFIG_DIR=$HOME/.claude`; `TMPDIR=$LAB`, `LC_ALL=C`,
`GIT_CONFIG_NOSYSTEM=1`, and `GIT_CONFIG_GLOBAL=/dev/null`. PATH contained the
tagged checkout's `bin`, the existing Homebrew tool directory, and system tool
directories. It inherited no Meridian configuration, worktree-root override,
API keys, or host authentication. The fresh home initially contained only the
downloaded source tree; no prior Meridian install, user config, skills, or
worktree root existed there. This isolates configuration, not the OS or
preinstalled binaries; Python installation on a bare machine was not tested.

Source acquisition ran `git clone --branch v1.2.15
https://github.com/biagiolibe/meridian $HOME/meridian`: first exit 128 (sandbox
DNS failure), then exit 0 after explicit network approval. Acquisition preceded
the isolated subprocess environment and used the public repository. No host
configuration was copied into the temporary home. Likewise, the first isolated
`self-check --check-latest` failed DNS; its approved retry kept the same isolated
environment and succeeded. These are harness restrictions, not release defects.

## Claude Code quick start — manual evidence only

The following is the exact procedure to perform in a fresh, authenticated Claude
Code session with the isolated home and a new empty Git project. Exit status is
**N/A — not executed** for each slash command; no plugin cache or initializer
success is inferred from the shell experiment.

| Step | Exact procedure | Evidence status |
|---|---|---|
| C1 | `/plugin marketplace add biagiolibe/meridian#v1.2.15` | Manual, unexecuted; check the marketplace ref is exactly v1.2.15 |
| C2 | `/plugin install meridian@meridian` | Manual, unexecuted; check the installed plugin version/cache |
| C3 | Open the new Git project and run `/meridian-init` | Manual, unexecuted; select project name `Install Probe`, `lean-delivery`, `opaque`, and conversation language `English`; supply stack and session details when asked |
| C4 | Review the initializer's setup plan, consent to its isolated setup, then fill the design and project plan | Manual, unexecuted; initializer source lists these interactions |
| C5 | `/meridian-task` for a task adding `hello.md`, then `Proceed with 001` | Manual, unexecuted; the shell recovery below exercises the lifecycle, not these host commands |

The tagged `commands/meridian-init.md` was inspected for the initializer's actual
steps. Its shell equivalent for copying templates and locking the project was
used below only after discovering that `meridian init` is unavailable. It does
not establish marketplace installation, slash-command behavior, or completion
of all interactive customization prompts.

## Executed shell transcript

Run order is chronological. Working directory P means `$PROJECT`, W means
`$TASK_WORKTREE`. Each row records the command's own exit code, even when the
outer recorder continued successfully. No failure is counted as a pass.
`bootstrap.py`, `fixture.py`, and the in-process task edits are reproduced below.
The setup apply operations were deliberate consent confined to this disposable
environment; generated machine configuration was never applied to the real home.
Doctor's exit 0 does not imply every reported capability is ready.

| # | CWD | Exact command (paths normalized) | Exit | Outcome |
|---|---|---|---|---|
| 1 | P | ``python3 --version`` | 0 | Python 3.14.7 |
| 2 | P | ``git --version`` | 0 | git version 2.54.0 (Apple Git-157) |
| 3 | P | ``git -C "$MERIDIAN_ROOT" rev-parse HEAD`` | 0 | fb76d6e0dd34247cbb5bd875727c996a8fb63b68 |
| 4 | P | ``git init -b main`` | 0 | Initialized empty Git repository in $PROJECT/.git/ |
| 5 | P | ``git config user.name "Install Verifier"`` | 0 | No output. |
| 6 | P | ``git config user.email "verifier@example.invalid"`` | 0 | No output. |
| 7 | P | ``git init --bare ../origin.git`` | 0 | hint: Using 'master' as the name for the initial branch. This default branch name<br>hint: will change to "main" in Git 3.0. To configure the initial branch name<br>hint: to use in all of your new repositories, which will suppress this warning,<br>hint: call:<br>hint:<br>hint: 	git config --global init.defaultBranch <name><br>hint:<br>hint: Names commonly chosen instead of 'master' are 'main', 'trunk' and<br>hint: 'development'. The just-created branch can be renamed via this command:<br>hint:<br>hint: 	git branch -m <name><br>hint:<br>hint: Disable this message with "git config set advice.defaultBranchName false"<br>Initialized empty Git repository in $LAB/origin.git/ |
| 8 | P | ``git remote add origin ../origin.git`` | 0 | No output. |
| 9 | P | ``meridian codex doctor`` | 0 | permission-model: approval-required<br>profile-ownership: not-applicable<br>project-trust: approval-required<br>command-policy: blocked<br>claude-project-allowlist: approval-required<br>candidate-validation-commands: advisory-undeclared<br>lifecycle-command-policy: blocked<br>archive-rename-policy: blocked<br>inspection-command-policy: blocked<br>validation-command-policy: blocked<br>worktree-root-write: approval-required<br>git-metadata: approval-required<br>skill-links: missing<br>MERIDIAN_ROOT: ready |
| 10 | P | ``meridian setup --check`` | 0 | directory: missing; codex-profile: unconfigured; candidate-validation-commands: undeclared; project-declaration: advisory-missing; task-identity: not-requested; codex-skill-links: missing; warning: resolved root is under a temporary directory and is unsuitable for persistent setup |
| 11 | P | ``meridian setup --apply`` | 0 | directory: missing; codex-profile: unconfigured; candidate-validation-commands: undeclared; project-declaration: advisory-missing; task-identity: not-requested; codex-skill-links: missing; warning: resolved root is under a temporary directory and is unsuitable for persistent setup; result: updated; restart Codex |
| 12 | P | ``meridian self-check`` | 2 | usage: meridian self-check [-h] --check-latest<br>meridian self-check: error: the following arguments are required: --check-latest |
| 13 | P | ``meridian init`` | 2 | CLI rejects `init`: invalid choice. |
| 14 | P | ``meridian codex doctor`` | 0 | permission-model: ready<br>profile-ownership: ready<br>project-trust: approval-required<br>command-policy: blocked<br>claude-project-allowlist: ready<br>candidate-validation-commands: advisory-undeclared<br>lifecycle-command-policy: blocked<br>archive-rename-policy: blocked<br>inspection-command-policy: blocked<br>validation-command-policy: blocked<br>worktree-root-write: ready<br>git-metadata: approval-required<br>skill-links: ready<br>MERIDIAN_ROOT: ready |
| 15 | P | ``meridian setup --check`` | 0 | directory: ready; codex-profile: ready; candidate-validation-commands: undeclared; project-declaration: present; task-identity: not-requested; codex-skill-links: ready; warning: resolved root is under a temporary directory and is unsuitable for persistent setup |
| 16 | P | ``meridian self-check --check-latest`` | 11 | Installed: 1.2.15<br>Status: UNKNOWN<br>Reason: network error: [Errno 8] nodename nor servname provided, or not known<br>Plugin ref: unknown (no user settings at $HOME/.claude/settings.json) |
| 17 | P | ``meridian lock --help`` | 0 | Help confirms --project and required --mode options. |
| 18 | P | ``meridian self-check --check-latest`` | 0 | Installed: 1.2.15<br>Latest: 1.2.15<br>Kind: template-changing<br>Plugin ref: unknown (no user settings at $HOME/.claude/settings.json)<br>Status: UP_TO_DATE |
| 19 | P | ``python3 ../bootstrap.py`` | 0 | Copied base and lean-delivery templates; set name, date, and language. |
| 20 | P | ``meridian lock --project . --mode lean-delivery`` | 0 | Locked $PROJECT to Meridian 1.2.15 (lean-delivery). |
| 21 | P | ``meridian setup --check --task-identity opaque`` | 0 | directory: ready; codex-profile: ready; candidate-validation-commands: undeclared; project-declaration: present; task-identity: planned; codex-skill-links: ready; warning: resolved root is under a temporary directory and is unsuitable for persistent setup |
| 22 | P | ``meridian setup --apply --task-identity opaque`` | 0 | directory: ready; codex-profile: ready; candidate-validation-commands: undeclared; project-declaration: present; task-identity: planned; codex-skill-links: ready; warning: resolved root is under a temporary directory and is unsuitable for persistent setup; result: updated; restart Codex |
| 23 | P | ``git status --short`` | 0 | ?? .claude/<br>?? .claudeignore<br>?? .codex/<br>?? .gitignore<br>?? .meridian/<br>?? AGENTS.md<br>?? CLAUDE.md<br>?? LANGUAGE_POLICY.md<br>?? PROJECT_PLAN.md<br>?? PROJECT_WORKFLOW.md<br>?? README.md<br>?? TECH_DESIGN.md<br>?? docs/<br>?? tasks/ |
| 24 | P | ``python3 ../fixture.py`` | 0 | Created task 001 and its matching plan entry; kept the template queue row. |
| 25 | P | ``git add .`` | 0 | No output. |
| 26 | P | ``git commit -m "Initialize install probe and task 001"`` | 0 | [main (root-commit) b96def3] Initialize install probe and task 001; see fixture contents below. |
| 27 | P | ``git push -u origin main`` | 0 | To ../origin.git<br> * [new branch]      main -> main<br>branch 'main' set up to track 'origin/main'. |
| 28 | P | ``meridian worktree prepare 001 --project . --format json`` | 2 | BLOCKED COMMAND_REFUSED: task 001 has no authoritative task file; resume: correct the condition that the detail names, then rerun the same meridian command |
| 29 | P | ``python3 -c 'from pathlib import Path; p=Path("tasks/001-setup.md"); p.write_text(p.read_text().replace("## Objective", "> **ID**: `001`\n\n## Objective"))'`` | 0 | No output. |
| 30 | P | ``git add tasks/001-setup.md`` | 0 | No output. |
| 31 | P | ``git commit -m "Declare the probe task identity"`` | 0 | [main 9b5417c] Declare the probe task identity; see fixture contents below. |
| 32 | P | ``git push origin main`` | 0 | To ../origin.git<br>   b96def3..9b5417c  main -> main |
| 33 | P | ``meridian worktree prepare 001 --project . --format json`` | 0 | branch: task-001; created: True |
| 34 | W | ``meridian worktree check 001 --project "$PROJECT" --format json`` | 0 | branch: task-001; clean: True; errors: []; status: ready |
| 35 | W | ``meridian execution start 001 --project .`` | 0 | status: QUEUED; started: False |
| 36 | W | ``git status --short`` | 0 | No output. |
| 37 | W | ``printf 'Hello, Meridian!\n' > hello.md`` | 0 | No output. |
| 38 | W | ``python3 -c "from pathlib import Path; assert Path('hello.md').read_text() == 'Hello, Meridian!\n'"`` | 0 | No output. |
| 39 | W | ``git diff --check`` | 0 | No output. |
| 40 | W | ``git add hello.md`` | 0 | No output. |
| 41 | W | ``git commit -m "Add greeting for task 001"`` | 0 | [task-001 5673112] Add greeting for task 001; see fixture contents below. |
| 42 | W | ``git rev-parse HEAD`` | 0 | 56731126c30bc49161e8140518dd799fb6f0ec43 |
| 43 | W | ``git mv tasks/001-setup.md tasks/done/001-setup.md`` | 128 | fatal: renaming 'tasks/001-setup.md' failed: No such file or directory |
| 44 | W | ``mkdir -p tasks/done`` | 0 | No output. |
| 45 | W | ``git mv tasks/001-setup.md tasks/done/001-setup.md`` | 0 | No output. |
| 46 | W | ``git add tasks`` | 0 | No output. |
| 47 | W | ``git commit -m "Record and archive task 001 completion"`` | 0 | [task-001 a378c3a] Record and archive task 001 completion; see fixture contents below. |
| 48 | W | ``git diff --check`` | 0 | No output. |
| 49 | P | ``meridian worktree advance 001 --project . --accepted --validation-command "git diff --check" --validation-exit-code 0 --format json`` | 2 | step: C6; action_required: human; performed: ['C5']; stop_code: UNDECLARED_VALIDATION_COMMANDS; commands: [] |
| 50 | P | ``python3 -c 'import json; from pathlib import Path; Path(".meridian/candidate-validation.json").write_text(json.dumps({"version":1,"state":"declared","outcomes":{k:["git diff --check"] for k in ["REUSE","BOUNDED","FULL"]}}, indent=2)+"\n")'`` | 0 | No output. |
| 51 | P | ``git add .meridian/candidate-validation.json`` | 0 | No output. |
| 52 | P | ``git commit -m "Declare candidate checks for the documentation probe"`` | 0 | [main 56b3297] Declare candidate checks for the documentation probe; see fixture contents below. |
| 53 | P | ``meridian worktree advance 001 --project . --accepted --validation-command "git diff --check" --validation-exit-code 0 --format json`` | 2 | BLOCKED COMMAND_REFUSED: unrecognized completion row for task 001 in $PROJECT/PROJECT_PLAN.md; resume: correct the condition that the detail names, then rerun the same meridian command |
| 54 | P | ``git status --short`` | 0 | No output. |
| 55 | P | ``python3 -c 'from pathlib import Path; p=Path("PROJECT_PLAN.md"); p.write_text(p.read_text().replace("001 Initial", "001 — Initial"))'`` | 0 | No output. |
| 56 | P | ``git add PROJECT_PLAN.md`` | 0 | No output. |
| 57 | P | ``git commit -m "Use the recognized plan completion row format"`` | 0 | [main 1879497] Use the recognized plan completion row format; see fixture contents below. |
| 58 | P | ``meridian worktree advance 001 --project . --accepted --validation-command "git diff --check" --validation-exit-code 0 --format json`` | 0 | step: C7; action_required: run-candidate-validation; performed: ['C6']; stop_code: None; commands: ['git diff --check', 'git diff --check'] |
| 59 | P | ``git diff --check`` | 0 | No output. |
| 60 | P | ``python3 -c "from pathlib import Path; assert Path('hello.md').read_text() == 'Hello, Meridian!\n'"`` | 0 | No output. |
| 61 | P | ``meridian worktree advance 001 --project . --accepted --candidate-command "git diff --check" --candidate-exit-code 0 --format json`` | 0 | step: C9; action_required: push; performed: ['C8']; stop_code: PUSH_PENDING; commands: ['git push origin main'] |
| 62 | P | ``git push origin main`` | 0 | To ../origin.git<br>   9b5417c..3e686df  main -> main |
| 63 | P | ``meridian worktree advance 001 --project . --accepted --format json`` | 0 | step: C10; action_required: none; performed: ['C10']; stop_code: None; commands: [] |
| 64 | P | ``meridian worktree cleanup 001 --project . --format json`` | 0 | status: cleaned; already_cleaned: True |
| 65 | P | ``git status --short`` | 0 | No output. |
| 66 | P | ``git worktree list --porcelain`` | 0 | worktree $PROJECT<br>HEAD 3e686dfe7bef152c84f0adee3406c31eb2767632<br>branch refs/heads/main |
| 67 | P | ``git branch --list task-001`` | 0 | No output. |
| 68 | P | ``git rev-parse HEAD origin/main`` | 0 | 3e686dfe7bef152c84f0adee3406c31eb2767632<br>3e686dfe7bef152c84f0adee3406c31eb2767632 |
| 69 | P | ``python3 -c 'from pathlib import Path; import os; h=Path.home(); r=Path(os.environ["MERIDIAN_ROOT"]); names=["meridian-lean-delivery","meridian-governed-sdd"]; assert all((h/".agents/skills"/n).is_symlink() and (h/".agents/skills"/n).resolve()==r/"skills"/n for n in names); print("Both skill links resolve to the tagged checkout")'`` | 0 | Both skill links resolve to the tagged checkout |
| 70 | P | ``git check-ignore .claude/settings.local.json`` | 1 | No output. |
| 71 | P | ``git status --short`` | 0 | No output. |

The first setup created both skill symlinks; an explicit final assertion verified
their targets against the tagged checkout. The repeated setup check was
idempotent. Doctor still reported blocked command policies and approval-required
project trust/Git metadata: a restarted, trusted host session remains untested.
`self-check --check-latest` eventually returned `Installed: 1.2.15`,
`Latest: 1.2.15`, and `Status: UP_TO_DATE`; its unknown plugin ref is expected
because this was a tagged checkout without a Claude marketplace installation.

The lifecycle's candidate scope was BOUNDED because recovery commits advanced
the fixture's main branch. This documentation fixture declares only
`git diff --check` for candidate scopes. The greeting assertion was also run on
the merged tree. Final `advance` performed C10 cleanup; the separate cleanup
call proved idempotence. Status was clean, only the primary worktree remained,
the task branch was absent, and `HEAD` and local `origin/main` both resolved to
`3e686dfe7bef152c84f0adee3406c31eb2767632`.

## Fixture and recovery details

The temporary `bootstrap.py` was this explicit surrogate for the initializer's
copy/name/date/language steps. No repository implementation was changed:

```python
import os, pathlib, shutil
source = pathlib.Path(os.environ['MERIDIAN_ROOT']) / 'templates'
target = pathlib.Path.cwd()
shutil.copytree(source / 'base', target, dirs_exist_ok=True)
shutil.copytree(source / 'workflows/lean-delivery', target, dirs_exist_ok=True)
for path in target.rglob('*'):
    if path.is_file() and '.git' not in path.parts:
        try:
            text = path.read_text()
        except UnicodeError:
            continue
        for before, after in {'[Project Name]': 'Install Probe', '[Data]': '2026-10-14',
                              '[Date]': '2026-10-14', '[Conversation language]': 'English'}.items():
            text = text.replace(before, after)
        path.write_text(text)
(target / 'tasks/done').mkdir(parents=True, exist_ok=True)
print('Copied base and lean-delivery templates; set name, date, and language.')
```

The temporary `fixture.py` supplied a concrete, bounded first task. The
template already provided its queue row. Its initial omissions caused the two
identity/plan-format failures recorded above; the transcript shows their exact
repairs. These are fixture mistakes, not proof that `/meridian-task` emits
incorrect records.

```python
from pathlib import Path
p = Path.cwd()
(p / 'PROJECT_PLAN.md').write_text('# Install Probe\n\n- `[ ]` 001 Initial setup\n')
(p / 'tasks/001-setup.md').write_text('''# Task 001 — Initial setup

## Objective
Add a greeting document to verify a first Lean Delivery task.

## Acceptance Criteria
- [ ] `hello.md` contains exactly `Hello, Meridian!` followed by a newline.

## Relevant Files
- `hello.md`

## Validation
- `python3 -c "from pathlib import Path; assert Path('hello.md').read_text() == 'Hello, Meridian!\\n'"`
- `git diff --check`
''')
print('Created task 001 and its matching plan entry; kept the template queue row.')
```

After prepare/check/start, the task writer performed the following direct
Python file edits in W after the implementation commit. Each write returned
normally. Shell commands around them, including the failed archive move, appear
in the transcript. `sha` was `56731126c30bc49161e8140518dd799fb6f0ec43`,
`prepared['base_commit']` was `9b5417c276274ec336918d346422db728b6e81c4`,
and `prepared['handoff_worktree']` was the returned relative local-repository
task path. `check` was the exact greeting assertion in the transcript.

```python
task = wt / 'tasks/001-setup.md'
task.write_text(task.read_text().replace('- [ ]', '- [x]'))
(wt / 'tasks/handoffs').mkdir(exist_ok=True)
(wt / 'tasks/handoffs/001.md').write_text(f'''## Completion Report — 001

- Files changed: `hello.md`, task 001 and its handoff.
- Branch: `task-001`
- Worktree: `{prepared['handoff_worktree']}`
- Validation: `{check}` (exit 0); `git diff --check` (exit 0).
- Validated task commit: `{sha}`
- Validated base main commit: `{prepared['base_commit']}`
- Full combined-tree validation required: no.
- Dependencies: none.
- Behavioral surfaces: greeting document only.
- Acceptance criteria: all met.
- Blockers/deviations: none.
''')
```

No task machine-state transition was needed: Lean `execution start` returned
`state: null`, and `advance` accepted the committed task archive and evidence.
Queue/plan completion and queue-section archival were left to integration.
After C6 rejected an undeclared candidate policy, the fixture's primary checkout
received an explicit documentation-only policy and commit, then advance was
retried. Its full command is in the transcript. These recoveries modify only
the disposable consumer, not Meridian's README, CLI, or templates.

## Findings for tasks 211 and 212

| ID | README section | Observed friction / boundary | Proposed correction |
|---|---|---|---|
| F1 | Quick start with Claude Code | Installation assumes an installed and authenticated Claude Code host; neither prerequisite is introduced there. Interactive marketplace/init steps remain unexecuted in this shell test. | State host/auth prerequisites and provide an interactive verification checklist; retain an explicit unverified status until performed. |
| F2 | Quick start with Claude Code | Python 3.12+ is documented in the Codex section but the plugin CLI needs the same runtime. | Put shared Python/Git prerequisites before both quick starts. |
| F3 | Quick start with Codex | The clone command uses `v<version>` without locally explaining which version to select. | Link Releases beside this command and show the selected current release as an example. |
| F4 | Quick start with Codex | `meridian init` is recommended for new projects but exits 2: no such subcommand exists in v1.2.15. | Document the actual supported initialization procedure for Codex or provide the missing CLI in a later task. |
| F5 | Updating Meridian / Quick start with Codex | Bare `meridian self-check` exits 2 because `--check-latest` is required; the Codex quick start has no final version-check command. | Show the full invocation and expected success/network-failure statuses at the end of both install paths. |
| F6 | Quick start with Codex | `setup --check` / `--apply` appears twice; check output proposes machine profile, links, project settings and declarations, not just links. Apply requests a host restart. | Consolidate setup once, explain its bounded writes and consent/restart boundary, and separate installation from project setup. |
| F7 | Quick start with Codex | Doctor exits 0 while reporting blocked command policies and approval-required trust/Git metadata even after setup. | Explain that exit 0 is diagnostic success, identify expected first-run states, and give the exact post-restart trust/access verification procedure. |
| F8 | Quick start with Codex | A default candidate declaration stays `undeclared`; first advance stops C6 with `UNDECLARED_VALIDATION_COMMANDS`. | Include declaration of project candidate checks before delegating the first task, with a minimal validated example. |
| F9 | Quick start with Claude Code / Quick start with Codex | There is no README worked example from task creation through advance, candidate checks, push, and cleanup. The surrogate needed templates, lock, explicit task/queue/plan records and validation knowledge from other files. | Add one complete Lean example with exact inputs, lifecycle gates, and expected outputs. |
| F10 | Quick start with Claude Code (first-task follow-up) | A manually written task without an explicit ID was not authoritative for `001`; a plan row without the recognized separator was rejected at integration. These were fixture mistakes. | Show generated task metadata and the exact supported plan-row format in the first-task example. |
| F11 | Quick start with Claude Code (first-task follow-up) | `tasks/done/` existed at bootstrap but was empty and absent in the linked worktree; the first archive move exited 128 until `mkdir -p tasks/done`. | Include destination-directory creation in archive instructions. |
| F12 | Quick start with Codex | The generated `.claude/settings.local.json` is described as ignored; `git check-ignore` returned 1, and initial `git add .` tracked it in the copied base-template project. | Ensure new-project ignore rules cover the setup-generated local settings and verify this in the worked example. |
| F13 | Quick start with Claude Code / Quick start with Codex | The newcomer needs Git identity, a first main commit, and an origin before demonstrating full closure. A new bare origin also emitted Git's default-branch advice. | Document these prerequisites and provide a local-bare-origin walkthrough without requiring a hosted account. |
| F14 | Quick start with Codex | A temporary-home setup warns its root is unsuitable for persistent setup. This is expected for this verification harness. | Distinguish disposable verification environments from persistent installation; do not suppress the warning. |
| F15 | Updating Meridian / install verification | Sandboxed clone and online self-check failed DNS (128 and 11); approved retries succeeded. This is a harness limitation. | Explain the online requirement and distinguish UNKNOWN from an installed-version mismatch. |

No finding is fixed by task 209. The noninteractive experiment is complete;
interactive marketplace/init evidence and effective host-session permissions
remain explicitly unverified. Windows and a minimum-Python-version installation
were outside this run. Only documentation is delivered, so unrelated runtime
tests are omitted under `docs/CONTEXT_BUDGET_POLICY.md`; repository consistency
and whitespace validation are recorded in the task handoff.
