# One complete Lean Delivery task

This example uses the current checkout's templates and CLI. It adds one
sentence to a new documentation project and closes task `001`. No sample
project is committed. The executable fences below run in order in one Bash
session; `text checked=...` fences are literal substrings checked at that point.
The regression test is `tests/test_lean_walkthrough.py`.

## Environment and host steps

Install Cardine first using the [quick start](../QUICKSTART.md). For this
exercise, start in an empty Git repository on `main`, with author identity
configured and an empty **local bare** repository registered as `origin`.
The test supplies these through the existing `WorktreeLifecycleCliTest`
fixture and its `create_bare_origin` helper. It needs no network or host setup.
Set `CARDINE_ROOT` to the installed framework checkout and
`CARDINE_WORKTREE_ROOT` to a writable disposable worktree directory. The test
sets both, plus a disposable HOME, so it does not touch your user configuration.

**Host step — initialization:** in Claude Code use `/meridian-init`; in Codex
follow `commands/meridian-init.md` from the installed framework. Choose
`Walkthrough`, the `lean` preset, `opaque`, and `English` when asked. The script
below reproduces its template-copy, placeholder, and lock steps for
this empty project. It does not exercise the interactive host or imply consent
to machine setup. In a real host, review setup separately and confirm actual
worktree access as described in the quick start.

```bash
set -euo pipefail
export PATH="$CARDINE_ROOT/bin:$PATH"
export PRIMARY="$PWD"
python3 - <<'PY'
import os
import shutil
from pathlib import Path
root = Path(os.environ["CARDINE_ROOT"])
shutil.copytree(root / "templates/single", Path.cwd(), dirs_exist_ok=True)
for path in Path.cwd().rglob("*"):
    if path.is_file() and ".git" not in path.parts:
        text = path.read_text()
        for old, new in (("[Project Name]", "Walkthrough"), ("[Data]", "2026-10-15"),
                         ("[Date]", "2026-10-15"), ("[Conversation language]", "English")):
            text = text.replace(old, new)
        path.write_text(text)
Path("tasks/done").mkdir(exist_ok=True)
PY
cardine lock --project . --mode single
```

The initialized files include `PROJECT_WORKFLOW.md` (the shared lifecycle),
`AGENTS.md`, `CLAUDE.md`, `LANGUAGE_POLICY.md`, `TECH_DESIGN.md`,
`PROJECT_PLAN.md`, `tasks/QUEUE.md`, the task blueprint, the `docs/`
and `.codex/` files, and the generated `.cardine/manifest.json` and baseline.
Fill in the real project's design, commands, conventions and toolchain before
implementation. Here the stack is Markdown and Git, and the only gate is
whitespace validation plus inspection of the requested sentence.

## Define the bounded task

**Host step — task creation:** normally `/meridian-task` or the Lean Delivery
skill helps write this contract. We write its exact result below and register it
with `cardine task new`, which publishes the record together with its validated
`queued` state. The queue and the plan's status region are generated views;
`cardine status --write` renders them from that state. The candidate policy is
deliberately limited to this documentation exercise.

```bash
export RECORD="$(mktemp)"
python3 - <<'PY'
import json
import os
from pathlib import Path
Path(".cardine/project.json").write_text(json.dumps({
    "version": 1, "preset": "lean", "taskIdentity": {"mode": "opaque"},
    "validation": {"commands": {"whitespace": "git diff --check"},
                   "baseline": ["whitespace"],
                   "candidate": {name: [] for name in ("REUSE", "BOUNDED", "FULL")}}
}) + "\n")
Path("TECH_DESIGN.md").write_text("# Technical design\n\nMarkdown documentation; Git for version control.\n")
Path("README.md").write_text("# Walkthrough\n")
Path(os.environ["RECORD"]).write_text("""# Task 001 — Add the purpose sentence

> **ID**: `001`
Priority: P1
Estimate: 15m

## Objective

Add the project purpose to README.md.

## Acceptance Criteria

- [ ] README.md contains: This project demonstrates Lean Delivery.

## Relevant Files

- README.md — project introduction.

## Out of scope

Application code and other tasks.

## Validation

- `whitespace`: `git diff --check`

## Dependencies

None.
""")
PY
cardine task new 001 --record "$RECORD" --project .
cardine execution reconcile 001 --apply --project .
cardine status --write --project .
git add .
git commit -m "Initialize the documentation project and task 001"
git push -u origin main
```

