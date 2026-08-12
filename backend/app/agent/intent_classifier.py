import json
import os
import re
from typing import Any, Dict, List, Optional


from app.agent.ai_client import ai_generate_text
from app.agent.neural_intent_trainer import predict_neural_intent
from app.agent.natural_query import normalize_typos, looks_like_self_data_request, looks_like_document_request, document_list_request, friendly_clean_query, is_greeting

INTENT_SYSTEM_PROMPT = """
You are the INTENT AGENT for a university AI system.
You do not answer the user. You only classify the latest message and choose the needed data source.

Important architecture:
- Permission is controlled by backend roles and tools.
- Your task is semantic routing, not final answering.
- Understand English, Thai, typos, split words, short follow-ups, and informal messages. Correct obvious typos for routing only, e.g. "re prot" or "repot" means "report", "writting" means "writing".
- Use recent chat history to interpret follow-ups like "everyone", "แล้วอันนี้ล่ะ", "that one", "what about all", or "I mean everyone".

Roles:
- admin: may access all student data, advisor data, program data, admin/global uploaded documents, and advisor subject documents. For non-university questions, admin should behave like a normal ChatGPT-style assistant without using database tools.
- advisor: may access only advisor-visible student names and subject grades for subjects they teach. Advisors may also search their own uploaded subject PDF/Excel files.
- student: may access only their own student data. Students may also search advisor-uploaded PDF/Excel files only for subjects they are enrolled in with that advisor.

Choose exactly ONE intent:
- greeting: only greeting or small talk with no data request.
- student_data: student name, GPA, grade, subject, score, what a student learns, all students, count students, grade summaries, class/course data, contact/profile/student status.
- advisor_data: advisor profile or advisor information.
- document_qa: uploaded PDF files, Excel files, spreadsheets, CSV files, documents, announcements, policies, rules, requirements, forms, manuals, files, lesson materials, subject materials, summaries, document names, content from a stored PDF/Excel/table, or questions that refer to advisor/admin uploaded PDF/Excel knowledge. Also choose this for academic content questions that may refer to a PDF title/content even with typos, such as "what is writing re prot" => Writing a report. For student/advisor roles, this means advisor_subject_documents, not admin_documents.
- program_data: admissions, tuition, program requirements, faculties, curriculum, application rules not specifically in uploaded PDF/Excel files.
- out_of_scope: does not need a university database/tool. For admin this is NOT a refusal; it routes to normal ChatGPT-style answering. Examples: writing, grammar correction, coding, math, translation, explanation, brainstorming, planning, weather, football, stock price, general news.

Operations:
- normal: normal lookup.
- count: count students or records.
- grade_summary: summarize/count grades across one or more students.
- list_names: list student names.
- list_documents: list uploaded/stored document names.
- document_search: answer from uploaded/stored documents. For student/advisor roles, search advisor-owned subject PDF/Excel files only.

Requested fields for student_data:
Use only fields needed by the question.
Allowed field names: student_id, name, program, gpa, academic_status, subject_grades, email, phone, national_id, passport_id, address, advisor_note.
For admin, if the user asks broadly for full profile/everything, include all fields.
For advisor, requested_fields should usually be student_id, name, subject_grades only.
For student, requested_fields should be their own allowed fields only.

Answer style:
- short: short factual question.
- medium: summary/list/count/comparison.
- detailed: explain/report/table/full details.

Return ONLY valid JSON. No markdown. No explanation.
Schema:
{
  "intent": "greeting | student_data | advisor_data | document_qa | program_data | out_of_scope",
  "search_query": "clean search query in the user's language",
  "target_student_id": "S001 or ALL or null",
  "requested_fields": ["field names"],
  "operation": "normal | count | grade_summary | list_names | list_documents | document_search",
  "grade_target": "A or A- or B+ or null",
  "answer_style": "short | medium | detailed",
  "confidence": 0.0
}
""".strip()


def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


def _history_text(chat_history: Optional[List[Dict[str, Any]]], max_items: int = 8) -> str:
    if not chat_history:
        return ""
    recent = chat_history[-max_items:]
    return "\n".join(f"{m.get('role', 'user')}: {str(m.get('content', ''))[:700]}" for m in recent)


