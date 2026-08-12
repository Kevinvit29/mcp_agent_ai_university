import sys
from pathlib import Path
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.production_gate import run_production_hardening_gate
from app.production_security import (
    RequestIdentity,
    SecurityError,
    SlidingWindowRateLimiter,
    issue_access_token,
    production_configuration_errors,
    rewrite_identity_query,
    route_required_role,
    verify_access_token,
)


def test_signed_token_binds_role_and_owner_and_rejects_tampering(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-at-least-32-characters-long")
    token, issued = issue_access_token("student", "S001", ttl_seconds=300, now=1_000)
    verified = verify_access_token(token, now=1_001)
    assert verified.role == "student"
    assert verified.student_id == "S001"
    assert verified.advisor_id is None
    with pytest.raises(SecurityError):
        verify_access_token(token + "tampered", now=1_001)


def test_expired_token_is_rejected(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-at-least-32-characters-long")
    token, _ = issue_access_token("advisor", "A001", ttl_seconds=10, now=1_000)
    with pytest.raises(SecurityError):
        verify_access_token(token, now=1_011)


def test_verified_identity_replaces_spoofed_query_identity():
    scope = {"query_string": b"user_role=admin&requester_student_id=S999&requester_advisor_id=A999&session_id=abc"}
    rewrite_identity_query(scope, RequestIdentity("student", "S001", 1, 2, "token"))
    values = parse_qs(scope["query_string"].decode("latin-1"))
    assert values["user_role"] == ["student"]
    assert values["requester_student_id"] == ["S001"]
    assert "requester_advisor_id" not in values
    assert values["session_id"] == ["abc"]


def test_rate_limiter_blocks_after_limit_and_calculates_retry_window():
    limiter = SlidingWindowRateLimiter()
    assert limiter.check("student:S001", limit=2, period_seconds=60, now=10)[0] is True
    assert limiter.check("student:S001", limit=2, period_seconds=60, now=11)[0] is True
    allowed, retry = limiter.check("student:S001", limit=2, period_seconds=60, now=12)
    assert allowed is False
    assert retry >= 1
    assert limiter.check("student:S001", limit=2, period_seconds=60, now=71)[0] is True


def test_role_routes_are_server_restricted_not_ui_restricted():
    assert route_required_role("/admin/audit-logs") == {"admin"}
    assert route_required_role("/advisor/documents") == {"advisor"}
    assert route_required_role("/student/documents") == {"student"}


def test_production_config_rejects_defaults(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "development-only-change-this-secret-before-production-32")
    monkeypatch.setenv("MCP_INTERNAL_KEY", "development-only-change-this-mcp-key-before-production")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin123")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("ALLOW_LEGACY_DEMO_PASSWORDS", "true")
    errors = production_configuration_errors()
    assert len(errors) >= 3


def test_v28_production_hardening_gate_passes_for_packaged_release(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    report = run_production_hardening_gate()
    assert report["success"] is True, report
    assert report["summary"]["failed"] == 0
