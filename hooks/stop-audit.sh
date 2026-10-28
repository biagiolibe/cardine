#!/bin/bash
# Compatibility shim for the frozen plugin registration in hooks/hooks.json.
# The product entry is `cardine hook stop-audit --host <host>`; this file only
# names the Claude host for that registration and holds no audit logic. It
# always exits 0 and never blocks the stop.
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

"$CARDINE_BIN" hook stop-audit --host claude >/dev/null 2>&1
exit 0
