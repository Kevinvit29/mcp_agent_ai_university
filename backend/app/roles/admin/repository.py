"""Database operations available only to the Admin API."""

from app.admin_accounts import (
    change_admin_password,
    create_admin_account,
    get_admin_account,
    list_admin_accounts,
    set_admin_active,
)
from app.db.postgres import (
    create_or_update_data_agent_index,
    delete_admin_document,
    delete_any_document_for_admin,
    get_admin_document,
    get_any_document_for_admin,
    list_admin_documents,
    list_all_documents_for_admin,
    save_admin_document,
)

__all__ = [
    "change_admin_password",
    "create_admin_account",
    "get_admin_account",
    "list_admin_accounts",
    "set_admin_active",
    "create_or_update_data_agent_index",
    "delete_admin_document",
    "delete_any_document_for_admin",
    "get_admin_document",
    "get_any_document_for_admin",
    "list_admin_documents",
    "list_all_documents_for_admin",
    "save_admin_document",
]
