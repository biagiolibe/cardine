# One complete Lean Delivery task

This example uses the current checkout's templates and CLI. It adds one
sentence to a new documentation project and closes task `001`. No sample
project is committed. The executable fences below run in order in one Bash
session; `text checked=...` fences are literal substrings checked at that point.
The regression test is `tests/test_lean_walkthrough.py`.

## Environment and host steps

Install Meridian first using the [quick start](../QUICKSTART.md). For this
exercise, start in an empty Git repository on `main`, with author identity
configured and an empty **local bare** repository registered as `origin`.
The test supplies these through the existing `WorktreeLifecycleCliTest`
fixture and its `create_bare_origin` helper. It needs no network or host setup.
Set `MERIDIAN_ROOT` to the installed framework checkout and
`MERIDIAN_WORKTREE_ROOT` to a writable disposable worktree directory. The test
sets both, plus a disposable HOME, so it does not touch your user configuration.

**Host step — initialization:** in Claude Code use `/meridian-init`; in Codex
follow `commands/meridian-init.md` from the installed framework. Choose
`Walkthrough`, `lean-delivery`, `opaque`, and `English` when asked. The script
below reproduces its base-copy, mode-overlay, placeholder, and lock steps for
this empty project. It does not exercise the interactive host or imply consent
to machine setup. In a real host, review setup separately and confirm actual
worktree access as described in the quick start.

```bash
set -euo pipefail
export PATH="$MERIDIAN_ROOT/bin:$PATH"
export PRIMARY="$PWD"
python3 - <<'PY'
import os
import shutil
from pathlib import Path
root = Path(os.environ["MERIDIAN_ROOT"])
for source in (root / "templates/base", root / "templates/workflows/lean-delivery"):
    shutil.copytree(source, Path.cwd(), dirs_exist_ok=True)
for path in Path.cwd().rglob("*"):
    if path.is_file() and ".git" not in path.parts:
        text = path.read_text()
        for old, new in (("[Project Name]", "Walkthrough"), ("[Data]", "2026-10-15"),
                         ("[Date]", "2026-10-15"), ("[Conversation language]", "English")):
            text = text.replace(old, new)
        path.write_text(text)
Path("tasks/done").mkdir(exist_ok=True)
PY
meridian lock --project . --mode lean-delivery
```

The initialized files include `PROJECT_WORKFLOW.md` (the `LEAN_DELIVERY`
lock), `AGENTS.md`, `CLAUDE.md`, `LANGUAGE_POLICY.md`, `TECH_DESIGN.md`,
`PROJECT_PLAN.md`, `tasks/QUEUE.md`, the task blueprint, mode-specific `docs/`
and `.codex/` files, and the generated `.meridian/manifest.json` and baseline.
Fill in the real project's design, commands, conventions and toolchain before
implementation. Here the stack is Markdown and Git, and the only gate is
whitespace validation plus inspection of the requested sentence.

## Define the bounded task

**Host step — task creation:** normally `/meridian-task` or the Lean Delivery
skill helps write this contract. We write its exact result below, reconciling
the template's `001` row and adding a recognizable plan entry. The candidate
policy is deliberately limited to this documentation exercise.

```bash
python3 - <<'PY'
import json
from pathlib import Path
Path("TECH_DESIGN.md").write_text("# Technical design\n\nMarkdown documentation; Git for version control.\n")
Path(".meridian/task-identity.json").write_text(json.dumps({"version": 1, "mode": "opaque"}) + "\n")
Path(".meridian/candidate-validation.json").write_text(json.dumps({
    "version": 1, "state": "declared", "outcomes": {
        name: ["git diff --check"] for name in ("REUSE", "BOUNDED", "FULL")
    }
}) + "\n")
Path("README.md").write_text("# Walkthrough\n")
Path("tasks/001-purpose.md").write_text("""# Task 001 — Add the purpose sentence

> **ID**: `001`

## Objective

Add the project purpose to README.md.

## Acceptance Criteria

- [ ] README.md contains: This project demonstrates Lean Delivery.

## Relevant Files

- README.md — project introduction.

## Validation

- git diff --check
- Inspect the requested sentence in README.md.

## Dependencies

None.
""")
queue = Path("tasks/QUEUE.md")
queue.write_text(queue.read_text().replace("Initial setup", "Add the purpose sentence").replace("001-setup.md", "001-purpose.md"))
plan = Path("PROJECT_PLAN.md")
plan.write_text(plan.read_text().replace("- `[ ]` Initial project setup", "- `[ ]` 001 — Add the purpose sentence"))
PY
git add .
git commit -m "Initialize the documentation project and task 001"
git push -u origin main
```

