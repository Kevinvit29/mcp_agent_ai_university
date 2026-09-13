from typing import Optional, Dict, Any, List
from app.agent.student_agent import plan_as_student_agent
from app.agent.advisor_agent import plan_as_advisor_agent
from app.agent.admin_agent import plan_as_admin_agent
from app.agent.lecturer_agent import plan_as_lecturer_agent


def route_to_role_agent(
    message: str,
    language: str,
    user_role: str,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    chat_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    role = (user_role or "student").lower()

    if role == "student":
        return plan_as_student_agent(message, language, requester_student_id, chat_history)

    if role == "advisor":
        return plan_as_advisor_agent(message, language, requester_advisor_id, chat_history)

    if role == "lecturer":
        return plan_as_lecturer_agent(message, language, requester_advisor_id, chat_history)

    if role == "admin":
        return plan_as_admin_agent(message, language, chat_history)

    return plan_as_student_agent(message, language, requester_student_id, chat_history)
