#!/usr/bin/env python3
"""Reusable V30 synthetic university dataset seeder for local development.

Safety controls:
- Refuses production mode.
- Requires --confirm-synthetic-demo and --replace-v28-demo.
- Writes only deterministic demo IDs and records tagged synthetic_demo_v30.
- It does not create, import, or imitate real student personal information.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, Iterable, List

from pymongo import MongoClient, ReplaceOne
from psycopg2.extras import execute_batch

from app.db.postgres import get_connection, init_postgres_tables, run_local_auto_training_cycle
from app.demo_data import DATA_ORIGIN, DEMO_PASSWORD, build_demo_dataset
from app.agent.neural_intent_trainer import train_neural_intent_model

# V30 owns the demo dataset marker. Older V29 synthetic rows are safe to replace
# only in an explicitly confirmed local demo seed; real data is never tagged with
# these origins and is not deleted by this module.
LEGACY_DEMO_ORIGINS = ("synthetic_demo_v29", "synthetic_demo_v30")


def _chunks(items: List[Dict[str, Any]], size: int = 250) -> Iterable[List[Dict[str, Any]]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _ensure_safe_environment(args: argparse.Namespace) -> None:
    if (os.getenv("APP_ENV") or "development").strip().lower() == "production":
        raise RuntimeError("Synthetic demo seeding is disabled when APP_ENV=production.")
    if not args.confirm_synthetic_demo or not args.replace_v28_demo:
        raise RuntimeError(
            "Refusing to modify data. Run with both --confirm-synthetic-demo and --replace-v28-demo. "
            "This script is only for a local V30 local demo database."
        )


def seed_mongo(dataset: Dict[str, Any]) -> Dict[str, int]:
    uri = os.getenv("MONGO_URI")
    db_name = os.getenv("MONGO_DB", "university_mongo")
    if not uri:
        raise RuntimeError("MONGO_URI is missing. The backend container must receive the root .env file.")
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    try:
        db = client[db_name]
        students = dataset["students"]
        advisors = dataset["advisors"]
        student_ids = [row["student_id"] for row in students]
        advisor_ids = [row["advisor_id"] for row in advisors]

        # Remove only prior V29/V30 *synthetic* rows that are outside the
        # requested deterministic demo range. Untagged or real data is never
        # deleted by this seed path.
        db.students.delete_many({
            "data_origin": {"$in": list(LEGACY_DEMO_ORIGINS)},
            "student_id": {"$nin": student_ids},
        })
        db.advisors.delete_many({
            "data_origin": {"$in": list(LEGACY_DEMO_ORIGINS)},
            "advisor_id": {"$nin": advisor_ids},
        })
        for group in _chunks(students):
            db.students.bulk_write([ReplaceOne({"student_id": row["student_id"]}, row, upsert=True) for row in group], ordered=False)
        for group in _chunks(advisors):
            db.advisors.bulk_write([ReplaceOne({"advisor_id": row["advisor_id"]}, row, upsert=True) for row in group], ordered=False)

        db.students.create_index("student_id", unique=True)
        db.students.create_index("name")
        db.students.create_index("program")
        db.students.create_index("program_code")
        db.students.create_index("gpa")
        db.students.create_index("academic_status")
        db.students.create_index("risk_level")
        db.students.create_index("attendance_rate")
        db.students.create_index("subject_grades.course_code")
        db.students.create_index("subject_grades.advisor_id")
        db.advisors.create_index("advisor_id", unique=True)
        db.advisors.create_index("department")
        db.system_metadata.update_one(
            {"key": "synthetic_dataset_v30"},
            {"$set": {
                "key": "synthetic_dataset_v30",
                "data_origin": DATA_ORIGIN,
                "student_count": len(students),
                "advisor_count": len(advisors),
                "notice": "All identities in this dataset are synthetic and for local testing only.",
            }},
            upsert=True,
        )
        return {"students": len(students), "advisors": len(advisors)}
    finally:
        client.close()


def _execute_many(cur, sql: str, rows: List[tuple]) -> None:
    if rows:
        execute_batch(cur, sql, rows, page_size=500)


def seed_postgres(dataset: Dict[str, Any]) -> Dict[str, int]:
    init_postgres_tables()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Clear only rows created by this synthetic demo. Existing unrelated data stays intact.
            for table in [
                "student_assessment_results", "student_attendance_summaries", "student_course_enrollments",
                "student_financial_accounts", "student_support_cases", "student_scholarship_awards",
                "advisor_course_assignments", "student_profiles", "advisor_profiles", "course_catalog",
                "university_program_catalog", "academic_terms", "demo_dataset_metadata",
            ]:
                cur.execute(f"DELETE FROM {table} WHERE data_origin = ANY(%s)", (list(LEGACY_DEMO_ORIGINS),))

            terms = [
                ("2026-1", "Academic Year 2026 Semester 1", "2026-08-01", "2026-12-15", DATA_ORIGIN),
                ("2026-2", "Academic Year 2026 Semester 2", "2027-01-08", "2027-05-25", DATA_ORIGIN),
                ("2026-S", "Academic Year 2026 Summer", "2026-06-01", "2026-07-15", DATA_ORIGIN),
            ]
            _execute_many(cur, """
                INSERT INTO academic_terms(term_code, term_name, start_date, end_date, data_origin)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (term_code) DO UPDATE SET term_name=EXCLUDED.term_name, start_date=EXCLUDED.start_date,
                    end_date=EXCLUDED.end_date, data_origin=EXCLUDED.data_origin
            """, terms)

            program_rows = []
            for row in dataset["programs"]:
                program_rows.append((
                    row["program_code"], row["program_name"], row["faculty"], row["language"],
                    row["tuition_fee"], "High school diploma or equivalent, English readiness, portfolio/interview where required.",
                    DATA_ORIGIN,
                ))
            _execute_many(cur, """
                INSERT INTO university_program_catalog(program_code, program_name, faculty, language, tuition_fee, admission_requirement, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (program_code) DO UPDATE SET program_name=EXCLUDED.program_name, faculty=EXCLUDED.faculty,
                    language=EXCLUDED.language, tuition_fee=EXCLUDED.tuition_fee, admission_requirement=EXCLUDED.admission_requirement,
                    data_origin=EXCLUDED.data_origin
            """, program_rows)
            # Preserve existing programs table semantics while ensuring all demo programs can be searched.
            for row in dataset["programs"]:
                cur.execute("SELECT 1 FROM programs WHERE program_name = %s LIMIT 1", (row["program_name"],))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO programs(program_name, faculty, admission_requirement, tuition_fee, language) VALUES (%s, %s, %s, %s, %s)",
                        (row["program_name"], row["faculty"], "Synthetic demo admission requirement. Replace with real university policy.", row["tuition_fee"], row["language"]),
                    )

            _execute_many(cur, """
                INSERT INTO course_catalog(course_code, course_name, program_code, program_name, credits, course_level, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (course_code) DO UPDATE SET course_name=EXCLUDED.course_name, program_code=EXCLUDED.program_code,
                    program_name=EXCLUDED.program_name, credits=EXCLUDED.credits, course_level=EXCLUDED.course_level,
                    data_origin=EXCLUDED.data_origin
            """, [
                (row["course_code"], row["course_name"], row["program_code"], row["program_name"], row["credits"], row["level"], DATA_ORIGIN)
                for row in dataset["courses"]
            ])

            _execute_many(cur, """
                INSERT INTO advisor_profiles(advisor_id, full_name, department, email, phone, office, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (advisor_id) DO UPDATE SET full_name=EXCLUDED.full_name, department=EXCLUDED.department,
                    email=EXCLUDED.email, phone=EXCLUDED.phone, office=EXCLUDED.office, data_origin=EXCLUDED.data_origin
            """, [
                (row["advisor_id"], row["name"], row["department"], row["email"], row["phone"], row["office"], DATA_ORIGIN)
                for row in dataset["advisors"]
            ])

            _execute_many(cur, """
                INSERT INTO student_profiles(
                    student_id, full_name, thai_name, program_code, program_name, faculty, email, phone,
                    admission_type, year_level, entry_year, expected_graduation_year, academic_status, gpa,
                    credits_earned, credits_required, attendance_rate, risk_level, scholarship_status, campus, data_origin
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (student_id) DO UPDATE SET full_name=EXCLUDED.full_name, thai_name=EXCLUDED.thai_name,
                    program_code=EXCLUDED.program_code, program_name=EXCLUDED.program_name, faculty=EXCLUDED.faculty,
                    email=EXCLUDED.email, phone=EXCLUDED.phone, admission_type=EXCLUDED.admission_type,
                    year_level=EXCLUDED.year_level, entry_year=EXCLUDED.entry_year,
                    expected_graduation_year=EXCLUDED.expected_graduation_year, academic_status=EXCLUDED.academic_status,
                    gpa=EXCLUDED.gpa, credits_earned=EXCLUDED.credits_earned, credits_required=EXCLUDED.credits_required,
                    attendance_rate=EXCLUDED.attendance_rate, risk_level=EXCLUDED.risk_level,
                    scholarship_status=EXCLUDED.scholarship_status, campus=EXCLUDED.campus, data_origin=EXCLUDED.data_origin,
                    updated_at=CURRENT_TIMESTAMP
            """, [
                (
                    row["student_id"], row["name"], row["name_th"], row["program_code"], row["program"], row["faculty"],
                    row["email"], row["phone"], row["admission_type"], row["year_level"], row["entry_year"],
                    row["expected_graduation_year"], row["academic_status"], row["gpa"], row["credits_earned"],
                    row["credits_required"], row["attendance_rate"], row["risk_level"], row["scholarship_status"], row["campus"], DATA_ORIGIN,
                ) for row in dataset["students"]
            ])

            _execute_many(cur, """
                INSERT INTO advisor_course_assignments(advisor_id, course_code, term_code, data_origin)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (advisor_id, course_code, term_code) DO UPDATE SET data_origin=EXCLUDED.data_origin
            """, [(row["advisor_id"], row["course_code"], row["term_code"], DATA_ORIGIN) for row in dataset["advisor_assignments"]])

            _execute_many(cur, """
                INSERT INTO student_course_enrollments(
                    student_id, course_code, course_name, term_code, advisor_id, grade, score, credits,
                    attendance_rate, enrollment_status, data_origin
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (student_id, course_code, term_code) DO UPDATE SET advisor_id=EXCLUDED.advisor_id,
                    grade=EXCLUDED.grade, score=EXCLUDED.score, credits=EXCLUDED.credits,
                    attendance_rate=EXCLUDED.attendance_rate, enrollment_status=EXCLUDED.enrollment_status,
                    data_origin=EXCLUDED.data_origin
            """, [
                (row["student_id"], row["course_code"], row["course_name"], row["term_code"], row["advisor_id"], row["grade"],
                 row["score"], row["credits"], row["attendance_rate"], row["enrollment_status"], DATA_ORIGIN)
                for row in dataset["enrollments"]
            ])

            _execute_many(cur, """
                INSERT INTO student_assessment_results(student_id, course_code, term_code, assessment_type, weight_percent, score, advisor_id, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (student_id, course_code, term_code, assessment_type) DO UPDATE SET weight_percent=EXCLUDED.weight_percent,
                    score=EXCLUDED.score, advisor_id=EXCLUDED.advisor_id, data_origin=EXCLUDED.data_origin
            """, [
                (row["student_id"], row["course_code"], row["term_code"], row["assessment_type"], row["weight_percent"],
                 row["score"], row["advisor_id"], DATA_ORIGIN) for row in dataset["assessments"]
            ])

            _execute_many(cur, """
                INSERT INTO student_attendance_summaries(student_id, course_code, term_code, advisor_id, attendance_rate, classes_attended, classes_scheduled, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (student_id, course_code, term_code) DO UPDATE SET advisor_id=EXCLUDED.advisor_id,
                    attendance_rate=EXCLUDED.attendance_rate, classes_attended=EXCLUDED.classes_attended,
                    classes_scheduled=EXCLUDED.classes_scheduled, data_origin=EXCLUDED.data_origin
            """, [
                (row["student_id"], row["course_code"], row["term_code"], row["advisor_id"], row["attendance_rate"],
                 row["classes_attended"], row["classes_scheduled"], DATA_ORIGIN) for row in dataset["attendance"]
            ])

            _execute_many(cur, """
                INSERT INTO student_financial_accounts(student_id, term_code, tuition_due, amount_paid, balance_due, payment_status, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (student_id, term_code) DO UPDATE SET tuition_due=EXCLUDED.tuition_due, amount_paid=EXCLUDED.amount_paid,
                    balance_due=EXCLUDED.balance_due, payment_status=EXCLUDED.payment_status, data_origin=EXCLUDED.data_origin
            """, [
                (row["student_id"], row["term_code"], row["tuition_due"], row["amount_paid"], row["balance_due"], row["payment_status"], DATA_ORIGIN)
                for row in dataset["financial_accounts"]
            ])

            _execute_many(cur, """
                INSERT INTO student_support_cases(student_id, case_type, priority, status, assigned_advisor_id, summary, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, [
                (row["student_id"], row["case_type"], row["priority"], row["status"], row["assigned_advisor_id"], row["summary"], DATA_ORIGIN)
                for row in dataset["support_cases"]
            ])

            _execute_many(cur, """
                INSERT INTO student_scholarship_awards(student_id, scholarship_name, term_code, amount, status, data_origin)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, [
                (row["student_id"], row["scholarship_name"], row["term_code"], row["amount"], row["status"], DATA_ORIGIN)
                for row in dataset["scholarship_awards"]
            ])

            # Existing role-visibility tables are updated too, so Advisor/Student document permissions still work.
            advisor_subject_rows = []
            student_subject_rows = []
            for row in dataset["enrollments"]:
                advisor_subject_rows.append((row["advisor_id"], row["course_code"], row["course_name"]))
                student_subject_rows.append((row["student_id"], row["advisor_id"], row["course_code"], row["course_name"]))
            _execute_many(cur, """
                INSERT INTO advisor_subjects(advisor_id, subject_code, subject_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (advisor_id, subject_code) DO UPDATE SET subject_name=EXCLUDED.subject_name
            """, list({row for row in advisor_subject_rows}))
            _execute_many(cur, """
                INSERT INTO student_subjects(student_id, advisor_id, subject_code, subject_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (student_id, advisor_id, subject_code) DO UPDATE SET subject_name=EXCLUDED.subject_name
            """, student_subject_rows)

            cur.execute(
                """
                INSERT INTO demo_dataset_metadata(dataset_key, data_origin, student_count, advisor_count, course_count, enrollment_count, assessment_count, notice, updated_at)
                VALUES ('university_v30_synthetic', %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (dataset_key) DO UPDATE SET data_origin=EXCLUDED.data_origin, student_count=EXCLUDED.student_count,
                    advisor_count=EXCLUDED.advisor_count, course_count=EXCLUDED.course_count, enrollment_count=EXCLUDED.enrollment_count,
                    assessment_count=EXCLUDED.assessment_count, notice=EXCLUDED.notice, updated_at=CURRENT_TIMESTAMP
                """,
                (DATA_ORIGIN, len(dataset["students"]), len(dataset["advisors"]), len(dataset["courses"]), len(dataset["enrollments"]), len(dataset["assessments"]),
                 "All identities and contact-style fields are synthetic for local demo/testing only."),
            )
        conn.commit()
        return {
            "student_profiles": len(dataset["students"]), "advisor_profiles": len(dataset["advisors"]),
            "courses": len(dataset["courses"]), "enrollments": len(dataset["enrollments"]),
            "assessments": len(dataset["assessments"]), "attendance": len(dataset["attendance"]),
            "support_cases": len(dataset["support_cases"]), "scholarships": len(dataset["scholarship_awards"]),
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed 1,000+ completely synthetic university records for V30 local development.")
    parser.add_argument("--count", type=int, default=1000, help="Synthetic students to create (1-5000, default: 1000).")
    parser.add_argument("--confirm-synthetic-demo", action="store_true", help="Required acknowledgement that this is synthetic demo data.")
    parser.add_argument("--replace-v28-demo", action="store_true", help="Required acknowledgement before replacing the V28 sample ID range.")
    parser.add_argument("--refresh-ai-index", action="store_true", help="Also rebuild local retrieval indexes after seeding. This can take longer.")
    parser.add_argument("--skip-neural-router-training", action="store_true", help="Do not train the local neural router after data is seeded.")
    args = parser.parse_args()
    try:
        _ensure_safe_environment(args)
        dataset = build_demo_dataset(args.count)
        mongo_summary = seed_mongo(dataset)
        postgres_summary = seed_postgres(dataset)
        result: Dict[str, Any] = {
            "success": True,
            "data_origin": DATA_ORIGIN,
            "synthetic_notice": "All names, identifiers, emails, phone-like values, and records are fictitious.",
            "default_demo_password": DEMO_PASSWORD,
            "mongo": mongo_summary,
            "postgres": postgres_summary,
        }
        if not args.skip_neural_router_training:
            result["neural_router_training"] = train_neural_intent_model(force=True, trigger_source="v30_synthetic_seed")
        if args.refresh_ai_index:
            result["semantic_index_refresh"] = run_local_auto_training_cycle(
                mongo_uri=os.getenv("MONGO_URI", ""),
                mongo_db_name=os.getenv("MONGO_DB", "university_mongo"),
                trigger_source="v30_synthetic_seed",
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"V30 synthetic seed failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
