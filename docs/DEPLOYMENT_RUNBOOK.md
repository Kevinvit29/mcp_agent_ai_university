# Deployment Runbook

Use this runbook with `docs/V28_PRODUCTION_HARDENING.md`.

- **Normal start:** `docker compose up -d --build`; verify `docker compose ps` and `/api/health/ready` through the frontend proxy.
- **Normal stop:** `docker compose down` keeps data volumes. Never use `docker compose down -v` unless a documented recovery procedure authorizes deletion of all persistent data.
- **Safe logs:** `docker compose logs --tail=200 backend` or `mcp_server`. Treat logs as sensitive operational data.
- **Token expiry:** users sign in again; the default token lifetime is eight hours and can be adjusted with `ACCESS_TOKEN_TTL_SECONDS` (5 minutes–24 hours).
- **Scale-out:** the built-in rate limiter is per backend container. Use an edge/WAF or shared Redis limiter before running more than one backend replica.
- **Privacy:** students and advisors use signed claims; MCP remains the final PDPA/data-field guard. Never bypass the MCP gateway with direct database access from the LLM.
