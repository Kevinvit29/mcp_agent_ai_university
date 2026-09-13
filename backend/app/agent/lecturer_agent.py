"""Lecturer planner with a strict signed teaching-assignment scope."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.advisor_agent import plan_as_advisor_agent


def plan_as_lecturer_agent(
    message: str,
    language: str,
    teaching_scope_id: Optional[str],
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Reuse the mature classroom parser without inheriting the Advisor role.

    The scope ID comes only from the signed Lxxx token.  The PostgreSQL tool
    binds every returned row to that assignment, course, and student.
    """
    plan = plan_as_advisor_agent(message, language, teaching_scope_id, chat_history)
    plan["user_role"] = "lecturer"
    plan["selected_agent"] = str(plan.get("selected_agent") or "lecturer_agent").replace("advisor", "lecturer")
    if str(plan.get("role_prompt_name") or "").startswith("ADVISOR_"):
        plan["role_prompt_name"] = str(plan["role_prompt_name"]).replace("ADVISOR_", "LECTURER_", 1)
    arguments = plan.setdefault("arguments", {})
    arguments["user_role"] = "lecturer"
    arguments["requester_advisor_id"] = teaching_scope_id
    if arguments.get("answer_style") == "advisor_scope":
        arguments["answer_style"] = "lecturer_scope"
    plan["reason"] = str(plan.get("reason") or "").replace("Advisor", "Lecturer").replace("advisor", "lecturer")
    return plan
