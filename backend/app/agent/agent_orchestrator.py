"""Agent Orchestrator V3 public API.

This is the V3 brain layer:
User question -> contextual purpose reasoning -> schema-aware tool plan ->
MCP execution -> result validation/repair -> final answer writer.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.agent.tool_planner import create_orchestrator_plan, deterministic_plan
from app.agent.contextual_tool_planner import create_contextual_orchestrator_plan
from app.agent.result_validator import validate_tool_result, repair_plan_after_validation
from app.agent.final_answer_writer import write_final_answer
from app.agent.debug_trace import summarize_tool_result, safe_compact
from app.agent.conversation_state import (
    build_context_for_planner,
    last_user_message,
    resolve_followup_student_ids,
)
from app.agent.purpose_contract import build_latest_message_contract
from app.agent.student_scope import enforce_student_scope_plan
from app.db.postgres import get_local_router_hint


def _attach_local_context(
    plan: Dict[str, Any],
    message: str,
    chat_history: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    plan.setdefault("orchestrator_context", build_context_for_planner(message, chat_history))
    try:
        plan["local_training_hint"] = get_local_router_hint(message)
    except Exception:
        plan["local_training_hint"] = None
    return plan


def _enforce_signed_student_scope(
    plan: Dict[str, Any],
    *,
    message: str,
    user_role: str,
    requester_student_id: Optional[str],
) -> Dict[str, Any]:
    return enforce_student_scope_plan(
        plan,
        message=message,
        user_role=user_role,
        requester_student_id=requester_student_id,
    ) or plan


def plan_turn(
    *,
    message: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    fallback_router=None,
) -> Dict[str, Any]:
    resolved_ids = resolve_followup_student_ids(message, chat_history)
    explicit_ids = {
        value.upper()
        for value in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I)
    }
    inherited_ids = [value for value in resolved_ids if value not in explicit_ids]
    planning_message = message
    if inherited_ids:
        planning_message = (
            f"[Resolved conversation student IDs: {', '.join(inherited_ids)}]\n"
            f"{message}"
        )
        # “Compare that with S002” inherits both the earlier entity and the
        # earlier requested fact (for example tuition or attendance). Without
        # the topic, a comparison becomes an unrelated generic profile lookup.
        if re.search(r"\bcompare\s+(?:that|this|it)\b", message or "", flags=re.I):
            previous_topic = last_user_message(chat_history)
            if previous_topic:
                planning_message += f"\n[Previous requested topic: {previous_topic}]"

    # Exact database/file contracts do not need a generative model to choose a
    # tool. Resolve them locally first so rankings, IDs, answer sections, and
    # role boundaries stay stable and fast. Contextual AI remains available for
    # genuinely ambiguous conversation and follow-up questions.
    latest_contract = build_latest_message_contract(planning_message)
    if latest_contract.get("domain") != "normal_chat":
        direct_plan = deterministic_plan(
            planning_message,
            language,
            user_role,
            requester_student_id,
            requester_advisor_id,
            chat_history,
        )
        if direct_plan:
            direct_plan.setdefault("arguments", {})["original_question"] = message
            if inherited_ids:
                direct_plan["arguments"]["resolved_context_student_ids"] = inherited_ids
            direct_plan["planner_warning"] = (
                direct_plan.get("planner_warning")
                or "V30 used the deterministic latest-message contract before contextual AI."
            )
            direct_plan = _enforce_signed_student_scope(
                direct_plan,
                message=message,
                user_role=user_role,
                requester_student_id=requester_student_id,
            )
            return _attach_local_context(direct_plan, message, chat_history)

    # V3 purpose-first planning: the AI first interprets the full context/purpose
    # of the latest user message. Backend then maps that purpose to safe MCP tools.
    # If the reasoner or contextual mapper fails, V2 schema guards remain as a
    # reliable fallback instead of letting the chatbot guess.
    contextual_plan = create_contextual_orchestrator_plan(
        message=planning_message,
        language=language,
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        chat_history=chat_history,
    )
    if contextual_plan:
        contextual_plan.setdefault("arguments", {})["original_question"] = message
        if inherited_ids:
            contextual_plan["arguments"]["resolved_context_student_ids"] = inherited_ids
        contextual_plan = _enforce_signed_student_scope(
            contextual_plan,
            message=message,
            user_role=user_role,
            requester_student_id=requester_student_id,
        )
        return _attach_local_context(contextual_plan, message, chat_history)

    plan = create_orchestrator_plan(
        message=planning_message,
        language=language,
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        chat_history=chat_history,
        fallback_router=fallback_router,
    )
    plan.setdefault("arguments", {})["original_question"] = message
    if inherited_ids:
        plan["arguments"]["resolved_context_student_ids"] = inherited_ids
    plan = _enforce_signed_student_scope(
        plan,
        message=message,
        user_role=user_role,
        requester_student_id=requester_student_id,
    )
    return _attach_local_context(plan, message, chat_history)


def execute_validate_repair(
    *,
    message: str,
    language: str,
    user_role: str,
    plan: Dict[str, Any],
    call_tool: Callable[[Dict[str, Any]], Dict[str, Any]],
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    max_repairs: int = 2,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    trace_steps: List[Dict[str, Any]] = []
    plan.setdefault("orchestrator_version", "V7_DEBUG_TRACE_PANEL")

    if plan.get("tool_name") == "none":
        result = {"success": True, "data": None, "note": "No MCP tool needed; normal AI chat mode."}
        validation = {"is_valid": True, "expected_domain": "normal_chat", "actual_domain": "normal_chat", "problems": []}
        trace_steps.append({
            "step": "normal_chat_no_tool",
            "reason": "Planner selected no database/PDF/Excel tool for this turn.",
            "validation": validation,
        })
        plan["orchestrator_validation"] = validation
        plan["orchestrator_execution_trace"] = trace_steps
        return plan, result, validation

    trace_steps.append({
        "step": "initial_tool_plan",
        "tool_name": plan.get("tool_name"),
        "arguments": safe_compact(plan.get("arguments", {}), max_depth=3),
        "purpose": safe_compact(plan.get("purpose_analysis"), max_depth=2),
        "contract": safe_compact(plan.get("purpose_contract"), max_depth=2),
    })

    result = call_tool(plan)
    validation = validate_tool_result(message, plan, result)
    trace_steps.append({
        "step": "tool_execution",
        "tool_name": plan.get("tool_name"),
        "arguments": safe_compact(plan.get("arguments", {}), max_depth=3),
        "result_summary": summarize_tool_result(result),
        "validation": safe_compact(validation, max_depth=3),
    })

    repairs = 0
    while not validation.get("is_valid") and repairs < max_repairs:
        repaired = repair_plan_after_validation(
            message=message,
            language=language,
            user_role=user_role,
            plan=plan,
            tool_result=result,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            chat_history=chat_history,
        )
        trace_steps.append({
            "step": "repair_attempt",
            "attempt": repairs + 1,
            "previous_tool": plan.get("tool_name"),
            "previous_arguments": safe_compact(plan.get("arguments", {}), max_depth=3),
            "validation_problems": validation.get("problems") or [],
            "repaired_plan_found": bool(repaired),
            "repaired_tool": repaired.get("tool_name") if repaired else None,
            "repaired_arguments": safe_compact((repaired or {}).get("arguments", {}), max_depth=3) if repaired else None,
        })
        if not repaired:
            break
        plan = repaired
        result = call_tool(plan)
        validation = validate_tool_result(message, plan, result)
        trace_steps.append({
            "step": "repaired_tool_execution",
            "attempt": repairs + 1,
            "tool_name": plan.get("tool_name"),
            "arguments": safe_compact(plan.get("arguments", {}), max_depth=3),
            "result_summary": summarize_tool_result(result),
            "validation": safe_compact(validation, max_depth=3),
        })
        repairs += 1
    plan["orchestrator_validation"] = validation
    plan["orchestrator_execution_trace"] = trace_steps
    plan["repair_count"] = repairs
    return plan, result, validation


def answer_turn(
    *,
    message: str,
    language: str,
    user_role: str,
    plan: Dict[str, Any],
    tool_result: Dict[str, Any],
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    return write_final_answer(message, language, user_role, plan, tool_result, chat_history)
