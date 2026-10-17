#!/usr/bin/env bash
# Upgrade one Meridian-managed project to the installed framework release.
#
# Default is a dry run: preflight plus every read-only check. With --apply it
# creates a dedicated branch, runs upgrade/setup/queue alignment, validates,
# and commits on that branch. It never merges, pushes, tags, or deletes.
#
# Usage:
#   upgrade_project.sh <project> [--apply] [--validate "<command>"]...
#                      [--meridian-root <path>] [--branch <name>]
#                      [--skip-setup] [--skip-queue] [--allow-untagged]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT=""
APPLY=0
SKIP_SETUP=0
SKIP_QUEUE=0
ALLOW_UNTAGGED=0
BRANCH=""
MERIDIAN_ROOT="${MERIDIAN_ROOT:-}"
VALIDATE=()

ON_BRANCH=0
die() {
  printf 'STOP: %s\n' "$*" >&2
  if [ "$ON_BRANCH" = "1" ]; then
    cat >&2 <<EOF_RECOVERY

The working tree was clean before this run, so every change on $BRANCH
came from it. Inspect with:
    git -C "$PROJECT" status --short
To discard the attempt and return to main:
    git -C "$PROJECT" reset --hard
    git -C "$PROJECT" clean -fd
    git -C "$PROJECT" switch main
    git -C "$PROJECT" branch -D $BRANCH
EOF_RECOVERY
  fi
  exit 2
}
step() { printf '\n==> %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --skip-setup) SKIP_SETUP=1 ;;
    --skip-queue) SKIP_QUEUE=1 ;;
    --allow-untagged) ALLOW_UNTAGGED=1 ;;
    --validate) shift; [ $# -gt 0 ] || die "--validate needs a command"; VALIDATE+=("$1") ;;
    --meridian-root) shift; MERIDIAN_ROOT="${1:-}" ;;
    --branch) shift; BRANCH="${1:-}" ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [ -z "$PROJECT" ] || die "only one project per run"; PROJECT="$1" ;;
  esac
  shift
done

[ -n "$PROJECT" ] || die "missing project path (see --help)"
PROJECT="$(cd "$PROJECT" && pwd)" || die "project path not found"

# --- Framework -------------------------------------------------------------
if [ -z "$MERIDIAN_ROOT" ]; then
  if command -v meridian >/dev/null 2>&1; then
    MERIDIAN_ROOT="$(cd "$(dirname "$(command -v meridian)")/.." && pwd)"
  else
    die "set MERIDIAN_ROOT or pass --meridian-root"
  fi
fi
M="$MERIDIAN_ROOT/bin/meridian"
[ -x "$M" ] || die "no executable $M"
TARGET="$(tr -d '[:space:]' < "$MERIDIAN_ROOT/VERSION")"
BRANCH="${BRANCH:-meridian-upgrade-$TARGET}"

manifest_field() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' \
    "$PROJECT/.meridian/manifest.json" "$1"
}

step "Framework"
info "root:    $MERIDIAN_ROOT"
info "version: $TARGET"
if git -C "$MERIDIAN_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  FRAMEWORK_HEAD="$(git -C "$MERIDIAN_ROOT" rev-parse HEAD)"
  TAG_COMMIT="$(git -C "$MERIDIAN_ROOT" rev-parse -q --verify "refs/tags/v$TARGET^{commit}" || true)"
  [ -n "$TAG_COMMIT" ] || die "framework checkout has no tag v$TARGET; upgrading from unreleased main is not supported"
  if [ "$FRAMEWORK_HEAD" != "$TAG_COMMIT" ]; then
    if [ "$ALLOW_UNTAGGED" = "1" ]; then
      info "warning: framework HEAD is not v$TARGET (--allow-untagged)"
    else
      die "framework HEAD is not tag v$TARGET; check out the tag or pass --allow-untagged"
    fi
  fi
  [ -z "$(git -C "$MERIDIAN_ROOT" status --porcelain)" ] || info "warning: framework checkout has local changes"
fi
set +e
"$M" self-check --check-latest
SELF=$?
set -e
case "$SELF" in
  0) info "framework is the latest release" ;;
  10) die "a newer Meridian release exists; update the framework first (see the final steps)" ;;
  *) info "latest-release check inconclusive (exit $SELF); continuing with $TARGET" ;;
esac

# --- Project preflight -----------------------------------------------------
step "Project preflight: $PROJECT"
[ -f "$PROJECT/.meridian/manifest.json" ] || die "no .meridian/manifest.json; use 'meridian adopt' instead"
git -C "$PROJECT" rev-parse --git-dir >/dev/null 2>&1 || die "not a Git repository"

PRIMARY="$(git -C "$PROJECT" worktree list --porcelain | awk '/^worktree /{print substr($0,10); exit}')"
[ "$(cd "$PRIMARY" && pwd -P)" = "$(cd "$PROJECT" && pwd -P)" ] || die "run on the primary checkout: $PRIMARY"

CURRENT_BRANCH="$(git -C "$PROJECT" branch --show-current)"
[ "$CURRENT_BRANCH" = "main" ] || die "primary checkout must be on main (found '$CURRENT_BRANCH')"
[ -z "$(git -C "$PROJECT" status --porcelain)" ] || die "working tree is not clean; commit or stash first"

if git -C "$PROJECT" remote get-url origin >/dev/null 2>&1; then
  git -C "$PROJECT" fetch -q origin
  BEHIND="$(git -C "$PROJECT" rev-list --count main..origin/main 2>/dev/null || echo 0)"
  [ "$BEHIND" = "0" ] || die "main is $BEHIND commit(s) behind origin/main; pull first"
