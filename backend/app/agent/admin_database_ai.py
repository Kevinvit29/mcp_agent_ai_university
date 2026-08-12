"""Admin Database AI planner.

This module is the second AI in the admin flow:
1. Admin-facing AI understands the user's message.
2. Database AI converts that meaning into a safe MCP/database plan.
3. MCP policy/tool layer retrieves allowed data.
4. Final answer AI explains the result naturally.

The Database AI is intentionally not allowed to mutate schema or data by itself.
It can request safe read/search/list operations and the backend can expose explicit
write endpoints separately, such as PDF upload/delete.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.agent.ai_client import ai_generate_text
from app.agent.natural_query import normalize_typos, document_list_request, friendly_clean_query

ADMIN_FIELDS = [
    "student_id", "name", "program", "gpa", "academic_status", "subject_grades",
    "email", "phone", "national_id", "passport_id", "address", "advisor_note",
]

ALLOWED_TOOLS = {"none", "mongodb_student_tool", "mongodb_advisor_tool", "postgres_university_tool"}
STUDENT_OPERATIONS = {"read_students", "count", "list_names", "grade_summary", "schema_overview"}
ADVISOR_OPERATIONS = {"read_advisors", "list_advisors", "schema_overview"}
POSTGRES_QUERY_TYPES = {
    "programs", "advisor_subjects", "all_documents", "documents", "advisor_documents",
    "tables", "database_map", "query",
}
POSTGRES_OPERATIONS = {"search", "normal", "list_documents", "document_search"}
PROMPTS = {
    "ADMIN_SUPER_AGENT_PROMPT",
    "ADMIN_DIRECTORY_AGENT_PROMPT",
    "ADMIN_GRADE_ANALYST_PROMPT",
    "ADMIN_DOCUMENT_AGENT_PROMPT",
    "ADMIN_PROGRAM_AGENT_PROMPT",
    "ADMIN_NORMAL_CHATGPT_PROMPT",
    "ADMIN_DATABASE_ARCHITECT_PROMPT",
}

DATABASE_AI_SYSTEM_PROMPT = """
You are DATABASE AI, an internal admin-only planning agent for a university AI system.
You do not answer the admin directly. You choose exactly one safe database/tool plan.

Architecture:
- Admin-facing AI talks naturally with the user.
- You are the second AI that understands the database and rearranges the request into a safe MCP tool call.
- The MCP server and PDPA policy still enforce access. Admin is allowed all university data.
- You may retrieve, list, search, summarize, or map data. You must NOT silently edit/delete/rewrite schema or private records.

Available data/tool catalog:
1) mongodb_student_tool
   - student records in MongoDB.
   - args: student_id: "ALL" or "S001" style ID; operation: read_students|count|list_names|grade_summary|schema_overview; requested_fields; grade_target optional.
   - fields: student_id, name, program, gpa, academic_status, subject_grades, email, phone, national_id, passport_id, address, advisor_note.
2) mongodb_advisor_tool
   - advisor records in MongoDB.
   - args: advisor_id: "ALL" or "A001" style ID; operation: read_advisors|list_advisors|schema_overview.
3) postgres_university_tool
   - programs, advisor_subjects, uploaded PDF/Excel files/documents, database table map.
   - args examples:
     {"query_type":"programs","keyword":"Computer Science"}
     {"query_type":"advisor_subjects","keyword":""}
     {"query_type":"all_documents","operation":"list_documents","keyword":""}
     {"query_type":"all_documents","operation":"document_search","keyword":"writing report"}
     {"query_type":"database_map","keyword":""}
     {"query_type":"tables","keyword":""}
     {"query_type":"query","sql":"SELECT ..."} only when a simple SELECT on public Postgres tables is clearly needed.
4) none
   - use only if the request does not need university database data.

Routing rules:
- Normal writing/coding/math/translation/general ChatGPT tasks -> tool_name none.
- Student/private/profile/grade/name/count/all students -> mongodb_student_tool.
- Advisor list/profile -> mongodb_advisor_tool.
- Admissions/program/tuition/faculty -> postgres_university_tool query_type programs.
- Uploaded PDF/file/document questions -> postgres_university_tool query_type all_documents for admin.
- "what data do you have", "database structure", "tables", "schema", "what can admin access" -> postgres_university_tool query_type database_map.
- Broad "everything / whole university overview" can start with database_map; backend may collect extra context.

