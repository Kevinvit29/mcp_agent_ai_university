# V30 Release Status

V30 is the only active release. There is no V31 download, overlay, or second
backend.

## Completed local release

Verified on 2026-08-17:

- all five Docker services build and become healthy;
- the backend dependency graph and MCP/database-agent graph are fully pinned;
- the frontend production build completes with zero npm vulnerabilities;
- all 145 backend regression tests pass;
- the academic live gate passes 19/19 cases;
- the random English/Thai/typo/privacy gate passes 28/28 cases;
- Admin, Advisor, Lecturer, and Student signed-role checks pass;
- forged browser identities are ignored and cross-role routes return 403;
- document retrieval uses a separate query type for each role; and
- the automatic read-only application check passes 5/5.

Use one command for every release candidate:

```bash
python3 scripts/v30_control.py release
```

## Deployment-owner work

The local V30 application is complete. A public production deployment still
requires environment-specific ownership decisions that cannot be stored in the
repository:

1. connect the repository to the intended Git account and CI environment;
2. configure a real domain, HTTPS reverse proxy/WAF, and explicit CORS origins;
3. replace every demo/default secret and disable legacy demo passwords;
4. set backup storage, retention, monitoring, alerting, and log rotation;
5. approve PDPA retention/export/deletion policy; and
6. demonstrate restoration into an isolated deployment before accepting real
   university data.

These are deployment controls, not another application version.
