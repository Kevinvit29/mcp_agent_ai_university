from typing import Dict, Any, List, Optional
import re
from app.agent.intent_classifier import classify_intent
from app.agent.admin_database_ai import _database_structure_signal
from app.agent.query_planner_ai import create_universal_admin_plan, build_mcp_plan_from_universal
from app.agent.database_worker_ai import create_database_worker_plan
from app.agent.entity_extractor import extract_entities, wants_profile_or_info

def _base(message: str, language: str, tool_name: str, arguments: Dict[str, Any], prompt: str, decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "selected_agent": "admin_agent",
        "role_prompt_name": prompt,
        "tool_name": tool_name,
        "arguments": {**arguments, "original_question": message, "answer_style": arguments.get("answer_style") or decision.get("answer_style")},
        "user_role": "admin",
        "requester_student_id": None,
        "requester_advisor_id": None,
        "language": language,
        "intent_decision": decision,
    }

def _needs_database_worker(message: str) -> bool:
    low = message.lower()

    worker_keywords = [
        "improve",
        "support",
        "risk",
        "weak",
        "lowest grade",
        "lowest gpa",
        "average gpa",
        "calculate",
        "organize database",
        "clean database",
        "duplicate",
        "import",
        "upload new data",
        "new data",
        "normalize",
        "update calculated",
    ]

    return any(k in low for k in worker_keywords)

def _student_fields(decision: Dict[str, Any]) -> List[str]:
    fields = decision.get("requested_fields") or []
    allowed = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email", "phone", "national_id", "passport_id", "address", "advisor_note"]
    cleaned = [f for f in fields if f in allowed]
    return cleaned or ["student_id", "name"]



def _advisor_id_from_message(message: str) -> Optional[str]:
    m = re.search(r"\bA\d{3}\b", message or "", flags=re.I)
    return m.group(0).upper() if m else None


def _campus_signal(message: str) -> bool:
    text = (message or "").lower()
    return any(w in text for w in [
        "cafeteria", "cafetaria", "canteen", "library", "building", "room", "office",
        "facility", "facilities", "where is", "location", "map",
        "โรงอาหาร", "ห้องสมุด", "อาคาร", "ห้อง", "แผนที่", "อยู่ไหน"
    ])



def _student_request_shape(message: str) -> Dict[str, Any]:
    """Decide what fields are needed for explicit Sxxx questions.

    This is deterministic on purpose. The LLM can misunderstand a question like
    "what is S001, S002, S035 grade" and only plan the first ID. These guards make
    explicit IDs stable and fast.
    """
    text = (message or "").lower()
    grade_words = ["grade", "grades", "score", "scores", "subject", "subjects", "course", "class", "เกรด", "คะแนน", "วิชา"]
    gpa_words = ["gpa", "เกรดเฉลี่ย"]
    name_words = ["name", "ชื่อ"]
    profile_words = ["profile", "information", "info", "record", "detail", "details", "data", "full", "everything", "ข้อมูล", "โปรไฟล์", "รายละเอียด"]

    if any(w in text for w in profile_words):
        return {
            "answer_style": "profile",
            "requested_fields": [
                "student_id", "name", "program", "gpa", "academic_status", "subject_grades",
                "email", "phone", "national_id", "passport_id", "address", "advisor_note",
            ],
        }
    if any(w in text for w in gpa_words) and not any(w in text for w in grade_words):
        return {"answer_style": "gpa", "requested_fields": ["student_id", "name", "gpa"]}
    if any(w in text for w in grade_words):
        return {"answer_style": "grades", "requested_fields": ["student_id", "name", "program", "academic_status", "subject_grades"]}
    if any(w in text for w in name_words):
        return {"answer_style": "names", "requested_fields": ["student_id", "name"]}
    return {
        "answer_style": "profile",
        "requested_fields": ["student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email"],
    }


def _explicit_student_plan(message: str, language: str, decision: Dict[str, Any], entities: Dict[str, Any]) -> Dict[str, Any]:
    ids = []
    for sid in entities.get("student_ids") or []:
        sid = str(sid).upper()
        if sid not in ids:
            ids.append(sid)
    shape = _student_request_shape(message)
    student_decision = {
        **decision,
        "intent": "student_data",
        "operation": "read_students",
        "target_student_id": ids[0] if len(ids) == 1 else "MULTIPLE",
        "target_student_ids": ids,
        "answer_style": shape["answer_style"],
        "confidence": max(float(decision.get("confidence") or 0), 0.99),
    }
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
    return _base(
        message=message,
        language=language,
        tool_name="mongodb_student_tool",
        arguments=args,
        prompt="ADMIN_SUPER_AGENT_PROMPT",
        decision=student_decision,
    )

