# AI Behavior Fix Notes

This build fixes the behavior shown in the screenshot where the chatbot answered only the first student ID from a multi-student question.

## Main fixes

### 1. Explicit multi-student ID routing
Questions like:

```text
what is S001, S002, S035 grade
```

now route deterministically to one MongoDB query using:

```json
{
  "student_id": "ALL",
  "query_filter": {"student_id": {"$in": ["S001", "S002", "S035"]}}
}
```

This prevents the LLM planner from accidentally selecting only `S001`.

### 2. Better answer shaping
The backend now detects whether the explicit Sxxx question is asking for:

- grades
- GPA
- names
- profile/full information

Then it requests only the needed fields and formats the answer correctly.

### 3. Advisor multi-ID support
Advisor questions with multiple student IDs are also supported. The MCP/PDPA layer still filters the results so advisors can only see subjects they teach.

### 4. Missing ID visibility
For explicit multi-ID admin/advisor questions, missing student IDs are not silently ignored. The answer includes a safe message such as:

```text
S999: No student found with ID S999
```

### 5. Safer deterministic formatter
Protected database answers no longer depend only on Gemini wording. If the MCP tool returns allowed data, the backend formats grades, GPA, profiles, subjects, and lists directly. This makes answers more stable and faster.

## How to test

After rebuilding Docker, ask:

```text
hello
```

Expected: normal chat reply.

```text
what is s001 , s002 , s035 grade
```

Expected: grades for S001, S002, and S035.

```text
what is s001 s002 gpa
```

Expected: GPA for both S001 and S002.

```text
s001 profile
```

Expected: full admin-visible profile for S001.

## Rebuild command

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```
