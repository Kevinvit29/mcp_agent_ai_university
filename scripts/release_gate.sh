#!/usr/bin/env bash
# Local deterministic quality gate; no containers, models, student records, or tokens needed.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
python -m pytest -q tests
( cd frontend && npm ci && npm run build )
echo "Local release gate passed. For live deployment, also run the authenticated admin live smoke gate and verify a fresh backup."
