#!/usr/bin/env sh
# 32matrix launcher for Linux / macOS.
# Keeps your current working directory so relative -o paths land where you expect.
#   chmod +x 32matrix.sh
#   ./32matrix.sh doctor
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

if command -v python3 >/dev/null 2>&1; then
    exec python3 -m 32matrix "$@"
elif command -v python >/dev/null 2>&1; then
    exec python -m 32matrix "$@"
else
    echo "32matrix: python3 not found on PATH" >&2
    exit 127
fi
