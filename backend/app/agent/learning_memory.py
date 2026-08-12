"""AI learning memory for user corrections.

This module makes the chatbot improve from mistakes in normal use.
It does not train or fine-tune Gemini. Instead, it stores routing lessons in
PostgreSQL and applies them before the next database plan is created.

Example:
    User: how many subject are there in this university
    Old AI: There are 100 students.
    User: i mean subject

The system saves a lesson:
    phrase/domain: subject => use subject_summary, never student_count

Future similar questions are routed through the learned rule first.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from app.agent.database_brain import build_database_brain_plan
from app.agent.natural_query import normalize_typos
from app.db.postgres import save_ai_learning_memory, search_ai_learning_memories


DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "subjects": ["subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา"],
    "students": ["student", "students", "learner", "learners", "นักเรียน", "นักศึกษา"],
    "grades": ["grade", "grades", "score", "scores", "mark", "marks", "เกรด", "คะแนน"],
    "gpa": ["gpa", "average gpa", "เกรดเฉลี่ย"],
    "documents": ["pdf", "document", "documents", "file", "files", "excel", "xlsx", "csv", "spreadsheet", "upload", "uploaded", "เอกสาร", "ไฟล์", "เอ็กเซล"],
    "programs": ["program", "programs", "major", "majors", "faculty", "faculties", "หลักสูตร", "สาขา", "คณะ"],
    "advisors": ["advisor", "advisors", "teacher", "teachers", "อาจารย์", "ที่ปรึกษา"],
    "normal_chat": ["normal chat", "general", "chatgpt", "explain", "write", "translate", "grammar"],
}

CORRECTION_SIGNALS = [
    "i mean", "mean", "i meant", "actually", "no", "not", "wrong", "i said",
    "หมายถึง", "ไม่ใช่", "ผิด", "หมายความว่า", "เอา",
]

NEGATIVE_DOMAIN_HINTS = {
    "students": ["not student", "not students", "ไม่ใช่นักเรียน", "ไม่ใช่นักศึกษา"],
    "subjects": ["not subject", "not subjects", "ไม่ใช่วิชา"],
    "documents": ["not file", "not pdf", "not document", "ไม่ใช่ไฟล์", "ไม่ใช่เอกสาร"],
}


def _norm(text: str) -> str:
    return normalize_typos(text or "").strip().lower()


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9\u0E00-\u0E7F]+", _norm(text)))


def has_explicit_entities(text: str) -> bool:
    """Return True when the current user message already names exact records.

    Learning memory must never override fresh explicit entities such as S035 or A002.
    This bug previously caused a follow-up like "S035 grade" to be treated as a
    correction to the previous "S001 grade" question, so the chatbot answered S001.
    """
    if re.search(r"\bS\d{3,6}\b", text or "", flags=re.I):
        return True
    if re.search(r"\bA\d{3}\b", text or "", flags=re.I):
        return True
    return False


def infer_domain(text: str) -> Optional[str]:
    normalized = _norm(text)
    if not normalized:
        return None
    scores: Dict[str, int] = {}
    token_set = _tokens(normalized)
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = 0
        for kw in keywords:
            nkw = _norm(kw)
            if not nkw:
                continue
            if " " in nkw:
                if nkw in normalized:
                    score += 3
            elif re.search(r"[\u0E00-\u0E7F]", nkw):
                if nkw in normalized:
                    score += 3
            elif nkw in token_set:
                score += 3
            else:
                # typo tolerance for English single words
                for tok in token_set:
                    if len(tok) >= 5 and len(nkw) >= 5 and SequenceMatcher(None, tok, nkw).ratio() >= 0.82:
                        score += 1
                        break
        if score:
            scores[domain] = score
    if not scores:
        return None
    return max(scores.items(), key=lambda x: x[1])[0]


def infer_negative_domain(text: str) -> Optional[str]:
    normalized = _norm(text)
    for domain, phrases in NEGATIVE_DOMAIN_HINTS.items():
        if any(_norm(p) in normalized for p in phrases):
            return domain
    return None


def is_correction_message(message: str) -> bool:
    normalized = _norm(message)
    if not normalized:
        return False

    # A message that names a concrete record is a new request, not a correction.
    # Example: after "S001 grade", the user asks "S035 grade".  The old system
    # treated this as a short grade correction and reused S001.
    if has_explicit_entities(message):
        return False

    if any(sig in normalized for sig in CORRECTION_SIGNALS):
        return True

    # Short domain-only follow-ups after a wrong answer: "subject", "pdf", "gpa".
    # Only accept very short domain words without IDs/numbers.
    words = normalized.split()
    if len(words) <= 3 and infer_domain(normalized) and not re.search(r"\d", normalized):
        return True
    return False


def _last_turn(history: Optional[List[Dict[str, Any]]]) -> Tuple[str, str]:
    """Return the latest previous user question and assistant answer."""
    if not history:
        return "", ""
    prev_user = ""
    prev_assistant = ""
    for item in reversed(history):
        role = str(item.get("role") or "").lower()
        content = str(item.get("content") or "")
        if role == "assistant" and not prev_assistant:
            prev_assistant = content
        elif role == "user" and not prev_user:
            prev_user = content
        if prev_user and prev_assistant:
            break
    return prev_user, prev_assistant


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def make_effective_question(previous_question: str, correction: str, learned_domain: Optional[str]) -> str:
    """Create a clearer question for planning after a correction."""
    prev = (previous_question or "").strip()
    corr = (correction or "").strip()
    if not prev:
        return corr
    if learned_domain == "subjects" and "subject" not in _norm(prev) and "course" not in _norm(prev):
        return f"{prev} about subjects/courses"
    if learned_domain == "documents" and not any(w in _norm(prev) for w in ["pdf", "document", "file", "excel"]):
        return f"{prev} about uploaded PDF/Excel files"
    if learned_domain == "programs" and "program" not in _norm(prev):
        return f"{prev} about programs/majors/faculties"
    if learned_domain == "advisors" and "advisor" not in _norm(prev):
        return f"{prev} about advisors"
    if learned_domain in {"grades", "gpa"}:
        return f"{prev} {learned_domain}"
    return f"{prev}\nCorrection from user: {corr}"


def _memory_to_plan(
    domain: str,
    effective_question: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str],
    requester_advisor_id: Optional[str],
    history: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Convert a learned domain into an MCP plan."""
    # Let Database Brain build stable plans for schema/domain questions.
    if domain in {"subjects", "documents", "programs", "advisors"}:
        return build_database_brain_plan(
            message=effective_question,
            language=language,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            chat_history=history,
        )

    # For grade/GPA/profile corrections, use the normal role router with a clearer question.
    if domain in {"grades", "gpa", "students"}:
        from app.agent.role_router import route_to_role_agent
        return route_to_role_agent(
            message=effective_question,
            language=language,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            chat_history=history,
        )

    return None


