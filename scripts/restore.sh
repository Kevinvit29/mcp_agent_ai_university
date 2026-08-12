#!/usr/bin/env bash
# DESTRUCTIVE: restore a verified archive. Test this first on a staging copy.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE="${1:-}"
COMPOSE=(docker compose -f "$ROOT_DIR/docker-compose.yml")

if [[ "$CONFIRM_RESTORE" != "YES" ]]; then
  echo "Refusing restore. Run with CONFIRM_RESTORE=YES after verifying a backup." >&2
  exit 1
fi
if [[ "${APP_ENV:-}" == "production" && "${ALLOW_PRODUCTION_RESTORE:-}" != "YES" ]]; then
  echo "Refusing direct production restore. Use staging first; set ALLOW_PRODUCTION_RESTORE=YES only during an approved incident." >&2
  exit 1
fi
if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "Usage: CONFIRM_RESTORE=YES $0 /path/to/backup.tar.gz" >&2
  exit 1
fi
if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "Missing .env configuration." >&2
  exit 1
fi
"$ROOT_DIR/scripts/verify_backup.sh" "$ARCHIVE"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
tar -xzf "$ARCHIVE" -C "$WORK_DIR"
printf 'Restoring PostgreSQL (existing database objects will be replaced)…\n'
"${COMPOSE[@]}" exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$WORK_DIR/postgres.dump"
printf 'Restoring MongoDB (existing database collections will be replaced)…\n'
"${COMPOSE[@]}" exec -T mongo sh -c 'mongorestore --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db "$MONGO_INITDB_DATABASE" --drop --archive' < "$WORK_DIR/mongo.archive"
echo "Restore completed. Run docker compose ps and /api/health/ready before reopening access."
