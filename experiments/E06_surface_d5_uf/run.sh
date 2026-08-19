#!/usr/bin/env bash
# The exact command that produces raw/. No hidden flags, no interactive prompts.
# Must fail loudly rather than fall back to a software path.
set -euo pipefail
cd "$(dirname "$0")"
echo "NOT IMPLEMENTED: see NOTES.md preconditions" >&2
exit 1