```text checked=tasks/QUEUE.md
| `[ ]` | 001 | Add the purpose sentence | 🔴 P1 | — |
```

```text checked=PROJECT_PLAN.md
- `[ ]` 001 — Add the purpose sentence
```

## Execute in the returned worktree

**Host step — assignment:** send `Proceed with 001`. The commands below show
what the agent does. It uses the returned worktree rather than creating a
second checkout. A successful Lean start may report no new machine state.

```bash
meridian worktree prepare 001 --project "$PRIMARY" --format json > "$HOME/prepared.json"
export TASK_WORKTREE="$(python3 -c 'import json, os; print(json.load(open(os.environ["HOME"] + "/prepared.json"))["worktree"])')"
cd "$TASK_WORKTREE"
meridian worktree check 001 --project "$PRIMARY" --format json
meridian execution start 001 --project .
git status --short
printf '\nThis project demonstrates Lean Delivery.\n' >> README.md
git diff --check
python3 - <<'PY'
from pathlib import Path
assert "This project demonstrates Lean Delivery." in Path("README.md").read_text()
PY
git add README.md
git commit -m "Add the project purpose sentence"
```

## Record completion and close the task

The handoff records actual validation, task/base commits, and the relative
worktree identity. Queue and plan stay untouched on the task branch. Close
through the CLI; do not write machine status fields yourself.

```bash
python3 - <<'PY'
import json
import os
import subprocess
from pathlib import Path
prepared = json.loads((Path(os.environ["HOME"]) / "prepared.json").read_text())
commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
record = Path("tasks/001-purpose.md")
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
git add tasks/001-purpose.md tasks/handoffs/001.md
git commit -m "Record verified completion of task 001"
meridian task close 001 --project .
git commit -m "Archive closed task 001"
cd "$PRIMARY"
meridian worktree advance 001 --project . --accepted --validation-command "git diff --check" --validation-exit-code 0 --format json
```

For this unchanged base and declared policy, `advance` stages integration and
returns `action_required: run-candidate-validation`, with `git diff --check`.
It records results; it never executes validation. Run the returned commands on
the candidate, then supply their actual results. If your project returns a
different action or `BLOCKED <CODE>`, follow that result and its resume command.

```bash
git diff --check
meridian worktree advance 001 --project . --accepted --candidate-command "git diff --check" --candidate-exit-code 0 --format json
```

Successful finalization returns `action_required: push`.

```bash
git push origin main
meridian worktree advance 001 --project . --accepted --format json
meridian worktree cleanup 001 --project . --format json
git status --short
git worktree list --porcelain
git branch --list task-001
```

The last advance performs cleanup and returns `action_required: none`.
The explicit cleanup call shows its idempotent result. Status and branch output
are empty, only the primary worktree remains, and `HEAD` equals `origin/main`.
The closed queue section moves to the archive; the plan and handoff remain:

```text checked=tasks/QUEUE_ARCHIVE.md
| `[x]` | 001 | Add the purpose sentence | 🔴 P1 | — |
```

```text checked=PROJECT_PLAN.md
- `[x]` 001 — Add the purpose sentence
```

```text checked=tasks/handoffs/001.md
- Validation: `git diff --check` — exit 0.
- Validation skips: none.
- Manual verification: requested README sentence inspected and present.
- Acceptance criteria: all met.
```

The completed contract is now `tasks/done/001-purpose.md`. For an application,
replace the minimal gate with its real checks before assigning a source task.
