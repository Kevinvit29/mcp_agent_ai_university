"""Shared authenticated-request dependencies for role-specific API routers."""

from __future__ import annotations

from fastapi import HTTPException, Request


def require_identity(request: Request, role: str):
    """Return the signed identity only when it matches the required role."""
    identity = getattr(request.state, "identity", None)
    if not identity or identity.role != role:
        label = {"admin": "Administrator", "advisor": "Advisor", "student": "Student"}.get(role, role.title())
        raise HTTPException(status_code=403, detail=f"{label} access is required.")
    return identity
