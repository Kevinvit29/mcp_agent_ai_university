"""Latest-message data contract for Agent Orchestrator V4.

The LLM is allowed to interpret context and purpose, but the newest user message
still creates a hard contract for exact entities and requested answer shape.
This prevents errors like:
- user asks "S099 profile" but final answer gives only grades
- user asks "S035 grade" but old context returns S001

This is not a keyword-only router. It is a safety contract applied after AI
purpose reasoning so the AI's plan cannot contradict the latest message.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.agent.natural_query import normalize_typos
from app.agent.aggregate_query import (
    parse_student_study_query,
    parse_student_metric_query,
    parse_student_statistic_query,
    parse_subject_ranking_query,
    parse_student_ranking_query,
)
from app.agent.entity_extractor import extract_entities
from app.agent.request_semantics import request_semantics
from app.agent.academic_query import parse_academic_query
from app.agent.analytics_query import parse_database_analytics_query

GRADE_WORDS = {"grade", "grades", "score", "scores", "mark", "marks", "เกรด", "คะแนน"}
GPA_WORDS = {"gpa", "เกรดเฉลี่ย"}
SUBJECT_WORDS = {"subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา"}
PROFILE_WORDS = {
    "profile", "information", "info", "record", "records", "detail", "details", "data",
    "full", "everything", "all data", "ข้อมูล", "โปรไฟล์", "รายละเอียด", "ประวัติ", "ทุกอย่าง", "ทั้งหมด",
}
NAME_WORDS = {"name", "names", "ชื่อ", "รายชื่อ"}
DOCUMENT_WORDS = {
    "pdf", "document", "documents", "file", "files", "excel", "xlsx", "xls", "csv",
    "spreadsheet", "sheet", "upload", "uploaded", "quote", "citation", "cite", "source excerpt",
    "เอกสาร", "ไฟล์", "เอ็กเซล", "ชีต", "อ้างอิง",
}
ADVISOR_WORDS = {"advisor", "advisors", "teacher", "teachers", "อาจารย์", "ที่ปรึกษา"}
PROGRAM_WORDS = {"program", "programs", "major", "majors", "faculty", "department", "หลักสูตร", "สาขา", "คณะ"}
COUNT_WORDS = {"how many", "count", "number of", "total", "กี่", "จำนวน", "ทั้งหมดกี่"}
LIST_WORDS = {"list", "show", "all", "what are", "which", "รายชื่อ", "แสดง", "ทั้งหมด"}

def _low(text: str) -> str:
    return normalize_typos(text or "").lower().strip()


def _has_any(text: str, words: set[str]) -> bool:
    return any(w in text for w in words)


def _student_ids(message: str) -> List[str]:
    ids: List[str] = []
    for sid in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I):
        sid = sid.upper()
        if sid not in ids:
            ids.append(sid)
    return ids


def _advisor_ids(message: str) -> List[str]:
    ids: List[str] = []
    for aid in re.findall(r"\bA\d{3,6}\b", message or "", flags=re.I):
        aid = aid.upper()
        if aid not in ids:
            ids.append(aid)
    return ids


def requested_student_answer_style(message: str) -> str:
    """Return the exact student answer shape requested by the latest message.

    Priority matters. "profile" is broader than grades and must win, because a
    profile row can include subject_grades but the answer should not collapse
    into only grades. Explicit GPA wins over generic grade words when both exist.
    """
    text = _low(message)
    if _has_any(text, PROFILE_WORDS):
        return "profile"
    if _has_any(text, GPA_WORDS) and _has_any(text, GRADE_WORDS | SUBJECT_WORDS):
        return "student_multi"
    if _has_any(text, GPA_WORDS):
        return "gpa"
    if _has_any(text, GRADE_WORDS | SUBJECT_WORDS):
        return "grades"
    if _has_any(text, NAME_WORDS):
        return "names"
    
    return "summary"


def requested_student_components(message: str) -> List[str]:
    """Return every student-master component explicitly requested."""
    text = _low(message)
    components: List[str] = []
    if _has_any(text, PROFILE_WORDS):
        components.append("profile")
    if _has_any(text, GPA_WORDS):
        components.append("gpa")
    if _has_any(text, GRADE_WORDS | SUBJECT_WORDS):
        components.append("grades")
    if _has_any(text, NAME_WORDS):
        components.append("names")
    return components


def build_latest_message_contract(message: str) -> Dict[str, Any]:
    extracted = extract_entities(message)
    extracted_last_names = extracted["last_names"]
    text = _low(message)
    semantics = request_semantics(message)
    student_ids = extracted["student_ids"]
    advisor_ids = extracted["advisor_ids"]
    answer_style = requested_student_answer_style(message)
    student_components = requested_student_components(message)
    analytics_query = parse_database_analytics_query(message)

    domain = "normal_chat"
    intent = "read"
    subject_ranking = parse_subject_ranking_query(message)
    student_ranking = parse_student_ranking_query(message)
    academic_query = parse_academic_query(message)
    study_query = parse_student_study_query(message)
    stat_query = parse_student_statistic_query(message)
    metric_query = parse_student_metric_query(message)
    if analytics_query:
        intent = "rank" if analytics_query.get("operation") in {"group_rank", "rank_students"} else "aggregate"
        answer_style = analytics_query.get("answer_style") or answer_style
    elif academic_query:
        intent = academic_query["intent"]
        answer_style = academic_query["answer_style"]
    elif subject_ranking:
        intent = "rank"
        answer_style = "subject_rank"
    elif student_ranking:
        intent = "rank"
        answer_style = "student_rank"
    elif stat_query:
        intent = "aggregate"
    elif _has_any(text, COUNT_WORDS):
        intent = "count"
    elif study_query and isinstance(study_query.get("ranking"), dict):
        intent = "rank"
    elif _has_any(text, LIST_WORDS):
        intent = "list"

    # Explicit entities define the current target. History/memory cannot replace them.
    if analytics_query and analytics_query.get("type") == "capability_limitation":
        domain = "clarify"
        intent = "clarify"
    elif analytics_query and analytics_query.get("type") == "database_analytics":
        domain = "students" if analytics_query.get("source") == "mongo" else "academic_records"
    elif analytics_query and analytics_query.get("type") in {"student_count", "student_ranking", "student_benchmark", "rank_with_academic"}:
        domain = "students"
    elif semantics["is_realtime_request"]:
        domain = "clarify"
        intent = "clarify"
    elif semantics["is_schema_request"]:
        domain = "database_map"
    elif academic_query:
        domain = academic_query["domain"]
    elif student_ids or extracted_last_names:
        domain = "students"
    elif advisor_ids or _has_any(text, ADVISOR_WORDS):
        domain = "advisors"
    elif _has_any(text, DOCUMENT_WORDS):
        domain = "documents"
    elif subject_ranking:
        domain = "subjects"
    elif student_ranking:
        domain = "students"
    elif stat_query:
        domain = "students"
    elif study_query:
        domain = "students"
    elif _has_any(text, SUBJECT_WORDS):
        domain = "subjects"
    elif _has_any(text, PROGRAM_WORDS):
        domain = "programs"
    elif (
        metric_query
        or _has_any(text, GPA_WORDS | GRADE_WORDS)
        or any(w in text for w in ["student", "students", "นักศึกษา", "นักเรียน"])
    ):
        domain = "students"

    if domain == "students" and student_ids:
        if answer_style == "gpa":
            purpose_domain = "student_gpa"
        elif answer_style == "grades":
            purpose_domain = "student_grades"
        else:
            purpose_domain = "students"
    else:
        purpose_domain = domain

    study_term = (
        stat_query.get("study_term")
        if isinstance(stat_query, dict)
        else (study_query.get("study_term") if isinstance(study_query, dict) else None)
    )

    return {
        "version": "v4_latest_message_contract",
        "student_ids": student_ids,
        "advisor_ids": advisor_ids,
        "last_names": extracted_last_names,
        "domain": domain,
        "purpose_domain": purpose_domain,
        "answer_style": answer_style,
        "student_components": student_components,
        "intent": intent,
        "must_use_latest_entities":  bool(
            student_ids
            or advisor_ids
            or study_term
            or extracted_last_names
        ),
        "must_not_use_previous_entities": bool(student_ids or advisor_ids or extracted_last_names),
        "study_query": study_query,
        "stat_query": stat_query,
        "metric_query": metric_query,
        "study_term": study_term,
        "statistic": stat_query.get("statistic") if isinstance(stat_query, dict) else None,
        "ranking": (
            student_ranking
            if isinstance(student_ranking, dict)
            else (study_query.get("ranking") if isinstance(study_query, dict) else None)
        ),
        "student_ranking": student_ranking,
        "subject_ranking": subject_ranking,
        "academic_query": academic_query,
        "analytics_query": analytics_query,
        "reason": "Latest message contract: explicit entities and requested answer shape from the current user text override older context and AI ambiguity.",
        "presentation": {"view": "table" if semantics["wants_table"] else "text","want_report": semantics["wants_report"],
        },
        "is_schema_request": semantics["is_schema_request"],
        "is_realtime_request": semantics["is_realtime_request"],
    }


def apply_contract_to_purpose(message: str, purpose: Dict[str, Any]) -> Dict[str, Any]:
    """Safely align AI purpose JSON with the latest-message contract."""
    contract = build_latest_message_contract(message)
    result = dict(purpose or {})
    entities = result.get("explicit_entities") if isinstance(result.get("explicit_entities"), dict) else {}
    entities = dict(entities)

    if contract["is_realtime_request"]:
        result["target_domain"] = "clarify"
        result["answer_intent"] = "clarify"
        result["should_use_database"] = False
        result["message_type"] = "clarify"
        result["use_history"] = False

    # The current message must override an incorrect AI fallback route.
    # Example: "list students as a table" is student data with table presentation,
    # not a database schema request.
    if contract["domain"] == "students" and not contract["is_schema_request"]:
        result["target_domain"] = "students"
        result["answer_intent"] = contract["intent"]
        result["should_use_database"] = True
        result["message_type"] = "new_request"
        result["use_history"] = False

    if contract["domain"] == "subjects":
        result["target_domain"] = "subjects"
        result["answer_intent"] = contract["intent"]
        result["should_use_database"] = True
        result["message_type"] = "new_request"
        result["use_history"] = False

    if contract["domain"] in {"academic_records", "course_catalog"}:
        result["target_domain"] = contract["domain"]
        result["answer_intent"] = contract["intent"]
        result["should_use_database"] = True
        result["message_type"] = "new_request"
        result["use_history"] = False
        result["academic_query"] = contract["academic_query"]

    if contract["domain"] == "documents":
        result["target_domain"] = "documents"
        result["answer_intent"] = contract["intent"]
        result["should_use_database"] = True
        result["message_type"] = "new_request"
        result["use_history"] = False

    if (
        contract["domain"] == "clarify"
        and isinstance(contract.get("analytics_query"), dict)
        and contract["analytics_query"].get("type") == "capability_limitation"
    ):
        result["target_domain"] = "clarify"
        result["answer_intent"] = "clarify"
        result["should_use_database"] = False
        result["message_type"] = "clarify"
        result["use_history"] = False

    if contract["domain"] == "database_map" and contract["is_schema_request"]:
        result["target_domain"] = "database_map"
        result["should_use_database"] = True

    if contract["student_ids"]:
        entities["student_ids"] = contract["student_ids"]
        entities["advisor_ids"] = []
        entities["last_names"] = []
        result["target_domain"] = contract["purpose_domain"]
        result["should_use_database"] = True
        result["message_type"] = "new_request"
        result["must_not_use_previous_entities"] = True
        result["use_history"] = False
    if contract["advisor_ids"]:
        entities["advisor_ids"] = contract["advisor_ids"]
        entities["student_ids"] = []
        entities["last_names"] = []
        result["target_domain"] = "advisors"
        result["should_use_database"] = True
        result["message_type"] = "new_request"
        result["must_not_use_previous_entities"] = True
        result["use_history"] = False
    if contract["last_names"]:
        entities["last_names"] = contract["last_names"]
        entities["student_ids"] = []
        entities["advisor_ids"] = []
        result["target_domain"] = "students"
        result["should_use_database"] = True
        result["message_type"] = "new_request"
        result["must_not_use_previous_entities"] = True
        result["use_history"] = False

    # Academic operations are more specific than a generic student-ID lookup.
    # Example: "S001 attendance" must use PostgreSQL attendance summaries, not
    # the MongoDB student profile merely because the message contains S001.
    if contract["domain"] in {"academic_records", "course_catalog"}:
        result["target_domain"] = contract["domain"]
        result["answer_intent"] = contract["intent"]
        result["academic_query"] = contract["academic_query"]
        result["should_use_database"] = True

    # A real-time limitation always wins over a database entity. The system can
    # retrieve stored records but must not imply live tracking or live activity.
    if contract["is_realtime_request"]:
        result["target_domain"] = "clarify"
        result["answer_intent"] = "clarify"
        result["should_use_database"] = False

    # For current-message profile/GPA/grade requests, force the answer shape even
    # when AI purpose reasoning picked a related but wrong subdomain.
    result["explicit_entities"] = entities
    result["latest_message_contract"] = contract
    result["requested_answer_style"] = contract["answer_style"]
    if contract["domain"] not in {"normal_chat", "clarify"} and not result.get("target_domain"):
        result["target_domain"] = contract["purpose_domain"]
    if contract["domain"] not in {"normal_chat", "clarify"}:
        result["should_use_database"] = True
    return result
