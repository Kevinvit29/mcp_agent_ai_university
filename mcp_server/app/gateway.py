from typing import Dict, Any
from app.policy import check_pdpa_policy, minimize_requested_fields, mask_sensitive_data
from app.tools.mongo_tool import mongodb_student_tool, mongodb_advisor_tool
from app.tools.postgres_tool import postgres_university_tool
from app.tools.excel_tool import excel_tool
from app.tools.pdf_tool import pdf_tool

TOOL_REGISTRY = {
    "mongodb_student_tool": mongodb_student_tool,
    "mongodb_advisor_tool": mongodb_advisor_tool,
    "postgres_university_tool": postgres_university_tool,
    "excel_tool": excel_tool,
    "pdf_tool": pdf_tool,
}

def execute_tool_request(request: Dict[str, Any]) -> Dict[str, Any]:
    tool_name = request.get("tool_name")
    arguments = request.get("arguments", {})
    user_role = request.get("user_role", "student")
    requester_student_id = request.get("requester_student_id")
    requester_advisor_id = request.get("requester_advisor_id")
    language = request.get("language", "en")

    if tool_name not in TOOL_REGISTRY:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}"
        }

    

    policy_result = check_pdpa_policy(
        tool_name=tool_name,
        arguments=arguments,
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id
    )

    if not policy_result["allowed"]:
        return {
            "success": False,
            "error": policy_result["reason"],
            "policy_note": "Request blocked by PDPA policy guard."
        }

    safe_arguments = minimize_requested_fields(
    tool_name=tool_name,
    arguments=arguments,
    user_role=user_role,
    requester_student_id=requester_student_id,
    requester_advisor_id=requester_advisor_id
    )

    # Internal metadata for tool-level filtering. This is not controlled by the LLM.
    safe_arguments["_user_role"] = user_role
    safe_arguments["_requester_student_id"] = requester_student_id
    safe_arguments["_requester_advisor_id"] = requester_advisor_id

    raw_data = TOOL_REGISTRY[tool_name](safe_arguments)
    safe_data = mask_sensitive_data(raw_data, user_role)

    return {
        "success": True,
        "tool_name": tool_name,
        "data": safe_data,
        "policy_note": policy_result["reason"],
        "language": language
    }
