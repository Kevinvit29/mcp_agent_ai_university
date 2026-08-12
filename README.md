# University AI V30 — One Project Guide

V30 is the only active version. Do not download, install, or overlay a V31
package. All changes are made directly in this project.

This README is the authoritative guide for starting, checking, debugging, and
continuing development. Files under `docs/archive_notes` are historical context,
not current instructions.

## The easiest way to run V30

Start Docker Desktop first and wait until the Docker engine is running.

### macOS or Linux

```bash
python3 scripts/v30_control.py start
```

### Windows

Double-click `START_V30.bat`.

Then open `http://localhost:3100`.

Demo identities:

```text
Administrator: ADMIN
Student:       S001
Advisor:       A001
```

The Administrator password is stored in PostgreSQL after the first account is
created. Changing `.env` later does not change it. Use
`RECOVER_ADMIN_V30.bat` on Windows if that password must be reset.

## One control command

On macOS/Linux, use this script instead of remembering Docker commands:

```bash
python3 scripts/v30_control.py start
python3 scripts/v30_control.py status
python3 scripts/v30_control.py check
python3 scripts/v30_control.py doctor
python3 scripts/v30_control.py logs
python3 scripts/v30_control.py restart
python3 scripts/v30_control.py stop
python3 scripts/v30_control.py release
python3 scripts/v30_control.py backup
python3 scripts/v30_control.py verify-backup backups/university-ai-TIMESTAMP.tar.gz
```

- `start` builds V30, starts it, waits for all services, and checks the dataset.
- `status` shows exactly which of the five services is healthy.
- `check` verifies services, synchronized data, routing tests, and database access.
- `doctor` runs the checks and shows useful logs if something fails.
- `restart` recreates containers while preserving database volumes.
- `stop` stops containers without deleting them.
- `release` rebuilds the exact source and runs compile, regression, frontend,
  service, dataset, AI-routing, end-to-end, and live database gates.
- `backup` creates checksummed MongoDB and PostgreSQL archives.
- `verify-backup` validates an archive without changing either database.

Never run `docker compose down -v`. The `-v` option deletes database volumes.

## What “5/5 services” means

V30 has exactly five Docker Compose services:

| Service | Purpose | Healthy when |
|---|---|---|
| `postgres` | accounts, sessions, documents, permissions, and operational tables | PostgreSQL accepts connections |
| `mongo` | authoritative student and advisor records | MongoDB accepts authenticated pings |
| `mcp_server` | policy-controlled database and document tools | MCP can reach its dependencies |
| `backend` | authentication, chat, reports, evaluation, and API | backend readiness passes |
| `frontend` | browser interface and authenticated downloads | backend is healthy and nginx is running |

The Administrator **Run system check** button also displays five checks, but
those are application checks—not the five containers:

1. Runtime health
2. Data consistency
3. AI routing quality
4. End-to-end flow
5. Live database connection

If Docker reports 5/5 but the app reports 4/5, run:

```bash
python3 scripts/v30_control.py check
```

It prints the exact failed application check.

## Database source-of-truth rules

- MongoDB `students` is authoritative for student population, profiles, GPA,
  grades, program membership, and academic status.
- MongoDB `advisors` is authoritative for advisor records.
- PostgreSQL stores Administrator accounts, sessions, documents, audit events,
  enrollment relationships, and supporting operational data.
- PostgreSQL relationship-row counts must never be reported as the university
  student count.
- Browser data access goes through the backend and MCP policy gateway.

The development dataset should contain 1,000 fictional students in the required
synchronized stores. Verify it with `python3 scripts/v30_control.py check`.

## Authorized Agent AI data flow

The AI agent organizes and retrieves university information through this fixed
chain:

```text
Signed user identity
  → latest-message purpose contract
  → deterministic registered-tool plan
  → internal MCP service-key gateway
  → role row scope and field minimization
  → authoritative database query
  → result-domain validation
  → grounded answer
```

- AI interpretation can suggest intent, but it cannot expand access.
- Student access is forced to the signed student's own record.
- Advisor access is forced to assigned students and subjects that advisor teaches.
- Administrator access is limited to registered administrative operations.
- Unreviewed tools and PostgreSQL query types are denied by default.
- Advisor counts are calculated after advisor assignment scope is applied.
- MongoDB `students` and `advisors` remain canonical master data.
- PostgreSQL relationship rows are never presented as the student population.
- Database facts remain deterministic; the model cannot rewrite them into
  unsupported facts.
- “Top/recommended subjects” is ranked by distinct enrolled-student count in
  the signed user's allowed scope. It is labelled as popularity, not a
  personalized prerequisite/interest recommendation.

The planner-facing registry is `backend/app/agent/schema_registry.py`. The
executing access guard is `mcp_server/app/policy.py`; database tools must not
bypass it.

## Reliable-answer rules

- The latest message wins over old conversation context.
- The latest student ID, name, or surname wins.
- Saved learning memory cannot replace normal chat routing.
- Database answers are formatted from validated tool results.
- Database-answer AI rewriting is disabled by default.
- Count questions return count answers, not record dumps.
- `list students as a table` returns records.
- `show columns in the student table` returns schema.
- Report downloads use authenticated requests.
- Unsupported real-time activity/location questions explain the limitation.
- Students and Advisors cannot open technical traces or Administrator controls.

Normal general chat may still use the configured AI provider. University
database facts do not need a second AI rewrite.

## Required acceptance questions

Sign in as Administrator and test:

```text
student S099 profile
gpa of boonmee
gpa of aksornchai
how many students study Business Analytics
list students as a table
create a PDF report for Business Analytics students
show columns in the student table
rank me top 5 subject that recommended
what is the Boonmee family doing right now
```

