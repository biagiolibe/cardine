#!/bin/bash
# Meridian read-guard — PreToolUse hook for the Read tool.
#
# docs/PROPOSAL_CONTEXT_ENFORCEMENT.md (M2, D1) found that
# CONTEXT_BUDGET_POLICY.md's prose rule ("read only the minimum files
# needed") was violated even when the need was never ambiguous: a whole-file
# Read of a large source file and of the ADR log both happened anyway.
# Mechanical enforcement -- the same lever that held for the queue read
# (queue-briefing.sh) -- is generalized here to the Read tool itself.
#
# No -e: any parsing/resolution failure must fall through to allow, never
# block on an internal error (an advisory-safe default the task requires).
set -uo pipefail

# The hook must be able to find the CLI when invoked directly, from a local
# plugin, or by any host, exactly like queue-briefing.sh.
HOOK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MERIDIAN_BIN="$HOOK_ROOT/bin/meridian"
for PLUGIN_DIRECTORY in "${PLUGIN_ROOT:-}" "${CLAUDE_PLUGIN_ROOT:-}"; do
  [ -x "$MERIDIAN_BIN" ] && break
  [ -n "$PLUGIN_DIRECTORY" ] && MERIDIAN_BIN="$PLUGIN_DIRECTORY/bin/meridian"
done
if [ ! -x "$MERIDIAN_BIN" ]; then
  MERIDIAN_BIN="$(command -v meridian 2>/dev/null || true)"
fi

INPUT="$(cat)"

# Pull tool_name/file_path/offset-or-limit/cwd out of the PreToolUse JSON
# payload with a single python3 call (already a hard project dependency;
# see CLAUDE.md's own commands) rather than a fragile shell/JSON regex.
# Any parse failure prints four empty fields, which the checks below treat
# as "unknown" and therefore allow.
FIELDS=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("\t\t\t")
    raise SystemExit
tool_input = data.get("tool_input") or {}
tool_name = data.get("tool_name") or ""
file_path = tool_input.get("file_path") or ""
has_range = "1" if (tool_input.get("offset") or tool_input.get("limit")) else "0"
cwd = data.get("cwd") or ""
print("\t".join([tool_name, file_path, has_range, cwd]).replace("\n", " "))
' 2>/dev/null)
IFS=$'\t' read -r TOOL_NAME FILE_PATH HAS_RANGE PAYLOAD_CWD <<< "$FIELDS"

# hooks.json's matcher already restricts invocation to the Read tool; this
# is only a defensive check against an unexpected payload shape.
[ -z "${TOOL_NAME:-}" ] || [ "$TOOL_NAME" = "Read" ] || exit 0
[ -n "${FILE_PATH:-}" ] || exit 0

CWD="${PAYLOAD_CWD:-$PWD}"
[ -f "$CWD/PROJECT_WORKFLOW.md" ] || exit 0
[ -f "$FILE_PATH" ] || exit 0

LINE_COUNT=$(wc -l < "$FILE_PATH" 2>/dev/null | tr -d ' ')
[ -n "${LINE_COUNT:-}" ] || exit 0
case "$LINE_COUNT" in ''|*[!0-9]*) exit 0 ;; esac

THRESHOLD=400
PROFILE="$CWD/docs/EXECUTION_EVIDENCE_PROFILE.md"
if [ -f "$PROFILE" ]; then
  CONFIGURED=$(grep -Eo '`Read-guard threshold`:[[:space:]]*[0-9]+' "$PROFILE" 2>/dev/null | grep -Eo '[0-9]+' | head -1)
  [ -n "${CONFIGURED:-}" ] && THRESHOLD="$CONFIGURED"
fi

[ "$LINE_COUNT" -gt "$THRESHOLD" ] || exit 0
[ "$HAS_RANGE" = "1" ] && exit 0

