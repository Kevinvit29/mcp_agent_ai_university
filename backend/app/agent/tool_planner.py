"""Tool Planner for Agent Orchestrator V2.

The planner is two-layered:
1) Deterministic guards for high-risk university data questions.
2) Gemini strict JSON planner with schema registry for flexible questions.

The output is always converted into an MCP-safe plan shape already used by the
existing backend.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.agent.ai_client import ai_generate_text
from app.agent.entity_extractor import extract_entities
from app.agent.natural_query import normalize_typos, document_list_request, friendly_clean_query
from app.agent.schema_registry import get_schema_registry_for_role, allowed_student_fields_for_role, STUDENT_FIELDS_ADMIN
from app.agent.query_planner_ai import create_universal_admin_plan, build_mcp_plan_from_universal
from app.agent.purpose_contract import build_latest_message_contract
from app.agent.aggregate_query import (
    parse_student_metric_query,
    parse_student_study_query,
    parse_student_statistic_query,
    parse_total_student_count_query,
    parse_subject_ranking_query,
    parse_student_ranking_query,
)
from app.agent.request_semantics import request_semantics
from app.agent.academic_query import parse_academic_query
from app.agent.analytics_query import parse_database_analytics_query
from app.agent.advisor_class_query import parse_advisor_class_query
from app.agent.student_scope import enforce_student_scope_plan
from app.agent.student_own_query import parse_student_own_course_query

COUNT_WORDS = {"how many", "count", "number of", "total", "กี่", "จำนวน", "ทั้งหมดกี่"}
LIST_WORDS = {"list", "show", "all", "what are", "which", "รายชื่อ", "แสดง", "ทั้งหมด"}
SUBJECT_WORDS = {"subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา"}
STUDENT_WORDS = {"student", "students", "นักเรียน", "นักศึกษา"}
GRADE_WORDS = {"grade", "grades", "score", "scores", "คะแนน", "เกรด"}
GPA_WORDS = {"gpa", "เกรดเฉลี่ย"}
PROFILE_WORDS = {"profile", "information", "info", "record", "details", "detail", "data", "ข้อมูล", "โปรไฟล์", "รายละเอียด"}
DOCUMENT_WORDS = {"pdf", "document", "documents", "file", "files", "excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "upload", "uploaded", "เอกสาร", "ไฟล์", "อัปโหลด", "ชีต", "เอ็กเซล"}
ADVISOR_WORDS = {"advisor", "advisors", "teacher", "teachers", "อาจารย์", "ที่ปรึกษา"}
PROGRAM_WORDS = {"program", "programs", "major", "majors", "faculty", "department", "คณะ", "สาขา", "หลักสูตร"}
CAMPUS_WORDS = {"cafeteria", "canteen", "library", "building", "room", "office", "location", "map", "โรงอาหาร", "ห้องสมุด", "อาคาร", "ห้อง", "อยู่ไหน"}
DATABASE_MAP_WORDS = {"database", "schema", "collection", "field", "structure", "ฐานข้อมูล", "โครงสร้าง", "คอลัมน์"}


def _low(message: str) -> str:
    return normalize_typos(message or "").lower().strip()


def _contains_any(text: str, words: set[str]) -> bool:
    return any(w in text for w in words)


def _has_count(text: str) -> bool:
    return any(w in text for w in COUNT_WORDS)


def _has_university_data_signal(text: str) -> bool:
    signal_sets = (
        SUBJECT_WORDS, STUDENT_WORDS, GRADE_WORDS, GPA_WORDS, PROFILE_WORDS, DOCUMENT_WORDS,
        ADVISOR_WORDS, PROGRAM_WORDS, CAMPUS_WORDS, DATABASE_MAP_WORDS,
    )
    return any(_contains_any(text, s) for s in signal_sets) or bool(re.search(r"\b[SA]\d{3,6}\b", text, flags=re.I))


def _is_document_query(message: str) -> bool:
    text = _low(message)
    # ASCII file words require boundaries. A substring check incorrectly finds
    # "file" inside "profile" and routes "S001 profile" to document search.
    if re.search(
        r"\b(?:pdf|documents?|files?|excel|xlsx|xls|csv|spreadsheets?|sheets?|uploads?|uploaded|quote|citation|cite)\b",
        text,
        flags=re.I,
    ):
        return True
    return any(word in text for word in {"เอกสาร", "ไฟล์", "เอ็กเซล", "ชีต", "อัปโหลด"})


def _normal_chat_plan(message: str, language: str, role: str, requester_student_id: Optional[str], requester_advisor_id: Optional[str], reason: str) -> Dict[str, Any]:
    return _base_plan(
        message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
        selected_agent=f"{role}_normal_chat_agent", tool_name="none", arguments={"reason": "normal_chat", "answer_style": "short"},
        prompt="ADMIN_NORMAL_CHATGPT_PROMPT" if role == "admin" else ("ADVISOR_AGENT_PROMPT" if role == "advisor" else "STUDENT_AGENT_PROMPT"),
        intent="normal_chat", domain="normal_chat", confidence=0.93, reason=reason,
    )


def _student_ids(message: str) -> List[str]:
    ids: List[str] = []
    for sid in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I):
        sid = sid.upper()
        if sid not in ids:
            ids.append(sid)
    return ids


def _advisor_ids(message: str) -> List[str]:
    ids: List[str] = []
    for aid in re.findall(r"\bA\d{3}\b", message or "", flags=re.I):
        aid = aid.upper()
        if aid not in ids:
            ids.append(aid)
    return ids


def _validation_contract(domain: str, message: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Contract that the result validator must enforce after MCP execution."""
    arguments = arguments or {}
    sids = _student_ids(message)
    aids = _advisor_ids(message)
    latest_contract = build_latest_message_contract(message)
    contract: Dict[str, Any] = {
        "expected_domain": domain,
        "required_student_ids": sids,
        "required_advisor_ids": aids,
        "must_not_return_other_student_for_single_id": len(sids) == 1,
        "operation": arguments.get("operation"),
        "answer_style": arguments.get("answer_style"),
        "latest_message_contract": latest_contract,
        "expected_answer_style": latest_contract.get("answer_style"),
    }
    study_query = parse_student_study_query(message)
    student_ranking = parse_student_ranking_query(message)
    stat_query = parse_student_statistic_query(message)
    total_count_query = parse_total_student_count_query(message)
    metric_query = parse_student_metric_query(message)
    if domain == "subjects":
        contract["must_have_keys"] = ["unique_subject_count", "subjects"]
        contract["forbidden_actual_domains"] = ["students"]
    elif domain == "students" and isinstance(student_ranking, dict):
        contract["expected_operation"] = "rank_students"
        contract["expected_answer_style"] = "student_rank"
        contract["expected_ranking"] = student_ranking
        contract["expected_top_n"] = student_ranking.get("top_n")
    elif domain == "students" and isinstance(total_count_query, dict):
        contract["expected_operation"] = "count"
        contract["expected_scope"] = "university"
        contract["expected_answer_style"] = "count"
    elif domain == "students" and isinstance(stat_query, dict):
        contract["expected_operation"] = stat_query.get("operation") or "study_term_aggregate"
        contract["expected_scope"] = stat_query.get("scope")
        contract["expected_study_term"] = stat_query.get("study_term")
        contract["expected_statistic"] = stat_query.get("statistic")
        contract["expected_answer_style"] = stat_query.get("answer_style") or contract.get("expected_answer_style")
    elif domain == "students" and isinstance(study_query, dict):
        contract["expected_operation"] = "study_term_search"
        contract["expected_study_term"] = study_query.get("study_term")
        contract["expected_answer_style"] = study_query.get("answer_style") or contract.get("expected_answer_style")
        contract["expected_ranking"] = study_query.get("ranking")
    elif domain == "students" and isinstance(metric_query, dict):
        contract["expected_operation"] = "filter_summary"
        contract["expected_metric_query"] = metric_query
    elif domain == "students" and sids:
        contract["must_include_student_ids_or_not_found_rows"] = sids
    elif domain == "documents":
        contract["must_come_from_tool"] = "postgres_university_tool"
    elif domain in {"academic_records", "course_catalog"}:
        contract["must_come_from_tool"] = "postgres_university_tool"
        contract["expected_query_type"] = arguments.get("query_type")
        contract["expected_sections"] = list(arguments.get("requested_sections") or [])
    elif domain == "advisors" and aids:
        contract["must_include_advisor_ids_or_not_found_rows"] = aids
    return contract


