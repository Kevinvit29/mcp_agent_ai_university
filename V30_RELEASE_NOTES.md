# V30 — Clean Foundation Release Notes

## What this release fixes

- **One normal Windows startup:** run `START_V30.bat`. It selects a free local web port, preserves named Docker volumes, starts the correct release, waits for health checks, and prints the real database status.
- **No competing demo datasets:** MongoDB initialization no longer creates an older 100-student sample. V30 is the only owner of the fictional demo dataset.
- **Verified 1,000-record synthetic dataset:** in development mode, V30 creates and verifies exactly 1,000 fictional students in both MongoDB and PostgreSQL before the application is marked ready.
- **Database-backed Admin accounts:** Administrator usernames and PBKDF2 password hashes remain in PostgreSQL. Environment values can bootstrap the first local account only; they never override an existing account.
- **One-click Admin recovery:** run `RECOVER_ADMIN_V30.bat` only when a database Admin password needs to be changed. It does not use raw SQL or reset application data.
- **Correct counts:** "How many students?" must use a database total. "Show students" is a paginated list and must not be reported as the total count.
- **Report links through the app:** browser report links use the frontend/Nginx route rather than exposing private backend port 8000.
- **Safer production boundary:** production blocks automatic synthetic seeding, demo mode, and the default bootstrap password.

## Scope and safety

The 1,000 records are fictional synthetic data for local demonstrations and test workflows. V30 does not train Gemini/OpenAI on student data. Its local MLP router is trained only from curated and administrator-approved intent examples; permissions and database policies remain authoritative.

## Start

1. Extract the release beside the older project folders.
2. Double-click `START_V30.bat`.
3. Read the opening console summary. It shows the exact local URL and confirms whether 1,000/1,000 records are synchronized.
4. Fresh local demo accounts:
   - Student: `S001` / `demo1234`
   - Advisor: `A001` / `demo1234`
   - Admin: `ADMIN` / `admin123` only for a fresh V30 database. Existing database administrators keep their database password.

Never use `docker compose down -v` unless you explicitly intend to remove all local Docker database volumes.