def _student_id(text: str) -> Optional[str]:
    m = re.search(r"\bs\d{3,6}\b", text or "", flags=re.I)
    return m.group(0).upper() if m else None


def _advisor_id(text: str) -> Optional[str]:
    m = re.search(r"\ba\d{3}\b", text or "", flags=re.I)
    return m.group(0).upper() if m else None


def _grade_target(text: str) -> Optional[str]:
    text = text or ""
    m = re.search(r"(?:grade\s*)?\b([ABCDF][+-]?)\b", text, flags=re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"เกรด\s*([ABCDF][+-]?)", text, flags=re.I)
    return m.group(1).upper() if m else None




TYPO_DOCUMENT_PHRASES = {
    "wht": "what",
    "wat": "what",
    "gade": "grade",
    "grde": "grade",
    "gard": "grade",
    "graed": "grade",
    "subjet": "subject",
    "subjct": "subject",
    "porfile": "profile",
    "re prot": "report",
    "re port": "report",
    "repot": "report",
    "reprot": "report",
    "rport": "report",
    "repo rt": "report",
    "writting": "writing",
    "writng": "writing",
    "wrting": "writing",
    "pdf beside": "uploaded pdfs",
    "pdf besides": "uploaded pdfs",
}

DOCUMENT_TOPIC_SIGNALS = [
    "pdf", "document", "file", "policy", "rule", "announcement", "manual", "form", "upload", "uploads", "uploaded", "stored",
    "summary", "summarize", "explain", "lesson", "table", "conclusion", "lecture", "homework", "assignment", "material", "materials",
    "syllabus", "report", "writing", "writting", "writng", "repot", "reprot", "re port", "re prot",
    "article", "essay", "chapter", "topic", "content", "notes", "slide", "slides", "worksheet",
    "เอกสาร", "ไฟล์", "ประกาศ", "นโยบาย", "ระเบียบ", "หลักเกณฑ์", "ตำรา", "หนังสือ", "ทุน",
    "จำหน่าย", "ขาย", "สรุป", "อัปโหลด", "บทเรียน", "การบ้าน", "ไฟล์เรียน", "เนื้อหาเรียน", "รายงาน", "เขียน"
]

CONTENT_QUESTION_STARTERS = (
    "what is", "what's", "explain", "explain about", "tell me about", "summarize", "summary of",
    "meaning of", "define", "how to", "what are", "describe", "คืออะไร", "อธิบาย", "สรุป", "หมายถึง", "เกี่ยวกับ"
)


def _normalize_typos_for_routing(text: str) -> str:
    # Keep this deterministic and conservative. It only helps routing/search; it is not final answering.
    return normalize_typos(text)


def _looks_like_document_question(text: str, combined: str) -> bool:
    t = _normalize_typos_for_routing(text)
    c = _normalize_typos_for_routing(combined)
    if any(signal in c for signal in DOCUMENT_TOPIC_SIGNALS):
        return True
    # Follow-up after a document answer: user may say "what is writing re prot" or "explain this" without saying PDF.
    if any(word in c for word in ["uploaded document", "stored document", "filename", "เอกสารที่อัปโหลด", "ไฟล์"]):
        if any(t.startswith(prefix) for prefix in CONTENT_QUESTION_STARTERS):
            return True
    # Academic content questions in this university/doc chat should search the allowed PDFs before refusing.
    academic_words = ["report", "writing", "essay", "article", "assignment", "homework", "lesson", "chapter", "notes", "รายงาน", "เขียน", "บทเรียน"]
    return any(w in t for w in academic_words) and any(t.startswith(prefix) for prefix in CONTENT_QUESTION_STARTERS)


