from typing import Dict, Any, List, Tuple
from pathlib import Path
import os
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "student_scores.xlsx"


def _pg_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        database=os.getenv("POSTGRES_DB", "university_db"),
        user=os.getenv("POSTGRES_USER", "university_user"),
        password=os.getenv("POSTGRES_PASSWORD", "university_pass"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        cursor_factory=RealDictCursor,
    )


def _iso_row(row: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(row)
    if row.get("created_at"):
        row["created_at"] = row["created_at"].isoformat()
    structured = row.get("structured_data") or {}
    if isinstance(structured, dict):
        row["structured_preview"] = {
            "sheet_count": structured.get("sheet_count"),
            "total_rows": structured.get("total_rows"),
            "sheets": [
                {
                    "sheet_name": sheet.get("sheet_name"),
                    "row_count": sheet.get("row_count"),
                    "columns": sheet.get("columns", [])[:40],
                    "sample_rows": sheet.get("sample_rows", [])[:5],
                    "numeric_summary": sheet.get("numeric_summary", {}),
                }
                for sheet in (structured.get("sheets") or [])[:5]
                if isinstance(sheet, dict)
            ],
        }
    return row


def _fetch_excel_uploads_for_role(cur, user_role: str, requester_student_id: str | None, requester_advisor_id: str | None) -> Tuple[List[Dict[str, Any]], str | None]:
    if user_role == "admin":
        cur.execute(
            """
            SELECT id, filename, uploaded_by, summary, conclusion_table, structured_data,
                   source_type, storage_target, cloned_agent_name, created_at,
                   'admin' AS document_scope, NULL::VARCHAR AS advisor_id, NULL::VARCHAR AS subject_code,
                   'Admin/global' AS subject_name
            FROM admin_documents
            WHERE source_type = 'excel'
            UNION ALL
            SELECT id, filename, uploaded_by, summary, conclusion_table, structured_data,
                   source_type, storage_target, cloned_agent_name, created_at,
                   'advisor' AS document_scope, advisor_id, subject_code, subject_name
            FROM advisor_documents
            WHERE source_type = 'excel'
            ORDER BY created_at DESC
            LIMIT 80;
            """
        )
        return cur.fetchall(), None

    if user_role == "advisor":
        if not requester_advisor_id:
            return [], "Advisor Excel access requires logged-in advisor ID."
        cur.execute(
            """
            SELECT id, filename, uploaded_by, summary, conclusion_table, structured_data,
                   source_type, storage_target, cloned_agent_name, created_at,
                   'advisor' AS document_scope, advisor_id, subject_code, subject_name
            FROM advisor_documents
            WHERE source_type = 'excel' AND advisor_id = %s
            ORDER BY created_at DESC
            LIMIT 80;
            """,
            (requester_advisor_id,),
        )
        return cur.fetchall(), None

    if user_role == "student":
        if not requester_student_id:
            return [], "Student Excel access requires logged-in student ID."
        cur.execute(
            """
            SELECT d.id, d.filename, d.uploaded_by, d.summary, d.conclusion_table, d.structured_data,
                   d.source_type, d.storage_target, d.cloned_agent_name, d.created_at,
                   'advisor' AS document_scope, d.advisor_id, d.subject_code, d.subject_name
            FROM advisor_documents d
            JOIN student_subjects ss
              ON ss.student_id = %s
             AND ss.advisor_id = d.advisor_id
             AND ss.subject_code = d.subject_code
            WHERE d.source_type = 'excel'
            ORDER BY d.created_at DESC
            LIMIT 80;
            """,
            (requester_student_id,),
        )
        return cur.fetchall(), None

    return [], "Unknown role. Access denied."


def _keyword_match(row: Dict[str, Any], keyword: str) -> bool:
    if not keyword:
        return True
    low = keyword.lower()
    haystack = " ".join(str(row.get(k) or "") for k in ["filename", "summary", "subject_name", "advisor_id", "subject_code", "cloned_agent_name"])
    haystack += " " + str(row.get("conclusion_table") or "") + " " + str(row.get("structured_data") or "")
    return low in haystack.lower()


def excel_tool(arguments: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Excel AI clone tool.

    - Default legacy behavior still reads app/data/student_scores.xlsx.
    - operation=list_uploaded_excel/search_uploaded_excel reads Excel files uploaded through the new knowledge uploader,
      filtered by role/subject access rules.
    """
    operation = arguments.get("operation") or "legacy_student_scores"
    keyword = (arguments.get("keyword") or "").strip()
    user_role = (arguments.get("_user_role") or (context or {}).get("user_role") or "").lower()
    requester_student_id = arguments.get("_requester_student_id") or (context or {}).get("requester_student_id")
    requester_advisor_id = arguments.get("_requester_advisor_id") or (context or {}).get("requester_advisor_id")

    if operation in {"list_uploaded_excel", "search_uploaded_excel", "document_search", "list_documents"}:
        conn = _pg_connection()
        try:
            with conn.cursor() as cur:
                rows, error = _fetch_excel_uploads_for_role(cur, user_role, requester_student_id, requester_advisor_id)
                if error:
                    return {"success": False, "error": error}
                if keyword:
                    rows = [r for r in rows if _keyword_match(r, keyword)] or rows[:8]
                return {
                    "success": True,
                    "type": "uploaded_excel_knowledge",
                    "operation": operation,
                    "keyword": keyword,
                    "data": [_iso_row(row) for row in rows[:30]],
                }
        finally:
            conn.close()

    df = pd.read_excel(DATA_PATH)
    return {
        "success": True,
        "source": "student_scores.xlsx",
        "rows": df.to_dict(orient="records"),
    }
