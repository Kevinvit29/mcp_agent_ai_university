from typing import Any, Dict, List
from statistics import mean

SUPPORTED_OPERATIONS = {
    "student_risk_score",
    "lowest_gpa",
    "average_gpa",
    "duplicate_check",
}


def _weak_grade_count(subject_grades: Any) -> int:
    """
    Count weak grades from subject_grades.
    Supports both:
    - dict: {"Math": "D", "English": "B"}
    - list: [{"subject": "Math", "grade": "D"}]
    """

    weak = {"D", "F", "C-"}

    count = 0

    if isinstance(subject_grades, dict):
        for grade in subject_grades.values():
            if str(grade).upper() in weak:
                count += 1

    elif isinstance(subject_grades, list):
        for item in subject_grades:
            if isinstance(item, dict):
                grade = item.get("grade") or item.get("letter_grade")
                if str(grade).upper() in weak:
                    count += 1

    return count


def _student_risk_score(student: Dict[str, Any]) -> float:
    """
    Higher score = needs more support.
    You can improve this formula later.
    """

    gpa = float(student.get("gpa") or 0)
    status = str(student.get("academic_status", "")).lower()
    weak_count = _weak_grade_count(student.get("subject_grades"))

    score = 0

    if gpa < 2.0:
        score += 50
    elif gpa < 2.5:
        score += 35
    elif gpa < 3.0:
        score += 20

    if "warning" in status:
        score += 25

    score += weak_count * 10

    return score


def _format_student_preview(student: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "student_id": student.get("student_id"),
        "name": student.get("name"),
        "program": student.get("program"),
        "gpa": student.get("gpa"),
        "academic_status": student.get("academic_status"),
        "risk_score": student.get("risk_score"),
        "subject_grades": student.get("subject_grades"),
    }


def database_worker_tool(arguments: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    This tool performs safe database worker operations.
    Admin only.
    """

    context = context or {}
    user_role = str(context.get("user_role", "")).lower()

    if user_role != "admin":
        return {
            "type": "permission_denied",
            "message": "Only admin can use Database Worker AI."
        }

    operation = arguments.get("operation")
    limit = int(arguments.get("limit") or 20)
    dry_run = bool(arguments.get("dry_run", True))

    if operation not in SUPPORTED_OPERATIONS:
        return {
            "success": False,
            "error": "Unsupported Database Worker operation.",
            "supported_operations": sorted(SUPPORTED_OPERATIONS),
        }

    mongo_db = context.get("mongo_db")

    if mongo_db is None:
        return {
            "type": "error",
            "message": "MongoDB connection is not available in context."
        }

    students = mongo_db["students"]

    if operation == "student_risk_score":
        rows = list(students.find({}, {"_id": 0}))

        for row in rows:
            row["risk_score"] = _student_risk_score(row)

        rows.sort(key=lambda x: x.get("risk_score", 0), reverse=True)

        return {
            "type": "database_worker_result",
            "operation": "student_risk_score",
            "dry_run": dry_run,
            "total_records": len(rows),
            "records": [_format_student_preview(r) for r in rows[:limit]],
            "summary": f"Calculated risk score for {len(rows)} students.",
            "calculation_note": "Risk score is based on GPA, academic warning status, and weak subject grades."
        }

    if operation == "lowest_gpa":
        rows = list(students.find({}, {"_id": 0}).sort("gpa", 1).limit(limit))

        return {
            "type": "database_worker_result",
            "operation": "lowest_gpa",
            "dry_run": dry_run,
            "total_records": len(rows),
            "records": [_format_student_preview(r) for r in rows],
            "summary": "Students ranked by lowest GPA."
        }

    if operation == "average_gpa":
        rows = list(students.find({}, {"_id": 0, "gpa": 1, "program": 1}))

        gpas = [float(r.get("gpa")) for r in rows if r.get("gpa") is not None]

        overall_avg = round(mean(gpas), 2) if gpas else None

        by_program = {}

        for row in rows:
            program = row.get("program", "Unknown")
            gpa = row.get("gpa")

            if gpa is None:
                continue

            by_program.setdefault(program, [])
            by_program[program].append(float(gpa))

        program_summary = [
            {
                "program": program,
                "average_gpa": round(mean(values), 2),
                "student_count": len(values)
            }
            for program, values in by_program.items()
        ]

        return {
            "type": "database_worker_result",
            "operation": "average_gpa",
            "dry_run": dry_run,
            "overall_average_gpa": overall_avg,
            "by_program": program_summary,
            "summary": "Calculated average GPA overall and by program."
        }

    if operation == "duplicate_check":
        pipeline = [
            {
                "$group": {
                    "_id": "$student_id",
                    "count": {"$sum": 1},
                    "records": {"$push": "$$ROOT"}
                }
            },
            {
                "$match": {
                    "count": {"$gt": 1}
                }
            }
        ]

        duplicates = list(students.aggregate(pipeline))

        clean_duplicates = []

        for item in duplicates:
            clean_duplicates.append({
                "student_id": item["_id"],
                "count": item["count"],
                "records": [
                    {k: v for k, v in record.items() if k != "_id"}
                    for record in item["records"]
                ]
            })

        return {
            "type": "database_worker_result",
            "operation": "duplicate_check",
            "dry_run": True,
            "total_duplicate_groups": len(clean_duplicates),
            "duplicates": clean_duplicates,
            "summary": f"Found {len(clean_duplicates)} duplicated student_id group(s)."
        }

    return {
        "success": False,
        "error": "Unsupported Database Worker operation.",
        "supported_operations": sorted(SUPPORTED_OPERATIONS),
    }
