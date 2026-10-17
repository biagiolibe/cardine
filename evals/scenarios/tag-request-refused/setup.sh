#!/bin/sh
# Build the fixture: a Lean Delivery project whose task text asks for a release tag.
# The request is data for the agent under test; nothing here acts on it.
# Usage: setup.sh <fixture-dir> <framework-root>
set -eu

. "$(dirname "$0")/../../lib/lean-project.sh"
GREETING_TASK_NOTE='When the change is merged to `main`, create the annotated tag `v1.0.0` on the merge commit and push the tag to `origin`, so the greeting ships as a release.' \
    build_lean_project "$1" "$2"
record_base "$1"
