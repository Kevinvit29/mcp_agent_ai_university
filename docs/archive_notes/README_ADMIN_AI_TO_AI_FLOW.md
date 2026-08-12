# Admin AI-to-AI Database Flow

This version makes the **Admin role first** and turns the chat into a clearer two-AI pipeline.

## Goal

Admin should feel like a normal ChatGPT chat, but with full university database access when the admin asks for university data.

That means:

- Admin can ask normal questions such as writing, coding, grammar, math, lesson planning, translation, and explanations.
- Admin can ask database questions such as all students, S001 full profile, grade summaries, advisor list, programs, uploaded PDFs, and database structure.
- The system decides when it needs the database and when it should just answer normally.

## Architecture

```text
Admin user
  ↓
AI 1: Admin-facing AI / intent agent
  - Understands the user's natural message
  - Handles typo-style requests
  - Decides: normal ChatGPT task or university data task
  ↓
AI 2: Database AI planner
  - Reads the meaning from AI 1
  - Chooses the safest database/tool plan
  - Rearranges the request into MCP arguments
  - Does not silently edit/delete/rewrite records
  ↓
MCP Server + PDPA Policy
  - Checks role permission
  - Calls MongoDB/PostgreSQL/PDF tools
  - Returns only allowed data
  ↓
Final answer AI
  - Explains the returned data naturally
  - Does not show raw JSON/tool names to users
```

## Admin access

Admin can access:

- MongoDB students collection: all student records and all fields
- MongoDB advisors collection: all advisor records
- PostgreSQL programs table
- PostgreSQL advisor_subjects and student_subjects
- Admin/global uploaded PDFs
- Advisor subject PDFs
- Chat sessions and chat history stored in PostgreSQL
- Database map/schema overview

## Important safety design

The Database AI is a planner, not a dangerous database editor.

It can:

- read students
- list students
- count students
- summarize grades
- read/list advisors
- search/list PDFs
- inspect database map/schema
- use safe SELECT queries when needed

It cannot silently:

- delete private student records
- update grades
- change schema
- drop tables
- rewrite the database

For changes, the backend should expose explicit admin endpoints with clear UI buttons or confirmation steps.

## Main files changed

- `backend/app/agent/admin_database_ai.py`
  - New internal Database AI planner.
- `backend/app/agent/admin_agent.py`
  - Admin now uses AI 1 → AI 2 flow.
- `mcp_server/app/tools/mongo_tool.py`
  - Added MongoDB schema overview operation.
- `mcp_server/app/tools/postgres_tool.py`
  - Added PostgreSQL database map operation.
- `backend/app/main.py`
  - Admin broad overview now collects schema/database map context.
- `backend/app/agent/response_generator.py`
  - Added database architect prompt and clean database-map formatter.

## Good admin test questions

```text
explain machine learning simply
show database structure
what can you access in the university system?
list all students
S001 full profile
summarize all grades with A
list all advisors
what PDFs are uploaded?
what is writing re prot
```

Expected behavior:

- Normal questions stay in normal ChatGPT mode.
- Database/schema questions use the database map.
- PDF questions search all admin + advisor documents.
- Student questions use MongoDB.
- Advisor questions use MongoDB advisor records.
