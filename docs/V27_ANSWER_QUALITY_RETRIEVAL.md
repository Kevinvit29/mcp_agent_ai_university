# V27 — Answer Quality & Retrieval

## Purpose

V27 makes answers easier to trust without exposing technical implementation details or changing role/PDPA restrictions.

## Changes

1. **Source labels** — Chat now displays a compact label showing whether an answer comes from approved student/advisor/university records, a selected uploaded file, uploaded documents, or general guidance.
2. **Safe failures** — A source timeout, mismatch, missing record, or role restriction produces clear recovery guidance instead of hostnames, stack traces, raw MCP errors, or SQL text. Technical details remain in the protected admin trace.
3. **Thai retrieval** — Common Thai typing errors are normalized for routing and selected-file questions. Focus terms are extracted from compact Thai questions such as `ละเมิดคืออะไร`, and narrowly fuzzy-matched only within selected stored document text.
4. **Pinned follow-ups** — Tests verify that a selected document remains the provenance for focused follow-up questions rather than falling back to a generic document search.

## Safety boundaries

- Source labels never disclose database hosts, collection/table names, semantic scores, or protected fields.
- Failure text never reveals infrastructure or raw exception strings.
- Source labels do not bypass roles, PDPA filters, or selected-file access checks.
- Thai fuzzy matching is local, narrowly scoped to selected document text, and cannot invent content.

## Checks

```bash
pytest -q tests/test_v27_answer_quality_retrieval.py
```