fi
git -C "$PROJECT" show-ref --verify --quiet "refs/heads/$BRANCH" && die "branch $BRANCH already exists"

INSTALLED="$(manifest_field frameworkVersion)"
MODE="$(manifest_field workflowMode)"
info "mode:              ${MODE:-unknown}"
info "frameworkVersion:  $INSTALLED -> $TARGET"
OTHER_WORKTREES="$(git -C "$PROJECT" worktree list --porcelain | grep -c '^worktree ' || true)"
if [ "$OTHER_WORKTREES" -gt 1 ]; then
  info "note: $((OTHER_WORKTREES - 1)) linked task worktree(s) exist; they keep the old"
  info "      baseline until their tasks integrate. Prefer upgrading with no open tasks."
fi

# --- Read-only plans -------------------------------------------------------
step "meridian upgrade --check"
set +e
"$M" upgrade --project "$PROJECT" --check
PLAN=$?
set -e
[ "$PLAN" = "0" ] || die "upgrade plan is blocked (exit $PLAN); resolve the listed conflicts first"

if [ "$SKIP_SETUP" = "0" ]; then
  step "meridian setup --check"
  "$M" setup --project "$PROJECT" --check || die "setup --check failed"
fi

ALIGN="$SCRIPT_DIR/align_queue.py"
if [ "$SKIP_QUEUE" = "0" ]; then
  step "Queue usage text (preview)"
  if [ -f "$ALIGN" ]; then
    python3 "$ALIGN" --meridian "$M" "$PROJECT" || info "queue alignment skipped (see notes above)"
  else
    info "align_queue.py not found next to this script; skipping"
    SKIP_QUEUE=1
  fi
fi

if [ "$APPLY" = "0" ]; then
  step "Dry run complete"
  info "Nothing was changed. Rerun with --apply to perform the upgrade on branch $BRANCH."
  exit 0
fi

# --- Apply on a dedicated branch -------------------------------------------
step "Create branch $BRANCH"
git -C "$PROJECT" switch -q -c "$BRANCH"
ON_BRANCH=1
info "on $BRANCH"

step "meridian upgrade --apply"
"$M" upgrade --project "$PROJECT" --apply

if [ "$SKIP_SETUP" = "0" ]; then
  step "meridian setup --apply"
  "$M" setup --project "$PROJECT" --apply
fi

if [ "$SKIP_QUEUE" = "0" ]; then
  step "Align queue usage text"
  python3 "$ALIGN" --meridian "$M" "$PROJECT" --apply || info "queue alignment left unchanged parts (see notes above)"
fi

# --- Validate ---------------------------------------------------------------
step "meridian audit"
# audit exits non-zero for UNVERIFIED or ADVISORY rows too (for example a
# legacy manifest without capabilityProfiles); only FAIL rows stop here.
set +e
AUDIT_OUT="$("$M" audit --project "$PROJECT" 2>&1)"
set -e
printf '%s\n' "$AUDIT_OUT"
AUDIT_FAILS="$(printf '%s\n' "$AUDIT_OUT" | sed -n 's/^SUMMARY .* FAIL=\([0-9][0-9]*\).*/\1/p')"
[ -n "$AUDIT_FAILS" ] || die "audit printed no SUMMARY line; nothing committed, still on $BRANCH"
[ "$AUDIT_FAILS" = "0" ] || die "audit reports FAIL=$AUDIT_FAILS; nothing committed, still on $BRANCH"

NEW_VERSION="$(manifest_field frameworkVersion)"
[ "$NEW_VERSION" = "$TARGET" ] || die "manifest frameworkVersion is '$NEW_VERSION', expected '$TARGET'"
info "manifest frameworkVersion: $NEW_VERSION"

for cmd in ${VALIDATE[@]+"${VALIDATE[@]}"}; do
  step "Project validation: $cmd"
  (cd "$PROJECT" && bash -c "$cmd") || die "validation failed: $cmd (nothing committed, still on $BRANCH)"
done

# --- Commit -----------------------------------------------------------------
step "Commit on $BRANCH"
git -C "$PROJECT" add -A
# Never commit host-local settings.
for local_file in .claude/settings.local.json; do
  if git -C "$PROJECT" diff --cached --quiet -- "$local_file" 2>/dev/null; then :; else
    git -C "$PROJECT" reset -q -- "$local_file"
    info "left $local_file uncommitted (host-local)"
  fi
done
if git -C "$PROJECT" diff --cached --quiet; then
  info "no changes to commit"
else
  git -C "$PROJECT" diff --cached --stat
  git -C "$PROJECT" commit -q -m "Upgrade Meridian to $TARGET"
  info "committed $(git -C "$PROJECT" rev-parse --short HEAD)"
fi

# --- Remaining manual steps -------------------------------------------------
cat <<EOF

==> Done on branch $BRANCH. Remaining steps, outside this script:

  1. Review the upgrade:
       git -C "$PROJECT" show --stat HEAD
       git -C "$PROJECT" diff main..$BRANCH

  2. Integrate into main and publish:
       git -C "$PROJECT" switch main
       git -C "$PROJECT" merge --ff-only $BRANCH
       git -C "$PROJECT" push origin main
       git -C "$PROJECT" branch -d $BRANCH

  3. If anything is wrong instead, discard the branch:
       git -C "$PROJECT" switch main
       git -C "$PROJECT" branch -D $BRANCH

  4. Restart open Claude Code or Codex sessions in this project so they
     reload the updated workflow text and settings.

  Framework updates (before the next project upgrade, not per project):
       Claude Code:  /plugin marketplace update meridian
       Codex:        git -C "\$MERIDIAN_ROOT" fetch --tags && git -C "\$MERIDIAN_ROOT" checkout v<version>
EOF