def _limit_from_text(text: str, default: int = 20) -> int:
    patterns = [
        r"(?:list|show|give|top|bottom)\s+(?:me\s+)?(\d{1,3})\b",
        r"\b(\d{1,3})\s+(?:students|student|people|records|คน)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return max(1, min(int(m.group(1)), 200))
    return default


def _student_answer_shape(message: str, role: str) -> Dict[str, Any]:
    text = _low(message)
    if _contains_any(text, PROFILE_WORDS) or any(w in text for w in ["full", "everything", "all data", "ทุกอย่าง", "ทั้งหมด"]):
        requested = STUDENT_FIELDS_ADMIN if role == "admin" else ["student_id", "name", "program", "academic_status", "subject_grades", "gpa", "email"]
        return {"answer_style": "profile", "requested_fields": allowed_student_fields_for_role(role, requested)}
    if _contains_any(text, GPA_WORDS) and _contains_any(text, SUBJECT_WORDS | GRADE_WORDS):
        requested = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
        return {
            "answer_style": "student_multi",
            "requested_components": ["gpa", "grades"],
            "requested_fields": allowed_student_fields_for_role(role, requested),
        }
    if _contains_any(text, GPA_WORDS) and not _contains_any(text, SUBJECT_WORDS | GRADE_WORDS):
        return {"answer_style": "gpa", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name", "gpa"])}
    if _contains_any(text, GRADE_WORDS | SUBJECT_WORDS):
        return {"answer_style": "grades", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name", "program", "academic_status", "subject_grades"])}
    if "name" in text or "ชื่อ" in text:
        return {"answer_style": "names", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name"])}
    return {"answer_style": "summary", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name", "program", "gpa", "academic_status"])}


def _base_plan(
    *,
    message: str,
    language: str,
    role: str,
    requester_student_id: Optional[str],
    requester_advisor_id: Optional[str],
    selected_agent: str,
    tool_name: str,
    arguments: Dict[str, Any],
    prompt: str,
    intent: str,
    domain: str,
    confidence: float,
    reason: str,
) -> Dict[str, Any]:
    return {
        "selected_agent": selected_agent,
        "role_prompt_name": prompt,
        "tool_name": tool_name,
        "arguments": {
            **arguments,
            "original_question": message,
            "answer_style": arguments.get("answer_style") or "summary",
            "orchestrator_reason": reason,
            "orchestrator_domain": domain,
            "orchestrator_intent": intent,
        },
        "user_role": role,
        "requester_student_id": requester_student_id,
        "requester_advisor_id": requester_advisor_id,
        "language": language,
        "intent_decision": {
            "source": "agent_orchestrator_v2",
            "intent": intent,
            "domain": domain,
            "confidence": confidence,
            "reason": reason,
        },
        "orchestrator": {
            "version": "v2",
            "domain": domain,
            "intent": intent,
            "confidence": confidence,
            "reason": reason,
        },
        "validation_contract": _validation_contract(domain, message, arguments),
    }


def _document_plan(message: str, language: str, role: str, requester_student_id: Optional[str], requester_advisor_id: Optional[str], reason: str) -> Dict[str, Any]:
    text = _low(message)
    if role == "admin":
        qtype = "all_documents"
        prompt = "ADMIN_DOCUMENT_AGENT_PROMPT"
    else:
        qtype = "advisor_documents"
        prompt = "ADVISOR_DOCUMENT_AGENT_PROMPT" if role == "advisor" else "STUDENT_ADVISOR_DOCUMENT_PROMPT"
    preferred = None
    if any(w in text for w in ["excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "เอ็กเซล", "ชีต"]):
        preferred = "excel"
    elif "pdf" in text:
        preferred = "pdf"
    compare_collection = any(w in text for w in ["compare", "versus", "difference between", "summarize every", "summarize all", "together"])
    focused_best_match = any(w in text for w in ["which file", "which document", "discusses", "mentions", "most relevant", "quote", "citation", "cite"])
    op = (
        "document_search"
        if compare_collection or focused_best_match
        else ("list_documents" if document_list_request(message) or _has_count(text) or _contains_any(text, LIST_WORDS) else "document_search")
    )
    answer_style = (
        "document_compare"
        if any(w in text for w in ["compare", "versus", "difference between"])
        else (
            "document_collection_summary"
            if any(w in text for w in ["summarize every", "summarize all", "together"])
            else ("document_quote" if any(w in text for w in ["quote", "citation", "cite"]) else "summary")
        )
    )
    return _base_plan(
        message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
        selected_agent=f"{role}_orchestrator_document_agent", tool_name="postgres_university_tool",
        arguments={"query_type": qtype, "operation": op, "keyword": friendly_clean_query(message), "preferred_source_type": preferred, "answer_style": answer_style},
        prompt=prompt, intent="query_documents", domain="documents", confidence=0.96, reason=reason,
    )


def _academic_plan(
    message: str,
    language: str,
    role: str,
    requester_student_id: Optional[str],
    requester_advisor_id: Optional[str],
    academic_query: Dict[str, Any],
    reason: str,
) -> Dict[str, Any]:
    query_type = str(academic_query.get("query_type") or "")
    student_ids = list(academic_query.get("student_ids") or [])
    requested_student_id = (
        requester_student_id
        if role == "student"
        else (student_ids[0] if student_ids else None)
    )
    if (
        role == "student"
        and student_ids
        and requester_student_id
        and any(student_id != requester_student_id for student_id in student_ids)
    ):
        plan = _normal_chat_plan(
            message, language, role, requester_student_id, requester_advisor_id,
            "The signed student requested another student's academic record.",
        )
        plan["arguments"]["reason"] = "student_other_record_denied"
        plan["arguments"]["answer_style"] = "access_scope"
        plan["purpose_contract"] = build_latest_message_contract(message)
        return plan
    if query_type == "student_academic_profile" and not requested_student_id:
        plan = _normal_chat_plan(
            message, language, role, requester_student_id, requester_advisor_id,
            "A student ID is required for this academic-record question.",
        )
        plan["arguments"]["reason"] = "academic_student_id_required"
        plan["arguments"]["answer_style"] = "clarification"
        plan["purpose_contract"] = build_latest_message_contract(message)
        return plan

    keyword = ""
    if query_type == "course_catalog":
        code_match = re.search(r"\b[A-Z]{2,5}\s?\d{2,4}\b", message or "", flags=re.I)
        keyword = code_match.group(0).upper().replace(" ", "") if code_match else ""

    allowed_sections_by_role = {
        "admin": {"profile", "enrollments", "assessments", "attendance", "financial_accounts", "support_cases", "scholarship_awards"},
        "advisor": {"profile", "enrollments", "assessments", "attendance"},
        "student": {"profile", "enrollments", "assessments", "attendance", "financial_accounts", "scholarship_awards"},
    }
    requested_sections = list(academic_query.get("requested_sections") or [])
    allowed_sections = allowed_sections_by_role.get(role, set())
    denied_sections = [section for section in requested_sections if section not in allowed_sections]
    requested_sections = [section for section in requested_sections if section in allowed_sections]
    master_sections = list(academic_query.get("student_master_sections") or [])
    allowed_master_sections_by_role = {
        "admin": {"profile", "gpa", "grades"},
        "advisor": {"profile", "grades"},
        "student": {"profile", "gpa", "grades"},
    }
    allowed_master_sections = allowed_master_sections_by_role.get(role, set())
    denied_master_sections = [section for section in master_sections if section not in allowed_master_sections]
    master_sections = [section for section in master_sections if section in allowed_master_sections]
    denied_sections.extend(section for section in denied_master_sections if section not in denied_sections)
    if denied_sections and not requested_sections and not master_sections:
        plan = _normal_chat_plan(
            message, language, role, requester_student_id, requester_advisor_id,
            "The signed role cannot access the requested academic section.",
        )
        plan["arguments"].update({
            "reason": "academic_sections_not_available_for_role",
            "answer_style": "access_scope",
            "denied_sections": denied_sections,
        })
        plan["purpose_contract"] = build_latest_message_contract(message)
        return plan

    arguments = {
        "query_type": query_type,
        "operation": "read",
        "student_id": requested_student_id,
        "student_ids": (
            [requester_student_id]
            if role == "student" and requester_student_id
            else student_ids
        ),
        "keyword": keyword,
        "limit": _limit_from_text(_low(message), 50),
        "requested_sections": requested_sections,
        "student_master_sections": master_sections,
        "include_student_master": bool(master_sections),
        "denied_sections": denied_sections,
        "requested_section_styles": dict(academic_query.get("requested_section_styles") or {}),
        "answer_style": academic_query.get("answer_style") or "summary",
        "academic_query": academic_query,
    }
    plan = _base_plan(
        message=message,
        language=language,
        role=role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        selected_agent=f"{role}_academic_records_agent",
        tool_name="postgres_university_tool",
        arguments=arguments,
        prompt=(
            "ADMIN_ACADEMIC_RECORDS_PROMPT"
            if role == "admin"
            else ("ADVISOR_ACADEMIC_RECORDS_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT")
        ),
        intent=f"query_{academic_query.get('domain') or 'academic_records'}",
        domain=academic_query.get("domain") or "academic_records",
        confidence=0.99,
        reason=reason,
    )
    plan["orchestrator"]["version"] = "v30_academic_brain"
    plan["purpose_contract"] = build_latest_message_contract(message)
    return plan


def _analytics_plan(
    message: str,
    language: str,
    role: str,
    requester_student_id: Optional[str],
    requester_advisor_id: Optional[str],
    analytics: Dict[str, Any],
) -> Dict[str, Any]:
    analytics_type = str(analytics.get("type") or "")
    if analytics_type == "capability_limitation":
        plan = _normal_chat_plan(
            message, language, role, requester_student_id, requester_advisor_id,
            "The question requires facts or a model that the current databases do not contain.",
        )
        plan["arguments"].update({
            "reason": analytics.get("reason"),
            "answer_style": "capability_limitation",
            "capability_limitation": analytics,
        })
        plan["purpose_contract"] = build_latest_message_contract(message)
        return plan

    if analytics_type == "student_count":
        return _base_plan(
            message=message, language=language, role=role,
            requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_student_population_agent",
            tool_name="mongodb_student_tool",
            arguments={
                "student_id": requester_student_id if role == "student" else "ALL",
                "operation": "count",
                "requested_fields": ["student_id"],
                "answer_style": "count",
                "analytics_query": analytics,
            },
            prompt="ADMIN_GRADE_ANALYST_PROMPT" if role == "admin" else "ADVISOR_GRADE_ANALYST_PROMPT",
            intent="count_students", domain="students", confidence=1.0,
            reason=str(analytics.get("reason") or "Student population count paraphrase."),
        )

    if analytics_type == "student_ranking":
        if role != "admin":
            plan = _normal_chat_plan(
                message, language, role, requester_student_id, requester_advisor_id,
                "University-wide GPA ranking is outside this signed role.",
            )
            plan["arguments"].update({
                "reason": "student_ranking_not_available_for_role",
                "answer_style": "access_scope",
            })
            return plan
        requested = ["student_id", "name", "program", "gpa", "academic_status"]
        return _base_plan(
            message=message, language=language, role=role,
            requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent="admin_student_ranking_agent",
            tool_name="mongodb_student_tool",
            arguments={
                "student_id": "ALL",
                "operation": "rank_students",
                "requested_fields": requested,
                "sort": [{"field": "gpa", "direction": analytics.get("direction") or "desc"}],
                "limit": analytics.get("top_n") or 10,
                "display_limit": analytics.get("top_n") or 10,
                "top_n": analytics.get("top_n") or 10,
                "ranking": analytics,
                "answer_style": "student_rank",
                "analytics_query": analytics,
            },
            prompt="ADMIN_GRADE_ANALYST_PROMPT", intent="rank_students",
            domain="students", confidence=1.0,
            reason=str(analytics.get("reason") or "Student GPA ranking."),
        )

    if analytics_type == "rank_with_academic":
        if role != "admin":
            plan = _normal_chat_plan(
                message, language, role, requester_student_id, requester_advisor_id,
                "Cross-student GPA ranking with academic details is limited to administrators.",
            )
            plan["arguments"].update({
                "reason": "student_ranking_not_available_for_role",
                "answer_style": "access_scope",
            })
            return plan
        top_n = int(analytics.get("top_n") or 10)
        return _base_plan(
            message=message, language=language, role=role,
            requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent="admin_ranked_academic_agent",
            tool_name="mongodb_student_tool",
            arguments={
                "student_id": "ALL",
                "operation": "rank_students",
                "requested_fields": ["student_id", "name", "program", "gpa", "academic_status"],
                "sort": [{"field": "gpa", "direction": analytics.get("direction") or "desc"}],
                "limit": top_n,
                "display_limit": top_n,
                "top_n": top_n,
                "ranking": analytics,
                "requested_academic_sections": analytics.get("requested_academic_sections") or [],
                "answer_style": "student_rank_with_academic",
                "analytics_query": analytics,
            },
            prompt="ADMIN_ACADEMIC_RECORDS_PROMPT", intent="rank_students_with_academic",
            domain="students", confidence=1.0,
            reason=str(analytics.get("reason") or "Rank students and attach requested academic sections."),
        )

    if analytics_type == "student_benchmark":
        if role == "advisor":
            plan = _normal_chat_plan(
                message, language, role, requester_student_id, requester_advisor_id,
                "Advisor accounts do not have access to student GPA benchmarks.",
            )
            plan["arguments"].update({
                "reason": "academic_sections_not_available_for_role",
                "answer_style": "access_scope",
                "denied_sections": ["gpa"],
            })
            return plan
        student_id = (
            requester_student_id
            if role == "student"
            else ((analytics.get("student_ids") or [None])[0])
        )
        if not student_id:
            plan = _normal_chat_plan(
                message, language, role, requester_student_id, requester_advisor_id,
                "A student benchmark comparison requires an explicit or signed student ID.",
            )
            plan["arguments"].update({"reason": "benchmark_student_id_required", "answer_style": "clarification"})
            return plan
        return _base_plan(
            message=message, language=language, role=role,
            requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_student_benchmark_agent",
            tool_name="mongodb_student_tool",
            arguments={
                "student_id": student_id,
                "operation": "compare_student_to_population",
                "requested_fields": ["student_id", "name", "gpa"],
                "metric_field": "gpa",
                "answer_style": "student_benchmark",
                "analytics_query": analytics,
            },
            prompt="ADMIN_GRADE_ANALYST_PROMPT" if role == "admin" else "STUDENT_SELF_DATA_AGENT_PROMPT",
            intent="compare_student_benchmark", domain="students", confidence=1.0,
            reason=str(analytics.get("reason") or "Student benchmark comparison."),
        )

    if analytics_type == "database_analytics":
        analytics = dict(analytics)
        denied_sections: List[str] = []
        if role == "advisor" and analytics.get("include_balance"):
            analytics["include_balance"] = False
            denied_sections.append("financial_accounts")
        source = str(analytics.get("source") or "postgres")
        if source == "mongo" and analytics.get("measure") == "average_gpa" and role == "advisor":
            plan = _normal_chat_plan(
                message, language, role, requester_student_id, requester_advisor_id,
                "Advisor accounts do not have access to grouped student GPA.",
            )
            plan["arguments"].update({
                "reason": "academic_sections_not_available_for_role",
                "answer_style": "access_scope",
                "denied_sections": ["gpa"],
            })
            return plan
        if analytics.get("measure") == "balance_due" and role == "advisor":
            plan = _normal_chat_plan(
                message, language, role, requester_student_id, requester_advisor_id,
                "Advisor accounts cannot aggregate student financial balances.",
            )
            plan["arguments"].update({
                "reason": "academic_sections_not_available_for_role",
                "answer_style": "access_scope",
                "denied_sections": ["financial_accounts"],
            })
            return plan
        if source == "mongo":
            tool_name = "mongodb_student_tool"
            arguments = {
                "student_id": requester_student_id if role == "student" else "ALL",
                "operation": "group_students",
                "analytics_query": analytics,
                "dimension": analytics.get("dimension"),
                "measure": analytics.get("measure"),
                "direction": analytics.get("direction"),
                "top_n": analytics.get("top_n"),
                "requested_fields": ["student_id", "program", "gpa", "academic_status"],
                "answer_style": "group_analytics",
            }
            domain = "students"
        else:
            tool_name = "postgres_university_tool"
            arguments = {
                "query_type": "academic_analytics",
                "operation": analytics.get("operation") or "group_aggregate",
                "analytics_query": analytics,
                "dimension": analytics.get("dimension"),
                "measure": analytics.get("measure"),
                "direction": analytics.get("direction"),
                "top_n": analytics.get("top_n"),
                "student_ids": analytics.get("student_ids") or [],
                "include_balance": bool(analytics.get("include_balance")),
                "denied_sections": denied_sections,
                "answer_style": analytics.get("answer_style") or "group_analytics",
            }
            domain = "academic_records"
        return _base_plan(
            message=message, language=language, role=role,
            requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_database_analytics_agent",
            tool_name=tool_name, arguments=arguments,
            prompt="ADMIN_ACADEMIC_RECORDS_PROMPT" if role == "admin" else "ADVISOR_GRADE_ANALYST_PROMPT",
            intent="database_analytics", domain=domain, confidence=1.0,
            reason=str(analytics.get("reason") or "Structured database analytics query."),
        )

    return _normal_chat_plan(
        message, language, role, requester_student_id, requester_advisor_id,
        "No executable analytics capability matched the query.",
    )


def _advisor_classroom_plan(
    message: str,
    language: str,
    requester_advisor_id: Optional[str],
    classroom: Dict[str, Any],
) -> Dict[str, Any]:
    if classroom.get("type") == "advisor_scope_denial":
        plan = _normal_chat_plan(
            message,
            language,
            "advisor",
            None,
            requester_advisor_id,
            "Advisor accounts are restricted to facts from their own assigned classes.",
        )
        plan["arguments"].update({
            "reason": "advisor_classroom_scope_only",
            "answer_style": "advisor_scope",
            "denied_fields": classroom.get("denied_fields") or [],
        })
        plan["purpose_contract"] = build_latest_message_contract(message)
        return plan

    return _base_plan(
        message=message,
        language=language,
        role="advisor",
        requester_student_id=None,
        requester_advisor_id=requester_advisor_id,
        selected_agent="advisor_classroom_data_agent",
        tool_name="postgres_university_tool",
        arguments={
            "query_type": "advisor_classroom",
            "operation": classroom.get("operation") or "class_records",
            "course_query": classroom.get("course_query") or "",
            "student_ids": classroom.get("student_ids") or [],
            "requested_metrics": classroom.get("requested_metrics") or ["grade"],
            "direction": classroom.get("direction") or "desc",
            "top_n": classroom.get("top_n") or 20,
            "answer_style": classroom.get("answer_style") or "advisor_class_records",
            "advisor_class_query": classroom,
        },
        prompt="ADVISOR_GRADE_ANALYST_PROMPT",
        intent="advisor_classroom_query",
        domain="academic_records",
        confidence=1.0,
        reason=str(classroom.get("reason") or "Strict signed-advisor classroom query."),
    )


def _deterministic_plan_unchecked(message: str, language: str, user_role: str, requester_student_id: Optional[str] = None, requester_advisor_id: Optional[str] = None, chat_history: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    role = (user_role or "student").lower()
    text = _low(message)
    sids = _student_ids(message)
    aids = _advisor_ids(message)
    analytics_query = parse_database_analytics_query(message)
    academic_query = parse_academic_query(message)

    # Writing/editing/translation requests may mention the word "student" but do not necessarily
    # ask to read student records.  Keep these in normal chat unless they contain exact IDs, GPA/grade,
    # database/file words, or direct data-access verbs.
    writing_words = ["write", "draft", "rephrase", "rewrite", "translate", "make a message", "caption", "email", "แก้ประโยค", "แปล", "เขียน"]
    data_access_words = ["show", "list", "find", "count", "how many", "what is", "who", "which", "gpa", "grade", "profile", "database", "record", "ข้อมูล", "เกรด", "คะแนน", "รายชื่อ"]
    if any(w in text for w in writing_words) and not sids and not aids and not any(w in text for w in data_access_words):
        return _normal_chat_plan(message, language, role, requester_student_id, requester_advisor_id, "Writing/editing request, not database access.")

    # File questions remain in the advisor-owned knowledge workspace and must
    # not be mistaken for classroom/student data merely because they mention a
    # class or grade.
    if _is_document_query(message):
        return _document_plan(message, language, role, requester_student_id, requester_advisor_id, "The user asked about uploaded PDF/Excel/CSV/document knowledge.")

    if role == "advisor":
        advisor_class_query = parse_advisor_class_query(message)
        if advisor_class_query:
            return _advisor_classroom_plan(
                message,
                language,
                requester_advisor_id,
                advisor_class_query,
            )

    if role == "student":
        own_course_query = parse_student_own_course_query(message)
        if own_course_query:
            operation = str(own_course_query.get("operation") or "list_subjects")
            arguments = {
                "student_id": requester_student_id or "S001",
                "operation": operation,
                "query_type": "student_subjects",
                "course_query": own_course_query.get("course_query") or "",
                "answer_style": own_course_query.get("answer_style"),
            }
            return _base_plan(
                message=message,
                language=language,
                role=role,
                requester_student_id=requester_student_id,
                requester_advisor_id=requester_advisor_id,
                selected_agent="student_own_course_agent",
                tool_name="postgres_university_tool",
                arguments=arguments,
                prompt="STUDENT_SELF_DATA_AGENT_PROMPT",
                intent="query_own_courses",
                domain="subjects",
                confidence=1.0,
                reason=str(own_course_query.get("reason") or "Signed-student own-course query."),
            )

    if analytics_query:
        return _analytics_plan(
            message,
            language,
            role,
            requester_student_id,
            requester_advisor_id,
            analytics_query,
        )

    if academic_query:
        return _academic_plan(
            message,
            language,
            role,
            requester_student_id,
            requester_advisor_id,
            academic_query,
            academic_query["reason"],
        )

    # If the latest message has no university/database signal, do normal ChatGPT-style chat.
    # This prevents the legacy admin planner from turning "hello" into a student lookup.
    if not _has_university_data_signal(text):
        return _normal_chat_plan(message, language, role, requester_student_id, requester_advisor_id, "No university/database data signal detected; use normal chat mode.")

    subject_ranking = parse_subject_ranking_query(message)
    if subject_ranking:
        return _base_plan(
            message=message,
            language=language,
            role=role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_orchestrator_subject_agent",
            tool_name="mongodb_student_tool",
            arguments={
                "student_id": requester_student_id if role == "student" and requester_student_id else "ALL",
                "operation": "subject_summary",
                "requested_fields": ["student_id", "name", "program", "subject_grades"],
                "limit": 5000,
                "answer_style": subject_ranking["answer_style"],
                "top_n": subject_ranking["top_n"],
                "ranking_basis": subject_ranking["ranking_basis"],
                "recommendation_basis": subject_ranking["recommendation_basis"],
            },
            prompt="ADMIN_SUBJECT_AGENT_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT"),
            intent="rank_subjects",
            domain="subjects",
            confidence=0.99,
            reason=subject_ranking["reason"],
        )

    student_ranking = parse_student_ranking_query(message)
    if student_ranking:
        if role != "admin":
            plan = _normal_chat_plan(
                message, language, role, requester_student_id, requester_advisor_id,
                "University-wide GPA rankings are not available to this signed role.",
            )
            plan["arguments"].update({
                "reason": "student_ranking_not_available_for_role",
                "answer_style": "access_scope",
            })
            plan["purpose_contract"] = build_latest_message_contract(message)
            return plan
        requested = student_ranking.get("requested_fields") or ["student_id", "name", "program", "gpa", "academic_status"]
        return _base_plan(
            message=message,
            language=language,
            role=role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            selected_agent="admin_student_ranking_agent",
            tool_name="mongodb_student_tool",
            arguments={
                "student_id": "ALL",
                "operation": "rank_students",
                "requested_fields": allowed_student_fields_for_role(role, requested),
                "sort": [{"field": student_ranking["field"], "direction": student_ranking["direction"]}],
                "limit": student_ranking["top_n"],
                "display_limit": student_ranking["top_n"],
                "top_n": student_ranking["top_n"],
                "ranking": student_ranking,
                "answer_style": "student_rank",
            },
            prompt="ADMIN_GRADE_ANALYST_PROMPT",
            intent="rank_students",
            domain="students",
            confidence=1.0,
            reason=student_ranking["reason"],
        )

    # Explicit student IDs have priority over broad subject words because "S001 subject/grade"
    # means that student's subject grades, not a university subject catalog.
    if sids:
        shape = _student_answer_shape(message, role)
        if len(sids) == 1:
            args = {"student_id": sids[0], "operation": "read_students", "requested_student_ids": sids, **shape}
        else:
            args = {
                "student_id": "ALL",
                "operation": "read_students",
                "query_filter": {"student_id": {"$in": sids}},
                "sort": [{"field": "student_id", "direction": "asc"}],
                "limit": len(sids),
                "requested_student_ids": sids,
                **shape,
            }
        prompt = "ADMIN_SUPER_AGENT_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT")
        return _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_orchestrator_student_agent", tool_name="mongodb_student_tool", arguments=args,
            prompt=prompt, intent="query_students", domain="students", confidence=0.99,
            reason="Explicit student ID(s) detected; fetch exactly those IDs and the requested fields.",
        )

    # Student self-data without explicit ID.
    if role == "student" and (_contains_any(text, GRADE_WORDS | GPA_WORDS | PROFILE_WORDS | SUBJECT_WORDS) or any(w in text for w in ["my", "me", "mine", "ผม", "หนู", "ของฉัน"])):
        shape = _student_answer_shape(message, role)
        return _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent="student_orchestrator_self_agent", tool_name="mongodb_student_tool",
            arguments={"student_id": requester_student_id or "S001", "operation": "read_students", **shape},
            prompt="STUDENT_SELF_DATA_AGENT_PROMPT", intent="query_students", domain="students", confidence=0.95,
            reason="Student role asked about own data; route to own student record under PDPA.",
        )

    # V10 statistical study-term questions: median/average/highest/lowest/count
    # should compute against matching program/subject rows, not just search all students.
    stat_query = parse_student_statistic_query(message)
    if stat_query and not sids:
        requested = stat_query.get("requested_fields") or ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
        args = {
            "student_id": "ALL",
            "operation": stat_query.get("operation") or "study_term_aggregate",
            "study_term": stat_query.get("study_term"),
            "statistic": stat_query.get("statistic"),
            "metric_field": stat_query.get("field") or "gpa",
            "stat_query": stat_query,
            "requested_fields": allowed_student_fields_for_role(role, requested),
            "limit": 5000,
            "display_limit": _limit_from_text(text, 50),
            "answer_style": stat_query.get("answer_style") or "study_statistic",
        }
        plan = _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_study_statistic_database_agent", tool_name="mongodb_student_tool", arguments=args,
            prompt="ADMIN_STUDENT_STATISTIC_AGENT_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT"),
            intent="aggregate_students", domain="students", confidence=0.95, reason=stat_query.get("reason") or "Study-term statistic query detected."
        )
        plan["purpose_analysis"] = {
            "source": "backend_statistic_query_parser",
            "target_domain": "students",
            "answer_intent": "aggregate",
            "should_use_database": True,
            "stat_query": stat_query,
            "user_purpose": f"Compute {stat_query.get('statistic')} {stat_query.get('field')} for students matching {stat_query.get('study_term')}",
        }
        return plan

    # Study-term questions: "students who study law" should search program and subject names, not read all students.
    study_query = parse_student_study_query(message)
    if study_query and not sids:
        requested = ["student_id", "name", "program", "academic_status", "subject_grades"]
        args = {
            "student_id": "ALL",
            "operation": "study_term_search",
            "study_term": study_query.get("study_term"),
            "study_query": study_query,
            "requested_fields": allowed_student_fields_for_role(role, requested),
            "limit": 5000 if study_query.get("intent") == "count" else _limit_from_text(text, 50),
            "display_limit": _limit_from_text(text, 50),
            "answer_style": study_query.get("answer_style") or "study_search",
        }
        plan = _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_study_term_database_agent", tool_name="mongodb_student_tool", arguments=args,
            prompt="ADMIN_STUDENT_STUDY_AGENT_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT"),
            intent="query_students", domain="students", confidence=0.93, reason=study_query.get("reason") or "Study-term query detected."
        )
        plan["purpose_analysis"] = {
            "source": "backend_study_query_parser",
            "target_domain": "students",
            "answer_intent": study_query.get("intent") or "search",
            "should_use_database": True,
            "study_query": study_query,
            "user_purpose": f"Find students who study {study_query.get('study_term')}",
        }
        return plan

    # University-wide subjects/courses. Count/list subjects from subject_grades, not student count.
    if _contains_any(text, SUBJECT_WORDS) and not _contains_any(text, DOCUMENT_WORDS):
        if role == "student" and not _has_count(text) and not _contains_any(text, LIST_WORDS):
            # For a student, "my subjects" means own grades/subjects.
            if any(w in text for w in ["my", "me", "mine", "ของฉัน", "ของหนู", "ของผม"]):
                shape = {"answer_style": "grades", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name", "subject_grades"])}
                return _base_plan(
                    message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
                    selected_agent="student_orchestrator_self_agent", tool_name="mongodb_student_tool",
                    arguments={"student_id": requester_student_id or "S001", "operation": "read_students", **shape},
                    prompt="STUDENT_SELF_DATA_AGENT_PROMPT", intent="query_students", domain="students", confidence=0.93,
                    reason="Student asked for own subjects; route to own subject_grades.",
                )
        return _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_orchestrator_subject_agent", tool_name="mongodb_student_tool",
            arguments={"student_id": requester_student_id if role == "student" and requester_student_id else "ALL", "operation": "subject_summary", "requested_fields": ["student_id", "name", "program", "subject_grades"], "limit": 5000, "answer_style": "subject_summary"},
            prompt="ADMIN_SUBJECT_AGENT_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT"),
            intent="query_subjects", domain="subjects", confidence=0.98,
            reason="The user asked about subjects/courses; use subject_summary from student subject_grades.",
        )

    # Advisor questions.
    if aids or _contains_any(text, ADVISOR_WORDS):
        advisor_id = aids[0] if aids else ("ALL" if role == "admin" and (_contains_any(text, LIST_WORDS) or _has_count(text) or "all" in text) else (requester_advisor_id or "ALL"))
        operation = "list_advisors" if advisor_id == "ALL" else "read_advisors"
        return _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_orchestrator_advisor_agent", tool_name="mongodb_advisor_tool",
            arguments={"advisor_id": advisor_id, "operation": operation, "answer_style": "summary"},
            prompt="ADMIN_SUPER_AGENT_PROMPT" if role == "admin" else "ADVISOR_AGENT_PROMPT", intent="query_advisors", domain="advisors", confidence=0.94,
            reason="Advisor/advisor ID terms detected.",
        )

    # Student count/list/ranking/filter without explicit IDs.
    if _contains_any(text, STUDENT_WORDS) or _contains_any(text, GPA_WORDS) or any(w in text for w in ["lowest", "highest", "top", "weak", "improve", "risk", "lower than", "less than", "above", "under", "นักศึกษาทั้งหมด"]):
        limit = _limit_from_text(text, 20)
        operation = "read_students"
        sort: List[Dict[str, str]] = []
        query_filter: Dict[str, Any] = {}
        requested = ["student_id", "name", "program", "gpa", "academic_status"]
        answer_style = "summary"
        allow_full_chat_list = False
        is_student_directory_request = (
            (_contains_any(text, LIST_WORDS) or "รายชื่อ" in text or "จัดเรียง" in text)
            and _contains_any(text, STUDENT_WORDS)
            and not (_contains_any(text, GRADE_WORDS) or _contains_any(text, GPA_WORDS) or _contains_any(text, PROFILE_WORDS))
        )
        if is_student_directory_request:
            operation = "list_names"
            answer_style = "names"
            requested = ["student_id", "name"]
            limit = 5000
            allow_full_chat_list = True
        if _has_count(text):
            operation = "count"
            answer_style = "count"
            allow_full_chat_list = False
        if any(w in text for w in ["lowest", "weak", "worst", "bottom", "improve", "risk"]):
            sort = [{"field": "gpa", "direction": "asc"}]
            limit = 1 if any(w in text for w in ["lowest", "weakest", "worst"]) and "list" not in text else max(limit, 10)
            requested = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
            answer_style = "rank"
        elif any(w in text for w in ["highest", "best", "top", "strongest"]):
            sort = [{"field": "gpa", "direction": "desc"}]
            limit = _limit_from_text(text, 10)
            answer_style = "rank"
        metric_query = parse_student_metric_query(message)
        if metric_query:
            query_filter = dict(metric_query.get("query_filter") or {})
            sort = list(metric_query.get("sort") or sort)
            requested = ["student_id", "name", "program", "gpa", "academic_status"]
            operation = "filter_summary"
            answer_style = metric_query.get("answer_style") or ("aggregate_count" if metric_query.get("intent") == "count" else "aggregate_filter")
            limit = 5000 if metric_query.get("intent") == "count" else max(limit, 50)
        return _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_orchestrator_student_agent", tool_name="mongodb_student_tool",
            arguments={"student_id": "ALL", "operation": operation, "requested_fields": allowed_student_fields_for_role(role, requested), "query_filter": query_filter, "sort": sort, "limit": 5000 if operation in {"count", "filter_summary", "list_names"} else limit, "answer_style": answer_style, "display_limit": 300 if allow_full_chat_list else limit, "create_report_if_over": 5000 if allow_full_chat_list else 20, "allow_full_chat_list": allow_full_chat_list, "metric_query": metric_query if 'metric_query' in locals() and isinstance(metric_query, dict) else None},
            prompt="ADMIN_GRADE_ANALYST_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT"),
            intent="query_students", domain="students", confidence=0.92,
            reason="Student/GPA/ranking/filter terms detected.",
        )

    if _contains_any(text, PROGRAM_WORDS):
        return _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_orchestrator_program_agent", tool_name="postgres_university_tool",
            arguments={"query_type": "programs", "operation": "search", "keyword": friendly_clean_query(message), "answer_style": "summary"},
            prompt="ADMIN_PROGRAM_AGENT_PROMPT", intent="query_programs", domain="programs", confidence=0.88,
            reason="Program/major/faculty terms detected.",
        )

    if _contains_any(text, CAMPUS_WORDS):
        return _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_orchestrator_campus_agent", tool_name="postgres_university_tool",
            arguments={"query_type": "campus_info", "operation": "search", "keyword": friendly_clean_query(message), "answer_style": "short"},
            prompt="ADMIN_PROGRAM_AGENT_PROMPT", intent="query_campus", domain="campus_info", confidence=0.87,
            reason="Campus/location terms detected.",
        )

    if request_semantics(message)["is_schema_request"]:
        return _base_plan(
            message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_orchestrator_schema_agent", tool_name="postgres_university_tool",
            arguments={"query_type": "database_map", "operation": "schema", "keyword": friendly_clean_query(message), "answer_style": "summary"},
            prompt="ADMIN_DATABASE_ARCHITECT_PROMPT", intent="database_overview", domain="database_map", confidence=0.90,
            reason="Database/schema/structure terms detected.",
        )

    return None


