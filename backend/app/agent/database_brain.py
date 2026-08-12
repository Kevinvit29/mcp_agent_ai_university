"""Database Brain: high-confidence routing and self-repair layer.

This layer exists because an LLM planner alone can misunderstand short or messy
questions. The Database Brain does not replace Gemini. It guards the data flow:
1) understand the data domain the user is asking about,
2) choose a safe MCP tool/operation when the intent is obvious,
3) validate that the tool result matches the requested domain,
4) repair one bad plan before the final response is written.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.natural_query import normalize_typos, document_list_request


SUBJECT_WORDS = {
    "subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา", "คอร์ส",
}
STUDENT_WORDS = {"student", "students", "people", "person", "นักศึกษา", "นักเรียน", "คน"}
COUNT_WORDS = {"how many", "count", "number of", "total", "กี่", "กี่วิชา", "จำนวน", "ทั้งหมด"}
LIST_WORDS = {"list", "show", "what are", "which", "all", "รายชื่อ", "แสดง", "มีอะไรบ้าง"}
PROGRAM_WORDS = {"program", "programs", "major", "majors", "faculty", "faculties", "หลักสูตร", "สาขา", "คณะ"}
DOCUMENT_WORDS = {"pdf", "document", "documents", "file", "files", "excel", "xlsx", "csv", "spreadsheet", "uploaded", "upload", "เอกสาร", "ไฟล์", "เอ็กเซล"}
ADVISOR_WORDS = {"advisor", "advisors", "teacher", "teachers", "อาจารย์", "ที่ปรึกษา"}


def _text(message: str) -> str:
    return normalize_typos(message or "").lower().strip()


def _has_any(text: str, words: set[str]) -> bool:
    return any(w in text for w in words)


def _recent_context_text(history: Optional[List[Dict[str, Any]]], max_items: int = 6) -> str:
    if not history:
        return ""
    chunks: List[str] = []
    for item in history[-max_items:]:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if content:
            chunks.append(f"{role}: {content}")
    return "\n".join(chunks).lower()


def _is_subject_request(message: str, history: Optional[List[Dict[str, Any]]] = None) -> bool:
    text = _text(message)
    context = _recent_context_text(history)

    # Clear direct subject questions.
    if _has_any(text, SUBJECT_WORDS):
        # If a student ID is present, the role agent should answer that student's subjects/grades.
        if re.search(r"\bS\d{3,6}\b", message or "", flags=re.I):
            return False
        # Uploaded subject files are document questions, not subject catalog questions.
        if _has_any(text, DOCUMENT_WORDS):
            return False
        return True

    # Short correction after the bot answered the wrong domain.
    # Example: user: "how many subject..." -> bot: "100 students" -> user: "i mean subject".
    short_corrections = {"i mean subject", "mean subject", "subject", "subjects", "วิชา", "หมายถึงวิชา"}
    if text in short_corrections and "student" in context:
        return True

    return False


def _is_program_request(message: str) -> bool:
    text = _text(message)
    if _has_any(text, PROGRAM_WORDS) and not re.search(r"\bS\d{3,6}\b", message or "", flags=re.I):
        return True
    return False


def _is_document_request(message: str) -> bool:
    text = _text(message)
    return _has_any(text, DOCUMENT_WORDS) or document_list_request(message)


def _is_advisor_count_request(message: str) -> bool:
    text = _text(message)
    return _has_any(text, ADVISOR_WORDS) and (_has_any(text, COUNT_WORDS) or _has_any(text, LIST_WORDS))


def _common_plan(message: str, language: str, user_role: str, requester_student_id: Optional[str], requester_advisor_id: Optional[str], tool_name: str, arguments: Dict[str, Any], prompt: str, reason: str) -> Dict[str, Any]:
    role = (user_role or "student").lower()
    return {
        "selected_agent": f"{role}_database_brain",
        "role_prompt_name": prompt,
        "tool_name": tool_name,
        "arguments": {
            **arguments,
            "original_question": message,
            "database_brain_reason": reason,
            "answer_style": arguments.get("answer_style") or "summary",
        },
        "user_role": role,
        "requester_student_id": requester_student_id,
        "requester_advisor_id": requester_advisor_id,
        "language": language,
        "intent_decision": {
            "source": "database_brain_guard",
            "intent": arguments.get("operation") or arguments.get("query_type") or "database_query",
            "confidence": 0.99,
            "reason": reason,
        },
    }


def build_database_brain_plan(
    message: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Return a high-confidence plan when the domain is obvious.

    This prevents questions like "how many subjects are there" from being routed
    to student_count simply because the phrase also contains "how many".
    """
    role = (user_role or "student").lower()
    text = _text(message)

    # Explicit documents go to the document knowledge base.
    if _is_document_request(message):
        if role == "student":
            qtype = "advisor_documents"
            prompt = "STUDENT_ADVISOR_DOCUMENT_PROMPT"
        elif role == "advisor":
            qtype = "advisor_documents"
            prompt = "ADVISOR_DOCUMENT_AGENT_PROMPT"
        else:
            qtype = "all_documents"
            prompt = "ADMIN_DOCUMENT_AGENT_PROMPT"
        return _common_plan(
            message, language, role, requester_student_id, requester_advisor_id,
            "postgres_university_tool",
            {
                "query_type": qtype,
                "operation": "list_documents" if document_list_request(message) or _has_any(text, LIST_WORDS | COUNT_WORDS) else "document_search",
                "keyword": message,
                "preferred_source_type": "excel" if any(w in text for w in ["excel", "xlsx", "csv", "spreadsheet", "เอ็กเซล"]) else ("pdf" if "pdf" in text else None),
                "answer_style": "summary",
            },
            prompt,
            "The latest message asks about uploaded PDF/Excel/document knowledge.",
        )

    # Subject catalog/count/list questions. Use Mongo subject_grades because the seeded
    # university data creates all subject names there, while Postgres advisor_subjects
    # only stores the initial teaching links.
    if _is_subject_request(message, chat_history):
        return _common_plan(
            message, language, role, requester_student_id, requester_advisor_id,
            "mongodb_student_tool",
            {
                "student_id": requester_student_id if role == "student" and requester_student_id else "ALL",
                "operation": "subject_summary",
                "requested_fields": ["student_id", "name", "subject_grades"],
                "limit": 5000,
                "answer_style": "subject_summary",
            },
            "ADMIN_SUBJECT_AGENT_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT"),
            "The latest message asks about university subjects/courses, not student count.",
        )

    # Program/major/faculty questions.
    if _is_program_request(message):
        return _common_plan(
            message, language, role, requester_student_id, requester_advisor_id,
            "postgres_university_tool",
            {"query_type": "programs", "operation": "search", "keyword": message, "answer_style": "summary"},
            "ADMIN_PROGRAM_AGENT_PROMPT",
            "The latest message asks about programs/majors/faculties.",
        )

    # Advisor count/list questions.
    if _is_advisor_count_request(message):
        return _common_plan(
            message, language, role, requester_student_id, requester_advisor_id,
            "mongodb_advisor_tool",
            {"advisor_id": "ALL", "operation": "list_advisors", "answer_style": "summary"},
            "ADMIN_SUPER_AGENT_PROMPT",
            "The latest message asks for advisor count/list.",
        )

    return None


