# AI Learning Memory Upgrade

This version adds a correction-learning layer so the chatbot can improve from mistakes without fine-tuning Gemini.

## What changed

### 1. New database table

PostgreSQL now creates:

```sql
ai_learning_memories
```

It stores:

- original user question
- user correction message
- wrong answer excerpt
- learned domain, such as `subjects`, `documents`, `programs`, `grades`, `gpa`, or `advisors`
- corrected question
- confidence
- use count
- metadata

### 2. New learning agent file

Added:

```text
backend/app/agent/learning_memory.py
```

It detects correction messages such as:

```text
i mean subject
not students, subjects
actually I mean uploaded PDFs
หมายถึงวิชา
ไม่ใช่นักศึกษา หมายถึงรายวิชา
```

When a correction is detected, it stores the lesson and immediately reroutes the previous question.

### 3. Applied before normal planning

The new chat flow is:

```text
User message
→ AI Learning Memory checks if this is a correction
→ If yes: save lesson and reroute previous question
→ If no: check if a previous lesson matches this question
→ Database Brain
→ Role Agent / Gemini Planner
→ MCP database call
→ Result self-check / repair
→ Final answer
```

### 4. New backend endpoints

List learning memories:

```bash
curl "http://localhost:8000/ai/learning/memories?user_role=admin"
```

Deactivate one memory:

```bash
curl -X DELETE "http://localhost:8000/ai/learning/memories/1?user_role=admin"
```

### 5. Frontend status card

The right knowledge panel now shows:

```text
Learning Memory Agent
X correction rules stored
```

This helps confirm when the system is learning from corrections.

## Example

Before:

```text
User: how many subject are there in this university
AI: There are 100 students.
User: i mean subject
```

Now:

```text
System stores a learning memory:
subject → use subject_summary, not student_count
```

Then the system reroutes the previous question and answers with subject count.

## Important

This is not model fine-tuning. It is safer for a university database project because it does not change the base model. It stores routing lessons in your own PostgreSQL database and applies them before Gemini/database planning.