Return ONLY valid JSON:
{
  "tool_name": "none|mongodb_student_tool|mongodb_advisor_tool|postgres_university_tool",
  "arguments": {},
  "role_prompt_name": "ADMIN_SUPER_AGENT_PROMPT|ADMIN_DIRECTORY_AGENT_PROMPT|ADMIN_GRADE_ANALYST_PROMPT|ADMIN_DOCUMENT_AGENT_PROMPT|ADMIN_PROGRAM_AGENT_PROMPT|ADMIN_NORMAL_CHATGPT_PROMPT|ADMIN_DATABASE_ARCHITECT_PROMPT",
  "reason": "short internal reason",
  "confidence": 0.0
}
""".strip()


def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    return m.group(0) if m else text


def _student_id(text: str) -> Optional[str]:
    m = re.search(r"\bS\d{3,6}\b", text or "", flags=re.I)
    return m.group(0).upper() if m else None


def _advisor_id(text: str) -> Optional[str]:
    m = re.search(r"\bA\d{3}\b", text or "", flags=re.I)
    return m.group(0).upper() if m else None


def _grade_target(text: str) -> Optional[str]:
    m = re.search(r"(?:grade\s*)?\b([ABCDF][+-]?)\b", text or "", flags=re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"เกรด\s*([ABCDF][+-]?)", text or "", flags=re.I)
    return m.group(1).upper() if m else None



def _explicit_document_signal(text: str) -> bool:
    low = normalize_typos(text)
    signals = {
        "pdf", "document", "documents", "file", "files", "upload", "uploaded", "uploads", "stored",
        "policy", "rule", "announcement", "manual", "form", "syllabus", "material", "materials",
        "lesson", "assignment", "homework", "notes", "worksheet", "report", "writing", "essay", "article",
        "เอกสาร", "ไฟล์", "อัปโหลด", "นโยบาย", "ประกาศ", "ตำรา", "หนังสือ", "รายงาน", "เขียน", "บทเรียน", "การบ้าน",
    }
    tokens = set(re.findall(r"[a-z0-9฀-๿]+", low))
    return any(sig in tokens or sig in low for sig in signals)


def _database_structure_signal(text: str) -> bool:
    low = normalize_typos(text)
    return any(w in low for w in [
        "schema", "database map", "database structure", "tables", "columns", "what data",
        "what can you access", "what do you know", "all database", "db map", "data stores",
        "โครงสร้าง", "ตาราง", "ฐานข้อมูล", "เข้าถึงอะไร",
    ])

def _fallback_plan(message: str, decision: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic fallback. This keeps the app usable when the AI provider is missing."""
    text = normalize_typos(message)
    low = text.lower()
    intent = decision.get("intent")
    operation = decision.get("operation") or "normal"

    if intent in {"greeting", "out_of_scope"}:
        return {
            "tool_name": "none",
            "arguments": {"reason": "normal_chat"},
            "role_prompt_name": "ADMIN_NORMAL_CHATGPT_PROMPT",
            "reason": "Admin normal ChatGPT mode.",
            "confidence": 0.85,
        }

    if _database_structure_signal(message):
        return {
            "tool_name": "postgres_university_tool",
            "arguments": {"query_type": "database_map", "keyword": text},
            "role_prompt_name": "ADMIN_DATABASE_ARCHITECT_PROMPT",
            "reason": "Admin asked for database/schema/access overview.",
            "confidence": 0.95,
        }

    if intent == "document_qa":
        # Some broad words like "explain" can be misclassified as document_qa.
        # In admin mode, keep normal ChatGPT behavior unless there is a real document/PDF signal.
        if not _explicit_document_signal(message):
            return {
                "tool_name": "none",
                "arguments": {"reason": "normal_chat"},
                "role_prompt_name": "ADMIN_NORMAL_CHATGPT_PROMPT",
                "reason": "No explicit database/PDF signal; answer as normal ChatGPT.",
                "confidence": 0.84,
            }
        op = operation if operation in {"list_documents", "document_search"} else ("list_documents" if document_list_request(message) else "document_search")
        return {
            "tool_name": "postgres_university_tool",
            "arguments": {"query_type": "all_documents", "operation": op, "keyword": decision.get("search_query") or friendly_clean_query(message)},
            "role_prompt_name": "ADMIN_DOCUMENT_AGENT_PROMPT",
            "reason": "Admin requested uploaded document/PDF knowledge.",
            "confidence": 0.94,
        }

    if intent == "program_data":
        return {
            "tool_name": "postgres_university_tool",
            "arguments": {"query_type": "programs", "keyword": decision.get("search_query") or message},
            "role_prompt_name": "ADMIN_PROGRAM_AGENT_PROMPT",
            "reason": "Admin requested program/admission information.",
            "confidence": 0.9,
        }

    if intent == "advisor_data" or any(w in low for w in ["advisor", "advisors", "อาจารย์", "ที่ปรึกษา"]):
        aid = _advisor_id(message) or decision.get("advisor_id")
        list_all = not aid or any(w in low for w in ["all", "list", "ทุก", "ทั้งหมด", "รายชื่อ"])
        return {
            "tool_name": "mongodb_advisor_tool",
            "arguments": {"advisor_id": "ALL" if list_all else aid, "operation": "list_advisors" if list_all else "read_advisors"},
            "role_prompt_name": "ADMIN_SUPER_AGENT_PROMPT",
            "reason": "Admin requested advisor data.",
            "confidence": 0.92,
        }

    # Default: student data. Admin may access all fields, but keep minimization unless asked broadly.
    target = decision.get("target_student_id") or _student_id(message) or "ALL"
    fields = [f for f in (decision.get("requested_fields") or []) if f in ADMIN_FIELDS]
    wants_full = any(w in low for w in ["full", "everything", "every single", "all fields", "private", "profile", "ข้อมูลทั้งหมด", "ทั้งหมด"])
    if not fields:
        fields = ADMIN_FIELDS if wants_full else ["student_id", "name"]

    if operation == "count" or any(w in low for w in ["how many", "count", "กี่คน", "จำนวน"]):
        return {
            "tool_name": "mongodb_student_tool",
            "arguments": {"student_id": target, "operation": "count", "requested_fields": ["student_id"]},
            "role_prompt_name": "ADMIN_DIRECTORY_AGENT_PROMPT",
            "reason": "Admin requested student count.",
            "confidence": 0.93,
        }
    if operation == "list_names" or any(w in low for w in ["list names", "student names", "รายชื่อ", "ชื่อทั้งหมด"]):
        return {
            "tool_name": "mongodb_student_tool",
            "arguments": {"student_id": "ALL", "operation": "list_names", "requested_fields": ["student_id", "name"]},
            "role_prompt_name": "ADMIN_DIRECTORY_AGENT_PROMPT",
            "reason": "Admin requested student directory.",
            "confidence": 0.93,
        }
    if operation == "grade_summary" or (any(w in low for w in ["grade", "grades", "score", "เกรด", "คะแนน"]) and any(w in low for w in ["summary", "count", "all", "ทุก", "สรุป", "กี่"])):
        return {
            "tool_name": "mongodb_student_tool",
            "arguments": {"student_id": target, "operation": "grade_summary", "grade_target": decision.get("grade_target") or _grade_target(message), "requested_fields": ["student_id", "name", "subject_grades"]},
            "role_prompt_name": "ADMIN_GRADE_ANALYST_PROMPT",
            "reason": "Admin requested grade analysis.",
            "confidence": 0.93,
        }

    return {
        "tool_name": "mongodb_student_tool",
        "arguments": {"student_id": target, "operation": "read_students", "requested_fields": fields},
        "role_prompt_name": "ADMIN_SUPER_AGENT_PROMPT",
        "reason": "Admin requested student data.",
        "confidence": 0.88,
    }


