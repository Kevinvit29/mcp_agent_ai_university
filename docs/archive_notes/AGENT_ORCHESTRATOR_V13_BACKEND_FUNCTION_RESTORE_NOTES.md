# Agent Orchestrator V13 — Backend Function Restore Fix

## Problem found
The backend chat endpoint was alive, but one database-answer formatting function was missing after the stability/cleanup pass:

```text
name '_format_student_study_statistic' is not defined
```

This caused chat answers such as Thai student list/statistical student queries to return a backend chat error.

## File fixed

```text
backend/app/agent/final_answer_writer.py
```

## What was restored
Added the missing function:

```python
_format_student_study_statistic(...)
```

It formats results from:

```text
student_study_term_aggregate
```

for queries like:

- median GPA in Law program
- average GPA of students who study Law
- highest GPA in Law program
- count students matching a program/subject

## Safety
The fix does not delete database data and does not change Docker volumes.

## Validation

```text
Backend Python compile passed
MCP server Python compile passed
No missing _format_* calls remain in final_answer_writer.py
```