Expected:

- no old `S099` appears after a newer surname request;
- surname questions use the requested surname;
- the Business Analytics question returns only the matching count;
- the table request shows student rows;
- the schema request shows table/column information;
- the subject request returns a top-five popularity ranking, not a search for a
  subject named `recommended` and not a highest-GPA answer;
- the report downloads while signed in;
- the real-time question does not invent current activity.

## When an answer looks wrong

1. Copy the exact question.
2. Start a new chat session.
3. Run `python3 scripts/v30_control.py check`.
4. If it fails, run `python3 scripts/v30_control.py doctor`.
5. Re-test the exact question.
6. Administrator users may inspect the technical trace.

Do not train the router or add a learning-memory rule to hide a deterministic
planner bug. Fix the contract, planner, validator, or formatter and add a
regression test.

## Active code map

| Area | Current file |
|---|---|
| FastAPI application assembly and chat | `backend/app/main.py` |
| Admin role folder | `backend/app/roles/admin/` |
| Advisor role folder | `backend/app/roles/advisor/` |
| Student role folder | `backend/app/roles/student/` |
| Signed role dependency | `backend/app/dependencies.py` |
| Admin routes and database interface | `backend/app/roles/admin/router.py`, `repository.py` |
| Advisor routes and database interface | `backend/app/roles/advisor/router.py`, `repository.py` |
| Student routes and read-only database interface | `backend/app/roles/student/router.py`, `repository.py` |
| Authoritative chat orchestration | `backend/app/agent/agent_orchestrator.py` |
| Latest-message contract | `backend/app/agent/purpose_contract.py` |
| Normalized academic query parser | `backend/app/agent/academic_query.py` |
| Brain/data source and role map | `docs/current/V30_BRAIN_ARCHITECTURE.md` |
| Canonical entity extraction | `backend/app/agent/entity_extractor.py` |
| Purpose-to-tool planning | `backend/app/agent/contextual_tool_planner.py` |
| Result validation | `backend/app/agent/result_validator.py` |
| Deterministic answers | `backend/app/agent/final_answer_writer.py` |
| MCP access policy | `mcp_server/app/policy.py` |
| MongoDB tools | `mcp_server/app/tools/mongo_tool.py` |
| PostgreSQL tools | `mcp_server/app/tools/postgres_tool.py` |
| Frontend | `frontend/src/App.jsx` |
| Shared result table | `frontend/src/components/WorkspaceDataTable.jsx` |
| Public runtime routes | `backend/app/routers/health.py` |
| Docker stack | `docker-compose.yml` |
| Unified local control | `scripts/v30_control.py` |
| V30 regression tests | `tests/test_v30_authoritative_chat.py` |
| Academic brain regression tests | `tests/test_v30_academic_brain.py` |
| V30 prompt benchmark | `backend/app/agent/evaluation_cases.json` |
| Live academic brain gate | `backend/app/agent/academic_brain_gate.py` |

Compatibility modules may remain temporarily when older code imports them.
New work must use the current files in this table.

## Safe development workflow

Before changing behavior:

```bash
python3 scripts/v30_control.py check
```

After backend changes:

```bash
python3 -m compileall -q backend/app mcp_server/app
python3 -m unittest discover -s tests -p 'test_v30_*.py' -v
```

For normalized academic routing, policy, retrieval, validation, and grounded
answers against the live databases:

```bash
docker compose exec -T backend python -m app.agent.academic_brain_gate
```

After frontend or dependency changes:

```bash
python3 scripts/v30_control.py restart
```

Then run the acceptance questions again.

## Git with your other account

This folder is now a local Git repository on branch `main`. It has no remote and
no repository-specific name/email, so it is not connected to the wrong account.
`.env`, backups, Python environments, caches, frontend dependencies, and
generated output are ignored.

After creating an empty repository in the account you want to use, configure
only this project:

```bash
git config --local user.name "YOUR OTHER ACCOUNT NAME"
git config --local user.email "YOUR OTHER ACCOUNT EMAIL"
git remote add origin YOUR_OTHER_ACCOUNT_REPOSITORY_URL
git add .
git commit -m "V30 working foundation"
git push -u origin main
```

Do not use `git config --global` if this computer also uses another Git account.
Review `git status` before the first commit; `.env` must not appear.

## Cleanup direction

Do not combine the backend or frontend into a larger source file. The current
`backend/app/main.py` and `frontend/src/App.jsx` are already too large. The safe
cleanup direction is:

1. keep one public `/chat` route and one authoritative chat service;
2. keep Admin, Advisor, and Student code inside their own `backend/app/roles/`
   folders; keep public runtime endpoints in their separate router;
3. continue splitting the frontend into Chat, Files, Results, and Administrator System
   components;
4. keep one table renderer and one authenticated report downloader;
5. move old notes to `docs/archive_notes`;
6. remove compatibility modules only after repository search and tests prove
   they are unused; the duplicate entity-extractor compatibility file has
   already been removed.

This follows the documented patterns for maintainable applications:

- [FastAPI: Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [Docker: Control startup order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Docker Compose health checks](https://docs.docker.com/compose/gettingstarted/)
- [Vite environment variables](https://vite.dev/guide/env-and-mode)

## Remaining project order

1. Keep the five services and five application checks stable.
2. Complete the chat benchmark in English and Thai.
3. Continue splitting large backend and frontend files without changing behavior.
4. Build master-data import, preview, validation, duplicate detection,
   confirmation, synchronization, and rollback.
5. Add Administrator, Advisor, and Student dashboards.
6. Run role-by-role security tests.
7. Test backup restoration.
8. Package and deploy the final V30 release.

The detailed definition remains in
`docs/current/V30_COMPLETION_DEFINITION.md`.
