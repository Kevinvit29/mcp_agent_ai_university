"""Regression coverage for Student self-only enrollment authorization."""

import inspect

from app.agent.final_answer_writer import _format_students
from app.agent.student_scope import enforce_student_scope_plan
from app.db import postgres as backend_postgres


def test_student_subject_list_uses_current_enrollments_not_legacy_links():
    source = inspect.getsource(backend_postgres.list_student_subjects)
    assert "FROM student_course_enrollments" in source
    assert "FROM student_subjects" not in source


def test_student_document_access_uses_current_enrollments_not_legacy_links():
    for function in (
        backend_postgres.list_student_accessible_documents,
        backend_postgres.get_student_accessible_document,
    ):
        source = inspect.getsource(function)
        assert "student_course_enrollments" in source
        assert "JOIN student_subjects" not in source


def test_student_grade_answer_includes_score_without_internal_advisor_id():
    answer = _format_students(
        {
            "student_id": "S001",
            "name": "Demo Student",
            "subject_grades": [{
                "subject": "Database Systems",
                "grade": "A",
                "score": 91.5,
                "advisor_id": "A999",
            }],
        },
        "grades",
        False,
    )
    assert "grade A, score 91.5" in answer
    assert "A999" not in answer


def test_student_scope_blocks_a_future_cross_student_plan_before_execution():
    guarded = enforce_student_scope_plan(
        {
            "tool_name": "postgres_university_tool",
            "arguments": {
                "query_type": "student_academic_profile",
                "student_id": "S002",
                "original_question": "show S002 attendance",
            },
        },
        message="show S002 attendance",
        user_role="student",
        requester_student_id="S001",
    )
    assert guarded["tool_name"] == "none"
    assert guarded["arguments"]["reason"] == "student_other_record_denied"
