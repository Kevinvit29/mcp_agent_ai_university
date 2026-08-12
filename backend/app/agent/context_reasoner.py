"""Contextual Purpose Reasoner for Agent Orchestrator V3.

This is the first thinking step before any database/tool routing.  It asks the
configured LLM to understand the user's *purpose* from the latest message and
recent conversation context, then applies small backend safety guards so explicit
entities in the latest message always win over old context.

Important design rule:
- The AI may interpret purpose.
- The backend still validates schema, role permissions, and exact entities.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.agent.ai_client import ai_generate_text
from app.agent.natural_query import normalize_typos
from app.agent.schema_registry import get_schema_registry_for_role
from app.agent.purpose_contract import apply_contract_to_purpose, build_latest_message_contract
from app.agent.aggregate_query import parse_student_metric_query, parse_student_study_query, parse_student_statistic_query, parse_total_student_count_query
from app.agent.request_semantics import request_semantics
from app.agent.entity_extractor import extract_entities
from app.agent.academic_query import parse_academic_query


TARGET_DOMAINS = {
    "normal_chat",
    "students",
    "student_grades",
    "student_gpa",
    "subjects",
    "advisors",
    "documents",
    "programs",
    "campus_info",
    "database_map",
    "academic_records",
    "course_catalog",
    "clarify",
}

MESSAGE_TYPES = {"new_request", "follow_up", "correction", "normal_chat", "clarify"}
ANSWER_INTENTS = {"read", "count", "list", "search", "explain", "write", "compare", "summarize", "rank", "filter", "aggregate", "clarify"}

GRADE_WORDS = {"grade", "grades", "score", "scores", "mark", "marks", "เกรด", "คะแนน"}
GPA_WORDS = {"gpa", "เกรดเฉลี่ย"}
PROFILE_WORDS = {"profile", "information", "info", "record", "records", "detail", "details", "data", "full", "everything", "all data", "ข้อมูล", "โปรไฟล์", "รายละเอียด", "ประวัติ", "ทุกอย่าง", "ทั้งหมด"}
SUBJECT_WORDS = {"subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา"}
DOCUMENT_WORDS = {"pdf", "document", "documents", "file", "files", "excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "upload", "uploaded", "เอกสาร", "ไฟล์", "เอ็กเซล", "ชีต"}
ADVISOR_WORDS = {"advisor", "advisors", "teacher", "teachers", "อาจารย์", "ที่ปรึกษา"}
PROGRAM_WORDS = {"program", "programs", "major", "majors", "faculty", "department", "หลักสูตร", "สาขา", "คณะ"}
CAMPUS_WORDS = {"cafeteria", "canteen", "library", "building", "room", "office", "location", "map", "โรงอาหาร", "ห้องสมุด", "อาคาร", "ห้อง"}
DATABASE_WORDS = {"database", "schema", "collection", "field", "structure", "ฐานข้อมูล", "โครงสร้าง", "คอลัมน์"}
COUNT_WORDS = {"how many", "count", "number of", "total", "กี่", "จำนวน"}
LIST_WORDS = {"list", "show", "all", "what are", "which", "รายชื่อ", "แสดง", "ทั้งหมด"}
WRITING_WORDS = {"write", "draft", "rephrase", "rewrite", "translate", "email", "caption", "grammar", "เขียน", "แปล", "แก้ประโยค"}
CORRECTION_WORDS = {"i mean", "i meant", "actually", "no", "not", "wrong", "หมายถึง", "ไม่ใช่", "ผิด"}


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


def _safe_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            cleaned = match.group(0)
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _recent_context(history: Optional[List[Dict[str, Any]]], limit: int = 8) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in (history or [])[-limit:]:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role and content:
            rows.append({"role": role, "content": content[:900]})
    return rows


def _fallback_purpose(message: str, language: str, user_role: str, requester_student_id: Optional[str], requester_advisor_id: Optional[str], chat_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    text = _low(message)
    semantics = request_semantics(message)
    latest_entities = extract_entities(message)
    sids = latest_entities["student_ids"]
    aids = latest_entities["advisor_ids"]
    last_names = latest_entities["last_names"]
    answer_intent = "read"
    total_count_query = parse_total_student_count_query(message)
    metric_query = parse_student_metric_query(message)
    stat_query = parse_student_statistic_query(message)
    study_query = parse_student_study_query(message)
    academic_query = parse_academic_query(message)
    if total_count_query:
        answer_intent = "count"
    elif stat_query:
        answer_intent = "aggregate"
    elif metric_query:
        answer_intent = metric_query.get("intent") or "filter"
    elif _has_any(text, COUNT_WORDS):
        answer_intent = "count"
    elif _has_any(text, LIST_WORDS):
        answer_intent = "list"
    elif any(w in text for w in ["highest", "lowest", "top", "bottom", "best", "worst", "risk", "weak"]):
        answer_intent = "rank"

    target_domain = "normal_chat"
    should_use_database = False
    if semantics["is_realtime_request"]:
        target_domain = "clarify"
        answer_intent = "clarify"
    elif academic_query:
        target_domain = academic_query["domain"]
        answer_intent = academic_query["intent"]
        should_use_database = True
    elif sids or last_names:
        # Current-message data purpose priority: profile > GPA > grades.
        # A profile request may include subject_grades in the returned fields,
        # but the answer must remain a profile answer, not collapse into grades.
        if _has_any(text, PROFILE_WORDS):
            target_domain = "students"
        elif _has_any(text, GPA_WORDS):
            target_domain = "student_gpa"
        elif _has_any(text, GRADE_WORDS | SUBJECT_WORDS):
            target_domain = "student_grades"
        else:
            target_domain = "students"
        should_use_database = True
    elif aids or _has_any(text, ADVISOR_WORDS):
        target_domain = "advisors"
        should_use_database = True
    elif _has_any(text, DOCUMENT_WORDS):
        target_domain = "documents"
        should_use_database = True
    elif study_query:
        # Student/program/subject search must win before generic program/subject
        # routing. Example: "list students with highest grade program law" should
        # search students who match Law, not route to a generic programs table.
        target_domain = "students"
        answer_intent = study_query.get("intent") or "search"
        should_use_database = True
    elif _has_any(text, SUBJECT_WORDS):
        target_domain = "subjects"
        should_use_database = True
    elif _has_any(text, PROGRAM_WORDS):
        target_domain = "programs"
        should_use_database = True
    elif _has_any(text, CAMPUS_WORDS):
        target_domain = "campus_info"
        should_use_database = True
    elif semantics["is_schema_request"]:
        target_domain = "database_map"
        should_use_database = True
    elif metric_query or any(w in text for w in ["student", "students", "gpa", "นักศึกษา"]):
        target_domain = "students"
        should_use_database = True

    message_type = "normal_chat" if not should_use_database else "new_request"
    if not sids and not aids and any(w in text for w in CORRECTION_WORDS):
        message_type = "correction"

    if any(w in text for w in WRITING_WORDS) and not should_use_database:
        target_domain = "normal_chat"
        answer_intent = "write"
        message_type = "normal_chat"

    return {
        "source": "backend_fallback_context_reasoner",
        "version": "v3",
        "message_type": message_type,
        "user_purpose": "Backend fallback inferred the most likely purpose from the latest message.",
        "target_domain": target_domain,
        "answer_intent": answer_intent,
        "should_use_database": should_use_database,
        "explicit_entities": {
            "student_ids": sids,
            "advisor_ids": aids,
            "last_names": last_names,
            "subject_terms": ([study_query.get("study_term")] if isinstance(study_query, dict) and study_query.get("study_term") else []),
        },
        "data_needed": (["student_id", "name", "program", "gpa", "academic_status"] if metric_query else (study_query.get("requested_fields") if isinstance(study_query, dict) else [])),
        "total_count_query": total_count_query,
        "metric_query": metric_query,
        "stat_query": stat_query,
        "study_query": study_query,
        "ranking_query": study_query.get("ranking") if isinstance(study_query, dict) else None,
        "academic_query": academic_query,
        "not_purpose": [],
        "must_not_use_previous_entities": bool(sids or aids or last_names),
        "use_history": message_type in {"follow_up", "correction"},
        "confidence": 0.55 if should_use_database else 0.65,
        "reason": "Fallback when AI purpose reasoning was unavailable or low-confidence.",
    }


CONTEXT_REASONER_SYSTEM_PROMPT = """
You are the Contextual Purpose Reasoner for a university AI database agent.
You do NOT answer the user. You identify the user's real purpose before any tool is selected.

