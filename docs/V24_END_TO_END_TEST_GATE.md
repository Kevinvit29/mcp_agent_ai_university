# V24 — End-to-End Test Gate

V24 adds a local, deterministic safety gate that tests the complete response shape:

`message → latest-message contract → contextual plan → fixture tool result → result validator → deterministic final answer`

It also checks selected-document Q&A separately.

## Why this exists

A parser can understand a question correctly while a later layer loses the intent. For example:

- intent says “median GPA for Law”
- planner accidentally searches `what is`
- validator only checks the broad domain
- final answer says no students found

V24 catches that complete-chain failure before releasing a planner change.

## Admin API

- `GET /admin/end-to-end-gate/latest?user_role=admin`
- `POST /admin/end-to-end-gate/run?user_role=admin`

No Gemini request and no live student data are used.

## Included checks

- total university student count in English and Thai
- Law-program median GPA
- GPA below threshold count
- exact student profile contract
- selected-document focused question
- selected-document overview question

## What V24 does not replace

It is a deterministic fixture gate, not a replacement for human acceptance testing against the real database. V25 should add a controlled live-read-only smoke test after Docker is stable.
