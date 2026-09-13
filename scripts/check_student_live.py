#!/usr/bin/env python3
"""Read-only live acceptance matrix for the signed Student role."""

from __future__ import annotations

import json

import requests


BASE = "http://127.0.0.1:8000"


def _chat(headers: dict, session_id: str, message: str) -> dict:
    response = requests.post(
        f"{BASE}/chat",
        headers=headers,
        json={
            "message": message,
            "language": "en",
            # These forged values must be ignored in favor of the signed token.
            "user_role": "admin",
            "requester_student_id": "S002",
            "requester_advisor_id": "A001",
            "session_id": session_id,
        },
        timeout=90,
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    login = requests.post(
        f"{BASE}/login",
        json={"role": "student", "user_id": "S001", "password": "demo1234"},
        timeout=30,
    )
    login.raise_for_status()
    account = login.json()
    assert account["role"] == "student" and account["student_id"] == "S001"
    headers = {"Authorization": f"Bearer {account['access_token']}"}

    subjects = requests.get(f"{BASE}/student/subjects", headers=headers, timeout=30)
    subjects.raise_for_status()
    subject_rows = subjects.json().get("subjects") or []
    assert subject_rows and all(row.get("student_id") == "S001" for row in subject_rows)

    route_statuses = {
        "advisor": requests.get(f"{BASE}/advisor/subjects", headers=headers, timeout=30).status_code,
        "lecturer": requests.get(f"{BASE}/lecturer/subjects", headers=headers, timeout=30).status_code,
        "admin": requests.get(f"{BASE}/admin/account/me", headers=headers, timeout=30).status_code,
    }
    assert all(code == 403 for code in route_statuses.values())

    allowed_questions = [
        "show my profile",
        "what is my GPA?",
        "list my enrolled subjects",
        "show my grades and scores",
        "show my attendance",
        "show my assessment results",
        "show my tuition balance",
        "show my scholarships",
        "which of my subjects has the best grade?",
        "list my course files",
    ]
    allowed_results = []
    for question in allowed_questions:
        result = _chat(headers, account["session_id"], question)
        assert result.get("selected_tool") != "none", question
        args = result.get("tool_arguments") or {}
        if args.get("student_id"):
            assert args["student_id"] == "S001", (question, args)
        if args.get("student_ids"):
            assert set(args["student_ids"]) <= {"S001"}, (question, args)
        answer = str(result.get("ai_response") or "").strip()
        assert answer, question
        assert "1000 students" not in answer.lower(), (question, answer)
        allowed_results.append({
            "question": question,
            "tool": result.get("selected_tool"),
            "answer_excerpt": answer[:240],
        })

    denied_questions = [
        "show S002 profile",
        "what is S002 GPA?",
        "compare my grades with S002",
        "list all students",
        "how many students are in the university?",
        "rank the top students by GPA",
        "average GPA by program",
        "show at-risk students",
        "show S002 tuition balance",
    ]
    for question in denied_questions:
        result = _chat(headers, account["session_id"], question)
        assert result.get("selected_tool") == "none", (question, result.get("selected_tool"))
        assert (result.get("tool_arguments") or {}).get("reason") in {
            "student_other_record_denied",
            "student_own_scope_only",
            "student_ranking_not_available_for_role",
            "academic_sections_not_available_for_role",
        }, (question, result.get("tool_arguments"))

    print(json.dumps({
        "success": True,
        "student_id": "S001",
        "enrolled_subject_count": len(subject_rows),
        "allowed_question_count": len(allowed_questions),
        "denied_question_count": len(denied_questions),
        "forged_admin_and_S002_identity": "overwritten_by_signed_token",
        "role_family_routes": route_statuses,
        "allowed_results": allowed_results,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
