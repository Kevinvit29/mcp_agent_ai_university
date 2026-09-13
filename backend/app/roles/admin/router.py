"""Admin-only account and knowledge routes."""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.dependencies import require_identity
from app.roles.admin import repository as admin_data
from app.roles.admin import master_import_repository, master_import_service, master_record_service
from app.roles.admin.master_import_models import ImportValidationError
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

    @router.post("/master-data/imports/preview")
    async def preview_student_master_import(
        request: Request,
        file: UploadFile = File(...),
        mapping: str = Form("{}"),
    ):
        """Parse and stage a CSV/Excel student file without changing live data."""
        identity = require_identity(request, "admin")
        try:
            requested_mapping = json.loads(mapping or "{}")
            if not isinstance(requested_mapping, dict):
                raise ValueError("mapping must be a JSON object")
            batch = master_import_service.create_preview(
                raw=await file.read(),
                filename=file.filename or "student-master.csv",
                actor_admin_id=identity.subject_id,
                mapping=requested_mapping,
            )
        except (ImportValidationError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "success": True,
            "detail": "Preview created. Live student records have not been changed.",
            "batch": batch,
        }

    @router.get("/master-data/imports")
    def student_master_imports(request: Request, limit: int = 50):
        require_identity(request, "admin")
        return {"success": True, "imports": master_import_repository.list_batches(limit)}

    @router.get("/master-data/imports/{import_id}")
    def student_master_import_detail(import_id: str, request: Request):
        require_identity(request, "admin")
        batch = master_import_repository.get_batch(import_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Import batch was not found.")
        return {"success": True, "batch": batch}

    @router.post("/master-data/imports/{import_id}/confirm")
    def confirm_student_master_import(import_id: str, payload: dict, request: Request):
        identity = require_identity(request, "admin")
        try:
            return master_import_service.confirm_import(
                import_id,
                actor_admin_id=identity.subject_id,
                confirmed=payload.get("confirm") is True,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'"))
        except master_import_service.ImportStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.get("/master-data/imports/{import_id}/verification")
    def verify_student_master_import(import_id: str, request: Request):
        require_identity(request, "admin")
        if not master_import_repository.get_batch(import_id, preview_limit=1):
            raise HTTPException(status_code=404, detail="Import batch was not found.")
        return master_import_service.verify_import(import_id)

    @router.post("/master-data/imports/{import_id}/rollback")
    def rollback_student_master_import(import_id: str, payload: dict, request: Request):
        identity = require_identity(request, "admin")
        try:
            return master_import_service.rollback_import(
                import_id,
                actor_admin_id=identity.subject_id,
                confirmed=payload.get("confirm") is True,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc).strip("'"))
        except master_import_service.ImportStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.get("/master-data/students")
    def managed_students(request: Request, limit: int = 100):
        require_identity(request, "admin")
        return {"success": True, "students": master_record_service.list_students(limit)}

    @router.post("/master-data/students")
    def add_student(payload: dict, request: Request):
        identity = require_identity(request, "admin")
        try:
            return master_record_service.save_student(
                payload=payload, actor_admin_id=identity.subject_id, create=True,
                confirmed=payload.get("confirm") is True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.patch("/master-data/students/{student_id}")
    def edit_student(student_id: str, payload: dict, request: Request):
        identity = require_identity(request, "admin")
        try:
            return master_record_service.save_student(
                payload=payload, target_student_id=student_id, actor_admin_id=identity.subject_id,
                create=False, confirmed=payload.get("confirm") is True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/master-data/students/{student_id}/active")
    def change_student_active(student_id: str, payload: dict, request: Request):
        require_identity(request, "admin")
        if not isinstance(payload.get("is_active"), bool):
            raise HTTPException(status_code=400, detail="is_active must be true or false.")
        try:
            student = master_record_service.set_student_active(student_id, payload["is_active"])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"success": True, "student": student}

    @router.get("/master-data/advisors")
    def managed_advisors(request: Request, limit: int = 100):
        require_identity(request, "admin")
        return {"success": True, "advisors": master_record_service.list_advisors(limit)}

    @router.post("/master-data/advisors")
    def add_advisor(payload: dict, request: Request):
        require_identity(request, "admin")
        try:
            advisor = master_record_service.save_advisor(
                payload=payload, create=True, confirmed=payload.get("confirm") is True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "advisor": advisor}

    @router.patch("/master-data/advisors/{advisor_id}")
    def edit_advisor(advisor_id: str, payload: dict, request: Request):
        require_identity(request, "admin")
        try:
            advisor = master_record_service.save_advisor(
                payload=payload, target_advisor_id=advisor_id, create=False,
                confirmed=payload.get("confirm") is True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "advisor": advisor}

    @router.post("/master-data/advisors/{advisor_id}/active")
    def change_advisor_active(advisor_id: str, payload: dict, request: Request):
        require_identity(request, "admin")
        if not isinstance(payload.get("is_active"), bool):
            raise HTTPException(status_code=400, detail="is_active must be true or false.")
        try:
            advisor = master_record_service.set_advisor_active(advisor_id, payload["is_active"])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"success": True, "advisor": advisor}

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

    @router.patch("/accounts/{admin_id}")
    def account_update(admin_id: str, payload: dict, request: Request):
        require_identity(request, "admin")
        try:
            account = admin_data.update_admin_account(
                target_admin_id=admin_id,
                username=str(payload.get("username") or ""),
                display_name=str(payload.get("display_name") or ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "account": account}

    @router.post("/accounts/{admin_id}/reset-password")
    def account_reset_password(admin_id: str, payload: dict, request: Request):
        identity = require_identity(request, "admin")
        try:
            account = admin_data.reset_admin_password_by_id(
                target_admin_id=admin_id,
                new_password=str(payload.get("new_password") or ""),
                actor_admin_id=identity.subject_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"success": True, "detail": "Administrator password reset securely.", "account": account}

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
