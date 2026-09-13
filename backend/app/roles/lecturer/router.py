"""Lecturer-only teaching assignment and course-material routes."""

from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.dependencies import require_identity
from app.roles.lecturer import repository as lecturer_data


KnowledgeProcessor = Callable[[bytes, str, str], Dict[str, Any]]


def create_lecturer_router(process_knowledge_file: KnowledgeProcessor) -> APIRouter:
    router = APIRouter(prefix="/lecturer", tags=["lecturer"])

    @router.get("/subjects")
    def subjects(request: Request):
        identity = require_identity(request, "lecturer")
        if not identity.lecturer_id or not identity.advisor_id:
            raise HTTPException(status_code=400, detail="Signed Lecturer identity is missing its teaching assignment.")
        rows = lecturer_data.list_advisor_subjects(identity.advisor_id)
        return {
            "success": True,
            "lecturer_id": identity.lecturer_id,
            "subjects": [
                {"lecturer_id": identity.lecturer_id, "subject_code": row["subject_code"], "subject_name": row["subject_name"]}
                for row in rows
            ],
        }

    @router.post("/documents/upload")
    async def upload_document(
        request: Request,
        file: UploadFile = File(...),
        subject_code: str = Form(...),
        storage_target: str = Form("postgres"),
    ):
        identity = require_identity(request, "lecturer")
        lecturer_id = identity.lecturer_id
        teaching_scope_id = identity.advisor_id
        if not lecturer_id or not teaching_scope_id:
            raise HTTPException(status_code=400, detail="Signed Lecturer identity is missing its teaching assignment.")
        subject_code = (subject_code or "").strip().upper()
        taught = lecturer_data.lecturer_teaches_subject(teaching_scope_id, subject_code)
        if not taught:
            raise HTTPException(status_code=403, detail="You can only upload files for classes assigned to you.")

        processed = process_knowledge_file(await file.read(), file.filename or "upload", storage_target)
        processed["conclusion_table"].update({
            "document_scope": "lecturer_course_document",
            "lecturer_id": lecturer_id,
            "teaching_scope_id": teaching_scope_id,
            "subject_code": subject_code,
            "subject_name": taught["subject_name"],
        })
        row = lecturer_data.save_lecturer_document(
            lecturer_id=lecturer_id,
            teaching_scope_id=teaching_scope_id,
            subject_code=subject_code,
            subject_name=taught["subject_name"],
            filename=file.filename or "upload",
            uploaded_by=lecturer_id,
            summary=processed["summary"],
            conclusion_table=processed["conclusion_table"],
            text_preview=processed["text_preview"],
            full_text=processed["text"],
            extraction_method=processed["extraction_method"],
            detected_language=processed["detected_language"],
            source_type=processed["source_type"],
            storage_target=processed["storage_target"],
            cloned_agent_name=processed["cloned_agent_name"],
            structured_data=processed["structured_data"],
            mongo_object_id=processed["mongo_object_id"],
        )
        neural_agent = lecturer_data.create_or_update_data_agent_index(
            document_scope="lecturer",
            document_id=int(row["id"]),
            filename=file.filename or "upload",
            source_type=processed["source_type"],
            storage_target=processed["storage_target"],
            cloned_agent_name=processed["cloned_agent_name"],
            structured_data=processed["structured_data"],
            summary=processed["summary"],
            conclusion_table=processed["conclusion_table"],
            full_text=processed["text"],
            owner_role="lecturer",
            owner_id=lecturer_id,
            subject_code=subject_code,
            subject_name=taught["subject_name"],
        )
        return {"success": True, "document": row, "selected_agent_clone": processed["cloned_agent_name"], "neural_data_agent": neural_agent}

    @router.get("/documents")
    def documents(request: Request):
        identity = require_identity(request, "lecturer")
        rows = lecturer_data.list_lecturer_documents_for_lecturer(identity.lecturer_id, identity.advisor_id, limit=50)
        return {"success": True, "documents": rows}

    @router.get("/documents/{document_id}")
    def document_detail(document_id: int, request: Request):
        identity = require_identity(request, "lecturer")
        row = lecturer_data.get_lecturer_document_for_lecturer(document_id, identity.lecturer_id, identity.advisor_id)
        if not row:
            raise HTTPException(status_code=404, detail="Lecturer document not found or not owned by this Lecturer.")
        return {"success": True, "document": row}

    @router.delete("/documents/{document_id}")
    def remove_document(document_id: int, request: Request):
        identity = require_identity(request, "lecturer")
        deleted = lecturer_data.delete_lecturer_document_for_lecturer(document_id, identity.lecturer_id, identity.advisor_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Lecturer document not found or not owned by this Lecturer.")
        return {"success": True, "deleted_document_id": document_id}

    return router
