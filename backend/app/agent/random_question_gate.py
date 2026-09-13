"""Signed live-chat gate for varied V30 questions.

Run inside the backend container::

    python -m app.agent.random_question_gate

The gate uses the same authenticated ``/chat`` endpoint as the browser. It
checks routing metadata only and never prints answer text or private record
values. Temporary chat sessions created by the gate are deleted in ``finally``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import requests

from app.db.postgres import get_connection
from app.production_security import issue_access_token


GATE_VERSION = "V30_RANDOM_QUESTION_LIVE_GATE_1"
CHAT_URL = "http://127.0.0.1:8000/chat"


Case = Tuple[str, str, str, str | None, str | None]


def _assigned_pair() -> tuple[str, str]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT student_id, advisor_id
                FROM student_course_enrollments
                WHERE student_id IS NOT NULL AND advisor_id IS NOT NULL
                ORDER BY student_id, advisor_id
                LIMIT 1
                """
            )
            row = cur.fetchone() or {}
            return str(row.get("student_id") or ""), str(row.get("advisor_id") or "")
    finally:
        conn.close()


def _cases(student_id: str) -> Dict[str, List[Case]]:
    return {
        "admin": [
            ("population_casual", "student headcount pls", "mongodb_student_tool", "count", None),
            ("population_thai", "มหาวิทยาลัยมีนักศึกษาทั้งหมดกี่คน", "mongodb_student_tool", "count", None),
            ("exact_gpa_reordered", "how many got exactly 4 gpa", "mongodb_student_tool", "filter_summary", None),
            ("bottom_ranking_casual", "gimme 5 lowest gpa students", "mongodb_student_tool", "rank_students", None),
            ("program_average", "which major performs best by average gpa", "mongodb_student_tool", "group_students", None),
            ("course_average", "rank all courses based on mean score", "postgres_university_tool", "group_rank", "academic_analytics"),
            ("attendance_reordered", "attendance record of S001", "postgres_university_tool", "read", "student_academic_profile"),
            ("attendance_thai", "ดูข้อมูลการเข้าเรียน S001", "postgres_university_tool", "read", "student_academic_profile"),
            ("finance_casual", "how much tuition does S001 still owe", "postgres_university_tool", "read", "student_academic_profile"),
            ("assessment_result", "midterm result for S001", "postgres_university_tool", "read", "student_academic_profile"),
            ("law_major_median", "median GPA for law majors", "mongodb_student_tool", "study_term_aggregate", None),
            ("future_gpa_boundary", "what will S001 GPA be next semester", "none", None, None),
            ("causal_boundary", "why is S001 grade low", "none", None, None),
        ],
        "student": [
            ("profile_typo", "wht is my porfile", "mongodb_student_tool", "read_students", None),
            ("grade_typo", "my gard pls", "mongodb_student_tool", "read_students", None),
            ("grades_thai", "เกรดของฉัน", "mongodb_student_tool", "read_students", None),
            ("enrolled_classes", "which classes am I enrolled in", "postgres_university_tool", "list_subjects", "student_subjects"),
            ("course_membership", "do I take Academic Writing", "postgres_university_tool", "course_membership", "student_subjects"),
            ("attendance_typo", "show my attandance", "postgres_university_tool", "read", "student_academic_profile"),
            ("other_student_denied", "show S002 attendance", "none", None, None),
            ("population_list_denied", "list everyone", "none", None, None),
            ("prediction_denied", "predict my next gpa", "none", None, None),
        ],
        "advisor": [
            ("assigned_grade", f"show {student_id} grade in my class", "postgres_university_tool", "class_records", "advisor_classroom"),
            ("assigned_attendance_typo", f"attandance of {student_id}", "postgres_university_tool", "class_records", "advisor_classroom"),
            ("class_attendance_summary", "average attendance in my classes", "postgres_university_tool", "class_summary", "advisor_classroom"),
            ("class_roster", "who is in Business English class", "postgres_university_tool", "class_roster", "advisor_classroom"),
            ("gpa_denied", f"show {student_id} gpa", "none", None, None),
            ("finance_denied", f"show {student_id} tuition", "none", None, None),
        ],
    }


def _cleanup_session(headers: Dict[str, str], role: str, session_id: str, advisor_id: str) -> None:
    if not session_id:
        return
    params = {
        "user_role": role,
        "requester_student_id": "S001" if role == "student" else "",
        "requester_advisor_id": advisor_id if role == "advisor" else "",
    }
    try:
        requests.delete(
            f"{CHAT_URL}/sessions/{session_id}",
            headers=headers,
            params=params,
            timeout=15,
        )
    except requests.RequestException:
        # Cleanup failure must not hide the answer-path result. Operators can
        # inspect chat sessions separately if local networking is interrupted.
        pass


def run_random_question_gate() -> Dict[str, Any]:
    student_id, advisor_id = _assigned_pair()
    if not student_id or not advisor_id:
        return {
            "version": GATE_VERSION,
            "success": False,
            "summary": {"total": 0, "passed": 0, "failed": 1},
            "problems": ["No advisor/student enrollment pair exists in the normalized dataset."],
        }

    subjects = {"admin": "ADMIN", "student": "S001", "advisor": advisor_id}
    reports: List[Dict[str, Any]] = []
    for role, role_cases in _cases(student_id).items():
        token, _ = issue_access_token(role, subjects[role])
        headers = {"Authorization": f"Bearer {token}"}
        session_id = ""
        try:
            for case_id, message, expected_tool, expected_operation, expected_query_type in role_cases:
                response = requests.post(
                    CHAT_URL,
                    headers=headers,
                    json={
                        "message": message,
                        "language": "th" if any("ก" <= char <= "๛" for char in message) else "en",
                        "user_role": role,
                        "session_id": session_id or None,
                    },
                    timeout=45,
                )
                payload = response.json() if response.content else {}
                session_id = str(payload.get("session_id") or session_id)
                arguments = payload.get("tool_arguments") if isinstance(payload.get("tool_arguments"), dict) else {}
                validation = (
                    (payload.get("debug_trace") or {}).get("validation")
                    if isinstance(payload.get("debug_trace"), dict)
                    else {}
                ) or {}
                actual_tool = payload.get("selected_tool")
                actual_operation = arguments.get("operation")
                actual_query_type = arguments.get("query_type")
                passed = bool(
                    response.ok
                    and payload.get("ai_response")
                    and actual_tool == expected_tool
                    and (expected_operation is None or actual_operation == expected_operation)
                    and (expected_query_type is None or actual_query_type == expected_query_type)
                    and validation.get("is_valid") is not False
                )
                reports.append({
                    "case_id": case_id,
                    "role": role,
                    "passed": passed,
                    "http_status": response.status_code,
                    "tool": actual_tool,
                    "operation": actual_operation,
                    "query_type": actual_query_type,
                    "validated": validation.get("is_valid") is True,
                })
        finally:
            _cleanup_session(headers, role, session_id, advisor_id)

    passed = sum(1 for case in reports if case["passed"])
    return {
        "version": GATE_VERSION,
        "success": passed == len(reports),
        "summary": {"total": len(reports), "passed": passed, "failed": len(reports) - passed},
        "privacy": "No question text, answer text, tokens, names, grades, attendance values, or balances are printed.",
        "cases": reports,
    }


if __name__ == "__main__":
    report = run_random_question_gate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["success"] else 1)
