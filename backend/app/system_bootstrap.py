"""V30 lifecycle bootstrap and dataset integrity commands.

This module is intentionally the single place that:
- runs idempotent PostgreSQL schema migrations;
- creates the first PostgreSQL-backed administrator in development only;
- reports the real MongoDB/PostgreSQL dataset counts;
- seeds the 1,000-record *synthetic* demo dataset only when explicitly enabled.

It never treats a 100-row UI page as a database total, and it refuses to seed when
production mode or unrecognised existing records suggest this is not a demo DB.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Iterable

from pymongo import MongoClient

from app.admin_accounts import bootstrap_admin_account
from app.db.postgres import get_connection, init_postgres_tables
from app.demo_data import DATA_ORIGIN, build_demo_dataset
from app.synthetic_seed import LEGACY_DEMO_ORIGINS, seed_mongo, seed_postgres
from app.agent.neural_intent_trainer import train_neural_intent_model

EXPECTED_STUDENT_COUNT = 1000
DEMO_ORIGINS = tuple(dict.fromkeys((*LEGACY_DEMO_ORIGINS, DATA_ORIGIN)))


def _env_truthy(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _is_production() -> bool:
    return (os.getenv("APP_ENV") or "development").strip().lower() in {"production", "prod"}


def migrate_and_bootstrap_admin() -> Dict[str, Any]:
    """Run idempotent table migration and first-account bootstrap."""
    init_postgres_tables()
    return bootstrap_admin_account()


def _postgres_status() -> Dict[str, Any]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM student_profiles")
            students = int((cur.fetchone() or {}).get("count") or 0)
            cur.execute(
                """
                SELECT data_origin, student_count, advisor_count, course_count,
                       enrollment_count, assessment_count, updated_at
                FROM demo_dataset_metadata
                WHERE dataset_key = 'university_v30_synthetic'
                LIMIT 1
                """
            )
            metadata = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS count FROM admin_accounts")
            admins = int((cur.fetchone() or {}).get("count") or 0)
            cur.execute(
                "SELECT COUNT(*) AS count FROM student_profiles WHERE data_origin = %s",
                (DATA_ORIGIN,),
            )
            v30_students = int((cur.fetchone() or {}).get("count") or 0)
            return {
                "reachable": True,
                "student_profiles": students,
                "v30_synthetic_students": v30_students,
                "admin_accounts": admins,
                "metadata": metadata,
            }
    finally:
        conn.close()


def _mongo_status() -> Dict[str, Any]:
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError("MONGO_URI is required.")
    db_name = os.getenv("MONGO_DB", "university_mongo")
    client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
    try:
        db = client[db_name]
        students = db.students.count_documents({})
        v30_students = db.students.count_documents({"data_origin": DATA_ORIGIN})
        metadata = db.system_metadata.find_one({"key": "synthetic_dataset_v30"}, {"_id": 0})
        return {
            "reachable": True,
            "students": int(students),
            "v30_synthetic_students": int(v30_students),
            "metadata": metadata,
        }
    finally:
        client.close()


def dataset_status() -> Dict[str, Any]:
    """Return counts from both stores and a deterministic readiness decision."""
    pg = _postgres_status()
    mongo = _mongo_status()
    expected = EXPECTED_STUDENT_COUNT
    synchronized = (
        pg["student_profiles"] == expected
        and pg["v30_synthetic_students"] == expected
        and mongo["students"] == expected
        and mongo["v30_synthetic_students"] == expected
    )
    return {
        "success": True,
        "mode": "production" if _is_production() else "development",
        "data_origin": DATA_ORIGIN,
        "expected_student_count": expected,
        "postgres": pg,
        "mongo": mongo,
        "synchronized": synchronized,
        "message": (
            "Synthetic demo dataset is synchronized across MongoDB and PostgreSQL."
            if synchronized
            else "Dataset is not yet synchronized. Use the V30 bootstrap/seed command; list page limits are not database totals."
        ),
    }


def _legacy_mongo_records_are_safe_to_replace() -> bool:
    """Allow the known legacy V29 100-row demo only; never auto-replace arbitrary records."""
    uri = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB", "university_mongo")
    client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
    try:
        collection = client[db_name].students
        untagged = list(
            collection.find(
                {"$or": [{"data_origin": {"$exists": False}}, {"data_origin": None}]},
                {"_id": 0, "student_id": 1, "name": 1},
            ).limit(101)
        )
        if not untagged:
            return True
        if len(untagged) > 100:
            return False
        return all(
            re.fullmatch(r"S\d{3}", str(row.get("student_id") or "")) is not None
            for row in untagged
        )
    finally:
        client.close()


def _has_non_demo_postgres_students() -> bool:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS count FROM student_profiles WHERE COALESCE(data_origin, '') <> ALL(%s)",
                (list(DEMO_ORIGINS),),
            )
            return int((cur.fetchone() or {}).get("count") or 0) > 0
    finally:
        conn.close()


def ensure_synthetic_dataset(*, train_router: bool = True) -> Dict[str, Any]:
    """Idempotently create the V30 1,000-record demo dataset when allowed."""
    if _is_production():
        raise RuntimeError("Synthetic data bootstrap is disabled in production.")
    if not _env_truthy("DEMO_DATA_MODE", default=True):
        raise RuntimeError("DEMO_DATA_MODE is false. Refusing to create synthetic records.")
    current = dataset_status()
    if current["synchronized"]:
        return {**current, "seeded": False, "message": "Dataset already synchronized; no records were changed."}

    if _has_non_demo_postgres_students():
        raise RuntimeError(
            "PostgreSQL contains records not marked as V29/V30 synthetic demo data. "
            "Refusing to replace or mix unknown records."
        )
    if not _legacy_mongo_records_are_safe_to_replace():
        raise RuntimeError(
            "MongoDB contains records that are not recognised as the local V29/V30 demo. "
            "Refusing to replace or mix unknown records."
        )

    dataset = build_demo_dataset(EXPECTED_STUDENT_COUNT)
    mongo_result = seed_mongo(dataset)
    postgres_result = seed_postgres(dataset)
    training: Dict[str, Any] | None = None
    if train_router:
        training = train_neural_intent_model(force=True, trigger_source="v30_dataset_bootstrap")

    result = dataset_status()
    if not result["synchronized"]:
        raise RuntimeError("Seeding completed but dataset verification failed. No chat count should be trusted until this is resolved.")
    return {
        **result,
        "seeded": True,
        "mongo_seed": mongo_result,
        "postgres_seed": postgres_result,
        "neural_router_training": training,
        "message": "Created and verified 1,000 fictional V30 demo students in both data stores.",
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V30 schema, admin, and synthetic-demo integrity commands.")
    parser.add_argument("--migrate", action="store_true", help="Run idempotent schema migration and first-admin bootstrap.")
    parser.add_argument("--status", action="store_true", help="Show actual database counts and synchronization state.")
    parser.add_argument(
        "--ensure-synthetic",
        action="store_true",
        help="Create/repair the development-only 1,000-record synthetic dataset when safe.",
    )
    parser.add_argument(
        "--skip-neural-router-training",
        action="store_true",
        help="Skip local router training when ensuring the demo dataset.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        bootstrap = None
        if args.migrate or args.ensure_synthetic or args.status:
            bootstrap = migrate_and_bootstrap_admin()
        if args.ensure_synthetic:
            result = ensure_synthetic_dataset(train_router=not args.skip_neural_router_training)
            result["admin_bootstrap"] = bootstrap
        elif args.status:
            result = dataset_status()
            result["admin_bootstrap"] = bootstrap
        else:
            result = {"success": True, "admin_bootstrap": bootstrap, "message": "Migration completed."}
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"V30 bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
