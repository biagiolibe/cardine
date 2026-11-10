# Cardine quick start

This walkthrough uses the published [v0.9.1 release](https://github.com/biagiolibe/cardine/releases/tag/v0.9.1), from installation through a first task integrated on `main`. Contoso is a fictional example. Replace its project name, slug, paths, remote URL, test command, task ID, and task contents with your own; use a repository and remote you can write to. The maintainer runs installation, console access, and developer-only confirmations; the agent can run the project commands below under the project’s permissions. Review each preview and staged diff before applying or committing it.

## Start with an agent

Open an agent in your project checkout (prepare it as described under [Prepare the project](#prepare-the-project)). With the Cardine project skill installed, ask: “I want to use Cardine here.” Before the skill is available, give the agent this self-contained request:

```text
I want to use Cardine here. Read the Quickstart at
https://github.com/biagiolibe/cardine/blob/main/docs/QUICKSTART.md and guide
me from this checkout to the first integrated task.
```

The agent follows the same walkthrough. You supply project-specific values, inspect the previews and rehearsal, and consent before project changes and host setup. The console is optional. Before choosing a task identity, the agent asks: “How would you like to number tasks: simple numbers such as 001 and 002, or IDs grouped by milestone and workstream such as M1-API-001 and M1-API-002?” After you confirm, it maps the first choice to `opaque` and the second to `milestone`; it does not choose on your behalf.

## Start in the terminal

Follow the sections below in order. After installation, connect an agent host and use the same agent-led workflow described in [everyday use](#everyday-use). Terminal-only operation is also possible; the console is optional.

## Install the CLI

You need macOS or Linux, Python 3.12 or later, Git, pipx, and a Git author identity. This clone contains the Cardine runtime, not your project:

```bash
git clone --branch v0.9.1 https://github.com/biagiolibe/cardine ~/src/cardine-runtime
pipx install --editable ~/src/cardine-runtime
cardine --version
```

Expect version 0.9.1. If installation fails, fix the reported prerequisite and retry. Terminal-only users need no agent host or plugin. To use Claude Code, install and authenticate it and install the matching plugin:

```bash
claude plugin marketplace add biagiolibe/cardine#v0.9.1
claude plugin install cardine@cardine
```

For Codex, install and authenticate Codex; project skills are installed by the separate setup step after project configuration. The self-contained prompt above works before then.

## Prepare the project

Cardine needs a clean project checkout on `main`, a writable `origin`, and a passing test command. Landing pushes `main`. For an existing project not yet local, replace the URL and path:

```bash
git clone https://github.com/YOUR-ORG/YOUR-REPO.git ~/src/contoso-api
cd ~/src/contoso-api
git switch main
git status --short
```

For an existing local checkout, instead run `cd /path/to/your/project`, `git switch main`, and `git status --short`. Resolve or commit existing changes before proceeding. Check `git remote -v` and verify that you can push to `origin`.

For a new project, create an empty writable remote first, then replace its URL below. These commands create and push an initial commit:

```bash
mkdir -p ~/src/contoso-api
cd ~/src/contoso-api
git init -b main
git remote add origin https://github.com/YOUR-ORG/YOUR-REPO.git
printf 'Initial project content\n' > PROJECT.txt
cat > test_project.py <<'PYTEST'
import unittest

class ExampleTest(unittest.TestCase):
    def test_example(self):
        self.assertTrue(True)
PYTEST
git add PROJECT.txt test_project.py
git diff --cached
git commit -m "Initial commit"
git push -u origin main
```

If the remote rejects the push, fix access or choose an empty writable remote; do not force push. For an existing project, ignore generated test files before configuring Cardine, review and commit that change, and push it. For the new-project example, wait until after `init`: it creates `.gitignore`. Run your actual test command now and fix failures before continuing. The new example contains one placeholder test; use `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest` to avoid creating bytecode before initialization.

## Initialize or adopt

From the project checkout, write a validation declaration outside it. Replace the example test command with one that passes in your project:

```bash
cat > ~/contoso-validation.json <<'JSON'
{"commands": {"test": "python3 -m unittest"},
 "baseline": ["test"],
 "candidate": {"REUSE": [], "BOUNDED": ["test"], "FULL": ["test"]}}
JSON
```

Choose `lean` or `governed`: governed defaults to independent review and requires an authority field. Each task can override the defaults. Both need an expected code surface for `cardine run`.

The `--task-identity` choice controls numbering: `opaque` permits simple IDs such as `001` and `002`; `milestone` requires a milestone, workstream and sequence, such as `M1-API-001` and `M1-API-002`. The examples below use `opaque`; replace it with your confirmed choice. If you choose `milestone`, also replace `001` throughout the task example with a valid milestone ID.

The agent can run the following commands from the project root; the maintainer reviews each result. For an existing project, preview adoption:

```bash
cardine adopt --project . --check --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque --validation ~/contoso-validation.json
```

Expect a plan without changes. Inspect conflicts and diagnostics; correct inputs and rerun the preview if needed. Then rehearse in a disposable clone:

```bash
cardine adopt --project . --rehearse --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque --validation ~/contoso-validation.json
```

Inspect the rehearsal result; resolve reported problems and repeat it before applying. With the maintainer's consent, apply from the project root:

```bash
cardine adopt --project . --apply --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque --validation ~/contoso-validation.json
```

For a new project with no conflicting generated paths, use `init` instead. Preview and inspect its plan, then consent and apply; `init` has no rehearsal option:

```bash
cardine init --project . --check --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque --validation ~/contoso-validation.json
```

Inspect the plan and resolve conflicts. When the maintainer consents, apply:

```bash
cardine init --project . --apply --name "Contoso API" --slug contoso-api \
  --preset lean --language English --task-identity opaque --validation ~/contoso-validation.json
```

Expect Cardine project files in the checkout. If apply reports a problem, inspect the diagnostics and `git status` before retrying. Review all changes, stage only the intended files, inspect the staged diff, then commit and push. For example, after checking the list with `git status --short`:

```bash
git add -- <each-intended-path>
git diff --cached
git commit -m "Configure Cardine"
git push origin main
```

Replace `<each-intended-path>` with the actual paths; do not type the placeholder. If the push fails, fix the cause and retry without repeating the commit. In the new-project example, ignore the test byproducts, review the staged change, and push it before running tests without `PYTHONDONTWRITEBYTECODE=1`:

```bash
printf '\n__pycache__/\n' >> .gitignore
git add .gitignore
git diff --cached
git commit -m "Ignore generated test files"
git push origin main
```

## Connect an agent host

Skip this section for terminal-only work. From the project checkout, the maintainer or agent previews setup:

```bash
cardine setup --check --project .
```

Review the changes to the host and project, then the maintainer consents to applying them:

```bash
cardine setup --apply --project .
```

For Claude Code run `cardine doctor --host claude --project .`. For Codex, restart Codex after setup, then run `cardine doctor --host codex --project .`. Inspect diagnostics and correct any reported problem. Setup installs Codex project skills; Claude Code uses the separately installed plugin.

## Create and deliver a task

From the project root, the agent drafts the contract, scope, dependencies, and validation based on the maintainer’s goal and the project. The maintainer reviews the proposal and supplies missing domain decisions. For the fictional example, the agent can prepare this proposal outside the checkout, replacing its content and test command with a meaningful task for the project:

```bash
cat > ~/proposal-001.md <<'MARKDOWN'
# Task 001 — Document the project purpose

> **ID**: `001`
> **Category**: Quick

## Objective

Document the project purpose.

## Acceptance Criteria

- README.md describes the project as a fictional example.

## Expected code surface

- `README.md`

## Dependencies

None.

## Validation

- `test`: `python3 -m unittest`
MARKDOWN
cardine task new 001 --quick --record ~/proposal-001.md --project .
git status --short
```

Expect task records in the checkout. The agent reviews and stages only their paths, inspects `git diff --cached`, commits with `git commit -m "Add task 001"`, and runs `git push origin main`, under the project’s permissions. If task creation reports an error, fix the proposal and retry. If push fails, repair it before delivery.

The agent runs `cardine run 001 --project .` and follows every returned `next.command`. When `work` requests implementation, it makes and commits the change in the returned worktree, then runs the next command. Cardine validates and lands the task when its gates pass; independent review requires a separate session. On `done`, the agent verifies from the project checkout:

```bash
git switch main
git pull --ff-only origin main
cardine status --project .
git log -1 --oneline
```

The agent confirms task 001 is done and its change is present on `main`, shows the maintainer what landed, and points to [everyday use](#everyday-use). It then offers: “Describe your next real goal, and I will inspect the project and propose a task for your review.” It does not start another task until the maintainer chooses a goal. If an outcome is `blocked`, inspect its stop code and resume instruction; make the required decision or repair and run that instruction. For `waiting`, wait the specified seconds; for `iterate`, fix the work and continue. See [stops and recovery](RUN_COMMANDS.md#stops-and-recovery).

## Project console

From the project checkout, run `cardine console --project .`. Use ↑/↓ or `j`/`k` to select a task, Enter for details, and Esc to return. Press `/` and type an ID or title to search, then Enter; press `q` to quit. `?` shows the available keys. The console is optional and shows status and the next action; continue delivery using the lifecycle commands above.


## Everyday use

Describe the goal and any domain knowledge or constraints to your agent. It inspects the project, drafts any needed specification and task contract, proposes acceptance criteria, validation commands, code scope and dependencies, and asks you to review the proposal and decide any open questions. After your approval, it registers and publishes the task under the project's permissions, then drives the run loop. You review its proposals and make required decisions; you do not need to provide a prewritten contract.

These examples use the v0.9.1 CLI and the project's installed workflow. The commands shown are actions for the agent or diagnostic references, except opening the optional console and developer-only confirmations.

| Goal | Ask the agent | Agent action | Maintainer action |
| --- | --- | --- | --- |
| Check progress | “What is the status and next action?” | Inspect `cardine status --project .` and explain the result. | Optionally open the [console](#project-console). |
| Start a new task | “I want to achieve …” | Inspect, propose specification and task contract, then use `cardine task new` and publish the reviewed records. | Explain the goal and domain context; review and approve the proposal. |
| Deliver a task | “Proceed with 001” | Follow `cardine run 001 --project .`, its work requests and next commands through landing. | Decide any human stop. |
| Run the lifecycle | “Run lifecycle 001” | Follow the installed lifecycle orchestration; arrange separate implementer and reviewer sessions when required. | Provide required decisions and owner acceptance where applicable. |
| Review or fix review findings | “Review 001” or “Address review 001” | Use an independent reviewer session for review; the implementer reads the durable findings and remediates. | Supply any required owner verdict; do not approve the implementer's own work as a reviewer. |
| Handle waiting or a stop | “Continue 001” | Wait `retry_after_seconds` when requested, follow `next.command`, or explain a blocked code and its resume instruction. | Decide or repair the named human-only issue, then authorize resumption. |
| Cancel or abort | “Cancel 001 because …” or “Abort 001” | Explain consequences and prepare the appropriate action. Cancellation is terminal and does not satisfy dependencies; abort restores the caller-owned candidate and lease and leaves the task resumable. | Run and confirm the developer-only `cardine cancel` or `cardine abort` in an interactive terminal. |
| Diagnose a host | “Check my Codex host” | Inspect diagnostics such as `cardine doctor --host codex --project .` and propose repairs. | Review and consent to host setup or changes. |

For exploratory tasks, see [spikes](OPERATOR_PROMPTS.md); for CI gates, see the [project declaration](PROJECT_DECLARATION.md); for upgrades and maintenance, see the [upgrade guide](HOW_TO_UPGRADE.md). The [run command reference](RUN_COMMANDS.md) explains outcomes and developer-only confirmations.
