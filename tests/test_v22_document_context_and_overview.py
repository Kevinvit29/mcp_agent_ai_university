from app.agent.document_qa import answer_from_selected_document, extract_focus_terms, is_general_document_overview_question
from app.agent.final_answer_writer import _format_documents


SAMPLE_DOC = {
    "id": 1,
    "filename": "law-notes.pdf",
    "source_type": "pdf",
    "storage_target": "mongodb",
    "match_score": 9999,
    "summary": "An introduction to law, including private law and torts.",
    "full_text": (
        "Law is a body of rules recognized and applied by the state. "
        "Private law includes torts, contracts, and trusts. "
        "Torts concern civil wrongs and remedies between private parties."
    ),
    "conclusion_table": {
        "short_summary": "An introduction to law, including private law and torts.",
        "main_topic": "Introduction to law",
        "key_points": ["Law is enforced by the state.", "Private law includes torts, contracts, and trusts."],
    },
}


def test_generic_prompt_is_overview_not_random_excerpt():
    assert is_general_document_overview_question("Can you explain this file that I uploaded?")
    assert answer_from_selected_document(SAMPLE_DOC, "Can you explain this file that I uploaded?", "en") is None
    answer = _format_documents({"operation": "document_by_id", "data": [SAMPLE_DOC]}, False, "Can you explain this file that I uploaded?")
    assert answer is not None
    assert "About the PDF file" in answer
    assert "An introduction to law" in answer


def test_targeted_question_still_uses_source_text():
    answer = answer_from_selected_document(SAMPLE_DOC, "What is torts?", "en") or ""
    assert "Torts concern civil wrongs" in answer
    assert "law-notes.pdf" in answer


def test_upload_is_not_a_focus_term():
    assert extract_focus_terms("Can you explain this file that I upload?") == []


def test_actual_document_beats_neural_pseudo_document():
    pseudo = {
        "id": 1,
        "filename": "law-notes.pdf",
        "summary": "Neural data agent match from PDF_AGENT (score 0.0962).",
        "text_excerpt": "Torts concern civil wrongs and remedies.",
        "match_score": 100.0962,
        "matched_terms": ["neural_data_agent"],
        "structured_preview": {"neural_agent_name": "PDF_AGENT"},
    }
    answer = _format_documents({"operation": "document_search", "data": [pseudo, SAMPLE_DOC]}, False, "explain") or ""
    assert "Neural data agent match" not in answer
    assert "score 0.0962" not in answer
    assert "An introduction to law" in answer
