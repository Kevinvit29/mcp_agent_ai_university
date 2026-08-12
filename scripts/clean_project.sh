#!/usr/bin/env bash
set -euo pipefail

printf "Stopping old containers for this compose project...\n"
docker compose down --remove-orphans || true

printf "Removing Python cache files...\n"
find . -type d -name __pycache__ -prune -exec rm -rf {} + || true
find . -type f -name '*.pyc' -delete || true
find . -type f -name '.DS_Store' -delete || true

printf "Optional Docker cleanup: removing unused images/containers/networks, not volumes...\n"
docker system prune -f || true

printf "Done. Database volumes were NOT deleted.\n"
printf "To rebuild: docker compose build --no-cache && docker compose up\n"
