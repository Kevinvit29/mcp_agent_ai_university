"""Authoritative data-source registry and university overview formatter.

The project has two stores with different purposes:
- MongoDB `students` is the canonical student master database.
- PostgreSQL stores relationship rows, programs, documents, chat state, and agent indexes.

A PostgreSQL table such as `student_subjects` must never be used as the total
student population. This module keeps that provenance explicit so broad
summaries do not mix sample relationship rows with the 100-record student
master collection.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

SOURCE_OF_TRUTH = {
    "student_master": {
        "source": "MongoDB university_mongo.students",
        "authority": "canonical",
        "use_for": ["student count", "student profile", "GPA", "program", "student grades"],
        "never_use_for": [],
    },
    "advisor_master": {
        "source": "MongoDB university_mongo.advisors",
        "authority": "canonical",
        "use_for": ["advisor count", "advisor profile", "teaching assignments"],
        "never_use_for": [],
    },
    "student_subject_links": {
        "source": "PostgreSQL student_subjects",
        "authority": "relationship_supporting",
        "use_for": ["student/advisor subject permission links"],
        "never_use_for": ["total student population", "all university grades"],
    },
    "program_directory": {
        "source": "PostgreSQL programs",
        "authority": "reference_directory",
        "use_for": ["published program information"],
        "never_use_for": ["student enrolment count unless explicitly synchronized"],
    },
    "documents": {
        "source": "PostgreSQL admin_documents + advisor_documents + lecturer_documents",
        "authority": "document_knowledge_base",
        "use_for": ["uploaded PDF/Excel/CSV content"],
        "never_use_for": ["student master count"],
    },
}


def _unwrap(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    data = value.get("data")
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return data.get("data")
    return data if data is not None else value


def _table_count(pg_map: Any, table_name: str) -> Optional[int]:
    if not isinstance(pg_map, dict):
        return None
    for row in pg_map.get("tables") or []:
        if isinstance(row, dict) and row.get("table_name") == table_name:
            try:
                return int(row.get("row_count"))
            except (TypeError, ValueError):
                return None
    return None


def _list_len(value: Any, list_key: str = "") -> Optional[int]:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        candidate = value.get(list_key) if list_key else None
        if isinstance(candidate, list):
            return len(candidate)
    return None


def build_university_truth_snapshot(admin_bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Build one provenance-aware view from the multi-tool admin bundle."""
    bundle = admin_bundle or {}
    student_count_data = _unwrap(bundle.get("student_count"))
    student_schema = _unwrap(bundle.get("student_schema"))
    advisor_schema = _unwrap(bundle.get("advisor_schema"))
    advisors = _unwrap(bundle.get("advisors"))
    programs = _unwrap(bundle.get("programs"))
    documents = _unwrap(bundle.get("documents"))
    pg_map = _unwrap(bundle.get("postgres_database_map"))

    canonical_student_count: Optional[int] = None
    if isinstance(student_count_data, dict) and student_count_data.get("count") is not None:
        try:
            canonical_student_count = int(student_count_data.get("count"))
        except (TypeError, ValueError):
            pass
    if canonical_student_count is None and isinstance(student_schema, dict):
        try:
            canonical_student_count = int(student_schema.get("count"))
        except (TypeError, ValueError):
            pass

    canonical_advisor_count: Optional[int] = None
    if isinstance(advisor_schema, dict) and advisor_schema.get("count") is not None:
        try:
            canonical_advisor_count = int(advisor_schema.get("count"))
        except (TypeError, ValueError):
            pass
    if canonical_advisor_count is None:
        canonical_advisor_count = _list_len(advisors, "advisors")

    program_count = _list_len(programs)
    if program_count is None:
        program_count = _table_count(pg_map, "programs")

    document_rows = documents.get("data") if isinstance(documents, dict) else documents
    document_count = _list_len(document_rows)

    relationship_counts = {
        "student_subject_links": _table_count(pg_map, "student_subjects"),
        "advisor_subject_links": _table_count(pg_map, "advisor_subjects"),
        "chat_sessions": _table_count(pg_map, "chat_sessions"),
        "uploaded_admin_documents": _table_count(pg_map, "admin_documents"),
        "uploaded_advisor_documents": _table_count(pg_map, "advisor_documents"),
    }

    conflicts: List[Dict[str, Any]] = []
    # Relationship row counts often differ from master record counts. This is
    # expected, but showing it makes it impossible for the final answer to call
    # the smaller table a student total.
    links = relationship_counts.get("student_subject_links")
    if canonical_student_count is not None and links is not None and links != canonical_student_count:
        conflicts.append({
            "field": "student count",
            "canonical_source": SOURCE_OF_TRUTH["student_master"]["source"],
            "canonical_value": canonical_student_count,
            "other_source": SOURCE_OF_TRUTH["student_subject_links"]["source"],
            "other_value": links,
            "resolution": "PostgreSQL student_subjects is a subject-link table, not the student master count.",
        })

    return {
        "type": "university_truth_snapshot",
        "source_of_truth": SOURCE_OF_TRUTH,
        "canonical_metrics": {
            "student_count": canonical_student_count,
            "advisor_count": canonical_advisor_count,
            "program_count": program_count,
            "uploaded_document_count": document_count,
        },
        "supporting_table_counts": relationship_counts,
        "conflicts_detected": conflicts,
    }


