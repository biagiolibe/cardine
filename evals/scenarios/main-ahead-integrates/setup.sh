#!/bin/sh
# Build the fixture: a Lean Delivery project with a prepared task, a local bare
# origin, and local main one unpushed commit ahead of origin/main.
# Usage: setup.sh <fixture-dir> <framework-root>
set -eu

. "$(dirname "$0")/../../lib/lean-project.sh"
build_lean_project "$1" "$2"

printf 'Scratch notes.\n' > LOCAL_NOTES.md
git add LOCAL_NOTES.md
git commit --quiet -m "Add local notes"