RELATIVE_PATH="$FILE_PATH"
case "$FILE_PATH" in
  "$CWD"/*) RELATIVE_PATH="${FILE_PATH#"$CWD"/}" ;;
esac

# ---- exemptions, checked before the threshold produces a denial ----

# LANGUAGE_POLICY.md is a fixed exemption, not project-declared: every
# Meridian project needs it readable regardless of size.
if [ "$RELATIVE_PATH" = "LANGUAGE_POLICY.md" ]; then
  exit 0
fi

is_exempt_path() {
  local candidate="$1"
  [ -z "$candidate" ] && return 1
  [ "$RELATIVE_PATH" = "$candidate" ] && return 0
  [ "$FILE_PATH" = "$candidate" ] && return 0
  [ "$CWD/$candidate" = "$FILE_PATH" ] && return 0
  return 1
}

# The lifecycle registration is the source of truth for an active task.  A
# task branch intentionally leaves the shared queue row untouched.
if [ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ]; then
  ACTIVE_EXEMPT=$(
    "$MERIDIAN_BIN" worktree active --format json 2>/dev/null | python3 -c '
import json, sys
try:
    print("\n".join(json.load(sys.stdin).get("exempt_paths", [])))
except Exception:
    pass
' 2>/dev/null
  )
  while IFS= read -r SOURCE; do
    if is_exempt_path "$SOURCE"; then
      exit 0
    fi
  done <<< "$ACTIVE_EXEMPT"

  # `context size` owns this list, so the hook does not carry a second
  # hard-coded router declaration.  Router files remain bounded by their
  # independently configured line ceiling.
  ROUTER_DECISION=$("$MERIDIAN_BIN" context size --role implementation --format json --project "$CWD" 2>/dev/null | python3 -c '
import json, sys
try:
    report = json.load(sys.stdin)
    path = sys.argv[1]
    for record in report.get("router_files", []):
        if record.get("path") == path:
            print("deny:%s:%s:%s" % (path, record.get("lines"), report.get("router_file_lines_ceiling")) if record.get("over_router_ceiling") else "allow")
            break
except Exception:
    pass
' "$RELATIVE_PATH" 2>/dev/null)
  if [[ "$ROUTER_DECISION" == deny:* ]]; then
    IFS=: read -r _ ROUTER_PATH ROUTER_LINES ROUTER_CEILING <<< "$ROUTER_DECISION"
    MESSAGE="Blocked: router file $ROUTER_PATH ($ROUTER_LINES lines) exceeds its declared ceiling ($ROUTER_CEILING lines). Shrink the file; do not read it in ranges."
    printf '%s\n' "$MESSAGE" >&2
    printf '{"hookSpecificOutput": {"permissionDecision": "deny"}, "systemMessage": "%s"}\n' "$MESSAGE"
    exit 2
  elif [ "$ROUTER_DECISION" = "allow" ]; then
    exit 0
  fi
fi

# The active task's own file, and every source task 034's `context
# authority` resolved from its `Authority` bullets -- a worker must never be
# blocked from reading the file its own task assigns.
if [ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ]; then
  QUEUE=$("$MERIDIAN_BIN" locations --project "$CWD" --field queue 2>/dev/null)
  [ -n "$QUEUE" ] || QUEUE="tasks/QUEUE.md"
  QUEUE_PATH="$CWD/$QUEUE"
  if [ -f "$QUEUE_PATH" ]; then
    ACTIVE=""
    if grep -Eq '^\| Order \| ID \|.*\| Status \|.*Dependencies \|' "$QUEUE_PATH" 2>/dev/null; then
      ACTIVE=$(awk -F'|' '
        /^\|/ && $0 ~ /\| Order \|/ {
          for (c = 2; c <= NF - 1; c++) { n = $c; gsub(/^[ \t]+|[ \t]+$/, "", n); if (n != "") col[n] = c }
          next
        }
        /^\| [0-9]+ /{
          if (!("ID" in col) || !("Status" in col)) next
          id = $(col["ID"]); status = $(col["Status"])
          gsub(/^[ \t]+|[ \t]+$/, "", id); gsub(/^[ \t]+|[ \t]+$/, "", status)
          if (status == "IN_PROGRESS") { print id; exit }
        }
      ' "$QUEUE_PATH" 2>/dev/null)
    else
      ACTIVE=$(grep -m1 '^| `\[/\]` | [0-9]\{3\} |' "$QUEUE_PATH" 2>/dev/null | sed -E 's/^\| `\[.\]` \| ([0-9]{3}) \|.*/\1/')
    fi
    if [ -n "$ACTIVE" ]; then
      # Every source 034's `context authority` resolved to an excerpt, plus
      # every backticked path in its Unresolved section -- a bullet that
      # names a whole file (no ADR ID, no `path`#Heading) is unresolved by
      # 034's own design (dumping it would defeat this task's purpose), but
      # it still names the exact file the task assigns and must stay
      # readable here.
      AUTHORITY_OUTPUT=$("$MERIDIAN_BIN" context authority "$ACTIVE" --project "$CWD" --labels-only 2>/dev/null)
      AUTHORITY_SOURCES=$(
        printf '%s\n' "$AUTHORITY_OUTPUT" | sed -n 's/^### \(.*\) — .*/\1/p'
        printf '%s\n' "$AUTHORITY_OUTPUT" | grep -Eo '`[^`]+`' | tr -d '`'
      )
      while IFS= read -r SOURCE; do
        if is_exempt_path "$SOURCE"; then
          exit 0
        fi
      done <<< "$AUTHORITY_SOURCES"
      TASK_ROOTS=$("$MERIDIAN_BIN" locations --project "$CWD" --field task-roots 2>/dev/null)
      while IFS= read -r ROOT_DIR; do
        [ -n "$ROOT_DIR" ] || continue
        TASK_FILE=$(find "$CWD/$ROOT_DIR" -name "${ACTIVE}.md" 2>/dev/null | head -1)
        if [ -n "$TASK_FILE" ] && [ "$FILE_PATH" = "$TASK_FILE" ]; then
          exit 0
        fi
      done <<< "$TASK_ROOTS"
    fi
  fi
