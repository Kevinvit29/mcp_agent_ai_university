"""Database operations available only to the Advisor API."""

from app.db.postgres import (
    advisor_teaches_subject,
    create_or_update_data_agent_index,
    delete_advisor_document_for_advisor,
    get_advisor_document_for_advisor,
    list_advisor_documents_for_advisor,
    list_advisor_subjects,
    save_advisor_document,
)

__all__ = [
    "advisor_teaches_subject",
    "create_or_update_data_agent_index",
    "delete_advisor_document_for_advisor",
    "get_advisor_document_for_advisor",
    "list_advisor_documents_for_advisor",
    "list_advisor_subjects",
    "save_advisor_document",
]
