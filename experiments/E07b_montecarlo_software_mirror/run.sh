#!/usr/bin/env bash
# The exact command that produces raw/ and processed/. No hidden flags.
set -euo pipefail
cd "$(dirname "$0")"
python3 run_montecarlo.py
