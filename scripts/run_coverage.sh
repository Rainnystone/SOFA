#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m coverage run --source=scripts -m unittest tests/test_frontier_lifecycle.py
python3 -m coverage report --include="scripts/frontier_lifecycle.py" --fail-under=90
