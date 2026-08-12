# Archived V21 — Core Reliability: Pinned Document Q&A + Release Quality Gate

## Purpose
V21 starts the final, quality-first development track. It focuses on one core user journey before adding more features:

1. Select an uploaded PDF/Excel/CSV file.
2. Ask a focused question about that exact file.
3. Receive an answer grounded in stored extracted content.
4. Verify the release with local, deterministic checks.

## What changed

### Exact selected-file answering
`backend/app/agent/document_qa.py` is a local deterministic document-answering layer. It:

- extracts meaningful terms from the user question;
- reads only the selected document’s stored `full_text`, preview, summary and study-note facts;
- ranks matching sentences locally;
- returns the best grounded excerpt before a broad file overview.

This fixes cases such as `What is torts?` after selecting a law PDF. The answer now comes from the selected file’s stored text instead of trying to find a filename/summary match again.

### Visible pinned context in chat
The chat composer displays `Asking about <filename>` when a file is selected with the workspace **Ask** action. The user can clear the context before sending a different question.

### Release quality gate
Admin endpoints:

```bash
GET  /admin/quality-gate/latest?user_role=admin
POST /admin/quality-gate/run?user_role=admin
```

The gate combines:

- the existing query-contract evaluation; and
- document-grounding checks.

It is local and deterministic. It does not call Gemini and does not expose private records.

## Tests

```bash
pytest -q tests/test_v21_document_grounding.py \
  tests/test_v15_query_contracts.py \
  tests/test_v16_regression_evaluation.py \
  tests/test_v17_data_truth.py \
  tests/test_v18_local_training_contract.py
```

## Next planned phase
V22 should add end-to-end API tests against Docker services and a small curated test dataset, then block releases when the core flows fail.
