#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
  python3 -m pytest -q
else
  python3 -m pytest "$@"
fi