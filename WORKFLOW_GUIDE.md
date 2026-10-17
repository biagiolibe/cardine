# Lean Delivery Guide

Lean Delivery is Meridian's complete lightweight workflow for small projects,
proof-of-concepts, demos, experiments, and reversible low-risk changes. It
preserves scope, verification, and visible progress without the dependency and
integration controls of Governed SDD.

## Workflow modes

Meridian offers two modes.

- **lean-delivery**: the lightweight checkbox workflow described in this guide; suitable for small projects, POCs, demos, experiments, and reversible low-risk iterations.
- **governed-sdd**: uses `PROJECT_WORKFLOW.md`, ADRs, atomic tasks with dependencies, a review policy, task worktrees, and a reviewer-integrator. Use it when agents should be able to receive only a task ID without repeating the operating process each time.

The complete Lean Delivery rules are in `templates/workflows/lean-delivery/`; governed rules are in `templates/workflows/governed-sdd/`. Do not mix their lifecycles. `classic` is accepted only as an initialization alias for `lean-delivery`.

## 1. Philosophy: Think big, act small

The key to effective AI work on complex projects is isolating context. Instead of asking an agent to “add a feature”:

1. Define the feature in the general backlog.
2. Extract an independent task with all necessary context.
3. Give it to the agent in a new session.

## 2. The model pillars

| File | Role | When to use it |
|------|------|----------------|
| `PROJECT_PLAN.md` | Vision and backlog | When planning new high-level features. |
| `TECH_DESIGN.md` | Technical reference | When defining architecture and conventions. |
| `tasks/QUEUE.md` | Work queue | Every day, to know what comes next and who owns it. |
| `tasks/NNN-task.md` | Agent briefing | When delegating a specific code change. |
| `LANGUAGE_POLICY.md` | Language invariant | Before every agent response or persistent edit. |

## 3. Starting a project (Day 0)

1. Copy the template files into the root of the new project.
2. Fill in `TECH_DESIGN.md` with the stack and module structure.
3. Fill in `PROJECT_PLAN.md` with high-level features.
4. Select the persistent conversation language in `LANGUAGE_POLICY.md`. Repository artifacts always remain in English, even when the conversation uses another language.

## 4. Daily work cycle

### Phase A: Triage and planning

The developer chooses an approved feature from `PROJECT_PLAN.md`.

- If it is simple (for example, renaming a variable), add it to the queue as a quick task without a file.
- If it is complex, create a new file in `tasks/` from `TASK_BLUEPRINT.md`.

### Phase B: Prepare the task file

Fill in the task file (for example, `tasks/001-name.md`). Ensure that it includes:

- **Objective**: What must change?
- **Acceptance criteria**: How can completion be verified?
- **Technical context**: Paste the relevant code or explain exactly where to make the change. The agent should not need to guess.

### Phase C: Delegate

Assign the task in `tasks/QUEUE.md` by changing its state from `[ ]` to `[/]`. Open a new agent session and ask it to read and execute that task file in the current project. Agents do not select the next task autonomously.

### Phase D: Verify and archive

After the agent finishes:

1. Verify the acceptance criteria and run the task validation plus applicable baseline checks.
2. Move the task file to `tasks/done/`.
3. Mark it `[x]` in `QUEUE.md` and `PROJECT_PLAN.md`.
4. When the last open task in an Active Queue phase or section is complete, move that section to `tasks/QUEUE_ARCHIVE.md` (create it when absent). `QUEUE.md` should contain only work with something still open, keeping the context cost low.

## Bounded validation commands by stack

`docs/EXECUTION_EVIDENCE_PROFILE.md` asks a governed-SDD project to record
each required validation check as the literal command string it runs,
output bound included, using the stack-agnostic shape:

```bash
set -o pipefail
<validation command> 2>&1 | tail -n <chosen bound>
```

The template itself names no language, build tool, or test runner; these
worked examples exist only here, in this repository's own documentation, not
in anything copied into a project.

**Rust (`cargo`)**

```bash
set -o pipefail
cargo test --workspace 2>&1 | tail -n 60
```

**Node.js (`npm`)**

```bash
set -o pipefail
npm test --silent 2>&1 | tail -n 60
```

**Python (`pytest`)**

```bash
set -o pipefail
python3 -m pytest -q 2>&1 | tail -n 60
```

In each case, `set -o pipefail` is what makes the pipeline's exit status
reflect the validation command instead of `tail`'s (which always succeeds).
Where the shell lacks `pipefail`, capture `${PIPESTATUS[0]}` immediately
after the pipeline and report that value instead.

### Which end to keep

`tail` suits a test runner, which stops at the failing target and prints the
panic, assertion, and failure list last. A compiler or formatter is the
opposite: it emits findings in source order, the first is usually the root
cause and the later ones its consequences, so a tail bound cuts exactly the
line worth reading. Choose the stage per command rather than uniformly — for
example, head-bounded `cargo check` / `cargo fmt --check` alongside
tail-bounded `cargo test`.

### Never use `head` for the first-lines bound

Use `awk 'NR<=40'` (or `sed -n '1,40p'`), never `head -n 40`:

```bash
set -o pipefail
<compiler or formatter> 2>&1 | awk 'NR<=40'
```

`head` exits after its last line. The producer then writes into a closed
pipe, `SIGPIPE` kills it with status 141, and `pipefail` reports a failed
pipeline for a command that succeeded. Measured on a real project whose
passing test suite emits 111 lines against a 40-line bound:

| Pipeline | Exit status |
|---|---|
| `cargo test --workspace --quiet \| head -n 40` | **101** — suite passing |
| `cargo test --workspace --quiet \| awk 'NR<=40'` | 0 |
| `cargo test --workspace --quiet \| tail -n 40` | 0 |

The distinction is not `head` versus `awk` as such — it is which stage exits
early. `head -n N` and `sed 'Nq'` close the pipe; `awk 'NR<=N'` and
`sed -n '1,Np'` consume the whole stream and only stop printing. `tail` is
safe for the same reason: it must reach the end to know where the end is.

The fault is intermittent by construction: it fires only when output exceeds
the bound, so it passes on a small project and starts failing as the suite
grows. Neither idiom masks a real failure — a failing command still exits
non-zero through `awk` or `tail` when `pipefail` is set, and exits 0 through
either without it.

## Tips for success

- **Keep tasks atomic**: if a task takes more than two hours, it can probably be split into smaller tasks.
- **Isolate modules**: modular code makes it easier for an agent to work without breaking the rest of the project.
- **Protect the queue**: do not start five tasks at once. Finish and archive one before assigning the next.
- **Keep the queue lean**: archive completed sections as they close. Delete obsolete snapshot documents that are no longer referenced instead of leaving them as unnecessary context.

To bootstrap a project, run `/meridian-init`. To create a task, run `/meridian-task`.
