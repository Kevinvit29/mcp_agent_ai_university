"""Safe, non-technical chat messages when an approved source cannot answer."""
from __future__ import annotations

from typing import Any, Dict


def _is_thai(language: str, message: str = "") -> bool:
    return (language or "").lower().startswith("th") or any("\u0e00" <= char <= "\u0e7f" for char in message or "")


def _source_name(plan: Dict[str, Any], thai: bool) -> str:
    tool = str((plan or {}).get("tool_name") or "")
    args = (plan or {}).get("arguments") or {}
    if tool == "postgres_university_tool" and (args.get("pinned_document") or args.get("query_type") in {"documents", "all_documents", "advisor_documents", "lecturer_documents", "course_documents"}):
        return "ไฟล์ที่เลือก" if thai else "the selected file"
    if tool == "mongodb_student_tool":
        return "ข้อมูลนักศึกษา" if thai else "student records"
    if tool == "mongodb_advisor_tool":
        return "ข้อมูลอาจารย์ที่ปรึกษา" if thai else "advisor records"
    return "แหล่งข้อมูลที่อนุญาต" if thai else "the approved data source"


def safe_failure_message(
    plan: Dict[str, Any],
    tool_result: Dict[str, Any],
    language: str,
    message: str = "",
    validation_failed: bool = False,
) -> str:
    """Explain a failure without exposing hostnames, stack traces, or raw SQL/MCP text."""
    thai = _is_thai(language, message)
    raw = " ".join(
        str(value or "")
        for value in [
            (tool_result or {}).get("error") if isinstance(tool_result, dict) else "",
            (tool_result or {}).get("detail") if isinstance(tool_result, dict) else "",
        ]
    ).lower()
    source = _source_name(plan, thai)

    permission_words = (
        "permission", "forbidden", "unauthorized", "access denied", "not allowed", "pdpa",
        "can only access", "only available", "current access role",
    )
    missing_words = ("not found", "no matching", "no document", "no file", "empty", "does not exist")
    connection_words = ("connection", "timeout", "unreachable", "refused", "mcp", "database", "mongo", "postgres", "network")

    if any(word in raw for word in permission_words):
        role = str((plan or {}).get("user_role") or "").lower()
        if role == "student":
            return (
                "คุณดูได้เฉพาะข้อมูลนักศึกษาของตนเองที่ผูกกับบัญชีนี้"
                if thai else "You can only access the student record linked to your own signed-in account."
            )
        if role == "advisor":
            return (
                "คุณดูได้เฉพาะนักศึกษา วิชา และข้อมูลการเรียนที่อยู่ในขอบเขตการสอนของคุณ"
                if thai else "You can only access students, subjects, and academic sections within your assigned teaching scope."
            )
        return (
            "ข้อมูลนี้ไม่พร้อมใช้งานสำหรับสิทธิ์การเข้าถึงของคุณค่ะ"
            if thai else "This information is not available for your current access role."
        )
    if any(word in raw for word in missing_words):
        if "file" in raw or "document" in raw or "ไฟล์" in raw or "เอกสาร" in raw:
            return (
                "ยังไม่พบไฟล์ที่ตรงกับคำถามในข้อมูลที่คุณมีสิทธิ์เข้าถึง ลองตรวจชื่อไฟล์หรือเลือกไฟล์จาก Knowledge Workspace อีกครั้งค่ะ"
                if thai else "I could not find a matching file among the documents you are allowed to access. Check the file name or choose it again from the Knowledge Workspace."
            )
        return (
            "ไม่พบข้อมูลที่ตรงกับคำถามในข้อมูลที่คุณมีสิทธิ์เข้าถึง ลองตรวจคำสะกดหรือระบุชื่อ/รหัสให้ชัดขึ้นค่ะ"
            if thai else "I could not find a matching record in the data you are allowed to access. Check the spelling or provide a clearer name or ID."
        )
    if validation_failed:
        return (
            f"ระบบได้รับผลลัพธ์จาก{source}ที่ไม่ตรงกับคำถาม จึงไม่ตอบแบบเดาเอง กรุณาลองถามใหม่ให้เฉพาะเจาะจงขึ้นค่ะ"
            if thai else f"The result from {source} did not match the question, so I will not guess. Please try a more specific question."
        )
    if any(word in raw for word in connection_words):
        return (
            f"ตอนนี้ระบบยังเชื่อมต่อกับ{source}ไม่ได้ชั่วคราว จึงยังตอบจากข้อมูลนี้ไม่ได้ ลองใหม่อีกครั้ง และตรวจ System health หากเกิดซ้ำค่ะ"
            if thai else f"I cannot reach {source} right now, so I cannot answer from it. Please try again and check System health if this keeps happening."
        )
    return (
        f"ตอนนี้ยังตอบคำถามนี้จาก{source}ไม่ได้ ระบบจะไม่เดาข้อมูลแทน กรุณาลองใหม่หรือถามให้เฉพาะเจาะจงขึ้นค่ะ"
        if thai else f"I cannot answer this from {source} right now. I will not guess instead of using a source; please try again or make the question more specific."
    )
