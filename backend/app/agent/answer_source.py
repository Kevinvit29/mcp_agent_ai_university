"""Small, user-facing provenance labels for university AI answers.

The UI needs to tell users whether an answer came from an allowed university
record, an exact uploaded file, or general guidance.  These labels deliberately
avoid raw database names, internal retrieval scores, and private field details.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _is_thai(language: str) -> bool:
    return (language or "").lower().startswith("th")


def _unwrap_data(tool_result: Dict[str, Any]) -> Any:
    if not isinstance(tool_result, dict):
        return None
    data = tool_result.get("data")
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return data.get("data")
    return data


def _documents(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [row for row in data.get("data") or [] if isinstance(row, dict)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _label(kind: str, language: str, filename: str = "") -> Dict[str, Any]:
    thai = _is_thai(language)
    labels = {
        "selected_document": (
            "แหล่งข้อมูล: ไฟล์ที่เลือก",
            "อ้างอิงจากข้อความที่ดึงเก็บไว้จากไฟล์นี้",
        ),
        "documents": (
            "แหล่งข้อมูล: เอกสารที่อัปโหลด",
            "อ้างอิงจากข้อมูลเอกสารที่คุณมีสิทธิ์เข้าถึง",
        ),
        "student_records": (
            "แหล่งข้อมูล: ระเบียนนักศึกษา",
            "อ้างอิงจากข้อมูลที่อนุญาตตามสิทธิ์ของคุณ",
        ),
        "advisor_records": (
            "แหล่งข้อมูล: ระเบียนอาจารย์ที่ปรึกษา",
            "อ้างอิงจากข้อมูลที่อนุญาตตามสิทธิ์ของคุณ",
        ),
        "university_records": (
            "แหล่งข้อมูล: ระเบียนมหาวิทยาลัย",
            "อ้างอิงจากข้อมูลมหาวิทยาลัยที่อนุญาต",
        ),
        "multiple_records": (
            "แหล่งข้อมูล: ระเบียนมหาวิทยาลัยหลายส่วน",
            "สรุปจากแหล่งข้อมูลที่อนุญาตหลายรายการ",
        ),
        "general_guidance": (
            "โหมดคำตอบ: คำแนะนำทั่วไป",
            "ไม่ได้อ้างอิงจากฐานข้อมูลมหาวิทยาลัยหรือไฟล์ที่อัปโหลด",
        ),
        "unavailable": (
            "สถานะแหล่งข้อมูล: ใช้งานไม่ได้ชั่วคราว",
            "ระบบไม่ได้เดาข้อมูลแทนแหล่งข้อมูล",
        ),
        "access_restricted": (
            "ขอบเขตข้อมูล: จำกัดตามสิทธิ์",
            "ระบบป้องกันข้อมูลที่อยู่นอกสิทธิ์ของบัญชีนี้",
        ),
    }
    english = {
        "selected_document": ("Source: selected file", "Grounded in stored extracted text from this file"),
        "documents": ("Source: uploaded documents", "Grounded in documents you are allowed to access"),
        "student_records": ("Source: student records", "Grounded in records allowed for your role"),
        "advisor_records": ("Source: advisor records", "Grounded in records allowed for your role"),
        "university_records": ("Source: university records", "Grounded in approved university records"),
        "multiple_records": ("Source: multiple university records", "Combined from approved university sources"),
        "general_guidance": ("Mode: general guidance", "Not based on university records or uploaded files"),
        "unavailable": ("Source status: temporarily unavailable", "The assistant did not guess instead of using a source"),
        "access_restricted": ("Access scope: restricted", "The requested data is outside this signed-in role"),
    }
    title, detail = (labels if thai else english).get(kind, english["general_guidance"])
    if filename:
        detail = f"{detail} · {filename}"
    return {
        "kind": kind,
        "label": title,
        "detail": detail,
        "visible": True,
        "grounded": kind not in {"general_guidance", "unavailable", "access_restricted"},
    }


def build_answer_source(plan: Dict[str, Any], tool_result: Dict[str, Any], language: str) -> Dict[str, Any]:
    """Return a compact source label safe to store with the chat message."""
    plan = plan or {}
    result = tool_result or {}
    args = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
    access_reasons = {
        "student_ranking_not_available_for_role",
        "student_other_record_denied",
        "student_signed_identity_required",
        "student_own_scope_only",
        "academic_sections_not_available_for_role",
        "advisor_classroom_scope_only",
    }
    if args.get("reason") in access_reasons or args.get("answer_style") == "access_scope":
        return _label("access_restricted", language)
    if isinstance(result, dict) and result.get("success") is False:
        raw = f"{result.get('error') or ''} {result.get('detail') or ''}".lower()
        if any(word in raw for word in ("permission", "forbidden", "access", "only", "role", "pdpa")):
            return _label("access_restricted", language)
        return _label("unavailable", language)

    tool = str(plan.get("tool_name") or "none")
    data = _unwrap_data(result)
    if isinstance(data, dict) and data.get("type") in {
        "student_combined_record", "student_combined_records", "student_rank_with_academic",
    }:
        return _label("multiple_records", language)

    if tool == "postgres_university_tool":
        query_type = str(args.get("query_type") or "")
        operation = str(args.get("operation") or (data.get("operation") if isinstance(data, dict) else ""))
        docs = _documents(data)
        if query_type in {"documents", "all_documents", "advisor_documents"} or operation.startswith("document") or operation == "list_documents":
            filename = ""
            if docs:
                filename = str(docs[0].get("filename") or "")
            if args.get("pinned_document") or operation == "document_by_id":
                return _label("selected_document", language, filename)
            return _label("documents", language, filename if len(docs) == 1 else "")
        return _label("university_records", language)

    if tool == "mongodb_student_tool":
        return _label("student_records", language)
    if tool == "mongodb_advisor_tool":
        return _label("advisor_records", language)
    if tool == "admin_multi_tool_context":
        return _label("multiple_records", language)
    if tool in {"error", "trace_unavailable"}:
        return _label("unavailable", language)
    return _label("general_guidance", language)