def format_authoritative_university_overview(admin_bundle: Dict[str, Any], language: str = "en") -> str:
    snap = build_university_truth_snapshot(admin_bundle)
    thai = (language or "").lower().startswith("th")
    metrics = snap.get("canonical_metrics") or {}
    support = snap.get("supporting_table_counts") or {}
    if thai:
        lines = ["ภาพรวมระบบมหาวิทยาลัยจากแหล่งข้อมูลที่ยืนยันแล้ว:"]
        if metrics.get("student_count") is not None:
            lines.append(f"- นักศึกษาทั้งหมด: {metrics['student_count']} คน (แหล่งหลัก: MongoDB students)")
        if metrics.get("advisor_count") is not None:
            lines.append(f"- Advisor ทั้งหมด: {metrics['advisor_count']} คน (แหล่งหลัก: MongoDB advisors)")
        if metrics.get("program_count") is not None:
            lines.append(f"- หลักสูตรใน PostgreSQL directory: {metrics['program_count']} รายการ")
        if metrics.get("uploaded_document_count") is not None:
            lines.append(f"- ไฟล์ PDF/Excel/CSV ที่เข้าถึงได้: {metrics['uploaded_document_count']} ไฟล์")
        if support.get("student_subject_links") is not None:
            lines.append(f"- ตาราง student_subjects มี {support['student_subject_links']} แถว ซึ่งเป็นความสัมพันธ์ student–subject ไม่ใช่จำนวนนักศึกษาทั้งมหาวิทยาลัย")
        lines.append("หมายเหตุ: หากตัวเลขใน PostgreSQL relationship table ต่างจาก MongoDB students ให้ใช้ MongoDB students เป็นจำนวนหลักของนักศึกษาเสมอ")
        return "\n".join(lines)

    lines = ["University overview from verified source-of-truth data:"]
    if metrics.get("student_count") is not None:
        lines.append(f"- Students: {metrics['student_count']} total (canonical source: MongoDB students)")
    if metrics.get("advisor_count") is not None:
        lines.append(f"- Advisors: {metrics['advisor_count']} total (canonical source: MongoDB advisors)")
    if metrics.get("program_count") is not None:
        lines.append(f"- Programs in the PostgreSQL directory: {metrics['program_count']}")
    if metrics.get("uploaded_document_count") is not None:
        lines.append(f"- Uploaded PDF/Excel/CSV files available: {metrics['uploaded_document_count']}")
    if support.get("student_subject_links") is not None:
        lines.append(f"- PostgreSQL student_subjects has {support['student_subject_links']} relationship row(s); this is not the total student population.")
    lines.append("For total students, profiles, GPA, and grades, MongoDB students is the authoritative source.")
    return "\n".join(lines)