def _fallback_classify(message: str, role: str, language: str, chat_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Safety fallback when the AI provider is unavailable or uncertain. Broad enough to avoid false refusal."""
    text = (message or "").lower().strip()
    hist = _history_text(chat_history).lower()
    combined = (hist + "\n" + text).strip()
    sid = _student_id(message)
    normalized_for_user = normalize_typos(message)

    if is_greeting(message):
        return {"intent": "greeting", "search_query": normalized_for_user or message, "target_student_id": None, "requested_fields": [], "operation": "normal", "grade_target": None, "answer_style": "short", "confidence": 0.92}

    # Strong student-self guard: typos like "wht is my gade" must be grades, not PDFs.
    if role == "student" and looks_like_self_data_request(message):
        fields = ["student_id", "name", "program", "academic_status", "subject_grades"]
        if "gpa" in normalized_for_user or "เกรดเฉลี่ย" in normalized_for_user:
            fields = ["student_id", "name", "gpa"]
        if any(w in normalized_for_user for w in ["profile", "information", "info", "record", "detail", "data", "email", "status", "program", "ข้อมูล", "โปรไฟล์"]):
            if role == "admin":
                fields = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email", "phone", "national_id", "passport_id", "address", "advisor_note"]
            else:
                fields = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email"]
        return {"intent": "student_data", "search_query": normalized_for_user or message, "target_student_id": None, "requested_fields": fields, "operation": "normal", "grade_target": _grade_target(normalized_for_user), "answer_style": "short", "confidence": 0.95}

    if any(w in text for w in ["weather", "stock", "bitcoin", "football", "อากาศ", "หุ้น", "ผลบอล"]):
        return {"intent": "out_of_scope", "search_query": normalized_for_user or message, "target_student_id": None, "requested_fields": [], "operation": "normal", "grade_target": None, "answer_style": "short", "confidence": 0.8}

    if _advisor_id(message) or any(w in normalized_for_user for w in ["advisor", "advisors", "teacher", "teachers", "อาจารย์", "ที่ปรึกษา"]):
        return {"intent": "advisor_data", "search_query": normalized_for_user or message, "target_student_id": None, "requested_fields": [], "operation": "list_names" if any(w in normalized_for_user for w in ["all", "list", "ทุก", "ทั้งหมด", "รายชื่อ"]) else "normal", "grade_target": None, "answer_style": "medium", "confidence": 0.9}

    # Explicit student/profile/grade requests must win before document routing.
    # Without this, the word "file" inside "profile" can wrongly send admin/student
    # profile questions to PDF search.
    explicit_student_words = ["student", "students", "profile", "information", "info", "record", "grade", "grades", "gpa", "score", "scores", "subject", "subjects", "name", "names", "ข้อมูล", "โปรไฟล์", "เกรด", "คะแนน", "วิชา", "ชื่อ"]
    explicit_doc_words = ["pdf", "document", "file", "upload", "uploaded", "uploads", "เอกสาร", "ไฟล์", "อัปโหลด"]
    if sid or (any(w in normalized_for_user for w in explicit_student_words) and not any(w in normalized_for_user for w in explicit_doc_words)):
        target = sid or ("ALL" if role == "admin" and any(w in normalized_for_user for w in ["all", "every", "everyone", "students", "ทุกคน", "ทั้งหมด"]) else None)
        fields = ["student_id", "name"]
        op = "normal"
        if any(w in normalized_for_user for w in ["profile", "information", "info", "record", "detail", "details", "data", "ข้อมูล", "โปรไฟล์"]):
            fields = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email"]
            if role == "admin":
                fields += ["phone", "national_id", "passport_id", "address", "advisor_note"]
        elif "gpa" in normalized_for_user or "เกรดเฉลี่ย" in normalized_for_user:
            fields = ["student_id", "name", "gpa"]
        elif any(w in normalized_for_user for w in ["grade", "grades", "score", "scores", "subject", "subjects", "เกรด", "คะแนน", "วิชา"]):
            fields = ["student_id", "name", "program", "academic_status", "subject_grades"]
        if any(w in normalized_for_user for w in ["count", "how many", "summary", "กี่", "สรุป"]) and any(w in normalized_for_user for w in ["grade", "grades", "score", "scores", "เกรด", "คะแนน"]):
            op = "grade_summary"
            target = target or (None if role == "student" else "ALL")
            fields = ["student_id", "name", "subject_grades"]
        elif any(w in normalized_for_user for w in ["list", "names", "ชื่อ", "รายชื่อ"]) and target == "ALL":
            op = "list_names"
            fields = ["student_id", "name"]
        return {"intent": "student_data", "search_query": normalized_for_user or message, "target_student_id": target, "requested_fields": fields, "operation": op, "grade_target": _grade_target(normalized_for_user), "answer_style": "medium" if op != "normal" else "short", "confidence": 0.97}

    if looks_like_document_request(message, hist):
        wants_list = document_list_request(message)
        return {
            "intent": "document_qa",
            "search_query": friendly_clean_query(message),
            "target_student_id": None,
            "requested_fields": [],
            "operation": "list_documents" if wants_list else "document_search",
            "grade_target": None,
            "answer_style": "detailed" if any(w in normalized_for_user for w in ["explain", "summarize", "summary", "detail", "อธิบาย", "สรุป"]) else "medium",
            "confidence": 0.86,
        }

    # Document fallback: typo-tolerant and context-aware. This prevents false "out of scope"
    # for questions like "what is writing re prot" when the PDF is Writing_a_report.pdf.
    normalized_text = _normalize_typos_for_routing(text)
    normalized_combined = _normalize_typos_for_routing(combined)
    # Short follow-up after a document/PDF/table conversation should stay in document mode.
    if len(normalized_text.split()) <= 5 and any(w in normalized_combined for w in ["pdf", "document", "file", "uploaded", "stored", "table", "filename", "เอกสาร", "ไฟล์"]):
        if normalized_text in {"really", "why", "then", "again", "more", "detail", "details", "explain", "this", "that", "it"} or any(w in normalized_text for w in ["beside", "upload", "uploads", "subject"]):
            return {
                "intent": "document_qa",
                "search_query": _normalize_typos_for_routing(message),
                "target_student_id": None,
                "requested_fields": [],
                "operation": "list_documents" if any(w in normalized_text for w in ["beside", "upload", "uploads", "available", "subject"]) else "document_search",
                "grade_target": None,
                "answer_style": "medium",
                "confidence": 0.74,
            }

    if _looks_like_document_question(text, combined):
        wants_list = any(w in normalized_text for w in [
            "list", "name", "names", "already", "upload", "uploads", "uploaded", "stored", "available", "beside", "besides", "all pdf", "subject upload", "subject uploads",
            "รายชื่อ", "ชื่อไฟล์", "มีอะไร", "เอกสารอะไร", "ไฟล์อะไร"
        ])
        return {
            "intent": "document_qa",
            "search_query": _normalize_typos_for_routing(message),
            "target_student_id": None,
            "requested_fields": [],
            "operation": "list_documents" if wants_list else "document_search",
            "grade_target": None,
            "answer_style": "detailed" if any(w in normalized_text for w in ["explain", "summarize", "summary", "อธิบาย", "สรุป"]) else "medium",
            "confidence": 0.72,
        }

    grade_words = ["grade", "grades", "score", "scores", "gpa", "subject", "subjects", "learn", "study", "course", "class", "เกรด", "คะแนน", "วิชา", "เรียน"]
    profile_words = [
        "profile", "information", "info", "record", "detail", "details", "status", "email", "id",
        "my data", "my record", "my profile", "own data", "ข้อมูล", "โปรไฟล์", "ข้อมูลส่วนตัว", "สถานะ", "อีเมล"
    ]
    self_words = ["my", "me", "mine", "own", "ฉัน", "ผม", "เรา", "ของฉัน", "ของผม", "ตัวเอง"]
    all_words = ["all", "every", "everyone", "everybody", "everyonew", "ทุกคน", "ทั้งหมด"]
    name_words = ["name", "names", "list", "ชื่อ", "รายชื่อ"]
    student_signals = grade_words + profile_words + name_words + ["student", "students", "นักเรียน", "นักศึกษา"]
    self_student_request = role == "student" and any(w in text for w in self_words) and any(w in combined for w in student_signals)
    if sid or self_student_request or any(w in combined for w in student_signals):
        op = "normal"
        fields = ["student_id", "name"]
        target = sid or None
        if role == "student" and not sid and any(w in text for w in self_words):
            target = None
        if any(w in text for w in all_words) or (not sid and role == "admin" and any(w in text for w in ["students", "นักเรียน", "นักศึกษา"])):
            target = "ALL"
        if any(w in text for w in ["how many", "count", "summary", "สรุป", "กี่"]) and any(w in combined for w in grade_words):
            op = "grade_summary"
            target = target or (None if role == "student" else "ALL")
            fields = ["student_id", "name", "subject_grades"]
        elif any(w in text for w in name_words) and (target == "ALL" or any(w in text for w in all_words)):
            op = "list_names"
            target = "ALL"
        elif any(w in combined for w in ["profile", "information", "info", "record", "detail", "details", "ข้อมูล", "โปรไฟล์", "ข้อมูลส่วนตัว"]):
            if role == "admin":
                fields = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email", "phone", "national_id", "passport_id", "address", "advisor_note"]
            else:
                fields = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email"]
        elif "gpa" in combined or "เกรดเฉลี่ย" in combined:
            fields = ["student_id", "name", "gpa"]
        elif any(w in combined for w in grade_words):
            fields = ["student_id", "name", "program", "academic_status", "subject_grades"]
        return {"intent": "student_data", "search_query": message, "target_student_id": target, "requested_fields": fields, "operation": op, "grade_target": _grade_target(message), "answer_style": "medium" if op != "normal" else "short", "confidence": 0.95 if sid else (0.9 if self_student_request else 0.75)}

    program_signals = ["admission", "tuition", "program", "faculty", "requirement", "apply", "หลักสูตร", "ค่าเทอม", "สมัคร", "คณะ"]
    if any(w in combined for w in program_signals):
        return {"intent": "program_data", "search_query": message, "target_student_id": None, "requested_fields": [], "operation": "normal", "grade_target": None, "answer_style": "medium", "confidence": 0.6}

    return {"intent": "out_of_scope", "search_query": message, "target_student_id": None, "requested_fields": [], "operation": "normal", "grade_target": None, "answer_style": "short", "confidence": 0.5}


def _validate_decision(decision: Dict[str, Any], message: str, role: str, language: str, chat_history: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    fallback = _fallback_classify(message, role, language, chat_history)
    if not isinstance(decision, dict):
        return fallback
    intent = decision.get("intent")
    allowed = {"greeting", "student_data", "advisor_data", "document_qa", "program_data", "out_of_scope"}
    if intent not in allowed:
        return fallback
    decision.setdefault("search_query", message)
    decision.setdefault("target_student_id", fallback.get("target_student_id"))
    decision.setdefault("requested_fields", fallback.get("requested_fields", []))
    decision.setdefault("operation", fallback.get("operation", "normal"))
    decision.setdefault("grade_target", fallback.get("grade_target"))
    decision.setdefault("answer_style", fallback.get("answer_style", "short"))
    decision.setdefault("confidence", 0.0)
    # Never let low-confidence out-of-scope override obvious document/student fallback.
    try:
        conf = float(decision.get("confidence", 0.0) or 0.0)
    except Exception:
        conf = 0.0
    # Deterministic safety override: explicit student/profile/grade requests must route to
    # student data. This is especially important for admin, because admin is allowed to
    # read student records and the LLM classifier can sometimes over-refuse or choose
    # program_data by mistake. The MCP policy still enforces the role rules.
    if fallback.get("intent") == "student_data" and fallback.get("confidence", 0) >= 0.75:
        if _student_id(message) or any(w in normalize_typos(message) for w in ["student", "students", "profile", "grade", "grades", "gpa", "score", "scores", "subject", "subjects", "name", "ข้อมูล", "โปรไฟล์", "เกรด"]):
            return fallback

    # Deterministic safety override: obvious in-scope student/profile/grade requests
    # must not be refused just because the LLM classifier was too conservative.
    if fallback.get("intent") in {"student_data", "document_qa"} and fallback.get("confidence", 0) >= 0.85:
        return fallback
    if intent == "out_of_scope" and fallback.get("intent") != "out_of_scope":
        # Never refuse obvious student self-data or uploaded-document questions, even if the LLM
        # classifier was overconfident. The downstream tool still enforces permissions.
        if fallback.get("intent") in {"student_data", "document_qa"}:
            return fallback
        if conf < 0.8:
            return fallback
    return decision


def _apply_neural_router_hint(
    decision: Dict[str, Any],
    message: str,
    role: str,
    language: str,
    chat_history: Optional[List[Dict[str, Any]]],
    *,
    fallback_mode: bool = False,
) -> Dict[str, Any]:
    """Attach the persisted neural prediction and use it only as a guarded fallback.

    The neural model has no permission to bypass deterministic student/document
    routing or PDPA policy. It can rescue a genuinely unclear out-of-scope fallback
    when the cloud intent provider is unavailable.
    """
    result = dict(decision or {})
    try:
        hint = predict_neural_intent(message)
    except Exception:
        return result
    if not hint.get("available"):
        return result
    result["neural_router_hint"] = hint
    predicted = str(hint.get("intent") or "")
    confidence = float(hint.get("confidence") or 0.0)
    if not fallback_mode or confidence < 0.78 or predicted not in ALLOWED_INTENTS:
        return result
    # Explicit deterministic rules always win. The neural model only fills a gap.
    baseline = _fallback_classify(message, role, language, chat_history)
    if baseline.get("intent") in {"student_data", "document_qa"} and float(baseline.get("confidence") or 0) >= 0.85:
        return result
    if str(result.get("intent") or "") != "out_of_scope" or predicted == "out_of_scope":
        return result

    result["intent"] = predicted
    result["confidence"] = max(float(result.get("confidence") or 0), round(confidence * 0.82, 4))
    result["neural_router_used"] = True
    result.setdefault("search_query", normalize_typos(message) or message)
    if predicted == "student_data":
        result.update({
            "target_student_id": _student_id(message),
            "requested_fields": ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"],
            "operation": "normal",
            "answer_style": "medium",
        })
    elif predicted == "advisor_data":
        result.update({"requested_fields": [], "operation": "normal", "answer_style": "medium"})
    elif predicted == "document_qa":
        result.update({"requested_fields": [], "operation": "document_search", "answer_style": "medium"})
    elif predicted == "program_data":
        result.update({"requested_fields": [], "operation": "normal", "answer_style": "medium"})
    elif predicted == "greeting":
        result.update({"requested_fields": [], "operation": "normal", "answer_style": "short"})
    return result


def classify_intent(message: str, role: str, language: str, chat_history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    prompt = f"""
Current role: {role}
Language selected by user: {language}

Admin routing rule: if role is admin and the question is a normal ChatGPT task (writing, coding, math, translation, advice, explanation, planning, general knowledge) and does not ask for university/private/database/PDF data, classify as out_of_scope so the backend answers with the configured AI provider directly.

Recent chat history:
{_history_text(chat_history)}

Latest user message:
{message}

Classify the latest message. For follow-up messages, use the history. Return JSON only.
""".strip()
    try:
        content = ai_generate_text(
            system_prompt=INTENT_SYSTEM_PROMPT,
            prompt=prompt,
            json_mode=True,
            timeout_env="GEMINI_INTENT_TIMEOUT",
            default_timeout=60,
            temperature=0.0,
            max_output_tokens=2048,
        )
        if not content:
            fallback = _fallback_classify(message, role, language, chat_history)
            return _apply_neural_router_hint(fallback, message, role, language, chat_history, fallback_mode=True)
        parsed = json.loads(_clean_json_text(content))
        validated = _validate_decision(parsed, message, role, language, chat_history)
        return _apply_neural_router_hint(validated, message, role, language, chat_history, fallback_mode=False)
    except Exception:
        fallback = _fallback_classify(message, role, language, chat_history)
        return _apply_neural_router_hint(fallback, message, role, language, chat_history, fallback_mode=True)
