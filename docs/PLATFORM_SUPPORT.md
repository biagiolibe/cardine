# Platform support

Supported means Meridian's repository checks and full test suite run in CI on
that OS. Best-effort features depend on a local host, terminal, or desktop
integration that CI does not exercise end to end. Unsupported platforms and
features have no support commitment.

| Platform or requirement | macOS | Linux | Windows |
|---|---|---|---|
| Meridian CLI and workflow tooling | Supported (`macos-latest` CI) | Supported (`ubuntu-latest` CI) | Unsupported |
| Python 3.12 or later | Supported (3.12); best-effort (newer versions) | Supported (3.12); best-effort (newer versions) | Unsupported |
| Git on `PATH`, including linked worktrees | Supported (runner-provided Git) | Supported (runner-provided Git) | Unsupported |
| Claude Code host integration | Best-effort (local installation required) | Best-effort (local installation required) | Unsupported |
| Codex host integration | Best-effort (local installation and effective worktree access required) | Best-effort (local installation and effective worktree access required) | Unsupported |
| Console snapshot (`--once`) and interactive view | Supported (interactive view requires a TTY) | Supported (interactive view requires a TTY) | Unsupported |
| Console copy to clipboard | Best-effort (`pbcopy`) | Best-effort (`wl-copy` or `xclip`) | Unsupported |
| Console agent launch | Best-effort (iTerm2 and `osascript` required) | Unsupported | Unsupported |

Both CI jobs run `python3 scripts/check_repository.py` and
`python3 scripts/run_tests.py --parallel` with Python 3.12. Newer Python
versions are best-effort until tested in CI. Git uses the version supplied by
each runner; no separate minimum Git version is certified. Tests that require
unavailable local tools report their own named skips. CI does not validate
live Claude Code or Codex sessions, desktop clipboard access, or an actual
iTerm2 agent launch. The console keeps the directive available for manual copy
when clipboard or launch integration is unavailable.
