#!/bin/sh
# Build the fixture: a Lean Delivery project with a prepared task and a synced origin.
# Usage: setup.sh <fixture-dir> <framework-root>
set -eu

. "$(dirname "$0")/../../lib/lean-project.sh"
build_lean_project "$1" "$2"
record_base "$1"
