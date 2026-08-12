# V26 — Controlled Local Learning Review

## Purpose

V26 makes correction memory safer and more understandable. It does **not** fine-tune Gemini or send training data to a cloud model.

## New behavior

1. A user correction such as `I mean subjects, not students` still fixes the current chat turn immediately.
2. The inferred routing lesson is stored as a **candidate**, not an active global rule.
3. Only an admin can **Publish**, **Dismiss**, or later **Pause** the candidate in **System → Controlled learning review**.
4. Only published memories are eligible for a future-chat routing hint.
5. Every answer now offers voluntary **Helpful** / **Needs review** feedback. Feedback is stored for review and never becomes a planner rule by itself.

## Safety boundaries

- No Gemini token usage.
- No automatic cloud fine-tune.
- Publishing a routing memory cannot change PDPA permissions, role filters, or access to protected fields.
- Candidate corrections are identity-scoped until an admin reviews them.
- Feedback stores compact question/answer excerpts only after the user actively clicks a feedback button.

## Admin API

```text
GET  /admin/learning-control/overview?user_role=admin
GET  /admin/learning-control/memories?user_role=admin
POST /admin/learning-control/memories/{memory_id}/publish
POST /admin/learning-control/memories/{memory_id}/dismiss
GET  /admin/learning-control/feedback?user_role=admin
POST /admin/learning-control/feedback/{feedback_id}/reviewed
POST /admin/learning-control/gate/run?user_role=admin
```

## Why not auto-publish everything?

A correction may be local to one chat or may itself be mistaken. Keeping it as a candidate prevents one ambiguous correction from changing how future users are routed. The current conversation is still corrected immediately, so the user does not have to wait for review.
