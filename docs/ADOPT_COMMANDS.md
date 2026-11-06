# Project adoption

Use `cardine adopt --project <path> --check` to inspect the conversion plan without writes. The JSON result lists ordered output paths and digests, diagnostics, missing inputs, and refusals. Supply `--name`, `--slug`, `--language`, and `--validation <json-file>`; projects without a legacy installation also require `--preset lean|governed` and `--task-identity opaque|milestone`. Optionally supply `--ci <json-file>` for a CI declaration.

Use `--rehearse` with the same inputs to convert and verify a disposable clone. `--apply` uses a matching rehearsal receipt or rehearses first, then converts the clean source project. Neither mode commits or pushes. The JSON envelope reports the plan, result, and diagnostics. Exit status is 0 on success, 2 on a guardrail or conversion failure, and 64 for invalid command syntax.
