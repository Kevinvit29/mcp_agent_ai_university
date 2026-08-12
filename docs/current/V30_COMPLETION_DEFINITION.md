# V30 Completion Definition

## Decision

V30 is the only active release line for this project.

There is no V31 package to install and no backend overlay step. All remaining
reliability, cleanup, data-management, dashboard, testing, and deployment work
will be implemented directly in the current V30 project. Version numbers found
in older notes describe historical milestones; they do not create a separate
product or installation requirement.

The target is a **complete V30 release** that starts with one supported method,
passes automated and live acceptance tests, and requires no manual source-code
fixes after installation.

## Current foundation

The project already contains:

- Dockerized frontend, backend, MCP server, MongoDB, and PostgreSQL services
- Database-backed Administrator login
- Student, Advisor, and Administrator permissions
- 1,000 synchronized synthetic students
- Academic, enrollment, grade, attendance, finance, scholarship, and advisor data
- PDF, Excel, and CSV upload and document-question support
- PDF report generation and authenticated report downloading
- A local trainable intent router
- Table-result rendering
- An Administrator system check and Advanced maintenance area
- Automated backend tests and a frontend build gate in GitHub Actions

These features are a foundation, not proof that V30 is release-ready. Each
required behavior must still pass the release gates below.

## Milestone 1: Harden the current V30 chat path

Do not install or copy code from another version. Refactor the current backend
in place until it has:

- one authoritative chat entry path;
- one current entity-extraction path;
- one current deterministic planning path with optional, non-authoritative AI
  routing hints;
- latest-message precedence over older conversation context;
- latest explicit student ID, name, or surname precedence;
- no learning-memory override in normal chat planning;
- clear separation between record tables and database-schema requests;
- exact count answers for count-only questions;
- authenticated report links;
- safe clarification for unsupported or real-time questions; and
- backend-enforced role and record-scope permissions.

Learning and feedback records may remain available for Administrator review and
offline router training, but they must never silently replace the entity,
purpose, or scope of a normal chat request.

### Required acceptance prompts

Run these against the live Docker stack:

```text
student S099 profile
gpa of boonmee
gpa of aksornchai
how many students study Business Analytics
list students as a table
create a PDF report for Business Analytics students
show columns in the student table
what is the Boonmee family doing right now
```

Expected behavior:

- the latest person, student ID, or surname always wins;
- count questions return the count without an unrelated record dump;
- table questions return records, not schema metadata;
- schema questions return tables or columns;
- report downloads work for an authenticated authorized user;
- unsupported real-time questions request clarification or explain the data
  limitation; and
- stored learning memory never forces an older student such as `S099`.

## Milestone 2: Finish the V30 frontend

The normal interface should expose:

```text
Chat
Files
Results
Run system check — Administrator only
```

Required cleanup:

- keep one reusable student/result table component;
- keep one authenticated report-download function;
- remove duplicate rendering and request helpers;
- remove obsolete debug controls and unnecessary right-panel actions;
- keep training, reindexing, repair actions, and traces inside Administrator-only
  Advanced maintenance;
- do not render system controls or technical traces for Students or Advisors;
- provide clear loading, empty, success, permission-denied, and error states; and
- split the current monolithic application component into maintainable,
  role-aware components.

## Milestone 3: Add real data management

Administrator workflows must support:

- CSV and Excel upload;
- import preview;
- source-to-database column mapping;
- required-field and data-type validation;
- duplicate-student detection;
- explicit confirmation before import;
- transactional failure handling and rollback;
- synchronization verification across MongoDB and PostgreSQL;
- add, edit, and deactivate workflows for students, advisors, and
  administrators;
- Administrator password reset; and
- an audit event for every data or account change.

Document upload is not the same as importing university master data. These must
remain separate, clearly labeled workflows.

## Milestone 4: Complete automated AI evaluation

Create a fixed, version-controlled benchmark covering:

- profiles, GPA, grades, attendance, advisors, rankings, and counts;
- program and subject filters;
- document and selected-file questions;
- record-table and PDF-report output;
- English and Thai requests;
- common typos;
- follow-ups such as `their GPA`;
- unsupported and real-time requests; and
- permission-denied and cross-scope attempts.

Critical failures must fail the release gate. Benchmark data must be synthetic
and deterministic.

## Milestone 5: Remove legacy code safely

Only after Milestones 1–4 pass:

- prove which planners, routers, entity extractors, endpoints, scripts, and
  startup paths are still imported or called;
- move uncertain legacy modules behind an explicitly disabled boundary;
- remove confirmed-unused modules and endpoints;
- remove obsolete V28/V29 migration and demo-login paths;
- reduce the project to one supported startup method; and
- pin every Python and npm dependency.

Never remove a legacy file solely because its name is old. Remove it only after
tests and import/call-site searches prove it is unused.

## Milestone 6: Build role dashboards

### Administrator

- total students and program distribution
- GPA trends and at-risk students
- attendance warnings
- finance and scholarship status
- reports and audit history

### Advisor

- assigned students only
- grades and attendance
- advisor notes and assigned documents
- risk warnings

### Student

- own profile only
- courses, grades, and attendance
- own documents and academic status

Dashboard APIs must enforce the same server-side scopes as chat.

## Milestone 7: Production readiness

Before deployment, V30 requires:

- a real domain and HTTPS;
- unique production secrets;
- database backups and a tested restore procedure;
- monitoring, error alerts, and log rotation;
- rate-limit tuning;
- PDPA retention, export, and deletion rules;
- account lockout and recovery;
- CI build, test, and deployment stages;
- deployment and operations documentation; and
- role-by-role security and authorization testing.

## Required order

```text
1. Preserve the current V30 snapshot
2. Start and verify the existing Docker stack
3. Harden the authoritative V30 chat path
4. Run live reliability and permission tests
5. Finish the V30 frontend cleanup
6. Build data import and management
7. Add the complete automated AI benchmark
8. Remove proven-unused legacy code
9. Build role dashboards
10. Run production security and recovery tests
11. Package and deploy one complete V30 release
```

## Definition of done

V30 is complete only when:

- a clean machine can start it using the documented method;
- all required containers become healthy;
- all deterministic tests, frontend builds, live acceptance prompts, and
  permission tests pass;
- the 1,000-record synthetic dataset remains synchronized;
- no normal chat request is redirected by stale learning memory;
- every role sees only authorized data and controls;
- reports download through authenticated requests;
- import failures can be rolled back;
- backup restoration has been demonstrated; and
- the release contains no instruction to install V31 or another missing package.
