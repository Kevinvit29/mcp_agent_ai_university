"""Administrator CRUD workflows for synchronized student/advisor master records."""

from __future__ import annotations

import csv
import io
import os
import re
from typing import Any, Dict, List

from pymongo import MongoClient

from app.admin_accounts import hash_password
from app.db.postgres import get_connection
from app.roles.admin import master_import_service
from app.roles.admin.master_import_models import CANONICAL_FIELDS


MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB = os.getenv("MONGO_DB", "university_mongo")


def _client() -> MongoClient:
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=10_000)


def _student_exists(student_id: str) -> bool:
    pg = master_import_service._postgres_records([student_id])
    mongo = master_import_service._mongo_records([student_id])
    return student_id in pg or student_id in mongo


def save_student(
    *, payload: Dict[str, Any], actor_admin_id: str, target_student_id: str | None = None,
    create: bool, confirmed: bool,
) -> Dict[str, Any]:
    if confirmed is not True:
        raise ValueError("Set confirm to true to save this student in both databases.")
    record = {field: payload.get(field) for field in CANONICAL_FIELDS if field in payload}
    record["student_id"] = str(target_student_id or record.get("student_id") or "").strip().upper()
    exists = _student_exists(record["student_id"]) if record["student_id"] else False
    if create and exists:
        raise ValueError("That student ID already exists. Use the edit workflow instead.")
    if not create and not exists:
        raise ValueError("Student record was not found.")
    if not create:
        current = master_import_service._postgres_records([record["student_id"]]).get(record["student_id"], {})
        mongo_current = master_import_service._mongo_records([record["student_id"]]).get(record["student_id"], {})
        for field in CANONICAL_FIELDS:
            mongo_field = master_import_service.MONGO_FIELD_MAP.get(field, field)
            if field not in record:
                record[field] = current.get(field, mongo_current.get(mongo_field))

    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(record.keys()))
    writer.writeheader()
    writer.writerow(record)
    batch = master_import_service.create_preview(
        raw=stream.getvalue().encode("utf-8"),
        filename=f"manual-student-{record['student_id']}.csv",
        actor_admin_id=actor_admin_id,
    )
    if not (batch.get("validation_summary") or {}).get("valid"):
        errors = [issue.get("message") for row in batch.get("rows", []) for issue in row.get("issues", []) if issue.get("severity") == "error"]
        raise ValueError(" ".join(errors) or "Student data is invalid.")
    result = master_import_service.confirm_import(batch["import_id"], actor_admin_id=actor_admin_id, confirmed=True)
    password = str(payload.get("password") or "")
    if password:
        encoded = hash_password(password)
        client = _client()
        try:
            client[MONGO_DB].students.update_one({"student_id": record["student_id"]}, {"$set": {"password_hash": encoded}})
        except Exception:
            master_import_service.rollback_import(batch["import_id"], actor_admin_id=actor_admin_id, confirmed=True)
            raise
        finally:
            client.close()
    return result


def set_student_active(student_id: str, active: bool) -> Dict[str, Any]:
    student_id = str(student_id or "").strip().upper()
    pg_old = master_import_service._postgres_records([student_id]).get(student_id)
    mongo_old = master_import_service._mongo_records([student_id]).get(student_id)
    if not pg_old and not mongo_old:
        raise ValueError("Student record was not found.")
    client = _client()
    mongo_changed = False
    conn = get_connection()
    try:
        client[MONGO_DB].students.update_one(
            {"student_id": student_id},
            {"$set": {"is_active": bool(active)}, "$unset": {"last_master_import_id": ""}},
        )
        mongo_changed = True
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE student_profiles SET is_active = %s, last_master_import_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE student_id = %s",
                (bool(active), student_id),
            )
            if cur.rowcount == 0:
                raise RuntimeError("Student is missing from PostgreSQL; repair it with a confirmed import before changing status.")
        conn.commit()
        return {"student_id": student_id, "is_active": bool(active), "synchronized": True}
    except Exception:
        conn.rollback()
        if mongo_changed and mongo_old:
            client[MONGO_DB].students.replace_one({"student_id": student_id}, mongo_old, upsert=True)
        raise
    finally:
        conn.close()
        client.close()


