# Context Reading Policy

<!-- CARDINE:BEGIN capability=bounded-context-readers v2 -->
## Reading

Advice: read the router, the assigned task, only the `Authority` entries it cites, and the files of its `Expected code surface`; do not scan the repository. Expand only when blocked or when an acceptance criterion cannot be verified, and say why in the report. Read large files by range. For one open-ended question outside that boundary, explore in isolation and keep only the distilled finding and its sources.

Advice: read cited ADRs and specifications with `cardine context authority <TASK-ID>`, one ADR with `cardine adr show <ADR-ID>`, and find a governing one with `cardine adr list`; never open the whole log. For a status request, run `cardine status`; it is not an audit.

Advice: keep plans to three bullets or fewer, report only state changes, findings, validation results, or blockers, and use parallel agents only for independent scopes.
<!-- CARDINE:END -->

## Context-size ceilings

`scripts/check_repository.py` checks these read-set ceilings for `cardine context size --role <role>`:

| Preset | Role | Ceiling (bytes) |
| --- | --- | ---: |
| All presets | status | 10000 |
| All presets | design | 10000 |
| All presets | implementation | 10000 |
| All presets | review | 10000 |
| All presets | remediation | 10000 |
| All presets | lifecycle | 10000 |
