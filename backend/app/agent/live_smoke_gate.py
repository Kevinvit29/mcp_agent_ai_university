"""V25 live, read-only environment smoke checks.

These checks verify the real Docker services after a deployment.  They do *not*
call Gemini, write to MongoDB/PostgreSQL, or return student names, IDs, grades,
or document text.  The report is safe to show in the admin System panel.

The goal is deliberately narrow: prove that the live services, canonical source
rules, and the MCP read path are available before we accept the release.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests
from pymongo import MongoClient

from app.db.postgres import get_connection
from app.production_security import mcp_service_key

LIVE_SMOKE_GATE_VERSION = "V25_LIVE_READ_ONLY_SMOKE_GATE"
_REQUIRED_POSTGRES_TABLES = (
    "chat_sessions",
    "chat_messages",
    "admin_documents",
    "advisor_documents",
    "student_subjects",
    "ai_data_agents",
    "ai_data_chunks",
)
_REQUIRED_MCP_TOOLS = {"mongodb_student_tool", "postgres_university_tool"}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _case(
    case_id: str,
    title: str,
    passed: bool,
    status: str,
    details: Dict[str, Any],
    *,
    severity: str = "blocker",
    note: str = "",
) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "title": title,
        "passed": bool(passed),
        "status": status,
        "severity": severity,
        "details": details,
        "note": note,
    }


def _mongo_snapshot(mongo_uri: str, mongo_db_name: str) -> Dict[str, Any]:
    """Return aggregate-only Mongo facts.  No student rows leave this helper."""
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2500)
    try:
        client.admin.command("ping")
        db = client[mongo_db_name]
        students = db["students"]
        advisors = db["advisors"]
        student_count = _as_int(students.count_documents({}))
        advisor_count = _as_int(advisors.count_documents({}))
        missing_student_id = _as_int(students.count_documents({"$or": [{"student_id": {"$exists": False}}, {"student_id": None}, {"student_id": ""}]}))
        missing_program = _as_int(students.count_documents({"$or": [{"program": {"$exists": False}}, {"program": None}, {"program": ""}]}))
        return {
            "database": mongo_db_name,
            "student_count": student_count,
            "advisor_count": advisor_count,
            "missing_student_id_count": missing_student_id,
            "missing_program_count": missing_program,
        }
    finally:
        client.close()


def _postgres_snapshot(connection_factory: Callable[[], Any] = get_connection) -> Dict[str, Any]:
    """Read public table status and counts using fixed, non-user-controlled SQL."""
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = ANY(%s)
                """,
                (list(_REQUIRED_POSTGRES_TABLES),),
            )
            table_rows = cur.fetchall() or []
            present = {str(row.get("table_name")) for row in table_rows if isinstance(row, dict)}

            counts: Dict[str, Optional[int]] = {}
            # All names below are internal constants, never request parameters.
            # A missing table should be reported as missing, not turn the entire
            # PostgreSQL probe into an opaque SQL exception.
            for table_name in ("admin_documents", "advisor_documents", "student_subjects", "ai_data_agents", "ai_data_chunks"):
                if table_name not in present:
                    counts[table_name] = None
                    continue
                cur.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
                row = cur.fetchone() or {}
                counts[table_name] = _as_int(row.get("count"))

        return {
            "required_tables": list(_REQUIRED_POSTGRES_TABLES),
            "present_tables": sorted(present),
            "missing_tables": sorted(set(_REQUIRED_POSTGRES_TABLES) - present),
            "counts": counts,
        }
    finally:
        conn.close()


