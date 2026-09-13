#!/usr/bin/env python3
"""Live acceptance checks for isolated V30 Lecturer course materials."""

from __future__ import annotations

import json
import sys

import requests


BASE = "http://127.0.0.1:8000"


def main() -> int:
    login = requests.post(
        f"{BASE}/login",
        json={"role": "lecturer", "user_id": "L001", "password": "demo1234"},
        timeout=30,
    )
    login.raise_for_status()
    account = login.json()
    assert account["role"] == "lecturer"
    assert account["lecturer_id"] == "L001"
    assert account["teaching_scope_id"] == "A001"
    headers = {"Authorization": f"Bearer {account['access_token']}"}

    subjects = requests.get(f"{BASE}/lecturer/subjects", headers=headers, timeout=30)
    subjects.raise_for_status()
    subject_rows = subjects.json().get("subjects") or []
    assert subject_rows
    assert all(row.get("lecturer_id") == "L001" for row in subject_rows)

    # Role-family routes must stay separated even if query/body values are forged.
    assert requests.get(f"{BASE}/advisor/subjects", headers=headers, timeout=30).status_code == 403
    assert requests.get(f"{BASE}/admin/account/me", headers=headers, timeout=30).status_code == 403

    allowed = requests.post(
        f"{BASE}/chat",
        headers=headers,
        json={
            "message": "list my assigned classes",
            "language": "en",
            "user_role": "admin",
            "requester_advisor_id": "A002",
            "session_id": account["session_id"],
        },
        timeout=60,
    )
    allowed.raise_for_status()
    allowed_data = allowed.json()
    assert allowed_data["selected_tool"] == "postgres_university_tool"
    assert allowed_data["selected_agent"] == "lecturer_classroom_data_agent"
    assert allowed_data["tool_arguments"]["query_type"] == "advisor_classroom"

    denied = requests.post(
        f"{BASE}/chat",
        headers=headers,
        json={
            "message": "rank all students by university GPA",
            "language": "en",
            "user_role": "admin",
            "requester_advisor_id": "A002",
            "session_id": account["session_id"],
        },
        timeout=60,
    )
    denied.raise_for_status()
    denied_data = denied.json()
    assert denied_data["selected_tool"] == "none"
    assert "cannot access" in str(denied_data.get("ai_response") or "").lower()

    # A Lecturer may create material only in an assigned class. This temporary
    # record is deleted in finally so the acceptance check leaves no demo data.
    denied_upload = requests.post(
        f"{BASE}/lecturer/documents/upload",
        headers=headers,
        data={"subject_code": "CALC", "storage_target": "postgres"},
        files={"file": ("forbidden.csv", b"topic,detail\ncalculus,forbidden", "text/csv")},
        timeout=60,
    )
    assert denied_upload.status_code == 403

    uploaded_id = None
    try:
        upload = requests.post(
            f"{BASE}/lecturer/documents/upload",
            headers=headers,
            data={"subject_code": "CS302", "storage_target": "postgres"},
            files={"file": ("lecturer-live-check.csv", b"topic,detail\nproject deadline,Friday 17:00", "text/csv")},
            timeout=60,
        )
        upload.raise_for_status()
        uploaded = upload.json()["document"]
        uploaded_id = int(uploaded["id"])
        assert uploaded["document_scope"] == "lecturer"
        assert uploaded["lecturer_id"] == "L001"
        assert uploaded["teaching_scope_id"] == "A001"

        lecturer_files = requests.get(f"{BASE}/lecturer/documents", headers=headers, timeout=30)
        lecturer_files.raise_for_status()
        assert any(int(row["id"]) == uploaded_id for row in lecturer_files.json().get("documents") or [])

        other_login = requests.post(
            f"{BASE}/login",
            json={"role": "lecturer", "user_id": "L002", "password": "demo1234"},
            timeout=30,
        )
        other_login.raise_for_status()
        other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
        assert requests.get(f"{BASE}/lecturer/documents/{uploaded_id}", headers=other_headers, timeout=30).status_code == 404

        student_login = requests.post(
            f"{BASE}/login",
            json={"role": "student", "user_id": "S001", "password": "demo1234"},
            timeout=30,
        )
        student_login.raise_for_status()
        student_account = student_login.json()
        student_headers = {"Authorization": f"Bearer {student_account['access_token']}"}
        student_files = requests.get(f"{BASE}/student/documents", headers=student_headers, timeout=30)
        student_files.raise_for_status()
        visible = [
            row for row in student_files.json().get("documents") or []
            if row.get("document_scope") == "lecturer" and int(row["id"]) == uploaded_id
        ]
        assert visible
        student_detail = requests.get(
            f"{BASE}/student/documents/{uploaded_id}?document_scope=lecturer",
            headers=student_headers,
            timeout=30,
        )
        student_detail.raise_for_status()

        pinned = requests.post(
            f"{BASE}/chat",
            headers=student_headers,
            json={
                "message": "What is the project deadline in this file?",
                "language": "en",
                "user_role": "admin",
                "requester_student_id": "S999",
                "document_id": uploaded_id,
                "document_scope": "lecturer",
                "session_id": student_account["session_id"],
            },
            timeout=90,
        )
        pinned.raise_for_status()
        pinned_data = pinned.json()
        assert pinned_data["selected_tool"] == "postgres_university_tool"
        assert pinned_data["tool_arguments"]["query_type"] == "course_documents"
        assert str(pinned_data.get("ai_response") or "").strip()
    finally:
        if uploaded_id is not None:
            cleanup = requests.delete(f"{BASE}/lecturer/documents/{uploaded_id}", headers=headers, timeout=30)
            assert cleanup.status_code == 200

    print(json.dumps({
        "success": True,
        "lecturer_id": "L001",
        "teaching_scope": "A001",
        "assigned_subject_count": len(subject_rows),
        "allowed_class_query": "passed",
        "forged_admin_and_A002_scope": "blocked",
        "advisor_route": "blocked",
        "admin_route": "blocked",
        "university_wide_gpa": "blocked_before_database",
        "assigned_course_upload": "passed_and_cleaned_up",
        "unassigned_course_upload": "blocked",
        "other_lecturer_access": "blocked",
        "enrolled_student_access": "passed",
        "student_pinned_file_answer": "passed",
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, indent=2))
        raise
