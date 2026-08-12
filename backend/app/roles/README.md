# V30 Role Folders

Each signed user role owns one small package:

```text
roles/
├── admin/
│   ├── router.py       # Admin accounts, global documents, dataset status
│   └── repository.py   # Admin-only PostgreSQL operations
├── advisor/
│   ├── router.py       # Taught subjects and advisor-owned documents
│   └── repository.py   # Advisor-scoped PostgreSQL operations
└── student/
    ├── router.py       # Own subjects and accessible advisor documents
    └── repository.py   # Read-only student PostgreSQL operations
```

Rules:

- `router.py` owns HTTP validation and signed-role checks.
- `repository.py` exposes only database operations allowed for that role.
- Shared physical database code remains in `app/db/postgres.py`.
- AI database access still passes through the MCP policy gateway.
- Student repository code must remain read-only.
