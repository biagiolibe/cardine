#!/bin/sh
# Build the fixture: a Lean Delivery project with a prepared task whose primary
# checkout holds a developer's uncommitted work, one tracked edit and one untracked file.
# Usage: setup.sh <fixture-dir> <framework-root>
set -eu

. "$(dirname "$0")/../../lib/lean-project.sh"
build_lean_project "$1" "$2"

printf '\nDraft paragraph the developer has not committed.\n' >> README.md
printf 'Scratch notes the developer has not committed.\n' > SCRATCH.txt
record_primary_files "$1" README.md SCRATCH.txt
record_base "$1"
