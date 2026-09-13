"""Deterministic parser for normalized academic and operational questions.

MongoDB remains authoritative for student master data, GPA, and grades.  This
module detects questions whose authoritative source is one of the normalized
PostgreSQL academic tables so an explicit student ID does not accidentally
send an attendance, enrollment, finance, or scholarship question to MongoDB.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.natural_query import normalize_typos


ATTENDANCE_WORDS = {
    "attendance", "attended", "absence", "absences", "absent", "present",
    "เข้าเรียน", "การเข้าเรียน", "ขาดเรียน", "เช็คชื่อ",
}
ENROLLMENT_WORDS = {
    "enrollment", "enrolment", "enrolled", "registered course", "registered courses",
    "current courses", "course registration", "currently taking", "this semester",
    "this term", "semester courses", "term courses", "ลงทะเบียน", "วิชาที่ลง",
    "รายวิชาที่ลง", "ภาคเรียน", "เทอม",
}
ASSESSMENT_WORDS = {
    "assessment result", "assessment results", "quiz score", "quiz result",
    "midterm score", "midterm result", "midterm results", "exam result",
    "exam results", "final result", "final exam score", "project score",
    "ผลการประเมิน", "คะแนนควิซ",
    "คะแนนกลางภาค", "คะแนนปลายภาค",
}
FINANCE_WORDS = {
    "tuition", "balance", "amount paid", "payment status", "financial account",
    "fee balance", "fees due", "ค่าเทอม", "ยอดค้าง", "ยอดชำระ", "การชำระเงิน",
}
SCHOLARSHIP_WORDS = {
    "scholarship", "scholarships", "ทุน", "ทุนการศึกษา",
}
SUPPORT_WORDS = {
    "support case", "support cases", "student case", "student cases",
    "เคสช่วยเหลือ", "กรณีช่วยเหลือ",
}
RISK_WORDS = {
    "academic risk", "risk level", "at risk", "risk summary",
    "ความเสี่ยง", "เสี่ยงทางการเรียน",
}
CREDIT_WORDS = {
    "credits earned", "credits required", "graduation progress", "graduate progress",
    "หน่วยกิตสะสม", "หน่วยกิตที่ต้อง", "ความคืบหน้าการจบ",
}
CATALOG_WORDS = {
    "course catalog", "course catalogue", "catalog of courses", "available courses",
    "course code", "course codes", "หลักสูตรรายวิชา", "แคตตาล็อกวิชา",
    "รหัสวิชา", "รายวิชาที่เปิด",
}
OVERVIEW_WORDS = {
    "academic dataset overview", "academic overview", "university academic overview",
    "ภาพรวมข้อมูลการศึกษา", "ภาพรวมวิชาการ",
}
SELF_WORDS = {
    "my", "me", "mine", "my own", "ของฉัน", "ของผม", "ของหนู", "ของเรา",
}
GPA_WORDS = {"gpa", "เกรดเฉลี่ย"}
GRADE_WORDS = {"grade", "grades", "subject grade", "subject grades", "เกรด", "ผลการเรียน"}
MASTER_PROFILE_WORDS = {"profile", "student profile", "โปรไฟล์", "ประวัตินักศึกษา"}


def _low(message: str) -> str:
    return normalize_typos(message or "").lower().strip()


def _has_any(text: str, words: set[str]) -> bool:
    return any(word in text for word in words)


def _has_grade_request(text: str) -> bool:
    # Word boundaries matter: "graduation" must not be read as "grade".
    return bool(re.search(r"\b(?:grade|grades)\b", text)) or any(
        word in text for word in {"เกรด", "ผลการเรียน"}
    )


def _student_ids(message: str) -> List[str]:
    result: List[str] = []
    for value in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I):
        value = value.upper()
        if value not in result:
            result.append(value)
    return result


def parse_academic_query(message: str) -> Optional[Dict[str, Any]]:
    """Return a normalized PostgreSQL academic query contract, if applicable."""
    text = _low(message)
    student_ids = _student_ids(message)
    is_self = _has_any(text, SELF_WORDS)

    query_type = ""
    answer_style = ""
    requested_sections: List[str] = []
    requested_section_styles: Dict[str, str] = {}
    domain = "academic_records"
    intent = "read"

    if _has_any(text, OVERVIEW_WORDS):
        query_type = "academic_overview"
        answer_style = "academic_overview"
        intent = "summarize"
    elif _has_any(text, CATALOG_WORDS):
        query_type = "course_catalog"
        answer_style = "course_catalog"
        domain = "course_catalog"
        intent = "list"
    else:
        requested: List[tuple[str, str]] = []
        if _has_any(text, ATTENDANCE_WORDS):
            requested.append(("attendance", "attendance"))
        if _has_any(text, ASSESSMENT_WORDS):
            requested.append(("assessments", "assessments"))
        if _has_any(text, FINANCE_WORDS):
            requested.append(("financial_accounts", "finance"))
        if _has_any(text, SCHOLARSHIP_WORDS):
            requested.append(("scholarship_awards", "scholarship"))
        if _has_any(text, SUPPORT_WORDS):
            requested.append(("support_cases", "support_cases"))
        if _has_any(text, CREDIT_WORDS):
            requested.extend([("profile", "graduation_progress"), ("enrollments", "graduation_progress")])
        if (student_ids or is_self) and _has_any(text, ENROLLMENT_WORDS):
            requested.append(("enrollments", "enrollments"))

        has_risk = _has_any(text, RISK_WORDS)
        if has_risk and not (student_ids or is_self) and not requested:
            query_type = "academic_risk_summary"
            answer_style = "academic_risk_summary"
            intent = "summarize"
        else:
            if has_risk:
                requested.append(("profile", "academic_risk"))
            if not requested:
                return None
            query_type = "student_academic_profile"
            for section, style in requested:
                if section not in requested_sections:
                    requested_sections.append(section)
                requested_section_styles[section] = style
            styles = [style for _, style in requested]
            answer_style = styles[0]
            if "graduation_progress" in styles:
                answer_style = "graduation_progress"

    student_master_sections: List[str] = []
    if query_type == "student_academic_profile":
        if _has_any(text, MASTER_PROFILE_WORDS):
            student_master_sections.append("profile")
        if _has_any(text, GPA_WORDS):
            student_master_sections.append("gpa")
        if _has_grade_request(text):
            student_master_sections.append("grades")
        # Some answers intentionally read more than one table for a single
        # requested component (graduation progress uses profile + enrollment).
        requested_part_count = len(set(requested_section_styles.values())) + len(student_master_sections)
        if requested_part_count > 1:
            answer_style = "academic_multi"

    return {
        "version": "v30_academic_query_v1",
        "domain": domain,
        "query_type": query_type,
        "answer_style": answer_style,
        "requested_sections": requested_sections,
        "requested_section_styles": requested_section_styles,
        "student_master_sections": student_master_sections,
        "student_ids": student_ids,
        "is_self_request": is_self,
        "intent": intent,
        "reason": (
            "The requested facts are authoritative in normalized PostgreSQL "
            "academic tables, not in MongoDB student master records."
        ),
    }
