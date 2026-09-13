"""PostgreSQL persistence for staged master-data import batches."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Sequence

from psycopg2.extras import Json, execute_batch

from app.db.postgres import get_connection


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _public_batch(row: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not row:
        return None
    result = json_safe(dict(row))
    result["import_id"] = str(result["import_id"])
    return result


def create_batch(
    *, import_id: str, filename: str, actor_admin_id: str, source_columns: Sequence[str],
    column_mapping: Dict[str, str], summary: Dict[str, Any], records: Sequence[Dict[str, Any]],
    row_issues: Sequence[Sequence[Dict[str, str]]],
) -> Dict[str, Any]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO master_import_batches(
                    import_id, import_type, filename, actor_admin_id, status,
                    source_columns, column_mapping, validation_summary, row_count
                ) VALUES (%s, 'student_master', %s, %s, 'staged', %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    import_id, filename[:255], actor_admin_id[:80], Json(list(source_columns)),
                    Json(column_mapping), Json(summary), len(records),
                ),
            )
            batch = cur.fetchone()
            execute_batch(
                cur,
                """
                INSERT INTO master_import_rows(import_id, row_number, canonical_data, issues)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (import_id, number, Json(json_safe(record)), Json(list(issues)))
                    for number, (record, issues) in enumerate(zip(records, row_issues), start=2)
                ],
                page_size=500,
            )
        conn.commit()
        return _public_batch(batch) or {}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_batches(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT import_id, import_type, filename, actor_admin_id, status,
                       validation_summary, row_count, inserted_count, updated_count,
                       created_at, confirmed_at, rolled_back_at, failure_detail
                FROM master_import_batches
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (max(1, min(int(limit), 100)),),
            )
            return [_public_batch(row) or {} for row in cur.fetchall()]
    finally:
        conn.close()


def get_batch(import_id: str, *, preview_limit: int = 50, include_all_rows: bool = False) -> Dict[str, Any] | None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM master_import_batches WHERE import_id = %s", (import_id,))
            batch = cur.fetchone()
            if not batch:
                return None
            sql = """
                SELECT row_number, canonical_data, issues
                FROM master_import_rows WHERE import_id = %s ORDER BY row_number
            """
            params: tuple[Any, ...] = (import_id,)
            if not include_all_rows:
                sql += " LIMIT %s"
                params += (max(1, min(int(preview_limit), 200)),)
            cur.execute(sql, params)
            rows = [json_safe(dict(row)) for row in cur.fetchall()]
            result = _public_batch(batch) or {}
            result["rows"] = rows
            result["preview_truncated"] = not include_all_rows and int(result.get("row_count") or 0) > len(rows)
            return result
    finally:
        conn.close()


def get_records(import_id: str) -> List[Dict[str, Any]]:
    batch = get_batch(import_id, include_all_rows=True)
    return [dict(row.get("canonical_data") or {}) for row in (batch or {}).get("rows", [])]


def save_snapshots(import_id: str, snapshots: Iterable[Dict[str, Any]]) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            execute_batch(
                cur,
                """
                INSERT INTO master_import_snapshots(
                    import_id, student_id, postgres_existed, postgres_record, mongo_existed, mongo_record
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (import_id, student_id) DO NOTHING
                """,
                [
                    (
                        import_id, item["student_id"], bool(item.get("postgres_record")),
                        Json(json_safe(item.get("postgres_record"))) if item.get("postgres_record") else None,
                        bool(item.get("mongo_record")),
                        Json(json_safe(item.get("mongo_record"))) if item.get("mongo_record") else None,
                    )
                    for item in snapshots
                ],
                page_size=500,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_snapshots(import_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM master_import_snapshots WHERE import_id = %s ORDER BY student_id",
                (import_id,),
            )
            return [json_safe(dict(row)) for row in cur.fetchall()]
    finally:
        conn.close()


def update_status(import_id: str, status: str, **changes: Any) -> Dict[str, Any]:
    allowed = {"inserted_count", "updated_count", "failure_detail"}
    assignments = ["status = %s"]
    params: List[Any] = [status]
    for key, value in changes.items():
        if key in allowed:
            assignments.append(f"{key} = %s")
            params.append(value)
    if status == "committed":
        assignments.append("confirmed_at = CURRENT_TIMESTAMP")
    if status == "rolled_back":
        assignments.append("rolled_back_at = CURRENT_TIMESTAMP")
    params.append(import_id)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE master_import_batches SET {', '.join(assignments)} WHERE import_id = %s RETURNING *",
                tuple(params),
            )
            row = cur.fetchone()
            if not row:
                raise KeyError("Import batch was not found.")
        conn.commit()
        return _public_batch(row) or {}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def transition_status(import_id: str, *, expected: str, status: str) -> Dict[str, Any]:
    """Atomically claim a batch so duplicate confirm/rollback requests cannot race."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE master_import_batches SET status = %s
                WHERE import_id = %s AND status = %s
                RETURNING *
                """,
                (status, import_id, expected),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Import batch is no longer {expected}; refresh its status before trying again.")
        conn.commit()
        return _public_batch(row) or {}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_incomplete_batches() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM master_import_batches WHERE status IN ('applying', 'rolling_back') ORDER BY created_at"
            )
            return [_public_batch(row) or {} for row in cur.fetchall()]
    finally:
        conn.close()
