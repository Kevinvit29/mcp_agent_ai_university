"""Lecturer is a separate identity with course-only academic access."""

from app.agent.tool_planner import deterministic_plan
from app.demo_data import build_demo_dataset
from app.production_security import issue_access_token, verify_access_token


def test_lecturer_demo_accounts_are_separate_from_advisors():
    dataset = build_demo_dataset(20)
    lecturer = dataset["lecturers"][0]
    assert lecturer["lecturer_id"] == "L001"
    assert lecturer["advisor_scope_id"] == "A001"
    assert lecturer["lecturer_id"] != lecturer["advisor_scope_id"]
    assert lecturer["password_hash"].startswith("pbkdf2_sha256$")


def test_lecturer_token_signs_both_account_and_teaching_scope():
    token, issued = issue_access_token(
        "lecturer", "L001", scope_id="A001", now=1_000, ttl_seconds=900
    )
    identity = verify_access_token(token, now=1_100)
    assert issued.lecturer_id == "L001"
    assert identity.lecturer_id == "L001"
    assert identity.advisor_id == "A001"
    assert identity.public()["teaching_scope_id"] == "A001"


def test_lecturer_class_questions_use_signed_same_course_query():
    plan = deterministic_plan(
        "show S001 grade and attendance in my class",
        "en",
        "lecturer",
        None,
        "A001",
        [],
    )
    assert plan["user_role"] == "lecturer"
    assert plan["tool_name"] == "postgres_university_tool"
    assert plan["arguments"]["query_type"] == "advisor_classroom"
    assert plan["requester_advisor_id"] == "A001"
    assert plan["selected_agent"] == "lecturer_classroom_data_agent"


def test_lecturer_university_wide_gpa_is_denied_before_database_call():
    plan = deterministic_plan(
        "rank all students by university GPA",
        "en",
        "lecturer",
        None,
        "A001",
        [],
    )
    assert plan["tool_name"] == "none"
    assert plan["arguments"]["reason"] in {
        "advisor_classroom_scope_only",
        "academic_sections_not_available_for_role",
    }


def test_lecturer_finance_is_denied_before_database_call():
    plan = deterministic_plan(
        "show tuition balances for students in my class",
        "en",
        "lecturer",
        None,
        "A001",
        [],
    )
    assert plan["tool_name"] == "none"
    assert plan["arguments"]["reason"] in {
        "advisor_classroom_scope_only",
        "academic_sections_not_available_for_role",
    }


def test_lecturer_document_questions_use_dedicated_owner_store():
    plan = deterministic_plan(
        "list my course files",
        "en",
        "lecturer",
        None,
        "A001",
        [],
    )
    assert plan["tool_name"] == "postgres_university_tool"
    assert plan["arguments"]["query_type"] == "lecturer_documents"
    assert plan["role_prompt_name"] == "LECTURER_DOCUMENT_AGENT_PROMPT"


def test_lecturer_router_has_owned_upload_read_and_delete_routes():
    source = open("/app/backend/app/roles/lecturer/router.py", encoding="utf-8").read()
    assert 'router.post("/documents/upload")' in source
    assert 'router.get("/documents")' in source
    assert 'router.delete("/documents/{document_id}")' in source
    assert "save_lecturer_document" in source
    assert "identity.lecturer_id" in source
    assert "identity.advisor_id" in source