def deterministic_plan(
    message: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Build a deterministic plan and enforce the signed-student boundary."""
    plan = _deterministic_plan_unchecked(
        message,
        language,
        user_role,
        requester_student_id,
        requester_advisor_id,
        chat_history,
    )
    return enforce_student_scope_plan(
        plan,
        message=message,
        user_role=user_role,
        requester_student_id=requester_student_id,
    )


PLANNER_SYSTEM_PROMPT = """
You are Agent Orchestrator V2 for a university database chatbot with strict schema-aware tool planning.
You do NOT answer the user. You choose the correct MCP tool and arguments.

Think in this order:
1. What exact data domain is the user asking about? students, subjects, advisors, documents, programs, campus_info, database_map, or normal_chat.
2. Which schema source contains that data?
3. Which operation matches the user request?
4. What fields are minimally needed under the user's role?
5. What validation expectation should be true after the tool returns?

Return ONLY JSON:
{
  "intent": "normal_chat | query_students | query_subjects | query_advisors | query_documents | query_programs | query_campus | database_overview | clarify",
  "domain": "normal_chat | students | subjects | advisors | documents | programs | campus_info | database_map",
  "tool_name": "none | mongodb_student_tool | mongodb_advisor_tool | postgres_university_tool",
  "arguments": {},
  "role_prompt_name": "ADMIN_NORMAL_CHATGPT_PROMPT",
  "answer_style": "short | summary | table | profile | grades | gpa | subject_summary | count | rank | detailed_report",
  "validation": {"expected_domain": "students", "required_student_ids": [], "must_not_be_domain": null},
  "confidence": 0.0,
  "reason": "brief reason"
}

Critical rules:
- If user asks how many/list subjects/courses in the university, use mongodb_student_tool operation=subject_summary. NEVER use student count.
- If user asks about S001/S002/S035 grades/profile/GPA, use mongodb_student_tool read_students for exactly those IDs. Never reuse a previous student ID when the current message contains a new ID.
- If user asks about uploaded PDF/Excel/file/document, use postgres_university_tool with query_type all_documents for admin or advisor_documents for advisor/student.
- If user asks normal chat (hello, write text, explain general topic) use tool_name none.
- Do not invent database fields or private data.
""".strip()


def _safe_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            cleaned = match.group(0)
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _sanitize_ai_plan(raw: Dict[str, Any], message: str, language: str, role: str, requester_student_id: Optional[str], requester_advisor_id: Optional[str]) -> Optional[Dict[str, Any]]:
    tool_name = str(raw.get("tool_name") or "none")
    if tool_name not in {"none", "mongodb_student_tool", "mongodb_advisor_tool", "postgres_university_tool"}:
        return None
    args = raw.get("arguments") if isinstance(raw.get("arguments"), dict) else {}
    domain = str(raw.get("domain") or "normal_chat")
    intent = str(raw.get("intent") or "normal_chat")
    prompt = str(raw.get("role_prompt_name") or ("ADMIN_NORMAL_CHATGPT_PROMPT" if tool_name == "none" else "ADMIN_SUPER_AGENT_PROMPT"))
    confidence = float(raw.get("confidence") or 0.0)
    reason = str(raw.get("reason") or "AI schema planner selected this plan.")

    # Backend safety normalization. The LLM is not allowed to create arbitrary operations.
    if tool_name == "none":
        args = {"reason": "normal_chat", "answer_style": raw.get("answer_style") or "short"}
    elif tool_name == "mongodb_student_tool":
        op = args.get("operation") if args.get("operation") in {"read_students", "count", "list_names", "grade_summary", "subject_summary", "schema_overview", "study_term_search", "study_term_aggregate", "filter_summary"} else "read_students"
        args["operation"] = op
        args["student_id"] = str(args.get("student_id") or (requester_student_id if role == "student" else "ALL")).upper()
        explicit_sids = _student_ids(message)
        if explicit_sids:
            args["requested_student_ids"] = explicit_sids
            if len(explicit_sids) == 1:
                args["student_id"] = explicit_sids[0]
            else:
                args["student_id"] = "ALL"
                args["query_filter"] = {"student_id": {"$in": explicit_sids}}
                args["limit"] = len(explicit_sids)
        if op == "subject_summary":
            args["student_id"] = requester_student_id if role == "student" and requester_student_id else "ALL"
            args["requested_fields"] = ["student_id", "name", "program", "subject_grades"]
            args["limit"] = 5000
        else:
            args["requested_fields"] = allowed_student_fields_for_role(role, args.get("requested_fields") or ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"])
    elif tool_name == "mongodb_advisor_tool":
        args["advisor_id"] = str(args.get("advisor_id") or (requester_advisor_id if role == "advisor" else "ALL")).upper()
        args["operation"] = args.get("operation") if args.get("operation") in {"read_advisors", "list_advisors", "schema_overview"} else ("list_advisors" if args["advisor_id"] == "ALL" else "read_advisors")
    elif tool_name == "postgres_university_tool":
        if role == "admin" and args.get("query_type") in {None, "documents"} and domain == "documents":
            args["query_type"] = "all_documents"
        elif role in {"student", "advisor"} and domain == "documents":
            args["query_type"] = "advisor_documents"
        args["operation"] = args.get("operation") or ("list_documents" if document_list_request(message) else "search")
        args["keyword"] = args.get("keyword") or friendly_clean_query(message)

    args["answer_style"] = args.get("answer_style") or raw.get("answer_style") or "summary"
    return _base_plan(
        message=message,
        language=language,
        role=role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        selected_agent=f"{role}_agent_orchestrator_v2",
        tool_name=tool_name,
        arguments=args,
        prompt=prompt,
        intent=intent,
        domain=domain,
        confidence=confidence,
        reason=reason,
    )


def ai_schema_plan(message: str, language: str, user_role: str, requester_student_id: Optional[str] = None, requester_advisor_id: Optional[str] = None, chat_history: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    role = (user_role or "student").lower()
    schema = get_schema_registry_for_role(role)
    prompt = f"""
User role: {role}
Language: {language}
Requester student ID: {requester_student_id}
Requester advisor ID: {requester_advisor_id}

Schema registry and role policy:
{json.dumps(schema, ensure_ascii=False)[:8000]}

Recent chat history for context only:
{json.dumps((chat_history or [])[-8:], ensure_ascii=False)[:3500]}

User message:
{message}

Create the MCP tool plan JSON now.
""".strip()
    try:
        raw = ai_generate_text(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            prompt=prompt,
            json_mode=True,
            timeout_env="GEMINI_INTENT_TIMEOUT",
            default_timeout=60,
            temperature=0.0,
            max_output_tokens=2048,
        )
        parsed = _safe_json(raw)
        if not parsed:
            return None
        return _sanitize_ai_plan(parsed, message, language, role, requester_student_id, requester_advisor_id)
    except Exception:
        return None


def create_orchestrator_plan(message: str, language: str, user_role: str, requester_student_id: Optional[str] = None, requester_advisor_id: Optional[str] = None, chat_history: Optional[List[Dict[str, Any]]] = None, fallback_router=None) -> Dict[str, Any]:
    role = (user_role or "student").lower()

    deterministic = deterministic_plan(message, language, role, requester_student_id, requester_advisor_id, chat_history)
    if deterministic:
        deterministic["planner_warning"] = deterministic.get("planner_warning") or "Agent Orchestrator V2 used deterministic schema guard."
        return deterministic

    ai_plan = ai_schema_plan(message, language, role, requester_student_id, requester_advisor_id, chat_history)
    if ai_plan:
        ai_plan["planner_warning"] = ai_plan.get("planner_warning") or "Agent Orchestrator V2 used schema-aware AI planner."
        return ai_plan

    # If the AI planner failed but the message still has no university data signal, keep normal chat.
    # Do not fall through to legacy admin DB planner for greetings/general writing.
    if not _has_university_data_signal(_low(message)):
        return _normal_chat_plan(message, language, role, requester_student_id, requester_advisor_id, "No university/database signal after AI planner fallback; normal chat.")

    # Reuse the older admin flexible planner as one fallback, because it already has
    # useful GPA/ranking filters. Then wrap metadata so validation still runs.
    if role == "admin":
        try:
            universal = create_universal_admin_plan(message, language, {"intent": "unknown"}, chat_history)
            db_plan = build_mcp_plan_from_universal(universal, message, language)
            plan = _base_plan(
                message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
                selected_agent="admin_agent_orchestrator_v2_fallback", tool_name=db_plan.get("tool_name") or "none",
                arguments=db_plan.get("arguments") or {"reason": "normal_chat"},
                prompt=db_plan.get("role_prompt_name") or "ADMIN_NORMAL_CHATGPT_PROMPT",
                intent=universal.get("intent") or "unknown", domain="students" if db_plan.get("tool_name") == "mongodb_student_tool" else "unknown",
                confidence=float(db_plan.get("confidence") or universal.get("confidence") or 0.5),
                reason=db_plan.get("reason") or "Legacy flexible planner fallback.",
            )
            plan["planner_warning"] = "Agent Orchestrator V2 used legacy flexible planner fallback."
            return plan
        except Exception:
            pass

    if fallback_router:
        plan = fallback_router(message, language, role, requester_student_id, requester_advisor_id, chat_history)
        plan["planner_warning"] = "Agent Orchestrator V2 used old role router fallback."
        plan.setdefault("orchestrator", {"version": "v2", "domain": "fallback", "intent": "fallback", "confidence": 0.3})
        return plan

    return _base_plan(
        message=message, language=language, role=role, requester_student_id=requester_student_id, requester_advisor_id=requester_advisor_id,
        selected_agent=f"{role}_agent_orchestrator_v2", tool_name="none", arguments={"reason": "normal_chat", "answer_style": "short"},
        prompt="ADMIN_NORMAL_CHATGPT_PROMPT" if role == "admin" else ("ADVISOR_AGENT_PROMPT" if role == "advisor" else "STUDENT_AGENT_PROMPT"),
        intent="normal_chat", domain="normal_chat", confidence=0.5, reason="No database domain detected.",
    )
