from typing import Dict, Any, List, Optional
import os
import statistics
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
MONGO_DB = os.getenv("MONGO_DB", "university_mongo")


def get_db():
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB]


ALLOWED_STUDENT_QUERY_FIELDS = {
    "student_id", "name", "program", "gpa", "academic_status",
    "subject_grades.subject", "subject_grades.grade", "subject_grades.advisor_id",
}
ALLOWED_QUERY_OPS = {"$lt", "$lte", "$gt", "$gte", "$eq", "$ne", "$regex", "$options", "$in"}
ALLOWED_STUDENT_SORT_FIELDS = {"student_id", "name", "program", "gpa", "academic_status"}


def _safe_student_query_filter(raw_filter: Dict[str, Any]) -> Dict[str, Any]:
    """Validate LLM-created Mongo filters before database execution."""
    if not isinstance(raw_filter, dict):
        return {}
    clean: Dict[str, Any] = {}
    for field, value in raw_filter.items():
        if field not in ALLOWED_STUDENT_QUERY_FIELDS:
            continue
        if isinstance(value, dict):
            op_clean: Dict[str, Any] = {}
            for op, op_value in value.items():
                if op not in ALLOWED_QUERY_OPS:
                    continue
                if field == "gpa" and op != "$options":
                    try:
                        if op == "$in" and isinstance(op_value, list):
                            op_clean[op] = [float(x) for x in op_value]
                        else:
                            op_clean[op] = float(op_value)
                    except Exception:
                        continue
                else:
                    op_clean[op] = op_value
            if op_clean:
                # Regex must always be case-insensitive only; never allow arbitrary regex options.
                if "$regex" in op_clean:
                    op_clean["$options"] = "i"
                clean[field] = op_clean
        else:
            if field == "gpa":
                try:
                    clean[field] = float(value)
                except Exception:
                    continue
            else:
                clean[field] = value
    return clean


def _safe_sort(raw_sort: Any) -> list[tuple[str, int]]:
    if not isinstance(raw_sort, list):
        return [("student_id", 1)]
    clean: list[tuple[str, int]] = []
    for item in raw_sort:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        direction = str(item.get("direction") or "asc").lower()
        if field in ALLOWED_STUDENT_SORT_FIELDS:
            clean.append((field, -1 if direction == "desc" else 1))
    return clean or [("student_id", 1)]


def _safe_limit(value: Any, default: int = 200) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(1, min(n, 5000))


