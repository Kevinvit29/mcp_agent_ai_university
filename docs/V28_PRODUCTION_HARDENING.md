# V28 — Production Hardening

## What this release enforces

- A signed login token is the authority for role and account ownership. Browser query/form/JSON values for `user_role`, `requester_student_id`, and `requester_advisor_id` are replaced by verified token claims before a chat plan or database call.
- MCP is an internal service protected by `X-MCP-Service-Key`; Docker no longer publishes MongoDB, PostgreSQL, MCP, or backend ports in the production compose file.
- Per-instance rate limits cover login, chat, uploads, admin writes, and general API calls. Put a WAF/reverse-proxy limit in front of multi-replica production deployments.
- Audit logs store actor, route, outcome, status, request ID, hashed client IP, and duration. They do **not** store chat content, documents, passwords, tokens, raw query strings, or private database values.
- Liveness (`/api/health/live`) and readiness (`/api/health/ready`) checks support monitoring. Readiness confirms PostgreSQL, MongoDB, and MCP reachability without exposing connection details.
- Docker service health checks, restart policies, private service networking, non-privilege-escalation flags, CI, backup verification, and a guarded restore workflow are included.

## Required deployment configuration

1. Copy `.env.example` to `.env` and generate different long random values for `APP_SECRET_KEY`, `MCP_INTERNAL_KEY`, database passwords, and `ADMIN_PASSWORD`.
2. Set `APP_ENV=production`.
3. Set `CORS_ALLOWED_ORIGINS` to the exact HTTPS browser origin, for example `https://ai.example.edu`.
4. Set `ALLOW_LEGACY_DEMO_PASSWORDS=false`. Student and advisor records then require a `password_hash` created by `scripts/generate_password_hash.py`, or a proper external identity-provider implementation.
5. Store `.env` in a secret manager or protected server path. It is intentionally excluded from this release ZIP and Git.

## Start and verify

```bash
cp .env.example .env
# edit .env — use real secrets, then set APP_ENV=production
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:3000/api/health/ready
```

The bundled frontend listens on `127.0.0.1:3000`. Put an HTTPS reverse proxy/load balancer in front of it for public access. Do not publish Docker database ports or the MCP port on the internet. For local database troubleshooting only, use:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

## Monitoring and incident response

Monitor readiness, container restart count, disk capacity for Docker volumes/backups, HTTP 5xx rate, 401/403 anomalies, 429 rate-limit events, and MCP/database latency. Use request IDs from browser errors to find a matching operational audit row and container log entry. The admin route `GET /admin/audit-logs` shows safe operational events only.

If readiness is red, do not expose the application to users. Check `docker compose ps`, then inspect the failing service with `docker compose logs --tail=200 <service>`. Do not paste secrets, tokens, full student records, or full document content into support tickets.

## Backup and restore drill

```bash
./scripts/backup.sh
./scripts/verify_backup.sh backups/university-ai-YYYYMMDDTHHMMSSZ.tar.gz
# First test on an isolated staging instance:
CONFIRM_RESTORE=YES ./scripts/restore.sh backups/university-ai-YYYYMMDDTHHMMSSZ.tar.gz
```

`restore.sh` is destructive and rejects a direct production restore unless `ALLOW_PRODUCTION_RESTORE=YES` is deliberately set during an approved incident. After restoring, verify `/api/health/ready`, run the admin live smoke gate, and document the incident.

## Release checklist

1. CI workflow **Release Gate** is green.
2. `./scripts/release_gate.sh` passes locally.
3. Authenticated admin quality gate, end-to-end gate, live smoke gate, and production gate pass.
4. A fresh backup has passed `verify_backup.sh`; a restore drill has been tested on staging.
5. Production secrets, HTTPS, external rate limiting, monitoring alerts, and database retention policies are reviewed by the deployment owner.
