# V30 Deployment Runbook

## Supported commands

Run commands from the project root:

```bash
python3 scripts/v30_control.py release
python3 scripts/v30_control.py check
python3 scripts/v30_control.py logs backend
python3 scripts/v30_control.py backup
python3 scripts/v30_control.py stop
```

`release` is the single build-and-validation path. It builds the locked backend,
frontend, and database-agent images; starts the five services without deleting
volumes; and runs regression, live-answer, role-security, and database checks.

If the persisted Administrator password differs from `.env`, provide it only to
the release process:

```bash
V30_RELEASE_ADMIN_PASSWORD='current-password' python3 scripts/v30_control.py release
```

Never commit that value. Never use `docker compose down -v` during normal
operations because it deletes persistent university data.

## Before public deployment

- Set unique production secrets and `ALLOW_LEGACY_DEMO_PASSWORDS=false`.
- Put the frontend behind HTTPS and an edge/WAF; set explicit CORS origins.
- Store backups outside the Docker host and verify each archive.
- Restore the newest archive into an isolated deployment and run `check`.
- Configure uptime/error alerts, log rotation, rate limits, and PDPA retention.
- Treat logs, backups, audit records, and uploaded documents as sensitive data.

Signed session claims define Student, Advisor, Lecturer, and Administrator
scope. The browser cannot expand that scope, and the MCP gateway remains the
final database-field policy boundary.