def learn_from_user_correction(
    message: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str],
    requester_advisor_id: Optional[str],
    session_id: str,
    history: Optional[List[Dict[str, Any]]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]]:
    """Detect a correction, store it, and return a corrected plan.

    Returns: (plan, effective_question, memory_row)
    """
    if not is_correction_message(message):
        return None, None, None

    previous_question, previous_answer = _last_turn(history)
    if not previous_question:
        return None, None, None

    learned_domain = infer_domain(message)
    negative_domain = infer_negative_domain(message)

    # If the user says "not student, subject", prefer the positive domain.
    if not learned_domain:
        learned_domain = infer_domain(previous_question)

    if not learned_domain:
        return None, None, None

    effective_question = make_effective_question(previous_question, message, learned_domain)
    memory = save_ai_learning_memory(
        user_role=user_role,
        user_identifier=_identity(user_role, requester_student_id, requester_advisor_id),
        session_id=session_id,
        original_question=previous_question,
        correction_message=message,
        wrong_answer_excerpt=(previous_answer or "")[:1200],
        learned_domain=learned_domain,
        negative_domain=negative_domain,
        corrected_question=effective_question,
        confidence=0.95,
        metadata={
            "source": "user_correction",
            "language": language,
            "requester_student_id": requester_student_id,
            "requester_advisor_id": requester_advisor_id,
        },
    )

    plan = _memory_to_plan(
        learned_domain,
        effective_question,
        language,
        user_role,
        requester_student_id,
        requester_advisor_id,
        history,
    )
    if plan:
        plan["selected_agent"] = f"{user_role}_learning_memory_agent"
        plan.setdefault("arguments", {})["learning_memory_applied"] = True
        plan["arguments"]["learning_memory_id"] = memory.get("id") if isinstance(memory, dict) else None
        plan["arguments"]["learning_memory_domain"] = learned_domain
        plan["arguments"]["original_user_correction"] = message
    return plan, effective_question, memory


