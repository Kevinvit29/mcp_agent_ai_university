import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.controlled_learning import (
    VALID_FEEDBACK_RATINGS,
    build_controlled_learning_gate,
    clean_feedback_rating,
    clean_review_action,
    safe_feedback_text,
)


def test_v26_feedback_accepts_only_safe_ratings():
    assert VALID_FEEDBACK_RATINGS == {"helpful", "needs_review"}
    assert clean_feedback_rating("Helpful") == "helpful"
    assert clean_feedback_rating("needs review") == "needs_review"
    assert clean_feedback_rating("auto-train") is None


def test_v26_review_actions_are_explicit():
    assert clean_review_action("publish", {"publish", "pause", "dismiss"}) == "publish"
    assert clean_review_action("approve everything", {"publish", "pause", "dismiss"}) is None


def test_v26_feedback_is_trimmed_and_control_gate_passes():
    assert safe_feedback_text("  a\x00  b   c ", 50) == "a b c"
    report = build_controlled_learning_gate()
    assert report["success"] is True
    assert report["summary"] == {"passed": 4, "failed": 0, "total": 4, "percentage": 100.0}


def test_v26_new_corrections_are_candidates_until_reviewed():
    db_source = (ROOT / "backend" / "app" / "db" / "postgres.py").read_text()
    assert "0, FALSE, 'candidate'" in db_source
    assert "review_status = 'published'" in db_source
    assert "CREATE TABLE IF NOT EXISTS ai_answer_feedback" in db_source
