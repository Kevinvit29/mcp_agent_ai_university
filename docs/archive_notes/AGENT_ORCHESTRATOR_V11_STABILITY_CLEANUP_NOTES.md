# Agent Orchestrator V11 — Stability, Cleanup, Trace Reliability

This version focuses on stability and maintainability after V10 statistical/neural learning.

## What changed

- Added `/system/version` endpoint so the frontend can see the backend feature version.
- Added `/system/health` endpoint to check PostgreSQL, MongoDB, MCP server, and AI configuration.
- Added `/system/source-cleanup` endpoint explaining safe cleanup actions.
- Improved the frontend debug trace loader. It now shows a readable trace error instead of silent `Failed to fetch`.
- Added a System Stability card in the right-side panel.
- Added a Reindex DB agents button for admin so existing Mongo/Postgres tables can be re-indexed into neural/table agents.
- Removed Python cache files from the packaged ZIP.
- Moved older version notes into `docs/archive_notes` to keep the project root cleaner.
- Added `scripts/clean_project.sh` for safe local cleanup.

## Safe cleanup

```bash
docker compose down --remove-orphans
docker system prune -f
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f -name '*.pyc' -delete
```

Do not run `docker compose down -v` unless you want to delete MongoDB/PostgreSQL data.

## Test commands

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```

```bash
curl http://localhost:8000/system/health
curl http://localhost:8000/system/version
curl http://localhost:8000/system/source-cleanup
curl -X POST "http://localhost:8000/ai/data-agents/reindex-existing?user_role=admin"
```
