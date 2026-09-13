#!/usr/bin/env python3
"""Read-only live release matrix for Admin, Advisor, Lecturer, and Student.

The script intentionally sends forged browser role/owner fields with every chat
request. A passing result proves the backend replaces those values with signed
token claims before planning or database access.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import requests


BASE = os.getenv("V30_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def _login(role: str, user_id: str, password: str) -> Dict[str, Any]:
    response = requests.post(
        f"{BASE}/login",
        json={"role": role, "user_id": user_id, "password": password},
        timeout=30,
    )
    response.raise_for_status()
    account = response.json()
    assert account.get("role") == role, account
    return account


def _headers(account: Dict[str, Any]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {account['access_token']}"}


def _chat(account: Dict[str, Any], message: str) -> Dict[str, Any]:
    response = requests.post(
        f"{BASE}/chat",
        headers=_headers(account),
        json={
            "message": message,
            "language": "en",
            "user_role": "admin",
            "requester_student_id": "S999",
            "requester_advisor_id": "A999",
            "requester_lecturer_id": "L999",
            "session_id": account["session_id"],
        },
        timeout=90,
    )
    response.raise_for_status()
    return response.json()


def _assert_forbidden_routes(account: Dict[str, Any], own_role: str) -> Dict[str, int]:
    routes = {
        "admin": "/admin/account/me",
        "advisor": "/advisor/subjects",
        "lecturer": "/lecturer/subjects",
        "student": "/student/subjects",
    }
    statuses: Dict[str, int] = {}
    for role, path in routes.items():
        if role == own_role:
            continue
        status = requests.get(f"{BASE}{path}", headers=_headers(account), timeout=30).status_code
        assert status == 403, (own_role, role, status)
        statuses[role] = status
    return statuses


def _assert_document_plan(account: Dict[str, Any], expected_query_type: str) -> None:
    result = _chat(account, "list uploaded course files")
    assert result.get("selected_tool") == "postgres_university_tool", result
    assert (result.get("tool_arguments") or {}).get("query_type") == expected_query_type, result


def main() -> int:
    demo_password = os.getenv("V30_DEMO_PASSWORD", "demo1234")
    admin_password = os.getenv("V30_RELEASE_ADMIN_PASSWORD") or os.getenv("ADMIN_BOOTSTRAP_PASSWORD")
    if not admin_password:
        raise RuntimeError(
            "Set V30_RELEASE_ADMIN_PASSWORD to the current Administrator password before running the live release matrix."
        )

    accounts = {
        "admin": _login("admin", os.getenv("V30_RELEASE_ADMIN_USERNAME", os.getenv("ADMIN_BOOTSTRAP_USERNAME", "ADMIN")), admin_password),
        "advisor": _login("advisor", "A001", demo_password),
        "lecturer": _login("lecturer", "L001", demo_password),
        "student": _login("student", "S001", demo_password),
    }

    admin = accounts["admin"]
    admin_count = _chat(admin, "how many students are in the university?")
    assert admin_count.get("selected_tool") == "mongodb_student_tool", admin_count
    assert str((admin_count.get("tool_arguments") or {}).get("operation")) == "count", admin_count
    _assert_document_plan(admin, "all_documents")

    advisor = accounts["advisor"]
    advisor_allowed = _chat(advisor, "show students I teach")
    assert advisor_allowed.get("selected_tool") == "postgres_university_tool", advisor_allowed
    assert (advisor_allowed.get("tool_arguments") or {}).get("query_type") == "advisor_classroom", advisor_allowed
    advisor_denied = _chat(advisor, "rank all university students by GPA")
    assert advisor_denied.get("selected_tool") == "none", advisor_denied
    _assert_document_plan(advisor, "advisor_documents")

    lecturer = accounts["lecturer"]
    lecturer_allowed = _chat(lecturer, "list my assigned classes")
    assert lecturer_allowed.get("selected_tool") == "postgres_university_tool", lecturer_allowed
    assert (lecturer_allowed.get("tool_arguments") or {}).get("query_type") == "advisor_classroom", lecturer_allowed
    lecturer_denied = _chat(lecturer, "show tuition balances for students in my class")
    assert lecturer_denied.get("selected_tool") == "none", lecturer_denied
    _assert_document_plan(lecturer, "lecturer_documents")

    student = accounts["student"]
    student_allowed = _chat(student, "what is my GPA?")
    assert student_allowed.get("selected_tool") == "mongodb_student_tool", student_allowed
    assert (student_allowed.get("tool_arguments") or {}).get("student_id") == "S001", student_allowed
    student_denied = _chat(student, "show S002 profile")
    assert student_denied.get("selected_tool") == "none", student_denied
    _assert_document_plan(student, "course_documents")

    route_boundaries = {
        role: _assert_forbidden_routes(account, role)
        for role, account in accounts.items()
    }

    health = requests.post(
        f"{BASE}/admin/system-check/run",
        headers=_headers(admin),
        timeout=120,
    )
    health.raise_for_status()
    health_payload = health.json()
    assert health_payload.get("success") is True, health_payload
    assert health_payload.get("summary") == {"passed": 5, "total": 5}, health_payload

    print(json.dumps({
        "success": True,
        "roles_passed": ["admin", "advisor", "lecturer", "student"],
        "signed_identity_overrode_forged_browser_values": True,
        "document_query_types": {
            "admin": "all_documents",
            "advisor": "advisor_documents",
            "lecturer": "lecturer_documents",
            "student": "course_documents",
        },
        "cross_role_route_boundaries": route_boundaries,
        "automatic_system_check": health_payload.get("summary"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
