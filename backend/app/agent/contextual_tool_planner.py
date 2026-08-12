"""Contextual Tool Planner for Agent Orchestrator V3.

This layer converts the AI-interpreted user purpose into a safe MCP plan.  It is
purpose-first: the model reads the full message/context first, then backend code
maps the purpose to an allowed tool/operation and role-limited fields.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.context_reasoner import analyze_user_purpose
from app.agent.natural_query import normalize_typos, document_list_request, friendly_clean_query
from app.agent.schema_registry import allowed_student_fields_for_role, STUDENT_FIELDS_ADMIN
from app.agent.tool_planner import deterministic_plan, _base_plan, _normal_chat_plan, _document_plan, _academic_plan, _analytics_plan, _advisor_classroom_plan, _limit_from_text, _student_answer_shape, _contains_any, STUDENT_WORDS, GRADE_WORDS, GPA_WORDS, PROFILE_WORDS
from app.agent.purpose_contract import build_latest_message_contract
from app.agent.aggregate_query import (
    parse_student_metric_query,
    parse_student_ranking_query,
    parse_student_study_query,
    parse_student_statistic_query,
    parse_total_student_count_query,
)
from app.agent.academic_query import parse_academic_query
from app.agent.advisor_class_query import parse_advisor_class_query
from app.agent.student_scope import enforce_student_scope_plan


def _low(message: str) -> str:
    return normalize_typos(message or "").lower().strip()


def _student_shape_from_purpose(message: str, role: str, purpose: Dict[str, Any]) -> Dict[str, Any]:
    # V4: the latest-message contract decides the requested answer shape before
    # the AI target_domain can narrow it incorrectly. Example: if Gemini labels
    # "S099 profile" as student_grades, the contract still says profile.
    contract = purpose.get("latest_message_contract") if isinstance(purpose.get("latest_message_contract"), dict) else build_latest_message_contract(message)
    requested_style = str(purpose.get("requested_answer_style") or contract.get("answer_style") or "summary")
    if requested_style == "profile":
        requested = STUDENT_FIELDS_ADMIN if role == "admin" else ["student_id", "name", "program", "academic_status", "subject_grades", "gpa", "email"]
        return {"answer_style": "profile", "requested_fields": allowed_student_fields_for_role(role, requested)}
    if requested_style == "student_multi":
        requested = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
        return {
            "answer_style": "student_multi",
            "requested_components": list(contract.get("student_components") or ["gpa", "grades"]),
            "requested_fields": allowed_student_fields_for_role(role, requested),
        }
    if requested_style == "gpa":
        return {"answer_style": "gpa", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name", "gpa"])}
    if requested_style == "grades":
        return {"answer_style": "grades", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name", "program", "academic_status", "subject_grades"])}
    if requested_style == "names":
        return {"answer_style": "names", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name"])}

    domain = str(purpose.get("target_domain") or "")
    answer_intent = str(purpose.get("answer_intent") or "")
    if domain == "student_gpa":
        return {"answer_style": "gpa", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name", "gpa"])}
    if domain == "student_grades":
        return {"answer_style": "grades", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name", "program", "academic_status", "subject_grades"])}
    if answer_intent == "list":
        return {"answer_style": "names", "requested_fields": allowed_student_fields_for_role(role, ["student_id", "name"])}
    return _student_answer_shape(message, role)


def _student_ids_from_purpose(purpose: Dict[str, Any]) -> List[str]:
    entities = purpose.get("explicit_entities") if isinstance(purpose.get("explicit_entities"), dict) else {}
    ids: List[str] = []
    for sid in entities.get("student_ids") or []:
        sid = str(sid).upper().strip()
        if re.fullmatch(r"S\d{3,6}", sid) and sid not in ids:
            ids.append(sid)
    return ids


def _advisor_ids_from_purpose(purpose: Dict[str, Any]) -> List[str]:
    entities = purpose.get("explicit_entities") if isinstance(purpose.get("explicit_entities"), dict) else {}
    ids: List[str] = []
    for aid in entities.get("advisor_ids") or []:
        aid = str(aid).upper().strip()
        if re.fullmatch(r"A\d{3,6}", aid) and aid not in ids:
            ids.append(aid)
    return ids


def _last_names_from_purpose(purpose: Dict[str, Any]) -> List[str]:
    entities = purpose.get("explicit_entities") if isinstance(purpose.get("explicit_entities"), dict) else {}
    names: List[str] = []
    for value in entities.get("last_names") or []:
        value = str(value).lower().strip()
        if value and value not in names:
            names.append(value)
    return names


def _plan_from_purpose_unchecked(
    *,
    message: str,
    language: str,
    user_role: str,
    purpose: Dict[str, Any],
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    role = (user_role or "student").lower()
    if role == "student":
        own_course_plan = deterministic_plan(
            message,
            language,
            role,
            requester_student_id,
            requester_advisor_id,
            chat_history,
        )
        if (
            own_course_plan
            and str(own_course_plan.get("selected_agent") or "") == "student_own_course_agent"
        ):
            return own_course_plan
    domain = str(purpose.get("target_domain") or "normal_chat")
    intent = str(purpose.get("answer_intent") or "read")
    confidence = float(purpose.get("confidence") or 0.0)
    reason = f"V3 purpose-first planner: {purpose.get('user_purpose') or purpose.get('reason') or 'purpose interpreted'}"
    contract = purpose.get("latest_message_contract") or {}
    contract_domain = str(contract.get("purpose_domain") or contract.get("domain") or "")
    if contract_domain and contract_domain != "normal_chat":
        domain = contract_domain
        intent = str(contract.get("intent") or intent)
    presentation = contract.get("presentation") or {}
    wants_table = presentation.get("view") == "table"
    wants_report = bool(presentation.get("want_report"))

    if role == "advisor" and contract_domain != "documents":
        classroom_query = parse_advisor_class_query(message)
        if classroom_query:
            plan = _advisor_classroom_plan(
                message,
                language,
                requester_advisor_id,
                classroom_query,
            )
            plan["purpose_analysis"] = purpose
            plan["purpose_contract"] = contract
            plan["planner_warning"] = "V30 applied the signed-advisor same-class contract before contextual routing."
            return plan

    # The structured analytics IR is more specific than broad purpose labels
    # such as “grades” or “students”. Reuse the same safe planner used by the
    # deterministic path so both planner layers agree.
    analytics_query = contract.get("analytics_query")
    if isinstance(analytics_query, dict):
        plan = _analytics_plan(
            message,
            language,
            role,
            requester_student_id,
            requester_advisor_id,
            analytics_query,
        )
        plan["purpose_analysis"] = purpose
        plan["purpose_contract"] = contract
        plan["planner_warning"] = "V30 routed the structured analytics contract through the authoritative data agent."
        return plan

    # If the AI is unsure and no database is needed, normal chat.
    if domain == "clarify":
        plan = _normal_chat_plan(message, language, role, requester_student_id, requester_advisor_id, reason)
        plan["arguments"]["reason"] = "unsupported_realtime" if contract.get("is_realtime_request") else "clarification_needed"
        plan["arguments"]["answer_style"] = "clarification"
        plan["orchestrator"]["version"] = "v30_authoritative"
        plan["purpose_analysis"] = purpose
        plan["purpose_contract"] = contract
        plan["planner_warning"] = "V30 refused an unsupported live-data request and requested clarification."
        return plan

    if domain == "normal_chat" or not purpose.get("should_use_database"):
        plan = _normal_chat_plan(message, language, role, requester_student_id, requester_advisor_id, reason)
        plan["orchestrator"]["version"] = "v3"
        plan["purpose_analysis"] = purpose
        plan["planner_warning"] = "Agent Orchestrator V3 used AI purpose reasoning: normal chat."
        return plan

    if domain in {"academic_records", "course_catalog"}:
        academic_query = (
            purpose.get("academic_query")
            if isinstance(purpose.get("academic_query"), dict)
            else parse_academic_query(message)
        )
        if not academic_query:
            academic_query = {
                "domain": domain,
                "query_type": "course_catalog" if domain == "course_catalog" else "student_academic_profile",
                "answer_style": "course_catalog" if domain == "course_catalog" else "summary",
                "requested_sections": [],
                "student_ids": _student_ids_from_purpose(purpose),
                "reason": "Purpose analysis selected normalized academic data.",
            }
        plan = _academic_plan(
            message,
            language,
            role,
            requester_student_id,
            requester_advisor_id,
            academic_query,
            reason,
        )
        plan["purpose_analysis"] = purpose
        plan["planner_warning"] = "V30 routed the question to its authoritative normalized academic source."
        return plan

    # Uploaded PDF/Excel/CSV knowledge.
    if domain == "documents":
        plan = _document_plan(message, language, role, requester_student_id, requester_advisor_id, reason)
        # purpose may distinguish count/list/search.
        collection_answer = (plan.get("arguments") or {}).get("answer_style") in {
            "document_compare",
            "document_collection_summary",
        }
        if collection_answer:
            plan["arguments"]["operation"] = "document_search"
        elif intent in {"count", "list"} or document_list_request(message):
            plan["arguments"]["operation"] = "list_documents"
        else:
            plan["arguments"]["operation"] = "document_search"
        plan["orchestrator"]["version"] = "v3"
        plan["purpose_analysis"] = purpose
        plan["planner_warning"] = "Agent Orchestrator V3 used contextual document purpose reasoning."
        return plan

    # University-wide subject/course questions.
    if domain == "subjects":
        subject_ranking = contract.get("subject_ranking") if isinstance(contract.get("subject_ranking"), dict) else {}
        answer_style = subject_ranking.get("answer_style") or "subject_summary"
        plan = _base_plan(
            message=message,
            language=language,
            role=role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_contextual_subject_agent",
            tool_name="mongodb_student_tool",
            arguments={
                "student_id": requester_student_id if role == "student" and requester_student_id else "ALL",
                "operation": "subject_summary",
                "requested_fields": ["student_id", "name", "program", "subject_grades"],
                "limit": 5000,
                "answer_style": answer_style,
                "top_n": subject_ranking.get("top_n", 10),
                "ranking_basis": subject_ranking.get("ranking_basis"),
                "recommendation_basis": subject_ranking.get("recommendation_basis"),
            },
            prompt="ADMIN_SUBJECT_AGENT_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT"),
            intent="query_subjects",
            domain="subjects",
            confidence=max(confidence, 0.9),
            reason=reason,
        )
        plan["orchestrator"]["version"] = "v3"
        plan["purpose_analysis"] = purpose
        plan["planner_warning"] = "Agent Orchestrator V3 used contextual subject purpose reasoning."
        return plan

    # Student records, grades, GPA.
    if domain in {"students", "student_grades", "student_gpa"}:
        sids = _student_ids_from_purpose(purpose)
        last_names = _last_names_from_purpose(purpose)
        shape = _student_shape_from_purpose(message, role, purpose)
        text = _low(message)
        student_ranking = parse_student_ranking_query(message)
        if student_ranking and role != "admin":
            plan = _normal_chat_plan(
                message, language, role, requester_student_id, requester_advisor_id,
                "University-wide GPA rankings are not available to this signed role.",
            )
            plan["arguments"].update({
                "reason": "student_ranking_not_available_for_role",
                "answer_style": "access_scope",
            })
            plan["orchestrator"]["version"] = "v30_authoritative"
            plan["purpose_analysis"] = purpose
            plan["purpose_contract"] = build_latest_message_contract(message)
            return plan
        if sids:
            if len(sids) == 1:
                args = {"student_id": sids[0], "operation": "read_students", "requested_student_ids": sids, **shape}
            else:
                args = {
                    "student_id": "ALL",
                    "operation": "read_students",
                    "query_filter": {"student_id": {"$in": sids}},
                    "sort": [{"field": "student_id", "direction": "asc"}],
                    "limit": len(sids),
                    "requested_student_ids": sids,
                    **shape,
                }
        elif last_names and role != "student":
            surname_pattern = "|".join(re.escape(value) for value in last_names)
            args = {
                "student_id": "ALL",
                "operation": "read_students",
                "query_filter": {"name": {"$regex": rf"(?:^|\s)(?:{surname_pattern})(?:$|\s)"}},
                "sort": [{"field": "student_id", "direction": "asc"}],
                "limit": 200,
                "requested_last_names": last_names,
                **shape,
            }
        elif role == "student":
            args = {"student_id": requester_student_id or "S001", "operation": "read_students", **shape}
        else:
            limit = _limit_from_text(text, 20)
            operation = "read_students"
            sort: List[Dict[str, str]] = []
            query_filter: Dict[str, Any] = {}
            requested = shape.get("requested_fields") or ["student_id", "name", "program", "gpa", "academic_status"]
            answer_style = shape.get("answer_style") or "summary"
            allow_full_chat_list = False
            directory_request = (
                intent == "list"
                and not (_contains_any(text, GRADE_WORDS) or _contains_any(text, GPA_WORDS) or _contains_any(text, PROFILE_WORDS))
            ) or (
                ("รายชื่อ" in text or "จัดเรียง" in text or "list all" in text or "all students" in text)
                and _contains_any(text, STUDENT_WORDS)
                and not (_contains_any(text, GRADE_WORDS) or _contains_any(text, GPA_WORDS) or _contains_any(text, PROFILE_WORDS))
            )
            if intent == "count":
                operation = "count"
                answer_style = "count"
            elif directory_request:
                if wants_table:
                    operation = "read_students"
                    answer_style = "student_table"
                    requested = [
                        "student_id",
                        "name",
                        "program",
                        "gpa",
                        "academic_status",
                    ]
                    limit = 5000
                    allow_full_chat_list = False
                else:
                    operation = "list_names"
                    answer_style = "names"
                    requested = ["student_id", "name"]
                    limit = 5000
                    allow_full_chat_list = not wants_report
            elif intent == "rank":
                sort = [{"field": "gpa", "direction": "asc" if any(w in text for w in ["low", "weak", "worst", "bottom"]) else "desc"}]
                requested = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
                answer_style = "rank"
            # V5 aggregate/filter contract: parse the latest message for numeric GPA comparisons
            # before executing the database call. This supports imperfect phrasing like
            # "how many student gpa lower 3.0" and "student grade lower than 3.0".
            # V15 scope-first contract: distinguish the whole university from a
            # programme/subject query before selecting an aggregate operation.
            # This stops "how many students are in the university" from being
            # routed to study_term_aggregate with an empty term.
            total_count_query = parse_total_student_count_query(message)
            metric_query = parse_student_metric_query(message) or purpose.get("metric_query")
            student_ranking = parse_student_ranking_query(message) or purpose.get("student_ranking")
            stat_query = parse_student_statistic_query(message) or purpose.get("stat_query")
            study_query = parse_student_study_query(message) or purpose.get("study_query")
            # V10: if the AI reasoner extracted subject_terms such as ["Law"],
            # never let the older raw-text extractor replace it with filler like "what is".
            purpose_entities = purpose.get("explicit_entities") if isinstance(purpose.get("explicit_entities"), dict) else {}
            subject_terms = [str(x).strip() for x in (purpose_entities.get("subject_terms") or []) if str(x).strip()]
            if subject_terms:
                preferred_term = subject_terms[0]
                if isinstance(stat_query, dict):
                    stat_query["study_term"] = preferred_term
                if isinstance(study_query, dict):
                    study_query["study_term"] = preferred_term
            if isinstance(student_ranking, dict):
                operation = "rank_students"
                requested = student_ranking.get("requested_fields") or ["student_id", "name", "program", "gpa", "academic_status"]
                answer_style = "student_rank"
                sort = [{"field": student_ranking.get("field") or "gpa", "direction": student_ranking.get("direction") or "desc"}]
                limit = max(1, min(int(student_ranking.get("top_n") or 10), 100))
                stat_query = None
                study_query = None
            elif isinstance(total_count_query, dict):
                operation = "count"
                answer_style = "count"
                requested = ["student_id", "name"]
                limit = 5000
                # Do not attach a false study/metric contract to a total count.
                stat_query = None
                study_query = None
            elif isinstance(metric_query, dict):
                query_filter = dict(metric_query.get("query_filter") or {})
                sort = list(metric_query.get("sort") or sort)
                requested = ["student_id", "name", "program", "gpa", "academic_status"]
                operation = "filter_summary"
                answer_style = metric_query.get("answer_style") or ("aggregate_count" if metric_query.get("intent") == "count" else "aggregate_filter")
                limit = 5000 if metric_query.get("intent") == "count" else max(limit, 50)
            elif isinstance(stat_query, dict):
                operation = stat_query.get("operation") or "study_term_aggregate"
                requested = stat_query.get("requested_fields") or ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
                answer_style = stat_query.get("answer_style") or "study_statistic"
                limit = 5000
            elif isinstance(study_query, dict):
                operation = "study_term_search"
                ranking = study_query.get("ranking") if isinstance(study_query.get("ranking"), dict) else None
                requested = study_query.get("requested_fields") or ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
                if ranking and "gpa" not in requested:
                    requested = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]
                answer_style = study_query.get("answer_style") or ("study_rank" if ranking else "study_search")
                if ranking:
                    sort = [{"field": ranking.get("field") or "gpa", "direction": ranking.get("direction") or "desc"}]
                    limit = max(1, min(int(ranking.get("top_n") or 20), 200))
                else:
                    limit = 5000 if study_query.get("intent") == "count" else max(limit, 50)
            args = {
                "student_id": "ALL",
                "operation": operation,
                "requested_fields": allowed_student_fields_for_role(role, requested),
                "query_filter": query_filter,
                "sort": sort,
                "limit": 5000 if operation in {"count", "list_names"} else limit,
                "answer_style": answer_style,
                "display_limit": 300 if allow_full_chat_list else limit,
                "create_report_if_over": 20 if (wants_table or wants_report) else 5000 if allow_full_chat_list else 20,
                "allow_full_chat_list": allow_full_chat_list,
                "total_count_query": total_count_query if isinstance(locals().get("total_count_query"), dict) else None,
                "metric_query": metric_query if isinstance(locals().get("metric_query"), dict) else None,
                "study_query": study_query if isinstance(locals().get("study_query"), dict) else None,
                "stat_query": stat_query if isinstance(locals().get("stat_query"), dict) else None,
                "student_ranking": student_ranking if isinstance(locals().get("student_ranking"), dict) else None,
                "scope": (stat_query.get("scope") if isinstance(locals().get("stat_query"), dict) else (total_count_query.get("scope") if isinstance(locals().get("total_count_query"), dict) else None)),
                "study_term": (stat_query.get("study_term") if isinstance(locals().get("stat_query"), dict) else (study_query.get("study_term") if isinstance(locals().get("study_query"), dict) else None)),
                "statistic": stat_query.get("statistic") if isinstance(locals().get("stat_query"), dict) else None,
                "metric_field": stat_query.get("field") if isinstance(locals().get("stat_query"), dict) else None,
                "ranking": study_query.get("ranking") if isinstance(locals().get("study_query"), dict) else None,
                "top_n": student_ranking.get("top_n") if isinstance(locals().get("student_ranking"), dict) else None,
                "presentation": presentation,
                "table_columns": requested if wants_table else [],
                "force_report": wants_report,
            }
            if operation in {"study_term_aggregate", "student_population_aggregate"}:
                args["display_limit"] = min(_limit_from_text(text, 50), 100)
            elif operation == "rank_students":
                args["display_limit"] = limit
        plan = _base_plan(
            message=message,
            language=language,
            role=role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_contextual_student_agent",
            tool_name="mongodb_student_tool",
            arguments=args,
            prompt="ADMIN_GRADE_ANALYST_PROMPT" if role == "admin" else ("ADVISOR_GRADE_ANALYST_PROMPT" if role == "advisor" else "STUDENT_SELF_DATA_AGENT_PROMPT"),
            intent="query_students",
            domain="students",
            confidence=max(confidence, 0.88),
            reason=reason,
        )
        plan["orchestrator"]["version"] = "v15"
        plan["purpose_analysis"] = purpose
        plan["purpose_contract"] = build_latest_message_contract(message)
        if last_names:
            plan["validation_contract"]["required_last_names"] = last_names
        if isinstance((plan.get("arguments") or {}).get("study_query"), dict) or isinstance((plan.get("arguments") or {}).get("stat_query"), dict):
            plan["purpose_contract"]["study_term"] = (plan.get("arguments") or {}).get("study_term")
            plan["purpose_contract"]["ranking"] = (plan.get("arguments") or {}).get("ranking")
            plan["purpose_contract"]["statistic"] = (plan.get("arguments") or {}).get("statistic")
            plan["purpose_contract"]["expected_operation"] = (plan.get("arguments") or {}).get("operation")
        plan["planner_warning"] = "Agent Orchestrator V15 used scope-first student query reasoning + validation contract."
        return plan

    # Advisors.
    if domain == "advisors":
        aids = _advisor_ids_from_purpose(purpose)
        advisor_id = aids[0] if aids else ("ALL" if role == "admin" and intent in {"count", "list"} else (requester_advisor_id or "ALL"))
        operation = "list_advisors" if advisor_id == "ALL" else "read_advisors"
        plan = _base_plan(
            message=message,
            language=language,
            role=role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            selected_agent=f"{role}_contextual_advisor_agent",
            tool_name="mongodb_advisor_tool",
            arguments={"advisor_id": advisor_id, "operation": operation, "answer_style": "summary"},
            prompt="ADMIN_SUPER_AGENT_PROMPT" if role == "admin" else "ADVISOR_AGENT_PROMPT",
            intent="query_advisors",
            domain="advisors",
            confidence=max(confidence, 0.86),
            reason=reason,
        )
        plan["orchestrator"]["version"] = "v3"
        plan["purpose_analysis"] = purpose
        plan["planner_warning"] = "Agent Orchestrator V3 used contextual advisor purpose reasoning."
        return plan

    if domain == "programs":
        qtype = "programs"
    elif domain == "campus_info":
        qtype = "campus_info"
    elif domain == "database_map":
        qtype = "database_map"
    else:
        return None

    plan = _base_plan(
        message=message,
        language=language,
        role=role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        selected_agent=f"{role}_contextual_{domain}_agent",
        tool_name="postgres_university_tool",
        arguments={"query_type": qtype, "operation": "schema" if qtype == "database_map" else "search", "keyword": friendly_clean_query(message), "answer_style": "summary"},
        prompt="ADMIN_DATABASE_ARCHITECT_PROMPT" if qtype == "database_map" else "ADMIN_PROGRAM_AGENT_PROMPT",
        intent=f"query_{domain}",
        domain=domain,
        confidence=max(confidence, 0.82),
        reason=reason,
    )
    plan["orchestrator"]["version"] = "v3"
    plan["purpose_analysis"] = purpose
    plan["planner_warning"] = f"Agent Orchestrator V3 used contextual {domain} purpose reasoning."
    return plan


def plan_from_purpose(
    *,
    message: str,
    language: str,
    user_role: str,
    purpose: Dict[str, Any],
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Map interpreted purpose to tools, then enforce the student data boundary."""
    plan = _plan_from_purpose_unchecked(
        message=message,
        language=language,
        user_role=user_role,
        purpose=purpose,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        chat_history=chat_history,
    )
    return enforce_student_scope_plan(
        plan,
        message=message,
        user_role=user_role,
        requester_student_id=requester_student_id,
    )


def create_contextual_orchestrator_plan(
    *,
    message: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    purpose = analyze_user_purpose(
        message=message,
        language=language,
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        chat_history=chat_history,
    )
    plan = plan_from_purpose(
        message=message,
        language=language,
        user_role=user_role,
        purpose=purpose,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        chat_history=chat_history,
    )
    return plan
