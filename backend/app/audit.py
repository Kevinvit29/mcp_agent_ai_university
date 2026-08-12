"""Minimal, privacy-preserving audit log writer.

Audit rows contain actor, action, status and request metadata only. They never
store chat contents, document text, password values, access tokens, or query
strings.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from app.production_security import hash_for_audit


def _enabled() -> bool:
    return (os.getenv("AUDIT_LOGGING_ENABLED") or "true").strip().lower() == "true"


def write_audit_event(
    *,
    request_id: str,
    actor_role: Optional[str],
    actor_id: Optional[str],
    action: str,
    outcome: str,
    status_code: int,
    client_ip: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    if not _enabled():
        return
    try:
        from app.db.postgres import get_connection
        safe_metadata = {
            "method": str((metadata or {}).get("method") or ""),
            "path": str((metadata or {}).get("path") or "")[:255],
            "duration_ms": int((metadata or {}).get("duration_ms") or 0),
            "rate_bucket": str((metadata or {}).get("rate_bucket") or "")[:60],
            "error_code": str((metadata or {}).get("error_code") or "")[:80],
        }
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_logs (
                        request_id, actor_role, actor_id, action, outcome,
                        status_code, client_ip_hash, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request_id[:80],
                        (actor_role or "anonymous")[:30],
                        (actor_id or "anonymous")[:80],
                        action[:255],
                        outcome[:30],
                        int(status_code),
                        hash_for_audit(client_ip),
                        Json(safe_metadata),
                    ),
                )
                conn.commit()
        finally:
            conn.close()
    except Exception:
        # Audit availability must never expose internals or interrupt a student
        # request. Readiness and deployment monitoring surface DB failures.
        return


def list_audit_events(limit: int = 100, action_prefix: Optional[str] = None) -> List[Dict[str, Any]]:
    from app.db.postgres import get_connection
    limit = min(max(int(limit), 1), 500)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if action_prefix:
                cur.execute(
                    """
                    SELECT request_id, actor_role, actor_id, action, outcome,
                           status_code, client_ip_hash, metadata, created_at
                    FROM audit_logs
                    WHERE action LIKE %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (f"{action_prefix[:180]}%", limit),
                )
            else:
                cur.execute(
                    """
                    SELECT request_id, actor_role, actor_id, action, outcome,
                           status_code, client_ip_hash, metadata, created_at
                    FROM audit_logs
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
            return [
                {
                    **dict(row),
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                }
                for row in rows
            ]
    finally:
        conn.close()