def _mcp_snapshot(
    mcp_base_url: str,
    request_get: Callable[..., Any] = requests.get,
    request_post: Callable[..., Any] = requests.post,
) -> Dict[str, Any]:
    """Exercise a safe, read-only MCP count call; no private records are requested."""
    base = (mcp_base_url or "http://mcp_server:9000").rstrip("/")
    health = request_get(f"{base}/health/ready", timeout=3)
    tools_response = request_get(f"{base}/tools", timeout=3)
    health_payload = health.json() if hasattr(health, "json") else {}
    tools_payload = tools_response.json() if hasattr(tools_response, "json") else {}
    tool_names = {
        str(item.get("name"))
        for item in (tools_payload.get("tools") or [])
        if isinstance(item, dict)
    }

    # Count is PDPA-safe and does not reveal a student row.  It proves gateway →
    # policy → Mongo tool → response wrapping all work together.
    count_response = request_post(
        f"{base}/mcp/call-tool",
        timeout=5,
        headers={"X-MCP-Service-Key": mcp_service_key()},
        json={
            "tool_name": "mongodb_student_tool",
            "arguments": {"student_id": "ALL", "operation": "count", "requested_fields": ["student_id"]},
            "user_role": "admin",
            "language": "en",
        },
    )
    count_payload = count_response.json() if hasattr(count_response, "json") else {}
    data = count_payload.get("data") if isinstance(count_payload, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data.get("data")
    mcp_count = _as_int((data or {}).get("count"), default=-1) if isinstance(data, dict) else -1

    return {
        "health_status_code": getattr(health, "status_code", None),
        "health_status": health_payload.get("status") if isinstance(health_payload, dict) else None,
        "tools_status_code": getattr(tools_response, "status_code", None),
        "tool_names": sorted(tool_names),
        "missing_required_tools": sorted(_REQUIRED_MCP_TOOLS - tool_names),
        "count_status_code": getattr(count_response, "status_code", None),
        "count_call_success": bool(isinstance(count_payload, dict) and count_payload.get("success") is True),
        "mcp_student_count": mcp_count,
    }


def run_live_smoke_gate(
    *,
    mongo_uri: Optional[str] = None,
    mongo_db_name: Optional[str] = None,
    mcp_base_url: Optional[str] = None,
    mongo_reader: Callable[[str, str], Dict[str, Any]] = _mongo_snapshot,
    postgres_reader: Callable[[], Dict[str, Any]] = _postgres_snapshot,
    mcp_reader: Callable[[str], Dict[str, Any]] = _mcp_snapshot,
) -> Dict[str, Any]:
    """Run V25's live read-only smoke gate and produce an admin-safe report."""
    mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://mongo:27017")
    mongo_db_name = mongo_db_name or os.getenv("MONGO_DB", "university_mongo")
    mcp_base_url = mcp_base_url or os.getenv("MCP_SERVER_URL", "http://mcp_server:9000")
    cases: List[Dict[str, Any]] = []
    mongo: Dict[str, Any] = {}
    postgres: Dict[str, Any] = {}
    mcp: Dict[str, Any] = {}

    try:
        mongo = mongo_reader(mongo_uri, mongo_db_name)
        students = _as_int(mongo.get("student_count"))
        bad_ids = _as_int(mongo.get("missing_student_id_count"))
        cases.append(_case(
            "mongo_canonical_student_master",
            "MongoDB canonical student master",
            students > 0 and bad_ids == 0,
            "passed" if students > 0 and bad_ids == 0 else "failed",
            {
                "student_count": students,
                "advisor_count": _as_int(mongo.get("advisor_count")),
                "missing_student_id_count": bad_ids,
                "missing_program_count": _as_int(mongo.get("missing_program_count")),
            },
            note="Counts only. No student names, IDs, grades, or contact data are included.",
        ))
    except Exception as exc:
        cases.append(_case(
            "mongo_canonical_student_master",
            "MongoDB canonical student master",
            False,
            "unavailable",
            {"error": str(exc)[:300]},
            note="Cannot verify the canonical student source until MongoDB is reachable.",
        ))

    try:
        postgres = postgres_reader()
        missing = list(postgres.get("missing_tables") or [])
        cases.append(_case(
            "postgres_core_tables",
            "PostgreSQL core tables",
            not missing,
            "passed" if not missing else "failed",
            {
                "required_table_count": len(_REQUIRED_POSTGRES_TABLES),
                "present_table_count": len(postgres.get("present_tables") or []),
                "missing_tables": missing,
                "aggregate_counts": postgres.get("counts") or {},
            },
            note="Only table names and aggregate counts are checked.",
        ))

        relation_rows = _as_int((postgres.get("counts") or {}).get("student_subjects"))
        cases.append(_case(
            "source_truth_population_boundary",
            "Source-of-truth population boundary",
            bool(mongo) and _as_int(mongo.get("student_count")) > 0,
            "passed" if bool(mongo) and _as_int(mongo.get("student_count")) > 0 else "blocked",
            {
                "canonical_population_source": "MongoDB university_mongo.students",
                "canonical_student_count": _as_int(mongo.get("student_count")),
                "postgres_relationship_row_count": relation_rows,
                "rule": "PostgreSQL student_subjects supports permissions only and is never used as the total student population.",
            },
            note="This guard prevents relationship rows from becoming a false university student total.",
        ))
    except Exception as exc:
        cases.append(_case(
            "postgres_core_tables",
            "PostgreSQL core tables",
            False,
            "unavailable",
            {"error": str(exc)[:300]},
            note="Cannot verify documents, sessions, or data-agent tables until PostgreSQL is reachable.",
        ))
        cases.append(_case(
            "source_truth_population_boundary",
            "Source-of-truth population boundary",
            False,
            "blocked",
            {"error": "PostgreSQL snapshot unavailable."},
            note="Population provenance could not be checked completely.",
        ))

    try:
        mcp = mcp_reader(mcp_base_url)
        health_ok = mcp.get("health_status") in {"healthy", "ready", "live"}
        tools_ok = not (mcp.get("missing_required_tools") or [])
        count_ok = bool(mcp.get("count_call_success")) and _as_int(mcp.get("mcp_student_count"), -1) >= 0
        cases.append(_case(
            "mcp_gateway_read_path",
            "MCP gateway read-only count path",
            health_ok and tools_ok and count_ok,
            "passed" if health_ok and tools_ok and count_ok else "failed",
            {
                "health": mcp.get("health_status"),
                "missing_required_tools": mcp.get("missing_required_tools") or [],
                "count_call_success": bool(mcp.get("count_call_success")),
                "mcp_student_count": _as_int(mcp.get("mcp_student_count"), -1),
            },
            note="The request is an admin count only; no student record is requested or displayed.",
        ))
    except Exception as exc:
        cases.append(_case(
            "mcp_gateway_read_path",
            "MCP gateway read-only count path",
            False,
            "unavailable",
            {"error": str(exc)[:300]},
            note="Cannot prove the backend-to-MCP read path until the gateway is reachable.",
        ))

    failed = [item["case_id"] for item in cases if not item.get("passed")]
    passed = len(cases) - len(failed)
    total = len(cases)
    return {
        "success": not failed,
        "gate_version": LIVE_SMOKE_GATE_VERSION,
        "mode": "live Docker services; aggregate-only, read-only, no Gemini calls",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "passed": passed,
            "failed": len(failed),
            "total": total,
            "percentage": round((passed / total * 100) if total else 0.0, 1),
        },
        "failed_case_ids": failed,
        "cases": cases,
        "next_action": (
            "Safe to continue when all live checks pass. If a case fails, fix Docker/service connectivity or the named source first; do not bypass the source-of-truth rule."
            if not failed
            else "Fix the failed service/source before accepting the release. No user data was changed by this test."
        ),
    }
