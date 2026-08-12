# Release Roadmap: Step-by-Step to a Reliable University AI

This project should now progress through controlled quality steps rather than adding isolated patches.

## Completed foundation

- Role-based access control and PDPA boundaries.
- MongoDB as the canonical student/advisor source.
- PostgreSQL for uploaded-document metadata, sessions, learning memory and data-agent index state.
- PDF, Excel and CSV ingestion.
- Local semantic indexing and auto-refresh without Gemini embedding tokens.
- Planner, validator, debug trace, evaluation dashboard and source-of-truth diagnostics.
- Selected-document context and local document-grounded answers (V21).

## V21 — Core reliability (current)

- Fix exact selected-file Q&A.
- Show selected document context in the composer.
- Run a local release quality gate for query contracts and document grounding.

## V22 — End-to-end test gate

- Add Docker/API smoke tests for login, chat, student query, document upload, document question and role permissions.
- Add a safe test dataset used only by tests.
- Make the dashboard show core-flow pass/fail before a release.

## V23 — Table understanding and workspace quality

- Consistent schema summaries for MongoDB, PostgreSQL, Excel and PDF sources.
- Column type detection, searchable/sortable table views and selected-row questions.
- Clear source-of-truth labels for canonical vs relationship/reference tables.

## V24 — Controlled learning

- Promote correction rules only after validation and regression checks pass.
- Track query → tool-plan → result-validation examples.
- Keep learning scoped by role and never allow it to bypass PDPA rules.

## V25 — Production hardening

- Rate limits, audit logs, structured error reporting and backup/restore procedure.
- CI pipeline running the release quality gate on each code change.
- Deployment configuration and health-monitoring guidance.

## Definition of done

The project is production-ready only when all core flows pass automated end-to-end tests, user corrections cannot bypass access control, source-of-truth rules are enforced, and chat errors are observable/recoverable.


## V23 — Table & Workspace Quality

Completed: Data workspaces distinguish source rows from reading-guide notes and support column-aware search, sorting, pagination, and CSV export.


## V24 — End-to-End Test Gate

Completed: the local fixture gate verifies message contract → plan → validation → answer shape and selected-document answers without a cloud model call.

## V25 — Live Database Smoke Gate

Completed: admins can run aggregate-only, read-only checks against the actual Docker MongoDB, PostgreSQL, and MCP services. The gate verifies canonical-source boundaries and reports no raw student/document content.

## V26 — Controlled Local Learning Review (completed)

- Corrections repair the current chat turn, then become review candidates rather than future global rules.
- Admin can publish, dismiss, or pause candidate routing lessons.
- Helpful / Needs review answer feedback is review-only and never creates a planner rule automatically.
- No Gemini tokens or cloud fine-tuning are used.

## V27 — Answer Quality & Retrieval (completed)

- Clear user-facing source labels for database, document, and general guidance answers.
- Improved Thai typo handling and selected-document follow-up tests using the exact selected-file contract.
- Safe, human-readable recovery messages when a source cannot answer; raw technical details remain only in admin debug traces.

## V28 — Production Hardening (completed)

- Signed session identities now bind role/account ownership at the backend; browser-supplied role and owner fields cannot change access scope.
- MCP tool calls require an internal service key in addition to existing PDPA enforcement.
- Per-instance rate limits, structured error responses with request IDs, privacy-preserving audit logs, and liveness/readiness endpoints are in place.
- Production Compose keeps database/MCP/backend services private, adds health checks/restart policies, and uses a same-origin frontend API proxy. A separate localhost-only developer overlay is provided.
- CI runs deterministic backend release tests and a production frontend build on each push/pull request.
- Backup, checksum verification, guarded restore, password-hash migration support, deployment, monitoring, and incident guidance are documented.

## Production release condition

A deployment owner must set real secrets, explicit HTTPS CORS origins, an external HTTPS reverse proxy/WAF, `ALLOW_LEGACY_DEMO_PASSWORDS=false`, tested backup recovery, and monitoring alerts before calling a live deployment production-ready.
