from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, Tuple, Dict, Any, List
import re
import os
import json
import uuid
import time
import requests
from io import BytesIO

import pandas as pd
from pymongo import MongoClient

from pypdf import PdfReader
import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageFilter
import pytesseract

from app.models.schemas import ChatRequest, ChatResponse, AnswerFeedbackRequest, LearningReviewRequest
from app.agent.role_router import route_to_role_agent
from app.agent.answer_source import build_answer_source
from app.agent.answer_failures import safe_failure_message
from app.agent.agent_orchestrator import plan_turn, execute_validate_repair, answer_turn
from app.agent.ai_client import ai_generate_text
from app.agent.debug_trace import build_debug_trace, summarize_tool_result, safe_compact
from app.agent.evaluation_suite import run_query_contract_evaluation
from app.agent.document_qa import run_document_grounding_checks
from app.agent.end_to_end_gate import run_end_to_end_gate
from app.agent.academic_brain_gate import run_academic_brain_gate
from app.agent.live_smoke_gate import run_live_smoke_gate
from app.agent.controlled_learning import (
    clean_feedback_rating, clean_review_action, safe_feedback_text,
    VALID_MEMORY_ACTIONS, VALID_FEEDBACK_ACTIONS, build_controlled_learning_gate,
)
from app.agent.data_truth import build_university_truth_snapshot
from app.agent.auto_training import start_auto_training_loop, stop_auto_training_loop, get_auto_training_status, run_local_training_now
from app.agent.neural_intent_trainer import get_neural_model_status, train_neural_intent_model
from app.agent.natural_query import normalize_typos, looks_like_self_data_request, document_list_request, has_any, DOCUMENT_WORDS, GRADE_WORDS, PROFILE_WORDS
from app.client.mcp_client import call_mcp_server
from app.reports.pdf_generator import REPORT_DIR, create_pdf_report
from app.auth import router as auth_router
from app.audit import write_audit_event, list_audit_events
from app.routers.health import create_health_router
from app.roles.admin.router import create_admin_router
from app.roles.advisor.router import create_advisor_router
from app.roles.student.router import router as student_router
from app.production_security import (
    SecurityError, SlidingWindowRateLimiter, apply_identity_to_model,
    bearer_token_from_headers, get_client_ip, is_public_path, production_configuration_errors,
    rate_limit_policy, request_id_from_headers, rewrite_identity_query, route_required_role,
    verify_access_token,
)
from app.production_gate import run_production_hardening_gate
from app.db.postgres import (
    init_postgres_tables,
    get_or_create_session,
    create_chat_session,
    list_chat_sessions,
    save_chat_message,
    get_chat_history,
    get_latest_debug_trace,
    delete_chat_session,
    list_ai_learning_memories,
    deactivate_ai_learning_memory,
    list_data_agents,
    search_data_agent_chunks,
    sync_existing_database_agents,
    get_connection,
    save_ai_answer_feedback,
    list_ai_answer_feedback,
    review_ai_learning_memory,
    review_ai_answer_feedback,
    get_controlled_learning_overview,
    list_learning_review_queue,
)
from app.admin_accounts import (
    bootstrap_admin_account,
)

app = FastAPI(title="MCP Client Backend")

PDF_VIEW_DIR = "generated_document_views"
os.makedirs(PDF_VIEW_DIR, exist_ok=True)

SUPPORTED_KNOWLEDGE_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv"}
ALLOWED_STORAGE_TARGETS = {"postgres", "mongodb", "excel"}
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB", "university_mongo")
APP_VERSION = "V30_CLEAN_FOUNDATION"
APP_RELEASE_NOTES = [
    "V30 authoritative chat: the latest request is planned directly; saved learning memory cannot replace its entity, purpose, or scope.",
    "V30 surname, table, schema, count, report, and unsupported real-time contracts are enforced by the built-in deterministic evaluation gate.",
    "Automatic local training pipeline: changed MongoDB/PostgreSQL/PDF/Excel sources are fingerprinted and reindexed without Gemini embedding calls.",
    "Every existing table and uploaded file has its own auto-refreshed data agent.",
    "Local centroid router learns from correction/query-shape examples without cloud tokens.",
    "MongoDB students/advisors remain the canonical master sources for student facts.",
    "Gemini remains available for chat reasoning only; local training is the default.",
    "Knowledge Workspace UX: uploaded PDF/Excel/CSV files now carry a deterministic data profile for clearer storage, schema, and retrieval summaries.",
    "Pinned document context: workspace Ask buttons fetch the exact selected file and final answers are grounded in stored text/notes without relying on filename keyword matching.",
    "Study Notes replaces vague AI Notes: notes are clearly marked as AI-organized helper material; original extracted rows remain available in Data table.",
    "V21 document Q&A: pinned files answer focused questions from exact stored text before falling back to a general file overview.",
    "V21 release quality gate: deterministic document-grounding checks run alongside query-contract evaluation before planner/document changes are accepted.",
    "V22 persistent document context: a workspace file remains selected for follow-up questions until the user clears it or starts a new chat.",
    "V22 explanation reliability: broad file requests use the document overview; focused questions use source-backed excerpts; internal semantic scores are hidden from chat.",
    "V23 table workspace: data tables support search, sorting, pagination, and CSV export with clearer source/reading-guide separation.",
    "V24 end-to-end test gate: validates message contract, planner, fixture result validation, deterministic answer shape, and selected-document Q&A before release changes.",
    "V25 live smoke gate: read-only checks prove MongoDB, PostgreSQL, source-of-truth boundaries, and the MCP count path work against the real Docker services without Gemini tokens or exposing student records.",
    "V27 answer quality: each response now has a user-facing safe source label, Thai typo handling is stronger for file questions, and source failures return clear non-technical recovery guidance.",
    "V28 production hardening: signed identities bind role and account ownership at the backend; rate limits, audit logs, health readiness checks, backup/restore runbooks, and CI release gates are included.",
    "V30 real local training: a supervised multilingual MLP intent router is trained, evaluated, versioned, and stored locally in PostgreSQL. It never fine-tunes Gemini/OpenAI and it never trains on raw student records.",
    "V30 clean foundation: one controlled startup migrates PostgreSQL, verifies the database-backed administrator account, and uses a free local frontend port without manual raw SQL.",
    "V30 dataset integrity: the development demo creates and verifies exactly 1,000 fictional students in BOTH MongoDB and PostgreSQL. A page limit is never reported as the database total.",
    "V30 source consistency: empty MongoDB starts without a competing 100-record sample; only the tagged V30 synthetic seed creates demo student records.",
    "V30 administrator accounts: Admin usernames and PBKDF2 password hashes are stored in PostgreSQL. Environment values bootstrap only the first account, then no longer control Admin sign-in.",
    "V26 controlled learning: a correction fixes the current turn but becomes a review candidate; only an admin can publish it for future routing.",
    "V26 answer feedback: Helpful / Needs review signals are stored locally for review and never create planner rules automatically.",
]
app.mount("/document-views", StaticFiles(directory=PDF_VIEW_DIR), name="document_views")

os.makedirs(REPORT_DIR, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORT_DIR), name="reports")

# Never combine credentialed CORS with a wildcard origin. Configure the real
# HTTPS frontend origins in CORS_ALLOWED_ORIGINS before a production release.
_allowed_origins = [
    item.strip() for item in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3100,http://127.0.0.1:3100",
    ).split(",") if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Access-Token", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

_rate_limiter = SlidingWindowRateLimiter()


