"""Regression tests for the normalized academic-record brain path."""

from pathlib import Path
import importlib.util
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.academic_query import parse_academic_query
from app.agent.analytics_query import parse_database_analytics_query
from app.agent.advisor_class_query import parse_advisor_class_query
from app.agent.agent_orchestrator import plan_turn
from app.agent.aggregate_query import parse_student_ranking_query
from app.agent.contextual_tool_planner import plan_from_purpose
from app.agent.final_answer_writer import deterministic_database_answer
from app.agent.purpose_contract import apply_contract_to_purpose
from app.agent.result_validator import validate_tool_result
from app.agent.schema_registry import AUTHORITATIVE_DATA_SOURCES
from app.agent.tool_planner import deterministic_plan


def _load_policy():
    path = ROOT / "mcp_server" / "app" / "policy.py"
    spec = importlib.util.spec_from_file_location("v30_academic_policy", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _purpose(message: str):
    return apply_contract_to_purpose(message, {
        "source": "test",
        "target_domain": "normal_chat",
        "answer_intent": "read",
        "should_use_database": False,
        "confidence": 1.0,
        "explicit_entities": {},
    })


def test_source_of_truth_map_separates_master_and_operational_facts():
    assert AUTHORITATIVE_DATA_SOURCES["student_master"]["tool"] == "mongodb_student_tool"
    academic = AUTHORITATIVE_DATA_SOURCES["academic_operations"]
    assert academic["tool"] == "postgres_university_tool"
    assert "attendance" in academic["facts"]
    assert "finance" in academic["facts"]


def test_academic_parser_covers_all_normalized_domains():
    cases = {
        "S001 attendance": ("student_academic_profile", "attendance"),
        "S001 registered courses": ("student_academic_profile", "enrollments"),
        "S001 midterm score": ("student_academic_profile", "assessments"),
        "S001 tuition balance": ("student_academic_profile", "finance"),
        "my scholarship": ("student_academic_profile", "scholarship"),
        "S001 academic risk": ("student_academic_profile", "academic_risk"),
        "academic risk summary": ("academic_risk_summary", "academic_risk_summary"),
        "show course catalog": ("course_catalog", "course_catalog"),
        "S001 graduation progress": ("student_academic_profile", "graduation_progress"),
        "ดูการเข้าเรียนของ S001": ("student_academic_profile", "attendance"),
    }
    for message, expected in cases.items():
        parsed = parse_academic_query(message)
        assert parsed is not None, message
        assert (parsed["query_type"], parsed["answer_style"]) == expected


def test_profile_and_grade_questions_stay_on_mongo_master_data():
    for message in ("S001 profile", "S001 GPA", "S001 grades"):
        plan = deterministic_plan(message, "en", "admin")
        assert plan["tool_name"] == "mongodb_student_tool"


def test_contextual_planner_routes_attendance_before_generic_student_id():
    message = "show S001 attendance"
    plan = plan_from_purpose(
        message=message,
        language="en",
        user_role="admin",
        purpose=_purpose(message),
    )
    assert plan["tool_name"] == "postgres_university_tool"
    assert plan["arguments"]["query_type"] == "student_academic_profile"
    assert plan["arguments"]["student_id"] == "S001"
    assert plan["arguments"]["requested_sections"] == ["attendance"]
    assert plan["arguments"]["answer_style"] == "attendance"


def test_student_self_finance_refuses_another_message_id():
    plan = deterministic_plan(
        "show S999 tuition balance",
        "en",
        "student",
        requester_student_id="S001",
    )
    assert plan["tool_name"] == "none"
    assert plan["arguments"]["reason"] == "student_other_record_denied"


def test_role_policy_denies_advisor_finance_and_unknown_worker_operation():
    policy = _load_policy()
    advisor_finance = policy.check_pdpa_policy(
        "postgres_university_tool",
        {"query_type": "student_academic_profile", "requested_sections": ["financial_accounts"]},
        "advisor",
        requester_advisor_id="A001",
    )
    unknown_worker = policy.check_pdpa_policy(
        "database_worker_tool",
        {"operation": "future_unreviewed_operation"},
        "admin",
    )
    student_finance = policy.check_pdpa_policy(
        "postgres_university_tool",
        {"query_type": "student_academic_profile", "requested_sections": ["financial_accounts"]},
        "student",
        requester_student_id="S001",
    )
    assert advisor_finance["allowed"] is False
    assert unknown_worker["allowed"] is False
    assert student_finance["allowed"] is True


def test_advisor_postgres_projection_does_not_select_gpa():
    source = (ROOT / "mcp_server" / "app" / "tools" / "postgres_tool.py").read_text()
    advisor_projection = source[
        source.index("# A fallback advisor profile exposes identity only"):
        source.index("profile = cur.fetchone()")
    ]
    advisor_select = advisor_projection[advisor_projection.index("SELECT student_id"):]
    assert " gpa" not in advisor_select.lower()
    assert "scholarship_status" not in advisor_select


def test_attendance_result_is_validated_and_formatted_as_attendance():
    message = "show S001 attendance"
    plan = deterministic_plan(message, "en", "admin")
    result = {
        "success": True,
        "data": {
            "type": "student_academic_profile",
            "student_id": "S001",
            "profile": {"student_id": "S001", "full_name": "Demo Student"},
            "attendance": [{
                "student_id": "S001",
                "course_code": "CS101",
                "term_code": "2026-1",
                "advisor_id": "A001",
                "attendance_rate": 92.5,
                "classes_attended": 37,
                "classes_scheduled": 40,
            }],
        },
    }
    validation = validate_tool_result(message, plan, result)
    answer = deterministic_database_answer(message, "en", plan, result)
    assert validation["is_valid"] is True, validation
    assert "Attendance for S001" in answer
    assert "92.5%" in answer
    assert "document" not in answer.lower()


def test_wrong_academic_payload_type_is_rejected():
    message = "show S001 attendance"
    plan = deterministic_plan(message, "en", "admin")
    wrong = {"success": True, "data": {"type": "course_catalog", "courses": []}}
    validation = validate_tool_result(message, plan, wrong)
    assert validation["is_valid"] is False
    assert any("must return type=student_academic_profile" in problem for problem in validation["problems"])


def test_screenshot_ranking_phrases_use_exact_dedicated_contract():
    cases = {
        "rank me top 5 students that have the best grade": ("desc", 5),
        "rank 5 student from gpa": ("desc", 5),
        "5 highest gpa": ("desc", 5),
        "bottom 5 students by gpa": ("asc", 5),
    }
    for message, (direction, top_n) in cases.items():
        parsed = parse_student_ranking_query(message)
        assert parsed is not None, message
        assert parsed["operation"] == "rank_students"
        assert parsed["direction"] == direction
        assert parsed["top_n"] == top_n
        plan = deterministic_plan(message, "en", "admin")
        assert plan["arguments"]["operation"] == "rank_students"
        assert plan["arguments"]["limit"] == top_n
        assert plan["arguments"]["answer_style"] == "student_rank"


def test_gpa_and_grades_are_returned_together():
    plan = deterministic_plan(
        "What is my GPA and grades?",
        "en",
        "student",
        requester_student_id="S001",
    )
    result = {
        "success": True,
        "data": {
            "student_id": "S001",
            "name": "Demo Student",
            "gpa": 3.75,
            "subject_grades": [{"subject": "Algorithms", "grade": "A"}],
        },
    }
    answer = deterministic_database_answer("What is my GPA and grades?", "en", plan, result)
    assert plan["arguments"]["answer_style"] == "student_multi"
    assert "GPA: 3.75" in answer
    assert "Algorithms: A" in answer


def test_grades_and_attendance_plan_keeps_both_sources():
    message = "show grades and attendance for S001"
    plan = deterministic_plan(message, "en", "admin")
    assert plan["tool_name"] == "postgres_university_tool"
    assert plan["arguments"]["answer_style"] == "academic_multi"
    assert plan["arguments"]["requested_sections"] == ["attendance"]
    assert plan["arguments"]["student_master_sections"] == ["grades"]
    assert plan["arguments"]["include_student_master"] is True


def test_combined_student_record_formats_every_requested_section():
    message = "show grades and attendance for S001"
    plan = deterministic_plan(message, "en", "admin")
    result = {
        "success": True,
        "data": {
            "type": "student_combined_record",
            "student_id": "S001",
            "student_master_sections": ["grades"],
            "student_master": {
                "student_id": "S001",
                "name": "Demo Student",
                "subject_grades": [{"subject": "Algorithms", "grade": "A"}],
            },
            "requested_sections": ["attendance"],
            "requested_section_styles": {"attendance": "attendance"},
            "academic": {
                "type": "student_academic_profile",
                "student_id": "S001",
                "profile": {"student_id": "S001", "full_name": "Demo Student"},
                "attendance": [{
                    "course_code": "CS101",
                    "term_code": "2026-1",
                    "attendance_rate": 92.5,
                    "classes_attended": 37,
                    "classes_scheduled": 40,
                }],
            },
            "denied_sections": [],
        },
    }
    answer = deterministic_database_answer(message, "en", plan, result)
    assert "Algorithms: A" in answer
    assert "Attendance for S001" in answer
    assert "92.5%" in answer


def test_random_course_performance_paraphrases_share_one_contract():
    messages = [
        "which subject have the greatest summary grade",
        "which course has the highest average grade",
        "show the best class by performance",
        "rank courses by score",
    ]
    for message in messages:
        parsed = parse_database_analytics_query(message)
        assert parsed is not None, message
        assert parsed["source"] == "postgres"
        assert parsed["dimension"] == "course"
        assert parsed["measure"] == "average_score"


def test_random_population_and_leaderboard_paraphrases_do_not_dump_records():
    count_messages = [
        "how large is the student body",
        "total learners",
        "student headcount",
    ]
    for message in count_messages:
        plan = deterministic_plan(message, "en", "admin")
        assert plan["arguments"]["operation"] == "count", message
    rank_messages = [
        "show the ten best academic performers",
        "leaderboard of 7 learners",
        "top 3 pupils",
    ]
    for message in rank_messages:
        plan = deterministic_plan(message, "en", "admin")
        assert plan["arguments"]["operation"] == "rank_students", message


def test_group_analytics_and_admin_student_benchmark_pass_specific_validation():
    group_message = "average GPA by program"
    group_plan = deterministic_plan(group_message, "en", "admin")
    group_result = {
        "success": True,
        "data": {
            "type": "group_analytics",
            "source": "mongodb_students",
            "dimension": "program",
            "measure": "average_gpa",
            "direction": "desc",
            "groups": [{"group": "Computer Science", "value": 3.2, "student_count": 20}],
        },
    }
    assert validate_tool_result(group_message, group_plan, group_result)["is_valid"] is True

    benchmark_message = "compare S001 GPA against the university average"
    benchmark_plan = deterministic_plan(
        benchmark_message,
        "en",
        "admin",
    )
    benchmark_result = {
        "success": True,
        "data": {
            "type": "student_benchmark",
            "student": {"student_id": "S001", "name": "Demo", "gpa": 3.2},
            "measure": "gpa",
            "population_average": 3.0,
            "population_count": 100,
            "difference": 0.2,
        },
    }
    assert validate_tool_result(benchmark_message, benchmark_plan, benchmark_result)["is_valid"] is True


def test_student_random_questions_are_guarded_to_own_record_and_enrolled_courses():
    denied_messages = [
        "show S002 profile",
        "compare S001 and S002 grades",
        "list all students",
        "how many students are in the university",
        "how many students study Business English",
        "average GPA by program",
        "show at-risk students",
        "compare my GPA against the university average",
        "show advisor A001",
    ]
    for message in denied_messages:
        plan = deterministic_plan(
            message,
            "en",
            "student",
            requester_student_id="S001",
        )
        assert plan["tool_name"] == "none", message
        assert plan["arguments"]["reason"] in {
            "student_other_record_denied",
            "student_own_scope_only",
        }, message

    own_messages = [
        "show my profile",
        "show my GPA and grades",
        "show my attendance",
        "show my enrolled courses",
        "show my assessment results",
        "show my tuition balance",
        "show my scholarships",
        "which of my subjects has the best grade",
        "list my course files",
    ]
    for message in own_messages:
        plan = deterministic_plan(
            message,
            "en",
            "student",
            requester_student_id="S001",
        )
        assert plan["tool_name"] != "none", message


def test_student_course_membership_and_list_use_only_signed_student_subjects():
    membership = deterministic_plan(
        "do I study Business English?",
        "en",
        "student",
        requester_student_id="S001",
    )
    assert membership["tool_name"] == "postgres_university_tool"
    assert membership["arguments"]["student_id"] == "S001"
    assert membership["arguments"]["query_type"] == "student_subjects"
    assert membership["arguments"]["operation"] == "course_membership"
    assert membership["arguments"]["course_query"] == "Business English"
    assert membership["arguments"]["answer_style"] == "student_course_membership"

    subject_list = deterministic_plan(
        "which subjects do I study?",
        "en",
        "student",
        requester_student_id="S001",
    )
    assert subject_list["tool_name"] == "postgres_university_tool"
    assert subject_list["arguments"]["student_id"] == "S001"
    assert subject_list["arguments"]["query_type"] == "student_subjects"
    assert subject_list["arguments"]["operation"] == "list_subjects"
    assert subject_list["arguments"]["answer_style"] == "student_course_list"

    no_answer = deterministic_database_answer(
        "do I study Business English?",
        "en",
        membership,
        {
            "success": True,
            "data": {
                "type": "student_subjects",
                "student_id": "S001",
                "operation": "course_membership",
                "course_query": "Business English",
                "subjects": [],
                "match_count": 0,
                "total_count": 8,
            },
        },
    )
    assert no_answer == "No. Business English is not in the subjects assigned to your account."
    validation = validate_tool_result(
        "do I study Business English?",
        membership,
        {
            "success": True,
            "data": {
                "type": "student_subjects",
                "student_id": "S001",
                "operation": "course_membership",
                "course_query": "Business English",
                "subjects": [],
                "match_count": 0,
                "total_count": 8,
            },
        },
    )
    assert validation["is_valid"] is True


def test_followup_comparison_inherits_student_and_previous_database_topic():
    history = [
        {"role": "user", "content": "show S001 profile"},
        {"role": "assistant", "content": "Student profile for S001"},
        {"role": "user", "content": "and tuition?"},
        {"role": "assistant", "content": "Financial account for S001"},
    ]
    plan = plan_turn(
        message="compare that with S002",
        language="en",
        user_role="admin",
        chat_history=history,
    )
    assert plan["tool_name"] == "postgres_university_tool"
    assert plan["arguments"]["student_ids"] == ["S001", "S002"]
    assert plan["arguments"]["requested_sections"] == ["financial_accounts"]
    result = {
        "success": True,
        "data": {
            "type": "student_academic_profiles",
            "requested_sections": ["financial_accounts"],
            "records": [
                {
                    "type": "student_academic_profile",
                    "student_id": student_id,
                    "profile": {"student_id": student_id, "full_name": student_id},
                    "financial_accounts": [],
                }
                for student_id in ["S001", "S002"]
            ],
        },
    }
    validation = validate_tool_result("compare that with S002", plan, result)
    assert validation["is_valid"] is True, validation


def test_missing_future_or_causal_data_returns_explicit_no_tool_boundary():
    cases = {
        "predict which students will fail next term": "unsupported_prediction",
        "what course should S001 take next": "unsupported_prerequisites",
        "why is S001 at risk": "unsupported_causal_explanation",
    }
    for message, reason in cases.items():
        plan = deterministic_plan(message, "en", "admin")
        assert plan["tool_name"] == "none"
        assert plan["arguments"]["reason"] == reason
        assert plan["arguments"]["answer_style"] == "capability_limitation"


def test_advisor_screenshot_questions_use_signed_classroom_database():
    cases = {
        "how many student are there learn academic writing": "Academic Writing",
        "how many student are there learn business english": "Business English",
        "count learners studying Business English": "Business English",
    }
    for message, course in cases.items():
        parsed = parse_advisor_class_query(message)
        assert parsed is not None, message
        assert parsed["operation"] == "class_count"
        assert parsed["course_query"].lower() == course.lower()
        plan = deterministic_plan(
            message,
            "en",
            "advisor",
            requester_advisor_id="A001",
        )
        assert plan["tool_name"] == "postgres_university_tool"
        assert plan["arguments"]["query_type"] == "advisor_classroom"
        assert plan["arguments"]["operation"] == "class_count"
        assert plan["requester_advisor_id"] == "A001"


def test_advisor_student_questions_never_plan_broad_mongo_or_profile_reads():
    allowed = deterministic_plan(
        "show S001 grades and attendance",
        "en",
        "advisor",
        requester_advisor_id="A001",
    )
    assert allowed["tool_name"] == "postgres_university_tool"
    assert allowed["arguments"]["query_type"] == "advisor_classroom"
    assert allowed["arguments"]["student_ids"] == ["S001"]
    assert set(allowed["arguments"]["requested_metrics"]) == {"grade", "attendance"}

    for message in ["show S001 GPA", "show S001 full profile", "show S001 tuition balance"]:
        denied = deterministic_plan(
            message,
            "en",
            "advisor",
            requester_advisor_id="A001",
        )
        assert denied["tool_name"] == "none", message
        assert denied["arguments"]["reason"] == "advisor_classroom_scope_only"


def test_advisor_classroom_payload_formats_only_same_class_facts():
    message = "show S001 grade"
    plan = deterministic_plan(
        message,
        "en",
        "advisor",
        requester_advisor_id="A001",
    )
    result = {
        "success": True,
        "data": {
            "type": "advisor_classroom",
            "status": "ok",
            "advisor_id": "A001",
            "operation": "class_records",
            "scope": "signed_advisor_same_course_only",
            "requested_student_ids": ["S001"],
            "requested_metrics": ["grade"],
            "student_count": 1,
            "rows": [{
                "student_id": "S001",
                "full_name": "Demo Student",
                "course_code": "CS302",
                "course_name": "Software Engineering",
                "grade": "A",
                "score": 91.5,
            }],
        },
    }
    validation = validate_tool_result(message, plan, result)
    answer = deterministic_database_answer(message, "en", plan, result)
    assert validation["is_valid"] is True, validation
    assert "Software Engineering" in answer
    assert "grade A" in answer
    assert "GPA" not in answer
    assert "program" not in answer.lower()


def test_advisor_classroom_validator_rejects_another_advisor_payload():
    message = "show S001 grade"
    plan = deterministic_plan(
        message,
        "en",
        "advisor",
        requester_advisor_id="A001",
    )
    wrong = {
        "success": True,
        "data": {
            "type": "advisor_classroom",
            "status": "ok",
            "advisor_id": "A002",
            "scope": "signed_advisor_same_course_only",
            "rows": [{"student_id": "S001"}],
        },
    }
    validation = validate_tool_result(message, plan, wrong)
    assert validation["is_valid"] is False
    assert any("signed advisor" in problem.lower() for problem in validation["problems"])


def test_advisor_summary_formats_only_the_requested_class_metric():
    message = "what is the average attendance of students I teach"
    plan = deterministic_plan(
        message,
        "en",
        "advisor",
        requester_advisor_id="A001",
    )
    result = {
        "success": True,
        "data": {
            "type": "advisor_classroom",
            "status": "ok",
            "advisor_id": "A001",
            "operation": "class_summary",
            "scope": "signed_advisor_same_course_only",
            "requested_metrics": ["attendance"],
            "summaries": [{
                "course_code": "CS302",
                "course_name": "Software Engineering",
                "student_count": 42,
                "average_score": 73.4,
                "average_attendance": 87.66,
            }],
        },
    }
    answer = deterministic_database_answer(message, "en", plan, result)
    assert "average attendance 87.66%" in answer
    assert "average score" not in answer
