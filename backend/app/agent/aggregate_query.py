"""Aggregate/filter query helpers for Agent Orchestrator V5.

This module handles questions where the user's purpose is not a single record,
but a computed set/count such as:
- how many students have GPA lower 3.0
- student that have gpa lower than 3.0
- which students are below 2.5

The important change is context-first aggregation: when the latest user message
asks for a numeric comparison, the data contract must include the comparison
filter before any tool is called.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, List

from app.agent.natural_query import normalize_typos

COUNT_TERMS = ("how many", "count", "number of", "total", "กี่", "จำนวน", "ทั้งหมดกี่")
LIST_TERMS = (
    "list", "show", "which", "who", "student that", "students that", "student who", "students who",
    "have", "has", "รายชื่อ", "แสดง", "ใครบ้าง", "คนไหน", "นักศึกษาที่", "นักเรียนที่",
)
STUDENT_TERMS = ("student", "students", "learner", "learners", "นักศึกษา", "นักเรียน")
GPA_TERMS = ("gpa", "เกรดเฉลี่ย")
GRADE_TERMS = ("grade", "grades", "score", "scores", "เกรด", "คะแนน")

# Ordered from more specific to less specific so "lower than or equal" wins before "lower than".
COMPARISON_PATTERNS = [
    ("$lte", r"(?:lower\s+than\s+or\s+equal\s+to|less\s+than\s+or\s+equal\s+to|no\s+more\s+than|at\s+most|<=|≤)\s*(\d+(?:\.\d+)?)"),
    ("$gte", r"(?:higher\s+than\s+or\s+equal\s+to|greater\s+than\s+or\s+equal\s+to|at\s+least|no\s+less\s+than|>=|≥)\s*(\d+(?:\.\d+)?)"),
    # Accept natural but imperfect English like "gpa lower 3.0" or "grade lower 3.0".
    ("$lt", r"(?:lower(?:\s+than)?|less(?:\s+than)?|below|under|<)\s*(\d+(?:\.\d+)?)"),
    ("$gt", r"(?:higher(?:\s+than)?|greater(?:\s+than)?|above|over|>)\s*(\d+(?:\.\d+)?)"),
]

OPERATOR_TEXT = {
    "$lt": "lower than",
    "$lte": "lower than or equal to",
    "$gt": "higher than",
    "$gte": "higher than or equal to",
}


def _low(message: str) -> str:
    return normalize_typos(message or "").lower().strip()


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def parse_student_metric_query(message: str) -> Optional[Dict[str, Any]]:
    """Return a safe aggregate/filter query contract, or None.

    Currently supports GPA-style numeric comparisons. When users say "grade lower
    than 3.0", we infer GPA because subject grades in this demo are letter grades
    (A, B+, C) while 3.0 is numeric on the GPA scale.
    """
    text = _low(message)
    if not text:
        return None

    has_student = _has_any(text, STUDENT_TERMS)
    has_gpa = _has_any(text, GPA_TERMS)
    has_grade_numeric_context = _has_any(text, GRADE_TERMS) and bool(re.search(r"\b\d(?:\.\d+)?\b", text))

    # Do not turn normal grade questions like "S001 grade" into aggregate filters.
    if not (has_student or has_gpa or has_grade_numeric_context):
        return None
    if re.search(r"\bS\d{3,6}\b", message or "", flags=re.I):
        return None

    matched_op = None
    matched_value = None
    matched_phrase = None
    for op, pattern in COMPARISON_PATTERNS:
        match = re.search(pattern, text)
        if match:
            try:
                matched_value = float(match.group(1))
            except Exception:
                continue
            matched_op = op
            matched_phrase = match.group(0)
            break

    if matched_op is None or matched_value is None:
        return None

    # Numeric threshold in a student/grade context = GPA in this schema.
    field = "gpa"
    wants_count = _has_any(text, COUNT_TERMS)
    wants_list = _has_any(text, LIST_TERMS) or any(x in text for x in ["student that", "students that", "student have", "students have", "student with", "students with"])
    intent = "count" if wants_count else ("list" if wants_list else "filter")

    return {
        "type": "student_metric_filter",
        "field": field,
        "operator": matched_op,
        "operator_text": OPERATOR_TEXT.get(matched_op, matched_op),
        "value": matched_value,
        "intent": intent,
        "query_filter": {field: {matched_op: matched_value}},
        "sort": [{"field": field, "direction": "asc" if matched_op in {"$lt", "$lte"} else "desc"}],
        "answer_style": "aggregate_count" if intent == "count" else "aggregate_filter",
        "matched_phrase": matched_phrase,
        "reason": "Latest message asks for a student GPA numeric comparison, so the database must filter/count by GPA before answering.",
    }


# ---------- Study/program/subject semantic query + ranking helpers ----------

STUDY_VERBS = (
    "study", "studies", "studying", "take", "takes", "taking", "learn", "learning",
    "enrolled in", "enroll in", "major in", "majors in", "program in", "course in", "subject in",
    "เรียน", "ลงเรียน", "สาขา", "วิชา",
)

RANK_HIGH_TERMS = (
    "highest", "highest grade", "highest gpa", "top", "best", "maximum", "max", "greatest", "strongest",
    "เกรดสูงสุด", "สูงสุด", "ดีที่สุด",
)
RANK_LOW_TERMS = (
    "lowest", "lowest grade", "lowest gpa", "bottom", "worst", "minimum", "min", "weakest",
    "เกรดต่ำสุด", "ต่ำสุด", "แย่สุด",
)

STATISTIC_TERMS = {
    "median": ("median", "middle", "ค่ามัธยฐาน", "มัธยฐาน"),
    "average": ("average", "mean", "avg", "ค่าเฉลี่ย", "เฉลี่ย"),
    "maximum": ("maximum", "max", "highest", "top", "best", "สูงสุด", "มากสุด"),
    "minimum": ("minimum", "min", "lowest", "bottom", "worst", "ต่ำสุด", "น้อยสุด"),
    "count": ("how many", "count", "number of", "total", "กี่", "จำนวน", "ทั้งหมดกี่"),
}

STATISTIC_LABELS = {
    "median": "median",
    "average": "average",
    "maximum": "maximum",
    "minimum": "minimum",
    "count": "count",
}

SUBJECT_RANKING_TERMS = (
    "recommend", "recommended", "recommendation", "popular", "popularity",
    "most common", "most enrolled", "highest enrollment",
    "แนะนำ", "ยอดนิยม", "ลงทะเบียนมาก",
)

_COMMAND_WORDS = {
    "give", "me", "the", "a", "an", "of", "in", "for", "to", "what", "is", "are", "how", "many", "calculate", "computed", "please", "list", "show", "find", "search", "student", "students",
    "that", "who", "which", "have", "has", "with", "name", "names", "grade", "grades", "gpa", "score", "scores",
    "highest", "lowest", "top", "best", "worst", "median", "average", "mean", "avg", "maximum", "minimum", "total", "number", "all", "program", "major", "subject", "course", "class", "study", "studies", "studying",
}

_STOP_AFTER_STUDY = re.compile(
    r"\b(?:grade|grades|gpa|profile|information|info|record|records|student|students|name|names|list|show|please|that|who|which|have|has|at|from|highest|lowest|top|best|worst|median|average|mean|avg|maximum|minimum)\b",
    flags=re.I,
)


def _clean_study_term(raw: str) -> str:
    term = (raw or "").strip(" .?!,:;()[]{}'\"\n\t")
    term = re.sub(r"^(?:the|a|an|about|of|in|for|program|major|subject|course|class)\s+", "", term, flags=re.I).strip()
    # Cut accidental trailing command words, but keep real multi-word program names.
    m = _STOP_AFTER_STUDY.search(term)
    if m and m.start() > 0:
        term = term[:m.start()].strip()
    term = re.sub(r"\s+(?:class|course|subject|program|major)$", "", term, flags=re.I).strip()
    # Remove common command/filler tokens from both sides repeatedly.
    words = term.split()
    while words and words[0].lower() in _COMMAND_WORDS:
        words.pop(0)
    while words and words[-1].lower() in _COMMAND_WORDS:
        words.pop()
    term = " ".join(words).strip()
    return term[:80]


def _extract_study_term(text: str) -> str:
    """Extract the real program/subject term from imperfect user phrasing.

    V10 fixes examples where older regexes returned filler words like "what is".
    The extractor now recognizes both "program law" and "law program", plus
    statistic questions such as "median grade in law program".
    """
    raw_text = text or ""
    patterns = [
        r"\bin\s+([a-zA-Z][a-zA-Z0-9&/\-\s]{1,80}?)\s+(?:program|major|subject|course|class)\b",
        r"\bof\s+([a-zA-Z][a-zA-Z0-9&/\-\s]{1,80}?)\s+(?:program|major|subject|course|class)\b",
        r"\bfor\s+([a-zA-Z][a-zA-Z0-9&/\-\s]{1,80}?)\s+(?:program|major|subject|course|class)\b",
        r"\b([a-zA-Z][a-zA-Z0-9&/\-\s]{1,80}?)\s+(?:program|major|subject|course|class)\b",
        r"\bprogram\s+(?:in\s+)?([a-zA-Z0-9&/\-\s]{2,80})",
        r"\bmajor\s+(?:in\s+)?([a-zA-Z0-9&/\-\s]{2,80})",
        r"\bsubject\s+(?:in\s+)?([a-zA-Z0-9&/\-\s]{2,80})",
        r"\bcourse\s+(?:in\s+)?([a-zA-Z0-9&/\-\s]{2,80})",
        r"(?:student|students|learner|learners)\s+(?:who|that)?\s*(?:study|studies|studying|take|takes|taking|learn|learning|are enrolled in|enrolled in|major in|majors in)\s+([a-zA-Z0-9&/\-\s]{2,80})",
        r"(?:name|names)\s+of\s+(?:the\s+)?(?:student|students)\s+(?:who|that)?\s*(?:study|studies|studying|take|takes|taking|learn|learning|are enrolled in|enrolled in|major in|majors in)\s+([a-zA-Z0-9&/\-\s]{2,80})",
        r"(?:who|which\s+students?)\s+(?:study|studies|studying|take|takes|taking|learn|learning|are enrolled in|enrolled in|major in|majors in)\s+([a-zA-Z0-9&/\-\s]{2,80})",
        r"(?:study|studies|studying|take|takes|taking|learn|learning|are enrolled in|enrolled in|major in|majors in)\s+([a-zA-Z0-9&/\-\s]{2,80})",
    ]
    candidates: List[str] = []
    for pat in patterns:
        for m in re.finditer(pat, raw_text, flags=re.I):
            term = _clean_study_term(m.group(1))
            if not term:
                continue
            low_term = term.lower()
            if low_term in _COMMAND_WORDS:
                continue
            tokens = [t for t in low_term.split() if t]
            if tokens and all(t in _COMMAND_WORDS for t in tokens):
                continue
            command_ratio = (sum(1 for t in tokens if t in _COMMAND_WORDS) / max(1, len(tokens)))
            if len(tokens) > 1 and command_ratio >= 0.45:
                continue
            candidates.append(term)
    if candidates:
        # Prefer most meaningful candidate; terms with many non-command tokens win.
        candidates.sort(key=lambda x: (len([t for t in x.split() if t.lower() not in _COMMAND_WORDS]), len(x)), reverse=True)
        return candidates[0]
    return ""

def _ranking_from_text(text: str) -> Optional[Dict[str, Any]]:
    high = any(t in text for t in RANK_HIGH_TERMS)
    low = any(t in text for t in RANK_LOW_TERMS)
    if not (high or low):
        return None
    # In this schema, program-level "highest grade" is best represented by GPA.
    # Subject grades are letters, while GPA is numeric and sortable.
    direction = "asc" if low else "desc"
    top_n = 1
    m = re.search(r"\btop\s+(\d{1,3})\b", text)
    if m:
        top_n = max(1, min(int(m.group(1)), 100))
    elif any(w in text for w in ["list", "show", "all", "students"]):
        # For "list students with highest grade program law", show a ranked list,
        # but still keep it compact.
        top_n = 20
    return {
        "field": "gpa",
        "direction": direction,
        "top_n": top_n,
        "metric_label": "GPA",
        "reason": "The message asks for highest/lowest grade in a program/subject context; GPA is the sortable numeric grade metric in this database.",
    }


def parse_subject_ranking_query(message: str) -> Optional[Dict[str, Any]]:
    """Recognise a request to rank subjects, without inventing a study term.

    The stored demo data has enrollment/grade-record counts but no curriculum
    prerequisite or student-interest model.  Therefore a generic request such
    as "top 5 recommended subjects" is answered transparently as a popularity
    ranking by the number of students in the caller's authorised scope.
    """
    text = _low(message)
    if not text:
        return None
    has_subject = any(term in text for term in ("subject", "subjects", "course", "courses", "class", "classes", "วิชา", "รายวิชา"))
    if not has_subject:
        return None

    has_recommendation_signal = any(term in text for term in SUBJECT_RANKING_TERMS)
    has_top_signal = bool(re.search(r"\btop(?:\s+\d{1,3})?\b", text)) or any(term in text for term in ("อันดับ", "ยอดนิยม"))
    # "highest GPA/grade in law subject" is a student statistic request, not a
    # popularity ranking of subject names.
    has_grade_metric = any(term in text for term in ("gpa", "grade", "grades", "score", "scores", "เกรด", "คะแนน"))
    if not has_recommendation_signal and not (has_top_signal and not has_grade_metric):
        return None

    top_n = 5
    match = re.search(r"\btop\s+(\d{1,3})\b", text)
    if match:
        top_n = max(1, min(int(match.group(1)), 50))
    return {
        "type": "subject_ranking",
        "operation": "subject_summary",
        "intent": "rank",
        "answer_style": "subject_rank",
        "top_n": top_n,
        "ranking_basis": "student_count",
        "recommendation_basis": "enrollment_popularity",
        "reason": "Rank subjects by distinct enrolled-student count within the caller's authorised data scope; the database has no personal-interest or prerequisite recommendation model.",
    }


def parse_student_ranking_query(message: str) -> Optional[Dict[str, Any]]:
    """Recognise university-wide top/bottom student ranking requests.

    Rankings are intentionally separate from maximum/minimum statistics:
    "highest GPA" asks for one computed extreme, while "top 5 students" asks
    for five ordered records. A dedicated contract prevents numbers and command
    words such as ``5`` or ``rank`` from becoming fake programme names.
    """
    text = _low(message)
    if not text or re.search(r"\bS\d{3,6}\b", message or "", flags=re.I):
        return None
    if parse_subject_ranking_query(message):
        return None

    has_student_metric = (
        _has_any(text, STUDENT_TERMS)
        or _has_any(text, GPA_TERMS)
        or _has_any(text, GRADE_TERMS)
    )
    rank_verb = bool(re.search(r"\b(?:rank|ranking|leaderboard)\b", text))
    high = any(term in text for term in RANK_HIGH_TERMS)
    low = any(term in text for term in RANK_LOW_TERMS)
    has_rank_signal = rank_verb or high or low
    if not (has_student_metric and has_rank_signal):
        return None

    # A real programme/subject ranking stays on the study-term path.
    has_study_scope = any(term in text for term in STUDY_VERBS) or any(
        word in text for word in ("program", "major", "subject", "course", "class", "สาขา", "วิชา")
    )
    if has_study_scope and _extract_study_term(text):
        return None

    top_n: Optional[int] = None
    number_patterns = (
        r"\b(?:top|bottom)\s+(\d{1,3})\b",
        r"\brank(?:\s+me)?\s+(?:the\s+)?(\d{1,3})\b",
        r"^\s*(\d{1,3})\s+(?:highest|lowest|best|worst|top|bottom)\b",
        r"\b(\d{1,3})\s+(?:student|students|learner|learners)\b",
    )
    for pattern in number_patterns:
        match = re.search(pattern, text)
        if match:
            top_n = max(1, min(int(match.group(1)), 100))
            break
    if top_n is None:
        # Singular "who has the highest GPA?" means one record. An open-ended
        # "rank students" request gets a useful but bounded default leaderboard.
        singular = bool(re.search(r"\bwho\b", text)) or (
            (high or low) and not rank_verb and not re.search(r"\b(?:students|learners)\b", text)
        )
        top_n = 1 if singular else 10

    direction = "asc" if low and not high else "desc"
    return {
        "type": "student_ranking",
        "operation": "rank_students",
        "scope": "university",
        "intent": "rank",
        "field": "gpa",
        "metric_label": "GPA",
        "direction": direction,
        "top_n": top_n,
        "include_ties": False,
        "answer_style": "student_rank",
        "requested_fields": [
            "student_id", "name", "program", "gpa", "academic_status",
        ],
        "reason": (
            f"Rank the visible student population by GPA "
            f"{'ascending' if direction == 'asc' else 'descending'} and return exactly {top_n} record(s)."
        ),
    }



def _statistic_from_text(text: str) -> Optional[str]:
    for stat, terms in STATISTIC_TERMS.items():
        if any(term in text for term in terms):
            return stat
    return None



def parse_total_student_count_query(message: str) -> Optional[Dict[str, Any]]:
    """Recognise a university-wide *student count* without inventing a study term.

    Examples:
    - how many students are in the university
    - total number of students
    - มหาวิทยาลัยมีนักศึกษากี่คน

    A count with a real programme/subject term is intentionally left to the
    study-term parser, for example "how many students study law".
    """
    text = _low(message)
    if not text or re.search(r"\bS\d{3,6}\b", message or "", flags=re.I):
        return None
    if not (_has_any(text, COUNT_TERMS) and _has_any(text, STUDENT_TERMS)):
        return None
    # Numeric comparisons are a different operation (filter_summary).
    if any(re.search(pattern, text) for _, pattern in COMPARISON_PATTERNS):
        return None
    # A concrete programme/subject should not be mistaken for the entire university.
    study_term = _extract_study_term(text)
    study_signal = any(v in text for v in STUDY_VERBS) or any(w in text for w in ["program", "major", "subject", "course", "class", "สาขา", "วิชา"])
    if study_term or study_signal:
        return None
    return {
        "type": "student_total_count",
        "operation": "count",
        "scope": "university",
        "intent": "count",
        "answer_style": "count",
        "reason": "The latest message asks for the total number of students in the university, without a programme, subject, GPA, or grade filter.",
    }


def parse_student_statistic_query(message: str) -> Optional[Dict[str, Any]]:
    """Parse student statistics while separating university-wide and study-term scopes.

    The old implementation treated every "how many students" request as a
    study-term aggregate even when no term existed. That produced invalid plans
    such as operation=study_term_aggregate with study_term="".
    """
    text = _low(message)
    if not text or re.search(r"\bS\d{3,6}\b", message or "", flags=re.I):
        return None
    if parse_subject_ranking_query(message):
        return None
    if parse_student_ranking_query(message):
        return None

    stat = _statistic_from_text(text)
    if not stat:
        return None

    has_student_context = _has_any(text, STUDENT_TERMS) or _has_any(text, GPA_TERMS) or _has_any(text, GRADE_TERMS)
    has_study_context = any(v in text for v in STUDY_VERBS) or any(w in text for w in ["program", "major", "subject", "course", "class", "สาขา", "วิชา"])
    if not (has_student_context or has_study_context):
        return None

    term = _extract_study_term(text)
    # Phrases such as "all students" and "students in the university" describe
    # the population scope; they are not programme/subject names.
    generic_population_terms = {"all", "all student", "all students", "university", "the university", "entire university", "whole university", "ทุกคน", "ทั้งหมด", "ทั้งมหาวิทยาลัย"}
    if term.lower().strip() in generic_population_terms:
        term = ""

    # "How many students are in the university?" is a direct count, not an
    # aggregate that requires a programme/subject term. The planner will route
    # it to operation=count through parse_total_student_count_query.
    if stat == "count" and not term and not has_study_context:
        return None

    field = "gpa"
    requested_fields = ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"]

    if term:
        return {
            "type": "student_study_term_aggregate",
            "operation": "study_term_aggregate",
            "scope": "study_term",
            "study_term": term,
            "statistic": stat,
            "field": field,
            "metric_label": "GPA",
            "intent": "aggregate",
            "answer_style": "study_statistic",
            "requested_fields": requested_fields,
            "reason": f"Latest message asks for {stat} GPA for students matching the programme/subject term {term!r}.",
        }

    # Explicit statistics such as "median GPA of all students" are valid
    # university-wide calculations. They use a different operation that does
    # not require or fabricate a study term.
    if stat in {"median", "average", "maximum", "minimum"}:
        return {
            "type": "student_population_aggregate",
            "operation": "student_population_aggregate",
            "scope": "university",
            "study_term": "",
            "statistic": stat,
            "field": field,
            "metric_label": "GPA",
            "intent": "aggregate",
            "answer_style": "population_statistic",
            "requested_fields": requested_fields,
            "reason": f"Latest message asks for university-wide {stat} GPA, without a programme/subject filter.",
        }

    return None

def parse_student_study_query(message: str) -> Optional[Dict[str, Any]]:
    """Parse student study/program/subject questions into a safe database contract."""
    text = _low(message)
    if not text:
        return None
    # Do not hijack explicit single-record requests.
    if re.search(r"\bS\d{3,6}\b", message or "", flags=re.I):
        return None

    has_student = _has_any(text, STUDENT_TERMS) or any(w in text for w in ["who", "name", "names", "them", "those", "of them", "คน", "นักศึกษา", "นักเรียน"])
    has_study_signal = any(v in text for v in STUDY_VERBS) or any(w in text for w in ["program", "major", "subject", "course", "law students"])
    if not (has_student and has_study_signal):
        return None

    term = _extract_study_term(text)
    if not term:
        return None

    bad_terms = {"student", "students", "name", "names", "the", "that", "who", "which", "study", "studies", "list", "show", "have", "has"}
    if term.lower() in bad_terms or len(term) < 2:
        return None

    ranking = _ranking_from_text(text)
    wants_count = _has_any(text, COUNT_TERMS)
    wants_names = "name" in text or "names" in text or _has_any(text, LIST_TERMS) or not wants_count
    intent = "count" if wants_count else ("rank" if ranking else ("list" if wants_names else "search"))
    answer_style = "study_count" if wants_count else ("study_rank" if ranking else "study_search")
    requested_fields = ["student_id", "name", "program", "academic_status", "subject_grades"]
    if ranking:
        requested_fields.insert(3, "gpa")
    return {
        "type": "student_study_term_search",
        "study_term": term,
        "intent": intent,
        "answer_style": answer_style,
        "requested_fields": requested_fields,
        "ranking": ranking,
        "reason": "Latest message asks which students study a specific program/subject term, so search program and subject_grades.subject before answering. If ranking is requested, sort matching students by GPA.",
    }