def _safe_select_sql(sql: str) -> bool:
    clean = (sql or "").strip().lower()
    if not clean.startswith("select"):
        return False
    # Keep generated SQL read-only and simple. The database tool also blocks non-SELECT.
    blocked = ["insert", "update", "delete", "drop", "alter", "truncate", "create", "grant", "revoke", "copy", "execute"]
    return not any(re.search(rf"\b{word}\b", clean) for word in blocked)


def _validate_plan(plan: Dict[str, Any], message: str, decision: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(plan, dict):
        return None
    tool_name = str(plan.get("tool_name") or "").strip()
    if tool_name not in ALLOWED_TOOLS:
        return None
    arguments = plan.get("arguments") or {}
    if not isinstance(arguments, dict):
        return None
    prompt = str(plan.get("role_prompt_name") or "ADMIN_SUPER_AGENT_PROMPT").strip()
    if prompt not in PROMPTS:
        prompt = "ADMIN_SUPER_AGENT_PROMPT"

    if tool_name == "none":
        return {
            "tool_name": "none",
            "arguments": {"reason": "normal_chat"},
            "role_prompt_name": "ADMIN_NORMAL_CHATGPT_PROMPT",
            "reason": str(plan.get("reason") or "Admin normal chat."),
            "confidence": float(plan.get("confidence") or 0.0),
        }

    if tool_name == "mongodb_student_tool":
        sid = str(arguments.get("student_id") or decision.get("target_student_id") or _student_id(message) or "ALL").upper()
        if sid != "ALL" and not re.fullmatch(r"S\d{3,6}", sid):
            sid = "ALL"
        operation = str(arguments.get("operation") or "read_students")
        if operation not in STUDENT_OPERATIONS:
            operation = "read_students"
        fields = arguments.get("requested_fields") or []
        if not isinstance(fields, list):
            fields = []
        fields = [f for f in fields if f in ADMIN_FIELDS]
        if not fields and operation not in {"count", "list_names", "schema_overview"}:
            fields = [f for f in (decision.get("requested_fields") or []) if f in ADMIN_FIELDS] or ["student_id", "name"]
        clean_args = {"student_id": sid, "operation": operation, "requested_fields": fields}
        gt = arguments.get("grade_target") or decision.get("grade_target") or _grade_target(message)
        if gt:
            clean_args["grade_target"] = str(gt).upper()
        return {"tool_name": tool_name, "arguments": clean_args, "role_prompt_name": prompt, "reason": str(plan.get("reason") or "Student data plan."), "confidence": float(plan.get("confidence") or 0.0)}

    if tool_name == "mongodb_advisor_tool":
        aid = str(arguments.get("advisor_id") or _advisor_id(message) or "ALL").upper()
        if aid != "ALL" and not re.fullmatch(r"A\d{3}", aid):
            aid = "ALL"
        operation = str(arguments.get("operation") or ("list_advisors" if aid == "ALL" else "read_advisors"))
        if operation not in ADVISOR_OPERATIONS:
            operation = "list_advisors" if aid == "ALL" else "read_advisors"
        return {"tool_name": tool_name, "arguments": {"advisor_id": aid, "operation": operation}, "role_prompt_name": prompt, "reason": str(plan.get("reason") or "Advisor data plan."), "confidence": float(plan.get("confidence") or 0.0)}

    if tool_name == "postgres_university_tool":
        qtype = str(arguments.get("query_type") or "programs")
        if qtype not in POSTGRES_QUERY_TYPES:
            qtype = "programs"
        clean_args: Dict[str, Any] = {"query_type": qtype}
        if qtype == "query":
            sql = str(arguments.get("sql") or "").strip()
            if not _safe_select_sql(sql):
                return _fallback_plan(message, decision)
            clean_args["sql"] = sql
        else:
            operation = str(arguments.get("operation") or ("list_documents" if document_list_request(message) else "search"))
            if operation not in POSTGRES_OPERATIONS:
                operation = "search"
            clean_args["operation"] = operation
            clean_args["keyword"] = str(arguments.get("keyword") or decision.get("search_query") or friendly_clean_query(message) or "")
        return {"tool_name": tool_name, "arguments": clean_args, "role_prompt_name": prompt, "reason": str(plan.get("reason") or "Postgres data plan."), "confidence": float(plan.get("confidence") or 0.0)}

    return None


def plan_admin_database_task(
    message: str,
    language: str,
    decision: Dict[str, Any],
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a validated MCP plan for admin requests.

    The configured AI provider is used as the second AI when available. If it is unavailable or returns an
    unsafe/invalid plan, a deterministic fallback creates the database plan.
    """
    fallback = _fallback_plan(message, decision)
    prompt = f"""
Language: {language}
Intent decision from first AI:
{json.dumps(decision, ensure_ascii=False)}

Recent chat history for follow-up interpretation only:
{json.dumps((chat_history or [])[-8:], ensure_ascii=False)[:4000]}

Latest admin message:
{message}

Choose the safest single database/tool plan.
""".strip()
    try:
        raw = ai_generate_text(
            system_prompt=DATABASE_AI_SYSTEM_PROMPT,
            prompt=prompt,
            json_mode=True,
            timeout_env="GEMINI_INTENT_TIMEOUT",
            default_timeout=60,
            temperature=0.0,
            max_output_tokens=2048,
        )
        if not raw:
            return fallback
        parsed = json.loads(_clean_json_text(raw))
        validated = _validate_plan(parsed, message, decision)
        return validated or fallback
    except Exception:
        return fallback
