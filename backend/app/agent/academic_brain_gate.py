"""Live read-only gate for the V30 normalized academic brain.

Run inside the backend container:
    python -m app.agent.academic_brain_gate

The gate verifies routing, MCP policy, PostgreSQL retrieval, validation, and
deterministic formatting. It reports only pass/fail metadata, never student
names, grades, attendance values, balances, or document content.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import requests

from app.agent.final_answer_writer import deterministic_database_answer
from app.agent.result_validator import validate_tool_result
from app.agent.tool_planner import deterministic_plan
from app.db.postgres import get_connection
from app.production_security import mcp_service_key


GATE_VERSION = "V30_ACADEMIC_BRAIN_LIVE_GATE_1"


def _mcp_call(
    tool_name: str,
    arguments: Dict[str, Any],
    user_role: str,
    *,
    requester_student_id: str | None = None,
    requester_advisor_id: str | None = None,
) -> Dict[str, Any]:
    base = (os.getenv("MCP_SERVER_URL") or "http://mcp_server:9000").rstrip("/")
    response = requests.post(
        f"{base}/mcp/call-tool",
        timeout=10,
        headers={"X-MCP-Service-Key": mcp_service_key()},
        json={
            "tool_name": tool_name,
            "arguments": arguments,
            "user_role": user_role,
            "requester_student_id": requester_student_id,
            "requester_advisor_id": requester_advisor_id,
            "language": "en",
        },
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"success": False, "error": "Invalid MCP payload."}


def _payload_type(payload: Dict[str, Any]) -> str:
    data: Any = payload.get("data")
    if isinstance(data, dict) and data.get("success") is True:
        data = data.get("data")
    return str(data.get("type") or "") if isinstance(data, dict) else ""


def _assigned_pair() -> tuple[str, str]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT student_id, advisor_id
                FROM student_course_enrollments
                WHERE student_id IS NOT NULL AND advisor_id IS NOT NULL
                ORDER BY student_id, advisor_id
                LIMIT 1
                """
            )
            row = cur.fetchone() or {}
            return str(row.get("student_id") or ""), str(row.get("advisor_id") or "")
    finally:
        conn.close()


def _brain_case(
    case_id: str,
    message: str,
    role: str,
    *,
    requester_student_id: str | None = None,
    requester_advisor_id: str | None = None,
) -> Dict[str, Any]:
    plan = deterministic_plan(
        message,
        "en",
        role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )
    result = _mcp_call(
        plan["tool_name"],
        plan.get("arguments") or {},
        role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )
    validation = validate_tool_result(message, plan, result)
    answer = deterministic_database_answer(message, "en", plan, result) or ""
    expected_type = {
        "student_academic_profile": "student_academic_profile",
        "course_catalog": "course_catalog",
        "academic_risk_summary": "academic_risk_summary",
        "academic_overview": "academic_overview",
    }.get(str((plan.get("arguments") or {}).get("query_type") or ""), "")
    passed = bool(
        result.get("success") is True
        and validation.get("is_valid") is True
        and answer
        and (not expected_type or _payload_type(result) == expected_type)
    )
    return {
        "case_id": case_id,
        "passed": passed,
        "tool": plan.get("tool_name"),
        "query_type": (plan.get("arguments") or {}).get("query_type"),
        "answer_style": (plan.get("arguments") or {}).get("answer_style"),
        "payload_type": _payload_type(result),
        "validated": validation.get("is_valid") is True,
        "grounded_answer_created": bool(answer),
        "problems": validation.get("problems") or [],
    }


def run_academic_brain_gate() -> Dict[str, Any]:
    cases: List[Dict[str, Any]] = [
        _brain_case("admin_attendance", "show S001 attendance", "admin"),
        _brain_case("admin_finance", "show S001 tuition balance", "admin"),
        _brain_case(
            "student_own_finance",
            "show my tuition balance",
            "student",
            requester_student_id="S001",
        ),
        _brain_case(
            "student_own_scholarship",
            "show my scholarship",
            "student",
            requester_student_id="S001",
        ),
        _brain_case(
            "student_own_assessments",
            "show my midterm score",
            "student",
            requester_student_id="S001",
        ),
        _brain_case("formal_course_catalog", "show course catalog", "admin"),
        _brain_case("admin_risk_summary", "show academic risk summary", "admin"),
    ]

    student_id, advisor_id = _assigned_pair()
    if student_id and advisor_id:
        cases.append(
            _brain_case(
                "advisor_assigned_attendance",
                f"show {student_id} attendance",
                "advisor",
                requester_advisor_id=advisor_id,
            )
        )
    else:
        cases.append({
            "case_id": "advisor_assigned_attendance",
            "passed": False,
            "problems": ["No advisor enrollment assignment exists in the live normalized dataset."],
        })

    denied_finance = _mcp_call(
        "postgres_university_tool",
        {
            "query_type": "student_academic_profile",
            "student_id": student_id or "S001",
            "requested_sections": ["financial_accounts"],
        },
        "advisor",
        requester_advisor_id=advisor_id or "A001",
    )
    cases.append({
        "case_id": "advisor_finance_denied",
        "passed": denied_finance.get("success") is False,
        "policy_denied": denied_finance.get("success") is False,
    })

    rejected_worker = _mcp_call(
        "database_worker_tool",
        {"operation": "future_unreviewed_operation"},
        "admin",
    )
    cases.append({
        "case_id": "unknown_database_worker_denied",
        "passed": rejected_worker.get("success") is False,
        "policy_denied": rejected_worker.get("success") is False,
    })

    passed = sum(1 for case in cases if case.get("passed"))
    return {
        "version": GATE_VERSION,
        "success": passed == len(cases),
        "summary": {"total": len(cases), "passed": passed, "failed": len(cases) - passed},
        "privacy": "No student values, names, IDs, grades, attendance rates, or balances are included.",
        "cases": cases,
    }


if __name__ == "__main__":
    report = run_academic_brain_gate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["success"] else 1)
