# Agent Orchestrator V1.1 Entity Priority Fix

## Problem fixed
A short query like `S035 grade` was incorrectly treated as a correction/learning-memory follow-up after `S001 grade`.
Because the Learning Memory Agent ran before the deterministic student-ID planner, it reused the previous student context and returned S001 grades.

## Fix
- Explicit entities in the current message now always win: `S001`, `S035`, `A001`, etc.
- Learning Memory is skipped when the latest message contains a concrete student/advisor ID.
- Short correction detection no longer treats `S035 grade` as a correction.
- Conversation-state correction detection has the same entity guard.

## Expected behavior
- `S001 grade` returns S001.
- `S035 grade` returns S035 or says S035 not found. It must not return S001.
- `I mean subject` can still be stored as a correction memory.