def _is_all_advisors_request(message: str) -> bool:
    text = (message or "").lower()
    return any(w in text for w in ["all advisors", "list advisors", "advisors", "advisor list", "อาจารย์ทั้งหมด", "รายชื่ออาจารย์"])


def plan_as_admin_agent(message: str, language: str, chat_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Admin is a two-AI flow.

    First AI: understand whether this is normal ChatGPT chat or university data.
    Second AI: DATABASE AI converts university requests into a safe MCP plan.
    """
    
    decision = classify_intent(message, "admin", language, chat_history)
    intent = decision.get("intent")

    if intent == "greeting":
        return _base(message, language, "none", {"reason": "normal_chat"}, "ADMIN_NORMAL_CHATGPT_PROMPT", decision)

    if intent == "out_of_scope" and not _database_structure_signal(message) and not _campus_signal(message):
        # In admin mode, out_of_scope means normal ChatGPT-style answering, not refusal.
        return _base(message, language, "none", {"reason": "normal_chat"}, "ADMIN_NORMAL_CHATGPT_PROMPT", decision)

    if intent == "out_of_scope" and _database_structure_signal(message):
        decision = {**decision, "intent": "program_data", "operation": "normal", "search_query": message}
        
        if intent == "out_of_scope" and _database_structure_signal(message):
            decision = {**decision, "intent": "program_data", "operation": "normal", "search_query": message}
            
    # Entity-first routing guard:
    # Explicit IDs must be answered deterministically and completely.
    # This fixes questions like "what is S001, S002, S035 grade" where an LLM planner
    # may otherwise call only the first ID.
    entities = extract_entities(message)

    if entities["has_student_id"]:
        return _explicit_student_plan(message, language, decision, entities)
        
    if entities["has_advisor_id"]:
        advisor_id = entities["advisor_ids"][0]

        advisor_decision = {
            **decision,
            "intent": "advisor_data",
            "operation": "advisor_profile",
            "target_advisor_id": advisor_id,
            "answer_style": "profile",
        }

        return _base(
            message=message,
            language=language,
            tool_name="mongodb_advisor_tool",
            arguments={
                "advisor_id": advisor_id,
                "operation": "read_advisors",
                "answer_style": "profile",
            },
            prompt="ADMIN_SUPER_AGENT_PROMPT",
            decision=advisor_decision,
        )    

    # Database Worker AI:
    # Use this for calculation, organize database, duplicate check, risk score,
    # lowest GPA, average GPA, new data handling, etc.
    if _needs_database_worker(message):
        worker_plan = create_database_worker_plan(message)

        worker_decision = {
            **decision,
            "intent": "database_worker",
            "operation": worker_plan.get("operation"),
            "answer_style": "summary",
        }

        worker_arguments = {
            **worker_plan,
            "original_question": message,
            "answer_style": "summary",
        }

        return _base(
            message=message,
            language=language,
            tool_name="database_worker_tool",
            arguments=worker_arguments,
            prompt="ADMIN_SUPER_AGENT_PROMPT",
            decision=worker_decision,
        )

    # Flexible multi-agent method:
    # 1) Query Planner AI creates a universal JSON plan.

    # Flexible multi-agent method:
    # 1) Query Planner AI creates a universal JSON plan.
    # 2) Backend validates/converts it into an MCP tool call.
    # This prevents the old bug where filter questions pulled ALL records.
    universal_plan = create_universal_admin_plan(message, language, decision, chat_history)
    db_plan = build_mcp_plan_from_universal(universal_plan, message, language)
    tool_name = db_plan.get("tool_name") or "mongodb_student_tool"
    arguments = db_plan.get("arguments") or {}
    prompt = db_plan.get("role_prompt_name") or "ADMIN_SUPER_AGENT_PROMPT"
    arguments = {
        **arguments,
        "database_ai_reason": db_plan.get("reason"),
        "database_ai_confidence": db_plan.get("confidence"),
    }
    return _base(message, language, tool_name, arguments, prompt, decision)
