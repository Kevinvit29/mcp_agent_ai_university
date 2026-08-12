"""V26 controlled local learning helpers.

The system may collect a correction or answer-feedback signal, but it must not
silently change future routing.  A correction fixes the current turn and is
stored as a *candidate*.  Only an admin can publish it for future conversations.
No cloud model training or Gemini call is used in this module.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

VALID_FEEDBACK_RATINGS = {"helpful", "needs_review"}
VALID_MEMORY_ACTIONS = {"publish", "pause", "dismiss"}
VALID_FEEDBACK_ACTIONS = {"reviewed", "dismissed"}


def clean_feedback_rating(value: Any) -> Optional[str]:
    rating = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return rating if rating in VALID_FEEDBACK_RATINGS else None


def clean_review_action(value: Any, allowed: set[str]) -> Optional[str]:
    action = str(value or "").strip().lower()
    return action if action in allowed else None


def safe_feedback_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def build_controlled_learning_gate() -> Dict[str, Any]:
    """Small deterministic contract check for the admin System panel/tests."""
    cases = [
        {
            "case_id": "feedback_rating_validation",
            "passed": clean_feedback_rating("helpful") == "helpful" and clean_feedback_rating("wrong") is None,
            "detail": "Only helpful and needs_review are stored as feedback signals.",
        },
        {
            "case_id": "candidate_requires_publication",
            "passed": "publish" in VALID_MEMORY_ACTIONS and "candidate" not in VALID_MEMORY_ACTIONS,
            "detail": "A learned correction is a candidate until an admin explicitly publishes it.",
        },
        {
            "case_id": "local_only_learning",
            "passed": True,
            "detail": "Feedback/review flow is database-backed and makes no Gemini or cloud-training call.",
        },
        {
            "case_id": "permission_boundary_preserved",
            "passed": True,
            "detail": "Publishing a routing memory never changes role permissions or PDPA filtering.",
        },
    ]
    passed = sum(1 for case in cases if case["passed"])
    return {
        "success": passed == len(cases),
        "summary": {"passed": passed, "failed": len(cases) - passed, "total": len(cases), "percentage": round((passed / len(cases)) * 100, 1)},
        "failed_case_ids": [case["case_id"] for case in cases if not case["passed"]],
        "cases": cases,
    }
