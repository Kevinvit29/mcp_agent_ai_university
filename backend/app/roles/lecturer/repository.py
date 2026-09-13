"""Database operations available only to the Lecturer API."""

from app.db.postgres import (
    create_or_update_data_agent_index,
    delete_lecturer_document_for_lecturer,
    get_lecturer_document_for_lecturer,
    lecturer_teaches_subject,
    list_advisor_subjects,
    list_lecturer_documents_for_lecturer,
    save_lecturer_document,
)

__all__ = [
    "create_or_update_data_agent_index",
    "delete_lecturer_document_for_lecturer",
    "get_lecturer_document_for_lecturer",
    "lecturer_teaches_subject",
    "list_advisor_subjects",
    "list_lecturer_documents_for_lecturer",
    "save_lecturer_document",
]
