# Agent Orchestrator V3 - Contextual Reasoning Planner

This version upgrades the chat brain from keyword/rule-first routing to **purpose-first AI reasoning**.

## Problem fixed
Earlier versions still felt fixed because the backend often routed from keywords such as `grade`, `subject`, `student`, or `how many` before understanding the whole sentence.

Example old failure:

```text
User: how many subject are there in this university
Bad router sees: how many
Wrong plan: count students
```

Or:

```text
User: S035 grade
Bad memory/context layer reused old S001 context
Wrong answer: S001 grade
```

## New V3 flow

```text
User message
→ Contextual Purpose Reasoner
→ Purpose JSON: what does the user actually want?
→ Contextual Tool Planner
→ Safe MCP plan with schema + role permissions
→ MCP database execution
→ Result Validator
→ Repair if result does not match purpose/entity/domain
→ Verified Facts Writer
→ AI naturalized final answer using only verified facts
```

## New files

```text
backend/app/agent/context_reasoner.py
backend/app/agent/contextual_tool_planner.py
```

## Updated files

```text
backend/app/agent/agent_orchestrator.py
backend/app/agent/result_validator.py
backend/app/agent/final_answer_writer.py
.env
.env.example
README.md
```

## What the Contextual Purpose Reasoner returns

The AI now creates a JSON purpose analysis before routing:

```json
{
  "message_type": "new_request",
  "user_purpose": "Get grade records for student S035.",
  "target_domain": "student_grades",
  "answer_intent": "read",
  "should_use_database": true,
  "explicit_entities": {
    "student_ids": ["S035"],
    "advisor_ids": []
  },
  "not_purpose": ["Do not use previous S001 context."],
  "must_not_use_previous_entities": true,
  "confidence": 0.95
}
```

## Backend safety guard

The AI is allowed to understand intent, but the backend still protects correctness:

- Latest explicit IDs always win over history.
- AI cannot invent arbitrary tools.
- AI cannot bypass PDPA policy.
- Result validator checks that returned data matches the requested domain and ID.
- If the model fails, V2 deterministic schema guards still run as fallback.

## Less fixed answers

V3 adds optional natural rewriting of database answers:

```env
AI_NATURALIZE_DATABASE_ANSWERS=true
```

The system first builds a deterministic answer from real database facts, then asks Gemini to rewrite only those facts naturally. Gemini is explicitly forbidden from adding new facts, grades, IDs, counts, or private data.

Set it to `false` if you want faster but more robotic answers.

## Recommended tests

```text
hello
what is law
s001 grade
s035 grade
s001 s002 s035 grade
how many subject are there in this university
how many students are there
list uploaded pdf files
what excel files are uploaded
show student list
which students have GPA lower than 3.0
i mean subject
```

Expected behavior:

- Normal questions stay normal chat.
- Explicit IDs never reuse previous IDs.
- Subject count uses `subject_summary`, not student count.
- Uploaded files use document tools.
- Database answers are based on MCP data and then naturally rewritten.
