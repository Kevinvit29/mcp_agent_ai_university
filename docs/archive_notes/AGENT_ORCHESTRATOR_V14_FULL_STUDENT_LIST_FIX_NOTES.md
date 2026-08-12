# Agent Orchestrator V14 — Full Student List Fix

## Problem
When the user asked `list all students` or asked in Thai to arrange/list student names, the chat only showed about 20 students.

This was not a database problem. MongoDB could contain 100 students, but the backend chat response was intentionally capped at 20 rows by `MAX_CHAT_ROWS` and the planner used a default `limit=20` for broad list requests.

## Files changed

- `backend/app/agent/tool_planner.py`
- `backend/app/agent/contextual_tool_planner.py`
- `backend/app/agent/final_answer_writer.py`
- `backend/app/main.py`

## What changed

### 1. Directory requests now use `list_names`
For questions like:

- `list all students`
- `show all students`
- `จัดเรียงรายชื่อนักศึกษาให้ดูง่ายๆหน่อย`

The planner now uses:

```json
{
  "operation": "list_names",
  "limit": 5000,
  "answer_style": "names",
  "allow_full_chat_list": true
}
```

### 2. Chat no longer wraps small directory lists into a 20-row preview
`backend/app/main.py` now skips the large-result preview wrapper for `list_names` when the total is reasonable, currently up to 300 rows.

### 3. Final answer now states the total
Instead of silently showing only the first 20, the answer says:

```text
Students (100 total):
- S001: ...
...
```

### 4. Safety remains for very large data
If the directory grows beyond 300 names, the final answer will still truncate safely and say how many are shown.

## Run

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```

Then hard-refresh Chrome:

```text
Cmd + Shift + R
```

## Test

```text
list all students
show all students
จัดเรียงรายชื่อนักศึกษาให้ดูง่ายๆหน่อย
```
