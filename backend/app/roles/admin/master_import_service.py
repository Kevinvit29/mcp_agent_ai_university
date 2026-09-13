"""Admin-only staged import and synchronized rollback for student master data."""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from pymongo import DeleteOne, MongoClient, ReplaceOne, UpdateOne
from psycopg2.extras import execute_batch

from app.db.postgres import get_connection
from app.roles.admin import master_import_repository as repository
from app.roles.admin.master_import_models import ImportValidationError, ParsedImport, parse_student_master


MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB = os.getenv("MONGO_DB", "university_mongo")

POSTGRES_FIELDS: Sequence[str] = (
    "full_name", "thai_name", "program_code", "program_name", "faculty", "email", "phone",
    "admission_type", "year_level", "entry_year", "expected_graduation_year", "academic_status",
    "gpa", "credits_earned", "credits_required", "attendance_rate", "risk_level",
    "scholarship_status", "campus",
)
MONGO_FIELD_MAP = {
    "full_name": "name",
    "thai_name": "name_th",
    "program_name": "program",
}


class ImportStateError(ValueError):
    """Raised when confirmation/rollback is unsafe for a batch state."""


def _mongo_client() -> MongoClient:
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=10_000)


def _postgres_records(student_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    if not student_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM student_profiles WHERE student_id = ANY(%s)", (list(student_ids),))
            return {str(row["student_id"]): dict(row) for row in cur.fetchall()}
    finally:
        conn.close()


def _mongo_records(student_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    if not student_ids:
        return {}
    client = _mongo_client()
    try:
        rows = client[MONGO_DB].students.find({"student_id": {"$in": list(student_ids)}}, {"_id": 0})
        return {str(row["student_id"]): dict(row) for row in rows}
    finally:
        client.close()


def _attach_database_conflicts(parsed: ParsedImport) -> ParsedImport:
    student_ids = [str(record.get("student_id") or "") for record in parsed.records if record.get("student_id")]
    postgres_rows = _postgres_records(student_ids)
    mongo_rows = _mongo_records(student_ids)
    issues = [list(row) for row in parsed.row_issues]
    existing = 0
    inconsistent = 0
    for index, record in enumerate(parsed.records):
        student_id = str(record.get("student_id") or "")
        in_postgres, in_mongo = student_id in postgres_rows, student_id in mongo_rows
        if in_postgres or in_mongo:
            existing += 1
            issues[index].append({
                "severity": "warning", "field": "student_id", "code": "existing_student",
                "message": "This student already exists and will be updated only after explicit confirmation.",
            })
        if in_postgres != in_mongo:
            inconsistent += 1
            issues[index].append({
                "severity": "warning", "field": "student_id", "code": "store_mismatch",
                "message": "This ID exists in only one database; confirmation will repair the missing copy.",
            })
    summary = dict(parsed.summary)
    summary.update({
        "existing_student_count": existing,
        "new_student_count": len(parsed.records) - existing,
        "cross_database_mismatch_count": inconsistent,
        "warning_count": sum(1 for row in issues for issue in row if issue["severity"] == "warning"),
    })
    return ParsedImport(parsed.source_columns, parsed.column_mapping, parsed.records, issues, summary)


def create_preview(
    *, raw: bytes, filename: str, actor_admin_id: str, mapping: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    parsed = _attach_database_conflicts(parse_student_master(raw, filename, mapping))
    import_id = str(uuid.uuid4())
    repository.create_batch(
        import_id=import_id,
        filename=filename,
        actor_admin_id=actor_admin_id,
        source_columns=parsed.source_columns,
        column_mapping=parsed.column_mapping,
        summary=parsed.summary,
        records=parsed.records,
        row_issues=parsed.row_issues,
    )
    return repository.get_batch(import_id) or {}


def _snapshots(import_id: str, records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ids = [str(record["student_id"]) for record in records]
    pg = _postgres_records(ids)
    mongo = _mongo_records(ids)
    return [
        {"student_id": student_id, "postgres_record": pg.get(student_id), "mongo_record": mongo.get(student_id)}
        for student_id in ids
    ]


def _postgres_upsert(conn: Any, records: Sequence[Dict[str, Any]], import_id: str) -> None:
    columns = ", ".join(POSTGRES_FIELDS)
    placeholders = ", ".join(["%s"] * (len(POSTGRES_FIELDS) + 3))
    updates = []
    required = {"full_name", "program_code", "program_name"}
    for field in POSTGRES_FIELDS:
        if field in required:
            updates.append(f"{field} = EXCLUDED.{field}")
        else:
            updates.append(f"{field} = COALESCE(EXCLUDED.{field}, student_profiles.{field})")
    updates.extend([
        "last_master_import_id = EXCLUDED.last_master_import_id",
        "updated_at = CURRENT_TIMESTAMP",
    ])
    sql = f"""
        INSERT INTO student_profiles(student_id, {columns}, data_origin, last_master_import_id)
        VALUES ({placeholders})
        ON CONFLICT (student_id) DO UPDATE SET {', '.join(updates)}
    """
    rows = [
        (
            record["student_id"],
            *[record.get(field) for field in POSTGRES_FIELDS],
            "master_import",
            import_id,
        )
        for record in records
    ]
    with conn.cursor() as cur:
        execute_batch(cur, sql, rows, page_size=500)


def _mongo_update_document(record: Dict[str, Any], import_id: str) -> UpdateOne:
    values = {
        MONGO_FIELD_MAP.get(field, field): value
        for field, value in record.items()
        if field != "student_id" and value is not None
    }
    values["last_master_import_id"] = import_id
    return UpdateOne(
        {"student_id": record["student_id"]},
        {
            "$set": values,
            "$setOnInsert": {
                "student_id": record["student_id"], "data_origin": "master_import", "is_synthetic": False,
                "subject_grades": [], "is_active": True,
            },
        },
        upsert=True,
    )


def _apply_mongo(records: Sequence[Dict[str, Any]], import_id: str) -> None:
    if not records:
        return
    client = _mongo_client()
    try:
        client[MONGO_DB].students.bulk_write(
            [_mongo_update_document(record, import_id) for record in records], ordered=True
        )
    finally:
        client.close()


def _restore_mongo(snapshots: Sequence[Dict[str, Any]]) -> None:
    operations: List[Any] = []
    for snapshot in snapshots:
        student_id = snapshot["student_id"]
        if snapshot.get("mongo_existed") or snapshot.get("mongo_record"):
            operations.append(ReplaceOne({"student_id": student_id}, snapshot["mongo_record"], upsert=True))
        else:
            operations.append(DeleteOne({"student_id": student_id}))
    if not operations:
        return
    client = _mongo_client()
    try:
        client[MONGO_DB].students.bulk_write(operations, ordered=True)
    finally:
        client.close()


def _restore_postgres(snapshots: Sequence[Dict[str, Any]]) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for snapshot in snapshots:
                student_id = snapshot["student_id"]
                old = snapshot.get("postgres_record") if snapshot.get("postgres_existed") else None
                if not old:
                    cur.execute("DELETE FROM student_profiles WHERE student_id = %s", (student_id,))
                    continue
                assignments = [f"{field} = %s" for field in POSTGRES_FIELDS]
                assignments.extend(["data_origin = %s", "last_master_import_id = %s", "created_at = %s", "updated_at = %s"])
                values = [old.get(field) for field in POSTGRES_FIELDS]
                values.extend([
                    old.get("data_origin") or "manual", old.get("last_master_import_id"),
                    old.get("created_at"), old.get("updated_at"), student_id,
                ])
                cur.execute(
                    f"UPDATE student_profiles SET {', '.join(assignments)} WHERE student_id = %s",
                    tuple(values),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _same_value(left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    try:
        if isinstance(left, (int, float)) or isinstance(right, (int, float)):
            return abs(float(left) - float(right)) < 0.001
    except (TypeError, ValueError):
        pass
    return str(left or "").strip() == str(right or "").strip()


def verify_import(import_id: str) -> Dict[str, Any]:
    records = repository.get_records(import_id)
    ids = [str(record["student_id"]) for record in records]
    pg = _postgres_records(ids)
    mongo = _mongo_records(ids)
    mismatches: List[Dict[str, str]] = []
    for record in records:
        student_id = str(record["student_id"])
        pg_row, mongo_row = pg.get(student_id), mongo.get(student_id)
        if not pg_row or not mongo_row:
            mismatches.append({"student_id": student_id, "field": "record", "detail": "Missing from PostgreSQL or MongoDB."})
            continue
        for field, expected in record.items():
            if expected is None or field == "student_id":
                continue
            mongo_field = MONGO_FIELD_MAP.get(field, field)
            if not _same_value(pg_row.get(field), expected) or not _same_value(mongo_row.get(mongo_field), expected):
                mismatches.append({"student_id": student_id, "field": field, "detail": "Stored values do not match the confirmed import."})
                if len(mismatches) >= 50:
                    break
        if len(mismatches) >= 50:
            break
    return {
        "success": len(mismatches) == 0,
        "synchronized": len(mismatches) == 0,
        "import_id": import_id,
        "checked_students": len(records),
        "postgres_records": len(pg),
        "mongo_records": len(mongo),
        "mismatches": mismatches,
    }


def confirm_import(import_id: str, *, actor_admin_id: str, confirmed: bool) -> Dict[str, Any]:
    if confirmed is not True:
        raise ImportStateError("Set confirm to true after reviewing the preview.")
    batch = repository.get_batch(import_id, include_all_rows=True)
    if not batch:
        raise KeyError("Import batch was not found.")
    if batch.get("actor_admin_id") != actor_admin_id:
        raise ImportStateError("Only the administrator who staged this batch may confirm it.")
    if batch.get("status") != "staged":
        raise ImportStateError(f"Only a staged batch can be confirmed; this batch is {batch.get('status')}.")
    if not (batch.get("validation_summary") or {}).get("valid"):
        raise ImportStateError("This batch has validation errors. Correct the file and create a new preview.")
    records = [dict(row.get("canonical_data") or {}) for row in batch.get("rows", [])]
    snapshots = _snapshots(import_id, records)
    repository.save_snapshots(import_id, snapshots)
    try:
        repository.transition_status(import_id, expected="staged", status="applying")
    except ValueError as exc:
        raise ImportStateError(str(exc)) from exc
    pg_existing = sum(1 for item in snapshots if item.get("postgres_record") or item.get("mongo_record"))
    conn = get_connection()
    mongo_attempted = False
    postgres_committed = False
    try:
        _postgres_upsert(conn, records, import_id)
        mongo_attempted = True
        _apply_mongo(records, import_id)
        conn.commit()
        postgres_committed = True
        verification = verify_import(import_id)
        if not verification["synchronized"]:
            raise RuntimeError("Cross-database verification failed after import.")
        committed = repository.update_status(
            import_id, "committed", inserted_count=len(records) - pg_existing,
            updated_count=pg_existing, failure_detail=None,
        )
        return {"success": True, "batch": committed, "verification": verification}
    except Exception as exc:
        conn.rollback()
        recovery = repository.get_snapshots(import_id)
        if mongo_attempted:
            _restore_mongo(recovery)
        if postgres_committed:
            _restore_postgres(recovery)
        repository.update_status(import_id, "failed", failure_detail=str(exc)[:1000])
        raise
    finally:
        conn.close()


def _assert_batch_is_latest(import_id: str, snapshots: Sequence[Dict[str, Any]]) -> None:
    ids = [str(item["student_id"]) for item in snapshots]
    pg = _postgres_records(ids)
    mongo = _mongo_records(ids)
    changed = []
    for student_id in ids:
        if str((pg.get(student_id) or {}).get("last_master_import_id") or "") != import_id:
            changed.append(student_id)
            continue
        if str((mongo.get(student_id) or {}).get("last_master_import_id") or "") != import_id:
            changed.append(student_id)
    if changed:
        raise ImportStateError(
            "Rollback stopped because these records changed after this batch: " + ", ".join(changed[:10])
        )


def rollback_import(import_id: str, *, actor_admin_id: str, confirmed: bool) -> Dict[str, Any]:
    if confirmed is not True:
        raise ImportStateError("Set confirm to true to roll back this committed batch.")
    batch = repository.get_batch(import_id)
    if not batch:
        raise KeyError("Import batch was not found.")
    if batch.get("actor_admin_id") != actor_admin_id:
        raise ImportStateError("Only the administrator who staged this batch may roll it back.")
    if batch.get("status") != "committed":
        raise ImportStateError(f"Only a committed batch can be rolled back; this batch is {batch.get('status')}.")
    snapshots = repository.get_snapshots(import_id)
    if not snapshots:
        raise ImportStateError("No recovery snapshot exists for this batch.")
    _assert_batch_is_latest(import_id, snapshots)
    records = repository.get_records(import_id)
    try:
        repository.transition_status(import_id, expected="committed", status="rolling_back")
    except ValueError as exc:
        raise ImportStateError(str(exc)) from exc
    mongo_restored = False
    try:
        _restore_mongo(snapshots)
        mongo_restored = True
        _restore_postgres(snapshots)
        rolled_back = repository.update_status(import_id, "rolled_back", failure_detail=None)
        return {"success": True, "batch": rolled_back, "restored_students": len(snapshots)}
    except Exception as exc:
        if mongo_restored:
            _apply_mongo(records, import_id)
        repository.update_status(import_id, "rollback_failed", failure_detail=str(exc)[:1000])
        raise


def recover_incomplete_imports() -> Dict[str, Any]:
    """Repair batches interrupted by a process/container stop.

    PostgreSQL transactions roll back when their connection disappears, while a
    MongoDB bulk write may already have completed.  Restoring both stored
    snapshots is therefore the only safe startup decision for an unfinished
    confirmation or rollback.
    """
    recovered: List[str] = []
    failed: List[str] = []
    for batch in repository.list_incomplete_batches():
        import_id = str(batch["import_id"])
        snapshots = repository.get_snapshots(import_id)
        try:
            if not snapshots:
                raise RuntimeError("Recovery snapshot is missing.")
            _restore_mongo(snapshots)
            _restore_postgres(snapshots)
            terminal = "rolled_back" if batch.get("status") == "rolling_back" else "failed"
            repository.update_status(
                import_id, terminal,
                failure_detail=(None if terminal == "rolled_back" else "Interrupted import was restored automatically at startup."),
            )
            recovered.append(import_id)
        except Exception as exc:
            repository.update_status(import_id, "recovery_failed", failure_detail=str(exc)[:1000])
            failed.append(import_id)
    return {"success": not failed, "recovered": recovered, "failed": failed}
