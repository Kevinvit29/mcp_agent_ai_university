"""Login endpoint with production-safe identity tokens.

The legacy sample identifiers remain available only in development so the demo
can run from its seeded data. Production requires a password_hash field for
student/advisor accounts (or an external identity-provider integration).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pymongo import MongoClient

from app.db.postgres import get_or_create_session
from app.admin_accounts import authenticate_admin
from app.production_security import app_environment, is_production, issue_access_token

router = APIRouter()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB = os.getenv("MONGO_DB", "university_mongo")

mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB]


def _legacy_passwords_allowed() -> bool:
    default = "false" if is_production() else "true"
    return (os.getenv("ALLOW_LEGACY_DEMO_PASSWORDS") or default).strip().lower() == "true"


def _verify_pbkdf2_password(password: str, encoded: str) -> bool:
    """Verify pbkdf2_sha256$iterations$salt$base64digest without another package."""
    try:
        scheme, iterations_text, salt, encoded_digest = str(encoded).split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if not 100_000 <= iterations <= 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt.encode("utf-8"), iterations)
        expected = base64.b64decode(encoded_digest.encode("ascii"), validate=True)
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def _verify_account_password(account: dict, password: str, legacy_field: str) -> bool:
    password_hash = account.get("password_hash")
    if password_hash:
        return _verify_pbkdf2_password(password, str(password_hash))
    if _legacy_passwords_allowed():
        # Only demo mode supports national ID / phone fallback. This never runs in
        # production unless an operator explicitly overrides the safer default.
        return hmac.compare_digest(str(account.get(legacy_field) or ""), str(password or ""))
    return False


def _login_response(request: Request, *, role: str, subject_id: str, name: str, session_id: str, extra: Optional[dict] = None) -> dict:
    token, identity = issue_access_token(role, subject_id)
    request.state.authenticated_identity = identity
    payload = {
        "success": True,
        "role": role,
        "name": name,
        "session_id": session_id,
        "access_token": token,
        "token_type": "Bearer",
        "expires_at": identity.expires_at,
        "auth_mode": "signed_session_token",
    }
    if extra:
        payload.update(extra)
    return payload


@router.post("/login")
def login(payload: dict, request: Request):
    role = (payload.get("role") or "").lower().strip()
    user_id = str(payload.get("user_id") or "").strip()
    password = str(payload.get("password") or "")

    if role == "student":
        student = mongo_db.students.find_one({"student_id": user_id}, {"_id": 0})
        if not student or not _verify_account_password(student, password, "national_id"):
            raise HTTPException(status_code=401, detail="Invalid student credentials.")
        session_id = get_or_create_session(None, "student", requester_student_id=student["student_id"])
        return _login_response(
            request,
            role="student",
            subject_id=student["student_id"],
            name=student["name"],
            session_id=session_id,
            extra={"student_id": student["student_id"]},
        )

    if role == "advisor":
        advisor = mongo_db.advisors.find_one({"advisor_id": user_id}, {"_id": 0})
        if not advisor or not _verify_account_password(advisor, password, "phone"):
            raise HTTPException(status_code=401, detail="Invalid advisor credentials.")
        session_id = get_or_create_session(None, "advisor", requester_advisor_id=advisor["advisor_id"])
        return _login_response(
            request,
            role="advisor",
            subject_id=advisor["advisor_id"],
            name=advisor["name"],
            session_id=session_id,
            extra={"advisor_id": advisor["advisor_id"]},
        )

    if role == "admin":
        # V30: Administrator credentials come from PostgreSQL. Environment
        # variables are used only once at startup to bootstrap the first record.
        admin = authenticate_admin(user_id, password)
        if not admin:
            raise HTTPException(status_code=401, detail="Invalid administrator credentials.")
        session_id = get_or_create_session(None, "admin")
        return _login_response(
            request,
            role="admin",
            subject_id=admin["admin_id"],
            name=admin["display_name"],
            session_id=session_id,
            extra={"admin_id": admin["admin_id"], "username": admin["username"]},
        )

    raise HTTPException(status_code=400, detail="Invalid role.")
