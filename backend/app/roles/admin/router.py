"""Admin-only account and knowledge routes."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.dependencies import require_identity
from app.roles.admin import repository as admin_data
from app.reports.document_pdf_viewer import create_document_table_pdf


KnowledgeProcessor = Callable[[bytes, str, str], Dict[str, Any]]


def create_admin_router(process_knowledge_file: KnowledgeProcessor) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.get("/account/me")
    def account_me(request: Request):
        identity = require_identity(request, "admin")
        account = admin_data.get_admin_account(identity.subject_id)
        if not account or not account.get("is_active"):
            raise HTTPException(status_code=401, detail="Administrator account is no longer active. Please sign in again.")
        return {"success": True, "account": account}

    @router.get("/system/dataset-status")
    def dataset_status(request: Request):
        require_identity(request, "admin")
        from app.system_bootstrap import dataset_status as read_dataset_status
        return read_dataset_status()

    @router.post("/account/change-password")
    def account_change_password(payload: dict, request: Request):
        identity = require_identity(request, "admin")
        try:
            account = admin_data.change_admin_password(
                admin_id=identity.subject_id,
                current_password=str(payload.get("current_password") or ""),
                new_password=str(payload.get("new_password") or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "detail": "Password updated. The new password is stored securely in PostgreSQL.", "account": account}

    @router.get("/accounts")
    def accounts_list(request: Request):
        require_identity(request, "admin")
        return {"success": True, "accounts": admin_data.list_admin_accounts()}

    @router.post("/accounts")
    def accounts_create(payload: dict, request: Request):
        identity = require_identity(request, "admin")
        try:
            account = admin_data.create_admin_account(
                username=str(payload.get("username") or ""),
                display_name=str(payload.get("display_name") or ""),
                password=str(payload.get("password") or ""),
                created_by=identity.subject_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "detail": "Administrator account created in PostgreSQL.", "account": account}

    @router.post("/accounts/{admin_id}/active")
    def account_set_active(admin_id: str, payload: dict, request: Request):
        identity = require_identity(request, "admin")
        active = payload.get("is_active")
        if not isinstance(active, bool):
            raise HTTPException(status_code=400, detail="is_active must be true or false.")
        try:
            account = admin_data.set_admin_active(
                target_admin_id=admin_id,
                active=active,
                actor_admin_id=identity.subject_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "account": account}

    @router.post("/documents/upload")
    async def upload_document(
        request: Request,
        file: UploadFile = File(...),
        uploaded_by: str = Form("ADMIN"),
        storage_target: str = Form("postgres"),
    ):
        require_identity(request, "admin")
        processed = process_knowledge_file(await file.read(), file.filename or "upload", storage_target)
        row = admin_data.save_admin_document(
            filename=file.filename or "upload",
            uploaded_by="ADMIN",
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
        neural_agent = admin_data.create_or_update_data_agent_index(
            document_scope="admin",
            document_id=int(row["id"]),
            filename=file.filename or "upload",
            source_type=processed["source_type"],
            storage_target=processed["storage_target"],
            cloned_agent_name=processed["cloned_agent_name"],
            structured_data=processed["structured_data"],
            summary=processed["summary"],
            conclusion_table=processed["conclusion_table"],
            full_text=processed["text"],
            owner_role="admin",
            owner_id="ADMIN",
        )
        return {"success": True, "document": row, "selected_agent_clone": processed["cloned_agent_name"], "neural_data_agent": neural_agent}

    @router.get("/documents")
    def documents(request: Request):
        require_identity(request, "admin")
        return {"success": True, "documents": admin_data.list_admin_documents(limit=50)}

    @router.get("/documents/{document_id}")
    def document_detail(document_id: int, request: Request):
        require_identity(request, "admin")
        doc = admin_data.get_admin_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"success": True, "document": doc}

    @router.delete("/documents/{document_id}")
    def remove_document(document_id: int, request: Request):
        require_identity(request, "admin")
        if not admin_data.delete_admin_document(document_id):
            raise HTTPException(status_code=404, detail="Document not found")
        return {"success": True, "deleted_document_id": document_id}

    @router.post("/documents/{document_id}/pdf-view")
    def document_pdf_view(document_id: int, request: Request):
        require_identity(request, "admin")
        doc = admin_data.get_admin_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        table = doc.get("conclusion_table") or {}
        if isinstance(table, str):
            try:
                table = json.loads(table)
            except Exception:
                table = {}
        rows = table.get("rows") or [{"Section": "Summary", "Information": doc.get("summary") or "No table data found for this document."}]
        columns = table.get("columns") or ["Section", "Information"]
        result = create_document_table_pdf(
            title=f"Document Table View - {doc.get('filename') or document_id}",
            rows=rows,
            columns=columns,
        )
        public_app_url = os.getenv("PUBLIC_APP_URL", "http://localhost:3100").rstrip("/")
        return {"success": True, "pdf_url": f"{public_app_url}{result['url']}", "filename": result["filename"]}

    @router.get("/all-documents")
    def all_documents(request: Request):
        require_identity(request, "admin")
        return {"success": True, "documents": admin_data.list_all_documents_for_admin(limit=100)}

    @router.get("/all-documents/{document_scope}/{document_id}")
    def any_document_detail(document_scope: str, document_id: int, request: Request):
        require_identity(request, "admin")
        doc = admin_data.get_any_document_for_admin(document_scope, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"success": True, "document": doc}

    @router.delete("/all-documents/{document_scope}/{document_id}")
    def remove_any_document(document_scope: str, document_id: int, request: Request):
        require_identity(request, "admin")
        if not admin_data.delete_any_document_for_admin(document_scope, document_id):
            raise HTTPException(status_code=404, detail="Document not found")
        return {"success": True, "deleted_document_id": document_id, "document_scope": document_scope}

    return router