def apply_relevant_learning_memory(
    message: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str],
    requester_advisor_id: Optional[str],
    history: Optional[List[Dict[str, Any]]],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Apply a stored memory before normal routing when it strongly matches.

    Explicit IDs in the latest message always win over memory.  Memory is for
    ambiguous wording corrections like "I mean subject", not for replacing S035
    with a previous S001 context.
    """
    normalized = _norm(message)
    if not normalized:
        return None, None

    if has_explicit_entities(message):
        return None, None

    memories = search_ai_learning_memories(
        user_role=user_role,
        user_identifier=_identity(user_role, requester_student_id, requester_advisor_id),
        query=normalized,
        limit=10,
    )
    if not memories:
        return None, None

    best = None
    best_score = 0.0
    current_domain = infer_domain(message)
    current_tokens = _tokens(message)

    for mem in memories:
        corrected = str(mem.get("corrected_question") or "")
        original = str(mem.get("original_question") or "")
        learned_domain = str(mem.get("learned_domain") or "")
        keyword_blob = " ".join([corrected, original, learned_domain])
        token_overlap = len(current_tokens.intersection(_tokens(keyword_blob)))
        score = max(_similarity(message, corrected), _similarity(message, original))
        score += min(token_overlap * 0.08, 0.32)
        if current_domain and learned_domain == current_domain:
            score += 0.35
        if score > best_score:
            best_score = score
            best = mem

    if not best or best_score < 0.62:
        return None, None

    learned_domain = str(best.get("learned_domain") or "")
    # Do not let a vague memory override explicit student IDs unless the domain is grades/GPA/student data.
    if re.search(r"\bS\d{3,6}\b", message or "", flags=re.I) and learned_domain not in {"grades", "gpa", "students"}:
        return None, None

    effective_question = str(best.get("corrected_question") or message)
    # If current question already contains the target domain, use current wording. Otherwise append the memory domain.
    if current_domain == learned_domain:
        effective_question = message
    else:
        effective_question = make_effective_question(message, f"learned domain: {learned_domain}", learned_domain)

    plan = _memory_to_plan(
        learned_domain,
        effective_question,
        language,
        user_role,
        requester_student_id,
        requester_advisor_id,
        history,
    )
    if plan:
        plan["selected_agent"] = f"{user_role}_learning_memory_agent"
        plan.setdefault("arguments", {})["learning_memory_applied"] = True
        plan["arguments"]["learning_memory_id"] = best.get("id")
        plan["arguments"]["learning_memory_domain"] = learned_domain
        plan["arguments"]["learning_memory_score"] = round(best_score, 3)
    return plan, best


def _identity(user_role: str, requester_student_id: Optional[str], requester_advisor_id: Optional[str]) -> str:
    role = (user_role or "student").lower()
    if role == "student":
        return requester_student_id or "unknown_student"
    if role == "advisor":
        return requester_advisor_id or "unknown_advisor"
    if role == "admin":
        return "ADMIN"
    return "unknown"
