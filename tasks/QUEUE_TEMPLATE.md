# Task Execution Queue

This is the operational execution queue. Tasks are ordered by priority.

Fully closed phases or sections (all `[x]`) belong in [`QUEUE_ARCHIVE.md`](QUEUE_ARCHIVE.md), not here. This file tracks only work with open items, keeping the reading cost low in every session. Consult the archive only when the history or rationale of a past phase is needed.

## How to use this queue

- **Execution**: The developer assigns a specific `[ ]` task; agents do not select work autonomously.
- **Update**: Change `[ ]` to `[/]` when starting and to `[x]` only after acceptance criteria and stated validation pass.
- **Delegation**: Follow the delegation instructions in the task file.
- **Task-file archive**: When a task is complete, move its file to `tasks/done/`.
- **Queue archive**: When an entire Active Queue phase or section becomes `[x]`, move its rows to `tasks/QUEUE_ARCHIVE.md` (create it if absent, reusing this file's structure) instead of accumulating them here. Archive a phase as soon as it closes.

## Priorities

| Code | Meaning |
|------|---------|
| 🔴 P1 | Blocking / Critical |
| 🟡 P2 | Important feature |
| 🟢 P3 | Optimization / Polish |

## 🤖 How to delegate a task to an agent

### Antigravity (local AI)

Open a new chat and write: “Read `tasks/NNN-name.md` and execute the task. The project is located at `...`.”

### Claude CLI

```bash
claude "$(cat tasks/NNN-name.md)"$'\n\nExecute this task in the current project.'
```

## 🏃 Active Queue

| Status | ID | Title | Priority | Agent | Task File |
|--------|----|-------|----------|-------|-----------|
| `[/]` | 001 | Example: Initialize ECS | 🔴 P1 | Antigravity | [001](001-init-ecs.md) |
| `[ ]` | 002 | Example: Create spawner | 🟡 P2 | — | [002](002-spawner.md) |

## 🧪 Quick Tasks (No File)

Tasks that take less than 15 minutes and do not need a detailed briefing.

| Status | Description | Priority |
|--------|-------------|----------|
| `[ ]` | Clean up imports | 🟢 P3 |

## ✅ Archived (Completed)

Keep only recently completed items relevant to active work here. When this section or an entire Active Queue phase is closed and no longer needed for immediate reference, move it to `tasks/QUEUE_ARCHIVE.md`.

| Status | ID | Title | Agent | File |
|--------|----|-------|-------|------|
| `[x]` | 000 | Define architecture | Manual | [000](done/000-arch.md) |

*Last updated: [Date]*