def _role_scoped_student_query(
    raw_query: Optional[Dict[str, Any]],
    *,
    user_role: Optional[str],
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply signed-role row scope before MongoDB reads or aggregate counts."""
    query = dict(raw_query or {})
    role = str(user_role or "").lower()
    if role == "student" and requester_student_id:
        query["student_id"] = requester_student_id
    elif role == "advisor" and requester_advisor_id:
        query["subject_grades.advisor_id"] = requester_advisor_id
    return query


def project_student(student: Dict[str, Any], requested_fields: List[str]) -> Dict[str, Any]:
    student = dict(student or {})
    student.pop("_id", None)
    if not requested_fields:
        return student
    return {field: student.get(field) for field in requested_fields if field in student}


def filter_advisor_subject_grades(student: Dict[str, Any], advisor_id: str) -> Dict[str, Any]:
    subject_grades = student.get("subject_grades", []) or []
    taught_grades = [item for item in subject_grades if item.get("advisor_id") == advisor_id]

    if not taught_grades:
        return {
            "student_id": student.get("student_id"),
            "name": student.get("name"),
            "message": "This advisor does not teach this student, so no grade data is available.",
        }

    return {
        "student_id": student.get("student_id"),
        "name": student.get("name"),
        "program": student.get("program"),
        "academic_status": student.get("academic_status"),
        "subject_grades": taught_grades,
    }


def _grade_summary_for_students(students: List[Dict[str, Any]], grade_target: Optional[str] = None) -> Dict[str, Any]:
    target = (grade_target or "").upper().strip() or None
    rows = []
    total_exact = 0
    total_all_grades = 0
    grade_distribution: Dict[str, int] = {}

    for student in students:
        grades = student.get("subject_grades", []) or []
        exact_count = 0
        grade_items = []
        for item in grades:
            if not isinstance(item, dict):
                continue
            grade = str(item.get("grade", "")).upper().strip()
            subject = item.get("subject")
            if grade:
                grade_distribution[grade] = grade_distribution.get(grade, 0) + 1
                total_all_grades += 1
            if target and grade == target:
                exact_count += 1
                total_exact += 1
            grade_items.append({"subject": subject, "grade": grade, "advisor_id": item.get("advisor_id")})

        row = {
            "student_id": student.get("student_id"),
            "name": student.get("name"),
            "program": student.get("program"),
            "grade_count": exact_count if target else len(grades),
            "grades": grade_items,
        }
        if target:
            row["grade_target"] = target
        rows.append(row)

    return {
        "type": "grade_summary",
        "grade_target": target,
        "total_matching_grades": total_exact if target else None,
        "total_grade_records": total_all_grades,
        "grade_distribution": grade_distribution,
        "students": rows,
    }



def _schema_overview(collection, sample_limit: int = 5) -> Dict[str, Any]:
    total = collection.count_documents({})
    samples = list(collection.find({}, {"_id": 0}).limit(sample_limit))
    fields: Dict[str, Dict[str, Any]] = {}
    for row in samples:
        for key, value in row.items():
            info = fields.setdefault(key, {"type_examples": set(), "example": None})
            info["type_examples"].add(type(value).__name__)
            if info["example"] is None:
                if isinstance(value, list):
                    info["example"] = f"list[{len(value)} items]"
                elif isinstance(value, dict):
                    info["example"] = "object"
                else:
                    info["example"] = value
    clean_fields = []
    for key, info in sorted(fields.items()):
        clean_fields.append({
            "field": key,
            "types": sorted(info["type_examples"]),
            "example": info["example"],
        })
    return {"type": "mongo_schema_overview", "collection": collection.name, "count": total, "fields": clean_fields}



def _subject_summary_for_students(students: List[Dict[str, Any]], scope: str = "all") -> Dict[str, Any]:
    """Summarize subjects/courses from student subject_grades.

    This answers questions like "how many subjects are there in this university"
    without confusing subjects with students.
    """
    subject_map: Dict[str, Dict[str, Any]] = {}
    total_grade_records = 0
    programs: Dict[str, int] = {}

    for student in students:
        program = student.get("program")
        if program:
            programs[program] = programs.get(program, 0) + 1
        for grade_item in student.get("subject_grades", []) or []:
            if not isinstance(grade_item, dict):
                continue
            subject = str(grade_item.get("subject") or "").strip()
            if not subject:
                continue
            total_grade_records += 1
            row = subject_map.setdefault(subject, {
                "subject": subject,
                "student_ids": set(),
                "advisors": set(),
                "grade_distribution": {},
                "grade_record_count": 0,
            })
            sid = student.get("student_id")
            advisor = grade_item.get("advisor_id")
            grade = str(grade_item.get("grade") or "").strip().upper()
            if sid:
                row["student_ids"].add(sid)
            if advisor:
                row["advisors"].add(advisor)
            if grade:
                row["grade_distribution"][grade] = row["grade_distribution"].get(grade, 0) + 1
            row["grade_record_count"] += 1

    subjects: List[Dict[str, Any]] = []
    for subject, row in sorted(subject_map.items(), key=lambda kv: kv[0].lower()):
        subjects.append({
            "subject": subject,
            "student_count": len(row["student_ids"]),
            "grade_record_count": row["grade_record_count"],
            "advisors": sorted(row["advisors"]),
            "grade_distribution": dict(sorted(row["grade_distribution"].items())),
        })

    top_subjects = sorted(subjects, key=lambda r: (-int(r.get("student_count") or 0), str(r.get("subject") or "")))[:20]
    return {
        "type": "subject_summary",
        "scope": scope,
        "unique_subject_count": len(subjects),
        "total_subject_grade_records": total_grade_records,
        "student_count_in_scope": len(students),
        "program_distribution": dict(sorted(programs.items())),
        "subjects": subjects,
        "top_subjects": top_subjects,
        "explanation": "unique_subject_count counts unique subject names found in subject_grades; total_subject_grade_records counts each student-subject grade record.",
    }


def _student_filter_summary(
    *,
    collection,
    mongo_query: Dict[str, Any],
    requested_fields: List[str],
    sort_spec: List[tuple[str, int]],
    limit: int,
    display_limit: int,
    user_role: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    metric_query: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return both a count and preview rows for aggregate/filter questions.

    This avoids the old failure mode where the final answer only received a
    preview list and could not truthfully state the count.
    """
    projection = {"_id": 0}
    cursor = collection.find(mongo_query or {}, projection)
    for field, direction in sort_spec:
        cursor = cursor.sort(field, direction)
        break

    # Fetch enough rows to count accurately within the demo limits. For admin this
    # demo caps at 5000 to prevent runaway responses.
    all_matching = list(cursor.limit(5000))

    if user_role == "advisor":
        visible = []
        for student in all_matching:
            result = filter_advisor_subject_grades(student, requester_advisor_id)
            if "subject_grades" in result:
                visible.append(result)
        all_matching = visible

    total = len(all_matching)
    preview_raw = all_matching[:max(1, min(display_limit or limit or 50, 200))]
    preview_rows = [project_student(student, requested_fields) for student in preview_raw]

    return {
        "type": "student_filter_summary",
        "count": total,
        "query_filter": mongo_query or {},
        "metric_query": metric_query or {},
        "students": preview_rows,
        "preview_count": len(preview_rows),
        "total_records": total,
        "truncated": total > len(preview_rows),
        "explanation": "count is calculated after applying the MongoDB query_filter and PDPA visibility rules.",
    }



def _student_study_term_search(
    *,
    collection,
    study_term: str,
    requested_fields: List[str],
    limit: int,
    display_limit: int,
    user_role: Optional[str] = None,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
    ranking: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Search students by program or subject name using real MongoDB data.

    V9 adds ranking support for prompts such as "highest grade program law".
    In this schema the sortable grade metric for a program is student GPA, so the
    result can return the top/lowest matching students without letting the final
    answer guess from an unsorted list.
    """
    term = str(study_term or "").strip()
    if not term:
        return {"type": "student_study_term_search", "count": 0, "study_term": term, "students": [], "message": "Missing study term."}
    low = term.lower()
    role_query = _role_scoped_student_query(
        {},
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )
    rows = list(collection.find(role_query, {"_id": 0}).sort("student_id", 1).limit(5000))
    matches: List[Dict[str, Any]] = []
    for student in rows:
        if user_role == "advisor":
            student = filter_advisor_subject_grades(student, requester_advisor_id)
            if "subject_grades" not in student:
                continue
        program = str(student.get("program") or "")
        subject_grades = student.get("subject_grades") or []
        matching_subjects = []
        if low in program.lower():
            pass
        for item in subject_grades:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject") or item.get("subject_name") or "")
            if low in subject.lower():
                matching_subjects.append({
                    "subject": subject,
                    "grade": item.get("grade"),
                    "advisor_id": item.get("advisor_id"),
                })
        if low in program.lower() or matching_subjects:
            row = project_student(student, requested_fields or ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"])
            row["matching_program"] = program if low in program.lower() else None
            row["matching_subjects"] = matching_subjects
            row["match_reason"] = "program" if low in program.lower() else "subject_grades.subject"
            matches.append(row)
    ranking = ranking if isinstance(ranking, dict) else None
    ranking_applied = None
    if ranking:
        field = str(ranking.get("field") or "gpa")
        direction = str(ranking.get("direction") or "desc").lower()
        if field not in {"gpa", "student_id", "name", "program", "academic_status"}:
            field = "gpa"
        reverse = direction != "asc"
        def _sort_value(row):
            value = row.get(field)
            if value is None:
                return -999999 if reverse else 999999
            try:
                return float(value)
            except Exception:
                return str(value).lower()
        matches.sort(key=_sort_value, reverse=reverse)
        top_n = _safe_limit(ranking.get("top_n"), default=limit or 20)
        display_limit = min(display_limit or top_n, top_n)
        ranking_applied = {
            "field": field,
            "direction": direction,
            "top_n": top_n,
            "metric_label": ranking.get("metric_label") or field.upper(),
            "reason": ranking.get("reason") or "Ranking was requested by the latest user message.",
        }
    total = len(matches)
    preview = matches[:max(1, min(display_limit or limit or 50, 200))]
    return {
        "type": "student_study_term_search",
        "study_term": term,
        "count": total,
        "students": preview,
        "preview_count": len(preview),
        "total_records": total,
        "truncated": total > len(preview),
        "ranking_applied": ranking_applied,
        "explanation": "Search matched the study term against student program and subject_grades.subject fields after PDPA visibility rules; ranking is applied before preview when requested.",
    }



def _student_study_term_aggregate(
    *,
    collection,
    study_term: str,
    statistic: str,
    metric_field: str,
    requested_fields: List[str],
    display_limit: int,
    user_role: Optional[str] = None,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute statistics for students matching a program/subject term.

    V10 prevents the old failure where the planner searched a filler phrase like
    "what is" and then validation passed.  This function returns the exact term,
    matching population, computed value, and supporting rows so the final answer
    can be grounded.
    """
    term = str(study_term or "").strip()
    stat = str(statistic or "count").lower().strip()
    field = str(metric_field or "gpa").lower().strip()
    if field not in {"gpa"}:
        field = "gpa"
    if stat not in {"median", "average", "maximum", "minimum", "count"}:
        stat = "count"
    if not term:
        return {
            "type": "student_study_term_aggregate",
            "success": True,
            "study_term": term,
            "statistic": stat,
            "field": field,
            "count": 0,
            "value": None,
            "students": [],
            "message": "Missing study term for aggregate query.",
        }

    low = term.lower()
    role_query = _role_scoped_student_query(
        {},
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )
    rows = list(collection.find(role_query, {"_id": 0}).sort("student_id", 1).limit(5000))
    matches: List[Dict[str, Any]] = []
    values: List[float] = []
    for student in rows:
        if user_role == "advisor":
            student = filter_advisor_subject_grades(student, requester_advisor_id)
            if "subject_grades" not in student:
                continue
        program = str(student.get("program") or "")
        subject_grades = student.get("subject_grades") or []
        matching_subjects = []
        for item in subject_grades:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("subject") or item.get("subject_name") or "")
            if low in subject.lower():
                matching_subjects.append({
                    "subject": subject,
                    "grade": item.get("grade"),
                    "advisor_id": item.get("advisor_id"),
                })
        if low in program.lower() or matching_subjects:
            row = project_student(student, requested_fields or ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"])
            row["matching_program"] = program if low in program.lower() else None
            row["matching_subjects"] = matching_subjects
            row["match_reason"] = "program" if low in program.lower() else "subject_grades.subject"
            matches.append(row)
            try:
                val = float(student.get(field))
                values.append(val)
            except Exception:
                pass

    value = None
    if stat == "count":
        value = len(matches)
    elif values:
        if stat == "median":
            value = float(statistics.median(values))
        elif stat == "average":
            value = float(sum(values) / len(values))
        elif stat == "maximum":
            value = float(max(values))
        elif stat == "minimum":
            value = float(min(values))

    # For max/min, sort supporting students in the same direction. For average/median,
    # show rows sorted by student_id for transparent population preview.
    if stat in {"maximum", "minimum"}:
        reverse = stat == "maximum"
        matches.sort(key=lambda r: float(r.get(field) or -999999), reverse=reverse)
    else:
        matches.sort(key=lambda r: str(r.get("student_id") or ""))
    preview = matches[:max(1, min(display_limit or 50, 200))]
    return {
        "type": "student_study_term_aggregate",
        "study_term": term,
        "statistic": stat,
        "field": field,
        "metric_label": field.upper(),
        "count": len(matches),
        "value": round(value, 4) if isinstance(value, float) else value,
        "values_used_count": len(values),
        "students": preview,
        "preview_count": len(preview),
        "total_records": len(matches),
        "truncated": len(matches) > len(preview),
        "explanation": "Matches were filtered by program or subject_grades.subject; statistic was computed from numeric GPA values after PDPA visibility rules.",
    }


def _student_population_aggregate(
    *,
    collection,
    statistic: str,
    metric_field: str,
    requested_fields: List[str],
    display_limit: int,
    user_role: Optional[str] = None,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute a university-wide student statistic without a fake study term."""
    stat = str(statistic or "count").lower().strip()
    field = str(metric_field or "gpa").lower().strip()
    if stat not in {"median", "average", "maximum", "minimum", "count"}:
        stat = "count"
    if field != "gpa":
        field = "gpa"

    role_query = _role_scoped_student_query(
        {},
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )
    rows = list(collection.find(role_query, {"_id": 0}).sort("student_id", 1).limit(5000))
    matches: List[Dict[str, Any]] = []
    values: List[float] = []
    for student in rows:
        if user_role == "advisor":
            student = filter_advisor_subject_grades(student, requester_advisor_id)
            if "subject_grades" not in student:
                continue
        row = project_student(student, requested_fields or ["student_id", "name", "program", "gpa", "academic_status"])
        matches.append(row)
        try:
            values.append(float(student.get(field)))
        except Exception:
            pass

    value = None
    if stat == "count":
        value = len(matches)
    elif values:
        if stat == "median":
            value = float(statistics.median(values))
        elif stat == "average":
            value = float(sum(values) / len(values))
        elif stat == "maximum":
            value = float(max(values))
        elif stat == "minimum":
            value = float(min(values))

    extreme_count = None
    preview_source = matches
    if stat in {"maximum", "minimum"}:
        matches.sort(key=lambda r: float(r.get(field) or -999999), reverse=(stat == "maximum"))
        preview_source = []
        if value is not None:
            for row in matches:
                try:
                    if abs(float(row.get(field)) - float(value)) < 1e-9:
                        preview_source.append(row)
                except Exception:
                    continue
        extreme_count = len(preview_source)
    else:
        matches.sort(key=lambda r: str(r.get("student_id") or ""))
    preview = preview_source[:max(1, min(display_limit or 50, 200))]
    return {
        "type": "student_population_aggregate",
        "scope": "university",
        "statistic": stat,
        "field": field,
        "metric_label": field.upper(),
        "count": len(matches),
        "value": round(value, 4) if isinstance(value, float) else value,
        "values_used_count": len(values),
        "students": preview,
        "extreme_count": extreme_count,
        "preview_count": len(preview),
        "total_records": len(matches),
        "truncated": len(preview_source) > len(preview),
        "explanation": "Statistic was computed across the visible student population after PDPA visibility rules; no programme or subject filter was applied.",
    }


def _rank_students(
    *,
    collection,
    query_filter: Dict[str, Any],
    requested_fields: List[str],
    field: str,
    direction: str,
    top_n: int,
    user_role: Optional[str] = None,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return an exact, bounded, and explicitly ordered student leaderboard."""
    ranking_field = field if field in ALLOWED_STUDENT_SORT_FIELDS else "gpa"
    ranking_direction = "asc" if str(direction).lower() == "asc" else "desc"
    requested_count = max(1, min(int(top_n or 10), 100))
    mongo_query = _role_scoped_student_query(
        dict(query_filter or {}),
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )
    mongo_query.setdefault(ranking_field, {"$ne": None})
    total_candidates = collection.count_documents(mongo_query)
    sort_direction = 1 if ranking_direction == "asc" else -1
    cursor = collection.find(mongo_query, {"_id": 0}).sort([
        (ranking_field, sort_direction),
        ("student_id", 1),
    ]).limit(requested_count)
    students: List[Dict[str, Any]] = []
    for student in cursor:
        if user_role == "advisor":
            student = filter_advisor_subject_grades(student, requester_advisor_id)
        students.append(project_student(
            student,
            requested_fields or ["student_id", "name", "program", "gpa", "academic_status"],
        ))
    return {
        "type": "student_ranking",
        "scope": "university",
        "field": ranking_field,
        "metric_label": ranking_field.upper(),
        "direction": ranking_direction,
        "requested_count": requested_count,
        "returned_count": len(students),
        "total_candidates": total_candidates,
        "include_ties": False,
        "students": students,
        "truncated": total_candidates > len(students),
        "explanation": "Students are ordered by the requested numeric field with student ID as the stable tie-breaker.",
    }


def _group_students(
    *,
    collection,
    dimension: str,
    measure: str,
    direction: str,
    top_n: int,
    user_role: Optional[str] = None,
    requester_student_id: Optional[str] = None,
    requester_advisor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate allowlisted student-master group metrics without dynamic Mongo."""
    safe_dimension = dimension if dimension in {"program", "academic_status"} else "program"
    safe_measure = measure if measure in {"student_count", "average_gpa"} else "student_count"
    query = _role_scoped_student_query(
        {},
        user_role=user_role,
        requester_student_id=requester_student_id,
        requester_advisor_id=requester_advisor_id,
    )
    rows = list(collection.find(query, {"_id": 0, safe_dimension: 1, "gpa": 1, "student_id": 1}).limit(5000))
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = str(row.get(safe_dimension) or "Unknown")
        bucket = grouped.setdefault(key, {"group": key, "student_count": 0, "gpa_total": 0.0, "gpa_count": 0})
        bucket["student_count"] += 1
        try:
            bucket["gpa_total"] += float(row.get("gpa"))
            bucket["gpa_count"] += 1
        except (TypeError, ValueError):
            pass
    groups: List[Dict[str, Any]] = []
    for bucket in grouped.values():
        value = bucket["student_count"]
        if safe_measure == "average_gpa":
            value = round(bucket["gpa_total"] / bucket["gpa_count"], 3) if bucket["gpa_count"] else None
        groups.append({
            "group": bucket["group"],
            "value": value,
            "student_count": bucket["student_count"],
            "average_gpa": round(bucket["gpa_total"] / bucket["gpa_count"], 3) if bucket["gpa_count"] else None,
        })
    reverse = str(direction or "desc").lower() != "asc"
    groups.sort(
        key=lambda row: (
            -(float(row.get("value")) if row.get("value") is not None else float("-inf"))
            if reverse else (float(row.get("value")) if row.get("value") is not None else float("inf")),
            str(row.get("group") or ""),
        )
    )
    bounded = max(1, min(int(top_n or 20), 100))
    return {
        "type": "group_analytics",
        "source": "mongodb_student_master",
        "dimension": safe_dimension,
        "measure": safe_measure,
        "direction": "desc" if reverse else "asc",
        "group_count": len(groups),
        "groups": groups[:bounded],
        "scope_count": len(rows),
        "truncated": len(groups) > bounded,
    }


def _compare_student_to_population(
    *,
    collection,
    student_id: str,
) -> Dict[str, Any]:
    student = collection.find_one({"student_id": student_id}, {"_id": 0, "student_id": 1, "name": 1, "gpa": 1})
    values: List[float] = []
    for row in collection.find({"gpa": {"$ne": None}}, {"_id": 0, "gpa": 1}).limit(5000):
        try:
            values.append(float(row.get("gpa")))
        except (TypeError, ValueError):
            continue
    average = round(sum(values) / len(values), 3) if values else None
    student_gpa = student.get("gpa") if isinstance(student, dict) else None
    try:
        difference = round(float(student_gpa) - float(average), 3) if average is not None else None
    except (TypeError, ValueError):
        difference = None
    return {
        "type": "student_benchmark",
        "student": student,
        "measure": "gpa",
        "population_average": average,
        "population_count": len(values),
        "difference": difference,
    }


def mongodb_student_tool(arguments: Dict[str, Any]) -> Any:
    db = get_db()
    collection = db["students"]

    student_id = arguments.get("student_id", "S001")
    requested_fields = arguments.get("requested_fields", [])
    operation = arguments.get("operation") or "read_students"
    user_role = arguments.get("_user_role")
    requester_student_id = arguments.get("_requester_student_id")
    requester_advisor_id = arguments.get("_requester_advisor_id")
    grade_target = arguments.get("grade_target")
    query_filter = _safe_student_query_filter(arguments.get("query_filter", {}))
    requested_student_ids = []
    for sid in arguments.get("requested_student_ids", []) or []:
        sid = str(sid).upper().strip()
        if sid and sid not in requested_student_ids:
            requested_student_ids.append(sid)
    sort_spec = _safe_sort(arguments.get("sort", []))
    limit = _safe_limit(arguments.get("limit"), default=5000 if student_id == "ALL" else 1)
    display_limit = _safe_limit(arguments.get("display_limit"), default=50)
    metric_query = arguments.get("metric_query") if isinstance(arguments.get("metric_query"), dict) else None

    if operation == "schema_overview":
        return _schema_overview(collection)

    if operation == "subject_summary":
        mongo_query = dict(query_filter)
        if student_id != "ALL":
            mongo_query["student_id"] = student_id
        mongo_query = _role_scoped_student_query(
            mongo_query,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )
        cursor = collection.find(mongo_query, {"_id": 0, "student_id": 1, "name": 1, "program": 1, "subject_grades": 1}).sort("student_id", 1)
        students = list(cursor.limit(limit))
        scope = "all_students"
        if user_role == "advisor":
            filtered_students = []
            for student in students:
                filtered_grades = [g for g in student.get("subject_grades", []) or [] if isinstance(g, dict) and g.get("advisor_id") == requester_advisor_id]
                if filtered_grades:
                    copy = dict(student)
                    copy["subject_grades"] = filtered_grades
                    filtered_students.append(copy)
            students = filtered_students
            scope = f"advisor_{requester_advisor_id}"
        elif user_role == "student":
            scope = f"student_{arguments.get('_requester_student_id') or student_id}"
        return _subject_summary_for_students(students, scope=scope)

    if operation == "rank_students":
        ranking = arguments.get("ranking") if isinstance(arguments.get("ranking"), dict) else {}
        return _rank_students(
            collection=collection,
            query_filter=query_filter,
            requested_fields=requested_fields,
            field=ranking.get("field") or (sort_spec[0][0] if sort_spec else "gpa"),
            direction=ranking.get("direction") or ("desc" if sort_spec and sort_spec[0][1] < 0 else "asc"),
            top_n=arguments.get("top_n") or ranking.get("top_n") or limit,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )

    if operation == "group_students":
        analytics = arguments.get("analytics_query") if isinstance(arguments.get("analytics_query"), dict) else {}
        return _group_students(
            collection=collection,
            dimension=arguments.get("dimension") or analytics.get("dimension") or "program",
            measure=arguments.get("measure") or analytics.get("measure") or "student_count",
            direction=arguments.get("direction") or analytics.get("direction") or "desc",
            top_n=arguments.get("top_n") or analytics.get("top_n") or 20,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )

    if operation == "compare_student_to_population":
        return _compare_student_to_population(
            collection=collection,
            student_id=str(student_id or requester_student_id or "").upper(),
        )


    if operation == "study_term_search":
        return _student_study_term_search(
            collection=collection,
            study_term=arguments.get("study_term") or arguments.get("keyword") or "",
            requested_fields=requested_fields or ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"],
            limit=limit,
            display_limit=display_limit,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
            ranking=arguments.get("ranking") if isinstance(arguments.get("ranking"), dict) else None,
        )


    if operation == "student_population_aggregate":
        return _student_population_aggregate(
            collection=collection,
            statistic=arguments.get("statistic") or (arguments.get("stat_query") or {}).get("statistic") or "count",
            metric_field=arguments.get("metric_field") or (arguments.get("stat_query") or {}).get("field") or "gpa",
            requested_fields=requested_fields or ["student_id", "name", "program", "gpa", "academic_status"],
            display_limit=display_limit,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )

    if operation == "study_term_aggregate":
        return _student_study_term_aggregate(
            collection=collection,
            study_term=arguments.get("study_term") or arguments.get("keyword") or "",
            statistic=arguments.get("statistic") or (arguments.get("stat_query") or {}).get("statistic") or "count",
            metric_field=arguments.get("metric_field") or (arguments.get("stat_query") or {}).get("field") or "gpa",
            requested_fields=requested_fields or ["student_id", "name", "program", "gpa", "academic_status", "subject_grades"],
            display_limit=display_limit,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )

    if operation == "filter_summary":
        mongo_query = dict(query_filter)
        if student_id != "ALL":
            mongo_query["student_id"] = student_id
        mongo_query = _role_scoped_student_query(
            mongo_query,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )
        return _student_filter_summary(
            collection=collection,
            mongo_query=mongo_query,
            requested_fields=requested_fields or ["student_id", "name", "program", "gpa", "academic_status"],
            sort_spec=sort_spec,
            limit=limit,
            display_limit=display_limit,
            user_role=user_role,
            requester_advisor_id=requester_advisor_id,
            metric_query=metric_query,
        )

    if operation == "count":
        mongo_query = dict(query_filter)
        if student_id != "ALL":
            mongo_query["student_id"] = student_id
        mongo_query = _role_scoped_student_query(
            mongo_query,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )
        return {"type": "student_count", "count": collection.count_documents(mongo_query), "query_filter": mongo_query}

    if operation == "list_names":
        projection = {"_id": 0, "student_id": 1, "name": 1}
        mongo_query = dict(query_filter)
        if student_id != "ALL":
            mongo_query["student_id"] = student_id
        mongo_query = _role_scoped_student_query(
            mongo_query,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )
        cursor = collection.find(mongo_query, projection)
        for field, direction in sort_spec:
            cursor = cursor.sort(field, direction)
            break
        students = list(cursor.limit(limit))
        if user_role == "advisor":
            # Advisor can see names only for students they teach at least one subject.
            all_students = list(collection.find(
                _role_scoped_student_query({}, user_role=user_role, requester_advisor_id=requester_advisor_id),
                {"_id": 0, "student_id": 1, "name": 1, "subject_grades": 1},
            ).sort("student_id", 1))
            students = []
            for s in all_students:
                if any(g.get("advisor_id") == requester_advisor_id for g in s.get("subject_grades", [])):
                    students.append({"student_id": s.get("student_id"), "name": s.get("name")})
        return {"type": "student_names", "students": students}

    if operation == "grade_summary":
        mongo_query = dict(query_filter)
        if student_id != "ALL":
            mongo_query["student_id"] = student_id
        mongo_query = _role_scoped_student_query(
            mongo_query,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )
        cursor = collection.find(mongo_query, {"_id": 0})
        for field, direction in sort_spec:
            cursor = cursor.sort(field, direction)
            break
        students = list(cursor.limit(limit))
        if user_role == "advisor":
            advisor_filtered = []
            for student in students:
                result = filter_advisor_subject_grades(student, requester_advisor_id)
                if "subject_grades" in result:
                    advisor_filtered.append(result)
            students = advisor_filtered
        return _grade_summary_for_students(students, grade_target)

    if student_id == "ALL":
        scoped_query = _role_scoped_student_query(
            query_filter,
            user_role=user_role,
            requester_student_id=requester_student_id,
            requester_advisor_id=requester_advisor_id,
        )
        cursor = collection.find(scoped_query, {"_id": 0})
        # Apply sort safely. For ranking questions this prevents pulling unsorted data.
        for field, direction in sort_spec:
            cursor = cursor.sort(field, direction)
            break
        students = list(cursor.limit(limit))

        # For explicit multi-ID questions, keep the answer complete: if one requested
        # ID does not exist, return a small placeholder instead of silently ignoring it.
        found_ids = {str(s.get("student_id", "")).upper() for s in students}
        missing_rows = [
            {"student_id": sid, "name": None, "message": f"No student found with ID {sid}"}
            for sid in requested_student_ids
            if sid not in found_ids
        ]

        if user_role == "advisor":
            filtered = []
            for student in students:
                result = filter_advisor_subject_grades(student, requester_advisor_id)
                # For broad advisor lists, hide students the advisor does not teach.
                # For explicit Sxxx questions, keep a safe message so the advisor knows
                # why that ID has no visible grade data.
                if "subject_grades" in result or requested_student_ids:
                    filtered.append(result)
            filtered.extend(missing_rows)
            return filtered

        rows = [project_student(student, requested_fields) for student in students]
        rows.extend(missing_rows)

        if requested_student_ids:
            order = {sid: i for i, sid in enumerate(requested_student_ids)}
            rows.sort(key=lambda r: order.get(str(r.get("student_id", "")).upper(), 999999))
        return rows

    student = collection.find_one({"student_id": student_id}, {"_id": 0})
    if not student:
        return {"student_id": student_id, "name": None, "message": f"No student found with ID {student_id}"}

    if user_role == "advisor":
        return filter_advisor_subject_grades(student, requester_advisor_id)

    return project_student(student, requested_fields)


def mongodb_advisor_tool(arguments: Dict[str, Any]) -> Any:
    db = get_db()
    advisor_id = arguments.get("advisor_id", "A001")
    requester_advisor_id = arguments.get("_requester_advisor_id")
    user_role = arguments.get("_user_role")
    operation = arguments.get("operation") or "read_advisors"

    if operation == "schema_overview" and user_role == "admin":
        return _schema_overview(db["advisors"])

    if user_role == "advisor" and requester_advisor_id:
        advisor_id = requester_advisor_id

    if user_role == "admin" and (operation == "list_advisors" or advisor_id == "ALL"):
        advisors = list(db["advisors"].find({}, {"_id": 0}).sort("advisor_id", 1))
        return {"type": "advisor_list", "advisors": advisors}

    advisor = db["advisors"].find_one({"advisor_id": advisor_id}, {"_id": 0})
    if not advisor:
        return {"message": f"No advisor found with ID {advisor_id}"}
    return advisor
