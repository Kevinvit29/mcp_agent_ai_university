"""Read-only database operations available only to the Student API."""

from app.db.postgres import (
    get_student_accessible_document,
    list_student_accessible_documents,
    list_student_subjects,
)

__all__ = [
    "get_student_accessible_document",
    "list_student_accessible_documents",
    "list_student_subjects",
]
