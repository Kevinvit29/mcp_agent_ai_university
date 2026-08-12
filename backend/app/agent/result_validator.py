"""Result Validator for Agent Orchestrator V2.

The validator is the safety net that prevents the final answer from using data
from the wrong domain or the wrong entity.  If the user asks for S035, a result
for S001 is invalid even if it came from the correct database tool.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.agent.tool_planner import deterministic_plan
from app.agent.natural_query import normalize_typos
from app.agent.aggregate_query import (
    parse_student_ranking_query,
    parse_student_study_query,
    parse_student_statistic_query,
    parse_total_student_count_query,
)
from app.agent.analytics_query import parse_database_analytics_query


SUBJECT_WORDS = {"subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา"}
DOCUMENT_WORDS = {"pdf", "document", "documents", "file", "files", "excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "upload", "uploaded", "เอกสาร", "ไฟล์", "เอ็กเซล"}
ADVISOR_WORDS = {"advisor", "advisors", "teacher", "teachers", "อาจารย์", "ที่ปรึกษา"}
STUDENT_WORDS = {"student", "students", "gpa", "grade", "grades", "score", "scores", "นักศึกษา", "เกรด", "คะแนน"}


def _low(message: str) -> str:
    return normalize_typos(message or "").lower().strip()


def _has_any(text: str, words: set[str]) -> bool:
    return any(w in text for w in words)


def _student_ids(message: str) -> List[str]:
    ids: List[str] = []
    for sid in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I):
        sid = sid.upper()
        if sid not in ids:
            ids.append(sid)
    return ids


def _advisor_ids(message: str) -> List[str]:
    ids: List[str] = []
    for aid in re.findall(r"\bA\d{3,6}\b", message or "", flags=re.I):
        aid = aid.upper()
        if aid not in ids:
            ids.append(aid)
    return ids


def expected_domain(message: str, current_plan: Optional[Dict[str, Any]] = None) -> str:
    contract = (current_plan or {}).get("validation_contract") or {}
    if contract.get("expected_domain"):
        return str(contract.get("expected_domain"))
    purpose = (current_plan or {}).get("purpose_analysis") or {}
    purpose_domain = str(purpose.get("target_domain") or "")
    if purpose_domain in {"students", "student_grades", "student_gpa"}:
        return "students"
    if purpose_domain in {"subjects", "advisors", "documents", "programs", "campus_info", "database_map", "academic_records", "course_catalog", "normal_chat"}:
        return purpose_domain
    text = _low(message)
    if re.search(r"\bS\d{3,6}\b", message or "", flags=re.I):
        return "students"
    if _has_any(text, DOCUMENT_WORDS):
        return "documents"
    if _has_any(text, SUBJECT_WORDS):
        return "subjects"
    if _has_any(text, ADVISOR_WORDS):
        return "advisors"
    if _has_any(text, STUDENT_WORDS):
        return "students"
    plan_domain = ((current_plan or {}).get("orchestrator") or {}).get("domain")
    return str(plan_domain or "normal_chat")


def _unwrap_data(tool_result: Dict[str, Any]) -> Any:
    data = tool_result.get("data") if isinstance(tool_result, dict) else None
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return data.get("data")
    return data


def result_domain(tool_result: Dict[str, Any]) -> str:
    data = _unwrap_data(tool_result)
    if isinstance(data, dict):
        typ = str(data.get("type") or "")
        if typ == "group_analytics":
            return "students" if str(data.get("source") or "").startswith("mongodb") else "academic_records"
        if typ == "student_benchmark":
            return "students"
        if typ in {
            "student_academic_profile", "student_academic_profiles", "student_risk_records",
            "academic_overview", "academic_risk_summary", "advisor_classroom",
        }:
            return "academic_records"
        if typ == "course_catalog":
            return "course_catalog"
        if typ == "student_subjects":
            return "subjects"
        if typ == "subject_summary" or "unique_subject_count" in data:
            return "subjects"
        if typ in {"student_count", "student_names", "student_ranking", "grade_summary", "student_filter_summary", "student_study_term_search", "student_study_term_aggregate", "student_population_aggregate"} or "students" in data:
            return "students"
        if typ == "advisor_list" or "advisors" in data or ("advisor_id" in data and "student_id" not in data):
            return "advisors"
        if "student_id" in data:
            return "students"
        if "filename" in data or "source_type" in data:
            return "documents"
        if "primary_result" in data and "admin_university_context" in data:
            return "admin_multi_context"
        if data.get("operation") in {"list_documents", "document_search"} or isinstance(data.get("data"), list):
            return "documents"
    if isinstance(data, list):
        if not data:
            return "empty_list"
        sample = next((x for x in data if isinstance(x, dict)), None)
        if sample:
            if "student_id" in sample:
                return "students"
            if "advisor_id" in sample and "student_id" not in sample:
                return "advisors"
            if "filename" in sample or "source_type" in sample:
                return "documents"
    return "unknown"


def _rows(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("students"), list):
            return [r for r in data.get("students") if isinstance(r, dict)]
        if isinstance(data.get("advisors"), list):
            return [r for r in data.get("advisors") if isinstance(r, dict)]
        if isinstance(data.get("data"), list):
            return [r for r in data.get("data") if isinstance(r, dict)]
        return [data]
    return []


def _extract_student_ids_from_result(tool_result: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for row in _rows(_unwrap_data(tool_result)):
        sid = row.get("student_id")
        if sid:
            sid = str(sid).upper()
            if sid not in ids:
                ids.append(sid)
    return ids


def _extract_advisor_ids_from_result(tool_result: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for row in _rows(_unwrap_data(tool_result)):
        aid = row.get("advisor_id")
        if aid:
            aid = str(aid).upper()
            if aid not in ids:
                ids.append(aid)
    return ids


def validate_tool_result(message: str, plan: Dict[str, Any], tool_result: Dict[str, Any]) -> Dict[str, Any]:
    contract = plan.get("validation_contract") or {}
    exp = expected_domain(message, plan)
    got = result_domain(tool_result)
    ok = True
    problems: List[str] = []
    plan_args = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
    student_own_subject_query = (
        str(plan.get("user_role") or "").lower() == "student"
        and str(plan_args.get("answer_style") or "") in {
            "student_course_list",
            "student_course_membership",
        }
        and str(plan_args.get("student_id") or "") == str(plan.get("requester_student_id") or "")
    )

    if plan.get("tool_name") == "none":
        return {"is_valid": True, "expected_domain": "normal_chat", "actual_domain": "normal_chat", "problems": [], "can_repair": False}

    if not isinstance(tool_result, dict) or tool_result.get("success") is False:
        return {"is_valid": False, "expected_domain": exp, "actual_domain": got, "problems": [str((tool_result or {}).get("error") or "MCP call failed")], "can_repair": False}

    if exp in {"subjects", "documents", "students", "advisors", "academic_records", "course_catalog"}:
        if exp == "documents":
            if got not in {"documents", "empty_list"} and plan.get("tool_name") != "postgres_university_tool":
                ok = False
                problems.append(f"Expected document data but got {got}.")
        elif exp != got and not (exp == "subjects" and got == "students" and student_own_subject_query):
            ok = False
            problems.append(f"Expected {exp} data but got {got}.")

    data = _unwrap_data(tool_result)
    analytics_query = parse_database_analytics_query(message)
    if exp == "subjects":
        if not student_own_subject_query and not (isinstance(data, dict) and (data.get("type") == "subject_summary" or "unique_subject_count" in data)):
            ok = False
            problems.append("Subject question must return a subject_summary payload, not a student/profile payload.")

    if exp in {"academic_records", "course_catalog"}:
        expected_query_type = str(contract.get("expected_query_type") or (plan.get("arguments") or {}).get("query_type") or "")
        expected_type = {
            "student_academic_profile": (
                "student_academic_profiles"
                if len((plan.get("arguments") or {}).get("student_ids") or []) > 1
                else "student_academic_profile"
            ),
            "academic_overview": "academic_overview",
            "academic_risk_summary": "academic_risk_summary",
            "course_catalog": "course_catalog",
            "academic_analytics": (
                "student_risk_records"
                if str((plan.get("arguments") or {}).get("measure") or "") == "risk_level"
                else "group_analytics"
            ),
            "advisor_classroom": "advisor_classroom",
        }.get(expected_query_type)
        if plan.get("tool_name") != "postgres_university_tool":
            ok = False
            problems.append("Academic facts must come from postgres_university_tool.")
        if expected_type and (not isinstance(data, dict) or data.get("type") != expected_type):
            ok = False
            problems.append(f"Academic query_type={expected_query_type} must return type={expected_type}.")
        academic_records = []
        if expected_type == "student_academic_profile" and isinstance(data, dict):
            academic_records = [data]
        elif expected_type == "student_academic_profiles" and isinstance(data, dict):
            academic_records = [row for row in (data.get("records") or []) if isinstance(row, dict)]
        for academic_record in academic_records:
            if academic_record.get("profile") is None:
                continue
            for section in contract.get("expected_sections") or []:
                if section != "profile" and section not in academic_record:
                    ok = False
                    problems.append(
                        f"Academic result for {academic_record.get('student_id') or 'student'} "
                        f"is missing requested section: {section}."
                    )

    if (
        isinstance(analytics_query, dict)
        and analytics_query.get("type") == "database_analytics"
        and str((plan.get("arguments") or {}).get("query_type") or "") != "advisor_classroom"
    ):
        expected_tool = "mongodb_student_tool" if analytics_query.get("source") == "mongo" else "postgres_university_tool"
        expected_operation = "group_students" if analytics_query.get("source") == "mongo" else analytics_query.get("operation")
        if plan.get("tool_name") != expected_tool:
            ok = False
            problems.append(f"Grouped analytics must use {expected_tool}.")
        if (plan.get("arguments") or {}).get("operation") != expected_operation:
            ok = False
            problems.append(f"Grouped analytics operation must be {expected_operation}.")
        expected_payload_type = "student_risk_records" if analytics_query.get("measure") == "risk_level" else "group_analytics"
        if not isinstance(data, dict) or data.get("type") != expected_payload_type:
            ok = False
            problems.append(f"Database analytics must return a {expected_payload_type} payload.")
        elif expected_payload_type == "group_analytics" and (
            str(data.get("dimension") or "") != str(analytics_query.get("dimension") or "")
            or str(data.get("measure") or "") != str(analytics_query.get("measure") or "")
        ):
            ok = False
            problems.append("Grouped analytics result does not match the requested dimension and measure.")
        elif analytics_query.get("operation") == "group_rank":
            values = []
            for row in data.get("groups") or []:
                try:
                    values.append(float(row.get("value")))
                except (TypeError, ValueError, AttributeError):
                    continue
            direction = str(analytics_query.get("direction") or "desc")
            ordered = all(
                values[index] <= values[index + 1] if direction == "asc"
                else values[index] >= values[index + 1]
                for index in range(len(values) - 1)
            )
            if not ordered:
                ok = False
                problems.append(f"Grouped analytics rows are not ordered {direction}.")

    if isinstance(analytics_query, dict) and analytics_query.get("type") == "student_benchmark":
        if (plan.get("arguments") or {}).get("operation") != "compare_student_to_population":
            ok = False
            problems.append("Student benchmark must use compare_student_to_population.")
        if not isinstance(data, dict) or data.get("type") != "student_benchmark":
            ok = False
            problems.append("Student benchmark must return a student_benchmark payload.")

    if isinstance(data, dict) and data.get("type") == "advisor_classroom":
        signed_advisor = str(plan.get("requester_advisor_id") or "").upper()
        if not signed_advisor or str(data.get("advisor_id") or "").upper() != signed_advisor:
            ok = False
            problems.append("Advisor classroom result is not bound to the signed advisor identity.")
        if data.get("scope") not in {None, "signed_advisor_same_course_only"}:
            ok = False
            problems.append("Advisor classroom result has an invalid access scope.")

    total_count_query = parse_total_student_count_query(message)
    ranking_query = parse_student_ranking_query(message)
    stat_query = parse_student_statistic_query(message)
    plan_args = plan.get("arguments") or {}

    if ranking_query and exp == "students":
        if plan_args.get("operation") != "rank_students":
            ok = False
            problems.append(f"Student ranking must use operation=rank_students, not {plan_args.get('operation') or 'empty'}.")
        elif not isinstance(data, dict) or data.get("type") != "student_ranking":
            ok = False
            problems.append("Student ranking must return a student_ranking payload.")
        else:
            expected_n = int(ranking_query.get("top_n") or 10)
            expected_direction = str(ranking_query.get("direction") or "desc")
            expected_field = str(ranking_query.get("field") or "gpa")
            rows = [row for row in (data.get("students") or []) if isinstance(row, dict)]
            total_candidates = int(data.get("total_candidates") or len(rows))
            expected_returned = min(expected_n, total_candidates)
            if int(data.get("requested_count") or 0) != expected_n:
                ok = False
                problems.append(f"Ranking requested_count must be {expected_n}.")
            if len(rows) != expected_returned or int(data.get("returned_count") or 0) != expected_returned:
                ok = False
                problems.append(f"Ranking must return exactly {expected_returned} row(s), got {len(rows)}.")
            if str(data.get("direction") or "") != expected_direction:
                ok = False
                problems.append(f"Ranking direction must be {expected_direction}.")
            if str(data.get("field") or "") != expected_field:
                ok = False
                problems.append(f"Ranking field must be {expected_field}.")
            values: List[float] = []
            for row in rows:
                try:
                    values.append(float(row.get(expected_field)))
                except (TypeError, ValueError):
                    ok = False
                    problems.append(f"Ranking row is missing numeric {expected_field}.")
                    break
            if values:
                ordered = all(
                    values[index] <= values[index + 1]
                    if expected_direction == "asc"
                    else values[index] >= values[index + 1]
                    for index in range(len(values) - 1)
                )
                if not ordered:
                    ok = False
                    problems.append(f"Ranking rows are not ordered by {expected_field} {expected_direction}.")

    if total_count_query and exp == "students":
        if plan_args.get("operation") != "count":
            ok = False
            problems.append("University-wide student count must use operation=count, not a study-term aggregate.")
        elif isinstance(data, dict) and data.get("type") != "student_count":
            ok = False
            problems.append("University-wide student count must return a student_count payload.")

    # The structured analytics contract is more specific than the legacy
    # free-form statistic parser. Do not make the older parser reject valid
    # grouped analytics or a two-scope student benchmark.
    if stat_query and exp == "students" and not (
        isinstance(analytics_query, dict)
        and analytics_query.get("type") in {"database_analytics", "student_benchmark"}
    ):
        expected_operation = str(stat_query.get("operation") or "study_term_aggregate")
        expected_type = "student_population_aggregate" if expected_operation == "student_population_aggregate" else "student_study_term_aggregate"
        if plan_args.get("operation") != expected_operation:
            ok = False
            problems.append(f"Statistic question must use operation={expected_operation}, not {plan_args.get('operation') or 'empty'}.")
        elif isinstance(data, dict) and data.get("type") != expected_type:
            ok = False
            problems.append(f"Statistic question must return a {expected_type} payload.")
        elif isinstance(data, dict):
            expected_term = str(stat_query.get("study_term") or "").lower().strip()
            got_term = str(data.get("study_term") or "").lower().strip()
            generic_terms = {"what", "what is", "how", "how many", "list", "list the", "show", "student", "students", "name", "names", "the"}
            if expected_operation == "study_term_aggregate":
                if not expected_term:
                    ok = False
                    problems.append("Study-term aggregate was selected without a concrete programme or subject term.")
                elif not got_term or got_term in generic_terms:
                    ok = False
                    problems.append(f"Statistic study term is missing or too generic: {got_term or 'empty'}.")
                elif expected_term not in got_term and got_term not in expected_term:
                    ok = False
                    problems.append(f"Statistic study term mismatch: expected {expected_term}, got {got_term}.")
            elif got_term:
                ok = False
                problems.append(f"University-wide statistic must not fabricate a study term, got {got_term}.")
            got_stat = str(data.get("statistic") or "").lower().strip()
            expected_stat = str(stat_query.get("statistic") or "").lower().strip()
            if expected_stat and got_stat != expected_stat:
                ok = False
                problems.append(f"Statistic mismatch: expected {expected_stat}, got {got_stat or 'empty'}.")

    study_query = parse_student_study_query(message)
    if study_query and exp == "students" and not stat_query:
        plan_args = plan.get("arguments") or {}
        if plan_args.get("operation") != "study_term_search":
            ok = False
            problems.append("Study-term question must use operation=study_term_search instead of reading all students.")
        elif isinstance(data, dict) and data.get("type") != "student_study_term_search":
            ok = False
            problems.append("Study-term question must return a student_study_term_search payload.")
        elif isinstance(data, dict):
            got_term = str(data.get("study_term") or "").lower().strip()
            expected_term = str(study_query.get("study_term") or "").lower().strip()
            generic_terms = {"list", "list the", "show", "show the", "student", "students", "name", "names", "the"}
            if not got_term or got_term in generic_terms:
                ok = False
                problems.append(f"Study search term is missing or too generic: {got_term or 'empty'}.")
            elif expected_term and got_term and expected_term not in got_term and got_term not in expected_term:
                ok = False
                problems.append(f"Study search term mismatch: expected {expected_term}, got {got_term}.")
            ranking_expected = study_query.get("ranking") if isinstance(study_query.get("ranking"), dict) else None
            if ranking_expected:
                if not isinstance(data.get("ranking_applied"), dict):
                    ok = False
                    problems.append("Ranking was requested but the tool result did not include ranking_applied.")
                plan_ranking = plan_args.get("ranking") if isinstance(plan_args.get("ranking"), dict) else None
                if not plan_ranking:
                    ok = False
                    problems.append("Ranking was requested but the tool plan did not include ranking arguments.")

    message_student_ids = _student_ids(message)
    contract_student_ids = contract.get("required_student_ids") or []
    purpose = plan.get("purpose_analysis") or {}
    purpose_entities = purpose.get("explicit_entities") if isinstance(purpose.get("explicit_entities"), dict) else {}
    purpose_student_ids = [str(x).upper() for x in (purpose_entities.get("student_ids") or []) if re.fullmatch(r"S\d{3,6}", str(x).upper())]
    inherited_student_ids = [
        str(value).upper()
        for value in ((plan.get("arguments") or {}).get("resolved_context_student_ids") or [])
        if re.fullmatch(r"S\d{3,6}", str(value).upper())
    ]
    allowed_contract_ids = list(dict.fromkeys(inherited_student_ids + message_student_ids))
    required_ids = (
        contract_student_ids
        if inherited_student_ids and contract_student_ids
        else (message_student_ids or contract_student_ids or purpose_student_ids)
    )
    if (
        message_student_ids
        and contract_student_ids
        and message_student_ids != contract_student_ids
        and contract_student_ids != allowed_contract_ids
    ):
        ok = False
        problems.append(f"Plan student IDs {contract_student_ids} do not match latest user message IDs {message_student_ids}.")
    if required_ids and got == "students":
        found = _extract_student_ids_from_result(tool_result)
        missing = [sid for sid in required_ids if sid not in found]
        wrong_extra = [sid for sid in found if sid not in required_ids]
        if missing:
            data_text = json.dumps(data, ensure_ascii=False, default=str)
            truly_missing = [sid for sid in missing if sid not in data_text]
            if truly_missing:
                ok = False
                problems.append(f"Missing requested student IDs: {', '.join(truly_missing)}")
        if len(required_ids) == 1 and wrong_extra:
            ok = False
            problems.append(f"Question requested {required_ids[0]} but result also/only contains other student IDs: {', '.join(wrong_extra)}")
    if required_ids and got == "academic_records":
        found: List[str] = []
        if isinstance(data, dict) and data.get("type") == "student_academic_profile":
            found = [str(data.get("student_id") or "").upper()]
        elif isinstance(data, dict) and data.get("type") == "student_academic_profiles":
            found = [
                str(row.get("student_id") or "").upper()
                for row in (data.get("records") or [])
                if isinstance(row, dict) and row.get("student_id")
            ]
        elif isinstance(data, dict) and data.get("type") == "advisor_classroom":
            found = [
                str(row.get("student_id") or "").upper()
                for row in (data.get("rows") or [])
                if isinstance(row, dict) and row.get("student_id")
            ]
            if data.get("status") == "student_not_in_advisor_class":
                found = list(required_ids)
        missing = [sid for sid in required_ids if sid not in found]
        if missing:
            ok = False
            problems.append(f"Academic result is missing requested student IDs: {', '.join(missing)}")


    # V4 answer-shape validation: the result can be from the right student but
    # still answer the wrong purpose. Example: latest message says "S099 profile"
    # but plan/result is grade-only. Treat that as invalid so repair can create
    # a profile plan.
    expected_style = str(contract.get("expected_answer_style") or "")
    plan_style = str((plan.get("arguments") or {}).get("answer_style") or "")
    if exp == "students" and required_ids and expected_style in {"profile", "gpa", "grades", "names"}:
        if plan_style and plan_style != expected_style:
            ok = False
            problems.append(f"Question requested student answer_style={expected_style} but plan used answer_style={plan_style}.")
        # For profile, the returned rows should contain more than just subject_grades.
        if expected_style == "profile" and got == "students":
            rows = _rows(data)
            for row in rows:
                if row.get("message"):
                    continue
                profile_keys = {"student_id", "name", "program", "gpa", "academic_status", "email"}
                if not any(k in row for k in profile_keys - {"student_id"}):
                    ok = False
                    problems.append("Profile question returned insufficient profile fields.")
                    break

    message_advisor_ids = _advisor_ids(message)
    contract_advisor_ids = contract.get("required_advisor_ids") or []
    purpose = plan.get("purpose_analysis") or {}
    purpose_entities = purpose.get("explicit_entities") if isinstance(purpose.get("explicit_entities"), dict) else {}
    purpose_advisor_ids = [str(x).upper() for x in (purpose_entities.get("advisor_ids") or []) if re.fullmatch(r"A\d{3,6}", str(x).upper())]
    required_advisors = message_advisor_ids or contract_advisor_ids or purpose_advisor_ids
    if message_advisor_ids and contract_advisor_ids and message_advisor_ids != contract_advisor_ids:
        ok = False
        problems.append(f"Plan advisor IDs {contract_advisor_ids} do not match latest user message IDs {message_advisor_ids}.")
    if required_advisors and got == "advisors":
        found = _extract_advisor_ids_from_result(tool_result)
        missing = [aid for aid in required_advisors if aid not in found]
        if missing:
            data_text = json.dumps(data, ensure_ascii=False, default=str)
            truly_missing = [aid for aid in missing if aid not in data_text]
            if truly_missing:
                ok = False
                problems.append(f"Missing requested advisor IDs: {', '.join(truly_missing)}")

    return {"is_valid": ok, "expected_domain": exp, "actual_domain": got, "problems": problems, "can_repair": not ok}


def _same_plan(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Compare tool + operation + important arguments, not tool only.

    V1 accidentally refused repair when the tool and operation were the same even
    if the repaired student_id changed from S001 to S035.  This made wrong-entity
    answers survive validation.  V2 compares the full safe argument shape.
    """
    if a.get("tool_name") != b.get("tool_name"):
        return False
    aa = dict(a.get("arguments") or {})
    bb = dict(b.get("arguments") or {})
    ignore = {"original_question", "orchestrator_reason", "orchestrator_domain", "orchestrator_intent"}
    aa = {k: v for k, v in aa.items() if k not in ignore}
    bb = {k: v for k, v in bb.items() if k not in ignore}
    return aa == bb


def repair_plan_after_validation(
    message: str,
    language: str,
    user_role: str,
    plan: Dict[str, Any],
    tool_result: Dict[str, Any],
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    validation = validate_tool_result(message, plan, tool_result)
    if validation.get("is_valid") or not validation.get("can_repair"):
        return None
    repaired = deterministic_plan(message, language, user_role, requester_student_id, requester_advisor_id, chat_history)
    if not repaired:
        return None
    if _same_plan(repaired, plan):
        return None
    repaired["planner_warning"] = "Agent Orchestrator V2 repaired the tool plan after result validation: " + "; ".join(validation.get("problems") or [])
    repaired["validation_repair"] = validation
    return repaired
