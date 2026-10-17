#!/bin/bash
# Meridian queue briefing — fires on UserPromptSubmit.
# Outputs a compact status only if the project's queue file exists in cwd.
# Silent exit in non-Meridian projects.

# The hook must be able to find the CLI when invoked directly, from a local
# plugin, or by any host. Its own parent directory is the authoritative bundled
# location. Host-provided plugin-root variables are equivalent fallbacks, not
# a preference for any particular AI tool.
HOOK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MERIDIAN_BIN="$HOOK_ROOT/bin/meridian"
for PLUGIN_DIRECTORY in "${PLUGIN_ROOT:-}" "${CLAUDE_PLUGIN_ROOT:-}"; do
  [ -x "$MERIDIAN_BIN" ] && break
  [ -n "$PLUGIN_DIRECTORY" ] && MERIDIAN_BIN="$PLUGIN_DIRECTORY/bin/meridian"
done
if [ ! -x "$MERIDIAN_BIN" ]; then
  MERIDIAN_BIN="$(command -v meridian 2>/dev/null || true)"
fi

# The conversation language is project-owned state. Echo it at the start of
# every Claude prompt when a Meridian project declares it, so the rule stays
# salient without duplicating its value in a host configuration. This is a
# reminder, not enforcement: repository text is validated by the project's
# own review and verification process.
emit_language_policy_briefing() {
  local policy="LANGUAGE_POLICY.md"
  [ -f "$policy" ] || return

  local values count language
  values=$(awk '
    /^\*\*Conversation language:\*\*/ {
      value = $0
      sub(/^\*\*Conversation language:\*\*[[:space:]]*/, "", value)
      gsub(/^[`[:space:]]+|[`[:space:]]+$/, "", value)
      if (value != "") print value
    }
  ' "$policy")
  count=$(printf '%s\n' "$values" | grep -c .)

  echo "[Meridian Language Policy]"
  if [ "$count" != "1" ]; then
    echo "  ⚠ Conversation language unavailable: policy is missing or ambiguous."
    echo "  📝 Repository artifacts: English only"
    return
  fi

  language="$values"
  if [ "$language" = "[Conversation language]" ]; then
    echo "  ⚠ Conversation language is not configured."
    echo "  📝 Repository artifacts: English only"
    return
  fi

  printf '  🗣 Conversation language: %s\n' "$language"
  echo "  📝 Repository artifacts: English only"
}

emit_language_policy_briefing

# governed-SDD's `execution-assets` capability defaults the queue to
# `tasks/QUEUE.md` "unless this section declares different locations for
# this project" (see templates/workflows/governed-sdd/PROJECT_WORKFLOW.md).
# A project that customizes it does so in an annotated paragraph immediately
# after that marker's END, still inside the "## Execution assets" section
# (the pattern task 014 documented from consumer project A's own adoption). Scan
# exactly that zone for a `*queue*.md`-shaped path; a project with no
# customization has nothing there and falls through to the default.
resolve_queue_path() {
  local workflow="PROJECT_WORKFLOW.md"
  local default="tasks/QUEUE.md"
  [ -f "$workflow" ] || { echo "$default"; return; }

  local zone
  zone=$(awk '
    /<!-- MERIDIAN:BEGIN capability=execution-assets /{ inblock=1; next }
    inblock && /<!-- MERIDIAN:END -->/ { inblock=0; inzone=1; next }
    inzone && /^## / { exit }
    inzone { print }
  ' "$workflow")
  [ -n "$zone" ] || { echo "$default"; return; }

  # Case-insensitive, deduplicated candidates. Excluding an archive path
  # matters: task 009 itself documents archiving terminal rows to a
  # `*QUEUE*ARCHIVE*.md`-shaped file in this same zone, which would
  # otherwise be indistinguishable from the live queue's own declaration.
  local candidates
  candidates=$(printf '%s\n' "$zone" \
    | grep -Eio '[A-Za-z0-9_./-]*queue[A-Za-z0-9_./-]*\.md' \
    | grep -Eiv 'archive' \
    | sort -u)

  # Exactly one distinct, non-archive candidate is a confident resolution.
  # Zero, or more than one (an ambiguous zone this heuristic cannot safely
  # pick between), silently keep the default rather than guess wrong — a
  # briefing computed from the wrong file is worse than no briefing.
  if [ "$(printf '%s\n' "$candidates" | grep -c .)" = "1" ]; then
    echo "$candidates"
  else
    echo "$default"
  fi
}

if [ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ]; then
  QUEUE=$("$MERIDIAN_BIN" locations --project . --field queue 2>/dev/null)
fi
QUEUE=${QUEUE:-$(resolve_queue_path)}
[ -f "$QUEUE" ] || exit 0

# Machine setup is independent of the project.  It is optional, so invoke it
# only after the required language reminder and queue briefing have printed.
emit_setup_notice() {
  [ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ] || return 0
  local setup_check codex_state root_mismatch
  setup_check=$("$MERIDIAN_BIN" setup --check 2>/dev/null)
  codex_state=$(printf '%s\n' "$setup_check" | sed -n 's/^codex-profile: //p')
  if [ "$codex_state" = "repair-and-replace-required" ]; then
    printf '[Meridian Host]\n  ⚠ Codex profile needs ownership repair and worktree-root replacement; run meridian setup --apply\n'
  else
    root_mismatch=$(printf '%s\n' "$setup_check" \
      | sed -n 's/^codex-root-mismatch: /  ⚠ Codex worktree root differs: /p')
    [ -n "$root_mismatch" ] && printf '[Meridian Host]\n%s\n' "$root_mismatch"
  fi
  return 0
}

# An archived ACCEPTED row (this task's own archiving convention) still
# satisfies a dependency and still counts toward the accepted tally; both
# queue formats below read it from here alongside the active queue's own
# rows, not as a separate uncounted total.
ARCHIVE="$(dirname "$QUEUE")/QUEUE_ARCHIVE.md"

# Governed SDD queues use explicit lifecycle states rather than checkbox rows.
# A governed queue needs lifecycle columns, not one exact framework-shaped
# header.  Established projects may intentionally omit the optional `Review`
# or task-file columns.  The parser below maps the required columns by name.
if grep -Eq '^\| Order \| ID \|.*\| Status \|.*Dependencies \|' "$QUEUE"; then
  # Print the mandatory briefing header before any optional CLI lookup.  A
  # stalled lifecycle query must never suppress the policy or queue signal.
  echo "[Meridian Governed Queue]"
  # Queue rows remain QUEUED while task worktrees are active. Lifecycle
  # registration plus the task record is the source of active/review state.
  DERIVED_STATES="[]"
  WORKTREE_STATES_SKIPPED=""
  if [ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ]; then
    # Perl's alarm is available on the macOS and Linux runners and avoids a
    # GNU-timeout dependency.  Keep this optional lookup below the mandatory
    # language and queue headings, and degrade only its derived section.
    DERIVED_STATES=$(perl -e '
      my $seconds = shift; my $child = fork(); die "fork failed" unless defined $child;
      if (!$child) { setpgrp(0, 0); exec @ARGV; die "exec failed" }
      $SIG{ALRM} = sub { kill "TERM", -$child; waitpid($child, 0); exit 124 };
      alarm $seconds; waitpid($child, 0); exit($? >> 8);
    ' 2 "$MERIDIAN_BIN" worktree states --project . --format json 2>/dev/null)
    WORKTREE_STATES_STATUS=$?
    if [ "$WORKTREE_STATES_STATUS" -ne 0 ]; then
      DERIVED_STATES="[]"
      WORKTREE_STATES_SKIPPED="  ⚠ In-progress lookup skipped (timed out or failed)."
    fi
  fi
  DERIVED_ACTIVE=$(printf '%s' "$DERIVED_STATES" | python3 -c 'import json,sys; print(", ".join(item["task_id"] for item in json.load(sys.stdin) if item.get("status") != "READY_FOR_REVIEW"))' 2>/dev/null)
  DERIVED_REVIEW=$(printf '%s' "$DERIVED_STATES" | python3 -c 'import json,sys; print(", ".join(item["task_id"] for item in json.load(sys.stdin) if item.get("status") == "READY_FOR_REVIEW"))' 2>/dev/null)
  ARCHIVE_ARG=""
  [ -f "$ARCHIVE" ] && ARCHIVE_ARG="$ARCHIVE"
  # Single awk pass: collect every row's ID/status/dependencies, then
  # resolve which QUEUED rows are actually startable (every dependency
  # ACCEPTED or, for a SPIKE, ANSWERED — task-lifecycle v2's rule) versus
  # blocked on an unmet one, so a session gets the same answer the queue's
  # own "choose the highest-priority queued task whose dependencies are all
  # accepted" instruction requires, without opening the file to compute it.
  # ANSWERED/INCONCLUSIVE rows stay outside the ACCEPTED tally (the same
  # capability's "invisible to those counts by design" rule for SPIKE rows) —
  # this only widens what counts as satisfying a *dependency*, a separate
  # question from what counts toward the accepted total.
  eval "$(awk -F'\\|' '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    # Single-quote a value for safe eval: close the quote, escape any
    # embedded single quote, reopen it. Values here are queue row IDs, never
    # attacker-controlled, but this is the only line standing between an
    # unquoted field and `eval`, so it earns the defensive treatment anyway.
    function shquote(s) { gsub(/'"'"'/, "'"'"'\\'"'"''"'"'", s); return "'"'"'" s "'"'"'" }
    /^\|/ && $0 ~ /\| Order \|/ {
      for (column = 2; column <= NF - 1; column++) {
        name = trim($column)
        if (name != "") columns[name] = column
      }
      next
    }
    /^\| [0-9]+ /{
      if (!("ID" in columns) || !("Status" in columns) || !("Dependencies" in columns)) next
      n++
      id[n]     = trim($(columns["ID"]))
      status[n] = trim($(columns["Status"]))
      deps[n]   = trim($(columns["Dependencies"]))
      by_status[id[n]] = status[n]
    }
    END {
      active = ""; review = ""
      ready_n = 0; blocked_n = 0
      ready = ""; blocked = ""
      accepted = 0
      for (i = 1; i <= n; i++) {
        s = status[i]
        if (s == "ACCEPTED") accepted++
        # Retain queue-derived states only for a legacy branch with no
        # lifecycle registration. Derived states below take precedence, so a
        # pre-migration queue edit is never double-counted.
        if (s == "IN_PROGRESS" && active == "") active = id[i]
        else if (s == "READY_FOR_REVIEW" && review == "") review = id[i]
        else if (s == "QUEUED") {
          d = trim(deps[i])
          gsub(/[][]/, "", d)
          met = 1
          if (d != "" && d != "—" && d != "-") {
            split(d, parts, ",")
            for (p in parts) {
              dep = trim(parts[p])
              dep_status = by_status[dep]
              if (dep_status != "ACCEPTED" && dep_status != "ANSWERED") met = 0
            }
          }
          if (met) {
            ready_n++
            if (ready_n <= 2) ready = ready (ready == "" ? "" : ", ") id[i]
          } else {
            blocked_n++
            if (blocked_n <= 2) blocked = blocked (blocked == "" ? "" : ", ") id[i]
          }
        }
      }
      printf "ACTIVE=%s\n", shquote(active)
      printf "REVIEW=%s\n", shquote(review)
      printf "READY=%s\n", shquote(ready)
      printf "READY_N=%d\n", ready_n
      printf "BLOCKED=%s\n", shquote(blocked)
      printf "BLOCKED_N=%d\n", blocked_n
      printf "ACCEPTED=%d\n", accepted
    }
  ' "$QUEUE" $ARCHIVE_ARG)"

  ACTIVE=${DERIVED_ACTIVE:-$ACTIVE}
  REVIEW=${DERIVED_REVIEW:-$REVIEW}

  [ -n "$WORKTREE_STATES_SKIPPED" ] && echo "$WORKTREE_STATES_SKIPPED"
  [ -n "$ACTIVE" ] && echo "  🔴 In progress: $ACTIVE" || echo "  ✅ No active task"
  # Echo the active task's diagnostic/evidence/context-expansion budget so
  # the cap stays at maximum salience every turn instead of a rule read once
  # at turn 1. A missing runner is visible: silently omitting the line would
  # turn a control-plane failure into a misleadingly normal briefing.
  if [ -n "$ACTIVE" ] && [ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ]; then
    BUDGET=$("$MERIDIAN_BIN" budget show "$ACTIVE" --project . 2>/dev/null)
    if [ -n "$BUDGET" ]; then
      echo "  ⏱  $BUDGET"
      echo "  ⛔ On exhaustion: return BLOCKED. Do not raise a cap."
    else
      echo "  ⚠ Budget state unavailable for: $ACTIVE"
    fi
  elif [ -n "$ACTIVE" ]; then
    echo "  ⚠ Meridian budget runner unavailable"
  fi
  # Echo the active task's resolved Authority (source + heading only, not the
  # excerpt body) so a session sees what it may cite without opening the ADR
  # log or a spec file directly. Same missing-runner visibility as the
  # budget echo above: a silent omission would look like a normal briefing.
  if [ -n "$ACTIVE" ] && [ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ]; then
    AUTHORITY=$("$MERIDIAN_BIN" context authority "$ACTIVE" --project . --labels-only 2>/dev/null)
    if [ -n "$AUTHORITY" ]; then
      echo "  📚 Authority:"
      while IFS= read -r LINE; do
        echo "     $LINE"
      done <<< "$AUTHORITY"
    else
      echo "  ⚠ Authority excerpt unavailable for: $ACTIVE"
    fi
  elif [ -n "$ACTIVE" ]; then
    echo "  ⚠ Meridian authority runner unavailable"
  fi
  [ -n "$REVIEW" ] && echo "  🔎 In review: $REVIEW"
  if [ "${READY_N:-0}" -gt 0 ]; then
    SUFFIX=""
    [ "$READY_N" -gt 2 ] && SUFFIX=" (+$((READY_N - 2)) more)"
    echo "  ⏳ Queued (startable): $READY$SUFFIX"
  fi
  if [ "${BLOCKED_N:-0}" -gt 0 ]; then
    SUFFIX=""
    [ "$BLOCKED_N" -gt 2 ] && SUFFIX=" (+$((BLOCKED_N - 2)) more)"
    echo "  🚧 Blocked on dependencies: $BLOCKED$SUFFIX"
  fi
  echo "  ✅ Accepted: ${ACCEPTED:-0}"
  emit_setup_notice
  exit 0
fi

# ARCHIVE was already resolved above, alongside QUEUE. Closed phases moved
# there (same directory) keep the active queue short — completed-task counts
# should still cover the whole project, so this is included whenever present.

# Only match actual queue table rows: "| `[x]` | NNN | Title | ... |".
# Anchoring on a leading "| `[x]` | NNN |" (a 3-digit task id right after
# the status cell) excludes prose bullets elsewhere in the file that happen
# to contain the same backticked status markers (e.g. "How to use this
# queue"'s "[ ]" / "[/]" / "[x]" examples).

# Resolve the active task from the registered worktree first.  Lean task
# branches intentionally retain `[ ]` in the shared queue.  The queue remains
# a title source and legacy fallback, never the authority for activity.
ACTIVE_ID=""
if [ -n "$MERIDIAN_BIN" ] && [ -x "$MERIDIAN_BIN" ]; then
  ACTIVE_ID=$("$MERIDIAN_BIN" worktree active --format json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("task_id", ""))' 2>/dev/null)
fi

# Extract active task ([/]) only as a compatibility fallback for legacy
# worktrees created before lifecycle registration. Anchored (`^`) so sed captures the ID/title
# columns right after the status cell, not a later 3-digit "| NNN |"-shaped
# match elsewhere in the row (e.g. a "Depends on" column) — sed's regex is
# greedy and, unanchored, matches the rightmost candidate instead.
ACTIVE=$(grep -m1 "^| \`\[/\]\` | [0-9]\{3\} |" "$QUEUE" | sed -E 's/^\| `\[.\]` \| [0-9]{3} \| ([^|]*)\|.*/\1/' | xargs)
if [ -n "$ACTIVE_ID" ]; then
  ACTIVE=$(grep -m1 "^| \`\[[ /x]\]\` | $ACTIVE_ID |" "$QUEUE" | sed -E 's/^\| `\[.\]` \| [0-9]{3} \| ([^|]*)\|.*/\1/' | xargs)
  [ -n "$ACTIVE" ] || ACTIVE="$ACTIVE_ID"
fi

# Extract next pending tasks ([ ])
PENDING=$(grep "^| \`\[ \]\` | [0-9]\{3\} |" "$QUEUE" | head -2 | sed -E 's/^\| `\[.\]` \| ([0-9]{3}) \| ([^|]*)\|.*/\1 - \2/' | xargs | sed 's/  */ /g')

# Count completed ([x]) rows across the active queue and, if present, the
# archive — a task moved to QUEUE_ARCHIVE.md is still a completed task for
# this project, not an uncounted one.
# `grep -c` already prints "0" and exits 1 on no match, so `|| echo 0` would
# double it up — redirect stderr only, don't fall back on exit status.
DONE_ACTIVE=$(grep -c "^| \`\[x\]\` | [0-9]\{3\} |" "$QUEUE" 2>/dev/null)
DONE_ARCHIVE=0
if [ -f "$ARCHIVE" ]; then
  DONE_ARCHIVE=$(grep -c "^| \`\[x\]\` | [0-9]\{3\} |" "$ARCHIVE" 2>/dev/null)
fi
DONE=$((DONE_ACTIVE + DONE_ARCHIVE))

echo "[Meridian Lean Delivery Queue]"
if [ -n "$ACTIVE" ]; then
  echo "  🔴 In progress: $ACTIVE"
else
  echo "  ✅ No active task"
fi
if [ -n "$PENDING" ]; then
  echo "  ⏳ Queued: $PENDING"
fi
echo "  ✅ Completed: $DONE"
emit_setup_notice
