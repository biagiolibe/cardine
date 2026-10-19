# Project Execution Evidence Profile

This project-owned profile applies Meridian's stack-agnostic execution-evidence
discipline to its actual tools. Configure it during bootstrap, or before the
next implementation after a framework upgrade adds this file. Keep commands and
tool choices current; the task's declared validation and acceptance criteria
remain mandatory.

## Context reuse

- Sources already supplied by the active agent environment: `[describe them]`.
- When an exact reread is justified: `[describe the evidence-gap standard]`.
- Read-guard threshold and the condition that requires a range instead of a
  whole-file `Read`: `Read-guard threshold`: 400 lines. A `Read` of a file
  past this line count with no `offset`/`limit` is mechanically denied
  outside the task's Authority/exemptions; locate the needed lines with
  `grep -n` first, then read that range. Override with a different numeric
  value when this project's files are legitimately larger.
<!-- MERIDIAN:BEGIN capability=investigation-scope v3 -->
- Record broad exploration with its question, source scope, sources, and
  finding using `meridian execution investigate`.
<!-- MERIDIAN:END -->

## Successful validation output

Record each required check as the complete literal command string that is
actually run, including its own output-bounding stage — not a bare command
plus a prose instruction to summarize or truncate the output afterwards. A
bound stated only in prose can govern nothing but how the output gets
*restated* once it has already been returned to the session and billed in
full; the command string is the only point that controls how much output
ever enters context at all. The shell shape is:

```bash
set -o pipefail
<validation command> 2>&1 | tail -n <this project's chosen bound>
```

`set -o pipefail` is not optional: without it, a pipeline reports the exit
status of its last stage (here, `tail`), which is always success, so a
failing validation command silently reads as passing. Where the shell lacks
`pipefail`, capture `${PIPESTATUS[0]}` explicitly instead.

If the chosen bound instead keeps only the *first* N lines, it must consume
the whole stream — `awk 'NR<=N'` or `sed -n '1,Np'` — never `head -n N` or
`sed 'Nq'`: an early-exiting stage closes the pipe, `SIGPIPE` kills the
producer with status 141, and `pipefail` then reports a failed pipeline for a
command that actually succeeded. The fault is intermittent — it fires only
once output exceeds the bound — so it passes on a small project and starts
failing as the suite grows. See `WORKFLOW_GUIDE.md` for the measured example.

- Required validation commands, each as the exact string executed —
  command, redirection, and output bound together: `[commands]`.
- Exit-status mechanism this project uses (`set -o pipefail` or
  `${PIPESTATUS[0]}`) and how the captured status is reported: `[method]`.
- The output bound itself (line count, byte count, or equivalent) is this
  project's own choice; record the chosen value and where it is applied:
  `[bound]`.

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

## Failure diagnostics

- First targeted diagnostic or bounded-log procedure: `[procedure]`.
- Conditions for full traces, verbose output, or complete logs: `[conditions]`.
## Diff inspection

- Change-summary command or procedure, run before the first code edit and
  after each material change: `[command or procedure]`.
- Per-file/hunk inspection procedure: `[command or procedure]`.

## Manual evidence

- How this project's own observables realize `docs/CONTEXT_BUDGET_POLICY.md`'s
  evidence tiers — where a tier-2 derived value is read back, and what channel
  captures a genuine tier-3 perceptual one: `[tier mapping]`.
- Primary deterministic evidence when available: `[tests or checks]`.
- Direct capture path and interactive-tool fallback: `[tools or procedure]`.

## Runtime configuration

- Faster-execution-mode availability and constraints: `[policy]`.
