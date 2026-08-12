# Agent Orchestrator V16 — Regression Evaluation Dashboard

## Purpose
V16 adds a deterministic regression suite so query-understanding and validation failures are discovered before planner changes are trusted.

## What is evaluated
- University-wide student totals
- Programme/subject term extraction (`Law`, `Business`, `Graphic Design`)
- Median, average, maximum, and minimum GPA routes
- Numeric GPA filtering
- Explicit student ID and answer-shape contracts
- Validator rejection of empty/generic study terms and incorrect aggregate operations

## What it does not claim
This dashboard does not train Gemini and does not run live student queries. It verifies the local intent/parser/planner contract layer without exposing student data or consuming API quota.

## Admin endpoints
- `GET /admin/evaluation/latest?user_role=admin`
- `POST /admin/evaluation/run?user_role=admin`

## Automated test
Run inside the backend container or local Python environment:

```bash
python -m unittest tests/test_v16_regression_evaluation.py
```
