# Project Execution Evidence Profile

This profile is advice. The engine runs only the validation commands a task declares and records their measured results.

<!-- CARDINE:BEGIN capability=long-command-waits v2 -->
Advice: start a command expected to run over a minute with a wait that covers it, and poll at most once; each empty poll re-sends the context. During work run only the touched modules' tests, and the full suite once after the last code change.
<!-- CARDINE:END -->

Advice: reuse unchanged session facts and successful validation, in review too. Locate a large file's range before reading it.

Advice: diagnose progressively: the failing check's bounded output, then the narrowest single test, then verbose output. State the evidence gap before a second hypothesis instead of repeating test-and-fix cycles.

Advice: inspect every changed hunk with `git diff -- <path>` and prefer deterministic checks; capture a manual view only for a perceptual criterion.

Criteria that conflict and that no check can settle are a scope change (`BLOCKED SCOPE_CHANGE_REQUIRED`).
