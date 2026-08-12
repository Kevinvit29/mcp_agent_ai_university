# Agent Orchestrator V17 — Data Truth + Semantic Training

## Why V16 could show 5 students instead of 100

The system has more than one database store:

- **MongoDB `students`** is the canonical student master table and contains the 100 seeded students.
- **PostgreSQL `student_subjects`** stores student-to-advisor-to-subject permission links. Its row count is not a university student count.
- PostgreSQL also stores programs, documents, agent indexes, and chat state.

A broad AI-generated summary could mix PostgreSQL relationship/sample counts into a sentence about students. That is a provenance bug, not missing MongoDB records.

## V17 changes

1. Adds `backend/app/agent/data_truth.py`.
2. Forces broad Admin university overviews to use the MongoDB student count as the authoritative student total.
3. Adds `GET /system/data-truth?user_role=admin`.
4. Adds an Admin sidebar card that displays the canonical MongoDB student total.
5. Adds `POST /ai/data-agents/train-semantic?user_role=admin&provider=gemini`.
6. Adds optional Gemini Embedding 2 indexing with a safe local-vector fallback.
7. Keeps MongoDB/PostgreSQL table agents and uploaded PDF/Excel agents source-aware.

## Important terminology

The semantic training endpoint rebuilds **retrieval indexes** from current table rows, schemas, PDF chunks, and Excel rows.

It does **not** fine-tune a generative Gemini chat model. Training a query planner requires labeled examples such as:

- user question
- intended tool
- intended operation
- expected filter/sort
- verified result quality

Those examples should come from accepted debug traces, regression tests, and explicit user corrections.

## How to use the semantic training button

1. Confirm the System Stability card is healthy.
2. Confirm Data Source of Truth shows 100 students in MongoDB.
3. Click **Train with Gemini embeddings**.
4. The system checks whether the configured Gemini key can embed vectors.
5. If remote embeddings are unavailable or rate-limited, it automatically builds a local semantic index instead.

## Environment

```env
NEURAL_EMBEDDING_PROVIDER=local
GEMINI_EMBEDDING_MODEL=gemini-embedding-2
GEMINI_EMBEDDING_DIM=768
GEMINI_EMBEDDING_TIMEOUT=20
```

Keep `local` for free/offline indexing. Use the Admin training button when you want to attempt Gemini embeddings for a full reindex.
