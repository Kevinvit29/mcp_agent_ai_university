# Agent Orchestrator V6 - Neural Data Agents

This version adds a neural-style data layer for uploaded PDF, Excel, and CSV files.

## Why this was added

Earlier versions could upload files and create PDF/Excel agent labels, but retrieval still depended heavily on keyword matching and fixed planner logic. This made the chat feel too rigid.

V6 adds a semantic data-agent index so each uploaded file/table receives its own searchable agent profile:

```
Upload PDF / Excel / CSV
→ Parse full text / sheets / columns / rows
→ Create AI data-agent profile
→ Create row/page/chunk records
→ Create local semantic embeddings
→ Store in PostgreSQL tables
→ MCP searches data-agent chunks before keyword fallback
→ Final answer uses verified chunks/rows
```

## Important note about “training a neural network”

This project does not train a large neural network from scratch. That would require a dataset, GPU/compute, labeling, evaluation, and model-serving infrastructure.

Instead, V6 implements a practical neural retrieval layer:

- semantic vector fingerprints
- chunk/row embeddings
- per-file/per-table agent profiles
- role-safe retrieval
- schema-aware search

This gives the project much more flexibility without heavy ML infrastructure.

## New backend files

```
backend/app/agent/neural_embedding.py
```

This is the local semantic embedding module. It creates lightweight vectors from text/rows/columns and supports cosine similarity.

## New PostgreSQL tables

```
ai_data_agents
ai_data_chunks
```

`ai_data_agents` stores one cloned data agent per uploaded file/table.

`ai_data_chunks` stores searchable semantic chunks:

- Excel row chunks
- Excel sheet schema chunks
- PDF extracted paragraph rows
- PDF text chunks
- AI explanation rows

## New backend endpoints

List cloned data agents:

```
GET /ai/data-agents
```

Semantic search inside all allowed data agents:

```
GET /ai/data-agents/search?q=your question
```

## Upload changes

When admin/advisor uploads a file, the backend now returns:

```
neural_data_agent: {
  agent_key,
  agent_name,
  indexed_chunk_count,
  capabilities
}
```

## MCP changes

`postgres_university_tool` now attaches neural data-agent matches to document search results. It respects the same role rules:

- Admin can search all uploaded data agents.
- Advisor can search only their own subject file agents.
- Student can search only advisor-subject file agents for subjects they are enrolled in.

## Frontend changes

The right knowledge panel now shows:

```
Neural Data Agents
X file/table agents indexed
```

Upload messages also show which neural data agent was created and how many chunks were indexed.

## What this improves

- Excel search becomes row-aware, not just file-summary search.
- PDF search can find later chunks/paragraphs more reliably.
- Each uploaded table/file has its own agent identity.
- The chat can pull more relevant data before final answer writing.
- This prepares the project for future pgvector/Gemini embedding/OpenAI embedding upgrades.

## Recommended next step

V7 should add a visible Debug Trace panel:

```
Purpose detected
Tool plan
Data agent selected
Semantic matches
Validator result
Final answer source facts
```

That will make it easier to see exactly why the AI answered a certain way.
