#!/usr/bin/env bash
# Compatibility entry point. The authoritative release workflow lives in
# scripts/v30_control.py so checks cannot drift between two implementations.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
exec python3 scripts/v30_control.py release
