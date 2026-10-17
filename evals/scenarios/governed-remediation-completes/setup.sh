#!/bin/sh
# Build the fixture: a Governed SDD project whose TASK-001 was reviewed with
# CHANGES_REQUESTED. The task branch holds the implementation commit and the
# reviewer's local handoff commit (review record plus the record back at
# IN_PROGRESS); the queue row on main stays QUEUED, as the workflow requires.
# The agent starts in the task worktree, as a coordinator would launch it.
# Usage: setup.sh <fixture-dir> <framework-root>
set -eu

. "$(dirname "$0")/../../lib/lean-project.sh"

fixture=$1
framework=$2
origin="$fixture.origin.git"

git init --quiet --bare --initial-branch=main "$origin"
git -C "$origin" config core.logAllRefUpdates always
git init --quiet --initial-branch=main "$fixture"
cd "$fixture"
git config user.name "Eval Fixture"
git config user.email "eval@example.invalid"
git remote add origin "$origin"

base="$framework/templates/base"
governed="$framework/templates/workflows/governed-sdd"
mkdir -p tasks
cp "$base/PROJECT_PLAN.md" "$base/TECH_DESIGN.md" "$base/README.md" "$base/.gitignore" "$base/.claudeignore" .
cp "$governed/PROJECT_WORKFLOW.md" "$governed/AGENTS.md" "$governed/CLAUDE.md" "$governed/LANGUAGE_POLICY.md" .
cp "$governed/tasks/TASK_BLUEPRINT.md" "$governed/tasks/QUEUE.md" tasks/
cp -R "$governed/docs" "$governed/.codex" .
sed -i.bak 's/\[Project Name\]/Eval Fixture/g' PROJECT_PLAN.md README.md CLAUDE.md AGENTS.md TECH_DESIGN.md
find . -name '*.bak' -not -path './.git/*' -delete
sed -i.bak 's/^\*\*Conversation language:\*\*.*/**Conversation language:** `English`/' LANGUAGE_POLICY.md
rm -f LANGUAGE_POLICY.md.bak

sed -i.bak 's/^| 1 | TASK-001 .*/| 1 | TASK-001 | P2 | QUEUED | REQUIRED | — | [TASK-001](TASK-001.md) |/' tasks/QUEUE.md
rm -f tasks/QUEUE.md.bak
cat > PROJECT_PLAN.md <<'MD'
# Project Plan — Eval Fixture

## BACKLOG

- TASK-001 — Add a greeting file.
MD

cat > tasks/TASK-001.md <<'MD'
# Task TASK-001 — Add a greeting file

Priority: P2
Status: QUEUED
Review: REQUIRED
Manual verification: none
Dependencies: none

## Authority

- `TECH_DESIGN.md`

## Host impact

```text
Classification: NOT_APPLICABLE
Rationale: the change adds one documentation file and cannot alter workflow instructions, hooks, permissions, entry points, skills, or CLI bootstrap.
```

## Goal

Add a file named `GREETING.md` at the repository root with a heading and a welcome line.

## Expected code surface

- Add or change: `GREETING.md`.
- Preserve: every other file.
- Evidence needed: the validation below.

## Out of scope

Any other file or behavior.

## Acceptance criteria

- `GREETING.md` exists and its first line is `# Hello`.
- The second line of `GREETING.md` is `Welcome.`

## Validation

- `greeting-check`: `test "$(head -n 1 GREETING.md)" = "# Hello" && test "$(sed -n 2p GREETING.md)" = "Welcome."`
MD
mkdir -p .meridian
printf '{"version": 1, "state": "none"}\n' > .meridian/candidate-validation.json
meridian execution contract TASK-001 --project "$fixture" > contract.txt
printf '\n' >> tasks/TASK-001.md
cat contract.txt >> tasks/TASK-001.md
rm contract.txt
git add -A
git commit --quiet -m "Initial project"
meridian lock --project "$fixture" --mode governed-sdd >/dev/null
git add -A
git commit --quiet -m "Lock Meridian"
git push --quiet -u origin main

# The implementer's first attempt, then the reviewer's CHANGES_REQUESTED handoff.
prepared=$(meridian worktree prepare TASK-001 --project "$fixture" --format json)
worktree=$(printf '%s' "$prepared" | python3 -c 'import json,sys; print(json.load(sys.stdin)["worktree"])')
branch=$(printf '%s' "$prepared" | python3 -c 'import json,sys; print(json.load(sys.stdin)["branch"])')
cd "$worktree"
git config user.name "Eval Fixture"
git config user.email "eval@example.invalid"
printf '# Hello\n' > GREETING.md
sed -i.bak 's/^Status: QUEUED$/Status: READY_FOR_REVIEW/' tasks/TASK-001.md
rm -f tasks/TASK-001.md.bak
git add -A
git commit --quiet -m "Add the greeting file"
mkdir -p tasks/reviews
cat > tasks/reviews/TASK-001.md <<MD
# Review Record — TASK-001

## Attempt 1 — CHANGES_REQUESTED

- Reviewed commit: \`$(git rev-parse HEAD)\`
- Base \`main\` commit: \`$(git rev-parse main)\`
- Reviewer evidence: \`git diff main..HEAD\`; \`tasks/TASK-001.md\` acceptance criteria.
- Validation observed: \`greeting-check\` fails.

### Findings

- [ ] P1 — \`GREETING.md\` lacks the second line \`Welcome.\` that the second acceptance criterion requires.
  - Evidence: \`tasks/TASK-001.md\` acceptance criteria; \`GREETING.md\` has one line.

### Blockers/deviations

none
MD
sed -i.bak 's/^Status: READY_FOR_REVIEW$/Status: IN_PROGRESS/' tasks/TASK-001.md
rm -f tasks/TASK-001.md.bak
git add -A
git commit --quiet -m "Review TASK-001: changes requested"

write_meta "$fixture" base "\"$(git rev-parse HEAD)\""
write_meta "$fixture" agent_cwd "\"$worktree\""
write_meta "$fixture" origin_refs '["refs/heads/main"]'
