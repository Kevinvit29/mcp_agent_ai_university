# Deep Database AI Behavior Fix

This version fixes the real routing problem where the chatbot could fetch the wrong database domain.

## Main problem fixed
Before, the planner could treat this question:

> how many subject are there in this university

as a generic `how many` query and call student count, producing:

> There are 100 students.

That was wrong because the user asked for subjects, not students.

## What was added

### 1. Database Brain guard layer
New file:

- `backend/app/agent/database_brain.py`

The Database Brain runs before the normal role planner. It detects high-confidence domains:

- subjects / courses
- uploaded PDF / Excel files
- programs / majors / faculties
- advisor count/list

It prevents the LLM planner from fetching the wrong table/collection for obvious questions.

### 2. Result self-check and repair
After the MCP tool returns data, the backend now checks whether the result matches the user's requested domain.

Example:

- User asks subjects
- Old plan returns `student_count`
- Database Brain repairs the plan into `subject_summary`
- Backend calls MCP again before answering

This makes the chatbot more like a real database agent instead of a one-shot keyword router.

### 3. Subject summary operation in MongoDB tool
New MCP operation:

```json
{
  "tool_name": "mongodb_student_tool",
  "operation": "subject_summary"
}
```

It returns:

- unique subject count
- total student-subject grade records
- student count in scope
- subject list
- advisor IDs per subject
- grade distribution per subject
- top/common subjects

It works for:

- admin: all subjects
- advisor: only subjects they teach
- student: only their own subjects

### 4. Better final answer formatting
The final response layer now formats `subject_summary` deterministically, so Gemini does not accidentally convert subjects into students.

### 5. Admin advisor access policy corrected
Admin can now access advisor list/profile data through MCP policy. Before, `mongodb_advisor_tool` was blocked for admin in the policy layer even though admin should have full access.

## Test questions

After rebuild, test these:

```text
hello
how many subject are there in this university
i mean subject
list all subjects
how many program are there
what pdf/excel files are uploaded
how many advisors are there
what is s001, s002, s035 grade
```

Expected behavior:

- Subject questions answer subjects, not student count.
- Short correction like `i mean subject` repairs the previous mistake.
- Admin can ask broad database questions without being blocked.
- The chat still uses Gemini for normal conversation and document explanation, but database facts are grounded in MCP results.

## Rebuild command

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```
