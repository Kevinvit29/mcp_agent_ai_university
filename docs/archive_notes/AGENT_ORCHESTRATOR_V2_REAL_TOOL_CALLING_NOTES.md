# Agent Orchestrator V2 - Real Tool Calling Fix

This version is the next step after V1.  It addresses the problem where the chat felt "fixed" and sometimes reused the wrong previous context.

## Main Fixes

1. **Fresh entities always win**
   - If the latest user message contains `S035`, the system must query `S035`.
   - Learning Memory and old chat context are not allowed to replace it with `S001`.

2. **Validation contract per turn**
   Every plan now carries a contract, for example:

```json
{
  "expected_domain": "students",
  "required_student_ids": ["S035"],
  "must_not_return_other_student_for_single_id": true
}
```

3. **Wrong-entity result is blocked**
   If the user asks `S035 grade` but the database returns `S001`, the validator marks the result invalid and repairs the plan.  If it still cannot repair, it refuses to guess.

4. **Plan repair compares full arguments**
   V1 compared only `tool_name` + `operation`, so it refused to repair from S001 to S035 because both calls were `mongodb_student_tool/read_students`.  V2 compares the actual important arguments too.

5. **Missing student IDs return clean not-found rows**
   If `S035` does not exist, MCP returns:

```json
{"student_id":"S035", "message":"No student found with ID S035"}
```

so the answer is not silently replaced by another student.

## New Flow

```text
User question
→ Fresh entity extractor
→ Learning memory only if no explicit new entity
→ Schema-aware planner
→ MCP database call
→ Validation contract check
→ Repair loop if wrong domain/entity
→ Deterministic final answer from actual data
→ Gemini only for normal chat or flexible wording
```

## Recommended Test Cases

Ask these after a clean rebuild:

```text
s001 grade
s035 grade
s002 grade
what is s001, s002, s035 grade
how many subject are there in this university
how many students are there
list all uploaded pdf files
hello
```

Expected behavior:
- `s035 grade` must never return S001.
- If S035 is not in MongoDB, it must say S035 was not found.
- Subject questions must use `subject_summary`, not student count.
