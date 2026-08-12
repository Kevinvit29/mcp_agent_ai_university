"""Production security primitives for the University AI backend.

These helpers keep browser-supplied role/identity fields from becoming an
authorization source. The signed token issued at login is the only authority
for a request's role and owner identifier.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import parse_qsl, urlencode


VALID_ROLES = {"student", "advisor", "admin"}
DEV_DEFAULT_SECRET = "development-only-change-this-secret-before-production-32"
DEV_DEFAULT_MCP_KEY = "development-only-change-this-mcp-key-before-production"


class SecurityError(ValueError):
    """Raised when a request cannot be authenticated or authorized."""


@dataclass(frozen=True)
class RequestIdentity:
    role: str
    subject_id: str
    issued_at: int
    expires_at: int
    token_id: str

    @property
    def student_id(self) -> Optional[str]:
        return self.subject_id if self.role == "student" else None

    @property
    def advisor_id(self) -> Optional[str]:
        return self.subject_id if self.role == "advisor" else None

    def public(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "student_id": self.student_id,
            "advisor_id": self.advisor_id,
            "expires_at": self.expires_at,
        }


def app_environment() -> str:
    return (os.getenv("APP_ENV") or "development").strip().lower()


def is_production() -> bool:
    return app_environment() in {"production", "prod"}


def access_token_ttl_seconds() -> int:
    try:
        return max(300, min(int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "28800")), 86_400))
    except ValueError:
        return 28_800


def _secret() -> bytes:
    configured = (os.getenv("APP_SECRET_KEY") or "").strip()
    if not configured:
        if is_production():
            raise SecurityError("APP_SECRET_KEY is required in production.")
        configured = DEV_DEFAULT_SECRET
    if is_production() and (configured == DEV_DEFAULT_SECRET or len(configured) < 32):
        raise SecurityError("APP_SECRET_KEY must be a unique value with at least 32 characters in production.")
    return configured.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign(encoded_payload: str) -> str:
    return _b64encode(hmac.new(_secret(), encoded_payload.encode("ascii"), hashlib.sha256).digest())


def issue_access_token(role: str, subject_id: str, ttl_seconds: Optional[int] = None, now: Optional[int] = None) -> Tuple[str, RequestIdentity]:
    role = (role or "").strip().lower()
    subject_id = str(subject_id or "").strip()
    if role not in VALID_ROLES or not subject_id:
        raise SecurityError("A valid role and account identifier are required.")
    issued_at = int(now if now is not None else time.time())
    expires_at = issued_at + int(ttl_seconds if ttl_seconds is not None else access_token_ttl_seconds())
    payload = {
        "v": 1,
        "role": role,
        "sub": subject_id,
        "iat": issued_at,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    token = f"v1.{encoded}.{_sign(encoded)}"
    return token, RequestIdentity(role, subject_id, issued_at, expires_at, payload["jti"])


def verify_access_token(token: str, now: Optional[int] = None) -> RequestIdentity:
    if not token:
        raise SecurityError("Missing access token.")
    try:
        version, encoded, signature = token.split(".", 2)
    except ValueError as exc:
        raise SecurityError("Malformed access token.") from exc
    if version != "v1":
        raise SecurityError("Unsupported access token version.")
    expected = _sign(encoded)
    if not hmac.compare_digest(signature, expected):
        raise SecurityError("Invalid access token signature.")
    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
        role = str(payload["role"]).lower()
        subject_id = str(payload["sub"])
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
        token_id = str(payload["jti"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise SecurityError("Invalid access token payload.") from exc
    if role not in VALID_ROLES or not subject_id or not token_id:
        raise SecurityError("Invalid access token claims.")
    current = int(now if now is not None else time.time())
    if expires_at <= current:
        raise SecurityError("Access token expired.")
    if issued_at > current + 300:
        raise SecurityError("Access token issue time is invalid.")
    return RequestIdentity(role, subject_id, issued_at, expires_at, token_id)


def bearer_token_from_headers(headers: Any) -> str:
    auth = (headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # Header fallback makes the browser client easy to inspect while retaining a
    # standards-compatible Authorization header in production deployments.
    return (headers.get("x-access-token") or "").strip()


def route_required_role(path: str) -> Optional[Iterable[str]]:
    """Return allowed roles for route families that are inherently role-specific."""
    if path.startswith("/admin/"):
        return {"admin"}
    if path.startswith("/advisor/"):
        return {"advisor"}
    if path.startswith("/student/"):
        return {"student"}
    if path.startswith("/ai/training") or path.startswith("/ai/data-agents/reindex") or path.startswith("/ai/data-agents/train"):
        return {"admin"}
    return None


def is_public_path(path: str) -> bool:
    return path in {"/", "/health", "/health/live", "/health/ready", "/openapi.json", "/docs", "/redoc", "/login"} or path.startswith("/docs/") or path.startswith("/redoc/")


def request_id_from_headers(headers: Any) -> str:
    candidate = (headers.get("x-request-id") or "").strip()
    if 8 <= len(candidate) <= 80 and all(ch.isalnum() or ch in {"-", "_"} for ch in candidate):
        return candidate
    return uuid.uuid4().hex


def get_client_ip(headers: Any, client_host: Optional[str]) -> str:
    # Only trust proxy forwarding headers when a deployment explicitly opts in.
    if (os.getenv("TRUST_PROXY_HEADERS") or "false").strip().lower() == "true":
        forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return client_host or "unknown"


def hash_for_audit(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def rewrite_identity_query(scope: Dict[str, Any], identity: RequestIdentity) -> None:
    """Remove client-controlled identity fields and replace them with verified claims."""
    raw = (scope.get("query_string") or b"").decode("latin-1")
    protected = {"user_role", "requester_student_id", "requester_advisor_id"}
    pairs = [(key, value) for key, value in parse_qsl(raw, keep_blank_values=True) if key not in protected]
    pairs.append(("user_role", identity.role))
    if identity.student_id:
        pairs.append(("requester_student_id", identity.student_id))
    if identity.advisor_id:
        pairs.append(("requester_advisor_id", identity.advisor_id))
    scope["query_string"] = urlencode(pairs, doseq=True).encode("latin-1")


def apply_identity_to_model(model: Any, identity: RequestIdentity) -> Any:
    """Force request models to use verified identity values before planning/database access."""
    model.user_role = identity.role
    if hasattr(model, "requester_student_id"):
        model.requester_student_id = identity.student_id
    if hasattr(model, "requester_advisor_id"):
        model.requester_advisor_id = identity.advisor_id
    return model


def mcp_service_key() -> str:
    value = (os.getenv("MCP_INTERNAL_KEY") or "").strip()
    if not value:
        if is_production():
            raise SecurityError("MCP_INTERNAL_KEY is required in production.")
        value = DEV_DEFAULT_MCP_KEY
    if is_production() and (value == DEV_DEFAULT_MCP_KEY or len(value) < 32):
        raise SecurityError("MCP_INTERNAL_KEY must be a unique value with at least 32 characters in production.")
    return value


def production_configuration_errors() -> list[str]:
    errors: list[str] = []
    if is_production():
        try:
            _secret()
        except SecurityError as exc:
            errors.append(str(exc))
        try:
            mcp_service_key()
        except SecurityError as exc:
            errors.append(str(exc))
        # Admin passwords live in PostgreSQL. The first account is bootstrapped
        # at startup only when the table is empty, and that flow validates its
        # own ADMIN_BOOTSTRAP_PASSWORD value without retaining it for sign-in.
        allowed_origins = (os.getenv("CORS_ALLOWED_ORIGINS") or "").strip()
        if not allowed_origins or "*" in allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS must list explicit HTTPS origins in production.")
        if (os.getenv("ALLOW_LEGACY_DEMO_PASSWORDS") or "false").strip().lower() == "true":
            errors.append("ALLOW_LEGACY_DEMO_PASSWORDS must be false in production.")
        if (os.getenv("DEMO_DATA_MODE") or "false").strip().lower() == "true":
            errors.append("DEMO_DATA_MODE must be false in production.")
        if (os.getenv("AUTO_SEED_SYNTHETIC_DATA") or "false").strip().lower() == "true":
            errors.append("AUTO_SEED_SYNTHETIC_DATA must be false in production.")
        bootstrap_password = (os.getenv("ADMIN_BOOTSTRAP_PASSWORD") or "").strip()
        if bootstrap_password == "admin123":
            errors.append("ADMIN_BOOTSTRAP_PASSWORD cannot use the default demo password in production.")
        if bootstrap_password and len(bootstrap_password) < 12:
            errors.append("ADMIN_BOOTSTRAP_PASSWORD must be at least 12 characters when supplied in production.")
    return errors


class SlidingWindowRateLimiter:
    """Small bounded, thread-safe rate limiter for a single backend instance.

    Deployment documentation pairs this with an edge/WAF limit for multi-replica
    installations. It is deliberately local so it adds no external dependency.
    """

    def __init__(self, max_keys: int = 20_000):
        self._events: Dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def check(self, key: str, limit: int, period_seconds: int, now: Optional[float] = None) -> Tuple[bool, int]:
        current = float(now if now is not None else time.time())
        cutoff = current - period_seconds
        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(period_seconds - (current - bucket[0])))
                return False, retry_after
            bucket.append(current)
            if len(self._events) > self._max_keys:
                # Drop only empty/stale buckets; preserves active limits without an
                # unbounded memory footprint.
                stale_keys = [name for name, values in self._events.items() if not values or values[-1] <= cutoff]
                for stale in stale_keys[: max(1, len(self._events) - self._max_keys)]:
                    self._events.pop(stale, None)
            return True, 0


def rate_limit_policy(method: str, path: str) -> Tuple[int, int, str]:
    if path == "/login" and method == "POST":
        return 10, 900, "login"
    if path == "/chat" and method == "POST":
        return 40, 60, "chat"
    if path.endswith("/documents/upload") and method == "POST":
        return 20, 3600, "upload"
    if path.startswith("/admin/") and method != "GET":
        return 40, 60, "admin_write"
    return 240, 60, "api"
