# Agent Orchestrator V8 — Existing Database Neural/Table Agents

This version improves the project in two important ways.

## 1. Existing databases are indexed as cloned AI data agents

Earlier versions created neural/data agents mainly when the user uploaded PDF/Excel/CSV files. V8 also indexes data that already exists in the project database.

At backend startup, the system can create/update cloned data agents for:

- MongoDB `students`
- MongoDB `advisors`
- PostgreSQL `programs`
- PostgreSQL `campus_locations`
- PostgreSQL `advisor_subjects`
- PostgreSQL `student_subjects`

Each table/collection becomes an AI-searchable data agent with:

- agent name
- table schema
- column list
- row chunks
- semantic vector fingerprints
- row metadata

This is the practical local version of "training the database". It does not train a large neural network from zero. Instead, it builds a searchable neural-style representation of your existing database so the orchestrator and tools can retrieve relevant rows more flexibly.

## 2. Study-term query fix

The question:

```text
give me the name of the student that study law
```

used to produce a weak plan:

```json
{
  "operation": "read_students",
  "student_id": "ALL",
  "query_filter": {}
}
```

That was wrong because the system pulled all students and then the final answer could guess.

V8 adds a real operation:

```text
mongodb_student_tool → study_term_search
```

The planner now detects study/program/subject questions and sends:

```json
{
  "operation": "study_term_search",
  "study_term": "law"
}
```

The MCP tool searches real fields:

- `program`
- `subject_grades.subject`

Then the final answer is generated from verified matches only.

## New/updated backend behavior

New startup behavior:

```env
AUTO_INDEX_EXISTING_DATABASE_AGENTS=true
```

New admin endpoint:

```bash
curl -X POST "http://localhost:8000/ai/data-agents/reindex-existing?user_role=admin"
```

Existing endpoint now also shows database table agents:

```bash
curl "http://localhost:8000/ai/data-agents?user_role=admin"
```

Semantic search over uploaded and existing database agents:

```bash
curl "http://localhost:8000/ai/data-agents/search?q=students studying law&user_role=admin"
```

## New MCP capability

`postgres_university_tool` now supports:

```json
{
  "query_type": "data_agents",
  "operation": "semantic_search",
  "keyword": "students studying law"
}
```

## Files changed

- `backend/app/agent/aggregate_query.py`
- `backend/app/agent/context_reasoner.py`
- `backend/app/agent/contextual_tool_planner.py`
- `backend/app/agent/tool_planner.py`
- `backend/app/agent/result_validator.py`
- `backend/app/agent/final_answer_writer.py`
- `backend/app/agent/neural_embedding.py`
- `backend/app/db/postgres.py`
- `backend/app/main.py`
- `mcp_server/app/tools/mongo_tool.py`
- `mcp_server/app/tools/postgres_tool.py`
- `mcp_server/app/tools/neural_embedding.py`
- `.env`
- `.env.example`

## Test questions

```text
give me the name of the student that study law
which students study law
how many students study law
students studying environmental science
find students who take graphic design
```

Expected behavior:

- The tool plan should use `study_term_search`.
- It should not read all students without a study filter.
- Final answer should list only students whose program or subject names match the study term.
- Debug trace should show purpose/study query and operation `study_term_search`.
