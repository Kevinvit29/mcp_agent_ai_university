import json
import os
import re
from typing import Any, Dict, List, Optional

from app.agent.ai_client import ai_generate_text
from app.agent.natural_query import normalize_typos, is_greeting, looks_like_self_data_request, document_list_request

BASE_SYSTEM_RULES = """
You are a natural AI assistant connected to a university database.
Your behavior depends on the role and the selected task.

CORE BEHAVIOR:
- Answer naturally, briefly, and directly like ChatGPT: friendly, clear, and smooth.
- The user may have typos or split words. Silently infer obvious corrections from allowed_data, filenames, subjects, and chat history before refusing. Example: "wht is my gade" means "what is my grade" and "writing re prot" likely means "Writing_a_report.pdf" or "writing report".
- Never show JSON, Python dicts, database rows, tool names, planner names, or internal policy details.
- For university/private data questions, use only allowed_data returned by the database/tools. Do not invent students, grades, subjects, documents, or private data.
- For admin general-knowledge questions that do not require university/private data, answer from the AI model's general knowledge. If the question depends on live/current information, say that the system needs a web-search tool for real-time verification.
- Answer only what the user asked. Do not dump unrelated fields.
- Choose answer length based on the question: short factual questions get 1 short sentence; summaries/explanations get a few bullets; requests for full report/table get a longer structured answer.
- If allowed_data contains relevant uploaded documents, you MUST use them. Do not say there is no document data unless allowed_data is empty.
- If the data is missing, explain what is missing and what the user can do next. If the question may contain a typo, infer the closest allowed match before asking them to choose.
- For student/advisor roles, if the question is outside their allowed university area, politely explain what they can ask about.
- If the user is angry, respond calmly and fix the issue directly.
- For follow-up messages, use recent chat history to answer smoothly and avoid repeating confusing refusals; never use it to bypass role restrictions.
- If the user challenges the answer with “really?”, “then?”, or a similar short reply, answer like a normal follow-up: acknowledge, clarify the previous result, and say the next useful action.
- In admin normal-chat mode with no selected tool, behave like a regular ChatGPT-style assistant. Markdown, tables, examples, and code blocks are allowed.
"""

ROLE_PROMPTS = {
    "admin": """
ADMIN ROLE PROMPT:
- Admin mode should feel like a normal ChatGPT-style assistant plus full university database access.
- The admin can ask anything text-based: writing, editing, grammar, coding, debugging, math, translation, explanations, lesson planning, brainstorming, general knowledge, and normal conversation. Answer naturally when no university database/tool is needed.
- The admin is allowed to access all university data: all student records, grades, GPA values, contact/private fields, advisor notes, advisor data, programs, advisor-subject links, admin PDF/Excel files, and advisor subject PDF/Excel files.
- For university/private questions, do not rely only on model memory. Use allowed_data from the database/tool results.
- However, even for admin, answer only the exact information requested. Do not dump private fields unless asked for full profile/everything.
- If admin asks for all/everyone/all students, use all allowed_data and summarize cleanly.
- If admin asks about uploaded PDF/Excel files/documents/policies/announcements, use the stored uploaded document data.
- If the exact policy is not found but uploaded documents are provided, answer from the most relevant uploaded document instead of refusing. Mention the filename if helpful.
- If admin asks for document names, list document names/IDs. If admin asks for document content, summarize the stored document data.
- For Thai questions or Thai selected language, answer in Thai naturally.
- Never refuse an in-scope admin database/document question just because it asks for broad data.
""",
    "advisor": """
ADVISOR ROLE PROMPT:
- Advisors may only see the students/subjects they teach.
- Advisors may see student_id, name, program, academic_status, and subject_grades only for taught subjects.
- Advisors may search and answer from their own uploaded subject PDF/Excel files only.
- Never reveal GPA, phone, email, national_id, passport_id, address, or advisor_note for students.
- If the advisor asks for all/everyone, answer only for students/subjects/documents included in allowed_data.
""",
    "student": """
STUDENT ROLE PROMPT:
- Students may only see their own record.
- Students may see their own student_id, name, program, GPA, academic_status, subject_grades, and email.
- Students may answer from advisor-uploaded PDF/Excel files only when allowed_data returned it, which means the student is enrolled in that subject with that advisor.
- Never answer with another student's private data, another subject's advisor PDF/Excel file, or admin-only PDF/Excel data.
""",
}

TASK_PROMPTS = {
    "ADMIN_GRADE_ANALYST_PROMPT": "When answering grade summaries, count carefully from allowed_data. If grade_target is A, count exact grade 'A' only, not A-. Present concise bullet points or a small readable summary.",
    "ADMIN_DOCUMENT_AGENT_PROMPT": "When answering document questions, treat allowed_data as the uploaded PDF/Excel knowledge base. Be typo-tolerant and match misspelled user wording to filenames/document content when allowed_data supports it. If there is at least one document in allowed_data, use the best matching document and answer naturally from filename, summary, conclusion_table, and text_excerpt. Explain clearly in simple language, not just a raw summary. Do not say you have no data when documents are present. For short questions like 'ตำราจำหน่ายคืออะไร', give a concise Thai explanation of what the document says. For document-name requests, list filenames and IDs only unless asked for summaries. If exact wording is not found but recent documents are provided, explain the closest relevant uploaded document and say the exact wording was not found only if necessary.",
    "ADMIN_DIRECTORY_AGENT_PROMPT": "When listing names, list only student IDs and names. Do not include grades or private details.",
    "ADVISOR_GRADE_ANALYST_PROMPT": "Summarize only the advisor-visible subject grades in allowed_data. Do not mention hidden students or hidden fields.",
    "ADVISOR_DOCUMENT_AGENT_PROMPT": "When answering document questions, use only advisor-owned subject PDF/Excel files in allowed_data. Be typo-tolerant: if a query spelling is close to a filename/title/subject, answer the closest allowed document. Mention subject_name and filename when helpful. Explain the content clearly in simple language, not just a raw summary. Do not reference admin/global PDF/Excel files.",
    "STUDENT_ADVISOR_DOCUMENT_PROMPT": "When answering document questions, use only advisor-uploaded PDF/Excel files in allowed_data. These are already filtered to the logged-in student's enrolled subjects. Be typo-tolerant: if a query spelling is close to a filename/title/subject, answer the closest allowed document. Explain the file clearly in simple language with the main idea, useful details, and what the student should understand. If allowed_data is empty, say no advisor PDF/Excel file is available for the student's enrolled subjects.",
    "STUDENT_SELF_DATA_AGENT_PROMPT": "Answer only about the logged-in student's own data.",
    "ADMIN_GENERAL_KNOWLEDGE_PROMPT": "Admin is asking a normal general-knowledge question that does not require university database data. Answer naturally like ChatGPT. Do not pretend to have live internet. If the answer requires current or real-time facts, clearly say a web-search tool should be added/used for verification.",
    "ADMIN_NORMAL_CHATGPT_PROMPT": "Admin is using normal ChatGPT mode. Help with anything text-based: writing, rewriting, grammar, coding, debugging, math, teaching, planning, brainstorming, summaries, translation, explanations, tables, and general knowledge. Use markdown/code blocks when helpful. Do not restrict the answer to university topics. Do not mention university tools unless the user asks for university/private/database/PDF/Excel data. If the request depends on live current information, say that a web-search tool would be needed for real-time verification.",
    "ADMIN_DATABASE_ARCHITECT_PROMPT": "Explain the database map like an admin dashboard. Mention the main stores, tables/collections, what each one is for, and what follow-up questions admin can ask. Keep it clear and do not expose raw JSON.",
    "ADMIN_SUBJECT_AGENT_PROMPT": "When answering subject/course summary questions, do not confuse subjects with students. Use unique_subject_count for how many subjects/courses exist. Use total_subject_grade_records only when explaining enrollment/grade records.",
    "ADMIN_PROGRAM_AGENT_PROMPT": "When answering program/major/faculty questions, count and list programs from allowed_data. Do not answer with student count unless the user asked students.",
}


def _compact_history(chat_history: Optional[List[Dict[str, Any]]], max_items: int = 8) -> List[Dict[str, str]]:
    if not chat_history:
        return []
    return [
        {"role": str(msg.get("role", "user")), "content": str(msg.get("content", ""))[:500]}
        for msg in chat_history[-max_items:]
    ]


def _normalize_tool_data(tool_result: Dict[str, Any]) -> Any:
    data = tool_result.get("data")
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return data["data"]
    return data


