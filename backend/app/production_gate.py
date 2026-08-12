"""Deterministic production-readiness gate used by CI and the admin dashboard."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from app.production_security import production_configuration_errors

ROOT = Path(__file__).resolve().parents[2]


def _check(check_id: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"id": check_id, "passed": bool(passed), "detail": detail}


def run_production_hardening_gate() -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    compose = ROOT / "docker-compose.yml"
    ci = ROOT / ".github" / "workflows" / "release-gate.yml"
    backup = ROOT / "scripts" / "backup.sh"
    verify = ROOT / "scripts" / "verify_backup.sh"
    restore = ROOT / "scripts" / "restore.sh"
    docs = ROOT / "docs" / "V28_PRODUCTION_HARDENING.md"

    checks.append(_check("no_packaged_runtime_env", not (ROOT / ".env").exists(), "No runtime .env secrets are packaged."))
    checks.append(_check("compose_hardening", compose.exists() and "healthcheck:" in compose.read_text(encoding="utf-8") and "mongo_data" in compose.read_text(encoding="utf-8"), "Compose has service health checks and persistent volumes."))
    checks.append(_check("ci_release_gate", ci.exists(), "CI workflow runs deterministic release gates."))
    checks.append(_check("backup_restore_assets", all(path.exists() for path in (backup, verify, restore)), "Backup, verification, and guarded restore scripts are present."))
    checks.append(_check("operations_documented", docs.exists(), "Production deployment, monitoring, and recovery guidance is documented."))
    errors = production_configuration_errors()
    checks.append(_check("production_secret_configuration", not errors, "Production secret/CORS configuration is valid." if not errors else "; ".join(errors)))

    passed = sum(1 for item in checks if item["passed"])
    return {
        "success": passed == len(checks),
        "version": "V28_PRODUCTION_HARDENING",
        "summary": {"passed": passed, "total": len(checks), "failed": len(checks) - passed},
        "checks": checks,
        "failed_case_ids": [item["id"] for item in checks if not item["passed"]],
        "note": "This gate never reads student records, document text, tokens, or password values.",
    }
