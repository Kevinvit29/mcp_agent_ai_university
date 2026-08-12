# V25 — Live Database Smoke Test Gate

V25 adds a **read-only live service check** for the real Docker deployment. It is
not a model evaluation and it does not train or alter the data.

## What it verifies

1. MongoDB is reachable and `university_mongo.students` contains the canonical
   student master records.
2. PostgreSQL has the core chat, document, relationship, and data-agent tables.
3. The source-of-truth boundary remains correct: `student_subjects` can support
   permissions, but never becomes the total university population.
4. The MCP gateway is healthy and can execute a safe student **count** request.

The report returns only table names, connection status, and aggregate counts. It
never returns student names, IDs, grades, contact details, or document text.

## Admin UI

Open **System → Live database smoke test → Run live smoke test**.

## API

```bash
curl "http://localhost:8000/admin/live-smoke-gate/latest?user_role=admin"
curl -X POST "http://localhost:8000/admin/live-smoke-gate/run?user_role=admin"
```

## Important behavior

- No Gemini or OpenAI request is made.
- No database write is made.
- A failure is a useful deployment signal. Fix the named service/source rather
  than bypassing the check.
