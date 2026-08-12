"""Flexible Admin Query Planner AI.

This is the "AI teaches AI" layer in a safer form:
- It converts any admin question into a universal JSON query plan.
- The backend validates that plan before MCP/database execution.
- The MCP tool executes only safe read operations.

The goal is not to hard-code every possible phrase. The goal is:
natural language -> structured plan -> safe database query.
"""

from __future__ import annotations

from email import message
from html import entities
import json
import re
from typing import Any, Dict, List, Optional

from app.agent.ai_client import ai_generate_text
from app.agent.natural_query import normalize_typos, document_list_request, friendly_clean_query

from app.agent.semantic_rewrite_ai import semantic_rewrite_for_planning
from app.agent.multilingual_query import enrich_message_for_planning
from app.agent.plan_critic_ai import critique_and_repair_plan

ADMIN_STUDENT_FIELDS = [
    "student_id", "name", "program", "gpa", "academic_status", "subject_grades",
    "email", "phone", "national_id", "passport_id", "address", "advisor_note",
]

SAFE_FILTER_FIELDS = {
    "student_id", "name", "program", "gpa", "academic_status",
    "subject_grades.subject", "subject_grades.grade", "subject_grades.advisor_id",
    "advisor_id", "department", "keyword", "filename", "subject_name", "building", "location",
}
SAFE_SORT_FIELDS = {"student_id", "name", "program", "gpa", "academic_status", "advisor_id", "department", "created_at"}
SAFE_OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte", "contains", "in", "between"}
SAFE_INTENTS = {
    "normal_chat", "query_students", "query_subjects", "query_advisors", "query_documents",
    "query_campus_info", "database_overview", "query_academic_records", "clarify",
}

