#!/bin/bash
# Meridian stop-audit — Stop hook.
# Records BLOCKED <CODE> reports in the final assistant message that no
# Meridian command emitted. Advisory only: it always exits 0 and never blocks
# the stop. The CLI decides whether the directory is a Meridian project.
set -uo pipefail

HOOK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MERIDIAN_BIN="$HOOK_ROOT/bin/meridian"
for PLUGIN_DIRECTORY in "${PLUGIN_ROOT:-}" "${CLAUDE_PLUGIN_ROOT:-}"; do
  [ -x "$MERIDIAN_BIN" ] && break
  [ -n "$PLUGIN_DIRECTORY" ] && MERIDIAN_BIN="$PLUGIN_DIRECTORY/bin/meridian"
done
if [ ! -x "$MERIDIAN_BIN" ]; then
  MERIDIAN_BIN="$(command -v meridian 2>/dev/null || true)"
fi
[ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ] || exit 0

"$MERIDIAN_BIN" hook stop-audit >/dev/null 2>&1
exit 0