Both files are generated from the task's state, so they list the task as queued
and startable:

```text checked=tasks/QUEUE.md
| queued | 001 | Task 001 — Add the purpose sentence | - | - | true |
```

```text checked=PROJECT_PLAN.md
| queued | 001 | Task 001 — Add the purpose sentence |
```

Read the same facts with `cardine status`; it never writes a file.

## Execute in the returned worktree

**Host step — assignment:** send `Proceed with 001`. The commands below show
what the agent does. It uses the returned worktree rather than creating a
second checkout. Starting records `in_progress` with the resolved task policy.

```bash
cardine worktree prepare 001 --project "$PRIMARY" --format json > "$HOME/prepared.json"
export TASK_WORKTREE="$(python3 -c 'import json, os; print(json.load(open(os.environ["HOME"] + "/prepared.json"))["worktree"])')"
cd "$TASK_WORKTREE"
cardine worktree check 001 --project "$PRIMARY" --format json
cardine execution start 001 --project .
git status --short
printf '\nThis project demonstrates Lean Delivery.\n' >> README.md
git diff --check
python3 - <<'PY'
from pathlib import Path
assert "This project demonstrates Lean Delivery." in Path("README.md").read_text()
PY
git add README.md tasks/001.md .cardine/tasks/001.json
git commit -m "Add the project purpose sentence"
```

## Record completion and close the task

The handoff records actual validation, task/base commits, and the relative
worktree identity. Queue and plan stay untouched on the task branch. Close
through the CLI; do not write machine status fields yourself. Closing verifies
the committed record and handoff and writes nothing: the record stays at its
path and the task stays `in_progress`. Only validated landing writes `done` and
regenerates the queue and the plan region on the candidate.

```bash
python3 - <<'PY'
import json
import os
import subprocess
from pathlib import Path
prepared = json.loads((Path(os.environ["HOME"]) / "prepared.json").read_text())
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
record = Path("tasks/001.md")
record.write_text(record.read_text().replace("- [ ]", "- [x]"))
Path("tasks/handoffs").mkdir(exist_ok=True)
Path("tasks/handoffs/001.md").write_text(f"""## Completion Report — 001

- Files changed: `README.md`
- Branch: `task-001`
- Worktree: `{prepared['handoff_worktree']}`
- Validated task commit: `{commit}`
- Validated base commit: `{prepared['base_commit']}`
- Validation: `git diff --check` — exit 0.
- Validation skips: none.
- Manual verification: requested README sentence inspected and present.
- Acceptance criteria: all met.
- Full combined-tree validation required: no; documentation-only sentence.
- Dependencies: none. Behavioral surfaces: README documentation.
- Budget usage: one bounded documentation change; no captures.
- Isolated exploration: none.
- Blockers/deviations: none.
""")
PY
git add tasks/001.md tasks/handoffs/001.md
git commit -m "Record verified completion of task 001"
cardine task close 001 --project .
cd "$PRIMARY"
cardine worktree advance 001 --project . --accepted --validation-command "git diff --check" --validation-exit-code 0 --format json
```

For this unchanged base and declared policy, `advance` stages integration and
returns `action_required: run-candidate-validation`, with `git diff --check`.
It records results; it never executes validation. Run the returned commands on
the candidate, then supply their actual results. If your project returns a
different action or `BLOCKED <CODE>`, follow that result and its resume command.

```bash
git diff --check
cardine worktree advance 001 --project . --accepted --candidate-command "git diff --check" --candidate-exit-code 0 --format json
```

Successful finalization returns `action_required: push`.

```bash
git push origin main
cardine worktree advance 001 --project . --accepted --format json
cardine worktree cleanup 001 --project . --format json
git status --short
git worktree list --porcelain
git branch --list task-001
```

The last advance performs cleanup and returns `action_required: none`.
The explicit cleanup call shows its idempotent result. Status and branch output
are empty, only the primary worktree remains, and `HEAD` equals `origin/main`.
Landing regenerated the queue and the plan status region from the landed
state; nothing was archived or moved:

```text checked=PROJECT_PLAN.md
| done | 001 |
```

```text checked=tasks/handoffs/001.md
- Validation: `git diff --check` — exit 0.
- Validation skips: none.
- Manual verification: requested README sentence inspected and present.
- Acceptance criteria: all met.
```

The completed contract stays at `tasks/001.md`. For an application,
replace the minimal gate with its real checks before assigning a source task.