PLANNER_PROMPT = """
You are the Admin Query Planner AI for a university database assistant.
You do NOT answer the admin directly. You convert the admin's natural language into a safe JSON query plan.

Core idea:
- The admin can ask almost anything.
- If the question needs university data, create a flexible query plan.
- If the question is normal ChatGPT/general help, use intent normal_chat.
- If the database probably does not contain the requested source, still route to the closest source and set missing_data_risk=true.
- Never pull all records when the user asks for a condition, ranking, top, lowest, highest, count, or limit.

Available sources:
1. mongodb_students
Fields: student_id, name, program, gpa, academic_status, subject_grades, email, phone, national_id, passport_id, address, advisor_note.
Use for students, profiles, GPA, grades, weak students, strong students, lowest/highest, students needing improvement, count/list/filter/rank.
Use query_subjects for university-wide subject/course count/list/summary questions.

2. mongodb_advisors
Fields: advisor_id, name, department, email, phone, teaches.
Use for advisors, advisor profile, advisor list, advisor teaching links.

3. postgres_documents
Use for uploaded PDF files, Excel/CSV files, document content, policies, rules, lesson materials.

4. campus_info
Use for cafeteria, buildings, offices, rooms, facilities, opening hours, location questions.
If the schema does not have campus_info yet, set missing_data_risk=true.

5. database_overview
Use for schema, tables, collections, fields, what data exists, what admin can access.

6. postgres_academic_records
Use query_academic_records for normalized course catalog, attendance, enrolment, term, scholarship, academic risk, or a detailed academic profile.
Use it especially when the request names a student ID together with attendance, enrolment, term, scholarship, finance, support, or risk.

Return ONLY valid JSON, no markdown:
{
  "intent": "normal_chat | query_students | query_subjects | query_advisors | query_documents | query_campus_info | database_overview | query_academic_records | clarify",
  "goal": "short meaning of the request",
  "data_sources": ["mongodb_students"],
  "operation": "find | count | filter | rank | aggregate | compare | summarize | search | schema | unknown",
  "filters": [
    {"field":"gpa", "operator":"lt", "value":3.0}
  ],
  "select": ["student_id", "name", "program", "gpa", "academic_status"],
  "sort": [
    {"field":"gpa", "direction":"asc"}
  ],
  "limit": 20,
  "create_report_if_over": 20,
  "needs_schema_lookup": false,
  "missing_data_risk": false,
  "clarifying_question": null,
  "answer_style": "short | table | summary | detailed_report",
  "confidence": 0.0
}

Examples:
- "name me the person that have gpa lower than 3.0"
  intent=query_students, operation=filter, filters=[{field:gpa,operator:lt,value:3.0}], select=[student_id,name,program,gpa,academic_status]

- "lower than 2.50"
  If the context is student GPA/grades, use filters=[{field:gpa,operator:lt,value:2.5}].

- "which one has the lowest grade"
  If no subject is named, rank students by gpa ascending, limit=1.

- "which student have to improve grade list me 10 student"
  intent=query_students, operation=rank, sort=[{field:gpa,direction:asc}], limit=10, select=[student_id,name,program,gpa,academic_status,subject_grades].

- "top 10 students"
  rank by gpa descending, limit=10.

- "where is cafeteria"
  intent=query_campus_info, operation=search, filters=[{field:keyword,operator:contains,value:cafeteria}], missing_data_risk=true.

- "how many subjects are there in this university"
  intent=query_subjects, operation=count, data_sources=[mongodb_students], select=[subject_grades]

- "list all subjects"
  intent=query_subjects, operation=find, data_sources=[mongodb_students], select=[subject_grades]

- "show S1000 attendance and enrolments"
  intent=query_academic_records, operation=find, data_sources=[postgres_academic_records]

- "summarize students at academic risk by program"
  intent=query_academic_records, operation=aggregate, data_sources=[postgres_academic_records]

Rules:
1. Use lt/lte/gt/gte for numbers like GPA lower than, under, above, more than.
2. Use rank + sort for lowest, highest, top, best, worst, weakest, needs improvement.
3. For "list me 10", limit=10.
4. For "all" or "export", answer_style=detailed_report and create_report_if_over=20.
5. Do not invent fields. Use missing_data_risk=true if a source may not exist.
6. Admin has full access, but the plan must still be minimal and structured.

ENTITY PRIORITY RULES:

1. If the user message contains a student ID pattern like S001, S035, S100, route to query_students.
Do not route to documents unless the user clearly asks for that student's uploaded PDF/document.

Examples:
"S035 profile" -> query_students
"give me S035 information" -> query_students
"show S035 PDF" -> query_documents
"documents for S035" -> query_documents

2. If the user message contains an advisor ID pattern like A001, A035, route to query_advisors.

3. The word "profile" usually means student/advisor profile if an ID is present.
It does not mean PDF profile.

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


def _number_after(pattern: str, text: str) -> Optional[float]:
    m = re.search(pattern, text, flags=re.I)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _limit_from_text(text: str, default: int = 20) -> int:
    low = text.lower()
    patterns = [
        r"(?:list|show|give|top|bottom)\s+(?:me\s+)?(\d{1,3})\b",
        r"\b(\d{1,3})\s+(?:students|student|people|records|คน)\b",
    ]
    for p in patterns:
        m = re.search(p, low)
        if m:
            return max(1, min(int(m.group(1)), 200))
    return default


def _fallback_universal_plan(message: str, decision: Optional[Dict[str, Any]] = None, chat_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Deterministic planner for common patterns when the AI provider is missing/unclear."""
    decision = decision or {}
    text = normalize_typos(message or "")
    low = text.lower()
    limit = _limit_from_text(low, 20)

    university_data_signals = [
        "student", "students", "subject", "subjects", "course", "courses", "gpa", "grade", "grades", "score", "advisor", "advisors",
        "pdf", "document", "file", "excel", "xlsx", "csv", "spreadsheet", "sheet", "dataset", "upload", "uploaded", "policy", "manual", "lesson", "material", "report", "writing",
        "database", "table", "schema",
        "cafeteria", "cafetaria", "canteen", "building", "room", "office", "library", "facility",
        "program", "admission", "tuition", "faculty",
        "นักศึกษา", "นักเรียน", "เกรด", "คะแนน", "อาจารย์", "เอกสาร", "ไฟล์", "ฐานข้อมูล", "โรงอาหาร", "อาคาร", "ห้อง"
    ]
    # If the first classifier got confused by words like "explain", keep admin in normal ChatGPT mode
    # unless the latest message has a real university/database signal.
    if decision.get("intent") in {"greeting", "out_of_scope", "document_qa"}:
        if not any(w in low for w in university_data_signals):
            return {"intent": "normal_chat", "goal": "normal chat", "data_sources": [], "operation": "unknown", "filters": [], "select": [], "sort": [], "limit": 20, "create_report_if_over": 20, "needs_schema_lookup": False, "missing_data_risk": False, "clarifying_question": None, "answer_style": "short", "confidence": 0.82}

    if any(w in low for w in ["schema", "database map", "database structure", "tables", "columns", "what data", "what can you access", "ฐานข้อมูล", "โครงสร้าง", "ตาราง"]):
        return {"intent": "database_overview", "goal": "show database structure", "data_sources": ["database_overview"], "operation": "schema", "filters": [], "select": [], "sort": [], "limit": 20, "create_report_if_over": 20, "needs_schema_lookup": True, "missing_data_risk": False, "clarifying_question": None, "answer_style": "summary", "confidence": 0.96}

    academic_terms = ["attendance", "absence", "absent", "enrolment", "enrollment", "term", "semester", "scholarship", "financial", "payment", "tuition balance", "support case", "risk level", "academic risk", "advising", "การเข้าเรียน", "ขาดเรียน", "ลงทะเบียน", "ภาคเรียน", "ทุน", "การเงิน", "ยอดค้าง", "ความเสี่ยง"]
    if any(w in low for w in academic_terms):
        return {"intent": "query_academic_records", "goal": "normalized academic records query", "data_sources": ["postgres_academic_records"], "operation": "aggregate" if any(w in low for w in ["summary", "summarize", "how many", "count", "จำนวน", "กี่"]) else "find", "filters": [], "select": [], "sort": [], "limit": limit, "create_report_if_over": 20, "needs_schema_lookup": False, "missing_data_risk": False, "clarifying_question": None, "answer_style": "summary", "confidence": 0.94}

    if any(w in low for w in ["subject", "subjects", "course", "courses", "classes", "class", "วิชา", "รายวิชา"]):
        if not _student_id(low) and not any(w in low for w in ["pdf", "document", "file", "excel", "uploaded", "เอกสาร", "ไฟล์"]):
            op = "count" if any(w in low for w in ["how many", "count", "number of", "total", "กี่", "จำนวน"]) else "find"
            return {"intent": "query_subjects", "goal": "university subject/course summary", "data_sources": ["mongodb_students"], "operation": op, "filters": [], "select": ["subject_grades"], "sort": [], "limit": 5000, "create_report_if_over": 20, "needs_schema_lookup": False, "missing_data_risk": False, "clarifying_question": None, "answer_style": "summary", "confidence": 0.98}

    if any(w in low for w in ["cafeteria", "cafetaria", "canteen", "library", "building", "room", "office", "facility", "facilities", "where is", "location", "map", "ห้อง", "อาคาร", "โรงอาหาร", "ห้องสมุด"]):
        keyword = "cafeteria" if any(w in low for w in ["cafeteria", "cafetaria", "canteen", "โรงอาหาร"]) else text
        return {"intent": "query_campus_info", "goal": f"search campus information for {keyword}", "data_sources": ["campus_info"], "operation": "search", "filters": [{"field": "keyword", "operator": "contains", "value": keyword}], "select": ["name", "location", "building", "floor", "opening_hours"], "sort": [], "limit": 5, "create_report_if_over": 20, "needs_schema_lookup": True, "missing_data_risk": True, "clarifying_question": None, "answer_style": "short", "confidence": 0.9}

    if any(w in low for w in ["pdf", "document", "file", "excel", "xlsx", "csv", "spreadsheet", "sheet", "dataset", "uploaded", "upload", "policy", "manual", "lesson", "material", "report", "writing", "worksheet", "notes", "เอกสาร", "ไฟล์", "อัปโหลด", "ตาราง", "ชีต", "เอ็กเซล"]):
        return {"intent": "query_documents", "goal": "search uploaded documents", "data_sources": ["postgres_documents"], "operation": "search", "filters": [{"field": "keyword", "operator": "contains", "value": friendly_clean_query(text)}], "select": [], "sort": [], "limit": 20, "create_report_if_over": 20, "needs_schema_lookup": False, "missing_data_risk": False, "clarifying_question": None, "answer_style": "summary", "confidence": 0.9}

    if _advisor_id(low) or any(w in low for w in ["advisor", "advisors", "teacher", "อาจารย์", "ที่ปรึกษา"]):
        filters = []
        aid = _advisor_id(low)
        if aid:
            filters.append({"field": "advisor_id", "operator": "eq", "value": aid})
        return {"intent": "query_advisors", "goal": "advisor data", "data_sources": ["mongodb_advisors"], "operation": "find", "filters": filters, "select": [], "sort": [{"field": "advisor_id", "direction": "asc"}], "limit": limit, "create_report_if_over": 20, "needs_schema_lookup": False, "missing_data_risk": False, "clarifying_question": None, "answer_style": "summary", "confidence": 0.9}

    # Student query fallback.
    filters: List[Dict[str, Any]] = []
    sort: List[Dict[str, str]] = []
    select = ["student_id", "name", "program", "gpa", "academic_status"]
    operation = "find"
    goal = "student lookup"
    sid = _student_id(low)
    if sid:
        filters.append({"field": "student_id", "operator": "eq", "value": sid})
        select = ADMIN_STUDENT_FIELDS if any(w in low for w in ["full", "profile", "everything", "all data", "detail"]) else select

    gpa_value = None
    gpa_patterns = [
        ("lte", r"(?:gpa|grade point).*?(?:less than or equal|lower than or equal|below or equal|<=)\s*(\d+(?:\.\d+)?)"),
        ("gte", r"(?:gpa|grade point).*?(?:greater than or equal|higher than or equal|above or equal|>=)\s*(\d+(?:\.\d+)?)"),
        ("lt", r"(?:gpa|grade point)?.*?(?:lower than|less than|below|under|<)\s*(\d+(?:\.\d+)?)"),
        ("gt", r"(?:gpa|grade point)?.*?(?:higher than|greater than|more than|above|over|>)\s*(\d+(?:\.\d+)?)"),
        ("eq", r"(?:gpa|grade point).*?(?:equal to|equals|exactly|=)\s*(\d+(?:\.\d+)?)"),
    ]
    if "gpa" in low or any(w in low for w in ["lower than", "less than", "below", "under", "higher than", "above", "over"]):
        for op, pattern in gpa_patterns:
            gpa_value = _number_after(pattern, low)
            if gpa_value is not None:
                filters.append({"field": "gpa", "operator": op, "value": gpa_value})
                operation = "filter"
                goal = f"students with GPA {op} {gpa_value}"
                break

    # Program filter.
    for program_word in ["business", "computer science", "engineering", "international relations", "marketing"]:
        if program_word in low:
            filters.append({"field": "program", "operator": "contains", "value": program_word})
            operation = "filter"
            break

    if "warning" in low:
        filters.append({"field": "academic_status", "operator": "contains", "value": "warning"})
        operation = "filter"
        
        # Semantic Rewrite AI hints
    if "student with the highest gpa" in low or '"direction": "desc"' in low and '"field": "gpa"' in low:
        return {
            "intent": "query_students",
            "goal": "student with the highest GPA",
            "data_sources": ["mongodb_students"],
            "operation": "rank",
            "filters": filters,
            "select": ["student_id", "name", "program", "gpa", "academic_status"],
            "sort": [{"field": "gpa", "direction": "desc"}],
            "limit": 1,
            "create_report_if_over": 20,
            "needs_schema_lookup": False,
            "missing_data_risk": False,
            "clarifying_question": None,
            "answer_style": "summary",
            "confidence": 0.96,
        }

    if "student with the lowest gpa" in low or '"direction": "asc"' in low and '"field": "gpa"' in low:
        return {
            "intent": "query_students",
            "goal": "student with the lowest GPA",
            "data_sources": ["mongodb_students"],
            "operation": "rank",
            "filters": filters,
            "select": ["student_id", "name", "program", "gpa", "academic_status"],
            "sort": [{"field": "gpa", "direction": "asc"}],
            "limit": 1,
            "create_report_if_over": 20,
            "needs_schema_lookup": False,
            "missing_data_risk": False,
            "clarifying_question": None,
            "answer_style": "summary",
            "confidence": 0.96,
        }

    # Ranking / improvement / lowest / highest.
    if any(w in low for w in ["need improve", "needs improve", "need to improve", "have to improve", "weak", "weakest", "support", "risk", "worst", "lowest", "bottom"]):
        sort = [{"field": "gpa", "direction": "asc"}]
        operation = "rank"
        select = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
        if not re.search(r"\b(list|show|give|top|bottom)\s+(?:me\s+)?\d+", low):
            limit = 1 if any(w in low for w in ["which one", "lowest", "worst", "weakest"]) else 10
        goal = "rank students who may need improvement"
    elif any(w in low for w in ["highest", "best", "top", "strongest"]):
        sort = [{"field": "gpa", "direction": "desc"}]
        operation = "rank"
        limit = _limit_from_text(low, 10)
        select = ["student_id", "name", "program", "gpa", "academic_status"]
        goal = "rank top students by GPA"

    if any(w in low for w in ["count", "how many", "จำนวน", "กี่คน"]):
        operation = "count"

    if any(w in low for w in ["all students", "all student", "student list", "list students", "show students", "นักศึกษาทั้งหมด"]):
        operation = "find"
        limit = max(limit, 20)

    if any(w in low for w in ["full", "profile", "everything", "detail", "details", "all fields", "private"]):
        select = ADMIN_STUDENT_FIELDS

    return {
        "intent": "query_students",
        "goal": goal,
        "data_sources": ["mongodb_students"],
        "operation": operation,
        "filters": filters,
        "select": select,
        "sort": sort,
        "limit": limit,
        "create_report_if_over": 20,
        "needs_schema_lookup": False,
        "missing_data_risk": False,
        "clarifying_question": None,
        "answer_style": "summary" if operation in {"rank", "filter", "count"} else "short",
        "confidence": 0.86,
    }


