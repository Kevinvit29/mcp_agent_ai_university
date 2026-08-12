"""Advisor-only subject and document routes."""

from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.dependencies import require_identity
from app.roles.advisor import repository as advisor_data


KnowledgeProcessor = Callable[[bytes, str, str], Dict[str, Any]]


def create_advisor_router(process_knowledge_file: KnowledgeProcessor) -> APIRouter:
    router = APIRouter(prefix="/advisor", tags=["advisor"])

    @router.get("/subjects")
    def subjects(request: Request):
        identity = require_identity(request, "advisor")
        if not identity.advisor_id:
            raise HTTPException(status_code=400, detail="Signed advisor identity is missing an advisor ID.")
        return {"success": True, "subjects": advisor_data.list_advisor_subjects(identity.advisor_id)}

    @router.post("/documents/upload")
    async def upload_document(
        request: Request,
        file: UploadFile = File(...),
        subject_code: str = Form(...),
        storage_target: str = Form("postgres"),
    ):
        identity = require_identity(request, "advisor")
        advisor_id = identity.advisor_id
        if not advisor_id:
            raise HTTPException(status_code=400, detail="Signed advisor identity is missing an advisor ID.")
        subject_code = (subject_code or "").strip().upper()
        taught = advisor_data.advisor_teaches_subject(advisor_id, subject_code)
        if not taught:
            raise HTTPException(status_code=403, detail="You can only upload files for subjects you teach.")

        processed = process_knowledge_file(await file.read(), file.filename or "upload", storage_target)
        processed["conclusion_table"]["document_scope"] = "advisor_subject_document"
        processed["conclusion_table"]["advisor_id"] = advisor_id
        processed["conclusion_table"]["subject_code"] = subject_code
        processed["conclusion_table"]["subject_name"] = taught["subject_name"]
        row = advisor_data.save_advisor_document(
            advisor_id=advisor_id,
            subject_code=subject_code,
            subject_name=taught["subject_name"],
            filename=file.filename or "upload",
            uploaded_by=advisor_id,
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
        neural_agent = advisor_data.create_or_update_data_agent_index(
            document_scope="advisor",
            document_id=int(row["id"]),
            filename=file.filename or "upload",
            source_type=processed["source_type"],
            storage_target=processed["storage_target"],
            cloned_agent_name=processed["cloned_agent_name"],
            structured_data=processed["structured_data"],
            summary=processed["summary"],
            conclusion_table=processed["conclusion_table"],
            full_text=processed["text"],
            owner_role="advisor",
            owner_id=advisor_id,
            subject_code=subject_code,
            subject_name=taught["subject_name"],
        )
        return {"success": True, "document": row, "selected_agent_clone": processed["cloned_agent_name"], "neural_data_agent": neural_agent}

    @router.get("/documents")
    def documents(request: Request):
        identity = require_identity(request, "advisor")
        return {"success": True, "documents": advisor_data.list_advisor_documents_for_advisor(identity.advisor_id, limit=50)}

    @router.get("/documents/{document_id}")
    def document_detail(document_id: int, request: Request):
        identity = require_identity(request, "advisor")
        doc = advisor_data.get_advisor_document_for_advisor(document_id, identity.advisor_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found or not owned by this advisor.")
        return {"success": True, "document": doc}

    @router.delete("/documents/{document_id}")
    def remove_document(document_id: int, request: Request):
        identity = require_identity(request, "advisor")
        if not advisor_data.delete_advisor_document_for_advisor(document_id, identity.advisor_id):
            raise HTTPException(status_code=404, detail="Document not found or not owned by this advisor.")
        return {"success": True, "deleted_document_id": document_id}

    return router
