import re
from typing import Dict, Any, List, Optional
from app.agent.intent_classifier import classify_intent
from app.agent.natural_query import normalize_typos, looks_like_self_data_request, looks_like_profile_request, document_list_request


STUDENT_ALLOWED_FIELDS = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email"]


def _base(message: str, language: str, student_id: str, tool_name: str, arguments: Dict[str, Any], prompt: str, decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "selected_agent": "student_agent",
        "role_prompt_name": prompt,
        "tool_name": tool_name,
        "arguments": {**arguments, "original_question": message, "answer_style": decision.get("answer_style")},
        "user_role": "student",
        "requester_student_id": student_id,
        "requester_advisor_id": None,
        "language": language,
        "intent_decision": decision,
    }


def _mentioned_student_id(message: str) -> Optional[str]:
    match = re.search(r"\bS\d{3,6}\b", message or "", flags=re.I)
    return match.group(0).upper() if match else None


def _looks_like_self_profile_request(message: str) -> bool:
    # Handles typos like "wht is my gade" / "my gard" / "my porfile".
    return looks_like_self_data_request(message)


def _student_fields(decision: Dict[str, Any], message: str = "") -> List[str]:
    allowed = set(STUDENT_ALLOWED_FIELDS)
    fields = [f for f in (decision.get("requested_fields") or []) if f in allowed]
    text = normalize_typos(message or "")

    # For broad self questions like "my profile", "my information", or "my record",
    # return the full student-visible record instead of only student_id/name.
    broad_profile_words = [
        "profile", "information", "info", "record", "details", "detail", "data", "everything",
        "all about me", "ข้อมูล", "โปรไฟล์", "ข้อมูลส่วนตัว", "รายละเอียด", "ทั้งหมด"
    ]
    if any(w in text for w in broad_profile_words):
        return STUDENT_ALLOWED_FIELDS

    if "gpa" in text or "เกรดเฉลี่ย" in text:
        return ["student_id", "name", "gpa"]

    grade_words = ["grade", "grades", "score", "scores", "subject", "subjects", "course", "class", "เกรด", "คะแนน", "วิชา"]
    if any(w in text for w in grade_words):
        return ["student_id", "name", "program", "academic_status", "subject_grades"]

    return fields or ["student_id", "name", "program", "gpa", "academic_status", "email"]


def _preferred_source_type(message: str):
    low = (message or "").lower()
    if any(w in low for w in ["excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "dataset", "เอ็กเซล", "ชีต"]):
        return "excel"
    if "pdf" in low:
        return "pdf"
    return None


def plan_as_student_agent(message: str, language: str, requester_student_id: Optional[str], chat_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    student_id = requester_student_id or "S001"
    decision = classify_intent(message, "student", language, chat_history)
    intent = decision.get("intent")
    mentioned_id = _mentioned_student_id(message)

    # Student asking another student's record: still route to the student tool with the
    # mentioned ID so the MCP PDPA guard blocks it cleanly and explains the permission rule.
    if mentioned_id and mentioned_id != student_id:
        decision["intent"] = "student_data"
        decision["target_student_id"] = mentioned_id
        return _base(
            message,
            language,
            student_id,
            "mongodb_student_tool",
            {"student_id": mentioned_id, "operation": "read_students", "requested_fields": _student_fields(decision, message)},
            "STUDENT_SELF_DATA_AGENT_PROMPT",
            decision,
        )

    # Deterministic guard: the logged-in student must always be able to ask for their
    # own profile/grades/GPA without relying on the LLM intent classifier.
    if _looks_like_self_profile_request(message):
        decision["intent"] = "student_data"
        decision["target_student_id"] = student_id
        return _base(
            message,
            language,
            student_id,
            "mongodb_student_tool",
            {"student_id": student_id, "operation": "read_students", "requested_fields": _student_fields(decision, message)},
            "STUDENT_SELF_DATA_AGENT_PROMPT",
            decision,
        )

    if intent == "greeting":
        return _base(message, language, student_id, "none", {"reason": "greeting"}, "STUDENT_AGENT_PROMPT", decision)
    if intent == "advisor_data":
        return _base(message, language, student_id, "none", {"reason": "out_of_scope"}, "STUDENT_AGENT_PROMPT", decision)
    if intent == "out_of_scope":
        return _base(message, language, student_id, "none", {"reason": "out_of_scope"}, "STUDENT_AGENT_PROMPT", decision)
    if intent == "document_qa":
        op = decision.get("operation") if decision.get("operation") in {"list_documents", "document_search"} else "document_search"
        return _base(
            message,
            language,
            student_id,
            "postgres_university_tool",
            {"query_type": "advisor_documents", "operation": op, "keyword": decision.get("search_query") or message, "preferred_source_type": _preferred_source_type(message)},
            "STUDENT_ADVISOR_DOCUMENT_PROMPT",
            decision,
        )
    if intent == "program_data":
        return _base(message, language, student_id, "postgres_university_tool", {"query_type": "programs", "keyword": decision.get("search_query") or message}, "STUDENT_AGENT_PROMPT", decision)

    # Normal student data request: only use the logged-in student's own ID unless the
    # user explicitly mentioned another ID above, which is handled and blocked by policy.
    return _base(
        message,
        language,
        student_id,
        "mongodb_student_tool",
        {"student_id": student_id, "operation": decision.get("operation") or "read_students", "requested_fields": _student_fields(decision, message), "grade_target": decision.get("grade_target")},
        "STUDENT_SELF_DATA_AGENT_PROMPT",
        decision,
    )
