"""Natural-language contracts for a signed student's own studied subjects."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.agent.natural_query import normalize_typos


def _clean_course(value: str) -> str:
    value = re.sub(r"\b(?:right now|currently|this term|this semester)\b", "", value, flags=re.I)
    return value.strip(" ?.!,'\"")


def parse_student_own_course_query(message: str) -> Optional[Dict[str, Any]]:
    raw = str(message or "").strip()
    text = normalize_typos(raw).lower().strip()
    if not text:
        return None

    membership_patterns = (
        r"\bdo\s+i\s+(?:study|take|learn)\s+(.+)$",
        r"\bam\s+i\s+(?:enrolled|registered)\s+in\s+(.+)$",
        r"\bis\s+(.+?)\s+(?:one\s+of\s+)?my\s+(?:subjects?|courses?|classes?)\b",
        r"\b(?:ฉัน|ผม|หนู)\s*(?:เรียน|ลงทะเบียน)\s*(.+?)(?:ไหม|หรือไม่)?$",
    )
    for pattern in membership_patterns:
        match = re.search(pattern, raw, flags=re.I)
        if not match:
            continue
        course_query = _clean_course(match.group(1))
        if course_query:
            return {
                "type": "student_own_course",
                "operation": "course_membership",
                "course_query": course_query,
                "answer_style": "student_course_membership",
                "reason": "Check only the signed student's recorded subject grades for the named course.",
            }

    list_patterns = (
        r"\bwhich\s+(?:subjects?|courses?|classes?)\s+do\s+i\s+(?:study|take|learn)\b",
        r"\bwhat\s+(?:subjects?|courses?|classes?)\s+(?:do\s+i\s+(?:study|take)|am\s+i\s+(?:taking|studying))\b",
        r"\b(?:my|mine)\s+(?:studied\s+)?(?:subjects?|courses?|classes?)\b",
        r"(?:ฉัน|ผม|หนู).*(?:เรียน|ลงทะเบียน).*(?:วิชา|รายวิชา)",
    )
    performance_signal = any(term in text for term in (
        "grade", "score", "best", "worst", "highest", "lowest", "average",
        "rank", "ranking", "pass rate", "attendance",
        "เกรด", "คะแนน", "สูงสุด", "ต่ำสุด", "เฉลี่ย", "เข้าเรียน",
    ))
    if not performance_signal and any(re.search(pattern, text, flags=re.I) for pattern in list_patterns):
        return {
            "type": "student_own_course",
            "operation": "list_subjects",
            "course_query": "",
            "answer_style": "student_course_list",
            "reason": "List only subject assignments attached to the signed student.",
        }
    return None