def _validate_filter(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    field = str(raw.get("field") or "").strip()
    op = str(raw.get("operator") or "eq").strip().lower()
    if field not in SAFE_FILTER_FIELDS or op not in SAFE_OPERATORS:
        return None
    value = raw.get("value")
    if field == "gpa":
        try:
            if op == "between" and isinstance(value, list) and len(value) == 2:
                value = [float(value[0]), float(value[1])]
            else:
                value = float(value)
        except Exception:
            return None
    if op == "in" and not isinstance(value, list):
        value = [value]
    return {"field": field, "operator": op, "value": value}


def _validate_plan(raw: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return fallback
    intent = str(raw.get("intent") or fallback.get("intent") or "query_students").strip()
    if intent not in SAFE_INTENTS:
        intent = fallback.get("intent", "query_students")
    filters = []
    for item in raw.get("filters") or []:
        clean = _validate_filter(item)
        if clean:
            filters.append(clean)
    select = raw.get("select") or []
    if not isinstance(select, list):
        select = []
    select = [str(x) for x in select if str(x) in ADMIN_STUDENT_FIELDS or str(x) in {"advisor_id", "department", "email", "phone", "filename", "summary", "location", "building", "opening_hours", "floor"}]
    sort = []
    for item in raw.get("sort") or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        direction = str(item.get("direction") or "asc").lower()
        if field in SAFE_SORT_FIELDS and direction in {"asc", "desc"}:
            sort.append({"field": field, "direction": direction})
    try:
        limit = int(raw.get("limit") or fallback.get("limit") or 20)
    except Exception:
        limit = 20
    limit = max(1, min(limit, 500))
    try:
        report_over = int(raw.get("create_report_if_over") or 20)
    except Exception:
        report_over = 20
    return {
        "intent": intent,
        "goal": str(raw.get("goal") or fallback.get("goal") or ""),
        "data_sources": raw.get("data_sources") if isinstance(raw.get("data_sources"), list) else fallback.get("data_sources", []),
        "operation": str(raw.get("operation") or fallback.get("operation") or "find"),
        "filters": filters,
        "select": select,
        "sort": sort,
        "limit": limit,
        "create_report_if_over": max(1, min(report_over, 500)),
        "needs_schema_lookup": bool(raw.get("needs_schema_lookup", False)),
        "missing_data_risk": bool(raw.get("missing_data_risk", False)),
        "clarifying_question": raw.get("clarifying_question"),
        "answer_style": str(raw.get("answer_style") or fallback.get("answer_style") or "summary"),
        "confidence": float(raw.get("confidence") or fallback.get("confidence") or 0.0),
    }


def create_universal_admin_plan(message: str, language: str, decision=None, chat_history=None) -> Dict[str, Any]:
    
    semantic = semantic_rewrite_for_planning(message)

    semantic_hint = ""
    if semantic:
        semantic_hint = f"""
Semantic rewrite for planning:
{json.dumps(semantic, ensure_ascii=False)}
"""

    fallback = _fallback_universal_plan(
        message + "\n\n" + semantic_hint,
        decision,
        chat_history
    )

    prompt = f"""
Language: {language}

Original admin message:
{message}

{semantic_hint}

First intent classifier result:
{json.dumps(decision or {}, ensure_ascii=False)}

Recent chat history for context only:
{json.dumps((chat_history or [])[-8:], ensure_ascii=False)[:3500]}

Create the safest flexible JSON query plan.
""".strip()

    try:
        raw = ai_generate_text(
            system_prompt=PLANNER_PROMPT,
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
        validated = _validate_plan(parsed, fallback)

        repaired = critique_and_repair_plan(message, validated)

        return _validate_plan(repaired, fallback)
    except Exception:
        return fallback


def _filters_to_mongo(filters: List[Dict[str, Any]]) -> Dict[str, Any]:
    op_map = {"lt": "$lt", "lte": "$lte", "gt": "$gt", "gte": "$gte", "ne": "$ne"}
    mongo: Dict[str, Any] = {}
    for f in filters:
        field = f.get("field")
        op = f.get("operator")
        value = f.get("value")
        if field == "keyword":
            continue
        if op == "eq":
            mongo[field] = value
        elif op in op_map:
            mongo.setdefault(field, {})[op_map[op]] = value
        elif op == "contains":
            mongo[field] = {"$regex": str(value), "$options": "i"}
        elif op == "in":
            mongo[field] = {"$in": value if isinstance(value, list) else [value]}
        elif op == "between" and isinstance(value, list) and len(value) == 2:
            mongo[field] = {"$gte": value[0], "$lte": value[1]}
    return mongo


def _keyword_from_filters(filters: List[Dict[str, Any]], message: str) -> str:
    for f in filters:
        if f.get("field") == "keyword":
            return str(f.get("value") or "")
    return friendly_clean_query(message)


def _preferred_source_type(message: str) -> str | None:
    low = (message or "").lower()
    if any(w in low for w in ["excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "dataset", "เอ็กเซล", "ชีต"]):
        return "excel"
    if any(w in low for w in ["pdf"]):
        return "pdf"
    return None


def build_mcp_plan_from_universal(universal: Dict[str, Any], message: str, language: str) -> Dict[str, Any]:
    from app.agent.entity_extractor import extract_entities
    
    intent = universal.get("intent")
    operation = universal.get("operation") or "find"
    answer_style = universal.get("answer_style") or "summary"
    limit = int(universal.get("limit") or 20)

    report_threshold = int(universal.get("create_report_if_over") or 20)
    # For open-ended list/filter questions, fetch enough rows to know whether a PDF report is needed.
    # Explicit "list me 10" / "lowest one" requests keep their small limit.
    database_fetch_limit = limit
    if intent == "query_students" and operation in {"find", "filter"} and limit == 20:
        database_fetch_limit = 5000

    common_meta = {
        "universal_query_plan": universal,
        "original_question": message,
        "answer_style": answer_style,
        "limit": database_fetch_limit,
        "display_limit": limit,
        "create_report_if_over": report_threshold,
    }
    
    entities = extract_entities(message)
    text = (message or "").lower()

    if entities["has_student_id"]:
        student_id = entities["student_ids"][0]

        academic_terms = ["attendance", "absence", "absent", "enrolment", "enrollment", "term", "semester", "scholarship", "financial", "payment", "tuition balance", "support case", "risk level", "academic risk", "การเข้าเรียน", "ขาดเรียน", "ลงทะเบียน", "ภาคเรียน", "ทุน", "การเงิน", "ยอดค้าง", "ความเสี่ยง"]
        if intent == "query_academic_records" or any(w in text for w in academic_terms):
            return {
                "tool_name": "postgres_university_tool",
                "arguments": {"query_type": "student_academic_profile", "student_id": student_id, "operation": "find", **common_meta},
                "role_prompt_name": "ADMIN_GRADE_ANALYST_PROMPT",
                "reason": "Student ID with normalized academic-record request.",
                "confidence": 0.98,
            }

        # Only use documents if the user clearly asks for PDF/file/document.
        asks_for_document = any(w in text for w in [
            "pdf",
            "document",
            "documents",
            "file",
            "files",
            "uploaded",
            "upload",
            "เอกสาร",
            "ไฟล์",
        ])

        if not asks_for_document:
            return {
                "tool_name": "mongodb_student_tool",
                "arguments": {
                    "student_id": student_id,
                    "operation": "read_students",
                    "requested_fields": [
                        "student_id",
                        "name",
                        "program",
                        "gpa",
                        "academic_status",
                        "subject_grades",
                        "email",
                        "phone",
                        "advisor_note",
                    ],
                    "answer_style": "profile",
                    **common_meta,
                },
                "role_prompt_name": "ADMIN_SUPER_AGENT_PROMPT",
                "reason": "Student ID detected, routing to student database.",
                "confidence": 0.98,
    }
            
    if intent == "normal_chat":
        return {
            "tool_name": "none",
            "arguments": {"reason": "normal_chat", **common_meta},
            "role_prompt_name": "ADMIN_NORMAL_CHATGPT_PROMPT",
            "reason": universal.get("goal") or "Normal ChatGPT mode.",
            "confidence": universal.get("confidence", 0.0),
        }

    if intent == "clarify":
        return {
            "tool_name": "none",
            "arguments": {"reason": "clarification_needed", "clarifying_question": universal.get("clarifying_question"), **common_meta},
            "role_prompt_name": "ADMIN_NORMAL_CHATGPT_PROMPT",
            "reason": universal.get("goal") or "Clarification needed.",
            "confidence": universal.get("confidence", 0.0),
        }

    if intent == "database_overview":
        return {
            "tool_name": "postgres_university_tool",
            "arguments": {"query_type": "database_map", "keyword": message, **common_meta},
            "role_prompt_name": "ADMIN_DATABASE_ARCHITECT_PROMPT",
            "reason": universal.get("goal") or "Database overview.",
            "confidence": universal.get("confidence", 0.0),
        }

    if intent == "query_academic_records":
        academic_text = text
        if any(w in academic_text for w in ["risk", "at risk", "academic risk", "ความเสี่ยง", "เสี่ยง"]):
            query_type = "academic_risk_summary"
        elif any(w in academic_text for w in ["course catalog", "course list", "courses", "subjects", "รายวิชา", "หลักสูตร"]):
            query_type = "course_catalog"
        else:
            query_type = "academic_overview"
        return {
            "tool_name": "postgres_university_tool",
            "arguments": {"query_type": query_type, "keyword": _keyword_from_filters(universal.get("filters") or [], message), "operation": operation, **common_meta},
            "role_prompt_name": "ADMIN_GRADE_ANALYST_PROMPT",
            "reason": universal.get("goal") or "Normalized academic records query.",
            "confidence": universal.get("confidence", 0.0),
        }

    if intent == "query_subjects":
        return {
            "tool_name": "mongodb_student_tool",
            "arguments": {"student_id": "ALL", "operation": "subject_summary", "requested_fields": ["student_id", "name", "subject_grades"], "limit": 5000, **common_meta},
            "role_prompt_name": "ADMIN_SUBJECT_AGENT_PROMPT",
            "reason": universal.get("goal") or "Subject/course summary.",
            "confidence": universal.get("confidence", 0.0),
        }

    if intent == "query_documents":
        keyword = _keyword_from_filters(universal.get("filters") or [], message)
        op = "list_documents" if document_list_request(message) else "document_search"
        return {
            "tool_name": "postgres_university_tool",
            "arguments": {"query_type": "all_documents", "operation": op, "keyword": keyword, "preferred_source_type": _preferred_source_type(message), **common_meta},
            "role_prompt_name": "ADMIN_DOCUMENT_AGENT_PROMPT",
            "reason": universal.get("goal") or "Document search.",
            "confidence": universal.get("confidence", 0.0),
        }

    if intent == "query_campus_info":
        keyword = _keyword_from_filters(universal.get("filters") or [], message)
        return {
            "tool_name": "postgres_university_tool",
            "arguments": {"query_type": "campus_info", "operation": "search", "keyword": keyword, "missing_data_risk": universal.get("missing_data_risk"), **common_meta},
            "role_prompt_name": "ADMIN_PROGRAM_AGENT_PROMPT",
            "reason": universal.get("goal") or "Campus information search.",
            "confidence": universal.get("confidence", 0.0),
        }

    if intent == "query_advisors":
        filters = universal.get("filters") or []
        advisor_id = "ALL"
        for f in filters:
            if f.get("field") == "advisor_id" and f.get("operator") == "eq":
                advisor_id = str(f.get("value") or "ALL").upper()
        return {
            "tool_name": "mongodb_advisor_tool",
            "arguments": {"advisor_id": advisor_id, "operation": "list_advisors" if advisor_id == "ALL" else "read_advisors", **common_meta},
            "role_prompt_name": "ADMIN_SUPER_AGENT_PROMPT",
            "reason": universal.get("goal") or "Advisor query.",
            "confidence": universal.get("confidence", 0.0),
        }        

    # Default: students.
    filters = universal.get("filters") or []
    mongo_filter = _filters_to_mongo(filters)
    sid = "ALL"
    if "student_id" in mongo_filter and isinstance(mongo_filter["student_id"], str):
        sid = mongo_filter.pop("student_id").upper()
    requested = [f for f in (universal.get("select") or []) if f in ADMIN_STUDENT_FIELDS]
    if not requested:
        requested = ["student_id", "name", "program", "gpa", "academic_status"]
    if operation in {"rank", "aggregate", "summarize"} and "subject_grades" not in requested:
        requested = list(dict.fromkeys(requested + ["subject_grades"]))
    return {
        "tool_name": "mongodb_student_tool",
        "arguments": {
            "student_id": sid,
            "operation": "count" if operation == "count" else "read_students",
            "requested_fields": requested,
            "query_filter": mongo_filter,
            "sort": universal.get("sort") or [],
            "limit": limit,
            "analysis_operation": operation,
            **common_meta,
        },
        "role_prompt_name": "ADMIN_GRADE_ANALYST_PROMPT" if operation in {"rank", "aggregate", "summarize", "filter"} else "ADMIN_SUPER_AGENT_PROMPT",
        "reason": universal.get("goal") or "Student query.",
        "confidence": universal.get("confidence", 0.0),
    }
