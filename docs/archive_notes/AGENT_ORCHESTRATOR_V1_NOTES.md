# Agent Orchestrator V1 Upgrade

This version upgrades the chat brain from a keyword-style database router into a schema-aware agent pipeline.

## New backend modules

- `backend/app/agent/schema_registry.py`  
  Defines what data exists in MongoDB/PostgreSQL, which tool owns each domain, and what fields each role can access.

- `backend/app/agent/conversation_state.py`  
  Extracts recent context, previous user message, previous assistant answer, and correction signals.

- `backend/app/agent/tool_planner.py`  
  Creates a safe MCP plan using:
  1. deterministic high-risk guards for subjects, student IDs, documents, advisors, GPA/ranking, programs, campus, schema
  2. Gemini strict JSON schema-aware planner
  3. legacy role-router fallback only if needed

- `backend/app/agent/result_validator.py`  
  Checks whether the returned database result matches the user's expected domain. If the user asks for subjects but the result is student count, it repairs the plan and calls MCP again.

- `backend/app/agent/final_answer_writer.py`  
  Writes final answers from actual MCP data. Protected database facts are formatted deterministically to avoid hallucination. Normal chat and nuanced answers can still use Gemini.

- `backend/app/agent/agent_orchestrator.py`  
  Public orchestration API used by `/chat`.

## New chat flow

```text
User question
→ Learning Memory / user correction layer
→ Agent Orchestrator V1
→ Schema-aware tool plan
→ MCP database call
→ Result Validator
→ Repair plan if domain mismatch
→ Final Answer Writer
→ Save chat history with planner + validation metadata
```

## Problems fixed

- `how many subject are there in this university` no longer counts students.
- `what is S001, S002, S035 grade` fetches all requested IDs, not just the first one.
- PDF/Excel questions are routed to the document agent even if previous chat context mentioned a student.
- Student, advisor, and admin roles still go through MCP/PDPA guards.
- Final answers for grades/GPA/subject count/advisors/documents are based on returned database data, not model guesses.

## Example plans

### Subject count

```json
{
  "tool_name": "mongodb_student_tool",
  "arguments": {
    "operation": "subject_summary",
    "student_id": "ALL"
  }
}
```

### Multi-student grade request

```json
{
  "tool_name": "mongodb_student_tool",
  "arguments": {
    "operation": "read_students",
    "student_id": "ALL",
    "query_filter": {"student_id": {"$in": ["S001", "S002", "S035"]}},
    "requested_fields": ["student_id", "name", "program", "academic_status", "subject_grades"]
  }
}
```

## Test commands

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```

Then test in chat:

```text
hello
how many subject are there in this university
what is S001, S002, S035 grade
how many students are there
list all pdf files
where is cafeteria
which students have GPA lower than 3.0
```

## Important design decision

For private university facts, the final answer writer uses deterministic formatting first. This is intentional: the AI can write normal chat, but it should not invent private database facts or ignore allowed rows.
