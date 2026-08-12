import os
import hmac
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
from pymongo import MongoClient

from app.tools.mongo_tool import mongodb_student_tool, mongodb_advisor_tool
from app.tools.postgres_tool import postgres_university_tool
from app.tools.pdf_tool import pdf_tool
from app.tools.excel_tool import excel_tool
from app.tools.image_tool import image_tool, analyze_document_image
from app.policy import access_scope_summary, check_pdpa_policy, minimize_requested_fields, mask_sensitive_data

from app.tools.database_worker_tool import database_worker_tool

app = FastAPI(title="MCP Server Gateway", version="2.0.0")


def _mcp_key() -> str:
    value = (os.getenv("MCP_INTERNAL_KEY") or "").strip()
    env = (os.getenv("APP_ENV") or "development").strip().lower()
    if not value:
        if env in {"production", "prod"}:
            raise RuntimeError("MCP_INTERNAL_KEY is required in production.")
        return "development-only-change-this-mcp-key-before-production"
    if env in {"production", "prod"} and len(value) < 32:
        raise RuntimeError("MCP_INTERNAL_KEY must be at least 32 characters in production.")
    return value


class InternalGatewayMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/mcp/call-tool":
            supplied = (request.headers.get("x-mcp-service-key") or "").strip()
            try:
                allowed = hmac.compare_digest(supplied, _mcp_key())
            except RuntimeError:
                allowed = False
            if not allowed:
                return JSONResponse(status_code=401, content={"success": False, "error": "Internal gateway authentication failed."})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


app.add_middleware(InternalGatewayMiddleware)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB", "university_mongo")

mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB_NAME]

class ToolCall(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    user_role: Optional[str] = None
    requester_student_id: Optional[str] = None
    requester_advisor_id: Optional[str] = None
    language: Optional[str] = "en"


AVAILABLE_TOOLS = {
    "mongodb_student_tool": mongodb_student_tool,
    "mongodb_advisor_tool": mongodb_advisor_tool,
    "postgres_university_tool": postgres_university_tool,
    "pdf_tool": pdf_tool,
    "excel_tool": excel_tool,
    "image_tool": image_tool,
    "analyze_document_image": analyze_document_image,
    "database_worker_tool": database_worker_tool,
}


@app.get("/")
def root():
    return {"message": "MCP Server Gateway", "available_tools": list(AVAILABLE_TOOLS.keys())}


@app.get("/tools")
def list_tools():
    return {"tools": [{"name": name} for name in AVAILABLE_TOOLS.keys()]}


@app.post("/mcp/call-tool")
def call_tool(tool_call: ToolCall):
    tool_name = tool_call.tool_name
    arguments = tool_call.arguments or {}
    user_role = (tool_call.user_role or "").lower()
    requester_student_id = tool_call.requester_student_id
    requester_advisor_id = tool_call.requester_advisor_id

    if tool_name not in AVAILABLE_TOOLS:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool_name}")

    policy_result = check_pdpa_policy(
        tool_name=tool_name,
        arguments=arguments,
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )

    if not policy_result.get("allowed"):
        return {
            "success": False,
            "tool_name": tool_name,
            "error": policy_result.get("reason"),
            "policy_note": "Request blocked by PDPA policy.",
        }

    safe_arguments = minimize_requested_fields(
        tool_name=tool_name,
        arguments=arguments,
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )
    safe_arguments["_user_role"] = user_role
    safe_arguments["_requester_student_id"] = requester_student_id
    safe_arguments["_requester_advisor_id"] = requester_advisor_id

    try:
        context = {
        "user_role": user_role,
        "requester_student_id": requester_student_id,
        "requester_advisor_id": requester_advisor_id,
        "language": tool_call.language,
        "mongo_db": mongo_db,
        }

        tool_func = AVAILABLE_TOOLS[tool_name]

        try:
            raw_result = tool_func(safe_arguments, context)
        except TypeError:
            raw_result = tool_func(safe_arguments)

        if isinstance(raw_result, dict) and raw_result.get("success") is False:
            return {
                "success": False,
                "tool_name": tool_name,
                "error": raw_result.get("error")
            }

        safe_result = mask_sensitive_data(raw_result, user_role)

        return {
            "success": True,
            "tool_name": tool_name,
            "data": safe_result,
            "policy_note": policy_result.get("reason"),
            "access_scope": access_scope_summary(
                tool_name=tool_name,
                user_role=user_role,
                requester_student_id=requester_student_id,
                requester_advisor_id=requester_advisor_id,
            ),
        }

    except Exception:
        return {"success": False, "tool_name": tool_name, "error": "MCP tool execution failed safely. Check internal service logs with the request ID."}

@app.get("/health")
def health_check():
    return {"status": "live"}


@app.get("/health/live")
def health_live():
    return {"status": "live"}


@app.get("/health/ready")
def health_ready():
    try:
        mongo_client.admin.command("ping")
        return {"status": "ready", "mongo": "reachable"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "mongo": "unavailable"})
