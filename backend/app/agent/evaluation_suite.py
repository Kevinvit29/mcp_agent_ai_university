"""Deterministic regression evaluation for the University AI query contracts.

This module intentionally does not call Gemini or an external database.  It tests
whether the local query-understanding and validation layers select the right safe
operation before any real student data is queried.  This prevents regressions
when agent/planner files are changed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agent.aggregate_query import (
    parse_student_metric_query,
    parse_student_statistic_query,
    parse_student_study_query,
    parse_total_student_count_query,
    parse_subject_ranking_query,
    parse_student_ranking_query,
)
from app.agent.purpose_contract import apply_contract_to_purpose, build_latest_message_contract
from app.agent.contextual_tool_planner import plan_from_purpose
from app.agent.result_validator import validate_tool_result
from app.agent.academic_query import parse_academic_query
from app.agent.analytics_query import parse_database_analytics_query
from app.agent.advisor_class_query import parse_advisor_class_query
from app.agent.agent_orchestrator import plan_turn
from app.agent.student_own_query import parse_student_own_course_query
from app.agent.tool_planner import deterministic_plan


EVALUATION_VERSION = "V30_AUTHORITATIVE_CHAT_EVALUATION"
BENCHMARK_PATH = Path(__file__).with_name("evaluation_cases.json")

PARSERS = {
    "total_student_count": parse_total_student_count_query,
    "student_study": parse_student_study_query,
    "student_statistic": parse_student_statistic_query,
    "student_metric": parse_student_metric_query,
    "subject_ranking": parse_subject_ranking_query,
    "student_ranking": parse_student_ranking_query,
    "academic_query": parse_academic_query,
    "database_analytics": parse_database_analytics_query,
    "advisor_classroom": parse_advisor_class_query,
    "student_own_course": parse_student_own_course_query,
}


def load_benchmark_catalog() -> Dict[str, Any]:
    """Load the single version-controlled prompt catalog used by local gates."""
    with BENCHMARK_PATH.open("r", encoding="utf-8") as handle:
        catalog = json.load(handle)
    required_sections = ("parser_cases", "contract_cases", "planner_cases", "conversation_cases")
    if not all(isinstance(catalog.get(name), list) for name in required_sections):
        raise ValueError("V30 benchmark catalog is missing a required case section.")
    case_ids = [
        str(case.get("case_id") or "")
        for section in required_sections
        for case in catalog[section]
    ]
    if not all(case_ids) or len(case_ids) != len(set(case_ids)):
        raise ValueError("V30 benchmark case IDs must be present and unique.")
    return catalog


def _result(case_id: str, category: str, message: str, passed: bool, expected: Dict[str, Any], actual: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "category": category,
        "message": message,
        "passed": bool(passed),
        "expected": expected,
        "actual": actual,
        "note": note,
    }


def _field(actual: Optional[Dict[str, Any]], key: str) -> Any:
    return actual.get(key) if isinstance(actual, dict) else None


def _run_parser_case(case_id: str, category: str, message: str, parser, expected: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    actual = parser(message)
    passed = actual is not None and all(_field(actual, key) == value for key, value in expected.items())
    return _result(case_id, category, message, passed, expected, actual or {}, note)


def _run_contract_case(case_id: str, message: str, expected: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    actual = build_latest_message_contract(message)
    passed = all(actual.get(key) == value for key, value in expected.items())
    return _result(case_id, "latest_message_contract", message, passed, expected, actual, note)


def _validator_cases() -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    # Prevents the screenshot bug: university count must not become an empty
    # study-term aggregate.
    message = "how many students are in the university"
    bad_plan = {
        "tool_name": "mongodb_student_tool",
        "purpose_analysis": {"target_domain": "students"},
        "arguments": {"operation": "study_term_aggregate", "study_term": "", "statistic": "count"},
        "validation_contract": {"expected_domain": "students"},
    }
    bad_result = {"success": True, "data": {"type": "student_study_term_aggregate", "study_term": "", "statistic": "count", "count": 0}}
    actual = validate_tool_result(message, bad_plan, bad_result)
    cases.append(_result(
        "validator_total_count_rejects_empty_study_term",
        "validator",
        message,
        actual.get("is_valid") is False and any("University-wide student count" in p for p in actual.get("problems", [])),
        {"is_valid": False, "problem_contains": "University-wide student count"},
        actual,
        "The validator must reject a study aggregate when the user asked for total university students.",
    ))

    message = "what is student median grade in law program"
    bad_plan = {
        "tool_name": "mongodb_student_tool",
        "purpose_analysis": {"target_domain": "students"},
        "arguments": {"operation": "study_term_aggregate", "study_term": "what is", "statistic": "median"},
        "validation_contract": {"expected_domain": "students"},
    }
    bad_result = {"success": True, "data": {"type": "student_study_term_aggregate", "study_term": "what is", "statistic": "median", "count": 0}}
    actual = validate_tool_result(message, bad_plan, bad_result)
    cases.append(_result(
        "validator_median_rejects_generic_term",
        "validator",
        message,
        actual.get("is_valid") is False and any("Statistic study term" in p or "mismatch" in p.lower() for p in actual.get("problems", [])),
        {"is_valid": False, "problem_contains": "Statistic study term"},
        actual,
        "The validator must reject generic terms such as 'what is'.",
    ))

    message = "how many students are in the university"
    good_plan = {
        "tool_name": "mongodb_student_tool",
        "purpose_analysis": {"target_domain": "students"},
        "arguments": {"operation": "count", "answer_style": "count"},
        "validation_contract": {"expected_domain": "students"},
    }
    good_result = {"success": True, "data": {"type": "student_count", "count": 100}}
    actual = validate_tool_result(message, good_plan, good_result)
    cases.append(_result(
        "validator_total_count_accepts_student_count",
        "validator",
        message,
        actual.get("is_valid") is True,
        {"is_valid": True},
        actual,
        "The validator should accept a correct university-wide student count payload.",
    ))

    message = "rank me top 5 students that have the best grade"
    rank_plan = {
        "tool_name": "mongodb_student_tool",
        "purpose_analysis": {"target_domain": "students"},
        "arguments": {"operation": "rank_students", "answer_style": "student_rank", "top_n": 5},
        "validation_contract": {"expected_domain": "students"},
    }
    rank_rows = [
        {"student_id": f"S{index:03d}", "gpa": value}
        for index, value in enumerate([3.95, 3.9, 3.8, 3.7, 3.6], start=1)
    ]
    good_rank_result = {
        "success": True,
        "data": {
            "type": "student_ranking",
            "field": "gpa",
            "direction": "desc",
            "requested_count": 5,
            "returned_count": 5,
            "total_candidates": 100,
            "students": rank_rows,
        },
    }
    actual = validate_tool_result(message, rank_plan, good_rank_result)
    cases.append(_result(
        "validator_accepts_exact_ordered_top_five",
        "validator",
        message,
        actual.get("is_valid") is True,
        {"is_valid": True, "returned_count": 5, "direction": "desc"},
        actual,
        "The rank validator accepts only the exact requested count in the correct GPA order.",
    ))

    bad_rank_result = {
        **good_rank_result,
        "data": {
            **good_rank_result["data"],
            "returned_count": 2,
            "students": list(reversed(rank_rows[:2])),
        },
    }
    actual = validate_tool_result(message, rank_plan, bad_rank_result)
    cases.append(_result(
        "validator_rejects_short_unsorted_ranking",
        "validator",
        message,
        actual.get("is_valid") is False
        and any("exactly 5" in problem or "not ordered" in problem for problem in actual.get("problems", [])),
        {"is_valid": False, "problem_contains": "exactly 5 or not ordered"},
        actual,
        "The validator rejects the former first-records/unsorted ranking behavior.",
    ))
    return cases


def _nested_field(value: Dict[str, Any], dotted_path: str) -> Any:
    current: Any = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _authoritative_planner_cases(catalog_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []

    def plan(
        message: str,
        role: str = "admin",
        requester_student_id: Optional[str] = None,
        requester_advisor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        purpose = apply_contract_to_purpose(message, {
            "source": "v30_evaluation",
            "target_domain": "normal_chat",
            "answer_intent": "read",
            "should_use_database": False,
            "confidence": 1.0,
            "explicit_entities": {},
        })
        return plan_from_purpose(
            message=message,
            language="en",
            user_role=role,
            purpose=purpose,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        ) or {}

    for case in catalog_cases:
        message = str(case.get("message") or "")
        expected = case.get("expected") or {}
        role = str(case.get("role") or "admin")
        requester_student_id = str(case.get("requester_student_id") or "") or None
        requester_advisor_id = str(case.get("requester_advisor_id") or "") or None
        if str(case.get("category") or "") == "student_own_scope_planner":
            actual = deterministic_plan(
                message,
                "en",
                role,
                requester_student_id=requester_student_id,
                requester_advisor_id=requester_advisor_id,
            ) or {}
        else:
            actual = plan(
                message,
                role=role,
                requester_student_id=requester_student_id,
                requester_advisor_id=requester_advisor_id,
            )
        passed = all(_nested_field(actual, path) == value for path, value in expected.items())
        # A surname lookup must also prove that the database filter is present.
        if case.get("case_id") == "v30_surname_gpa_filtered":
            passed = passed and "$regex" in (((actual.get("arguments") or {}).get("query_filter") or {}).get("name") or {})
        cases.append(_result(
            str(case.get("case_id") or ""),
            str(case.get("category") or "authoritative_planner"),
            message,
            passed,
            expected,
            actual,
            str(case.get("note") or ""),
        ))
    return cases


def _conversation_planner_cases(catalog_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Verify that short follow-ups inherit entities/topics without widening role scope."""
    cases: List[Dict[str, Any]] = []
    for case in catalog_cases:
        message = str(case.get("message") or "")
        expected = case.get("expected") or {}
        actual = plan_turn(
            message=message,
            language=str(case.get("language") or "en"),
            user_role=str(case.get("role") or "admin"),
            requester_student_id=str(case.get("requester_student_id") or "") or None,
            requester_advisor_id=str(case.get("requester_advisor_id") or "") or None,
            chat_history=case.get("history") or [],
            allow_contextual_ai=False,
        )
        passed = all(_nested_field(actual, path) == value for path, value in expected.items())
        cases.append(_result(
            str(case.get("case_id") or ""),
            str(case.get("category") or "conversation_followup"),
            message,
            passed,
            expected,
            actual,
            str(case.get("note") or ""),
        ))
    return cases


