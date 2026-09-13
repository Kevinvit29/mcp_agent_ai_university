"""Non-destructive local bootstrap for the V30 synthetic Lecturer accounts."""

from __future__ import annotations

import json
import os

from pymongo import MongoClient, ReplaceOne

from app.demo_data import DATA_ORIGIN, DEMO_PASSWORD, build_demo_dataset


def seed_synthetic_lecturers() -> dict:
    if (os.getenv("APP_ENV") or "development").strip().lower() == "production":
        raise RuntimeError("Synthetic Lecturer bootstrap is disabled in production.")
    uri = (os.getenv("MONGO_URI") or "").strip()
    if not uri:
        raise RuntimeError("MONGO_URI is required.")
    rows = build_demo_dataset(1)["lecturers"]
    client = MongoClient(uri, serverSelectionTimeoutMS=10_000)
    try:
        collection = client[os.getenv("MONGO_DB", "university_mongo")].lecturers
        if rows:
            collection.bulk_write(
                [ReplaceOne({"lecturer_id": row["lecturer_id"]}, row, upsert=True) for row in rows],
                ordered=False,
            )
        collection.create_index("lecturer_id", unique=True)
        collection.create_index("advisor_scope_id", unique=True)
        collection.create_index("department")
        return {
            "success": True,
            "data_origin": DATA_ORIGIN,
            "lecturer_count": len(rows),
            "default_demo_password": DEMO_PASSWORD,
            "mutation": "non_destructive_upsert_only",
        }
    finally:
        client.close()


if __name__ == "__main__":
    print(json.dumps(seed_synthetic_lecturers(), indent=2))
