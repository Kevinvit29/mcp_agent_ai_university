"""Student-only, read-only subject and document routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.dependencies import require_identity
from app.roles.student import repository as student_data


router = APIRouter(prefix="/student", tags=["student"])


@router.get("/subjects")
def subjects(request: Request):
    identity = require_identity(request, "student")
    if not identity.student_id:
        raise HTTPException(status_code=400, detail="Signed student identity is missing a student ID.")
    return {"success": True, "subjects": student_data.list_student_subjects(identity.student_id)}


@router.get("/documents")
def documents(request: Request):
    identity = require_identity(request, "student")
    return {"success": True, "documents": student_data.list_student_accessible_documents(identity.student_id, limit=50)}


@router.get("/documents/{document_id}")
def document_detail(document_id: int, request: Request):
    identity = require_identity(request, "student")
    doc = student_data.get_student_accessible_document(document_id, identity.student_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or not accessible for this student's enrolled subjects.")
    return {"success": True, "document": doc}
