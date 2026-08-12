"""Entity extractor for Agent Orchestrator V2.

This module is intentionally deterministic.  The AI planner may be flexible, but
fresh explicit entities from the user's latest message must always win over chat
history and learning-memory rules.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


ENTITY_STOP_WORDS = {
    "all",
    "analytics",
    "attendance",
    "business",
    "for",
    "gpa",
    "grade",
    "grades",
    "of",
    "program",
    "show",
    "student",
    "students",
    "subject",
    "the",
    "their",
}


def _unique_upper(matches: List[str]) -> List[str]:
    seen: List[str] = []
    for item in matches:
        value = str(item).upper().strip()
        if value and value not in seen:
            seen.append(value)
    return seen


def _low(text: str) -> str:
    return (text or "").lower().strip()


def normalize_entity_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-zA-Zก-๙0-9\s-]", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def extract_last_names(message: str) -> List[str]:
    """Extract an explicitly requested family/surname from the latest message."""
    text = normalize_entity_text(message)
    patterns = [
        r"(?:gpa|grade|grades|attendance)\s+(?:of|for)\s+([a-zA-Zก-๙-]+)",
        r"(?:students?|student)\s+(?:named|with last name|surname)\s+([a-zA-Zก-๙-]+)",
        r"([a-zA-Zก-๙-]+)\s+family\b",
        r"(?:surname|last name|family name)\s+([a-zA-Zก-๙-]+)",
        r"(?:นามสกุล|เกรดของ|เกรด)\s*([ก-๙a-zA-Z-]+)",
    ]
    found: List[str] = []
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = normalize_entity_text(match.group(1))
        if candidate and candidate not in ENTITY_STOP_WORDS and candidate not in found:
            found.append(candidate)
    return found


def extract_entities(message: str) -> Dict[str, Any]:
    text = message or ""
    low = _low(text)

    student_ids = _unique_upper(re.findall(r"\bS\d{3,6}\b", text, flags=re.I))
    advisor_ids = _unique_upper(re.findall(r"\bA\d{3,6}\b", text, flags=re.I))
    last_names = extract_last_names(text)

    domains: List[str] = []
    def add(domain: str) -> None:
        if domain not in domains:
            domains.append(domain)

    if student_ids or last_names or any(w in low for w in ["student", "students", "นักเรียน", "นักศึกษา"]):
        add("students")
    if advisor_ids or any(w in low for w in ["advisor", "advisors", "teacher", "อาจารย์", "ที่ปรึกษา"]):
        add("advisors")
    if any(w in low for w in ["subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา"]):
        add("subjects")
    if any(w in low for w in ["grade", "grades", "score", "scores", "คะแนน", "เกรด"]):
        add("grades")
    if any(w in low for w in ["gpa", "เกรดเฉลี่ย"]):
        add("gpa")
    if any(w in low for w in ["pdf", "document", "documents", "file", "files", "excel", "xlsx", "xls", "csv", "upload", "uploaded", "เอกสาร", "ไฟล์", "เอ็กเซล"]):
        add("documents")
    if any(w in low for w in ["program", "programs", "major", "faculty", "department", "หลักสูตร", "สาขา", "คณะ"]):
        add("programs")
    if any(w in low for w in ["cafeteria", "canteen", "library", "building", "room", "office", "location", "โรงอาหาร", "ห้องสมุด", "อาคาร", "ห้อง"]):
        add("campus_info")

    count_request = bool(re.search(r"\b(how many|count|number of|total)\b", low) or any(w in low for w in ["กี่", "จำนวน"]))
    list_request = bool(re.search(r"\b(list|show|all|which|what are)\b", low) or any(w in low for w in ["รายชื่อ", "แสดง", "ทั้งหมด"]))

    return {
        "student_ids": student_ids,
        "advisor_ids": advisor_ids,
        "last_names": last_names,
        "has_student_id": bool(student_ids),
        "has_advisor_id": bool(advisor_ids),
        "domains": domains,
        "count_request": count_request,
        "list_request": list_request,
        "latest_message_has_explicit_entity": bool(student_ids or advisor_ids or last_names),
    }


def wants_profile_or_info(message: str) -> bool:
    text = _low(message)
    keywords = [
        "profile", "information", "info", "detail", "details", "record", "data", "full", "about",
        "ข้อมูล", "ประวัติ", "รายละเอียด",
    ]
    return any(k in text for k in keywords)