def _json_preview(value: Any, max_chars: int = 12000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def _role_system_prompt(user_role: str, plan: Dict[str, Any]) -> str:
    role = (user_role or "student").lower()
    prompt_name = plan.get("role_prompt_name") or ""
    return "\n\n".join([
        BASE_SYSTEM_RULES.strip(),
        ROLE_PROMPTS.get(role, ROLE_PROMPTS["student"]).strip(),
        TASK_PROMPTS.get(prompt_name, "").strip(),
    ]).strip()



def _answer_length_instruction(user_message: str) -> str:
    text = (user_message or "").lower().strip()
    short_markers = ["what is", "who is", "ชื่อ", "คืออะไร", "คือ", "gpa", "name"]
    long_markers = ["explain", "summarize", "summary", "detail", "details", "compare", "report", "table", "ทั้งหมด", "สรุป", "อธิบาย", "รายละเอียด"]
    if any(m in text for m in long_markers):
        return "Use a medium or detailed answer with bullets if helpful."
    if len(text.split()) <= 10 or any(m in text for m in short_markers):
        return "Use a short direct answer, usually 1-3 sentences."
    return "Use a natural medium-length answer."

def generate_database_worker_answer(
    user_message: str,
    worker_plan: dict,
    tool_result: dict,
    language: str = "en"
) -> str:
    operation = tool_result.get("operation") or worker_plan.get("operation")
    records = tool_result.get("records", [])
    summary = tool_result.get("summary", "")

    if operation == "student_risk_score":
        lines = [
            summary,
            "",
            "Here are the students who may need the most academic support:",
            ""
        ]

        for i, row in enumerate(records, start=1):
            lines.append(
                f"{i}. {row.get('student_id')} — {row.get('name')} "
                f"— GPA {row.get('gpa')} — Risk Score {row.get('risk_score')}"
            )

        lines.append("")
        lines.append("Reason: The ranking is based on GPA, academic status, and weak subject grades.")

        return "\n".join(lines)

    if operation == "lowest_gpa":
        lines = [
            "Here are the student(s) with the lowest GPA:",
            ""
        ]

        for i, row in enumerate(records, start=1):
            lines.append(
                f"{i}. {row.get('student_id')} — {row.get('name')} "
                f"— GPA {row.get('gpa')} — {row.get('academic_status')}"
            )

        return "\n".join(lines)

    if operation == "average_gpa":
        overall = tool_result.get("overall_average_gpa")
        by_program = tool_result.get("by_program", [])

        lines = [
            f"Overall average GPA: {overall}",
            "",
            "Average GPA by program:",
            ""
        ]

        for row in by_program:
            lines.append(
                f"- {row.get('program')}: {row.get('average_gpa')} "
                f"({row.get('student_count')} students)"
            )

        return "\n".join(lines)

    if operation == "duplicate_check":
        count = tool_result.get("total_duplicate_groups", 0)

        if count == 0:
            return "I checked the database and found no duplicate student IDs."

        lines = [
            f"I found {count} duplicated student ID group(s).",
            "",
            "Please review them before deleting or merging records."
        ]

        return "\n".join(lines)

    return tool_result.get("message") or summary or "Database Worker AI completed the task."

def _has_allowed_data(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, dict):
        if value.get("success") is False:
            return False
        if "data" in value:
            return _has_allowed_data(value.get("data"))
        return bool(value)
    return bool(value)


def _is_document_payload(payload: Dict[str, Any]) -> bool:
    args = payload.get("tool_arguments") or {}
    return payload.get("selected_tool") == "postgres_university_tool" and args.get("query_type") in {"documents", "advisor_documents", "all_documents"}

def _call_ai_agent(payload: Dict[str, Any], system_prompt: str) -> Optional[str]:
    user = f"""
User question:
{payload.get('user_message')}

Language:
{payload.get('language')}

User role:
{payload.get('user_role')}

Answer length rule:
{_answer_length_instruction(payload.get('user_message', ''))}

Planner reason:
{(payload.get('tool_arguments') or {}).get('reason', '')}

Tool success:
{payload.get('tool_success')}

Tool error:
{payload.get('tool_error')}

Recent chat history for reference only:
{_json_preview(payload.get('recent_chat_history', []), 2500)}

Allowed data you may use:
{_json_preview(payload.get('allowed_data'), 12000)}

Decision rule:
- If allowed_data contains documents or Excel uploads, first choose the most relevant file by filename, source_type, subject, matched_terms, normalized_query, summary, structured_preview, and text_excerpt.
- If the user has a typo, correct it silently or say "I think you mean ..." only when helpful.
- Explain the document content clearly. Do not only list the title.
- If match_score is 0 for every document and the question is not asking for a list, explain the closest allowed document only if it is clearly relevant from filename/subject/history; otherwise ask which document they mean.
- For PDF answers, include: main idea, simple explanation, key points, useful details, and conclusion when available.
- For Excel answers, include: sheets, important columns, row counts, numeric summaries, sample row insights, and conclusion when available.

Write the final answer only. Be natural and helpful. Do not show raw data structures. If allowed data is present, answer from it instead of refusing.
""".strip()

    try:
        answer = ai_generate_text(
            system_prompt=system_prompt,
            prompt=user,
            json_mode=False,
            timeout_env="GEMINI_TIMEOUT",
            default_timeout=180,
            temperature=0.05,
            max_output_tokens=4096,
        )
        answer = str(answer or "").strip()
        answer = re.sub(r"^```(?:json|python|text)?", "", answer).strip()
        answer = re.sub(r"```$", "", answer).strip()
        if _reject_ai_answer(answer, payload):
            return None
        return answer
    except Exception:
        return None


def _reject_ai_answer(answer: str, payload: Dict[str, Any]) -> bool:
    if not answer or len(answer.strip()) < 2:
        return True
    low = answer.lower().strip()

    # Admin + no tool = normal ChatGPT-style mode.
    # Do not reject markdown, code blocks, JSON examples, or normal wording here.
    # Only block obvious hallucinated university private data when no database tool was used.
    if payload.get("selected_tool") == "none" and (payload.get("user_role") or "").lower() == "admin":
        suspicious_private = ["s001", "s002", "nina", "ken", "national id", "passport", "advisor_note", "gpa: 3."]
        if any(x in low for x in suspicious_private) and not any(x in (payload.get("user_message") or "").lower() for x in ["example", "sample", "template", "json", "schema"]):
            return True
        return False

    if low.startswith("{") or low.startswith("["):
        return True
    bad_markers = [
        "allowed_data", "selected_tool", "tool_arguments", "mongodb_student_tool", "postgres_university_tool",
        "here is what i found", "```", "student_id\"", "\"student_id", "subject_grades", "national_id",
        "planner", "mcp", "database row",
    ]
    if any(marker in low for marker in bad_markers):
        return True
    if payload.get("selected_tool") == "none" and any(x in low for x in ["s001", "s002", "nina", "ken", "gpa", "grade:"]):
        return True
    no_data_claims = [
        "don't have", "do not have", "no data", "not found", "cannot find", "can't find",
        "ไม่มีข้อมูล", "ไม่พบข้อมูล", "ไม่สามารถ", "ข้อมูลที่อนุญาต"
    ]
    if _has_allowed_data(payload.get("allowed_data")) and any(x in low for x in no_data_claims):
        # Especially important for uploaded PDF/Excel files: the model must answer from the document card/table, not refuse.
        if _is_document_payload(payload) or payload.get("user_role") == "admin":
            return True
    return False


def _lower(text: str) -> str:
    return (text or "").lower()


def _is_th(language: str) -> bool:
    return (language or "en").lower().startswith("th")


def _records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _field_value(data: Any, field: str) -> Any:
    recs = _records(data)
    if len(recs) == 1:
        return recs[0].get(field)
    if len(recs) > 1:
        return [{"student_id": r.get("student_id"), field: r.get(field)} for r in recs if field in r]
    return None


def _format_grade_summary(data: Any, language: str, user_role: str = "student") -> str:
    lang_th = _is_th(language)
    if not isinstance(data, dict) or data.get("type") != "grade_summary":
        return _format_grades(data, language, user_role)
    target = data.get("grade_target")
    students = data.get("students") or []
    if not students:
        return "ไม่พบข้อมูลเกรดที่อนุญาตให้ดูค่ะ" if lang_th else "I couldn’t find any grade data you’re allowed to view."
    if target:
        total = data.get("total_matching_grades", 0)
        lines = [f"{s.get('student_id')} ({s.get('name')}): {s.get('grade_count', 0)}" for s in students]
        if lang_th:
            return f"สรุปจำนวนเกรด {target} ทั้งหมดคือ {total} รายการ:\n" + "\n".join(f"- {x}" for x in lines)
        return f"There are {total} exact {target} grades in total. By student:\n" + "\n".join(f"- {x}" for x in lines)
    # No specific grade target: show distribution and per-student record counts.
    dist = data.get("grade_distribution") or {}
    dist_text = ", ".join(f"{g}: {c}" for g, c in sorted(dist.items()))
    lines = [f"{s.get('student_id')} ({s.get('name')}): {s.get('grade_count', 0)} grade records" for s in students[:50]]
    return ("สรุปเกรด: " if lang_th else "Grade summary: ") + dist_text + "\n" + "\n".join(f"- {x}" for x in lines)


def _owner_label(record: Dict[str, Any], user_role: str, possessive: bool = False) -> str:
    """Human-friendly label for deterministic answers."""
    role = (user_role or "student").lower()
    sid = record.get("student_id") or "the student"
    name = record.get("name") or ""
    base = f"{sid} ({name})" if name and sid != "the student" else str(sid)
    if role == "student":
        return "your" if possessive else "you"
    return f"{base}'s" if possessive else base


def _format_subjects(data: Any, language: str, user_role: str = "student") -> str:
    lang_th = _is_th(language)
    role = (user_role or "student").lower()
    recs = _records(data)
    lines: List[str] = []
    for record in recs:
        sid = record.get("student_id", "")
        name = record.get("name", "")
        grades = record.get("subject_grades") or []
        subjects = [g.get("subject") for g in grades if isinstance(g, dict) and g.get("subject")]
        if not subjects and record.get("message"):
            lines.append(f"{sid} {name}: {record.get('message')}")
        elif subjects:
            if len(recs) > 1:
                label = f"{sid} ({name})" if name else sid
                lines.append(f"{label}: {', '.join(subjects)}")
            else:
                lines.extend(subjects)
    if not lines:
        return "ฉันไม่พบรายวิชาที่มีสิทธิ์ดูค่ะ" if lang_th else "I couldn’t find subject information in the allowed data."
    if len(lines) == 1:
        if role == "student":
            return f"รายวิชาของคุณคือ {lines[0]} ค่ะ" if lang_th else f"Your subject is {lines[0]}."
        return f"รายวิชาคือ {lines[0]} ค่ะ" if lang_th else f"The subject is {lines[0]}."
    prefix = "รายวิชาของคุณคือ:" if role == "student" else "Subjects:"
    if lang_th and role != "student":
        prefix = "รายวิชา:"
    return prefix + "\n" + "\n".join(f"- {x}" for x in lines)

def _format_grades(data: Any, language: str, user_role: str = "student") -> str:
    lang_th = _is_th(language)
    role = (user_role or "student").lower()
    recs = _records(data)
    lines: List[str] = []
    for record in recs:
        sid = record.get("student_id", "")
        name = record.get("name", "")
        grades = record.get("subject_grades") or []
        if not grades and record.get("message"):
            lines.append(f"{sid} {name}: {record.get('message')}")
            continue
        if len(recs) > 1 and grades:
            lines.append(f"{sid} - {name}")
        for item in grades:
            if isinstance(item, dict):
                subject = item.get('subject', 'Unknown subject')
                grade = item.get('grade', 'N/A')
                advisor = item.get('advisor_id')
                suffix = f" ({advisor})" if advisor and role in {"admin", "advisor"} else ""
                lines.append(f"- {subject}: {grade}{suffix}")
    if not lines:
        return "ฉันไม่พบข้อมูลเกรดที่มีสิทธิ์ดูค่ะ" if lang_th else "I couldn’t find grade information in the allowed data."
    if role == "student":
        prefix = "เกรดของคุณคือ:" if lang_th else "Your grades are:"
    else:
        prefix = "เกรดที่ดูได้คือ:" if lang_th else "The grades are:"
    return prefix + "\n" + "\n".join(lines)



def _format_gpa(data: Any, language: str, user_role: str = "student") -> str:
    lang_th = _is_th(language)
    role = (user_role or "student").lower()
    recs = _records(data)
    rows = []
    for r in recs:
        if r.get("message") and r.get("gpa") is None:
            rows.append(f"{r.get('student_id', '-')}: {r.get('message')}")
            continue
        if r.get("gpa") is not None:
            sid = r.get("student_id") or "-"
            name = r.get("name")
            label = f"{sid} ({name})" if name and role != "student" else ("your" if role == "student" else sid)
            rows.append(f"{label}: {r.get('gpa')}")
    if not rows:
        return "ไม่พบ GPA ค่ะ" if lang_th else "I couldn’t find the GPA."
    if role == "student" and len(rows) == 1:
        value = recs[0].get("gpa")
        return f"GPA ของคุณคือ {value} ค่ะ" if lang_th else f"Your GPA is {value}."
    return ("GPA ที่พบ:\n" if lang_th else "The GPAs are:\n") + "\n".join(f"- {x}" for x in rows)

def _format_student_profile(data: Any, language: str, user_role: str = "student") -> str:
    lang_th = _is_th(language)
    role = (user_role or "student").lower()
    recs = _records(data)
    if not recs:
        return "ไม่พบข้อมูลโปรไฟล์ที่มีสิทธิ์ดูค่ะ" if lang_th else "I couldn’t find profile information in the allowed data."

    def one_profile(r: Dict[str, Any]) -> str:
        if r.get("message") and not r.get("subject_grades"):
            sid = r.get("student_id") or "-"
            return f"{sid}: {r.get('message')}"

        grades = r.get("subject_grades") or []
        grade_lines = []
        for item in grades:
            if isinstance(item, dict):
                advisor = item.get("advisor_id")
                suffix = f" ({advisor})" if advisor and role in {"admin", "advisor"} else ""
                grade_lines.append(f"{item.get('subject', 'Unknown subject')}: {item.get('grade', 'N/A')}{suffix}")

        if role == "student":
            en_title = "Your profile:"
            th_title = "โปรไฟล์ของคุณ:"
        else:
            sid = r.get("student_id", "the student")
            name = r.get("name")
            en_title = f"{sid}" + (f" ({name})" if name else "")
            th_title = en_title

        if lang_th:
            lines = [th_title]
            if "student_id" in r: lines.append(f"- Student ID: {r.get('student_id', '-')}")
            if "name" in r: lines.append(f"- ชื่อ: {r.get('name', '-')}")
            if "program" in r: lines.append(f"- หลักสูตร/สาขา: {r.get('program', '-')}")
            if "gpa" in r: lines.append(f"- GPA: {r.get('gpa', '-')}")
            if "academic_status" in r: lines.append(f"- สถานะ: {r.get('academic_status', '-')}")
            if "email" in r: lines.append(f"- อีเมล: {r.get('email', '-')}")
            if role == "admin":
                if "phone" in r: lines.append(f"- โทรศัพท์: {r.get('phone', '-')}")
                if "national_id" in r: lines.append(f"- National ID: {r.get('national_id', '-')}")
                if "passport_id" in r: lines.append(f"- Passport ID: {r.get('passport_id', '-')}")
                if "address" in r: lines.append(f"- ที่อยู่: {r.get('address', '-')}")
                if "advisor_note" in r: lines.append(f"- Advisor note: {r.get('advisor_note', '-')}")
            if grade_lines:
                lines.append("- เกรดรายวิชา: " + "; ".join(grade_lines))
            return "\n".join(lines)

        lines = [en_title]
        if "student_id" in r: lines.append(f"- Student ID: {r.get('student_id', '-')}")
        if "name" in r: lines.append(f"- Name: {r.get('name', '-')}")
        if "program" in r: lines.append(f"- Program: {r.get('program', '-')}")
        if "gpa" in r: lines.append(f"- GPA: {r.get('gpa', '-')}")
        if "academic_status" in r: lines.append(f"- Academic status: {r.get('academic_status', '-')}")
        if "email" in r: lines.append(f"- Email: {r.get('email', '-')}")
        if role == "admin":
            if "phone" in r: lines.append(f"- Phone: {r.get('phone', '-')}")
            if "national_id" in r: lines.append(f"- National ID: {r.get('national_id', '-')}")
            if "passport_id" in r: lines.append(f"- Passport ID: {r.get('passport_id', '-')}")
            if "address" in r: lines.append(f"- Address: {r.get('address', '-')}")
            if "advisor_note" in r: lines.append(f"- Advisor note: {r.get('advisor_note', '-')}")
        if grade_lines:
            lines.append("- Subject grades: " + "; ".join(grade_lines))
        return "\n".join(lines)

    if len(recs) == 1:
        r = recs[0]
        if role != "student" and not lang_th and not r.get("message"):
            # Keep the old friendly single-student title.
            sid = r.get("student_id", "the student")
            name = r.get("name")
            body = one_profile(r).split("\n")
            body[0] = f"Here’s {sid}'s profile" + (f" ({name}):" if name else ":")
            return "\n".join(body)
        if role != "student" and lang_th and not r.get("message"):
            sid = r.get("student_id", "the student")
            name = r.get("name")
            body = one_profile(r).split("\n")
            body[0] = f"โปรไฟล์ของ {sid}" + (f" ({name}):" if name else ":")
            return "\n".join(body)
        return one_profile(r)

    header = "โปรไฟล์ที่พบ:" if lang_th else "Here are the student profiles I found:"
    return header + "\n\n" + "\n\n".join(one_profile(r) for r in recs)

def _format_documents(data: Any, language: str, user_message: str = "", user_role: str = "student") -> str:
    lang_th = _is_th(language)
    records = _records(data)
    if not records:
        role = (user_role or "student").lower()
        if role == "admin":
            return "ยังไม่พบไฟล์ PDF/Excel ในระบบทั้งฝั่ง Admin และ Advisor ค่ะ" if lang_th else "I don’t see any uploaded PDF/Excel files yet in either the admin/global store or advisor subject store."
        if role == "advisor":
            return "ยังไม่พบไฟล์ PDF/Excel ที่คุณอัปโหลดสำหรับวิชาของคุณค่ะ" if lang_th else "I don’t see any subject PDF/Excel files you’ve uploaded yet."
        if lang_th:
            return "ยังไม่พบไฟล์ PDF/Excel จากอาจารย์สำหรับวิชาที่คุณลงเรียนค่ะ ถ้าอาจารย์อัปโหลดไฟล์แล้ว ไฟล์จะแสดงในแถบด้านขวาและฉันจะช่วยอธิบายให้ได้ค่ะ"
        return "I don’t see any advisor PDF/Excel files for your enrolled subjects yet. Once your advisor uploads a file for your subject, it will appear on the right panel and I can explain it here."

    text = _lower(user_message)
    wants_names = any(w in text for w in ["name", "names", "list", "already", "upload", "uploads", "uploaded", "stored", "available", "beside", "besides", "subject upload", "รายชื่อ", "ชื่อ", "ไฟล์", "มีอะไรบ้าง"])
    if wants_names:
        lines = []
        for doc in records[:20]:
            subject = doc.get('subject_name')
            advisor = doc.get('advisor_id')
            extra = f" — {subject}" if subject else ""
            if advisor:
                extra += f" ({advisor})"
            source = str(doc.get('source_type') or 'pdf').upper()
            agent = doc.get('cloned_agent_name') or ''
            agent_note = f" • {agent}" if agent else ""
            lines.append(f"#{doc.get('id')} [{source}] {doc.get('filename', 'Untitled')}{extra}{agent_note}")
        role = (user_role or "student").lower()
        if role == "admin":
            header = "PDF ทั้งหมดในระบบ (Admin + Advisor):\n" if lang_th else "All uploaded PDF/Excel files in the university system (admin + advisor):\n"
        elif role == "advisor":
            header = "PDF วิชาที่คุณอัปโหลดมีดังนี้:\n" if lang_th else "Your uploaded subject PDF/Excel files:\n"
        else:
            header = "เอกสารที่คุณมีสิทธิ์ดูมีดังนี้:\n" if lang_th else "Stored documents you can access:\n"
        return header + "\n".join(f"- {x}" for x in lines)


    # Prefer a document with a positive match score. If every score is 0, keep the newest
    # document but make the answer transparent, because it may be a typo or ambiguous question.
    scored = [r for r in records if isinstance(r.get("match_score"), int)]
    doc = max(scored, key=lambda r: r.get("match_score", 0)) if scored else records[0]
    title = doc.get("filename", "เอกสาร")
    table = doc.get("conclusion_table") or {}
    summary = table.get("short_summary") or table.get("summary") or doc.get("summary", "")
    main_topic = table.get("main_topic") or ""
    conclusion = table.get("clear_conclusion") or table.get("conclusion") or ""
    rows = table.get("rows") or []
    excerpt = str(doc.get("text_excerpt") or doc.get("text_preview") or "")
    source_type = str(doc.get("source_type") or table.get("source_type") or "pdf").lower()
    structured_preview = doc.get("structured_preview") or {}
    structured_data = doc.get("structured_data") or {}
    if source_type == "excel":
        sheet_lines = []
        sheets = []
        if isinstance(structured_preview, dict):
            sheets = structured_preview.get("sheets") or []
        if not sheets and isinstance(structured_data, dict):
            sheets = structured_data.get("sheets") or []
        for sheet in sheets[:5]:
            if isinstance(sheet, dict):
                cols = ", ".join(str(c) for c in (sheet.get("columns") or [])[:12])
                sheet_lines.append(f"- {sheet.get('sheet_name', 'Sheet')}: {sheet.get('row_count', 0)} rows; columns: {cols}")
                numeric = sheet.get("numeric_summary") or {}
                if numeric:
                    sample_numeric = "; ".join(
                        f"{k}: min {v.get('min')}, max {v.get('max')}, avg {v.get('mean')}"
                        for k, v in list(numeric.items())[:4]
                        if isinstance(v, dict)
                    )
                    if sample_numeric:
                        sheet_lines.append(f"  Numeric summary: {sample_numeric}")
        detail_values = []
        for key in ["key_points", "detailed_information", "important_columns", "data_quality_notes"]:
            value = table.get(key) or []
            if isinstance(value, list):
                detail_values.extend(str(x) for x in value if str(x).strip())
        if rows:
            for row in rows[:5]:
                if isinstance(row, dict):
                    info = row.get("Detailed information") or row.get("Main point") or row.get("Simple explanation")
                    if info and str(info).strip() not in detail_values:
                        detail_values.append(str(info).strip())
        subject_line = f" for {doc.get('subject_name')}" if doc.get("subject_name") else ""
        agent_line = f" It is handled by {doc.get('cloned_agent_name')}." if doc.get("cloned_agent_name") else ""
        if lang_th:
            parts = [f"ไฟล์ Excel ที่เกี่ยวข้องคือ “{title}”{subject_line}.{agent_line}"]
            if summary:
                parts.append(f"\n\nสรุปง่าย ๆ: {summary}")
            if sheet_lines:
                parts.append("\n\nข้อมูลชีต:\n" + "\n".join(sheet_lines))
            if detail_values:
                parts.append("\n\nข้อมูลสำคัญที่เก็บไว้:\n" + "\n".join(f"- {x}" for x in detail_values[:8]))
            if conclusion and conclusion != summary:
                parts.append(f"\n\nสรุปสุดท้าย: {conclusion}")
            return "".join(parts).strip()
        parts = [f"The relevant uploaded Excel file is “{title}”{subject_line}.{agent_line}"]
        if summary:
            parts.append(f"\n\nSimple explanation: {summary}")
        if sheet_lines:
            parts.append("\n\nSheet data:\n" + "\n".join(sheet_lines))
        if detail_values:
            parts.append("\n\nStored insights:\n" + "\n".join(f"- {x}" for x in detail_values[:8]))
        if conclusion and conclusion != summary:
            parts.append(f"\n\nConclusion: {conclusion}")
        return "".join(parts).strip()

    key_points = []
    for row in rows:
        if isinstance(row, dict):
            pieces = [
                row.get("Main point"), row.get("main_point"), row.get("point"),
                row.get("Detailed information"), row.get("detailed_information"), row.get("details"),
                row.get("Information"), row.get("information"),
                row.get("Simple explanation"), row.get("simple_explanation"), row.get("explanation"),
                row.get("Why it matters"), row.get("why_it_matters"),
            ]
            info = " — ".join(str(x).strip() for x in pieces if str(x or "").strip())
            if info and len(info) > 8 and info not in key_points:
                if len(re.findall(r"[A-Za-z0-9\u0E00-\u0E7F]", info)) / max(len(info), 1) > 0.45:
                    key_points.append(info)
        if len(key_points) >= 5:
            break
    if not key_points and excerpt:
        # Pull readable sentences from the extracted PDF text as a deterministic fallback.
        sentences = re.split(r"(?<=[.!?])\s+|\n+", excerpt)
        for sent in sentences:
            sent = re.sub(r"\s+", " ", sent).strip(" -•\t")
            if 25 <= len(sent) <= 260 and sent not in key_points:
                key_points.append(sent)
            if len(key_points) >= 4:
                break

    subject_line = f" ({doc.get('subject_name')})" if doc.get("subject_name") else ""
    score = doc.get("match_score", 0)
    maybe = ""
    if score == 0 and not wants_names:
        maybe = "I’m not fully sure which document you mean, but the closest allowed document I can see is "

    if lang_th:
        prefix = "เอกสารที่เกี่ยวข้องคือ" if score > 0 else "ฉันไม่แน่ใจว่าหมายถึงเอกสารไหน แต่เอกสารที่ใกล้เคียงที่สุดที่คุณมีสิทธิ์ดูคือ"
        parts = [f"{prefix} “{title}”{subject_line}"]
        if summary:
            parts.append(f"\n\nสรุปง่าย ๆ: {summary}")
        elif main_topic:
            parts.append(f"\n\nหัวข้อหลักคือ {main_topic}")
        else:
            parts.append("\n\nเอกสารนี้ถูกบันทึกไว้ในระบบ แต่สรุปจากไฟล์ยังไม่ชัดเจนมากค่ะ")
        if key_points:
            parts.append("\n\nประเด็นสำคัญ:\n" + "\n".join(f"- {p}" for p in key_points[:4]))
        if conclusion and conclusion != summary:
            parts.append(f"\n\nสรุปสุดท้าย: {conclusion}")
        return "".join(parts).strip()

    agent_line = f" It is handled by {doc.get('cloned_agent_name')}." if doc.get("cloned_agent_name") else ""
    prefix = (maybe + f"“{title}”{subject_line}.{agent_line}" if maybe else f"The relevant uploaded document is “{title}”{subject_line}.{agent_line}")
    parts = [prefix]
    if summary:
        parts.append(f"\n\nSimple explanation: {summary}")
    elif main_topic:
        parts.append(f"\n\nThe main topic is {main_topic}.")
    else:
        parts.append("\n\nIt is stored in the system, but the extracted summary is not very clear yet.")
    if key_points:
        parts.append("\n\nKey points:\n" + "\n".join(f"- {p}" for p in key_points[:4]))
    if conclusion and conclusion != summary:
        parts.append(f"\n\nConclusion: {conclusion}")
    return "".join(parts).strip()

def _natural_out_of_scope(user_message: str, language: str, user_role: str = "student") -> str:
    lang_th = _is_th(language)
    text = normalize_typos(user_message).strip()
    if (user_role or "").lower() == "admin":
        if is_greeting(user_message):
            return "สวัสดีค่ะ ถามได้ทุกเรื่องเหมือน ChatGPT ได้เลย หรือถามข้อมูลในฐานข้อมูลมหาวิทยาลัยก็ได้ค่ะ" if lang_th else "Hi — ask me anything like a normal ChatGPT chat, or ask me to check the university database/PDF/Excel files."
        return "ฉันตอบแบบแชททั่วไปได้ค่ะ แต่รอบนี้ Gemini ไม่ได้ส่งคำตอบกลับมา ลองถามใหม่อีกครั้ง หรือเช็ก GEMINI_API_KEY/connection ค่ะ" if lang_th else "I can answer like a normal chat, but Gemini did not return a response this time. Try again or check GEMINI_API_KEY/connection."
    if is_greeting(user_message):
        if lang_th:
            return "สวัสดีค่ะ 😊 ถามได้เลย เช่น เกรดของฉัน, GPA ของฉัน, วิชาที่เรียน, หรือไฟล์ PDF/Excel ที่อาจารย์อัปโหลด"
        return "Hi 😊 You can ask me about your grades, GPA, subjects, profile, or any advisor PDF/Excel files you’re allowed to read."
    if any(w in text for w in ["wtf", "fuck", "shit", "wrong", "bad answer", "มั่ว"]):
        return "I get it. Ask again in your words, even with typos, and I’ll match it to the allowed university data."
    return (
        "ฉันยังจับคำถามนี้กับข้อมูลในระบบไม่ได้ค่ะ ลองถามเป็นเรื่องเกรด GPA วิชา โปรไฟล์ หรือไฟล์ PDF/Excel ที่อัปโหลดได้เลยค่ะ"
        if lang_th else
        "I’m not fully sure what you want to check. Try asking about grades, GPA, subjects, profile, programs, or uploaded PDF/Excel files. Typos are okay."
    )


def _format_advisors(data: Any, language: str) -> str:
    lang_th = _is_th(language)
    if isinstance(data, dict) and data.get("type") == "advisor_list":
        advisors = data.get("advisors") or []
        if not advisors:
            return "ยังไม่พบข้อมูลอาจารย์ค่ะ" if lang_th else "I couldn’t find any advisors."
        lines = []
        for a in advisors[:100]:
            teaches = a.get("teaches") or []
            subject_count = len(teaches) if isinstance(teaches, list) else 0
            lines.append(f"{a.get('advisor_id')}: {a.get('name')} — {a.get('department', '-')} ({subject_count} teaching links)")
        return ("รายชื่ออาจารย์ทั้งหมด:\n" if lang_th else "Advisor list:\n") + "\n".join(f"- {x}" for x in lines)
    if isinstance(data, dict) and data.get("advisor_id"):
        teaches = data.get("teaches") or []
        teach_lines = []
        for item in teaches[:20]:
            if isinstance(item, dict):
                teach_lines.append(f"{item.get('student_id', '-')}: {item.get('subject', '-')}")
        if lang_th:
            lines = [f"ข้อมูลอาจารย์ {data.get('advisor_id')}:"]
            lines.append(f"- ชื่อ: {data.get('name', '-')}")
            lines.append(f"- แผนก: {data.get('department', '-')}")
            if data.get("email"): lines.append(f"- อีเมล: {data.get('email')}")
            if data.get("phone"): lines.append(f"- โทรศัพท์: {data.get('phone')}")
            if teach_lines: lines.append("- รายวิชาที่เกี่ยวข้อง: " + "; ".join(teach_lines))
            return "\n".join(lines)
        lines = [f"Advisor {data.get('advisor_id')}:"]
        lines.append(f"- Name: {data.get('name', '-')}")
        lines.append(f"- Department: {data.get('department', '-')}")
        if data.get("email"): lines.append(f"- Email: {data.get('email')}")
        if data.get("phone"): lines.append(f"- Phone: {data.get('phone')}")
        if teach_lines: lines.append("- Teaching links: " + "; ".join(teach_lines))
        return "\n".join(lines)
    return ""




def _format_student_list_result(data: Any, language: str, user_message: str, plan: Dict[str, Any]) -> str:
    """Format filtered/ranked student lists without pretending the result is one GPA."""
    lang_th = _is_th(language)
    records = _records(data)
    if not records:
        return "ไม่พบนักศึกษาที่ตรงกับเงื่อนไขนี้ค่ะ" if lang_th else "I couldn’t find any students matching that condition."

    args = plan.get("arguments") or {}
    universal = args.get("universal_query_plan") or {}
    operation = args.get("analysis_operation") or universal.get("operation") or "find"
    goal = universal.get("goal") or "matching students"
    limit = args.get("limit") or len(records)

    # Detect a concise condition label for the header.
    condition = ""
    for f in universal.get("filters") or []:
        if not isinstance(f, dict):
            continue
        if f.get("field") == "gpa":
            op_word = {
                "lt": "lower than", "lte": "lower than or equal to", "gt": "higher than",
                "gte": "higher than or equal to", "eq": "equal to", "ne": "not equal to",
            }.get(str(f.get("operator")), str(f.get("operator")))
            condition = f" with GPA {op_word} {f.get('value')}"
        elif f.get("field") == "program":
            condition += f" in program containing {f.get('value')}"
        elif f.get("field") == "academic_status":
            condition += f" with status containing {f.get('value')}"

    if operation == "rank" and not condition:
        if any((x.get("field") == "gpa" and x.get("direction") == "asc") for x in (universal.get("sort") or [])):
            condition = ", ranked by lowest GPA"
        elif any((x.get("field") == "gpa" and x.get("direction") == "desc") for x in (universal.get("sort") or [])):
            condition = ", ranked by highest GPA"

    lines = []
    for i, row in enumerate(records[:min(len(records), 50)], start=1):
        sid = row.get("student_id", "-")
        name = row.get("name", "-")
        pieces = [f"{i}. {sid} — {name}"]
        if row.get("program"):
            pieces.append(str(row.get("program")))
        if row.get("gpa") is not None:
            pieces.append(f"GPA {row.get('gpa')}")
        if row.get("academic_status"):
            pieces.append(str(row.get("academic_status")))
        # For improvement/risk questions, add a compact reason from grades if available.
        if operation == "rank" and row.get("subject_grades"):
            weak = []
            for g in row.get("subject_grades") or []:
                if isinstance(g, dict) and str(g.get("grade", "")).upper() in {"D", "F", "C-"}:
                    weak.append(f"{g.get('subject')}: {g.get('grade')}")
            if weak:
                pieces.append("weak subjects: " + "; ".join(weak[:3]))
        lines.append(" — ".join(pieces))

    if lang_th:
        if operation == "rank":
            header = f"พบนักศึกษาที่เกี่ยวข้อง {len(records)} คน ({goal})"
        else:
            header = f"พบนักศึกษาที่ตรงกับเงื่อนไข {len(records)} คน"
        if len(records) >= int(limit or 0):
            header += f" แสดงสูงสุด {limit} รายการตามที่ขอ"
        return header + "\n\n" + "\n".join(lines)

    if operation == "rank":
        header = f"I found {len(records)} student(s) for this ranking{condition}."
    else:
        header = f"I found {len(records)} student(s){condition}."
    if len(records) >= int(limit or 0):
        header += f" Showing up to {limit}."
    return header + "\n\n" + "\n".join(lines)




def _format_subject_summary(data: Any, language: str, user_role: str = "admin", user_message: str = "") -> str:
    lang_th = _is_th(language)
    if not isinstance(data, dict) or data.get("type") != "subject_summary":
        return ""
    subjects = data.get("subjects") or []
    top_subjects = data.get("top_subjects") or subjects[:20]
    unique_count = data.get("unique_subject_count", len(subjects))
    total_records = data.get("total_subject_grade_records", 0)
    student_scope = data.get("student_count_in_scope", 0)
    text = (user_message or "").lower()
    wants_list = any(w in text for w in ["list", "show", "all", "what are", "which", "รายชื่อ", "อะไรบ้าง", "ทั้งหมด"])

    if lang_th:
        lines = [f"มีรายวิชาไม่ซ้ำทั้งหมด {unique_count} วิชาในข้อมูลที่คุณมีสิทธิ์เข้าถึงค่ะ"]
        lines.append(f"ข้อมูลนี้นับจาก subject_grades ของนักศึกษา {student_scope} คน รวม {total_records} ระเบียนวิชา/เกรด")
        if wants_list or unique_count <= 30:
            lines.append("\nรายวิชา:")
            for row in subjects[:80]:
                advisors = ", ".join(row.get("advisors") or []) or "-"
                lines.append(f"- {row.get('subject')} — นักศึกษา {row.get('student_count', 0)} คน — advisor: {advisors}")
        else:
            lines.append("\nวิชาที่พบมากที่สุด:")
            for row in top_subjects[:10]:
                lines.append(f"- {row.get('subject')} ({row.get('student_count', 0)} คน)")
        lines.append("\nหมายเหตุ: จำนวนวิชา = ชื่อวิชาที่ไม่ซ้ำ ส่วนระเบียนวิชา/เกรด = แต่ละแถวที่นักศึกษามีเกรดในวิชานั้น")
        return "\n".join(lines)

    lines = [f"There are {unique_count} unique subject(s)/course(s) in the university data I can access."]
    lines.append(f"I counted this from subject_grades across {student_scope} student(s), with {total_records} total student-subject grade records.")
    if wants_list or unique_count <= 30:
        lines.append("\nSubjects:")
        for row in subjects[:80]:
            advisors = ", ".join(row.get("advisors") or []) or "-"
            lines.append(f"- {row.get('subject')} — {row.get('student_count', 0)} student(s) — advisor(s): {advisors}")
    else:
        lines.append("\nMost common subjects:")
        for row in top_subjects[:10]:
            lines.append(f"- {row.get('subject')} ({row.get('student_count', 0)} student(s))")
    lines.append("\nNote: unique subjects are counted by subject name. Total grade records count every student-subject row.")
    return "\n".join(lines)


def _format_programs(data: Any, language: str, user_message: str = "") -> str:
    lang_th = _is_th(language)
    rows = data if isinstance(data, list) else []
    if not rows:
        return "ยังไม่พบข้อมูลหลักสูตรค่ะ" if lang_th else "I couldn’t find any program data."
    text = (user_message or "").lower()
    wants_count_only = any(w in text for w in ["how many", "count", "number of", "total", "กี่", "จำนวน"]) and not any(w in text for w in ["list", "show", "what", "อะไร"])
    if lang_th:
        if wants_count_only:
            return f"มีหลักสูตรทั้งหมด {len(rows)} หลักสูตรค่ะ"
        lines = [f"พบหลักสูตร {len(rows)} หลักสูตร:"]
        for row in rows[:50]:
            lines.append(f"- {row.get('program_name', '-')} — {row.get('faculty', '-')} — ค่าเทอม {row.get('tuition_fee', '-')}")
        return "\n".join(lines)
    if wants_count_only:
        return f"There are {len(rows)} program(s) in the program table."
    lines = [f"I found {len(rows)} program(s):"]
    for row in rows[:50]:
        lines.append(f"- {row.get('program_name', '-')} — {row.get('faculty', '-')} — tuition: {row.get('tuition_fee', '-')}")
    return "\n".join(lines)

def _format_campus_info(data: Any, language: str) -> str:
    lang_th = _is_th(language)
    if not isinstance(data, dict):
        return ""
    if data.get("type") == "missing_campus_info_source":
        if lang_th:
            return "ยังไม่มีฐานข้อมูลสถานที่ในมหาวิทยาลัยค่ะ ต้องเพิ่มตาราง campus_locations ก่อน เช่น name, building, floor, location, opening_hours"
        return "I can’t find campus location data yet. Add a campus_locations table with fields like name, building, floor, location, and opening_hours, then I can answer location questions."
    if data.get("type") != "campus_info":
        return ""
    rows = data.get("rows") or []
    if not rows:
        keyword = data.get("keyword") or "that place"
        return (f"ไม่พบข้อมูลสถานที่สำหรับ {keyword} ค่ะ" if lang_th else f"I couldn’t find campus information for {keyword}.")
    lines = []
    for row in rows[:10]:
        name = row.get("name", "-")
        building = row.get("building") or ""
        floor = row.get("floor") or ""
        location = row.get("location") or ""
        hours = row.get("opening_hours") or ""
        pieces = [name]
        if building:
            pieces.append(building)
        if floor:
            pieces.append(floor)
        if location:
            pieces.append(location)
        if hours:
            pieces.append(f"Hours: {hours}")
        lines.append(" — ".join(pieces))
    return ("ข้อมูลสถานที่ที่พบ:\n" if lang_th else "Campus information found:\n") + "\n".join(f"- {x}" for x in lines)

def _format_large_result_report(data: Any, language: str, user_role: str = "admin") -> str:
    lang_th = _is_th(language)
    if not isinstance(data, dict) or data.get("type") != "large_result_with_report":
        return ""

    total = data.get("total_records", 0)
    limit = data.get("preview_limit", 20)
    rows = data.get("preview_rows") or []
    report = data.get("report") or {}
    url = report.get("download_url") or report.get("url") or ""

    def row_label(row: Dict[str, Any]) -> str:
        sid = row.get("student_id") or row.get("advisor_id") or row.get("id") or "-"
        name = row.get("name") or row.get("filename") or row.get("title") or "-"
        program = row.get("program") or row.get("department") or row.get("subject_name") or ""
        gpa = row.get("gpa")
        status = row.get("academic_status") or ""
        pieces = [str(sid), str(name)]
        if program:
            pieces.append(str(program))
        if gpa is not None:
            pieces.append(f"GPA {gpa}")
        if status:
            pieces.append(str(status))
        return " — ".join(pieces)

    preview_lines = [f"{i + 1}. {row_label(row)}" for i, row in enumerate(rows[:limit]) if isinstance(row, dict)]

    if lang_th:
        lines = [f"ฉันพบข้อมูลทั้งหมด {total} รายการค่ะ"]
        lines.append(f"ด้านล่างคือ {min(limit, len(rows))} รายการแรกสำหรับดูเร็ว:")
        if preview_lines:
            lines.append("\n".join(preview_lines))
        lines.append("เพราะข้อมูลมีมากกว่า 20 รายการ ฉันสร้างไฟล์ PDF ฉบับเต็มให้แล้วค่ะ")
        if url:
            lines.append(f"ดาวน์โหลด PDF: {url}")
        return "\n\n".join(lines)

    lines = [f"I found {total} records."]
    lines.append(f"Here are the first {min(limit, len(rows))} for quick review:")
    if preview_lines:
        lines.append("\n".join(preview_lines))
    lines.append("Because there are more than 20 records, I created a full PDF report.")
    if url:
        lines.append(f"Download PDF: {url}")
    return "\n\n".join(lines)


def _format_database_map(data: Any, language: str) -> str:
    lang_th = _is_th(language)
    if not isinstance(data, dict):
        return ""

    # Single Postgres database map.
    if data.get("type") == "postgres_database_map":
        tables = data.get("tables") or []
        if lang_th:
            lines = ["แผนที่ฐานข้อมูล PostgreSQL ที่ Admin เข้าถึงได้:"]
            for table in tables[:20]:
                cols = table.get("columns") or []
                col_names = ", ".join(str(c.get("column_name")) for c in cols[:8] if isinstance(c, dict))
                lines.append(f"- {table.get('table_name')}: {table.get('row_count')} records; columns: {col_names}")
            lines.append("ส่วน MongoDB จะเก็บข้อมูล student/advisor records ส่วน PostgreSQL จะเก็บ programs, chat history, subject links และ PDFs.")
            return "\n".join(lines)
        lines = ["Admin database map:"]
        for table in tables[:20]:
            cols = table.get("columns") or []
            col_names = ", ".join(str(c.get("column_name")) for c in cols[:8] if isinstance(c, dict))
            lines.append(f"- {table.get('table_name')}: {table.get('row_count')} records; columns: {col_names}")
        lines.append("MongoDB stores student/advisor records. PostgreSQL stores programs, chat history, subject links, and uploaded PDF knowledge.")
        return "\n".join(lines)

    # Single Mongo collection schema.
    if data.get("type") == "mongo_schema_overview":
        fields = data.get("fields") or []
        lines = [
            (f"แผนที่ MongoDB collection `{data.get('collection')}`: {data.get('count')} records" if lang_th else f"MongoDB collection `{data.get('collection')}`: {data.get('count')} records")
        ]
        for field in fields[:20]:
            lines.append(f"- {field.get('field')}: {', '.join(field.get('types') or [])}; example: {field.get('example')}")
        return "\n".join(lines)

    return ""


def _format_admin_bundle(data: Any, language: str) -> str:
    """Deterministic fallback for broad admin multi-tool questions."""
    lang_th = _is_th(language)
    if not isinstance(data, dict) or "admin_university_context" not in data:
        return ""
    bundle = data.get("admin_university_context") or {}

    def unwrap(key: str) -> Any:
        item = bundle.get(key) or {}
        inner = item.get("data") if isinstance(item, dict) else None
        if isinstance(inner, dict) and inner.get("success") is True and "data" in inner:
            return inner.get("data")
        return inner

    student_count = unwrap("student_count")
    students = unwrap("students")
    advisors = unwrap("advisors")
    programs = unwrap("programs")
    subjects = unwrap("advisor_subjects")
    docs = unwrap("documents")
    pg_map = unwrap("postgres_database_map")
    student_schema = unwrap("student_schema")
    advisor_schema = unwrap("advisor_schema")

    count_text = None
    if isinstance(student_count, dict) and "count" in student_count:
        count_text = student_count.get("count")
    student_list = students.get("students") if isinstance(students, dict) and students.get("type") == "student_names" else students
    advisor_list = advisors.get("advisors") if isinstance(advisors, dict) and advisors.get("type") == "advisor_list" else advisors
    doc_list = docs.get("data") if isinstance(docs, dict) else docs

    if lang_th:
        lines = ["ภาพรวมข้อมูลที่ Admin เข้าถึงได้ในระบบ:"]
        if count_text is not None: lines.append(f"- นักศึกษาทั้งหมด: {count_text} คน")
        if isinstance(student_list, list): lines.append(f"- รายชื่อนักศึกษา: {len(student_list)} รายการที่โหลดมา")
        if isinstance(advisor_list, list): lines.append(f"- อาจารย์/Advisor: {len(advisor_list)} คน")
        if isinstance(programs, list): lines.append(f"- Programs: {len(programs)} หลักสูตร")
        if isinstance(subjects, list): lines.append(f"- Advisor subjects: {len(subjects)} รายการ")
        if isinstance(doc_list, list): lines.append(f"- ไฟล์ PDF/Excel ทั้งหมด: {len(doc_list)} ไฟล์ (รวม admin/global และ advisor subject files)")
        if isinstance(pg_map, dict) and isinstance(pg_map.get("tables"), list): lines.append(f"- PostgreSQL tables: {len(pg_map.get('tables'))} tables")
        if isinstance(student_schema, dict) and student_schema.get("count") is not None: lines.append(f"- Mongo students collection: {student_schema.get('count')} records")
        if isinstance(advisor_schema, dict) and advisor_schema.get("count") is not None: lines.append(f"- Mongo advisors collection: {advisor_schema.get('count')} records")
        lines.append("ถามต่อได้เลย เช่น 'ขอโปรไฟล์ S001', 'สรุปเกรดทุกคน', 'PDF อะไรถูกอัปโหลด', หรือ 'รายชื่อ advisors'.")
        return "\n".join(lines)

    lines = ["Here’s the admin-level university overview I can access:"]
    if count_text is not None: lines.append(f"- Students: {count_text} total")
    if isinstance(student_list, list): lines.append(f"- Student directory loaded: {len(student_list)} records")
    if isinstance(advisor_list, list): lines.append(f"- Advisors: {len(advisor_list)} records")
    if isinstance(programs, list): lines.append(f"- Programs: {len(programs)} records")
    if isinstance(subjects, list): lines.append(f"- Advisor subject links: {len(subjects)} records")
    if isinstance(doc_list, list): lines.append(f"- PDF/Excel files: {len(doc_list)} files across admin/global and advisor subject stores")
    if isinstance(pg_map, dict) and isinstance(pg_map.get("tables"), list): lines.append(f"- PostgreSQL tables: {len(pg_map.get('tables'))} tables")
    if isinstance(student_schema, dict) and student_schema.get("count") is not None: lines.append(f"- Mongo students collection: {student_schema.get('count')} records")
    if isinstance(advisor_schema, dict) and advisor_schema.get("count") is not None: lines.append(f"- Mongo advisors collection: {advisor_schema.get('count')} records")
    lines.append("You can ask follow-ups like: 'S001 full profile', 'summarize all grades', 'what PDF/Excel files are uploaded?', or 'list advisors'.")
    return "\n".join(lines)


def _clarification(user_message: str, language: str, user_role: str) -> str:
    lang_th = _is_th(language)
    if user_role == "admin":
        return "What do you want to check? For example: S001 profile, all students, grade summary, programs, or uploaded PDF/Excel files."
    if user_role == "advisor":
        return "What do you want to check? You can ask about students you teach, subject grades, or your uploaded subject PDF/Excel files."
    if lang_th:
        return "อยากดูข้อมูลอะไรคะ เช่น เกรดของฉัน, GPA, วิชาที่เรียน, โปรไฟล์ หรือ ไฟล์ PDF/Excel ที่อาจารย์อัปโหลด"
    return "What do you want to check? You can ask: my grades, my GPA, my subjects, my profile, or advisor PDF/Excel files."


def _fallback_answer(user_message: str, language: str, user_role: str, plan: Dict[str, Any], tool_result: Dict[str, Any]) -> str:
    lang_th = _is_th(language)
    text = _lower(user_message)
    reason = (plan.get("arguments") or {}).get("reason")
    data = _normalize_tool_data(tool_result)

    large_report_answer = _format_large_result_report(data, language, user_role)
    if large_report_answer:
        return large_report_answer

    if plan.get("tool_name") == "none":
        if reason == "greeting":
            return _natural_out_of_scope(user_message, language, user_role)
        if reason == "clarification_needed":
            return _clarification(user_message, language, user_role)
        if reason in {"general_knowledge", "normal_chat"} and (user_role or "").lower() == "admin":
            return "I can answer normal ChatGPT-style questions, but Gemini did not return a response this time. Check GEMINI_API_KEY / internet connection, then try again."
        return _natural_out_of_scope(user_message, language, user_role)

    if not tool_result.get("success"):
        err = tool_result.get("error") or tool_result.get("detail") or "Unknown error"
        return f"ขออภัยค่ะ ไม่สามารถเข้าถึงข้อมูลได้: {err}" if lang_th else f"Sorry, I can’t access that information: {err}"

    if isinstance(data, dict) and data.get("success") is False:
        err = data.get("error") or "Access blocked or data unavailable."
        return f"ขออภัยค่ะ ไม่สามารถเข้าถึงข้อมูลได้: {err}" if lang_th else f"Sorry, I can’t access that information: {err}"

    if plan.get("tool_name") == "postgres_university_tool" and (plan.get("arguments") or {}).get("query_type") == "database_map":
        formatted = _format_database_map(data, language)
        if formatted:
            return formatted

    if isinstance(data, dict) and data.get("type") in {"postgres_database_map", "mongo_schema_overview"}:
        formatted = _format_database_map(data, language)
        if formatted:
            return formatted

    if plan.get("tool_name") == "postgres_university_tool" and (plan.get("arguments") or {}).get("query_type") == "programs":
        formatted = _format_programs(data, language, user_message)
        if formatted:
            return formatted

    if plan.get("tool_name") == "postgres_university_tool" and (plan.get("arguments") or {}).get("query_type") == "campus_info":
        formatted = _format_campus_info(data, language)
        if formatted:
            return formatted

    if plan.get("tool_name") == "postgres_university_tool" and (plan.get("arguments") or {}).get("query_type") in {"documents", "advisor_documents", "all_documents"}:
        return _format_documents(data, language, user_message, user_role=user_role)

    if data in ({}, [], None):
        if plan.get("tool_name") == "postgres_university_tool" and (plan.get("arguments") or {}).get("query_type") in {"documents", "advisor_documents", "all_documents"}:
            return _format_documents(data, language, user_message, user_role=user_role)
        return "ยังไม่พบข้อมูลที่ตรงกับคำถามนี้ค่ะ" if lang_th else "I couldn’t find that information in the data you’re allowed to access."

    if isinstance(data, dict) and data.get("type") == "subject_summary":
        formatted = _format_subject_summary(data, language, user_role, user_message)
        if formatted:
            return formatted
    if isinstance(data, dict) and data.get("type") == "grade_summary":
        return _format_grade_summary(data, language, user_role)
    if isinstance(data, dict) and data.get("type") == "student_names":
        students = data.get("students") or []
        if not students:
            return "No student names were found in the allowed data."
        return "Student names:\n" + "\n".join(f"- {s.get('student_id')}: {s.get('name')}" for s in students)
    if isinstance(data, dict) and data.get("type") == "student_count":
        return f"ฐานข้อมูลมีนักเรียนทั้งหมด {data['count']} คนค่ะ" if lang_th else f"The database contains {data['count']} students in total."
    if isinstance(data, dict) and "count" in data:
        return f"ฐานข้อมูลมีนักเรียนทั้งหมด {data['count']} คนค่ะ" if lang_th else f"The database contains {data['count']} students in total."
    if isinstance(data, dict) and "admin_university_context" in data:
        formatted = _format_admin_bundle(data, language)
        if formatted:
            return formatted
    if isinstance(data, dict) and (data.get("type") == "advisor_list" or data.get("advisor_id")):
        formatted = _format_advisors(data, language)
        if formatted:
            return formatted

    recs = _records(data)
    args = plan.get("arguments") or {}
    if plan.get("tool_name") == "mongodb_student_tool" and recs and (args.get("query_filter") or args.get("sort") or args.get("analysis_operation") in {"filter", "rank", "aggregate", "summarize"}):
        return _format_student_list_result(data, language, user_message, plan)

    if any(w in text for w in ["profile", "information", "info", "record", "details", "detail", "data", "ข้อมูล", "โปรไฟล์", "ข้อมูลส่วนตัว", "รายละเอียด"]):
        return _format_student_profile(data, language, user_role)
    if any(w in text for w in ["learn", "learning", "study", "studying", "take", "takes", "class", "course", "subject", "subjects", "เรียน", "วิชา"]):
        if any(w in text for w in ["grade", "score", "คะแนน", "เกรด"]):
            return _format_grades(data, language, user_role)
        return _format_subjects(data, language, user_role)
    if any(w in text for w in ["grade", "grades", "score", "คะแนน", "เกรด"]):
        return _format_grades(data, language, user_role)
    if any(w in text for w in ["name", "ชื่อ"]):
        value = _field_value(data, "name")
        if isinstance(value, list):
            lines = [f"{x.get('student_id')}: {x.get('name')}" for x in value if x.get("name")]
            return "\n".join(lines) if lines else ("ไม่พบชื่อค่ะ" if lang_th else "I couldn’t find the name.")
        sid = (_records(data)[0].get("student_id") if _records(data) else "")
        return (f"{sid} คือ {value} ค่ะ" if lang_th else f"{sid} is {value}.") if value else ("ไม่พบชื่อค่ะ" if lang_th else "I couldn’t find the name.")
    if any(w in text for w in ["gpa", "เกรดเฉลี่ย"]):
        return _format_gpa(data, language, user_role)

    recs = _records(data)
    if len(recs) == 1:
        r = recs[0]
        if r.get("student_id") and r.get("name"):
            return f"You are {r.get('name')} ({r.get('student_id')}). You can ask me for your grades, GPA, subjects, or full profile."
    return "I found related data. Please ask for the exact detail you want."



def _safe_database_answer(user_message: str, language: str, user_role: str, plan: Dict[str, Any], tool_result: Dict[str, Any]) -> Optional[str]:
    """Deterministic answer for protected DB data.

    The AI provider may sometimes over-refuse protected data even after the MCP tool returned
    allowed_data. This guard makes role/PDPA behavior stable: routing + policy decide
    access, then this formatter answers the common profile/grade/GPA/subject cases.
    """
    if not tool_result.get("success"):
        return None
    data = _normalize_tool_data(tool_result)
    large_report_answer = _format_large_result_report(data, language, user_role)
    if large_report_answer:
        return large_report_answer
    if not _has_allowed_data(data):
        return None
    selected = plan.get("tool_name")
    args = plan.get("arguments") or {}
    op = args.get("operation") or "normal"
    q = normalize_typos(user_message)

    if selected == "postgres_university_tool" and args.get("query_type") == "programs":
        formatted = _format_programs(data, language, user_message)
        return formatted or None

    if selected == "postgres_university_tool" and args.get("query_type") == "campus_info":
        formatted = _format_campus_info(data, language)
        return formatted or None

    if selected != "mongodb_student_tool":
        return None

    if isinstance(data, dict) and data.get("type") in {"student_count", "student_names", "grade_summary", "subject_summary"}:
        return _fallback_answer(user_message, language, user_role, plan, tool_result)

    # Broad/profile request: admin should never receive a fake no-access answer here.
    if op == "read_students":
        recs = _records(data)
        analysis_op = args.get("analysis_operation") or (args.get("universal_query_plan") or {}).get("operation")
        has_filter_or_sort = bool(args.get("query_filter") or args.get("sort") or analysis_op in {"filter", "rank", "aggregate", "summarize"})
        if recs and has_filter_or_sort and not args.get("requested_student_ids"):
            return _format_student_list_result(data, language, user_message, plan)
        if len(recs) > 1 and any(w in q for w in ["lower than", "less than", "below", "under", "higher than", "above", "over", "lowest", "highest", "top", "improve", "support", "weak"]):
            return _format_student_list_result(data, language, user_message, plan)
        if args.get("answer_style") == "grades":
            return _format_grades(data, language, user_role)
        if args.get("answer_style") == "profile":
            return _format_student_profile(data, language, user_role)
        if any(w in q for w in ["profile", "information", "info", "record", "detail", "details", "data", "full", "everything", "ข้อมูล", "โปรไฟล์", "รายละเอียด"]):
            return _format_student_profile(data, language, user_role)
        if any(w in q for w in ["gpa", "เกรดเฉลี่ย"]) or args.get("answer_style") == "gpa":
            return _format_gpa(data, language, user_role)
        if any(w in q for w in ["grade", "grades", "score", "scores", "คะแนน", "เกรด"]):
            return _format_grades(data, language, user_role)
        if any(w in q for w in ["subject", "subjects", "learn", "study", "studying", "course", "class", "วิชา", "เรียน"]):
            return _format_subjects(data, language, user_role)
        if any(w in q for w in ["name", "ชื่อ"]):
            return _fallback_answer(user_message, language, user_role, plan, tool_result)
        # Default student record request.
        return _format_student_profile(data, language, user_role)

    return None

def generate_final_answer(
    user_message: str,
    language: str,
    user_role: str,
    plan: Dict[str, Any],
    tool_result: Dict[str, Any],
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    data = _normalize_tool_data(tool_result)
    payload = {
        "user_message": user_message,
        "language": language,
        "user_role": user_role,
        "recent_chat_history": _compact_history(chat_history),
        "selected_agent": plan.get("selected_agent"),
        "selected_tool": plan.get("tool_name"),
        "tool_arguments": plan.get("arguments", {}),
        "allowed_data": data,
        "tool_success": tool_result.get("success"),
        "tool_error": tool_result.get("error"),
    }

    safe_answer = _safe_database_answer(user_message, language, user_role, plan, tool_result)
    if safe_answer:
        return safe_answer

    system_prompt = _role_system_prompt(user_role, plan)
    ai_answer = _call_ai_agent(payload, system_prompt)
    if ai_answer:
        return ai_answer
    return _fallback_answer(user_message, language, user_role, plan, tool_result)