fi

# A project's entry router may declare files that are always loaded, in a
# line containing "always" alongside their backticked paths -- e.g. "AGENTS.md
# and CLAUDE.md are always loaded." Project-declared, not a hardcoded path
# list, so other projects do not inherit consumer project A exemptions.
ROUTER="$CWD/docs/workflows/ENTRY_ROUTER.md"
if [ -f "$ROUTER" ]; then
  ALWAYS_LOADED=$(grep -i 'always' "$ROUTER" 2>/dev/null | grep -Eo '`[^`]+`' | tr -d '`')
  while IFS= read -r DECLARED; do
    if is_exempt_path "$DECLARED"; then
      exit 0
    fi
  done <<< "$ALWAYS_LOADED"
fi

# ---- deny ----

MESSAGE="Blocked: Read of $RELATIVE_PATH ($LINE_COUNT lines) exceeds the read-guard threshold ($THRESHOLD lines) with no offset/limit. Use \`grep -n\` to find the needed lines, then a ranged Read; for the ADR log or a spec file, use \`meridian context authority <TASK-ID>\` or \`meridian adr show <ADR-ID>\` (task 034) instead. If this file genuinely must be read in full, declare it in the task's Authority/exemptions, or raise \`Read-guard threshold\` in docs/EXECUTION_EVIDENCE_PROFILE.md -- do not repeat the unranged Read."

printf '%s\n' "$MESSAGE" >&2
SYSTEM_MESSAGE_JSON=$(printf '%s' "$MESSAGE" | python3 -c 'import json, sys; print(json.dumps(sys.stdin.read().rstrip("\n")))' 2>/dev/null)
if [ -n "$SYSTEM_MESSAGE_JSON" ]; then
  printf '{"hookSpecificOutput": {"permissionDecision": "deny"}, "systemMessage": %s}\n' "$SYSTEM_MESSAGE_JSON"
fi
exit 2
