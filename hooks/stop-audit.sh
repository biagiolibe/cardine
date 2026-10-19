#!/bin/bash
# Cardine stop-audit — Stop hook.
# Records BLOCKED <CODE> reports in the final assistant message that no
# Cardine command emitted. Advisory only: it always exits 0 and never blocks
# the stop. The CLI decides whether the directory is a Cardine project.
set -uo pipefail

HOOK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CARDINE_BIN="$HOOK_ROOT/bin/cardine"
for PLUGIN_DIRECTORY in "${PLUGIN_ROOT:-}" "${CLAUDE_PLUGIN_ROOT:-}"; do
  [ -x "$CARDINE_BIN" ] && break
  [ -n "$PLUGIN_DIRECTORY" ] && CARDINE_BIN="$PLUGIN_DIRECTORY/bin/cardine"
done
if [ ! -x "$CARDINE_BIN" ]; then
  CARDINE_BIN="$(command -v cardine 2>/dev/null || true)"
fi
[ -n "$CARDINE_BIN" ] && [ -x "$CARDINE_BIN" ] || exit 0

"$CARDINE_BIN" hook stop-audit >/dev/null 2>&1
exit 0
