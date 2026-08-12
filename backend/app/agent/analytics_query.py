"""Structured, capability-aware parsing for university database analytics.

This module converts many natural paraphrases into a small allowlisted query IR.
It deliberately separates:
- questions the current databases can calculate;
- questions that need several stored measures;
- questions that require data the project does not have.

The IR never contains SQL. Tool implementations map its dimensions and measures
to fixed, role-scoped queries.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.agent.natural_query import normalize_typos


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twenty": 20,
}


def _low(message: str) -> str:
    return normalize_typos(message or "").lower().strip()


def _top_n(text: str, default: int) -> int:
    match = re.search(r"\b(?:top|bottom|best|worst|first|last|leaderboard(?:\s+of)?)\s+(\d{1,3})\b", text)
    if not match:
        match = re.search(r"\b(\d{1,3})\s+(?:students?|learners?|pupils?|subjects?|courses?|classes?|performers?)\b", text)
    if match:
        return max(1, min(int(match.group(1)), 100))
    for word, number in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return number
    return default


def _student_ids(message: str) -> list[str]:
    result: list[str] = []
    for value in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I):
        value = value.upper()
        if value not in result:
            result.append(value)
    return result


def parse_capability_limitation(message: str) -> Optional[Dict[str, Any]]:
    """Return an honest limitation when the database lacks the required facts."""
    text = _low(message)
    if not text:
        return None

    if "gpa" in text and any(term in text for term in ("trend", "over terms", "over semesters", "term by term", "semester by semester")):
        return {
            "type": "capability_limitation",
            "reason": "unsupported_historical_gpa",
            "answer_style": "capability_limitation",
            "missing_data": ["term-level GPA snapshots"],
            "available_alternative": "term-level course scores and attendance plus the current GPA",
        }

    if any(term in text for term in ("predict", "forecast", "will fail", "future failure", "future gpa", "next semester risk")):
        return {
            "type": "capability_limitation",
            "reason": "unsupported_prediction",
            "answer_style": "capability_limitation",
            "missing_data": ["future outcome labels", "validated prediction model"],
            "available_alternative": "current academic risk, GPA, attendance, and assessment records",
        }

    if (
        any(term in text for term in ("prerequisite", "prerequisites", "take next", "course next", "next course"))
        and any(term in text for term in ("recommend", "should", "what", "which", "course", "subject"))
    ):
        return {
            "type": "capability_limitation",
            "reason": "unsupported_prerequisites",
            "answer_style": "capability_limitation",
            "missing_data": ["course prerequisite rules", "degree requirement sequence"],
            "available_alternative": "course catalog and the student's stored grades",
        }

    causal_signal = any(term in text for term in ("why did", "why is", "cause of", "what caused", "reason for", "find the cause"))
    causal_metric = any(term in text for term in ("gpa", "grade", "attendance", "risk", "fail", "declined", "fell", "low"))
    if causal_signal and causal_metric:
        return {
            "type": "capability_limitation",
            "reason": "unsupported_causal_explanation",
            "answer_style": "capability_limitation",
            "missing_data": ["verified causal events or intervention history"],
            "available_alternative": "the stored measurements and current risk indicators",
        }

    if any(term in text for term in ("month by month", "monthly", "each month")):
        return {
            "type": "capability_limitation",
            "reason": "unsupported_monthly_history",
            "answer_style": "capability_limitation",
            "missing_data": ["monthly academic snapshots"],
            "available_alternative": "term-level records",
        }
    return None


def parse_database_analytics_query(message: str) -> Optional[Dict[str, Any]]:
    """Build a safe analytics contract from group/rank/compare paraphrases."""
    text = _low(message)
    if not text:
        return None

    limitation = parse_capability_limitation(message)
    if limitation:
        return limitation

    student_ids = _student_ids(message)
    student_population_words = ("student", "students", "learner", "learners", "pupil", "pupils")
    # Word boundaries matter: the substring "top" in an internal label such as
    # "Previous requested topic" must never turn a follow-up into a leaderboard.
    ranking_signal = bool(re.search(
        r"\b(?:leaderboard|rank|ranking|top|best|highest|strongest|bottom|worst|lowest)\b",
        text,
    ))
    requested_academic_sections = []
    if any(term in text for term in ("attendance", "absence", "absent", "เข้าเรียน", "ขาดเรียน")):
        requested_academic_sections.append("attendance")
    if any(term in text for term in ("tuition", "balance", "amount due", "ค่าเทอม", "ยอดค้าง")):
        requested_academic_sections.append("financial_accounts")
    if any(term in text for term in ("scholarship", "ทุน")):
        requested_academic_sections.append("scholarship_awards")
    if any(term in text for term in ("assessment", "midterm", "final score", "quiz", "คะแนนสอบ")):
        requested_academic_sections.append("assessments")
    if any(term in text for term in ("enrollment", "enrolled courses", "registered courses", "ลงทะเบียน")):
        requested_academic_sections.append("enrollments")
    if (
        ranking_signal
        and any(term in text for term in student_population_words)
        and requested_academic_sections
        and not student_ids
    ):
        direction = "asc" if any(term in text for term in ("bottom", "worst", "lowest", "weakest")) else "desc"
        return {
            "type": "rank_with_academic",
            "operation": "rank_students",
            "field": "gpa",
            "direction": direction,
            "top_n": _top_n(text, 10),
            "requested_academic_sections": requested_academic_sections,
            "answer_style": "student_rank_with_academic",
            "reason": "Rank students first, then retrieve every requested academic section for those exact ranked IDs.",
        }

    if any(term in text for term in ("improved most", "most improved", "grades improved", "grades declined", "scores declined", "performance declined")):
        direction = "asc" if any(term in text for term in ("declined", "decreased", "fell")) else "desc"
        return {
            "type": "database_analytics",
            "source": "postgres",
            "query_type": "academic_analytics",
            "operation": "trend_rank",
            "dimension": "student",
            "measure": "score_change",
            "direction": direction,
            "top_n": _top_n(text, 20),
            "student_ids": student_ids,
            "answer_style": "group_analytics",
            "reason": "Compare each visible student's average course score between the earliest and latest stored terms.",
        }

    if "enrollment" in text and any(term in text for term in ("change", "changes", "trend", "latest")):
        return {
            "type": "database_analytics",
            "source": "postgres",
            "query_type": "academic_analytics",
            "operation": "group_aggregate",
            "dimension": "term",
            "measure": "student_count",
            "direction": "asc",
            "top_n": 20,
            "student_ids": student_ids,
            "answer_style": "group_analytics",
            "reason": "Show stored enrollment counts by term; the system has term snapshots rather than change-event logs.",
        }

    if (
        any(term in text for term in ("at risk", "risk students", "students at risk", "เสี่ยง"))
        and any(term in text for term in student_population_words)
    ):
        return {
            "type": "database_analytics",
            "source": "postgres",
            "query_type": "academic_analytics",
            "operation": "filtered_list",
            "dimension": "student",
            "measure": "risk_level",
            "direction": "desc",
            "top_n": _top_n(text, 50),
            "student_ids": student_ids,
            "include_balance": any(term in text for term in ("balance", "tuition", "amount due", "ยอดค้าง", "ค่าเทอม")),
            "answer_style": "risk_students",
            "reason": "List current at-risk students inside the signed role scope and attach only authorized requested fields.",
        }

    # Personal value versus university benchmark is a two-scope calculation.
    if (
        "gpa" in text
        and any(term in text for term in ("compare", "versus", " vs ", "against"))
        and any(term in text for term in ("university average", "overall average", "all students", "student average"))
    ):
        return {
            "type": "student_benchmark",
            "operation": "compare_student_to_population",
            "measure": "gpa",
            "student_ids": student_ids,
            "answer_style": "student_benchmark",
            "reason": "Compare one authorized student GPA with the visible university population average.",
        }

    subject_words = ("subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา")
    performance_words = (
        "grade", "grades", "score", "scores", "result", "results", "performance",
        "pass rate", "summary grade", "overall grade", "เกรด", "คะแนน", "ผลการเรียน",
    )
    rank_words = (
        "highest", "greatest", "best", "top", "maximum", "max",
        "lowest", "worst", "bottom", "minimum", "min", "strongest", "weakest",
        "rank", "ranking", "compare", "เทียบ", "สูงสุด", "ต่ำสุด",
    )
    has_subject = any(term in text for term in subject_words)
    has_performance = any(term in text for term in performance_words)
    has_rank = any(term in text for term in rank_words)

    # Course/subject performance must take precedence over student ranking.
    if has_subject and has_performance and (has_rank or "average" in text or "rate" in text):
        measure = "pass_rate" if "pass rate" in text else "average_score"
        direction = "asc" if any(term in text for term in ("lowest", "worst", "bottom", "minimum", "min", "ต่ำสุด")) else "desc"
        return {
            "type": "database_analytics",
            "source": "postgres",
            "query_type": "academic_analytics",
            "operation": "group_rank" if has_rank else "group_aggregate",
            "dimension": "course",
            "measure": measure,
            "direction": direction,
            "top_n": _top_n(text, 1 if has_rank and "compare" not in text else 20),
            "student_ids": student_ids,
            "answer_style": "group_analytics",
            "reason": "Calculate course performance from numeric enrollment scores instead of confusing courses with students.",
        }

    dimension: Optional[str] = None
    if re.search(r"\b(?:by|per|each|every|across)\s+(?:program|programs|major|majors)\b", text) or "แต่ละสาขา" in text:
        dimension = "program"
    elif re.search(r"\b(?:by|per|each|every|across)\s+(?:year|year level|cohort)\b", text) or "แต่ละชั้นปี" in text:
        dimension = "year_level"
    elif re.search(r"\b(?:by|per|each|every|across)\s+(?:term|semester)\b", text) or "แต่ละเทอม" in text:
        dimension = "term"
    elif re.search(r"\b(?:by|per|each|every|across)\s+(?:course|courses|subject|subjects|class|classes)\b", text):
        dimension = "course"

    measure: Optional[str] = None
    if "pass rate" in text:
        measure = "pass_rate"
    elif any(term in text for term in ("attendance", "absence", "absent", "เข้าเรียน", "ขาดเรียน")):
        measure = "attendance_rate"
    elif any(term in text for term in ("balance", "tuition", "amount due", "ยอดค้าง", "ค่าเทอม")):
        measure = "balance_due"
    elif "gpa" in text or "เกรดเฉลี่ย" in text:
        measure = "average_gpa"
    elif any(term in text for term in ("score", "scores", "grade", "grades", "performance", "result", "results", "คะแนน", "เกรด")):
        measure = "average_score"
    elif any(term in text for term in ("count", "number", "how many", "headcount", "จำนวน", "กี่")):
        measure = "student_count"

    if dimension and measure:
        source = "mongo" if dimension == "program" and measure in {"average_gpa", "student_count"} else "postgres"
        direction = "asc" if any(term in text for term in ("lowest", "worst", "bottom", "minimum", "ต่ำสุด")) else "desc"
        return {
            "type": "database_analytics",
            "source": source,
            "query_type": "academic_analytics" if source == "postgres" else None,
            "operation": "group_rank" if has_rank else "group_aggregate",
            "dimension": dimension,
            "measure": measure,
            "direction": direction,
            "top_n": _top_n(text, 20),
            "student_ids": student_ids,
            "answer_style": "group_analytics",
            "reason": f"Calculate {measure} grouped by {dimension} using an allowlisted role-scoped aggregate.",
        }

    if (
        measure == "average_score"
        and has_rank
        # A possessive teaching-scope phrase asks for marks recorded in
        # PostgreSQL. Generic "top students/best grade" remains the existing,
        # authoritative MongoDB GPA leaderboard.
        and any(term in text for term in ("my students", "students i teach", "my learners", "learners i teach"))
        and "gpa" not in text
    ):
        direction = "asc" if any(term in text for term in ("lowest", "worst", "bottom", "weakest")) else "desc"
        return {
            "type": "database_analytics",
            "source": "postgres",
            "query_type": "academic_analytics",
            "operation": "group_rank",
            "dimension": "student",
            "measure": "average_score",
            "direction": direction,
            "top_n": _top_n(text, 1),
            "student_ids": student_ids,
            "answer_style": "group_analytics",
            "reason": "Rank students by numeric course scores inside the signed role's teaching scope.",
        }

    # Overall attendance/score aggregate, especially useful for advisor scope.
    if measure in {"attendance_rate", "average_score", "pass_rate"} and any(
        term in text for term in ("average", "mean", "overall", "students i teach", "my students")
    ):
        return {
            "type": "database_analytics",
            "source": "postgres",
            "query_type": "academic_analytics",
            "operation": "aggregate",
            "dimension": "overall",
            "measure": measure,
            "direction": "desc",
            "top_n": 1,
            "student_ids": student_ids,
            "answer_style": "group_analytics",
            "reason": f"Calculate the overall {measure} inside the signed role's data scope.",
        }

    # Broad population count paraphrases that do not literally say "students".
    population_count = (
        "student headcount", "student body", "number enrolled", "total learners",
        "count everybody studying", "how large is the student body", "จำนวนผู้เรียน",
    )
    if any(term in text for term in population_count):
        return {
            "type": "student_count",
            "operation": "count",
            "scope": "university",
            "answer_style": "count",
            "reason": "Natural-language paraphrase asks for the visible student population count.",
        }

    performer_words = ("student", "students", "learner", "learners", "pupil", "pupils", "academic performer", "academic performers")
    if any(term in text for term in performer_words) and ranking_signal and not has_subject:
        direction = "asc" if any(term in text for term in ("bottom", "worst", "lowest", "weakest")) else "desc"
        return {
            "type": "student_ranking",
            "operation": "rank_students",
            "scope": "university",
            "field": "gpa",
            "direction": direction,
            "top_n": _top_n(text, 10),
            "answer_style": "student_rank",
            "reason": "Natural-language leaderboard request maps to an exact GPA ranking.",
        }
    return None
