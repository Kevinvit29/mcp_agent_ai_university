#!/usr/bin/env bash
# Validate archive structure and checksums without touching live databases.
set -euo pipefail

ARCHIVE="${1:-}"
if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "Usage: $0 /path/to/university-ai-YYYYMMDDTHHMMSSZ.tar.gz" >&2
  exit 1
fi
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

tar -xzf "$ARCHIVE" -C "$WORK_DIR"
for required in manifest.json postgres.dump mongo.archive SHA256SUMS; do
  [[ -f "$WORK_DIR/$required" ]] || { echo "Backup missing $required" >&2; exit 1; }
done
if command -v sha256sum >/dev/null 2>&1; then
  ( cd "$WORK_DIR" && sha256sum -c SHA256SUMS )
else
  ( cd "$WORK_DIR" && shasum -a 256 -c SHA256SUMS )
fi
PYTHON_BIN="$(command -v python3 || command -v python)"
"$PYTHON_BIN" - "$WORK_DIR/manifest.json" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding='utf-8'))
assert manifest.get('format') == 'university-ai-backup-v1', 'Unexpected backup format'
print('Manifest format:', manifest['format'])
PY
echo "Backup verification passed: $ARCHIVE"