class ProductionSecurityMiddleware(BaseHTTPMiddleware):
    """Bind protected requests to signed identity claims and audit safe metadata.

    The role or requester ID inside a URL/form/JSON body is treated as display
    input only. The authenticated signed token is the policy authority.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        request_id = request_id_from_headers(request.headers)
        request.state.request_id = request_id
        client_ip = get_client_ip(request.headers, request.client.host if request.client else None)
        identity = None
        rate_bucket = "public"
        started = time.perf_counter()

        if method != "OPTIONS" and not is_public_path(path):
            try:
                identity = verify_access_token(bearer_token_from_headers(request.headers))
                allowed_roles = route_required_role(path)
                if allowed_roles and identity.role not in allowed_roles:
                    raise SecurityError("Your signed account does not have access to this resource.")
                request.state.identity = identity
                rewrite_identity_query(request.scope, identity)
            except SecurityError as exc:
                message = "Sign in again to continue." if "token" in str(exc).lower() else "Your account does not have access to this resource."
                response = JSONResponse(
                    status_code=401 if "token" in str(exc).lower() else 403,
                    content={
                        "success": False,
                        "detail": message,
                        "error": {"code": "AUTH_REQUIRED" if "token" in str(exc).lower() else "FORBIDDEN", "message": message, "request_id": request_id},
                        "request_id": request_id,
                    },
                )
                response.headers["X-Request-ID"] = request_id
                write_audit_event(
                    request_id=request_id, actor_role=None, actor_id=None, action=path,
                    outcome="blocked", status_code=response.status_code, client_ip=client_ip,
                    metadata={"method": method, "path": path, "duration_ms": 0, "error_code": "AUTH_REQUIRED"},
                )
                return response

        limit, period, rate_bucket = rate_limit_policy(method, path)
        rate_subject = identity.token_id if identity else f"ip:{client_ip}"
        allowed, retry_after = _rate_limiter.check(f"{rate_bucket}:{rate_subject}", limit, period)
        if not allowed:
            message = "Too many requests. Please try again shortly."
            response = JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "detail": message,
                    "error": {"code": "RATE_LIMITED", "message": message, "request_id": request_id},
                    "request_id": request_id,
                },
            )
            response.headers.update({"Retry-After": str(retry_after), "X-Request-ID": request_id, "X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"})
            write_audit_event(
                request_id=request_id, actor_role=identity.role if identity else None, actor_id=identity.subject_id if identity else None,
                action=path, outcome="rate_limited", status_code=429, client_ip=client_ip,
                metadata={"method": method, "path": path, "duration_ms": 0, "rate_bucket": rate_bucket, "error_code": "RATE_LIMITED"},
            )
            return response

        response = await call_next(request)
        identity = identity or getattr(request.state, "authenticated_identity", None)
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = "available"
        if not is_public_path(path) or path == "/login":
            write_audit_event(
                request_id=request_id, actor_role=identity.role if identity else None, actor_id=identity.subject_id if identity else None,
                action=path, outcome="success" if response.status_code < 400 else "failed", status_code=response.status_code, client_ip=client_ip,
                metadata={"method": method, "path": path, "duration_ms": duration_ms, "rate_bucket": rate_bucket},
            )
        return response


app.add_middleware(ProductionSecurityMiddleware)

app.include_router(auth_router)


def _verified_admin_identity(request: Request):
    identity = getattr(request.state, "identity", None)
    if not identity or identity.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return identity


@app.exception_handler(HTTPException)
async def structured_http_error(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", request_id_from_headers(request.headers))
    detail = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    code = "FORBIDDEN" if exc.status_code == 403 else "NOT_FOUND" if exc.status_code == 404 else "REQUEST_ERROR"
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "detail": detail, "error": {"code": code, "message": detail, "request_id": request_id}, "request_id": request_id},
    )


@app.exception_handler(Exception)
async def structured_unexpected_error(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", request_id_from_headers(request.headers))
    client_ip = get_client_ip(request.headers, request.client.host if request.client else None)
    write_audit_event(
        request_id=request_id, actor_role=getattr(getattr(request.state, "identity", None), "role", None),
        actor_id=getattr(getattr(request.state, "identity", None), "subject_id", None), action=request.url.path,
        outcome="error", status_code=500, client_ip=client_ip,
        metadata={"method": request.method, "path": request.url.path, "duration_ms": 0, "error_code": type(exc).__name__},
    )
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "The service could not complete that request. Please retry or contact an administrator with the request ID.", "error": {"code": "INTERNAL_ERROR", "message": "The service could not complete that request.", "request_id": request_id}, "request_id": request_id},
    )


@app.on_event("startup")
def startup_event():
    configuration_errors = production_configuration_errors()
    if configuration_errors:
        raise RuntimeError("Production configuration is incomplete: " + "; ".join(configuration_errors))
    init_postgres_tables()
    # V30 creates an initial PostgreSQL administrator only when the account
    # table is empty. Later sign-ins never read ADMIN_PASSWORD from .env.
    bootstrap_result = bootstrap_admin_account()
    if bootstrap_result.get("created"):
        print("Administrator account bootstrap completed in PostgreSQL.")
    # V18 starts a background, local-only incremental index loop. It fingerprints
    # existing DB tables/uploads and skips unchanged sources, so it does not spend
    # Gemini tokens or block chat startup with repeated full rebuilds.
    try:
        start_auto_training_loop(mongo_uri=MONGO_URI, mongo_db_name=MONGO_DB_NAME)
    except Exception as exc:
        print(f"Automatic local training startup skipped: {exc}")


@app.on_event("shutdown")
def shutdown_event():
    stop_auto_training_loop()


def _safe_check(name: str, fn):
    try:
        data = fn()
        return {"name": name, "ok": True, "detail": data}
    except Exception:
        # Keep raw connection details only in container logs/audit metadata, never in
        # a browser health response where hostnames and credentials could leak.
        return {"name": name, "ok": False, "detail": {"status": "unavailable"}}


def _runtime_dependency_checks():
    mcp_url = os.getenv("MCP_SERVER_URL", "http://mcp_server:9000").rstrip("/")

    def check_postgres():
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                return {"status": "reachable", "ok": bool((cur.fetchone() or {}).get("ok"))}
        finally:
            conn.close()

    def check_mongo():
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
        try:
            client.admin.command("ping")
            return {"status": "reachable"}
        finally:
            client.close()

    def check_mcp():
        res = requests.get(f"{mcp_url}/health/ready", timeout=2)
        return {"status": "reachable", "status_code": res.status_code, "ready": bool(res.ok)}

    checks = [
        _safe_check("postgres", check_postgres),
        _safe_check("mongo", check_mongo),
        _safe_check("mcp_server", check_mcp),
    ]
    # The Docker health check is intentionally stricter in local demo mode: a
    # healthy chat must not start against the legacy 100-row/empty-Postgres mix.
    if (os.getenv("DEMO_DATA_MODE") or "").strip().lower() == "true":
        def check_demo_dataset():
            from app.system_bootstrap import dataset_status
            status = dataset_status()
            if not status.get("synchronized"):
                raise RuntimeError("V30 synthetic dataset is not synchronized.")
            return {
                "status": "synchronized",
                "students": status.get("expected_student_count"),
                "data_origin": status.get("data_origin"),
            }
        checks.append(_safe_check("demo_dataset", check_demo_dataset))
    return checks


app.include_router(create_health_router(
    app_version=APP_VERSION,
    release_notes=APP_RELEASE_NOTES,
    dependency_checks=_runtime_dependency_checks,
))


@app.get("/system/health")
def system_health():
    checks = _runtime_dependency_checks()
    provider = (os.getenv("AI_PROVIDER") or "gemini").lower()
    ai_key_present = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) if provider == "gemini" else bool(os.getenv("OPENAI_API_KEY"))
    all_ok = all(item.get("ok") for item in checks)
    return {
        "success": True,
        "status": "healthy" if all_ok else "degraded",
        "app_version": APP_VERSION,
        "checks": checks,
        "ai": {
            "provider": provider,
            "key_present": ai_key_present,
            "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if provider == "gemini" else os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            "note": "Readiness checks dependencies only; model prompts are not sent from this endpoint.",
        },
    }


@app.get("/system/source-cleanup")
def source_cleanup_summary():
    return {
        "success": True,
        "app_version": APP_VERSION,
        "cleanup_done": [
            "Removed Python __pycache__ and .pyc files from the packaged ZIP.",
            "Moved old version note files out of the root into docs/archive_notes.",
            "Added scripts/clean_project.sh for safe local Docker/source cleanup.",
            "Kept legacy Python agent modules when they are still imported or useful as safe fallback; no risky deletion of live agent code.",
        ],
        "safe_local_cleanup": [
            "docker compose down --remove-orphans",
            "docker system prune -f",
            "find . -type d -name __pycache__ -prune -exec rm -rf {} +",
            "find . -type f -name '*.pyc' -delete",
        ],
        "warning": "Do not run docker compose down -v unless you want to erase MongoDB/PostgreSQL data volumes.",
    }

@app.get("/system/data-truth")
def system_data_truth(user_role: str = "admin"):
    """Show which database is authoritative for each university metric."""
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can inspect data source-of-truth diagnostics.")
    bundle = _collect_admin_university_context("en", include_full_students=False)
    return {"success": True, "app_version": APP_VERSION, "data_truth": build_university_truth_snapshot(bundle)}


@app.get("/admin/evaluation/latest")
def latest_admin_evaluation(user_role: str = "admin"):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view the AI evaluation dashboard.")
    # The evaluation is deliberately deterministic and local. Running it again is
    # inexpensive and avoids stale results after a backend restart.
    return run_query_contract_evaluation()


@app.post("/admin/evaluation/run")
def run_admin_evaluation(user_role: str = "admin"):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can run the AI evaluation suite.")
    return run_query_contract_evaluation()


@app.get("/admin/quality-gate/latest")
def admin_quality_gate(user_role: str = "admin"):
    """Run local release checks for query planning and selected-document Q&A.

    This endpoint is deterministic: it does not call Gemini, does not expose
    private data, and gives the UI one clear readiness signal after upgrades.
    """
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view the release quality gate.")
    query_report = run_query_contract_evaluation()
    document_report = run_document_grounding_checks()
    query_summary = query_report.get("summary") or {}
    document_summary = document_report.get("summary") or {}
    passed = int(query_summary.get("passed") or 0) + int(document_summary.get("passed") or 0)
    total = int(query_summary.get("total") or 0) + int(document_summary.get("total") or 0)
    return {
        "success": bool(query_report.get("success")) and bool(document_report.get("success")),
        "app_version": APP_VERSION,
        "summary": {"passed": passed, "total": total, "percentage": round((passed / total * 100) if total else 0, 1)},
        "checks": {"query_contracts": query_report, "document_grounding": document_report},
        "note": "Local deterministic checks only. No Gemini tokens or private records are used.",
    }


@app.post("/admin/quality-gate/run")
def run_admin_quality_gate(user_role: str = "admin"):
    return admin_quality_gate(user_role=user_role)

@app.get("/admin/end-to-end-gate/latest")
def admin_end_to_end_gate(user_role: str = "admin"):
    """Run local answer-flow checks plus the live role-aware academic brain gate."""
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view the end-to-end test gate.")
    local_report = run_end_to_end_gate()
    academic_report = run_academic_brain_gate()
    local_summary = local_report.get("summary") or {}
    academic_summary = academic_report.get("summary") or {}
    passed = int(local_summary.get("passed") or 0) + int(academic_summary.get("passed") or 0)
    total = int(local_summary.get("total") or 0) + int(academic_summary.get("total") or 0)
    return {
        **local_report,
        "success": bool(local_report.get("success")) and bool(academic_report.get("success")),
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total": total,
            "percentage": round((passed / total * 100) if total else 0.0, 1),
        },
        "checks": {
            "local_answer_flow": local_report,
            "live_academic_brain": academic_report,
        },
        "note": "Includes live read-only role, policy, database retrieval, validation, and formatting checks.",
    }


@app.post("/admin/end-to-end-gate/run")
def run_admin_end_to_end_gate(user_role: str = "admin"):
    return admin_end_to_end_gate(user_role=user_role)


@app.get("/admin/live-smoke-gate/latest")
def admin_live_smoke_gate(user_role: str = "admin"):
    """Run V25 aggregate-only checks against the live Docker services.

    This endpoint has no writes, calls no model, and returns only aggregate
    counts/table status so an admin can diagnose deployment readiness safely.
    """
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can run live database smoke tests.")
    return run_live_smoke_gate(
        mongo_uri=MONGO_URI,
        mongo_db_name=MONGO_DB_NAME,
        mcp_base_url=os.getenv("MCP_SERVER_URL", "http://mcp_server:9000"),
    )


@app.post("/admin/live-smoke-gate/run")
def run_admin_live_smoke_gate(user_role: str = "admin"):
    return admin_live_smoke_gate(user_role=user_role)

@app.post("/admin/system-check/run")
def run_admin_system_check(user_role: str = "admin"):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can run a system check.")

    def run_check(name: str, runner):
        try:
            result = runner() or {}
            summary = result.get("summary") or {}

            failed = int(summary.get("failed") or 0)
            is_ok = bool(result.get("success", False))

            # Health endpoint uses status instead of summary.failed.
            if name == "Runtime health":
                is_ok = result.get("status") == "healthy"

            if failed > 0:
                is_ok = False

            return {
                "name": name,
                "ok": is_ok,
                "summary": summary,
                "status": result.get("status"),
                "message": result.get("detail") or result.get("note") or "",
            }
        except Exception as exc:
            return {
                "name": name,
                "ok": False,
                "summary": {},
                "status": "error",
                "message": str(exc),
            }

    checks = [
        run_check("Runtime health", system_health),
        run_check("Data consistency", lambda: system_data_truth(user_role="admin")),
        run_check("AI routing quality", lambda: admin_quality_gate(user_role="admin")),
        run_check("End-to-end flow", lambda: admin_end_to_end_gate(user_role="admin")),
        run_check("Live database connection", lambda: admin_live_smoke_gate(user_role="admin")),
    ]

    passed = sum(1 for item in checks if item["ok"])
    total = len(checks)

    return {
        "success": passed == total,
        "status": "ready" if passed == total else "needs_attention",
        "summary": {
            "passed": passed,
            "total": total,
        },
        "checks": checks,
        "note": "Read-only diagnostic check. No student data was changed and no AI model was trained.",
    }


@app.get("/admin/production-gate/latest")
def admin_production_gate(user_role: str = "admin"):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view production hardening checks.")
    return run_production_hardening_gate()


@app.post("/admin/production-gate/run")
def run_admin_production_gate(user_role: str = "admin"):
    return admin_production_gate(user_role=user_role)


@app.get("/admin/audit-logs")
def admin_audit_logs(user_role: str = "admin", limit: int = 100, action_prefix: Optional[str] = None):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view operational audit logs.")
    rows = list_audit_events(limit=limit, action_prefix=action_prefix)
    return {"success": True, "count": len(rows), "events": rows, "note": "Audit logs exclude chat content, document text, passwords, and access tokens."}


@app.get("/ai/status")
def ai_status():
    provider = (os.getenv("AI_PROVIDER") or "gemini").lower()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if provider == "gemini" else os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    has_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) if provider == "gemini" else bool(os.getenv("OPENAI_API_KEY"))
    if not has_key:
        return {
            "provider": provider,
            "connected": False,
            "model": model,
            "message": "GEMINI_API_KEY is missing inside the backend container." if provider == "gemini" else "OPENAI_API_KEY is missing inside the backend container.",
        }
    try:
        text = ai_generate_text(
            prompt="Reply with only: ok",
            timeout_env="GEMINI_STATUS_TIMEOUT",
            default_timeout=15,
            temperature=0.0,
            max_output_tokens=10,
        )
        return {
            "provider": provider,
            "connected": bool(text),
            "model": model,
            "reply": text,
        }
    except Exception as e:
        return {
            "provider": provider,
            "connected": False,
            "model": model,
            "error": str(e),
        }


def _message_with_history_context(message: str, history: List[Dict[str, Any]]) -> str:
    """Add lightweight conversational context before planning.

    This helps the planner understand short follow-ups like "really",
    "what about that", "subject upload yet", or typo document questions without
    giving the model permission to bypass database/PDPA rules. The final answer still
    uses only tool data returned after permission filtering.
    """
    raw = message or ""
    low = raw.lower().strip()
    normalized_low = normalize_typos(raw)

    # Strong guard: explicit questions should NOT inherit old chat context.
    # Example bug fixed: after asking for a student profile, "what PDFs are uploaded?"
    # was routed back to the old student because the previous S002 context was appended.
    # If the latest message is clearly about PDFs/documents, keep it raw.
    if has_any(raw, DOCUMENT_WORDS) or document_list_request(raw):
        return raw

    # If the latest message is clearly about student data, keep it raw too.
    # The policy layer must see the exact student ID and decide whether that ID is allowed.
    if re.search(r"\bS\d{3,6}\b", raw, flags=re.IGNORECASE):
        return raw
    if looks_like_self_data_request(raw) or has_any(raw, GRADE_WORDS) or has_any(raw, PROFILE_WORDS):
        return raw

    recent_user_messages = [
        str(item.get("content", ""))
        for item in history[-14:]
        if str(item.get("role", "")).lower() == "user" and str(item.get("content", "")).strip()
    ]
    recent_assistant_messages = [
        str(item.get("content", ""))
        for item in history[-14:]
        if str(item.get("role", "")).lower() == "assistant" and str(item.get("content", "")).strip()
    ]
    previous_user = recent_user_messages[-1] if recent_user_messages else ""
    previous_assistant = recent_assistant_messages[-1] if recent_assistant_messages else ""
    joined = "\n".join(str(item.get("content", "")) for item in history[-12:])

    # User expands a previous question to all/everyone.
    followup_all_words = ["everyone", "everybody", "all", "everyonew", "everyonw", "ทั้งหมด", "ทุกคน"]
    if previous_user and any(w in low for w in followup_all_words):
        return (
            f"{raw}\n\n"
            f"[Follow-up context: The user is correcting/expanding the previous question. "
            f"Previous user question: {previous_user}. Interpret this new message as asking for all/every student where allowed.]"
        )

    # Very short replies usually depend on the previous turn. Keep both previous user
    # and assistant text so the planner can choose the same data source again.
    vague_followup_words = {
        "really", "seriously", "why", "how", "then", "so", "again", "more", "detail",
        "details", "explain", "this", "that", "it", "beside", "besides", "what about",
        "แล้ว", "จริงหรอ", "จริงดิ", "ทำไม", "อันนี้", "อันนั้น", "ต่อ", "เพิ่ม"
    }
    document_followup_signals = [
        "pdf", "document", "file", "upload", "uploaded", "stored", "table", "summary",
        "subject upload", "subject uploads", "เอกสาร", "ไฟล์", "อัปโหลด", "ตาราง", "สรุป"
    ]
    is_short = len(normalized_low.split()) <= 5
    is_vague = is_short and (normalized_low in vague_followup_words or any(w in normalized_low for w in vague_followup_words))
    asks_upload_status = any(w in normalized_low for w in document_followup_signals) or document_list_request(raw)
    if previous_user and (is_vague or asks_upload_status):
        return (
            f"{raw}\n\n"
            f"[Recent conversation context for routing only:\n"
            f"Previous user: {previous_user[:500]}\n"
            f"Previous assistant: {previous_assistant[:700]}\n"
            f"If the latest message is a follow-up, answer the same topic naturally using fresh allowed database results.]"
        )

    # Follow-ups about recently mentioned student IDs.
    matches = re.findall(r"\bS\d{3,6}\b", joined, flags=re.IGNORECASE)
    if matches and any(w in low for w in ["his", "her", "that", "above", "gpa", "grade", "grades", "name", "score", "subject", "subjects", "เขา", "คนนี้", "ด้านบน"]):
        return f"{raw}\n\n[Conversation context: the most recently discussed student ID was {matches[-1].upper()}]"

    return raw


def _admin_should_collect_extra_context(message: str, plan: Dict[str, Any]) -> bool:
    """Admin may ask broad university questions that need more than one tool."""
    text = normalize_typos(message)
    explicit_broad_phrases = [
        "everything", "all data", "all information", "all info",
        "university overview", "overview of the university", "whole university",
        "university system overview", "what can you access", "what data can you access",
        "database map", "database structure", "database schema", "all tables", "all columns",
        "ทุกอย่าง", "ข้อมูลทั้งหมด", "ภาพรวมมหาวิทยาลัย", "ทั้งระบบ", "โครงสร้างฐานข้อมูล",
    ]
    if any(phrase in text for phrase in explicit_broad_phrases):
        return True
    # Never replace a specific validated database plan merely because the
    # question contains generic words such as "summary", "student", or
    # "university". Unsupported/specific questions must clarify or fail safely.
    return False


def _admin_context_plan(tool_name: str, arguments: Dict[str, Any], language: str) -> Dict[str, Any]:
    return {
        "selected_agent": "admin_agent",
        "role_prompt_name": "ADMIN_SUPER_AGENT_PROMPT",
        "tool_name": tool_name,
        "arguments": arguments,
        "user_role": "admin",
        "requester_student_id": None,
        "requester_advisor_id": None,
        "language": language,
    }


def _collect_admin_university_context(language: str, include_full_students: bool = False) -> Dict[str, Any]:
    """Collect multiple MCP tool results for broad admin questions.

    This does not bypass policy. Every sub-call still goes through MCP + PDPA guard,
    but admin is allowed to audit all university data stores.
    """
    student_args = {
        "student_id": "ALL",
        "operation": "read_students" if include_full_students else "list_names",
        "requested_fields": [
            "student_id", "name", "program", "gpa", "academic_status", "subject_grades",
            "email", "phone", "national_id", "passport_id", "address", "advisor_note"
        ] if include_full_students else ["student_id", "name"],
    }
    calls = {
        "postgres_database_map": _admin_context_plan("postgres_university_tool", {"query_type": "database_map", "keyword": ""}, language),
        "student_schema": _admin_context_plan("mongodb_student_tool", {"student_id": "ALL", "operation": "schema_overview", "requested_fields": []}, language),
        "advisor_schema": _admin_context_plan("mongodb_advisor_tool", {"advisor_id": "ALL", "operation": "schema_overview"}, language),
        "student_count": _admin_context_plan("mongodb_student_tool", {"student_id": "ALL", "operation": "count", "requested_fields": ["student_id"]}, language),
        "students": _admin_context_plan("mongodb_student_tool", student_args, language),
        "advisors": _admin_context_plan("mongodb_advisor_tool", {"advisor_id": "ALL", "operation": "list_advisors"}, language),
        "programs": _admin_context_plan("postgres_university_tool", {"query_type": "programs", "keyword": ""}, language),
        "advisor_subjects": _admin_context_plan("postgres_university_tool", {"query_type": "advisor_subjects", "keyword": ""}, language),
        "documents": _admin_context_plan("postgres_university_tool", {"query_type": "all_documents", "operation": "list_documents", "keyword": ""}, language),
    }
    bundle: Dict[str, Any] = {"type": "admin_university_context_bundle"}
    for key, subplan in calls.items():
        bundle[key] = call_mcp_server(subplan)
    return bundle


MAX_CHAT_ROWS = 20


def _rows_from_tool_result(tool_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract list rows from common MCP result shapes."""
    data = tool_result.get("data") if isinstance(tool_result, dict) else None
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        data = data.get("data")

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if isinstance(data, dict):
        for key in ["students", "advisors", "documents", "rows", "data"]:
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

    return []

