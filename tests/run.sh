#!/usr/bin/env sh
# Run the full test suite under the stdlib `trace` module and fail if line
# coverage across `scripts/` drops below 90%.
#
# Uses only tools the deploy sandbox provides: the Python 3.10+ standard
# library (including `trace`, `unittest`, `tokenize`) and `pytest`.
# No `pip install`, no virtualenv required at runtime.
#
# Prefers `.venv/bin/python3` when present (local dev workflow after
# `make setup`). Falls back to system `python3` otherwise (sandbox).
#
# Invoke from the repo root:
#     ./tests/run.sh
# or via make:
#     make test

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

cd "$REPO_ROOT"

if [ -x "$REPO_ROOT/.venv/bin/python3" ]; then
    PY="$REPO_ROOT/.venv/bin/python3"
else
    PY=python3
fi

exec "$PY" tests/coverage_runner.py