Rules:
1. Read the latest user message first. Recent history is only context, never a replacement for explicit entities in the latest message.
2. If the latest message contains S001/S002/S035/etc, those student IDs are the current target. Do not reuse older student IDs.
3. If the latest message is a correction like "I mean subject" or "ไม่ใช่นักศึกษา หมายถึงวิชา", mark message_type="correction" and infer the corrected purpose from history.
4. If the user asks a general ChatGPT-style question, writing task, translation, or explanation that does not need university data, use target_domain="normal_chat" and should_use_database=false.
5. Distinguish purpose carefully:
   - "how many subjects/courses" means count unique subjects from student subject_grades, NOT count students.
   - "S001 grade" means student_grades for S001.
   - "how many students have GPA lower 3.0" means filter students where gpa < 3.0 and count them.
   - "students that have grade lower than 3.0" means numeric GPA filter, not letter-grade subject_grades.
   - "give me the name of the student that study law" means search student program and subject_grades.subject for Law, then return verified names.
   - "uploaded files/PDF/Excel" means documents.
   - "schema/database/table" means database_map.
6. Return ONLY valid JSON. No markdown.

JSON schema:
{
  "message_type": "new_request | follow_up | correction | normal_chat | clarify",
  "user_purpose": "one clear sentence describing what the user wants",
  "target_domain": "normal_chat | students | student_grades | student_gpa | subjects | advisors | documents | programs | campus_info | database_map | academic_records | course_catalog | clarify",
  "answer_intent": "read | count | list | search | explain | write | compare | summarize | rank | filter | clarify",
  "should_use_database": true,
  "explicit_entities": {"student_ids": [], "advisor_ids": [], "file_terms": [], "subject_terms": []},
  "data_needed": ["specific data needed"],
  "not_purpose": ["what the user is NOT asking for"],
  "must_not_use_previous_entities": false,
  "use_history": false,
  "confidence": 0.0,
  "reason": "brief reason"
}
""".strip()


def analyze_user_purpose(
    *,
    message: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    role = (user_role or "student").lower()
    latest_entities = extract_entities(message)
    latest_sids = latest_entities["student_ids"]
    latest_aids = latest_entities["advisor_ids"]
    latest_last_names = latest_entities["last_names"]
    schema = get_schema_registry_for_role(role)
    prompt = {
        "user_role": role,
        "language": language,
        "requester_student_id": requester_student_id,
        "requester_advisor_id": requester_advisor_id,
        "latest_message": message,
        "latest_message_explicit_entities_backend_detected": {
            "student_ids": latest_sids,
            "advisor_ids": latest_aids,
            "last_names": latest_last_names,
        },
        "recent_history_for_context_only": _recent_context(chat_history),
        "schema_registry_summary": schema,
    }

    parsed: Optional[Dict[str, Any]] = None
    try:
        raw = ai_generate_text(
            system_prompt=CONTEXT_REASONER_SYSTEM_PROMPT,
            prompt=json.dumps(prompt, ensure_ascii=False)[:15000],
            json_mode=True,
            timeout_env="GEMINI_INTENT_TIMEOUT",
            default_timeout=60,
            temperature=0.0,
            max_output_tokens=2048,
        )
        parsed = _safe_json(raw or "")
    except Exception:
        parsed = None

    if not parsed:
        parsed = _fallback_purpose(message, language, role, requester_student_id, requester_advisor_id, chat_history)

    # V4: AI reads purpose first, then the latest-message contract constrains
    # exact entities and answer shape. This prevents context/history from turning
    # "S099 profile" into a grade-only answer or reusing an older student ID.
    parsed = apply_contract_to_purpose(message, parsed)
    total_count_query = parse_total_student_count_query(message)
    metric_query = parse_student_metric_query(message)
    stat_query = parse_student_statistic_query(message)
    study_query = parse_student_study_query(message)
    academic_query = parse_academic_query(message)
    if total_count_query:
        parsed["target_domain"] = "students"
        parsed["answer_intent"] = "count"
        parsed["should_use_database"] = True
        parsed["total_count_query"] = total_count_query
        parsed["data_needed"] = ["student_id"]
        answer_intent = "count"
    elif stat_query:
        parsed["target_domain"] = "students"
        parsed["answer_intent"] = "aggregate"
        parsed["should_use_database"] = True
        parsed["stat_query"] = stat_query
        parsed["data_needed"] = stat_query.get("requested_fields") or ["student_id", "name", "gpa"]
        answer_intent = "aggregate"
    elif metric_query:
        parsed["target_domain"] = "students"
        parsed["answer_intent"] = metric_query.get("intent") or "filter"
        parsed["should_use_database"] = True
        parsed["metric_query"] = metric_query
        parsed["data_needed"] = ["student_id", "name", "program", "gpa", "academic_status"]
        parsed["not_purpose"] = list(set((parsed.get("not_purpose") or []) + ["do not answer from subject letter grades only", "do not return all students without applying the GPA filter"]))

    if study_query:
        parsed["target_domain"] = "students"
        parsed["answer_intent"] = study_query.get("intent") or "search"
        parsed["should_use_database"] = True
        parsed["study_query"] = study_query
        parsed["data_needed"] = study_query.get("requested_fields") or ["student_id", "name", "program", "subject_grades"]
        parsed["not_purpose"] = list(set((parsed.get("not_purpose") or []) + ["do not return all students without applying the study/program/subject term search", "do not infer a student name unless it appears in verified matches"]))

    if academic_query:
        parsed["target_domain"] = academic_query["domain"]
        parsed["answer_intent"] = academic_query["intent"]
        parsed["should_use_database"] = True
        parsed["academic_query"] = academic_query
        parsed["data_needed"] = academic_query["requested_sections"]
        parsed["not_purpose"] = list(set((parsed.get("not_purpose") or []) + ["do not answer normalized academic operations from the MongoDB master profile"]))

    # Sanitize AI output into safe, known values.
    target_domain = str(parsed.get("target_domain") or "normal_chat").strip()
    if target_domain not in TARGET_DOMAINS:
        target_domain = "normal_chat"
    message_type = str(parsed.get("message_type") or "new_request").strip()
    if message_type not in MESSAGE_TYPES:
        message_type = "new_request"
    answer_intent = str(parsed.get("answer_intent") or "read").strip()
    if answer_intent not in ANSWER_INTENTS:
        answer_intent = "read"

    entities = parsed.get("explicit_entities") if isinstance(parsed.get("explicit_entities"), dict) else {}
    entity_student_ids = []
    for sid in entities.get("student_ids") or []:
        sid = str(sid).upper().strip()
        if re.fullmatch(r"S\d{3,6}", sid) and sid not in entity_student_ids:
            entity_student_ids.append(sid)
    entity_advisor_ids = []
    for aid in entities.get("advisor_ids") or []:
        aid = str(aid).upper().strip()
        if re.fullmatch(r"A\d{3,6}", aid) and aid not in entity_advisor_ids:
            entity_advisor_ids.append(aid)
    entity_last_names = []
    contract = parsed.get("latest_message_contract") if isinstance(parsed.get("latest_message_contract"), dict) else {}
    for last_name in (contract.get("last_names") or entities.get("last_names") or latest_last_names):
        last_name = str(last_name).lower().strip()
        if last_name and last_name not in entity_last_names:
            entity_last_names.append(last_name)

    # Hard safety guard: entities in the latest message always override AI/history.
    if latest_sids:
        entity_student_ids = latest_sids
        message_type = "new_request"
        parsed["must_not_use_previous_entities"] = True
        text = _low(message)
        if academic_query:
            target_domain = academic_query["domain"]
        elif _has_any(text, PROFILE_WORDS):
            target_domain = "students"
        elif _has_any(text, GPA_WORDS):
            target_domain = "student_gpa"
        elif _has_any(text, GRADE_WORDS | SUBJECT_WORDS):
            target_domain = "student_grades"
        elif target_domain not in {"students", "student_grades", "student_gpa"}:
            target_domain = "students"
        parsed["should_use_database"] = True
    if latest_aids:
        entity_advisor_ids = latest_aids
        message_type = "new_request"
        parsed["must_not_use_previous_entities"] = True
        target_domain = "advisors"
        parsed["should_use_database"] = True
    if latest_last_names:
        entity_last_names = latest_last_names
        message_type = "new_request"
        parsed["must_not_use_previous_entities"] = True
        parsed["use_history"] = False
        target_domain = "students"
        parsed["should_use_database"] = True

    semantics = request_semantics(message)
    if semantics["is_realtime_request"]:
        target_domain = "clarify"
        answer_intent = "clarify"
        message_type = "clarify"
        parsed["should_use_database"] = False
        parsed["use_history"] = False

    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    should_use_database = bool(parsed.get("should_use_database"))
    if target_domain not in {"normal_chat", "clarify"}:
        should_use_database = True
    if target_domain == "normal_chat":
        should_use_database = False

    result = {
        "source": parsed.get("source") or "ai_context_reasoner",
        "version": "v3",
        "message_type": message_type,
        "user_purpose": str(parsed.get("user_purpose") or ""),
        "target_domain": target_domain,
        "answer_intent": answer_intent,
        "should_use_database": should_use_database,
        "explicit_entities": {
            "student_ids": entity_student_ids,
            "advisor_ids": entity_advisor_ids,
            "last_names": entity_last_names,
            "file_terms": (entities.get("file_terms") or [])[:10] if isinstance(entities.get("file_terms"), list) else [],
            "subject_terms": (entities.get("subject_terms") or [])[:10] if isinstance(entities.get("subject_terms"), list) else [],
        },
        "data_needed": parsed.get("data_needed") if isinstance(parsed.get("data_needed"), list) else [],
        "total_count_query": parsed.get("total_count_query") if isinstance(parsed.get("total_count_query"), dict) else None,
        "metric_query": parsed.get("metric_query") if isinstance(parsed.get("metric_query"), dict) else None,
        "stat_query": parsed.get("stat_query") if isinstance(parsed.get("stat_query"), dict) else None,
        "study_query": parsed.get("study_query") if isinstance(parsed.get("study_query"), dict) else None,
        "ranking_query": (parsed.get("study_query") or {}).get("ranking") if isinstance(parsed.get("study_query"), dict) else None,
        "not_purpose": parsed.get("not_purpose") if isinstance(parsed.get("not_purpose"), list) else [],
        "requested_answer_style": str(parsed.get("requested_answer_style") or (build_latest_message_contract(message).get("answer_style"))),
        "latest_message_contract": parsed.get("latest_message_contract") if isinstance(parsed.get("latest_message_contract"), dict) else build_latest_message_contract(message),
        "must_not_use_previous_entities": bool(parsed.get("must_not_use_previous_entities") or latest_sids or latest_aids or latest_last_names),
        "use_history": bool(parsed.get("use_history")),
        "confidence": confidence if confidence else (0.86 if should_use_database else 0.75),
        "reason": str(parsed.get("reason") or "Contextual AI purpose reasoning completed."),
    }
    return result
