"""Regression tests for signed-role database scope at the MCP boundary."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


policy = _load_module("v30_mcp_policy", ROOT / "mcp_server" / "app" / "policy.py")
mongo_tool = _load_module("v30_mongo_tool", ROOT / "mcp_server" / "app" / "tools" / "mongo_tool.py")
access_scope_summary = policy.access_scope_summary
check_pdpa_policy = policy.check_pdpa_policy
minimize_requested_fields = policy.minimize_requested_fields
_role_scoped_student_query = mongo_tool._role_scoped_student_query
_student_study_term_search = mongo_tool._student_study_term_search
_student_study_term_aggregate = mongo_tool._student_study_term_aggregate


def test_student_cannot_request_another_student_record():
    result = check_pdpa_policy(
        "mongodb_student_tool",
        {"operation": "read_students", "student_id": "S999"},
        "student",
        requester_student_id="S001",
    )
    assert result["allowed"] is False


def test_advisor_mongo_student_reads_are_blocked_in_favor_of_classroom_query():
    result = check_pdpa_policy(
        "mongodb_student_tool",
        {"operation": "read_students", "student_id": "S001"},
        "advisor",
        requester_advisor_id="A001",
    )
    assert result["allowed"] is False
    assert "advisor_classroom" in result["reason"]


def test_student_scope_replaces_any_planner_student_id():
    query = _role_scoped_student_query(
        {"student_id": "S999"},
        user_role="student",
        requester_student_id="S001",
    )
    assert query["student_id"] == "S001"


def test_non_admin_database_schema_and_unknown_postgres_queries_are_denied():
    schema = check_pdpa_policy(
        "postgres_university_tool",
        {"query_type": "database_map"},
        "advisor",
        requester_advisor_id="A001",
    )
    unknown = check_pdpa_policy(
        "postgres_university_tool",
        {"query_type": "future_unreviewed_operation"},
        "student",
        requester_student_id="S001",
    )
    assert schema["allowed"] is False
    assert unknown["allowed"] is False


def test_advisor_classroom_policy_and_scope_are_explicit():
    result = check_pdpa_policy(
        "postgres_university_tool",
        {"query_type": "advisor_classroom", "operation": "class_records"},
        "advisor",
        requester_advisor_id="A001",
    )
    assert result["allowed"] is True
    assert access_scope_summary("postgres_university_tool", "advisor")["scope"] == "assigned_classes_same_course_records"


def test_student_mongo_policy_allows_own_reads_but_denies_population_operations():
    own = check_pdpa_policy(
        "mongodb_student_tool",
        {"operation": "read_students", "student_id": "S001"},
        "student",
        requester_student_id="S001",
    )
    assert own["allowed"] is True

    for operation in {
        "count",
        "list_names",
        "rank_students",
        "group_students",
        "compare_student_to_population",
        "student_population_aggregate",
        "future_operation",
    }:
        result = check_pdpa_policy(
            "mongodb_student_tool",
            {"operation": operation, "student_id": "S001"},
            "student",
            requester_student_id="S001",
        )
        assert result["allowed"] is False, operation


def test_student_postgres_analytics_are_limited_to_own_course_facts():
    allowed = check_pdpa_policy(
        "postgres_university_tool",
        {
            "query_type": "academic_analytics",
            "dimension": "course",
            "measure": "average_score",
            "student_ids": ["S001"],
        },
        "student",
        requester_student_id="S001",
    )
    assert allowed["allowed"] is True

    denied_cases = [
        {"dimension": "student", "measure": "average_score"},
        {"dimension": "program", "measure": "student_count"},
        {"dimension": "course", "measure": "risk_level"},
        {"dimension": "course", "measure": "average_score", "student_ids": ["S002"]},
    ]
    for arguments in denied_cases:
        result = check_pdpa_policy(
            "postgres_university_tool",
            {"query_type": "academic_analytics", **arguments},
            "student",
            requester_student_id="S001",
        )
        assert result["allowed"] is False, arguments


def test_student_subject_graph_query_requires_signed_student_role():
    allowed = check_pdpa_policy(
        "postgres_university_tool",
        {"query_type": "student_subjects", "operation": "list_subjects"},
        "student",
        requester_student_id="S001",
    )
    advisor = check_pdpa_policy(
        "postgres_university_tool",
        {"query_type": "student_subjects", "operation": "list_subjects"},
        "advisor",
        requester_advisor_id="A001",
    )
    assert allowed["allowed"] is True
    assert advisor["allowed"] is False


def test_student_cannot_use_legacy_global_spreadsheet_or_direct_file_tools():
    legacy_excel = check_pdpa_policy(
        "excel_tool",
        {"operation": "legacy_student_scores"},
        "student",
        requester_student_id="S001",
    )
    enrolled_excel = check_pdpa_policy(
        "excel_tool",
        {"operation": "list_uploaded_excel"},
        "student",
        requester_student_id="S001",
    )
    direct_pdf = check_pdpa_policy(
        "pdf_tool",
        {"query": "show policy"},
        "student",
        requester_student_id="S001",
    )
    assert legacy_excel["allowed"] is False
    assert enrolled_excel["allowed"] is True
    assert direct_pdf["allowed"] is False


class _Cursor(list):
    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        return _Cursor(self[:value])


class _CapturingCollection:
    def __init__(self):
        self.queries = []

    def find(self, query, *_args, **_kwargs):
        self.queries.append(dict(query))
        return _Cursor([])


def test_study_search_and_aggregate_pass_signed_student_id_into_mongo_filter():
    collection = _CapturingCollection()
    _student_study_term_search(
        collection=collection,
        study_term="Business English",
        requested_fields=["student_id"],
        limit=20,
        display_limit=20,
        user_role="student",
        requester_student_id="S001",
    )
    _student_study_term_aggregate(
        collection=collection,
        study_term="Business English",
        statistic="count",
        metric_field="gpa",
        requested_fields=["student_id"],
        display_limit=20,
        user_role="student",
        requester_student_id="S001",
    )
    assert collection.queries == [
        {"student_id": "S001"},
        {"student_id": "S001"},
    ]
