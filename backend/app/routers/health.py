"""Public runtime routes kept separate from the V30 chat application."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse


def create_health_router(
    *,
    app_version: str,
    release_notes: List[str],
    dependency_checks: Callable[[], List[Dict[str, Any]]],
) -> APIRouter:
    """Create public health/version routes with explicit runtime dependencies."""
    router = APIRouter(tags=["runtime"])

    @router.get("/")
    def root():
        return {"service": "MCP Backend Client", "status": "running"}

    @router.get("/health")
    def health():
        """Public liveness endpoint. It intentionally reveals no dependency details."""
        return {"status": "live", "version": app_version}

    @router.get("/health/live")
    def health_live():
        return {"status": "live", "version": app_version}

    @router.get("/health/ready")
    def health_ready():
        """Public readiness endpoint used only by the orchestrator health check."""
        checks = dependency_checks()
        ready = all(item.get("ok") for item in checks)
        payload = {"status": "ready" if ready else "not_ready", "version": app_version, "checks": checks}
        if not ready:
            return JSONResponse(status_code=503, content=payload)
        return payload

    @router.get("/system/version")
    def system_version():
        return {
            "success": True,
            "app_version": app_version,
            "backend_title": "MCP Agent University AI",
            "features": {
                "agent_orchestrator": "V30 deterministic planning + local semantic and supervised routing",
                "debug_trace": True,
                "route_table": True,
                "learning_memory": True,
                "neural_data_agents": True,
                "auto_local_training": True,
                "local_router_learning": True,
                "pdf_excel_upload": True,
                "pinned_document_q_and_a": True,
                "persistent_document_context": True,
                "reading_guide_evidence_disclosure": True,
                "release_quality_gate": True,
                "live_database_smoke_gate": True,
                "controlled_learning_review": True,
                "answer_feedback": True,
                "pdpa_policy": True,
                "signed_identity_enforcement": True,
                "mcp_internal_gateway": True,
                "rate_limits": True,
                "privacy_preserving_audit_log": True,
                "production_hardening_gate": True,
                "trainable_neural_router": True,
                "synthetic_development_dataset": True,
                "normalized_academic_tables": True,
                "data_driven_chat_benchmark": True,
            },
            "release_notes": release_notes,
        }

    return router
