# Agent Orchestrator V5 - Aggregate Reasoning Fix

## Problem fixed

The previous version could understand single-student questions like `S099 profile`, but it still failed on aggregate/comparison questions such as:

- `how many student grade lower 3.0`
- `how many student gpa lower 3.0`
- `student that have gpa lower than 3.0`
- `which students have grade under 3`

The chatbot sometimes answered: `The verified facts do not specify...` because the planner did not create a strict numeric GPA filter before calling MongoDB.

## What V5 adds

### 1. Aggregate Query Parser

New file:

```text
backend/app/agent/aggregate_query.py
```

This detects numeric student/GPA comparison intent from the latest message before database execution.

It supports imperfect English such as:

```text
gpa lower 3.0
grade lower 3.0
gpa below 3
student that have gpa lower than 3.0
which students have grade under 3
```

Because the demo database stores subject grades as letters but GPA as a number, numeric `grade lower 3.0` is interpreted as a GPA filter.

### 2. New MCP operation

Updated:

```text
mcp_server/app/tools/mongo_tool.py
```

New operation:

```text
filter_summary
```

It returns:

```json
{
  "type": "student_filter_summary",
  "count": 0,
  "query_filter": {"gpa": {"$lt": 3.0}},
  "metric_query": {...},
  "students": [...],
  "total_records": 0,
  "truncated": false
}
```

This is better than only returning preview rows because the final answer can now truthfully answer both count and list questions.

### 3. Contextual planner now builds a real filter contract

Updated:

```text
backend/app/agent/context_reasoner.py
backend/app/agent/contextual_tool_planner.py
backend/app/agent/tool_planner.py
```

The planner now creates:

```json
{
  "operation": "filter_summary",
  "query_filter": {"gpa": {"$lt": 3.0}},
  "answer_style": "aggregate_count"
}
```

for count questions, and:

```json
{
  "operation": "filter_summary",
  "query_filter": {"gpa": {"$lt": 3.0}},
  "answer_style": "aggregate_filter"
}
```

for list/filter questions.

### 4. Final Answer Writer handles aggregate results

Updated:

```text
backend/app/agent/final_answer_writer.py
```

Example output:

```text
I found 33 student(s) with GPA lower than 3.0.
```

or:

```text
I found 33 student(s) with GPA lower than 3.0.

Matching students:
- S010 (Student 010): GPA 2.96, Computer Science
- S024 (Student 024): GPA 2.97, Data Science
...
```

## Test prompts

After rebuilding, test:

```text
how many student grade lower 3.0
how many student gpa lower 3.0
student that have gpa lower than 3.0
which students have grade under 3
students below 2.5
students above 3.5
```

## Why this is the next step

V4 made the AI understand context for single-record requests. V5 adds aggregate reasoning, meaning the system can now answer questions that require computing a filtered count or filtered list from the database.

The architecture is now closer to:

```text
Understand purpose
→ Build data contract
→ Build exact database filter
→ Pull/count data
→ Validate result type
→ Answer from verified facts
```
