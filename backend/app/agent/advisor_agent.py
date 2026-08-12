from typing import Dict, Any, List, Optional
from app.agent.intent_classifier import classify_intent
from app.agent.entity_extractor import extract_entities
from app.agent.advisor_class_query import parse_advisor_class_query


def _base(message: str, language: str, advisor_id: str, tool_name: str, arguments: Dict[str, Any], prompt: str, decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "selected_agent": "advisor_agent",
        "role_prompt_name": prompt,
        "tool_name": tool_name,
        "arguments": {**arguments, "original_question": message, "answer_style": decision.get("answer_style")},
        "user_role": "advisor",
        "requester_student_id": None,
        "requester_advisor_id": advisor_id,
        "language": language,
        "intent_decision": decision,
    }



def _student_id_shape(message: str) -> Dict[str, Any]:
    text = (message or "").lower()
    if any(w in text for w in ["grade", "grades", "score", "scores", "subject", "subjects", "course", "class", "เกรด", "คะแนน", "วิชา"]):
        return {"answer_style": "grades", "requested_fields": ["student_id", "name", "program", "academic_status", "subject_grades"]}
    if any(w in text for w in ["profile", "information", "info", "record", "detail", "details", "data", "ข้อมูล", "โปรไฟล์", "รายละเอียด"]):
        return {"answer_style": "profile", "requested_fields": ["student_id", "name", "program", "academic_status", "subject_grades"]}
    return {"answer_style": "short", "requested_fields": ["student_id", "name", "subject_grades"]}


def _explicit_student_plan(message: str, language: str, advisor_id: str, decision: Dict[str, Any], ids: List[str]) -> Dict[str, Any]:
    ids = list(dict.fromkeys([str(x).upper() for x in ids]))
    shape = _student_id_shape(message)
    if len(ids) == 1:
        args = {
            "student_id": ids[0],
            "operation": "read_students",
            "requested_fields": shape["requested_fields"],
            "requested_student_ids": ids,
            "answer_style": shape["answer_style"],
        }
    else:
        args = {
            "student_id": "ALL",
            "operation": "read_students",
            "query_filter": {"student_id": {"$in": ids}},
            "sort": [{"field": "student_id", "direction": "asc"}],
            "limit": len(ids),
            "requested_fields": shape["requested_fields"],
            "requested_student_ids": ids,
            "answer_style": shape["answer_style"],
        }
    return _base(message, language, advisor_id, "mongodb_student_tool", args, "ADVISOR_GRADE_ANALYST_PROMPT", {**decision, "intent": "student_data", "answer_style": shape["answer_style"]})

def _preferred_source_type(message: str):
    low = (message or "").lower()
    if any(w in low for w in ["excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "dataset", "เอ็กเซล", "ชีต"]):
        return "excel"
    if "pdf" in low:
        return "pdf"
    return None


def plan_as_advisor_agent(message: str, language: str, requester_advisor_id: Optional[str], chat_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    advisor_id = requester_advisor_id or "A001"
    decision = classify_intent(message, "advisor", language, chat_history)
    intent = decision.get("intent")
    operation = decision.get("operation") or "normal"

    classroom = parse_advisor_class_query(message)
    if classroom:
        if classroom.get("type") == "advisor_scope_denial":
            return _base(
                message,
                language,
                advisor_id,
                "none",
                {
                    "reason": "advisor_classroom_scope_only",
                    "answer_style": "advisor_scope",
                    "denied_fields": classroom.get("denied_fields") or [],
                },
                "ADVISOR_AGENT_PROMPT",
                decision,
            )
        return _base(
            message,
            language,
            advisor_id,
            "postgres_university_tool",
            {
                "query_type": "advisor_classroom",
                "operation": classroom.get("operation"),
                "course_query": classroom.get("course_query") or "",
                "student_ids": classroom.get("student_ids") or [],
                "requested_metrics": classroom.get("requested_metrics") or ["grade"],
                "direction": classroom.get("direction") or "desc",
                "top_n": classroom.get("top_n") or 20,
                "answer_style": classroom.get("answer_style"),
            },
            "ADVISOR_GRADE_ANALYST_PROMPT",
            {**decision, "answer_style": classroom.get("answer_style")},
        )

    entities = extract_entities(message)
    if entities.get("has_student_id"):
        return _explicit_student_plan(message, language, advisor_id, decision, entities.get("student_ids") or [])

    if intent == "greeting":
        return _base(message, language, advisor_id, "none", {"reason": "greeting"}, "ADVISOR_AGENT_PROMPT", decision)
    if intent == "out_of_scope":
        return _base(message, language, advisor_id, "none", {"reason": "out_of_scope"}, "ADVISOR_AGENT_PROMPT", decision)
    if intent == "document_qa":
        op = decision.get("operation") if decision.get("operation") in {"list_documents", "document_search"} else "document_search"
        return _base(
            message,
            language,
            advisor_id,
            "postgres_university_tool",
            {"query_type": "advisor_documents", "operation": op, "keyword": decision.get("search_query") or message, "preferred_source_type": _preferred_source_type(message)},
            "ADVISOR_DOCUMENT_AGENT_PROMPT",
            decision,
        )
    if intent == "advisor_data":
        return _base(message, language, advisor_id, "mongodb_advisor_tool", {"advisor_id": advisor_id}, "ADVISOR_AGENT_PROMPT", decision)
    if intent == "program_data":
        return _base(message, language, advisor_id, "postgres_university_tool", {"query_type": "programs", "keyword": decision.get("search_query") or message}, "ADVISOR_AGENT_PROMPT", decision)

    target = decision.get("target_student_id") or "ALL"
    if operation == "list_names":
        return _base(message, language, advisor_id, "mongodb_student_tool", {"student_id": "ALL", "operation": "list_names", "requested_fields": ["student_id", "name", "subject_grades"]}, "ADVISOR_GRADE_ANALYST_PROMPT", decision)
    if operation == "grade_summary":
        return _base(message, language, advisor_id, "mongodb_student_tool", {"student_id": target, "operation": "grade_summary", "grade_target": decision.get("grade_target"), "requested_fields": ["student_id", "name", "subject_grades"]}, "ADVISOR_GRADE_ANALYST_PROMPT", decision)
    return _base(message, language, advisor_id, "mongodb_student_tool", {"student_id": target, "operation": "read_students", "requested_fields": ["student_id", "name", "subject_grades"]}, "ADVISOR_GRADE_ANALYST_PROMPT", decision)