def run_query_contract_evaluation() -> Dict[str, Any]:
    """Run the safe local regression set and return a UI-friendly report."""
    cases: List[Dict[str, Any]] = []
    catalog = load_benchmark_catalog()
    for case in catalog["parser_cases"]:
        parser_name = str(case.get("parser") or "")
        parser = PARSERS.get(parser_name)
        if parser is None:
            cases.append(_result(
                str(case.get("case_id") or ""),
                str(case.get("category") or "parser"),
                str(case.get("message") or ""),
                False,
                case.get("expected") or {},
                {},
                f"Unknown benchmark parser: {parser_name}",
            ))
            continue
        cases.append(_run_parser_case(
            str(case.get("case_id") or ""),
            str(case.get("category") or "parser"),
            str(case.get("message") or ""),
            parser,
            case.get("expected") or {},
            str(case.get("note") or ""),
        ))

    for case in catalog["contract_cases"]:
        cases.append(_run_contract_case(
            str(case.get("case_id") or ""),
            str(case.get("message") or ""),
            case.get("expected") or {},
            str(case.get("note") or ""),
        ))

    cases.extend(_authoritative_planner_cases(catalog["planner_cases"]))
    cases.extend(_conversation_planner_cases(catalog["conversation_cases"]))
    cases.extend(_validator_cases())
    passed = sum(1 for case in cases if case["passed"])
    failed = len(cases) - passed
    categories: Dict[str, Dict[str, int]] = {}
    for case in cases:
        bucket = categories.setdefault(case["category"], {"total": 0, "passed": 0, "failed": 0})
        bucket["total"] += 1
        bucket["passed" if case["passed"] else "failed"] += 1

    return {
        "success": failed == 0,
        "evaluation_version": EVALUATION_VERSION,
        "benchmark_version": catalog.get("version"),
        "benchmark_file": BENCHMARK_PATH.name,
        "mode": "deterministic local query-contract evaluation; no Gemini API call and no real student data is returned",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(cases),
            "passed": passed,
            "failed": failed,
            "pass_rate": round((passed / len(cases) * 100) if cases else 0.0, 1),
        },
        "categories": categories,
        "cases": cases,
    }
