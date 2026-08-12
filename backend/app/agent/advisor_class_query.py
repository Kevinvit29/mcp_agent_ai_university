"""Strict classroom-scoped query contracts for signed advisor accounts.

An advisor is not a smaller administrator. The advisor may identify students
only through ``student_subjects`` rows assigned to that advisor, and may answer
only with facts recorded for that same advisor + course relationship.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.agent.natural_query import normalize_typos


def _low(message: str) -> str:
    return normalize_typos(message or "").lower().strip()


def _student_ids(message: str) -> list[str]:
    return list(dict.fromkeys(
        value.upper()
        for value in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I)
    ))


def _top_n(text: str, default: int = 20) -> int:
    match = re.search(r"\b(?:top|bottom|first|last)\s+(\d{1,3})\b", text)
    if not match:
        match = re.search(r"\b(\d{1,3})\s+(?:students?|learners?)\b", text)
    if match:
        return max(1, min(int(match.group(1)), 100))
    if any(term in text for term in ("highest", "lowest", "best", "worst")):
        return 1
    return default


def _course_hint(message: str) -> str:
    """Extract a likely class name while leaving final matching to PostgreSQL."""
    raw = str(message or "").strip()
    code = re.search(r"\b[A-Z]{2,8}\s?\d{2,4}\b", raw, flags=re.I)
    if code:
        return code.group(0).upper().replace(" ", "")
    patterns = (
        r"\b(?:learn|learning|study|studies|studying|take|taking|enrolled\s+in)\s+(.+)$",
        r"\b(?:grade|score|attendance|assessment|students?|learners?)\s+(?:in|for|of)\s+(.+)$",
        r"\b(?:in|for)\s+(?:my\s+)?(?:course|class|subject)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.I)
        if not match:
            continue
        value = re.sub(
            r"\b(?:course|class|subject|please|today|this\s+term)\b[?.!]*$",
            "",
            match.group(1),
            flags=re.I,
        ).strip(" ?.!,'\"")
        value = re.sub(r"\s+in\s+my$", "", value, flags=re.I).strip()
        if re.fullmatch(r"(?:my\s+)?(?:students?|learners?)\s+(?:i\s+)?teach", value, flags=re.I):
            return ""
        if value and value.lower() not in {"my", "the", "this", "that"}:
            return value
    return ""


def parse_advisor_class_query(message: str) -> Optional[Dict[str, Any]]:
    """Return a course-scoped query or an explicit advisor access boundary."""
    text = _low(message)
    if not text:
        return None

    student_ids = _student_ids(message)
    classroom_signal = any(term in text for term in (
        "student", "learner", "class", "course", "subject", "teach", "enroll",
        "study", "learn", "grade", "score", "attendance", "assessment", "exam",
        "นักศึกษา", "นักเรียน", "ชั้นเรียน", "วิชา", "สอน", "เกรด", "คะแนน", "เข้าเรียน",
    )) or bool(student_ids)
    if not classroom_signal:
        return None

    forbidden = {
        "gpa": "gpa",
        "tuition": "financial information",
        "finance": "financial information",
        "balance": "financial information",
        "scholarship": "scholarship information",
        "risk": "university-wide risk information",
        "academic status": "academic status",
        "full profile": "student profile",
        "profile": "student profile",
        "email": "contact information",
        "phone": "contact information",
        "address": "contact information",
        "national id": "identity information",
        "passport": "identity information",
        "program": "program information",
        "major": "program information",
        "faculty": "faculty information",
        "graduation": "graduation information",
        "all information": "full student information",
        "everything about": "full student information",
    }
    denied = list(dict.fromkeys(label for term, label in forbidden.items() if term in text))
    if denied:
        return {
            "type": "advisor_scope_denial",
            "reason": "advisor_classroom_scope_only",
            "denied_fields": denied,
            "student_ids": student_ids,
            "answer_style": "advisor_scope",
        }

    course_hint = _course_hint(message)
    requested_metrics: list[str] = []
    if any(term in text for term in ("grade", "score", "mark", "result", "เกรด", "คะแนน")):
        requested_metrics.append("grade")
    if any(term in text for term in ("attendance", "absence", "absent", "เข้าเรียน", "ขาดเรียน")):
        requested_metrics.append("attendance")
    if any(term in text for term in ("assessment", "exam", "midterm", "final", "quiz", "สอบ")):
        requested_metrics.append("assessments")

    if (
        any(term in text for term in ("my classes", "my courses", "my subjects", "classes i teach", "courses i teach", "subjects i teach"))
        and not student_ids
        and not requested_metrics
    ):
        operation = "class_list"
        answer_style = "advisor_class_list"
    elif any(term in text for term in ("how many", "count", "number of", "กี่", "จำนวน")):
        operation = "class_count"
        answer_style = "advisor_class_count"
    elif any(term in text for term in ("average", "mean", "pass rate", "summary")) and requested_metrics:
        operation = "class_summary"
        answer_style = "advisor_class_summary"
    elif (
        any(term in text for term in ("rank", "top", "bottom", "highest", "lowest", "best", "worst"))
        and ("student" in text or "learner" in text)
    ):
        operation = "class_records"
        answer_style = "advisor_class_records"
    elif any(term in text for term in ("who", "list", "names", "roster", "which students", "รายชื่อ", "ใคร")) and not requested_metrics:
        operation = "class_roster"
        answer_style = "advisor_class_roster"
    else:
        operation = "class_records"
        answer_style = "advisor_class_records"

    direction = "asc" if any(term in text for term in ("bottom", "lowest", "worst")) else "desc"
    return {
        "type": "advisor_classroom",
        "query_type": "advisor_classroom",
        "operation": operation,
        "course_query": course_hint,
        "student_ids": student_ids,
        "requested_metrics": requested_metrics or ["grade"],
        "direction": direction,
        "top_n": _top_n(text),
        "answer_style": answer_style,
        "reason": "Use only signed-advisor student_subjects rows and same-advisor same-course academic facts.",
    }
