#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ -f ".venv/bin/python" ]; then
    .venv/bin/python run_dashboard.py "$@"
else
    python3 run_dashboard.py "$@"
fi

