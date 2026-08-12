# Agent Orchestrator V7 — Debug Trace Panel

This version adds a developer/debugging layer so the project owner can see how the AI database agent made each answer.

## Why this was added

Earlier versions improved routing, context reasoning, validation, aggregate queries, and neural data agents. The next bottleneck was visibility: when an answer was wrong, it was hard to know whether the problem came from:

- purpose/context understanding
- selected tool
- wrong MCP arguments
- database result shape
- validator not catching a mismatch
- final answer writer formatting the wrong fields
- learning memory overriding the latest question

V7 makes this visible.

## New backend file

```text
backend/app/agent/debug_trace.py
```

This module builds safe compact traces for chat turns. It redacts sensitive keys such as email, phone, national_id, passport_id, address, passwords, API keys, tokens, full_text, and embeddings.

## New chat response field

`POST /chat` now returns:

```json
{
  "debug_trace": {
    "version": "V7_DEBUG_TRACE_PANEL",
    "input": {},
    "purpose_analysis": {},
    "purpose_contract": {},
    "selected_plan": {},
    "execution_steps": [],
    "validation": {},
    "tool_result_summary": {},
    "answer_quality": {},
    "developer_hint": "..."
  }
}
```

## Stored in PostgreSQL chat metadata

Each assistant answer saves the trace into `chat_messages.metadata.debug_trace`, so old chat turns can be opened and inspected later.

## New endpoint

```bash
curl "http://localhost:8000/chat/debug/last?session_id=<SESSION_ID>&user_role=admin"
```

Returns the latest assistant debug trace for the selected chat session.

## Frontend changes

The UI now has:

- `View AI trace` button under assistant messages
- right-side `AI Debug Trace` card
- full-screen trace panel showing:
  1. user purpose/context
  2. selected tool plan
  3. execution and repair steps
  4. tool result summary and validation
  5. final answer grounding preview

## What this helps fix next

After testing real questions, use the trace to find the true failure point:

- If purpose is wrong → improve `context_reasoner.py` / `purpose_contract.py`
- If purpose is correct but tool is wrong → improve `contextual_tool_planner.py`
- If tool is correct but result is wrong → improve MCP tool operation
- If result is correct but answer is wrong → improve `final_answer_writer.py`
- If old context overrides new ID → improve learning memory / context guard

## Validation completed

- Backend Python compile passed
- MCP server Python compile passed
- Frontend build passed after npm ci