def _build_chat_table_payload(plan: Dict[str, Any], tool_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    args = plan.get("arguments") or {}
    presentation = args.get("presentation") or {}

    if presentation.get("view") != "table":
        return None

    if plan.get("tool_name") != "mongodb_student_tool":
        return None

    data = tool_result.get("data") if isinstance(tool_result, dict) else {}
    rows = []
    total_records = 0
    report = None

    if isinstance(data, dict) and data.get("type") == "large_result_with_report":
        rows = data.get("preview_rows") or []
        total_records = int(data.get("total_records") or len(rows))
        report = data.get("report")
    else:
        rows = _rows_from_tool_result(tool_result)
        total_records = len(rows)

    columns = args.get("table_columns") or [
        "student_id",
        "name",
        "program",
        "gpa",
        "academic_status",
    ]

    safe_rows = []
    for row in rows[:20]:
        safe_rows.append({
            column: (
                json.dumps(row.get(column), ensure_ascii=False)
                if isinstance(row.get(column), (dict, list))
                else str(row.get(column) if row.get(column) is not None else "—")
            )
            for column in columns
        })

    if not safe_rows:
        return None

    return {
        "title": "Student Directory",
        "total_records": total_records,
        "shown_records": len(safe_rows),
        "columns": columns,
        "rows": safe_rows,
        "report": report,
    }

def _report_title_for_plan(plan: Dict[str, Any]) -> str:
    tool = plan.get("tool_name")
    args = plan.get("arguments") or {}
    force_report = bool(args.get("force_report"))
    
    if tool == "mongodb_student_tool":
        op = args.get("operation")
        if op == "grade_summary":
            return "Student Grade Summary Report"
        if op == "list_names":
            return "Student Directory Report"
        return "Student Records Report"
    if tool == "mongodb_advisor_tool":
        return "Advisor Records Report"
    if tool == "postgres_university_tool":
        qtype = args.get("query_type") or "University Data"
        return f"{str(qtype).replace('_', ' ').title()} Report"
    return "University Database Report"


def _report_columns_for_plan(plan: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[str]:
    args = plan.get("arguments") or {}
    requested = args.get("requested_fields") or []
    if requested:
        return requested
    tool = plan.get("tool_name")
    if tool == "mongodb_student_tool":
        return ["student_id", "name", "program", "gpa", "academic_status", "email", "phone", "subject_grades"]
    if tool == "mongodb_advisor_tool":
        return ["advisor_id", "name", "department", "email", "phone"]
    return list(rows[0].keys())[:10] if rows else []


def _maybe_create_large_admin_report(request: ChatRequest, plan: Dict[str, Any], tool_result: Dict[str, Any]) -> Dict[str, Any]:
    """For admin large read results, keep chat short and create a PDF report.

    Chat should not print 1,000 database rows. It should show first 20 and link a report.
    """
    if (request.user_role or "").lower() != "admin":
        return tool_result
    if not isinstance(tool_result, dict) or not tool_result.get("success"):
        return tool_result
    if plan.get("tool_name") not in {"mongodb_student_tool", "mongodb_advisor_tool", "postgres_university_tool"}:
        return tool_result

    args = plan.get("arguments") or {}
    op = str(args.get("operation") or "")
    answer_style = str(args.get("answer_style") or "")

    # Counts, averages, medians, highest/lowest results are answers,
    # not large lists. Never create a PDF preview for them.
    if op in {"study_term_aggregate", "student_population_aggregate", "count"}:
        return tool_result

    if answer_style in {"study_statistic", "aggregate_count", "count"}:
        return tool_result

    rows = _rows_from_tool_result(tool_result)
    total = len(rows)

    force_report = bool(args.get("force_report", False))
    report_threshold = int(args.get("create_report_if_over") or 20)
    # V14: directory/list requests are intentionally small enough to show in chat.
    # Earlier versions wrapped list-all-students in a large-result preview, which made
    # users see only 20 names even when the database contained 100+ students.
    allow_full_chat_list = bool(args.get("allow_full_chat_list")) or (op == "list_names" and answer_style == "names" and total <= 300)
    if allow_full_chat_list:
        return tool_result

    try:
        report_threshold = int(args.get("create_report_if_over") or MAX_CHAT_ROWS)
    except Exception:
        report_threshold = MAX_CHAT_ROWS
    try:
        preview_limit = int(args.get("display_limit") or MAX_CHAT_ROWS)
    except Exception:
        preview_limit = MAX_CHAT_ROWS
    preview_limit = max(1, min(preview_limit, MAX_CHAT_ROWS))
    if total <= report_threshold and not force_report:
        return tool_result

    report = create_pdf_report(
        title=_report_title_for_plan(plan),
        subtitle=f"Generated from admin request: {request.message}",
        rows=rows,
        columns=_report_columns_for_plan(plan, rows),
    )
    # The backend stays private in the base Compose file. Download links point to
    # the frontend origin, whose Nginx proxy forwards /reports/ to the backend.
    public_app_url = os.getenv("PUBLIC_APP_URL", "http://localhost:3100").rstrip("/")
    report["download_url"] = f"{public_app_url}{report['url']}"
    preview = rows[:preview_limit]
    return {
        **tool_result,
        "data": {
            "type": "large_result_with_report",
            "total_records": total,
            "preview_limit": preview_limit,
            "preview_rows": preview,
            "report": report,
            "original_data_type": type(tool_result.get("data")).__name__,
        },
        "large_result_note": f"Only the first {preview_limit} records are included in chat. Full result is in the PDF report.",
    }


def _compact_history_for_response(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return chat history without huge metadata/debug blobs.

    Older versions returned every message with full debug_trace metadata. After many
    database turns this made /chat responses very large and browsers sometimes
    showed only `Failed to fetch`. The full trace is still saved in PostgreSQL
    and can be loaded through /chat/debug/last; the chat response only needs
    role/content/date plus tiny metadata.
    """
    compact: List[Dict[str, Any]] = []
    for row in history or []:
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        tiny_meta = {}
        for key in ["selected_tool", "effective_question", "learning_memory_used", "answer_source","data_table",]:
            if key in meta:
                tiny_meta[key] = meta.get(key)
        compact.append({
            "role": row.get("role") or "assistant",
            "content": row.get("content") or "",
            "created_at": row.get("created_at"),
            "metadata": tiny_meta,
        })
    return compact


def _compact_mcp_result_for_response(mcp_result: Dict[str, Any]) -> Dict[str, Any]:
    """Return a small result preview for API response.

    The right panel/debug modal should use debug_trace, not a raw full MCP result.
    This prevents large Mongo/PDF/Excel payloads from breaking the browser fetch.
    """
    try:
        return {"success": bool((mcp_result or {}).get("success", True)), "summary": summarize_tool_result(mcp_result or {})}
    except Exception as exc:
        return {"success": False, "error": str(exc)[:500]}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http_request: Request):
    identity = getattr(http_request.state, "identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="Sign in again to continue.")
    request = apply_identity_to_model(request, identity)
    try:
        return _chat_impl(request)
    except Exception as exc:
        # Never let a backend exception appear in the browser as a vague
        # JavaScript `Failed to fetch`. Return a small JSON response with a trace.
        technical_error = f"Backend chat error: {str(exc)[:500]}"
        error_text = safe_failure_message({"tool_name": "error", "arguments": {}}, {"success": False, "error": technical_error}, request.language, request.message)
        fallback_session = request.session_id or str(uuid.uuid4())
        error_trace = {
            "version": "V15_SAFE_CHAT_ERROR",
            "input": {
                "original_message": request.message,
                "effective_question": request.message,
                "language": request.language,
                "user_role": request.user_role,
            },
            "selected_plan": {"tool_name": "error", "selected_agent": "backend_safe_chat_wrapper", "arguments": {}},
            "validation": {"is_valid": False, "problems": [technical_error], "can_repair": False},
            "tool_result_summary": {"success": False, "error": technical_error},
            "answer_quality": {"answer_preview": error_text, "grounded_in_tool_result": False},
            "developer_hint": "Check docker compose logs backend --tail=120. The chat endpoint caught this error and returned JSON instead of breaking fetch.",
        }
        return ChatResponse(
            success=False,
            ai_response=error_text,
            answer=error_text,
            session_id=fallback_session,
            selected_agent="backend_safe_chat_wrapper",
            selected_tool="error",
            tool_arguments={},
            planner_warning="A backend exception was caught by the safe chat wrapper.",
            mcp_result={"success": False, "summary": error_trace.get("tool_result_summary")},
            debug_trace=error_trace,
            answer_source=build_answer_source({"tool_name": "error", "arguments": {}}, {"success": False}, request.language),
            history=[
                {"role": "user", "content": request.message, "created_at": None, "metadata": {}},
                {"role": "assistant", "content": error_text, "created_at": None, "metadata": {}},
            ],
        )


def _build_pinned_document_plan(request: ChatRequest) -> Dict[str, Any]:
    """Create a safe exact-file plan for the Knowledge Workspace Ask action.

    A filename is not a stable query key: punctuation, brackets and version text can
    make document search select the wrong row. The workspace therefore sends the
    selected document id/scope and this plan fetches that exact allowed record.
    """
    role = (request.user_role or "student").lower()
    scope = (request.document_scope or "").lower().strip()
    # Admin may open either admin/global or advisor files. Advisor/student interfaces
    # only expose advisor-scope documents they are allowed to read.
    query_type = "all_documents" if role == "admin" else "advisor_documents"
    if role == "admin" and scope == "admin":
        query_type = "documents"
    return {
        "selected_agent": f"{role}_pinned_knowledge_agent",
        "role_prompt_name": "ADMIN_DOCUMENT_AGENT_PROMPT" if role == "admin" else ("ADVISOR_DOCUMENT_AGENT_PROMPT" if role == "advisor" else "STUDENT_ADVISOR_DOCUMENT_PROMPT"),
        "tool_name": "postgres_university_tool",
        "arguments": {
            "query_type": query_type,
            "operation": "document_by_id",
            "document_id": int(request.document_id),
            "document_scope": scope or None,
            "keyword": request.message,
            "answer_style": "document_explanation",
            "pinned_document": True,
        },
        "user_role": role,
        "requester_student_id": request.requester_student_id,
        "requester_advisor_id": request.requester_advisor_id,
        "language": request.language,
        "orchestrator": {"version": "v22", "mode": "persistent_pinned_document_context"},
        "purpose_analysis": {
            "source": "knowledge_workspace_pinned_document",
            "message_type": "file_specific_request",
            "user_purpose": "Explain or answer from the exact file selected in the Knowledge Workspace.",
            "target_domain": "documents",
            "answer_intent": "explain",
            "should_use_database": True,
            "explicit_entities": {"document_id": int(request.document_id), "document_scope": scope or None},
        },
        "purpose_contract": {
            "version": "v22_persistent_document_contract",
            "expected_operation": "document_by_id",
            "document_id": int(request.document_id),
            "document_scope": scope or None,
            "answer_style": "document_explanation",
        },
        "planner_warning": "V22 pinned document context selected the exact workspace file and remains active for follow-up messages until cleared.",
    }


def _learning_identity(user_role: str, requester_student_id: Optional[str], requester_advisor_id: Optional[str]) -> str:
    role = (user_role or "student").lower()
    if role == "student":
        return requester_student_id or "unknown_student"
    if role == "advisor":
        return requester_advisor_id or "unknown_advisor"
    return "ADMIN" if role == "admin" else "unknown"


def _safe_feedback_session_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _tool_payload(result: Dict[str, Any]) -> Any:
    """Unwrap the MCP gateway and tool envelopes without exposing internals."""
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return data.get("data")
    return data


def _combine_student_academic_sources(
    request: ChatRequest,
    plan: Dict[str, Any],
    primary_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Add authorized Mongo student-master facts to a PostgreSQL academic result.

    The second read goes through the same MCP policy gateway as every other
    request. This lets one question answer several explicitly requested parts
    while retaining student/advisor/admin row and field boundaries.
    """
    args = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
    master_sections = [
        str(section)
        for section in (args.get("student_master_sections") or [])
        if str(section) in {"profile", "gpa", "grades"}
    ]
    if (
        plan.get("tool_name") != "postgres_university_tool"
        or not args.get("include_student_master")
        or not master_sections
        or not isinstance(primary_result, dict)
        or primary_result.get("success") is False
    ):
        return primary_result

    academic_payload = _tool_payload(primary_result)
    if not isinstance(academic_payload, dict) or academic_payload.get("type") not in {
        "student_academic_profile", "student_academic_profiles",
    }:
        return primary_result

    if academic_payload.get("type") == "student_academic_profiles":
        academic_records = [
            row for row in (academic_payload.get("records") or [])
            if isinstance(row, dict)
        ]
        student_ids = [
            str(row.get("student_id") or "").upper().strip()
            for row in academic_records
            if row.get("student_id")
        ]
    else:
        academic_records = [academic_payload]
        student_ids = [
            str(
                args.get("student_id")
                or academic_payload.get("student_id")
                or request.requester_student_id
                or ""
            ).upper().strip()
        ]
    student_ids = [value for value in dict.fromkeys(student_ids) if value]
    if not student_ids:
        return primary_result

    requested_fields = ["student_id", "name"]
    if "profile" in master_sections:
        requested_fields.extend(["program", "academic_status", "gpa", "subject_grades"])
    if "gpa" in master_sections and "gpa" not in requested_fields:
        requested_fields.append("gpa")
    if "grades" in master_sections and "subject_grades" not in requested_fields:
        requested_fields.append("subject_grades")

    secondary_plan = {
        "tool_name": "mongodb_student_tool",
        "arguments": {
            "student_id": student_ids[0] if len(student_ids) == 1 else "ALL",
            "operation": "read_students",
            "requested_student_ids": student_ids,
            "query_filter": (
                {}
                if len(student_ids) == 1
                else {"student_id": {"$in": student_ids}}
            ),
            "limit": len(student_ids),
            "requested_fields": requested_fields,
            "answer_style": "student_multi",
            "original_question": request.message,
        },
        "user_role": request.user_role,
        "requester_student_id": request.requester_student_id,
        "requester_advisor_id": request.requester_advisor_id,
        "language": request.language,
    }
    secondary_result = call_mcp_server(secondary_plan)
    master_payload = _tool_payload(secondary_result) if secondary_result.get("success") is not False else None

    common = {
        "student_master_sections": master_sections,
        "requested_sections": list(args.get("requested_sections") or []),
        "requested_section_styles": dict(args.get("requested_section_styles") or {}),
        "denied_sections": list(args.get("denied_sections") or []),
        "student_master_available": master_payload is not None,
    }
    if len(student_ids) == 1:
        combined = {
            "type": "student_combined_record",
            "student_id": student_ids[0],
            "academic": academic_records[0],
            "student_master": master_payload,
            **common,
        }
        combined_operation = "student_combined_record"
    else:
        master_records = (
            [row for row in master_payload if isinstance(row, dict)]
            if isinstance(master_payload, list)
            else ([master_payload] if isinstance(master_payload, dict) else [])
        )
        combined = {
            "type": "student_combined_records",
            "student_ids": student_ids,
            "academic_records": academic_records,
            "student_master_records": master_records,
            **common,
        }
        combined_operation = "student_combined_records"
    trace = plan.get("orchestrator_execution_trace")
    if isinstance(trace, list):
        trace.append({
            "step": "authorized_multi_source_read",
            "tool_name": "mongodb_student_tool",
            "student_ids": student_ids,
            "requested_sections": master_sections,
            "success": master_payload is not None,
        })
    return {
        **primary_result,
        "data": {
            "success": True,
            "operation": combined_operation,
            "data": combined,
            "source": "Authorized PostgreSQL academic records and MongoDB student master",
        },
        "policy_note": "Combined only from independently policy-checked MCP reads.",
    }


def _augment_ranked_students_with_academic(
    request: ChatRequest,
    plan: Dict[str, Any],
    primary_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Attach authorized PostgreSQL sections to the exact ranked Mongo IDs."""
    args = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
    sections = [
        str(value)
        for value in (args.get("requested_academic_sections") or [])
        if str(value) in {
            "profile", "enrollments", "assessments", "attendance",
            "financial_accounts", "support_cases", "scholarship_awards",
        }
    ]
    ranking = _tool_payload(primary_result)
    if (
        not sections
        or not isinstance(ranking, dict)
        or ranking.get("type") != "student_ranking"
        or primary_result.get("success") is False
    ):
        return primary_result
    student_ids = [
        str(row.get("student_id") or "").upper()
        for row in (ranking.get("students") or [])
        if isinstance(row, dict) and row.get("student_id")
    ]
    if not student_ids:
        return primary_result
    academic_plan = {
        "tool_name": "postgres_university_tool",
        "arguments": {
            "query_type": "student_academic_profile",
            "operation": "read",
            "student_id": student_ids[0],
            "student_ids": student_ids,
            "requested_sections": sections,
            "answer_style": "academic_multi" if len(sections) > 1 else sections[0],
            "original_question": request.message,
        },
        "user_role": request.user_role,
        "requester_student_id": request.requester_student_id,
        "requester_advisor_id": request.requester_advisor_id,
        "language": request.language,
    }
    academic_result = call_mcp_server(academic_plan)
    academic_payload = _tool_payload(academic_result) if academic_result.get("success") is not False else None
    return {
        **primary_result,
        "data": {
            "success": True,
            "operation": "student_rank_with_academic",
            "data": {
                "type": "student_rank_with_academic",
                "ranking": ranking,
                "academic": academic_payload,
                "requested_sections": sections,
            },
            "source": "Authorized MongoDB ranking and PostgreSQL academic records",
        },
        "policy_note": "Every ranked academic section was independently checked by the MCP policy gateway.",
    }


def _chat_impl(request: ChatRequest):
    session_id = get_or_create_session(
        request.session_id,
        request.user_role,
        requester_student_id=request.requester_student_id,
        requester_advisor_id=request.requester_advisor_id,
    )

    previous_history = get_chat_history(session_id, limit=20)
    save_chat_message(session_id, "user", request.message)

    effective_question = request.message
    learning_memory_row = None
    learning_memory_used = False

    # V30 authoritative chat path:
    # 1) an explicitly pinned document wins;
    # 2) every other request goes through the current purpose/contract planner.
    # Saved correction memory is intentionally not consulted here. Feedback and
    # reviewed learning records remain available for offline router training, but
    # they can never replace the latest message's entity, purpose, or scope.
    if request.document_id:
        plan = _build_pinned_document_plan(request)
    else:
        plan = plan_turn(
            message=request.message,
            language=request.language,
            user_role=request.user_role,
            requester_student_id=request.requester_student_id,
            requester_advisor_id=request.requester_advisor_id,
            chat_history=previous_history,
            fallback_router=route_to_role_agent,
        )
    plan["routing_policy"] = {
        "version": "v30_authoritative",
        "latest_message_wins": True,
        "normal_chat_learning_memory_enabled": False,
    }

    # Execute MCP through the orchestrator validator. It checks whether the
    # returned data domain matches the question, and repairs obvious mismatches
    # before the final answer is written.
    plan, mcp_result, orchestrator_validation = execute_validate_repair(
        message=effective_question,
        language=request.language,
        user_role=request.user_role,
        plan=plan,
        call_tool=call_mcp_server,
        requester_student_id=request.requester_student_id,
        requester_advisor_id=request.requester_advisor_id,
        chat_history=previous_history,
        max_repairs=2,
    )
    mcp_result = _augment_ranked_students_with_academic(request, plan, mcp_result)
    mcp_result = _combine_student_academic_sources(request, plan, mcp_result)
    chat_table = None
    if plan.get("tool_name") != "none":
        mcp_result = _maybe_create_large_admin_report(request, plan, mcp_result)
        chat_table = _build_chat_table_payload(plan, mcp_result)

    if (request.user_role or "").lower() == "admin" and _admin_should_collect_extra_context(effective_question, plan):
        include_full = any(w in normalize_typos(effective_question) for w in ["every single thing", "full data", "all private", "all fields", "everything", "ข้อมูลทั้งหมด"])
        extra_bundle = _collect_admin_university_context(request.language, include_full_students=include_full)
        mcp_result = {
            "success": True,
            "tool_name": "admin_multi_tool_context",
            "data": {
                "primary_result": mcp_result,
                "admin_university_context": extra_bundle,
            },
            "policy_note": "Admin multi-tool context collected through MCP policy guard.",
        }
        plan["tool_name"] = "admin_multi_tool_context"
        plan["role_prompt_name"] = "ADMIN_SUPER_AGENT_PROMPT"
        plan["arguments"] = {"operation": "admin_multi_context", "reason": "Broad admin question needs multiple university data sources."}

    answer = answer_turn(
        message=effective_question,
        language=request.language,
        user_role=request.user_role,
        plan=plan,
        tool_result=mcp_result,
        chat_history=previous_history,
    )
    answer_source = build_answer_source(plan, mcp_result, request.language)

    debug_trace = build_debug_trace(
        message=request.message,
        effective_question=effective_question,
        language=request.language,
        user_role=request.user_role,
        session_id=session_id,
        plan=plan,
        tool_result=mcp_result,
        validation=orchestrator_validation,
        answer=answer,
        learning_memory_used=learning_memory_used,
        learning_memory_row=learning_memory_row,
    )

    save_chat_message(
        session_id,
        "assistant",
        answer,
        metadata={
            "selected_tool": plan.get("tool_name"),
            "tool_arguments": plan.get("arguments", {}),
            "effective_question": effective_question,
            "learning_memory_used": learning_memory_used,
            "learning_memory_id": learning_memory_row.get("id") if isinstance(learning_memory_row, dict) else None,
            "orchestrator_validation": plan.get("orchestrator_validation"),
            "orchestrator": plan.get("orchestrator"),
            "purpose_analysis": plan.get("purpose_analysis"),
            "answer_source": answer_source,
            "data_table": chat_table,
            "debug_trace": debug_trace,
        },
    )

    history = _compact_history_for_response(get_chat_history(session_id, limit=100))
    return ChatResponse(
        success=True,
        ai_response=answer,
        answer=answer,
        session_id=session_id,
        selected_agent=plan.get("selected_agent"),
        selected_tool=plan.get("tool_name"),
        tool_arguments=safe_compact(plan.get("arguments", {}), max_depth=3),
        planner_warning=plan.get("planner_warning"),
        mcp_result=_compact_mcp_result_for_response(mcp_result),
        debug_trace=debug_trace,
        answer_source=answer_source,
        history=history,
    )


@app.get("/chat/debug/last")
def last_debug_trace(
    request: Request,
    session_id: str,
):
    identity = _verified_admin_identity(request)
    trace = get_latest_debug_trace(session_id, "admin", None, None)
    if not trace:
        return {"success": False, "debug_trace": None, "message": "No debug trace found for this session yet."}
    return {"success": True, "debug_trace": trace}


@app.get("/ai/learning/memories")
def ai_learning_memories(
    user_role: str = "admin",
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    limit: int = 50,
):
    role = (user_role or "admin").lower()
    if role == "student":
        identifier = requester_student_id or "unknown_student"
    elif role == "advisor":
        identifier = requester_advisor_id or "unknown_advisor"
    else:
        identifier = "ADMIN"
    memories = list_ai_learning_memories(role, identifier, limit=min(max(limit, 1), 200))
    return {"success": True, "count": len(memories), "memories": memories}


@app.delete("/ai/learning/memories/{memory_id}")
def delete_ai_learning_memory(
    memory_id: int,
    user_role: str = "admin",
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
):
    role = (user_role or "admin").lower()
    if role == "student":
        identifier = requester_student_id or "unknown_student"
    elif role == "advisor":
        identifier = requester_advisor_id or "unknown_advisor"
    else:
        identifier = "ADMIN"
    deleted = deactivate_ai_learning_memory(memory_id, role, identifier)
    if not deleted:
        raise HTTPException(status_code=404, detail="Learning memory not found for this account.")
    return {"success": True, "deactivated_memory_id": memory_id}


@app.post("/ai/feedback")
def submit_answer_feedback(request: AnswerFeedbackRequest, http_request: Request):
    """Store a voluntary signal; it never creates or publishes a planner rule."""
    identity = getattr(http_request.state, "identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="Sign in again to continue.")
    request = apply_identity_to_model(request, identity)
    rating = clean_feedback_rating(request.rating)
    if not rating:
        raise HTTPException(status_code=422, detail="rating must be 'helpful' or 'needs_review'.")
    role = (request.user_role or "student").lower()
    if role not in {"student", "advisor", "admin"}:
        raise HTTPException(status_code=422, detail="Unsupported user role.")
    question = safe_feedback_text(request.question, 1200)
    answer_excerpt = safe_feedback_text(request.answer_excerpt, 1600)
    if not question or not answer_excerpt:
        raise HTTPException(status_code=422, detail="A question and answer excerpt are required for feedback.")
    row = save_ai_answer_feedback(
        user_role=role,
        user_identifier=_learning_identity(role, request.requester_student_id, request.requester_advisor_id),
        session_id=_safe_feedback_session_id(request.session_id),
        question=question,
        answer_excerpt=answer_excerpt,
        rating=rating,
        note=safe_feedback_text(request.note, 1000) or None,
        selected_tool=safe_feedback_text(request.selected_tool, 120) or None,
    )
    return {
        "success": True,
        "feedback": row,
        "message": "Thanks. This feedback is stored for review; it does not automatically change future answers.",
    }


@app.get("/admin/learning-control/overview")
def controlled_learning_overview(user_role: str = "admin"):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    return {
        "success": True,
        "learning": get_controlled_learning_overview(),
        "policy": {
            "current_turn_corrections": "Applied only to the current answer.",
            "future_routing": "Only published memories can guide a later plan.",
            "cloud_training": False,
            "permission_override": False,
        },
    }


@app.get("/admin/learning-control/memories")
def controlled_learning_review_queue(user_role: str = "admin", limit: int = 30):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    rows = list_learning_review_queue(limit=min(max(limit, 1), 100))
    return {"success": True, "count": len(rows), "memories": rows}


@app.post("/admin/learning-control/memories/{memory_id}/{action}")
def controlled_learning_review_memory(memory_id: int, action: str, request: LearningReviewRequest):
    if (request.user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    clean_action = clean_review_action(action, VALID_MEMORY_ACTIONS)
    if not clean_action:
        raise HTTPException(status_code=422, detail="action must be publish, pause, or dismiss.")
    row = review_ai_learning_memory(memory_id, clean_action, reviewer="ADMIN", note=safe_feedback_text(request.note, 1000) or None)
    if not row:
        raise HTTPException(status_code=404, detail="Learning candidate not found.")
    return {"success": True, "memory": row}


@app.get("/admin/learning-control/feedback")
def controlled_learning_feedback_queue(user_role: str = "admin", limit: int = 30):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    rows = list_ai_answer_feedback(limit=min(max(limit, 1), 100))
    return {"success": True, "count": len(rows), "feedback": rows}


@app.post("/admin/learning-control/feedback/{feedback_id}/{action}")
def controlled_learning_review_feedback(feedback_id: int, action: str, request: LearningReviewRequest):
    if (request.user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    clean_action = clean_review_action(action, VALID_FEEDBACK_ACTIONS)
    if not clean_action:
        raise HTTPException(status_code=422, detail="action must be reviewed or dismissed.")
    row = review_ai_answer_feedback(feedback_id, clean_action, reviewer="ADMIN", note=safe_feedback_text(request.note, 1000) or None)
    if not row:
        raise HTTPException(status_code=404, detail="Feedback record not found.")
    return {"success": True, "feedback": row}


@app.post("/admin/learning-control/gate/run")
def run_controlled_learning_review_gate(user_role: str = "admin"):
    if (user_role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    return build_controlled_learning_gate()


@app.get("/chat/history")
def history(
    session_id: Optional[str] = None,
    user_role: str = "student",
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
):
    sid = get_or_create_session(session_id, user_role, requester_student_id, requester_advisor_id)
    return {"success": True, "session_id": sid, "messages": get_chat_history(sid, limit=120)}


@app.get("/chat/sessions")
def sessions(
    user_role: str = "student",
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
):
    rows = list_chat_sessions(user_role, requester_student_id, requester_advisor_id, limit=40)
    if not rows:
        sid = create_chat_session(user_role, requester_student_id, requester_advisor_id)
        rows = list_chat_sessions(user_role, requester_student_id, requester_advisor_id, limit=40)
        return {"success": True, "active_session_id": sid, "sessions": rows}
    return {"success": True, "active_session_id": rows[0]["session_id"], "sessions": rows}


@app.post("/chat/sessions/new")
def new_session(http_request: Request):
    identity = getattr(http_request.state, "identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="Sign in again to continue.")
    sid = create_chat_session(identity.role, identity.student_id, identity.advisor_id)
    return {"success": True, "session_id": sid}


@app.delete("/chat/sessions/{session_id}")
def remove_chat_session(
    session_id: str,
    user_role: str = "student",
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
):
    deleted = delete_chat_session(session_id, user_role, requester_student_id, requester_advisor_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found for this account.")
    return {"success": True, "deleted_session_id": session_id}




def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text

def _clean_pdf_text(text: str) -> str:
    text = text or ""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    # Tesseract sometimes inserts spaces between every Thai character. Collapse those spaces.
    for _ in range(4):
        text = re.sub(r"([\u0E00-\u0E7F])\s+([\u0E00-\u0E7F])", r"\1\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _text_quality_score(text: str) -> float:
    if not text or len(text.strip()) < 20:
        return 0.0
    useful = len(re.findall(r"[A-Za-z0-9\u0E00-\u0E7F]", text))
    total = max(len(text), 1)
    words = len(text.split())
    return (useful / total) + min(words / 250, 1.0)


def _extract_with_pypdf(file_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(file_bytes))
    pages: List[str] = []
    for i, page in enumerate(reader.pages, start=1):
        text = _clean_pdf_text(page.extract_text() or "")
        if text:
            pages.append(f"--- Page {i} ---\n{text}")
    return "\n\n".join(pages)


def _extract_with_pymupdf(file_bytes: bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages: List[str] = []
    for i, page in enumerate(doc, start=1):
        text = _clean_pdf_text(page.get_text("text") or "")
        if text:
            pages.append(f"--- Page {i} ---\n{text}")
    doc.close()
    return "\n\n".join(pages)


def _extract_with_ocr(file_bytes: bytes, max_pages: int = 40) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages: List[str] = []
    for index, page in enumerate(doc):
        if index >= max_pages:
            pages.append(f"[OCR stopped after {max_pages} pages. Upload a shorter PDF or split the document for full OCR.]")
            break
        # Higher zoom is slower but gives much better OCR for Thai scans.
        matrix = fitz.Matrix(3.2, 3.2)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image = Image.open(BytesIO(pix.tobytes("png"))).convert("L")
        image = ImageOps.autocontrast(image)
        image = image.filter(ImageFilter.SHARPEN)
        config = "--oem 1 --psm 6"
        text = pytesseract.image_to_string(image, lang="tha+eng", config=config)
        text = _clean_pdf_text(text)
        if text:
            pages.append(f"--- Page {index + 1} ---\n{text}")
    doc.close()
    return "\n\n".join(pages)


def detect_language(text: str) -> str:
    thai_chars = len(re.findall(r"[\u0E00-\u0E7F]", text or ""))
    latin_chars = len(re.findall(r"[A-Za-z]", text or ""))
    if thai_chars and latin_chars:
        return "thai+english"
    if thai_chars:
        return "thai"
    if latin_chars:
        return "english"
    return "unknown"


def extract_pdf_text(file_bytes: bytes) -> Tuple[str, str, str, float]:
    # Try two embedded-text engines first because they are cleaner than OCR for real text PDFs.
    pypdf_text = _extract_with_pypdf(file_bytes)
    pymupdf_text = _extract_with_pymupdf(file_bytes)
    direct_text = pymupdf_text if _text_quality_score(pymupdf_text) >= _text_quality_score(pypdf_text) else pypdf_text
    direct_score = _text_quality_score(direct_text)

    if direct_score >= 1.05 and len(direct_text.split()) >= 20:
        return direct_text, "embedded_text", detect_language(direct_text), direct_score

    # OCR takes longer but gives better results for scanned PDF.
    ocr_text = _extract_with_ocr(file_bytes)
    ocr_score = _text_quality_score(ocr_text)
    if ocr_score > direct_score:
        return ocr_text, "ocr_tha_eng", detect_language(ocr_text), ocr_score

    return direct_text, "embedded_text_short", detect_language(direct_text), direct_score


def _first_meaningful_lines(text: str, limit: int = 10) -> List[str]:
    lines = []
    for line in (text or "").splitlines():
        clean = _clean_pdf_text(line)
        if len(clean) >= 12 and not clean.startswith("--- Page"):
            lines.append(clean[:500])
        if len(lines) >= limit:
            break
    if not lines:
        clean = _clean_pdf_text(text)
        lines = [clean[i:i + 320] for i in range(0, min(len(clean), 1600), 320) if clean[i:i + 320].strip()]
    return lines[:limit]



def _split_pdf_pages(text: str) -> List[Dict[str, Any]]:
    """Return page-aware text blocks from the extracted PDF text.

    extract_pdf_text already adds markers like --- Page 1 ---. This helper keeps those
    markers so PDF->Excel storage can preserve all readable data instead of only the
    AI summary/conclusion table.
    """
    clean = _clean_pdf_text(text)
    if not clean:
        return []
    pattern = re.compile(r"---\s*Page\s+(\d+)\s*---", re.IGNORECASE)
    matches = list(pattern.finditer(clean))
    pages: List[Dict[str, Any]] = []
    if not matches:
        return [{"page": 1, "text": clean}]
    for idx, match in enumerate(matches):
        page_no = int(match.group(1)) if match.group(1).isdigit() else idx + 1
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(clean)
        page_text = clean[start:end].strip()
        if page_text:
            pages.append({"page": page_no, "text": page_text})
    return pages or [{"page": 1, "text": clean}]


def _paragraph_chunks(page_text: str, max_chars: int = 850) -> List[str]:
    """Split page text into readable spreadsheet-sized chunks without dropping content."""
    raw_parts = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z0-9])", page_text or "") if p.strip()]
    if not raw_parts:
        raw_parts = [ln.strip() for ln in (page_text or "").splitlines() if ln.strip()]
    chunks: List[str] = []
    buffer = ""
    for part in raw_parts:
        part = _clean_pdf_text(part)
        if not part:
            continue
        if len(part) > max_chars:
            if buffer:
                chunks.append(buffer.strip())
                buffer = ""
            for i in range(0, len(part), max_chars):
                piece = part[i:i + max_chars].strip()
                if piece:
                    chunks.append(piece)
            continue
        if not buffer:
            buffer = part
        elif len(buffer) + 1 + len(part) <= max_chars:
            buffer = f"{buffer} {part}"
        else:
            chunks.append(buffer.strip())
            buffer = part
    if buffer.strip():
        chunks.append(buffer.strip())
    return chunks


def _pdf_to_excel_structured_data(
    text: str,
    filename: str,
    extraction_method: str,
    detected_language: str,
    max_rows: int = 5000,
) -> Dict[str, Any]:
    """Convert every readable PDF paragraph/chunk into structured rows.

    This is used for the PDF_EXCEL_AGENT and also helps every storage target keep a
    full extraction table. The AI explanation table remains separate; this table is
    the raw searchable data layer.
    """
    clean = _clean_pdf_text(text)
    pages = _split_pdf_pages(clean)
    rows: List[Dict[str, Any]] = []
    page_summaries: List[Dict[str, Any]] = []
    for page in pages:
        page_no = page.get("page") or len(page_summaries) + 1
        chunks = _paragraph_chunks(str(page.get("text") or ""))
        page_summaries.append({
            "page": page_no,
            "chunk_count": len(chunks),
            "word_count": len(str(page.get("text") or "").split()),
            "char_count": len(str(page.get("text") or "")),
        })
        for chunk_index, chunk in enumerate(chunks, start=1):
            if len(rows) >= max_rows:
                break
            words = chunk.split()
            rows.append({
                "No": len(rows) + 1,
                "Page": page_no,
                "Chunk": chunk_index,
                "Extracted text": chunk,
                "Word count": len(words),
                "Character count": len(chunk),
            })
        if len(rows) >= max_rows:
            break
    truncated = sum(ps.get("chunk_count", 0) for ps in page_summaries) > len(rows)
    columns = ["No", "Page", "Chunk", "Extracted text", "Word count", "Character count"]
    return {
        "source_type": "pdf",
        "storage_mode": "pdf_to_excel_full_extraction_table",
        "filename": filename,
        "extraction_method": extraction_method,
        "detected_language": detected_language,
        "total_pages": len(pages),
        "total_rows": len(rows),
        "stored_row_count": len(rows),
        "truncated": truncated,
        "columns": columns,
        "rows": rows,
        "sample_rows": rows[:10],
        "page_summaries": page_summaries,
        "searchable_text": clean,
        "notes": [
            "PDF text is stored twice: AI explanation table for understanding, and full extraction rows for complete lookup/export-style viewing.",
            "If the PDF is scanned and OCR quality is poor, some extracted text may still need manual review.",
        ],
    }


def _build_knowledge_data_profile(
    *,
    filename: str,
    source_type: str,
    storage_target: str,
    cloned_agent_name: str,
    structured_data: Dict[str, Any],
    conclusion_table: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a deterministic, UI-friendly description of what was stored.

    This does not use an LLM. It makes the result understandable even when a
    document summary is weak, and it is identical for PostgreSQL, MongoDB, and
    Excel-agent storage targets.
    """
    structured = structured_data or {}
    table = conclusion_table or {}
    storage_labels = {
        "postgres": "PostgreSQL knowledge record",
        "mongodb": "MongoDB knowledge clone",
        "excel": "Excel-agent structured store",
    }
    profile: Dict[str, Any] = {
        "version": "v19_knowledge_workspace",
        "title": filename,
        "source_type": source_type,
        "storage": {
            "target": storage_target,
            "label": storage_labels.get(storage_target, storage_target),
            "agent": cloned_agent_name,
            "searchable": True,
        },
        "summary": table.get("short_summary") or table.get("clear_conclusion") or "The file was processed and stored as searchable knowledge.",
        "main_topic": table.get("main_topic") or filename.rsplit(".", 1)[0],
        "document_type": table.get("document_type") or source_type,
        "facts": [],
        "schema_preview": [],
        "numeric_highlights": [],
        "search_capabilities": [],
        "recommended_questions": table.get("recommended_questions") or [],
    }

    if source_type == "pdf":
        pages = int(structured.get("total_pages") or table.get("pdf_total_pages") or 0)
        chunks = int(structured.get("stored_row_count") or structured.get("total_rows") or table.get("full_text_row_count") or 0)
        profile["facts"] = [
            {"label": "Pages", "value": pages or "Unknown"},
            {"label": "Searchable text chunks", "value": chunks or "No extracted chunks"},
            {"label": "Extraction", "value": structured.get("extraction_method") or table.get("extraction_method") or "text extraction"},
            {"label": "Language", "value": structured.get("detected_language") or table.get("detected_language") or "unknown"},
        ]
        profile["search_capabilities"] = [
            "Search concepts, definitions, rules, and phrases",
            "Open the full extracted text by page and chunk",
            "Ask the AI to explain a specific section of this file",
        ]
    elif source_type == "excel":
        sheets = structured.get("sheets") or []
        profile["facts"] = [
            {"label": "Sheets", "value": int(structured.get("sheet_count") or len(sheets))},
            {"label": "Stored rows", "value": int(structured.get("total_rows") or sum(int(s.get("row_count") or 0) for s in sheets))},
            {"label": "Columns", "value": int(structured.get("total_columns") or sum(int(s.get("column_count") or 0) for s in sheets))},
            {"label": "Parsing", "value": "Structured spreadsheet rows"},
        ]
        for sheet in sheets[:6]:
            columns = [str(col) for col in (sheet.get("columns") or [])[:8]]
            profile["schema_preview"].append({
                "sheet": sheet.get("sheet_name") or "Sheet",
                "rows": int(sheet.get("row_count") or 0),
                "columns": columns,
            })
            for column, stats in (sheet.get("numeric_summary") or {}).items():
                if isinstance(stats, dict):
                    profile["numeric_highlights"].append({
                        "sheet": sheet.get("sheet_name") or "Sheet",
                        "column": str(column),
                        "min": stats.get("min"),
                        "max": stats.get("max"),
                        "average": stats.get("mean", stats.get("average")),
                    })
        profile["numeric_highlights"] = profile["numeric_highlights"][:8]
        profile["search_capabilities"] = [
            "Search individual rows and column values",
            "Compare highest, lowest, average, and totals for numeric columns",
            "Ask which sheet contains a value or topic",
        ]
    else:
        profile["facts"] = [{"label": "Stored source", "value": source_type or "knowledge file"}]
        profile["search_capabilities"] = ["Search stored knowledge", "Ask the AI for a grounded explanation"]

    if not profile["recommended_questions"]:
        if source_type == "excel":
            profile["recommended_questions"] = [
                "What sheets and columns are in this file?",
                "Which rows match a condition?",
                "What are the highest and lowest values?",
            ]
        else:
            profile["recommended_questions"] = [
                "What is this file about?",
                "Explain a key term from this file.",
                "Which page discusses a topic?",
            ]
    return profile


def _attach_full_pdf_table(conclusion_table: Dict[str, Any], structured_data: Dict[str, Any], storage_target: str) -> Dict[str, Any]:
    """Attach full PDF extraction rows while keeping the AI explanation table separate."""
    if not isinstance(conclusion_table, dict):
        conclusion_table = {}
    rows = structured_data.get("rows") or []
    if rows:
        conclusion_table["full_extraction_table"] = {
            "title": "Full PDF extracted data",
            "description": "Every readable PDF paragraph/chunk stored as table rows. This is the complete data layer, not just the AI conclusion.",
            "columns": structured_data.get("columns") or ["No", "Page", "Chunk", "Extracted text", "Word count", "Character count"],
            "rows": rows,
            "total_rows": structured_data.get("total_rows", len(rows)),
            "total_pages": structured_data.get("total_pages"),
            "truncated": structured_data.get("truncated", False),
        }
        conclusion_table["full_text_row_count"] = len(rows)
        conclusion_table["pdf_total_pages"] = structured_data.get("total_pages")
        if storage_target == "excel":
            conclusion_table["status"] = "processed_pdf_to_excel_full_table"
            conclusion_table["clear_conclusion"] = (
                (conclusion_table.get("clear_conclusion") or conclusion_table.get("short_summary") or "The PDF was processed.")
                + f" The PDF_EXCEL_AGENT also stored {len(rows)} full extraction row(s), so the file is not limited to the short summary."
            )
    return conclusion_table



def _ai_pdf_table(text: str, filename: str, detected_language: str, extraction_method: str, quality_score: float) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Use the configured AI provider to turn extracted PDF text into a clear explanation table."""
    clean = _clean_pdf_text(text)
    if not clean:
        return None

    excerpt = clean[:28000]
    prompt = f"""
You are a university document-reading AI agent.
Read this PDF text carefully. It may be Thai, English, or mixed. The user will ask questions later, so store the document in a way that is easy to explain naturally.
The user specifically needs rich stored information, not only a short conclusion. Extract as many useful details as possible from the readable text.
Do NOT return messy OCR fragments. If OCR text is unclear, say which parts are unclear.
Return ONLY valid JSON. No markdown.

JSON schema:
{{
  "short_summary": "2-4 sentence natural summary in the document language if possible",
  "clear_conclusion": "1-3 sentence conclusion: what the reader should understand after reading this document",
  "document_type": "lesson|announcement|policy|admission|grade|finance|assignment|unknown",
  "main_topic": "main topic/title in clean words",
  "important_dates": ["date or empty"],
  "key_points": ["clear point 1", "clear point 2"],
  "detailed_information": ["specific detail, rule, example, number, definition, or fact from the document"],
  "section_notes": ["section/chapter/topic notes when visible"],
  "requirements_or_conditions": ["requirement or empty"],
  "actions_or_next_steps": ["action or empty"],
  "student_takeaways": ["what a student should remember or do"],
  "recommended_questions": ["helpful question the user can ask about this PDF"],
  "explanation_table": [
    {{
      "Section": "Topic / purpose / key point / requirement / action / conclusion",
      "Main point": "short clear point",
      "Detailed information": "include concrete details, rules, dates, examples, numbers, or definitions from the PDF",
      "Simple explanation": "explain this point in easy language",
      "Why it matters": "why this point is useful or important"
    }}
  ],
  "confidence": "high|medium|low",
  "ocr_warning": "empty if readable; otherwise explain the OCR issue"
}}

Rules:
- Make the explanation_table useful for students/advisors/admin, not just copied text.
- Prefer 12-30 useful rows when enough information exists. Do not stop at only a conclusion.
- Include definitions, examples, requirements, dates, formulas, names, amounts, and key facts when present.
- Combine repeated OCR fragments into clear points.
- If the PDF is a lesson, focus on meaning, key concepts, and what to remember.
- If the PDF is an announcement/policy, focus on rule, conditions, dates, and actions.

Filename: {filename}
Detected language: {detected_language}
Extraction method: {extraction_method}
Quality score: {quality_score}

PDF text:
{excerpt}
"""
    try:
        raw = ai_generate_text(
            prompt=prompt,
            json_mode=True,
            timeout_env="GEMINI_DOCUMENT_TIMEOUT",
            default_timeout=240,
            temperature=0.1,
            max_output_tokens=8192,
        )
        if not raw:
            return None
        parsed = json.loads(_clean_json_text(raw))

        rows: List[Dict[str, Any]] = []
        table_rows = parsed.get("explanation_table") or []
        if isinstance(table_rows, list):
            for item in table_rows[:40]:
                if isinstance(item, dict):
                    rows.append({
                        "No": len(rows) + 1,
                        "Section": str(item.get("Section") or item.get("section") or "Key point").strip(),
                        "Main point": str(item.get("Main point") or item.get("main_point") or item.get("point") or "").strip(),
                        "Detailed information": str(item.get("Detailed information") or item.get("detailed_information") or item.get("details") or item.get("detail") or "").strip(),
                        "Simple explanation": str(item.get("Simple explanation") or item.get("simple_explanation") or item.get("explanation") or "").strip(),
                        "Why it matters": str(item.get("Why it matters") or item.get("why_it_matters") or item.get("importance") or "").strip(),
                    })

        def add_rows(section: str, values: Any):
            if isinstance(values, str) and values.strip():
                rows.append({
                    "No": len(rows) + 1,
                    "Section": section,
                    "Main point": values.strip(),
                    "Simple explanation": values.strip(),
                    "Why it matters": "Important for understanding the document.",
                })
            elif isinstance(values, list):
                for item in values:
                    item_text = str(item).strip()
                    if item_text:
                        rows.append({
                            "No": len(rows) + 1,
                            "Section": section,
                            "Main point": item_text,
                            "Simple explanation": item_text,
                            "Why it matters": "Useful detail from the document.",
                        })

        if not rows:
            add_rows("Summary", parsed.get("short_summary"))
            add_rows("Main topic", parsed.get("main_topic"))
            add_rows("Key points", parsed.get("key_points"))
            add_rows("Detailed information", parsed.get("detailed_information"))
            add_rows("Section notes", parsed.get("section_notes"))
            add_rows("Requirements / conditions", parsed.get("requirements_or_conditions"))
            add_rows("Actions / next steps", parsed.get("actions_or_next_steps"))
            add_rows("Student takeaways", parsed.get("student_takeaways"))
            add_rows("Conclusion", parsed.get("clear_conclusion"))
            add_rows("OCR warning", parsed.get("ocr_warning"))

        summary = parsed.get("short_summary") or "The document was processed and stored."
        conclusion = parsed.get("clear_conclusion") or summary
        table = {
            "filename": filename,
            "status": "processed_by_ai",
            "extraction_method": extraction_method,
            "detected_language": detected_language,
            "quality_score": round(quality_score, 3),
            "estimated_word_count": len(clean.split()),
            "columns": ["No", "Section", "Main point", "Detailed information", "Simple explanation", "Why it matters"],
            "rows": rows,
            "short_summary": summary,
            "clear_conclusion": conclusion,
            "document_type": parsed.get("document_type"),
            "main_topic": parsed.get("main_topic"),
            "important_dates": parsed.get("important_dates") or [],
            "key_points": parsed.get("key_points") or [],
            "detailed_information": parsed.get("detailed_information") or [],
            "section_notes": parsed.get("section_notes") or [],
            "requirements_or_conditions": parsed.get("requirements_or_conditions") or [],
            "actions_or_next_steps": parsed.get("actions_or_next_steps") or [],
            "student_takeaways": parsed.get("student_takeaways") or [],
            "recommended_questions": parsed.get("recommended_questions") or [],
            "confidence": parsed.get("confidence", "medium"),
            "ocr_warning": parsed.get("ocr_warning", ""),
        }
        return summary, table
    except Exception:
        return None


def make_document_summary(text: str, filename: str, quality_score: float, extraction_method: str) -> tuple[str, Dict[str, Any]]:
    clean = _clean_pdf_text(text)
    detected = detect_language(clean)
    if not clean:
        summary = "No readable text could be extracted. Try a clearer PDF scan or a text-based PDF."
        table = {
            "filename": filename,
            "status": "no_text",
            "extraction_method": extraction_method,
            "detected_language": detected,
            "quality_score": round(quality_score, 3),
            "columns": ["Section", "Information"],
            "rows": [{"Section": "Status", "Information": summary}],
            "short_summary": summary,
        }
        return summary, table

    # Prefer real AI summary/table when Gemini or the configured AI provider is available.
    ai_table = _ai_pdf_table(clean, filename, detected, extraction_method, quality_score)
    if ai_table:
        return ai_table

    # Safe fallback: do NOT show raw messy OCR as if it were a good summary.
    rows = _first_meaningful_lines(clean, limit=10)
    status = "processed_without_ai"
    if quality_score < 0.65 or len(clean.split()) < 20:
        status = "needs_review"

    if status == "needs_review":
        short_summary = "Text was extracted, but quality may be low. Check GEMINI_API_KEY for a cleaner AI summary or upload a clearer PDF."
        table_rows = [{"Section": "Status", "Information": short_summary}]
        table_rows += [{"Section": "Extracted text preview", "Information": row} for row in rows[:5]]
    else:
        short_summary = rows[0] if rows else clean[:400]
        table_rows = [{"Section": "Extracted information", "Information": row} for row in rows]

    table = {
        "filename": filename,
        "status": status,
        "extraction_method": extraction_method,
        "detected_language": detected,
        "quality_score": round(quality_score, 3),
        "estimated_word_count": len(clean.split()),
        "columns": ["Section", "Information"],
        "rows": table_rows,
        "short_summary": short_summary,
    }
    return short_summary, table




def _normalize_storage_target(storage_target: str) -> str:
    target = (storage_target or "postgres").lower().strip()
    return target if target in ALLOWED_STORAGE_TARGETS else "postgres"


def _file_extension(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower().strip()


def _source_type_from_filename(filename: str) -> str:
    ext = _file_extension(filename)
    if ext == ".pdf":
        return "pdf"
    if ext in {".xlsx", ".xls", ".csv"}:
        return "excel"
    return "unknown"


def _cloned_agent_name(source_type: str, storage_target: str) -> str:
    source = (source_type or "file").lower()
    target = (storage_target or "postgres").lower()
    if source == "excel":
        return f"EXCEL_{target.upper()}_AGENT"
    if source == "pdf":
        return f"PDF_{target.upper()}_AGENT"
    return f"KNOWLEDGE_{target.upper()}_AGENT"


def _json_safe_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _json_safe_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): _json_safe_value(v) for k, v in record.items()}


def _dataframe_to_sheet_payload(sheet_name: str, df: pd.DataFrame, max_store_rows: int = 5000) -> Dict[str, Any]:
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() if str(c).strip() else f"Column {i + 1}" for i, c in enumerate(df.columns)]
    df = df.where(pd.notna(df), None)
    rows = [_json_safe_record(r) for r in df.head(max_store_rows).to_dict(orient="records")]
    sample_rows = rows[:10]

    numeric_summary: Dict[str, Any] = {}
    for col in df.columns:
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.notna().sum() > 0:
            numeric_summary[str(col)] = {
                "count": int(numeric.notna().sum()),
                "min": _json_safe_value(numeric.min()),
                "max": _json_safe_value(numeric.max()),
                "mean": _json_safe_value(round(float(numeric.mean()), 4)),
            }

    return {
        "sheet_name": sheet_name,
        "row_count": int(len(df)),
        "stored_row_count": len(rows),
        "truncated": int(len(df)) > len(rows),
        "column_count": int(len(df.columns)),
        "columns": [str(c) for c in df.columns],
        "sample_rows": sample_rows,
        "rows": rows,
        "numeric_summary": numeric_summary,
    }


def extract_excel_knowledge(file_bytes: bytes, filename: str) -> Tuple[Dict[str, Any], str, str, float]:
    ext = _file_extension(filename)
    sheets: List[Dict[str, Any]] = []
    if ext == ".csv":
        df = pd.read_csv(BytesIO(file_bytes))
        sheets.append(_dataframe_to_sheet_payload("CSV", df))
        method = "csv_pandas"
    else:
        xls = pd.ExcelFile(BytesIO(file_bytes))
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            sheets.append(_dataframe_to_sheet_payload(str(sheet_name), df))
        method = "excel_pandas"

    total_rows = sum(s.get("row_count", 0) for s in sheets)
    total_columns = sum(s.get("column_count", 0) for s in sheets)
    searchable_text_parts: List[str] = [f"Filename: {filename}"]
    for sheet in sheets:
        searchable_text_parts.append(
            f"Sheet {sheet['sheet_name']}: {sheet['row_count']} rows, columns: {', '.join(sheet['columns'][:40])}"
        )
        for row in sheet.get("sample_rows", [])[:5]:
            searchable_text_parts.append(json.dumps(row, ensure_ascii=False))

    structured = {
        "source_type": "excel",
        "filename": filename,
        "sheet_count": len(sheets),
        "total_rows": total_rows,
        "total_columns": total_columns,
        "sheets": sheets,
        "searchable_text": "\n".join(searchable_text_parts)[:50000],
    }
    quality = 1.0 if total_rows or total_columns else 0.2
    return structured, method, "structured_table", quality


def _excel_fallback_summary_table(structured: Dict[str, Any], filename: str) -> Tuple[str, Dict[str, Any]]:
    sheets = structured.get("sheets") or []
    rows: List[Dict[str, Any]] = []
    for sheet in sheets:
        columns = sheet.get("columns") or []
        numeric = sheet.get("numeric_summary") or {}
        rows.append({
            "No": len(rows) + 1,
            "Section": f"Sheet: {sheet.get('sheet_name')}",
            "Main point": f"{sheet.get('row_count', 0)} rows and {sheet.get('column_count', 0)} columns",
            "Detailed information": f"Columns: {', '.join(columns[:30])}",
            "Simple explanation": "This sheet has been converted into structured rows so the chat can answer questions from it.",
            "Why it matters": "The AI can search columns, sample rows, and numeric summaries without rereading the file.",
        })
        if numeric:
            rows.append({
                "No": len(rows) + 1,
                "Section": f"Numeric summary: {sheet.get('sheet_name')}",
                "Main point": "Numeric columns detected",
                "Detailed information": json.dumps(numeric, ensure_ascii=False)[:1200],
                "Simple explanation": "The system calculated count, min, max, and average for numeric columns.",
                "Why it matters": "Useful for quick questions like highest, lowest, average, and comparison.",
            })
    summary = f"Excel file “{filename}” was stored with {structured.get('sheet_count', 0)} sheet(s) and {structured.get('total_rows', 0)} total row(s)."
    table = {
        "filename": filename,
        "status": "processed_excel_without_ai",
        "source_type": "excel",
        "document_type": "excel_dataset",
        "main_topic": filename.rsplit('.', 1)[0],
        "short_summary": summary,
        "clear_conclusion": "The file is now searchable as structured spreadsheet data.",
        "columns": ["No", "Section", "Main point", "Detailed information", "Simple explanation", "Why it matters"],
        "rows": rows or [{"No": 1, "Section": "Excel", "Main point": "No rows found", "Detailed information": "", "Simple explanation": "The spreadsheet may be empty.", "Why it matters": "Upload a file with visible rows and columns."}],
        "key_points": [summary],
        "detailed_information": [f"Sheets: {', '.join(str(s.get('sheet_name')) for s in sheets)}"],
        "recommended_questions": ["What columns are in this Excel file?", "Summarize this spreadsheet", "What are the highest and lowest values?"],
        "confidence": "medium",
        "excel_metadata": {"sheet_count": structured.get("sheet_count"), "total_rows": structured.get("total_rows")},
    }
    return summary, table


def make_excel_summary(structured: Dict[str, Any], filename: str, quality_score: float, extraction_method: str) -> Tuple[str, Dict[str, Any]]:
    excerpt = {
        "filename": filename,
        "sheet_count": structured.get("sheet_count"),
        "total_rows": structured.get("total_rows"),
        "sheets": [
            {
                "sheet_name": s.get("sheet_name"),
                "row_count": s.get("row_count"),
                "columns": s.get("columns"),
                "sample_rows": s.get("sample_rows"),
                "numeric_summary": s.get("numeric_summary"),
            }
            for s in (structured.get("sheets") or [])[:8]
        ],
    }
    prompt = f"""
You are an Excel-reading AI agent for a university knowledge base.
The spreadsheet was parsed into sheets, columns, sample rows, and numeric summaries.
Create rich stored information so chat can answer later quickly. Do not only write a conclusion.
Return ONLY valid JSON. No markdown.

JSON schema:
{{
  "short_summary": "2-4 sentence summary",
  "clear_conclusion": "1-3 sentence conclusion",
  "document_type": "excel_dataset|grade_sheet|attendance|finance|program_list|student_list|unknown",
  "main_topic": "clean topic/title",
  "key_points": ["important insight"],
  "detailed_information": ["specific detail from sheets/columns/sample rows/numeric summary"],
  "important_columns": ["column name and why it matters"],
  "data_quality_notes": ["missing/truncated/empty notes"],
  "recommended_questions": ["questions the user can ask"],
  "explanation_table": [
    {{
      "Section": "Sheet / columns / numeric insight / sample rows / next use",
      "Main point": "short clear point",
      "Detailed information": "specific columns, counts, sample values, min/max/mean, or row facts",
      "Simple explanation": "easy explanation",
      "Why it matters": "how this helps chat answer later"
    }}
  ],
  "confidence": "high|medium|low"
}}

Spreadsheet JSON excerpt:
{json.dumps(excerpt, ensure_ascii=False)[:24000]}
""".strip()
    try:
        raw = ai_generate_text(
            prompt=prompt,
            json_mode=True,
            timeout_env="GEMINI_DOCUMENT_TIMEOUT",
            default_timeout=240,
            temperature=0.05,
            max_output_tokens=8192,
        )
        if not raw:
            return _excel_fallback_summary_table(structured, filename)
        parsed = json.loads(_clean_json_text(raw))
        rows: List[Dict[str, Any]] = []
        for item in (parsed.get("explanation_table") or [])[:40]:
            if isinstance(item, dict):
                rows.append({
                    "No": len(rows) + 1,
                    "Section": str(item.get("Section") or item.get("section") or "Excel detail").strip(),
                    "Main point": str(item.get("Main point") or item.get("main_point") or item.get("point") or "").strip(),
                    "Detailed information": str(item.get("Detailed information") or item.get("detailed_information") or item.get("details") or "").strip(),
                    "Simple explanation": str(item.get("Simple explanation") or item.get("simple_explanation") or item.get("explanation") or "").strip(),
                    "Why it matters": str(item.get("Why it matters") or item.get("why_it_matters") or item.get("importance") or "").strip(),
                })
        if not rows:
            _, fallback_table = _excel_fallback_summary_table(structured, filename)
            rows = fallback_table.get("rows", [])
        summary = parsed.get("short_summary") or _excel_fallback_summary_table(structured, filename)[0]
        table = {
            "filename": filename,
            "status": "processed_excel_by_ai",
            "source_type": "excel",
            "extraction_method": extraction_method,
            "detected_language": "structured_table",
            "quality_score": round(quality_score, 3),
            "document_type": parsed.get("document_type") or "excel_dataset",
            "main_topic": parsed.get("main_topic") or filename.rsplit('.', 1)[0],
            "short_summary": summary,
            "clear_conclusion": parsed.get("clear_conclusion") or summary,
            "columns": ["No", "Section", "Main point", "Detailed information", "Simple explanation", "Why it matters"],
            "rows": rows,
            "key_points": parsed.get("key_points") or [],
            "detailed_information": parsed.get("detailed_information") or [],
            "important_columns": parsed.get("important_columns") or [],
            "data_quality_notes": parsed.get("data_quality_notes") or [],
            "recommended_questions": parsed.get("recommended_questions") or [],
            "confidence": parsed.get("confidence") or "medium",
            "excel_metadata": {"sheet_count": structured.get("sheet_count"), "total_rows": structured.get("total_rows")},
        }
        return summary, table
    except Exception:
        return _excel_fallback_summary_table(structured, filename)


def _store_knowledge_to_mongo(payload: Dict[str, Any]) -> Optional[str]:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        db = client[MONGO_DB_NAME]
        result = db["knowledge_uploads"].insert_one(payload)
        return str(result.inserted_id)
    except Exception:
        return None


def process_knowledge_file(file_bytes: bytes, filename: str, storage_target: str) -> Dict[str, Any]:
    ext = _file_extension(filename)
    if ext not in SUPPORTED_KNOWLEDGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF, Excel (.xlsx/.xls), or CSV files are supported.")

    storage_target = _normalize_storage_target(storage_target)
    source_type = _source_type_from_filename(filename)
    cloned_agent = _cloned_agent_name(source_type, storage_target)

    if source_type == "pdf":
        text, extraction_method, detected_language, quality_score = extract_pdf_text(file_bytes)
        summary, conclusion_table = make_document_summary(text, filename, quality_score, extraction_method)
        # Important: PDF->Excel must not store only the AI conclusion.
        # Keep the natural AI explanation table AND a full extracted-text table.
        structured_data: Dict[str, Any] = _pdf_to_excel_structured_data(
            text=text,
            filename=filename,
            extraction_method=extraction_method,
            detected_language=detected_language,
        )
        conclusion_table = _attach_full_pdf_table(conclusion_table, structured_data, storage_target)
        conclusion_table["detected_language"] = detected_language
        conclusion_table["source_type"] = "pdf"
    elif source_type == "excel":
        structured_data, extraction_method, detected_language, quality_score = extract_excel_knowledge(file_bytes, filename)
        text = structured_data.get("searchable_text") or ""
        summary, conclusion_table = make_excel_summary(structured_data, filename, quality_score, extraction_method)
        conclusion_table["detected_language"] = detected_language
        conclusion_table["source_type"] = "excel"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    conclusion_table["storage_target"] = storage_target
    conclusion_table["cloned_agent_name"] = cloned_agent
    conclusion_table["data_profile"] = _build_knowledge_data_profile(
        filename=filename,
        source_type=source_type,
        storage_target=storage_target,
        cloned_agent_name=cloned_agent,
        structured_data=structured_data,
        conclusion_table=conclusion_table,
    )

    mongo_object_id = None
    if storage_target == "mongodb":
        mongo_payload = {
            "filename": filename,
            "source_type": source_type,
            "storage_target": storage_target,
            "cloned_agent_name": cloned_agent,
            "summary": summary,
            "conclusion_table": conclusion_table,
            "text": text,
            "structured_data": structured_data,
            "extraction_method": extraction_method,
            "detected_language": detected_language,
        }
        mongo_object_id = _store_knowledge_to_mongo(mongo_payload)
        conclusion_table["mongo_object_id"] = mongo_object_id

    return {
        "source_type": source_type,
        "storage_target": storage_target,
        "cloned_agent_name": cloned_agent,
        "summary": summary,
        "conclusion_table": conclusion_table,
        "text": text,
        "text_preview": text[:3000],
        "structured_data": structured_data,
        "extraction_method": extraction_method,
        "detected_language": detected_language,
        "quality_score": quality_score,
        "mongo_object_id": mongo_object_id,
    }

app.include_router(create_admin_router(process_knowledge_file))
app.include_router(create_advisor_router(process_knowledge_file))
app.include_router(student_router)


@app.get("/ai/data-agents")
def get_ai_data_agents(
    user_role: str = "admin",
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
):
    """List the cloned data agents created for uploaded PDF/Excel/CSV files."""
    return {
        "success": True,
        "agents": list_data_agents(
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            limit=100,
        ),
    }


@app.get("/ai/data-agents/search")
def search_ai_data_agents(
    q: str,
    user_role: str = "admin",
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
):
    """Semantic search over cloned PDF/Excel/CSV table agents."""
    return search_data_agent_chunks(
        keyword=q,
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
        limit=30,
    )


@app.post("/ai/data-agents/reindex-existing")
def reindex_existing_database_agents(user_role: str = "admin"):
    """Create/update cloned AI data agents for existing MongoDB/PostgreSQL tables."""
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can reindex existing database agents.")
    return sync_existing_database_agents(mongo_uri=MONGO_URI, mongo_db_name=MONGO_DB_NAME)


@app.get("/ai/training/status")
def auto_training_status(user_role: str = "admin"):
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view automatic training status.")
    return {"success": True, "training": get_auto_training_status()}


@app.post("/ai/training/run-local")
def run_local_training(user_role: str = "admin"):
    """Run a local-only incremental training/index cycle now. No Gemini tokens."""
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can run local training.")
    return run_local_training_now(
        mongo_uri=MONGO_URI,
        mongo_db_name=MONGO_DB_NAME,
        trigger_source="admin_manual",
    )


@app.get("/ai/training/neural-router/status")
def neural_router_status(user_role: str = "admin"):
    """Show local supervised neural router status and the last evaluated model."""
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view neural router status.")
    return {"success": True, "neural_router": get_neural_model_status()}


@app.post("/ai/training/neural-router/run")
def run_neural_router_training(user_role: str = "admin", force: bool = True):
    """Train the local MLP routing model from curated and admin-published examples."""
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can train the neural router.")
    return train_neural_intent_model(force=bool(force), trigger_source="admin_manual")


@app.post("/ai/data-agents/train-semantic")
def train_semantic_data_agents(user_role: str = "admin", provider: str = "local"):
    """Compatibility endpoint. V18 defaults to free local incremental training.

    `provider=gemini` is intentionally no longer selected by the UI because it
    consumes API quota. Use local auto-training for table/file retrieval.
    """
    if user_role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin can train/rebuild semantic data agents.")
    provider = (provider or "local").lower().strip()
    if provider not in {"local", "auto", "gemini"}:
        raise HTTPException(status_code=400, detail="provider must be local, auto, or gemini")
    if provider in {"local", "auto"}:
        result = run_local_training_now(
            mongo_uri=MONGO_URI, mongo_db_name=MONGO_DB_NAME, trigger_source="compatibility_endpoint"
        )
        result["training_mode"] = "automatic_incremental_local_semantic_index"
        result["uses_gemini_tokens"] = False
        return result
    # Advanced/manual remote option remains available for an explicit request only.
    result = sync_existing_database_agents(
        mongo_uri=MONGO_URI, mongo_db_name=MONGO_DB_NAME, embedding_provider="gemini"
    )
    result["training_mode"] = "manual_remote_embedding_rebuild"
    result["uses_gemini_tokens"] = True
    result["warning"] = "Gemini embeddings may consume API quota. Automatic training uses local vectors instead."
    return result
