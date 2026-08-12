"""V24 end-to-end contract gate for the University AI.

This is deliberately local and deterministic.  It validates the full *shape* of
an answer path without making Gemini calls or querying private production data:

message -> latest-message contract -> planner -> fixture-shaped tool result
-> validator -> deterministic answer formatter.

It catches regressions where a parser is correct but the planner, validation, or
answer layer later drops the intent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.agent.contextual_tool_planner import plan_from_purpose
from app.agent.document_qa import answer_from_selected_document, is_general_document_overview_question
from app.agent.final_answer_writer import deterministic_database_answer, _format_documents
from app.agent.purpose_contract import build_latest_message_contract
from app.agent.result_validator import validate_tool_result

E2E_GATE_VERSION = "V24_END_TO_END_CONTRACT_GATE"


def _purpose(domain: str, intent: str = "read", *, subject_terms: List[str] | None = None) -> Dict[str, Any]:
    return {
        "target_domain": domain,
        "answer_intent": intent,
        "should_use_database": True,
        "confidence": 0.98,
        "user_purpose": "Deterministic end-to-end quality gate fixture.",
        "explicit_entities": {
            "student_ids": [],
            "advisor_ids": [],
            "subject_terms": subject_terms or [],
            "file_terms": [],
        },
    }


def _case(case_id: str, area: str, message: str, passed: bool, expected: Dict[str, Any], actual: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "area": area,
        "message": message,
        "passed": bool(passed),
        "expected": expected,
        "actual": actual,
        "note": note,
    }


def _student_plan(message: str, purpose: Dict[str, Any]) -> Dict[str, Any]:
    return plan_from_purpose(
        message=message,
        language="th" if any("\u0e00" <= c <= "\u0e7f" for c in message) else "en",
        user_role="admin",
        purpose=purpose,
        requester_student_id=None,
        requester_advisor_id=None,
        chat_history=[],
    ) or {}


def _student_case(
    case_id: str,
    message: str,
    purpose: Dict[str, Any],
    expected_operation: str,
    expected_style: str,
    fixture_data: Dict[str, Any],
    expected_answer_piece: str,
) -> Dict[str, Any]:
    contract = build_latest_message_contract(message)
    plan = _student_plan(message, purpose)
    plan["purpose_analysis"] = purpose
    plan["validation_contract"] = {"expected_domain": "students"}
    result = {"success": True, "data": fixture_data}
    validation = validate_tool_result(message, plan, result)
    answer = deterministic_database_answer(message, "en", plan, result) or ""
    args = plan.get("arguments") or {}
    passed = (
        args.get("operation") == expected_operation
        and args.get("answer_style") == expected_style
        and validation.get("is_valid") is True
        and expected_answer_piece.lower() in answer.lower()
    )
    return _case(
        case_id,
        "student_flow",
        message,
        passed,
        {"operation": expected_operation, "answer_style": expected_style, "answer_contains": expected_answer_piece},
        {
            "contract": {k: contract.get(k) for k in ("domain", "intent", "answer_style", "student_ids")},
            "operation": args.get("operation"),
            "answer_style": args.get("answer_style"),
            "validation": validation,
            "answer_preview": answer[:350],
        },
        "Checks message contract, planner, fixture result validation, and deterministic answer shape together.",
    )


def _document_cases() -> List[Dict[str, Any]]:
    doc = {
        "id": 101,
        "filename": "law-foundations.pdf",
        "source_type": "pdf",
        "storage_target": "postgres",
        "summary": "An introduction to law, private law, contracts, and torts.",
        "full_text": (
            "Law is a body of rules recognized and applied by the state. "
            "Private law includes torts, contracts, and trusts. "
            "Torts concern civil wrongs and remedies between private parties."
        ),
        "conclusion_table": {
            "main_topic": "Introduction to law",
            "short_summary": "An introduction to law, private law, contracts, and torts.",
            "key_points": ["Private law includes torts, contracts, and trusts."],
        },
    }
    targeted = answer_from_selected_document(doc, "What is torts?", "en") or ""
    overview = _format_documents({"operation": "document_by_id", "data": [doc]}, False, "What is this file about?") or ""
    return [
        _case(
            "document_targeted_pinned_answer",
            "document_flow",
            "What is torts?",
            "Torts concern civil wrongs" in targeted and "law-foundations.pdf" in targeted,
            {"source": "selected document", "answer_contains": "Torts concern civil wrongs"},
            {"answer_preview": targeted[:350], "overview_question": is_general_document_overview_question("What is torts?")},
            "A focused question must use stored text from the selected document.",
        ),
        _case(
            "document_overview_answer",
            "document_flow",
            "What is this file about?",
            "About the PDF file" in overview and "introduction to law" in overview.lower(),
            {"source": "selected document overview", "answer_contains": "introduction to law"},
            {"answer_preview": overview[:350], "overview_question": is_general_document_overview_question("What is this file about?")},
            "A broad request must produce an overview, not a random retrieval excerpt.",
        ),
    ]


def run_end_to_end_gate() -> Dict[str, Any]:
    """Return a UI-friendly V24 test report. No external calls are made."""
    cases: List[Dict[str, Any]] = []
    cases.append(_student_case(
        "university_total_en",
        "how many students are in the university",
        _purpose("students", "count"),
        "count", "count",
        {"type": "student_count", "count": 100},
        "100",
    ))
    cases.append(_student_case(
        "university_total_th",
        "มหาวิทยาลัยมีนักศึกษากี่คน",
        _purpose("students", "count"),
        "count", "count",
        {"type": "student_count", "count": 100},
        "100",
    ))
    cases.append(_student_case(
        "law_median",
        "what is student median grade in law program",
        _purpose("students", "aggregate", subject_terms=["law"]),
        "study_term_aggregate", "study_statistic",
        {"type": "student_study_term_aggregate", "study_term": "law", "statistic": "median", "metric_field": "gpa", "count": 4, "value": 3.42, "students": []},
        "3.42",
    ))
    cases.append(_student_case(
        "gpa_below_count",
        "how many students have GPA lower than 3.0",
        _purpose("students", "count"),
        "filter_summary", "aggregate_count",
        {"type": "student_filter_summary", "field": "gpa", "operator": "$lt", "value": 3.0, "count": 2, "students": []},
        "2",
    ))
    cases.append(_student_case(
        "student_top_five_ranking",
        "rank me top 5 students that have the best grade",
        _purpose("students", "rank"),
        "rank_students", "student_rank",
        {
            "type": "student_ranking",
            "field": "gpa",
            "direction": "desc",
            "requested_count": 5,
            "returned_count": 5,
            "total_candidates": 100,
            "students": [
                {"student_id": "S001", "name": "One", "gpa": 3.99},
                {"student_id": "S002", "name": "Two", "gpa": 3.95},
                {"student_id": "S003", "name": "Three", "gpa": 3.9},
                {"student_id": "S004", "name": "Four", "gpa": 3.85},
                {"student_id": "S005", "name": "Five", "gpa": 3.8},
            ],
        },
        "Top 5 students by GPA",
    ))

    multi_message = "show grades and attendance for S001"
    multi_plan = _student_plan(multi_message, _purpose("academic_records", "read"))
    multi_result = {
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
                    "attendance_rate": 95,
                    "classes_attended": 38,
                    "classes_scheduled": 40,
                }],
            },
            "denied_sections": [],
        },
    }
    multi_answer = deterministic_database_answer(multi_message, "en", multi_plan, multi_result) or ""
    cases.append(_case(
        "student_grades_attendance_combined_answer",
        "student_flow",
        multi_message,
        "Algorithms: A" in multi_answer and "Attendance for S001" in multi_answer and "95%" in multi_answer,
        {"answer_contains": ["Algorithms: A", "Attendance for S001", "95%"]},
        {"answer_preview": multi_answer[:500], "arguments": multi_plan.get("arguments")},
        "One answer must preserve every authorized section requested from both databases.",
    ))
    profile_message = "what is S095 profile"
    profile_purpose = _purpose("students", "read")
    profile_purpose["explicit_entities"]["student_ids"] = ["S095"]
    profile_plan = _student_plan(profile_message, profile_purpose)
    profile_plan["purpose_analysis"] = profile_purpose
    profile_plan["validation_contract"] = {"expected_domain": "students"}
    profile_result = {"success": True, "data": [{"student_id": "S095", "name": "Taylor", "program": "Law", "gpa": 3.6, "academic_status": "Active", "subject_grades": []}]}
    profile_validation = validate_tool_result(profile_message, profile_plan, profile_result)
    profile_answer = deterministic_database_answer(profile_message, "en", profile_plan, profile_result) or ""
    cases.append(_case(
        "exact_student_profile",
        "student_flow",
        profile_message,
        (profile_plan.get("arguments") or {}).get("student_id") == "S095" and profile_validation.get("is_valid") is True and "Taylor" in profile_answer,
        {"student_id": "S095", "answer_style": "profile", "answer_contains": "Taylor"},
        {"arguments": profile_plan.get("arguments"), "validation": profile_validation, "answer_preview": profile_answer[:350]},
        "Exact latest student ID cannot be replaced by older context.",
    ))
    cases.extend(_document_cases())
    passed = sum(1 for item in cases if item["passed"])
    total = len(cases)
    failed_cases = [item["case_id"] for item in cases if not item["passed"]]
    return {
        "success": passed == total,
        "gate_version": E2E_GATE_VERSION,
        "mode": "local fixture end-to-end gate; no Gemini call and no live private records",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"passed": passed, "failed": total - passed, "total": total, "percentage": round((passed / total * 100) if total else 0.0, 1)},
        "failed_case_ids": failed_cases,
        "cases": cases,
        "next_action": "Safe to proceed when all checks pass. If a case fails, inspect the contract, planned operation, validation, and answer preview in that case before changing code.",
    }
