# V30 — Clean Foundation & Dataset Integrity

## Purpose

V30 consolidates prior fixes into one predictable local-demo lifecycle rather than requiring manual `.env`, SQL, and container commands.

## Non-negotiable behavior

1. **Administrator identity**
   - `admin_accounts` in PostgreSQL is the only normal login source.
   - Only the first development startup can bootstrap `ADMIN/admin123`.
   - Later `.env` changes do not override an existing admin password.
   - `RECOVER_ADMIN_V30.bat` is the sole local break-glass recovery route.

2. **One demo dataset**
   - V30 does not ship a competing 100-row MongoDB seed.
   - `app.system_bootstrap --ensure-synthetic` creates exactly 1,000 fictional profiles in both stores.
   - It verifies:
     - `student_profiles = 1000`;
     - MongoDB `students = 1000`;
     - each is tagged `synthetic_demo_v30`.
   - It refuses to replace unrecognised data or any production dataset.

3. **Counts versus list pages**
   - A `COUNT(*)` / `count_documents()` answer is a database total.
   - A result page is a capped preview and must say how many are shown.
   - V30 tests reject code paths that can confuse a 100-row display cap with a total count.

4. **Startup**
   - `START_V30.bat` selects a free port from 3100 upward.
   - The backend command first runs the idempotent migration and dataset integrity bootstrap.
   - Reports and document PDFs use the frontend proxy, not port 8000.

5. **Training**
   - The local `MLPClassifier` classifies intent only.
   - It has no authority to bypass role, PDPA, or MCP policy checks.
   - It does not fine-tune Gemini/OpenAI and never uses raw student records as training examples.
   - Approved corrections are the only user-generated examples permitted into training.

## Fresh local-demo lifecycle

`START_V30.bat` creates `.env` from the template when no prior local file exists, starts Docker, and verifies counts. The new demo `.env` contains local-only default credentials. It is not a production configuration.

## Upgrade lifecycle

V30 keeps the V29 named volume defaults:
- `university_ai_mongo_data`
- `university_ai_postgres_data`
- `university_ai_reports`
- `university_ai_document_views`

The start script may copy compatible connection settings from the most recent adjacent V29 folder. PostgreSQL retains the existing Admin account and password hash. No command in the normal flow removes a volume.

## Manual CLI equivalents

```powershell
docker compose up -d --build
docker compose exec -T backend python -m app.system_bootstrap --status
docker compose exec -it backend python -m app.admin_recovery --username ADMIN --reset-password --confirm-local-recovery
```

`START_V30.bat` and `RECOVER_ADMIN_V30.bat` are preferred because they choose the correct local port and show the relevant diagnostics.

## Production boundary

Set all of the following before a real deployment:

```env
APP_ENV=production
DEMO_DATA_MODE=false
AUTO_SEED_SYNTHETIC_DATA=false
ALLOW_LEGACY_DEMO_PASSWORDS=false
```

Configure real secrets, a secure identity provider or password-hash migration, HTTPS, backups, monitoring, and an external reverse proxy. Never publish MongoDB, PostgreSQL, MCP, or the backend port directly.
