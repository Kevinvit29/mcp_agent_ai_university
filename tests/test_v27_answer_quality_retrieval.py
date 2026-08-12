import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.answer_failures import safe_failure_message
from app.agent.answer_source import build_answer_source
from app.agent.document_qa import answer_from_selected_document, extract_focus_terms
from app.agent.final_answer_writer import write_final_answer


SAMPLE_DOC = {
    "id": 17,
    "filename": "thai-law.pdf",
    "source_type": "pdf",
    "full_text": "การละเมิดคือการกระทำโดยจงใจหรือประมาทเลินเล่อที่ทำให้ผู้อื่นเสียหาย.",
    "conclusion_table": {"short_summary": "บทนำเรื่องกฎหมายละเมิด"},
}


def _pinned_result():
    return {"success": True, "data": {"operation": "document_by_id", "data": [SAMPLE_DOC]}}


def _selected_file_plan():
    # This is the exact tool contract sent by the Knowledge Workspace for a
    # selected file. It keeps the test independent from Docker-only DB imports.
    return {
        "tool_name": "postgres_university_tool",
        "arguments": {
            "query_type": "advisor_documents",
            "operation": "document_by_id",
            "document_id": 17,
            "document_scope": "advisor",
            "pinned_document": True,
            "answer_style": "document_explanation",
        },
    }


def test_source_label_identifies_selected_file_without_internal_storage_details():
    plan = _selected_file_plan()
    source = build_answer_source(plan, _pinned_result(), "th")
    assert source["kind"] == "selected_document"
    assert "thai-law.pdf" in source["detail"]
    assert "postgres" not in (source["label"] + source["detail"]).lower()


def test_thai_typo_question_retrieves_selected_document_text():
    answer = answer_from_selected_document(SAMPLE_DOC, "ละเมิ้ดคืออะไร", "th") or ""
    assert "ละเมิด" in answer
    assert "thai-law.pdf" in answer
    assert "ละเมิด" in extract_focus_terms("ละเมิ้ดคืออะไร")


def test_follow_up_keeps_exact_pinned_file_contract_and_source():
    plan = _selected_file_plan()
    answer = write_final_answer("ละเมิ้ดคืออะไร", "th", "student", plan, _pinned_result(), chat_history=[])
    source = build_answer_source(plan, _pinned_result(), "th")
    assert "thai-law.pdf" in answer
    assert source["kind"] == "selected_document"


def test_safe_failure_hides_raw_connection_error_but_gives_recovery_action():
    failure = safe_failure_message(
        {"tool_name": "mongodb_student_tool", "arguments": {}},
        {"success": False, "error": "Connection refused to mongo:27017 with internal token abc"},
        "en",
        "show grades",
    )
    assert "mongo:27017" not in failure
    assert "token abc" not in failure
    assert "System health" in failure


def test_role_failure_is_human_readable_and_not_technical():
    failure = safe_failure_message(
        {"tool_name": "postgres_university_tool", "arguments": {"query_type": "documents"}},
        {"success": False, "error": "Permission denied: advisor document ACL"},
        "th",
        "ขอไฟล์ทั้งหมด",
    )
    assert "สิทธิ์" in failure
    assert "ACL" not in failure
