# Agent Orchestrator V4 - Context-First Data Contract

## Why this fix exists

V3 added contextual reasoning, but one class of mistakes still survived:

- User asked: `S099 profile`
- AI/database plan sometimes treated it as `student_grades`
- Final answer returned only grades because `subject_grades` existed in the returned profile row

That made the chatbot feel fixed/rule-based and not aligned with the user's real purpose.

## What V4 adds

V4 keeps the AI context/purpose reasoner, then adds a strict **latest-message data contract**.

Flow:

```text
User message
→ AI Contextual Purpose Reasoner
→ Latest Message Data Contract
→ Contextual Tool Planner
→ MCP Database Tool
→ Result Validator
→ Final Answer Writer
```

The AI still reads the full context first, but the newest message creates a hard contract for:

- explicit student IDs such as S001, S099
- explicit advisor IDs such as A001
- requested answer shape: profile, grades, GPA, names, summary
- whether history is allowed or forbidden

## New file

```text
backend/app/agent/purpose_contract.py
```

Important functions:

```python
build_latest_message_contract(message)
apply_contract_to_purpose(message, purpose)
requested_student_answer_style(message)
```

## Main behavior improvement

### Before

```text
User: S099 profile
Assistant: Student S099 has these grades...
```

### After

```text
User: S099 profile
Assistant: Student profile:
- S099 (...)
  - Program: ...
  - GPA: ...
  - Academic status: ...
  - Email: ...
  - Subjects/grades: ...
```

## Validation added

The result validator now checks answer shape, not only domain/entity.

Example:

```text
Question requested profile
Plan used grades
→ invalid
→ repair plan
```

This prevents the system from saying "correct student, wrong type of answer."

## Final answer writer fix

Previously, if a row had `subject_grades`, the final writer automatically formatted it as grades, even if the user asked for a profile.

V4 fixes this by making `answer_style="profile"` stronger than the presence of `subject_grades`.

## Test cases

```text
s099 profile
s099 grade
s099 gpa
s001 profile
s001 grade
s001 s002 s035 profile
what is s095 profile
```

Expected:

- profile questions answer with profile fields
- grade questions answer with subject grades only
- GPA questions answer with GPA only
- explicit latest IDs always override previous chat context
