# Agent operations

This reference covers the project console, Codex approvals and hooks, local
session usage, and language policy. For the task lifecycle see
[Run commands](RUN_COMMANDS.md).

## Project console

`cardine console` opens the experimental project state console. It refreshes
local state every two seconds by default; `--project` selects a project and
`--interval` sets the refresh period from 0.2 to 60 seconds. The project state
view is read-only, though copying writes to the clipboard and launching an
agent can change the project.

Press `?` for help. The keys are:

| Key | Action |
| --- | --- |
| Up/Down or `j`/`k` | Select a task. |
| Tab/Shift+Tab | Cycle status filters; tabs can also be clicked. |
| Enter | Open full task details. |
| `o` | Open run output. |
| Esc | Return to the task list. |
| `/` | Search task ID or title. |
| `[` / `]` | Scroll task details. |
| `c` or click `[copy]` | Copy a permitted task directive. |
| `l` | Choose Claude Code or Codex to launch in an iTerm2 split pane. |
| `r` | Refresh now. |
| `q` | Quit. |

The footer also offers `x` for cancel and `a` for abort. The launch panel
requires an agent selection and rechecks task state. Resuming an active task
requires confirmation, with an additional confirmation for a dirty worktree.
The first agent splits the console pane vertically; subsequent agents split an
existing agent pane horizontally. Launch requires macOS and iTerm2; copying a
directive remains available when launch is unavailable.

## Codex approvals and hooks

`cardine setup --check` previews setup; `cardine setup --apply` applies it.
The managed user-level approval file is `~/.codex/rules/cardine.rules`; the
project file is `.codex/rules/cardine.rules`. Codex loads project rules only
when the project's `.codex` layer is trusted in `~/.codex/config.toml`.
Rules from the available layers combine, with the most restrictive matching
decision taking precedence. Use the execution tool's working-directory setting
instead of relying on a general prefix rule for `git -C`.

The project file documents an offline check using `codex execpolicy check`;
confirm activation separately in a trusted session. Issue one command per
execution call: the offline checker evaluates argument vectors, and shell
chains are not a reliable way to check each segment.

Setup registers Codex hooks in `~/.codex/hooks.json`. Review and trust them in
Codex with `/hooks`. The read guard checks recognized shell reads before
execution and blocks those whose effective output from large files exceeds the
configured threshold, 400 lines by default. It does not parse arbitrary shell
or scripts. Use `rg -n` to locate content and bounded `sed -n` reads when
appropriate. The stop audit is also registered by setup.

## Local session token usage

`cardine usage report --format text` summarizes local Codex and Claude Code
session counters. The experimental report supports `--host`, `--project`,
`--since`, `--breakdown`, and JSON output. It reports aggregate counters and
metadata without displaying prompts or tool arguments. Input includes cached
input; cached is the cache-read portion. Unsupported or absent host log formats
are reported as such.

## Language behavior

A project's `LANGUAGE_POLICY.md` records its conversation language and requires
persistent repository text to be in English. Agents follow that preference
regardless of an individual prompt's language. An explicit change to the
conversation language must update the policy as well. For example, Contoso's
operators and agents use the language recorded in Contoso's own policy.
