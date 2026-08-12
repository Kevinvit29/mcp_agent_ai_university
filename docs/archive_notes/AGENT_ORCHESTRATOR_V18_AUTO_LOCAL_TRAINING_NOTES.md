# V18 — Automatic Local Training Pipeline

## Goal

Keep every existing/new MongoDB collection, PostgreSQL table, PDF, Excel sheet, CSV row set, and uploaded document agent up to date **without using Gemini embeddings or API tokens**.

## What is automatic

- Backend startup starts a background training controller.
- It runs immediately once, then repeats every `AUTO_TRAINING_INTERVAL_SECONDS` (default: 300 seconds).
- Uploads already create/update a data agent immediately.
- The background loop fingerprints all known database/file sources and skips unchanged agents.
- Only changed sources rebuild their local semantic vectors/chunks.
- A small local routing-centroid model refreshes from safe query-shape seeds plus active user corrections.

## Local method

V18 uses `local_hash_vector_v2`, a deterministic local semantic vectorizer plus lexical boosting. It is free and works offline after the container starts. This is **semantic indexing / retrieval training**, not a cloud LLM fine-tune and not a large neural network trained from scratch.

Why this is the right default:

- no Gemini quota/token use for indexing;
- new data becomes searchable automatically;
- indexes are incremental rather than full rebuilds;
- each table/file still has its own cloned data-agent profile.

## New storage

- `ai_index_source_state` — fingerprints, row/chunk counts, last indexed state.
- `ai_training_jobs` — job status/history.
- `ai_router_training_examples` — safe local routing examples.
- `ai_router_label_centroids` — locally trained routing centroids.

## New endpoints

```bash
# View current automatic local-training status
curl "http://localhost:8000/ai/training/status?user_role=admin"

# Run a local incremental cycle immediately (no Gemini tokens)
curl -X POST "http://localhost:8000/ai/training/run-local?user_role=admin"
```

## Environment

```env
AUTO_TRAINING_ENABLED=true
AUTO_TRAINING_INTERVAL_SECONDS=300
NEURAL_EMBEDDING_PROVIDER=local
LOCAL_ROUTER_LEARNING_ENABLED=true
```

## Important safety rule

The learned local routing hint is advisory only. It is visible in debug traces but cannot override explicit student IDs, role/PDPA policy, purpose contracts, or result validation.
