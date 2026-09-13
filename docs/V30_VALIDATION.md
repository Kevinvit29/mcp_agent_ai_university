# V30 Validation Record

Last verified locally: 2026-08-16 (Asia/Bangkok)

## Student role acceptance

- Signed `S001` access passed 10 own-data questions covering profile, GPA,
  subjects, grades/scores, attendance, assessments, tuition, scholarships,
  best-course performance, and course files.
- Nine cross-student/population questions were blocked before database execution.
- Forged `admin`, `S002`, and `A001` request fields were overwritten by the signed token.
- Advisor, Lecturer, and Administrator route-family requests returned HTTP 403.
- Replaced the duplicated `student_subjects` permission source with current
  `student_course_enrollments` across API lists, document access, Excel access,
  semantic data agents, and MCP queries.
- Removed six exact stale legacy subject links; the stale-link audit now returns zero.
- S001 now consistently reports 6 current enrolled subjects instead of an incorrect 8.
- Grade answers include numeric scores when stored and no longer expose internal Advisor IDs.
- Full regression suite: 143 passed.
- All five Docker services and the deployed Student interface are healthy.

## Lecturer role acceptance

- Added 40 non-destructively upserted synthetic Lecturer accounts (`L001`–`L040`).
- `L001 / demo1234` signs in with a separate Lecturer identity and signed `A001`
  teaching-assignment scope.
- Live Lecturer query returned 9 assigned subjects and used the scoped classroom tool.
- A forged Administrator role and forged `A002` scope were overwritten by the signed token.
- Advisor and Administrator route-family requests returned HTTP 403.
- University-wide GPA ranking was blocked before a database query.
- Added a dedicated `lecturer_documents` store with signed Lxxx ownership and
  Axxx teaching-scope validation. Lecturer files no longer reuse Advisor rows.
- Live upload to assigned class `CS302` passed; upload to unassigned `CALC` was blocked.
- L002 could not read L001's file. Enrolled Student S001 could list, open, and ask
  the AI about the L001/CS302 file. The acceptance record was deleted afterward.
- Forged Lecturer identity values were overwritten by the signed token.
- Full regression suite: 145 passed.
- All five Docker services were healthy after deployment.

## Current verified state

- All five Docker services are running and healthy: PostgreSQL, MongoDB, MCP server, backend, and frontend.
- The synthetic V30 dataset is synchronized: 1,000 student master records in MongoDB and 1,000 linked student profiles in PostgreSQL.
- The automatic system gate passes 5/5 checks.
- Deterministic AI routing and validation passes 113/113 cases (108 catalog cases plus 5 validator cases), without Gemini calls or private records.
- The packaged end-to-end gate passes 29/29 cases.
- The live database connection gate passes 4/4 cases.
- The complete packaged test suite passes 145/145 tests.
- The live academic brain gate passes 19/19 role-scoped database cases.
- The signed random-question gate passes 28/28 English, Thai, typo, paraphrase, capability-boundary, and role-scope cases.
- A signed `/chat` matrix passes 19/19 browser-equivalent cases across admin, student, and advisor roles.

## Step 3 master-data validation

- Student CSV, XLSX, and XLS files are staged separately from document knowledge uploads.
- Preview performs deterministic alias mapping, editable source-column mapping,
  required-field checks, number/range/email checks, within-file duplicate checks,
  and existing-record checks against both databases.
- A live reversible test proved preview made no database change, confirmation
  synchronized a new synthetic test record into PostgreSQL and MongoDB, per-row
  verification passed, and rollback returned the stores to 1,000/1,000 records.
- A controlled crash simulation wrote only the MongoDB half of a staged test
  batch, restarted the backend, and proved startup recovery removed the partial
  row from both stores before dataset verification. The interrupted batch was
  retained as `failed` for audit review rather than silently retried.
- Dataset health now compares the exact sorted student-ID fingerprint in both
  stores, so confirmed real rows beyond the 1,000-row demo baseline do not create
  a false health failure.
- Live student and advisor edit/deactivate/reactivate workflows stayed
  synchronized, and the original active state was restored after the test.
- A signed Student request to the Administrator master-data API returned HTTP 403.
- The Administrator browser UI exposes separate **Files** and **Student data**
  tabs. The safe import card, mapping editor, preview table, explicit confirmation,
  audit history, and rollback control rendered with no browser errors.

## Brain and database coverage

The verified live cases include:

- total student counts and exact GPA-filter counts;
- individual student GPA rankings;
- average GPA grouped by program;
- average grade grouped by course;
- attendance, finance, scholarship, assessments, course catalog, and academic-risk retrieval;
- student access to only the signed student's own records;
- advisor access to grades and attendance only inside the signed advisor's assigned classes;
- denial of advisor finance/GPA requests and denial of unknown database-worker operations.
- typo-tolerant profile, grade, and attendance requests;
- Thai student-count, grade, and attendance questions;
- enrolled-class lists and named-course membership for the signed student;
- follow-up entity/topic inheritance without widening permissions;
- explicit boundaries for prediction, causation, prerequisites, and unavailable future facts; and
- context-safe denial of broad requests such as a student asking to list everyone.

The program-average check has an explicit semantic contract: it must use the MongoDB grouped-program aggregate and return a `group_analytics` payload. An individual-student ranking cannot pass that check.

The random-question gate uses signed access tokens and the real `/chat` endpoint. It reports routing metadata only and deletes the temporary chat sessions it creates.

## Interface and operational behavior

- Health checks run invisibly after login and after every completed chat message.
- The removed System/maintenance panel is not part of the normal frontend.
- Administrator technical traces remain admin-only.
- Local training and maintenance endpoints remain backend operational capabilities and are not exposed as normal user controls.

## Data notice

The current local dataset is `synthetic_demo_v30`. It is for development and demonstration; it is not production university data.
