#!/usr/bin/env bash
# Safe generated-cache cleanup only. This script never stops containers,
# removes Docker resources, touches database volumes, or deletes dependencies.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

find backend mcp_server scripts tests -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find backend mcp_server scripts tests -depth -type d -name '__pycache__' -empty -delete
find . -maxdepth 3 -type f -name '.DS_Store' -delete

printf 'Generated Python/macOS cache files removed. Services and data were not changed.\n'
