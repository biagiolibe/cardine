# Project Execution Evidence Profile

This default profile is fully configured and may be tightened by an explicit
task contract. A project may replace command names with its own equivalents,
but unresolved placeholders are never verification evidence.

## Context and diagnostics

- Reuse unchanged sources and successful results from the active session.
- Locate a large-file range before reading it; the default threshold is 400
  lines.
- Allow at most two context expansions and three diagnostic hypotheses per
  failure. Stop with `BLOCKED CONTRACT_EXHAUSTED` when the applicable task contract is exhausted.
- Start with the failing check's ordinary bounded output, then run the
  narrowest single-test or file-specific diagnostic. Use verbose output or a
  full trace only when those two levels cannot identify the cause.

## Validation output

Run required checks with a producer-status-preserving bound:

```bash
set -o pipefail
<required validation command> 2>&1 | tail -n 200
```

The task record supplies each required validation command. Record the literal
command, its exit status, and the material final lines. Never treat the example
placeholder above as an executable project check.

Run a command expected to take longer than one minute in the foreground with a
timeout of up to 600 seconds, or in a persistent terminal session; never
detach it and poll for completion.

<!-- MERIDIAN:BEGIN capability=long-command-waits v1 -->
Long commands and suite runs:

- Start a command expected to take longer than one minute with a wait long
  enough to cover its expected duration in the same call. Poll an already
  running command at most once, and only after that wait has expired; never
  loop on empty polls, because each one re-sends the whole context.
- Codex returns control from a command session when the requested wait ends,
  not when the command ends, so ask for a wait that covers the expected
  duration in the call that starts the command. If the host caps the wait below
  that duration, use the cap once and then one further wait, not repeated short
  polls. Observed on codex-cli 0.160.0: a command cell starts with
  `yield_time_ms` and `max_output_tokens`, and a still-running cell is resumed
  with `wait` (`cell_id`, `yield_time_ms`, `max_tokens`). A wait of 60000 ms
  was honored in full; no larger value was exercised, so the maximum is not
  stated here.
- During implementation, run only the tests of the modules the task touches.
  Run the full suite once, after the last code change, as the validation of
  record, and rerun it only when code changed since. This does not change the
  declared candidate validation (`REUSE`, `BOUNDED`, `FULL`) in
  `docs/WORKTREE_LIFECYCLE.md`.
<!-- MERIDIAN:END -->

## Diff and manual evidence

- Before and after material edits, use `git status --short` and
  `git diff --stat`; inspect every changed hunk with `git diff -- <path>`.
- Prefer unit, integration, schema, hash, and command-output checks. Capture a
  manual view only for a genuinely perceptual acceptance criterion, with at
  most two distinct views per criterion unless the task explicitly authorizes
  more.

## Runtime configuration

Faster execution is allowed only when it preserves required evidence.
