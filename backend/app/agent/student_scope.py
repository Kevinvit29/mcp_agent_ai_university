"""Central, future-safe scope guard for signed student accounts.

Student accounts may use university data only for:

* the student record bound to the signed login;
* normalized academic facts bound to that same student;
* analytics over that student's own enrolled courses/terms;
* learning files attached to a current ``student_course_enrollments`` row; and
* non-personal public catalog/campus information.

This guard runs after planning, so it also protects future AI-generated plans
that do not yet have a dedicated deterministic parser.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Optional


STUDENT_OWN_MONGO_OPERATIONS = {
    "read_students",
    "grade_summary",
    "subject_summary",
    "study_term_search",
    "study_term_aggregate",
    "filter_summary",
}

STUDENT_PUBLIC_POSTGRES_QUERY_TYPES = {
    "programs",
    "campus_info",
    "course_catalog",
}

STUDENT_OWN_POSTGRES_QUERY_TYPES = {
    "student_academic_profile",
    "student_subjects",
    "advisor_documents",
    "course_documents",
    "advisor_subjects",
}

STUDENT_COURSE_ANALYTICS_MEASURES = {
    "average_score",
    "pass_rate",
    "attendance_rate",
    "student_count",
    "score_change",
}

STUDENT_COURSE_ANALYTICS_DIMENSIONS = {
    "course",
    "term",
    "overall",
}


def _student_ids(message: str) -> list[str]:
    return list(dict.fromkeys(
        value.upper()
        for value in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I)
    ))


def _denial(
    plan: Dict[str, Any],
    *,
    reason: str,
    message: str,
    detail: str,
) -> Dict[str, Any]:
    guarded = copy.deepcopy(plan or {})
    previous_tool = guarded.get("tool_name")
    previous_arguments = guarded.get("arguments") if isinstance(guarded.get("arguments"), dict) else {}
    guarded["selected_agent"] = "student_own_scope_guard"
    guarded["tool_name"] = "none"
    guarded["role_prompt_name"] = "STUDENT_AGENT_PROMPT"
    guarded["arguments"] = {
        "reason": reason,
        "answer_style": "student_scope",
        "original_question": previous_arguments.get("original_question") or message,
        "scope_detail": detail,
        "blocked_tool": previous_tool,
        "blocked_operation": previous_arguments.get("operation"),
        "blocked_query_type": previous_arguments.get("query_type"),
    }
    guarded["intent_decision"] = {
        "intent": "access_restricted",
        "domain": "student_own_scope",
        "confidence": 1.0,
        "reason": detail,
    }
    guarded["planner_warning"] = "Student own-record/course scope guard blocked a broader database plan."
    orchestrator = guarded.setdefault("orchestrator", {})
    orchestrator.update({
        "version": "v30_student_scope_guard",
        "domain": "student_own_scope",
        "intent": "access_restricted",
        "confidence": 1.0,
        "reason": detail,
    })
    return guarded


def enforce_student_scope_plan(
    plan: Optional[Dict[str, Any]],
    *,
    message: str,
    user_role: str,
    requester_student_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Replace any broader student database plan with an explicit refusal."""
    if not plan or str(user_role or "").lower() != "student":
        return plan

    signed_id = str(requester_student_id or "").upper().strip()
    if not signed_id:
        return _denial(
            plan,
            reason="student_signed_identity_required",
            message=message,
            detail="Student database access requires a signed student identity.",
        )

    mentioned_ids = _student_ids(message)
    if any(student_id != signed_id for student_id in mentioned_ids):
        return _denial(
            plan,
            reason="student_other_record_denied",
            message=message,
            detail="The question names a student record other than the signed-in student.",
        )

    normalized_message = str(message or "").lower().strip()
    if (
        re.search(
            r"\b(?:list|show|find|give\s+me)\s+(?:everyone|everybody|all\s+(?:students?|learners?))\b",
            normalized_message,
        )
        or any(
            term in normalized_message
            for term in ("รายชื่อนักศึกษาทั้งหมด", "แสดงนักศึกษาทั้งหมด")
        )
    ):
        return _denial(
            plan,
            reason="student_own_scope_only",
            message=message,
            detail="Student accounts cannot list a broader student population.",
        )

    tool_name = str(plan.get("tool_name") or "none")
    arguments = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
    operation = str(arguments.get("operation") or "")

    if tool_name == "none":
        return plan

    if tool_name == "mongodb_student_tool":
        requested_id = str(arguments.get("student_id") or "").upper().strip()
        requested_ids = {
            str(value).upper().strip()
            for value in (arguments.get("requested_student_ids") or [])
            if str(value).strip()
        }
        if (
            requested_id not in {"", signed_id}
            or any(student_id != signed_id for student_id in requested_ids)
        ):
            reason = (
                "student_other_record_denied"
                if requested_id not in {"", "ALL", signed_id}
                or any(student_id != signed_id for student_id in requested_ids)
                else "student_own_scope_only"
            )
            return _denial(
                plan,
                reason=reason,
                message=message,
                detail=(
                    "The MongoDB plan targets a student other than the signed-in student."
                    if reason == "student_other_record_denied"
                    else "The MongoDB plan targets a broader student population."
                ),
            )
        if operation not in STUDENT_OWN_MONGO_OPERATIONS:
            return _denial(
                plan,
                reason="student_own_scope_only",
                message=message,
                detail="Student accounts cannot run population, directory, ranking, benchmark, or grouped student-master operations.",
            )
        return plan

    if tool_name == "postgres_university_tool":
        query_type = str(arguments.get("query_type") or "")
        if query_type in STUDENT_PUBLIC_POSTGRES_QUERY_TYPES:
            return plan
        if query_type in STUDENT_OWN_POSTGRES_QUERY_TYPES:
            requested_id = str(arguments.get("student_id") or signed_id).upper().strip()
            requested_ids = {
                str(value).upper().strip()
                for value in (arguments.get("student_ids") or [])
                if str(value).strip()
            }
            if (
                query_type == "student_academic_profile"
                and (
                    requested_id != signed_id
                    or any(student_id != signed_id for student_id in requested_ids)
                )
            ):
                return _denial(
                    plan,
                    reason="student_other_record_denied",
                    message=message,
                    detail="The academic plan targets a student other than the signed-in student.",
                )
            return plan
        if query_type == "academic_analytics":
            measure = str(arguments.get("measure") or "")
            dimension = str(arguments.get("dimension") or "")
            requested_ids = {
                str(value).upper().strip()
                for value in (arguments.get("student_ids") or [])
                if str(value).strip()
            }
            if (
                measure in STUDENT_COURSE_ANALYTICS_MEASURES
                and dimension in STUDENT_COURSE_ANALYTICS_DIMENSIONS
                and not any(student_id != signed_id for student_id in requested_ids)
            ):
                return plan
        return _denial(
            plan,
            reason="student_own_scope_only",
            message=message,
            detail="The PostgreSQL plan is outside the signed student's own academic and enrolled-course scope.",
        )

    if tool_name in {"pdf_tool", "excel_tool", "image_tool", "analyze_document_image"}:
        # Exact document authorization is checked against current enrollments before
        # any of these content tools receive a selected file.
        return plan

    return _denial(
        plan,
        reason="student_own_scope_only",
        message=message,
        detail="The selected tool is not available to a signed student account.",
    )
