# Agent Orchestrator V12 — Failed Fetch / Response Size Fix

This version fixes the repeated frontend `Error: Failed to fetch` issue that appeared after long database answers and debug traces.

## Root cause

The chat endpoint returned too much data:

- full MCP results
- full chat history
- full debug trace metadata inside every previous assistant message
- large student/PDF/Excel previews

After several turns, `/chat` responses could become large and unstable in the browser. When the browser connection was interrupted, the UI only showed `Failed to fetch`.

## Fixes

- Added a safe `/chat` wrapper so backend exceptions return JSON instead of breaking the fetch.
- Reduced `/chat` response payload size.
- Chat history returned to frontend now contains only role, content, created_at, and tiny metadata.
- Full debug traces are still saved in PostgreSQL and loaded separately from `/chat/debug/last`.
- `mcp_result` returned by `/chat` is now a compact summary instead of the full raw payload.
- Added typo normalization for business-related queries: `bisness`, `buisness`, `bussiness`, `busines`, `bisnes` → `business`.
- Improved follow-up study queries like `how many of them study law` by treating `them / those / of them` as student-context terms.

## Important files changed

- `backend/app/main.py`
- `backend/app/agent/natural_query.py`
- `backend/app/agent/aggregate_query.py`

## Run clean

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```

Then hard refresh Chrome:

```text
Cmd + Shift + R
```

## Test questions

```text
how many student study business
how many student study bisness
which students study law
how many of them that study law
what is student median grade in law program
```

## If Failed to fetch still appears

Run:

```bash
docker compose logs backend --tail=150
docker compose logs frontend --tail=80
curl http://localhost:8000/system/health
```

The fixed backend should return a JSON error trace instead of causing the browser to show only `Failed to fetch`.