def list_students(limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT student_id, full_name, program_code, program_name, academic_status,
                       gpa, attendance_rate, is_active, updated_at
                FROM student_profiles ORDER BY student_id LIMIT %s
                """,
                (max(1, min(int(limit), 500)),),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _validate_advisor(payload: Dict[str, Any], target_advisor_id: str | None = None) -> Dict[str, Any]:
    result = {
        "advisor_id": str(target_advisor_id or payload.get("advisor_id") or "").strip().upper(),
        "full_name": str(payload.get("full_name") or payload.get("name") or "").strip(),
        "department": str(payload.get("department") or "").strip(),
        "email": str(payload.get("email") or "").strip() or None,
        "phone": str(payload.get("phone") or "").strip() or None,
        "office": str(payload.get("office") or "").strip() or None,
    }
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,19}", result["advisor_id"]):
        raise ValueError("advisor_id must be 1-20 letters, numbers, dots, underscores, or hyphens.")
    if not result["full_name"] or len(result["full_name"]) > 255:
        raise ValueError("Advisor full_name must contain 1-255 characters.")
    if result["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", result["email"]):
        raise ValueError("Advisor email is not valid.")
    return result


def _advisor_snapshots(advisor_id: str) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM advisor_profiles WHERE advisor_id = %s", (advisor_id,))
            pg = cur.fetchone()
    finally:
        conn.close()
    client = _client()
    try:
        mongo = client[MONGO_DB].advisors.find_one({"advisor_id": advisor_id}, {"_id": 0})
    finally:
        client.close()
    return dict(pg) if pg else None, dict(mongo) if mongo else None


def save_advisor(
    *, payload: Dict[str, Any], target_advisor_id: str | None = None, create: bool,
    confirmed: bool,
) -> Dict[str, Any]:
    if confirmed is not True:
        raise ValueError("Set confirm to true to save this advisor in both databases.")
    advisor_id = str(target_advisor_id or payload.get("advisor_id") or "").strip().upper()
    pg_old, mongo_old = _advisor_snapshots(advisor_id)
    exists = bool(pg_old or mongo_old)
    if create and exists:
        raise ValueError("That advisor ID already exists. Use the edit workflow instead.")
    if not create and not exists:
        raise ValueError("Advisor record was not found.")
    combined = dict(pg_old or {})
    if mongo_old:
        combined.setdefault("full_name", mongo_old.get("name"))
        for field in ("department", "email", "phone", "office"):
            combined.setdefault(field, mongo_old.get(field))
    combined.update(payload)
    row = _validate_advisor(combined, advisor_id)
    password = str(payload.get("password") or "")
    encoded = hash_password(password) if password else None
    active = bool(payload.get("is_active", (pg_old or mongo_old or {}).get("is_active", True)))
    client = _client()
    conn = get_connection()
    mongo_changed = False
    try:
        mongo_set = {"name": row["full_name"], "department": row["department"], "email": row["email"], "phone": row["phone"], "office": row["office"], "is_active": active}
        if encoded:
            mongo_set["password_hash"] = encoded
        client[MONGO_DB].advisors.update_one(
            {"advisor_id": advisor_id},
            {"$set": mongo_set, "$setOnInsert": {"advisor_id": advisor_id, "data_origin": "manual_admin"}},
            upsert=True,
        )
        mongo_changed = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO advisor_profiles(advisor_id, full_name, department, email, phone, office, is_active, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'manual_admin')
                ON CONFLICT (advisor_id) DO UPDATE SET full_name=EXCLUDED.full_name,
                    department=EXCLUDED.department, email=EXCLUDED.email, phone=EXCLUDED.phone,
                    office=EXCLUDED.office, is_active=EXCLUDED.is_active, updated_at=CURRENT_TIMESTAMP
                """,
                (advisor_id, row["full_name"], row["department"], row["email"], row["phone"], row["office"], active),
            )
        conn.commit()
        return {"advisor_id": advisor_id, **row, "is_active": active, "synchronized": True}
    except Exception:
        conn.rollback()
        if mongo_changed:
            if mongo_old:
                client[MONGO_DB].advisors.replace_one({"advisor_id": advisor_id}, mongo_old, upsert=True)
            else:
                client[MONGO_DB].advisors.delete_one({"advisor_id": advisor_id})
        raise
    finally:
        conn.close()
        client.close()


def set_advisor_active(advisor_id: str, active: bool) -> Dict[str, Any]:
    pg_old, mongo_old = _advisor_snapshots(str(advisor_id or "").strip().upper())
    if not pg_old and not mongo_old:
        raise ValueError("Advisor record was not found.")
    payload = {
        "full_name": (pg_old or {}).get("full_name") or (mongo_old or {}).get("name"),
        "department": (pg_old or {}).get("department") or (mongo_old or {}).get("department"),
        "email": (pg_old or {}).get("email") or (mongo_old or {}).get("email"),
        "phone": (pg_old or {}).get("phone") or (mongo_old or {}).get("phone"),
        "office": (pg_old or {}).get("office") or (mongo_old or {}).get("office"),
        "is_active": bool(active),
    }
    return save_advisor(payload=payload, target_advisor_id=advisor_id, create=False, confirmed=True)


def list_advisors(limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT advisor_id, full_name, department, email, phone, office, is_active, updated_at
                FROM advisor_profiles ORDER BY advisor_id LIMIT %s
                """,
                (max(1, min(int(limit), 500)),),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