def expected_domain(message: str, chat_history: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    if _is_subject_request(message, chat_history):
        return "subjects"
    if _is_document_request(message):
        return "documents"
    if _is_program_request(message):
        return "programs"
    if _is_advisor_count_request(message):
        return "advisors"
    return None


def _result_type(tool_result: Dict[str, Any]) -> str:
    data = tool_result.get("data") if isinstance(tool_result, dict) else None
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        data = data.get("data")
    if isinstance(data, dict):
        return str(data.get("type") or "")
    return "list" if isinstance(data, list) else ""


def repair_plan_if_result_mismatch(
    message: str,
    language: str,
    user_role: str,
    plan: Dict[str, Any],
    tool_result: Dict[str, Any],
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Repair one obviously wrong database call before final answer.

    Example fixed:
    user asks "how many subjects" but planner produced mongodb_student_tool count,
    result type is student_count. The brain reroutes to subject_summary.
    """
    domain = expected_domain(message, chat_history)
    if not domain:
        return None

    current_type = _result_type(tool_result)
    tool = plan.get("tool_name")
    args = plan.get("arguments") or {}

    if domain == "subjects" and not (tool == "mongodb_student_tool" and args.get("operation") == "subject_summary"):
        repaired = build_database_brain_plan(message, language, user_role, requester_student_id, requester_advisor_id, chat_history)
        if repaired:
            repaired["planner_warning"] = f"Database Brain repaired mismatched result type '{current_type or tool}' into subject_summary."
        return repaired

    if domain == "documents" and not (tool == "postgres_university_tool" and args.get("query_type") in {"documents", "advisor_documents", "all_documents"}):
        repaired = build_database_brain_plan(message, language, user_role, requester_student_id, requester_advisor_id, chat_history)
        if repaired:
            repaired["planner_warning"] = f"Database Brain repaired mismatched result type '{current_type or tool}' into document search."
        return repaired

    if domain == "programs" and not (tool == "postgres_university_tool" and args.get("query_type") == "programs"):
        repaired = build_database_brain_plan(message, language, user_role, requester_student_id, requester_advisor_id, chat_history)
        if repaired:
            repaired["planner_warning"] = f"Database Brain repaired mismatched result type '{current_type or tool}' into program search."
        return repaired

    return None
