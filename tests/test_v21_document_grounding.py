import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.document_qa import answer_from_selected_document, extract_focus_terms, run_document_grounding_checks


def _sample_document():
    return {
        "id": 44,
        "filename": "law-foundations.pdf",
        "full_text": (
            "Law is a body of rules recognized and applied by the state. "
            "Private law includes torts, contracts, and trusts. "
            "Torts concern civil wrongs and remedies between private parties."
        ),
        "conclusion_table": {
            "short_summary": "A short introduction to law and its private-law categories.",
            "key_points": ["Private law includes torts, contracts, and trusts."],
        },
    }


def test_document_question_uses_exact_stored_text():
    answer = answer_from_selected_document(_sample_document(), "What is torts?", "en")
    assert answer
    assert "law-foundations.pdf" in answer
    assert "torts" in answer.lower()


def test_focus_terms_ignore_question_fillers():
    terms = extract_focus_terms("What is student median grade in law program?")
    assert "what" not in terms
    assert "is" not in terms
    assert "law" in terms


def test_document_grounding_release_checks_pass():
    report = run_document_grounding_checks()
    assert report["success"] is True
    assert report["summary"]["passed"] == report["summary"]["total"]
