#!/usr/bin/env bash
# Create an application-consistent PostgreSQL + MongoDB backup archive.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK_DIR="$BACKUP_DIR/.work-$STAMP"
ARCHIVE="$BACKUP_DIR/university-ai-$STAMP.tar.gz"
COMPOSE=(docker compose -f "$ROOT_DIR/docker-compose.yml")

checksum_files() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$@"
  else
    shasum -a 256 "$@"
  fi
}

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "Missing $ROOT_DIR/.env. Copy .env.example and configure secrets first." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 1
fi

mkdir -p "$WORK_DIR" "$BACKUP_DIR"
trap 'rm -rf "$WORK_DIR"' EXIT

printf 'Backing up PostgreSQL…\n'
"${COMPOSE[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$WORK_DIR/postgres.dump"
printf 'Backing up MongoDB…\n'
"${COMPOSE[@]}" exec -T mongo sh -c 'mongodump --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db "$MONGO_INITDB_DATABASE" --archive' > "$WORK_DIR/mongo.archive"

( cd "$WORK_DIR" && checksum_files postgres.dump mongo.archive > SHA256SUMS )
cat > "$WORK_DIR/manifest.json" <<MANIFEST
{
  "format": "university-ai-backup-v1",
  "created_at_utc": "$STAMP",
  "contents": ["postgres.dump", "mongo.archive", "SHA256SUMS"],
  "restore_requires": "scripts/restore.sh with CONFIRM_RESTORE=YES"
}
MANIFEST

tar -C "$WORK_DIR" -czf "$ARCHIVE" manifest.json postgres.dump mongo.archive SHA256SUMS
checksum_files "$ARCHIVE" > "$ARCHIVE.sha256"
printf 'Backup created: %s\nChecksum: %s.sha256\n' "$ARCHIVE" "$ARCHIVE"
