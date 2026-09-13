"""Final Answer Writer for Agent Orchestrator V1.

The model may write natural language, but protected database facts are first
formatted deterministically from MCP output.  This prevents the AI from
inventing fields or ignoring rows.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from app.agent.response_generator import generate_final_answer
from app.agent.ai_client import ai_generate_text
from app.agent.data_truth import format_authoritative_university_overview
from app.agent.document_qa import answer_from_selected_document, is_general_document_overview_question
from app.agent.answer_failures import safe_failure_message


def _unwrap_data(tool_result: Dict[str, Any]) -> Any:
    data = tool_result.get("data") if isinstance(tool_result, dict) else None
    if isinstance(data, dict) and data.get("success") is True and "data" in data:
        return data.get("data")
    return data


def _lang_is_thai(language: str, message: str) -> bool:
    return (language or "").lower().startswith("th") or any("\u0e00" <= ch <= "\u0e7f" for ch in message or "")


def _line_join(lines: List[str]) -> str:
    return "\n".join([line for line in lines if line is not None])


def _format_subject_summary(data: Dict[str, Any], thai: bool, arguments: Optional[Dict[str, Any]] = None, user_role: str = "admin") -> str:
    arguments = arguments or {}
    count = data.get("unique_subject_count", 0)
    total = data.get("total_subject_grade_records", 0)
    students = data.get("student_count_in_scope", 0)
    subjects = data.get("subjects") or []
    top = data.get("top_subjects") or subjects[:20]
    answer_style = str(arguments.get("answer_style") or "subject_summary")
    if answer_style == "subject_rank":
        top_n = max(1, min(int(arguments.get("top_n") or 5), 50))
        ranked = top[:top_n]
        if user_role == "student":
            if thai:
                lines = ["ข้อมูลที่คุณมีสิทธิ์เข้าถึงมีเฉพาะวิชาที่อยู่ในระเบียนของคุณ จึงยังจัดอันดับวิชาใหม่แบบเฉพาะบุคคลจากความสนใจหรือวิชาบังคับก่อนไม่ได้"]
                lines.append("\nวิชาในระเบียนของคุณ:")
                lines.extend(f"{index}. {row.get('subject')}" for index, row in enumerate(ranked, start=1))
                lines.append(f"\nพบระเบียนวิชา/เกรดทั้งหมด {total} รายการ")
                return _line_join(lines)
            lines = ["Your authorised data contains only subjects already in your own record, so I cannot rank new courses as a personalized recommendation from interests or prerequisites yet."]
            lines.append("\nSubjects in your record:")
            lines.extend(f"{index}. {row.get('subject')}" for index, row in enumerate(ranked, start=1))
            lines.append(f"\nYour record contains {total} student-subject grade record(s).")
            return _line_join(lines)
        if thai:
            scope = "ทั้งมหาวิทยาลัย" if user_role == "admin" else ("นักศึกษาในรายวิชาที่ได้รับมอบหมาย" if user_role in {"advisor", "lecturer"} else "ข้อมูลของคุณเอง")
            lines = [f"อันดับ {len(ranked)} วิชาจาก{scope} โดยเรียงตามจำนวนนักศึกษาที่ลงเรียน:"]
            lines.extend(f"{index}. {row.get('subject')} — {row.get('student_count', 0)} คน" for index, row in enumerate(ranked, start=1))
            lines.append(f"\nอ้างอิงข้อมูลนักศึกษา {students} คน และระเบียนวิชา/เกรด {total} รายการ")
            lines.append("หมายเหตุ: นี่คืออันดับความนิยมจากจำนวนผู้เรียน ไม่ใช่คำแนะนำเฉพาะบุคคลตามความสนใจหรือวิชาบังคับก่อน")
            return _line_join(lines)
        scope = "university-wide data" if user_role == "admin" else ("students in your assigned courses" if user_role in {"advisor", "lecturer"} else "your own record")
        lines = [f"Top {len(ranked)} subjects in {scope}, ranked by distinct enrolled-student count:"]
        lines.extend(f"{index}. {row.get('subject')} — {row.get('student_count', 0)} student(s)" for index, row in enumerate(ranked, start=1))
        lines.append(f"\nBased on {students} student(s) and {total} student-subject grade record(s) in your authorised scope.")
        lines.append("Note: this is a popularity ranking from enrollment data, not a personalized recommendation based on interests or prerequisites.")
        return _line_join(lines)
    if thai:
        lines = [f"มีรายวิชาที่ไม่ซ้ำทั้งหมด {count} วิชา", f"พบข้อมูลเกรดรายวิชารวม {total} รายการ"]
        if top:
            lines.append("\nรายวิชาที่พบ:")
            for row in top[:25]:
                advisors = ", ".join(row.get("advisors") or []) or "-"
                lines.append(f"- {row.get('subject')}: นักศึกษา {row.get('student_count')} คน, advisor {advisors}")
        return _line_join(lines)
    lines = [f"There are {count} unique subjects in the university data.", f"I found {total} total student-subject grade records."]
    if top:
        lines.append("\nSubjects found:")
        for row in top[:25]:
            advisors = ", ".join(row.get("advisors") or []) or "-"
            lines.append(f"- {row.get('subject')}: {row.get('student_count')} student(s), advisor(s): {advisors}")
    return _line_join(lines)


def _format_grade_list(student: Dict[str, Any], thai: bool) -> List[str]:
    sid = student.get("student_id") or "Unknown"
    name = student.get("name") or ""
    if student.get("message") and not student.get("subject_grades"):
        return [f"- {sid}: {student.get('message')}"]
    header = f"- {sid}" + (f" ({name})" if name else "")
    grades = student.get("subject_grades") or []
    if not grades:
        return [header + (": ไม่พบข้อมูลเกรด" if thai else ": no grade records found")]
    lines = [header]
    for g in grades:
        if isinstance(g, dict):
            subj = g.get("subject") or g.get("subject_name") or "Unknown subject"
            grade = g.get("grade") or "-"
            score = g.get("score")
            detail = f"grade {grade}, score {_format_number(score)}" if score is not None else str(grade)
            lines.append(f"  - {subj}: {detail}")
    return lines


def _format_students(data: Any, answer_style: str, thai: bool) -> Optional[str]:
    rows: List[Dict[str, Any]]
    if isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict) and data.get("type") == "grade_summary":
        rows = data.get("students") or []
        lines = ["สรุปข้อมูลเกรด:" if thai else "Grade summary:"]
        if data.get("grade_target"):
            lines.append((f"จำนวนเกรด {data.get('grade_target')} ทั้งหมด: {data.get('total_matching_grades')}" if thai else f"Total exact {data.get('grade_target')} grades: {data.get('total_matching_grades')}"))
        for row in rows[:30]:
            lines.extend(_format_grade_list({"student_id": row.get("student_id"), "name": row.get("name"), "subject_grades": row.get("grades")}, thai))
        return _line_join(lines)
    elif isinstance(data, dict) and data.get("type") == "student_filter_summary":
        return _format_student_filter_summary(data, answer_style, thai)
    elif isinstance(data, dict) and data.get("type") == "student_ranking":
        return _format_student_ranking(data, thai)
    elif isinstance(data, dict) and data.get("type") == "student_study_term_aggregate":
        return _format_student_study_statistic(data, thai)
    elif isinstance(data, dict) and data.get("type") == "student_population_aggregate":
        return _format_student_population_statistic(data, thai)
    elif isinstance(data, dict) and data.get("type") == "student_study_term_search":
        return _format_student_study_search(data, answer_style, thai)
    elif isinstance(data, dict) and data.get("type") == "student_count":
        return f"ฐานข้อมูลมีนักศึกษาทั้งหมด {data.get('count')} คน" if thai else f"The database contains {data.get('count')} students in total."
    elif isinstance(data, dict) and isinstance(data.get("students"), list):
        rows = data.get("students") or []
    elif isinstance(data, dict) and data.get("student_id"):
        rows = [data]
    else:
        return None

    if not rows:
        return "ไม่พบข้อมูลนักศึกษาที่ตรงกับคำถาม" if thai else "I could not find matching student records."

    if answer_style == "student_course_list":
        subjects = []
        for row in rows:
            for item in row.get("subject_grades") or []:
                if not isinstance(item, dict):
                    continue
                subject = item.get("subject") or item.get("subject_name")
                if subject and subject not in subjects:
                    subjects.append(subject)
        if not subjects:
            return "ไม่พบรายวิชาที่บันทึกไว้ของคุณ" if thai else "No studied subjects are recorded for your account."
        heading = "รายวิชาที่บันทึกไว้ของคุณ:" if thai else "Your recorded studied subjects:"
        return _line_join([heading, *[f"- {subject}" for subject in subjects]])

    if answer_style == "gpa":
        lines = ["GPA:" if not thai else "GPA:"]
        for row in rows:
            sid = row.get("student_id") or "Unknown"
            name = row.get("name") or ""
            gpa = row.get("gpa", "Not available")
            lines.append(f"- {sid}" + (f" ({name})" if name else "") + f": {gpa}")
        return _line_join(lines)

    if answer_style == "student_multi":
        lines = ["ข้อมูล GPA และเกรด:" if thai else "GPA and grades:"]
        for row in rows[:20]:
            sid = row.get("student_id") or "Unknown"
            name = row.get("name") or ""
            lines.append(f"- {sid}" + (f" ({name})" if name else ""))
            lines.append(f"  - GPA: {row.get('gpa', 'Not available')}")
            grades = row.get("subject_grades") or []
            if grades:
                lines.append("  - วิชา/เกรด:" if thai else "  - Subjects/grades:")
                for item in grades[:20]:
                    if isinstance(item, dict):
                        subject = item.get("subject") or item.get("subject_name") or "Unknown subject"
                        grade = item.get("grade") or "-"
                        lines.append(f"    - {subject}: {grade}")
            else:
                lines.append("  - ไม่พบข้อมูลเกรดรายวิชา" if thai else "  - No subject-grade records found.")
        return _line_join(lines)

    if answer_style in {"grades", "subject_summary"}:
        lines = ["The grades are:" if not thai else "ข้อมูลเกรดมีดังนี้:"]
        for row in rows:
            lines.extend(_format_grade_list(row, thai))
        return _line_join(lines)

    if answer_style == "profile":
        lines = ["ข้อมูลโปรไฟล์นักศึกษา:" if thai else "Student profile:"]
        for row in rows[:50]:
            if row.get("message") and len(row.keys()) <= 3:
                lines.append(f"- {row.get('student_id', 'Unknown')}: {row.get('message')}")
                continue
            sid = row.get("student_id") or "Unknown"
            name = row.get("name") or ""
            lines.append(f"- {sid}" + (f" ({name})" if name else ""))
            for key, label in [("program", "Program"), ("gpa", "GPA"), ("academic_status", "Academic status"), ("email", "Email"), ("phone", "Phone")]:
                if key in row and row.get(key) is not None:
                    lines.append(f"  - {label}: {row.get(key)}")
            grades = row.get("subject_grades")
            if isinstance(grades, list) and grades:
                lines.append("  - Subjects/grades:" if not thai else "  - วิชา/เกรด:")
                for item in grades[:20]:
                    if isinstance(item, dict):
                        subject = item.get("subject") or item.get("subject_name") or "Subject"
                        grade = item.get("grade", "N/A")
                        score = item.get("score")
                        detail = f"grade {grade}, score {_format_number(score)}" if score is not None else str(grade)
                        lines.append(f"    - {subject}: {detail}")
        return _line_join(lines)

    if answer_style == "names":
        total = len(rows)
        lines = [f"รายชื่อนักศึกษาทั้งหมด {total} คน:" if thai else f"Students ({total} total):"]
        max_names = 20
        for row in rows[:max_names]:
            lines.append(f"- {row.get('student_id')}: {row.get('name')}")
        if total > max_names:
            lines.append((f"แสดง {max_names} คนแรกจากทั้งหมด {total} คน" if thai else f"Showing the first {max_names} of {total} students."))
        return _line_join(lines)

    lines = ["ข้อมูลนักศึกษา:" if thai else "Student records:"]
    for row in rows[:50]:
        if row.get("message") and len(row.keys()) <= 3:
            lines.append(f"- {row.get('student_id', 'Unknown')}: {row.get('message')}")
            continue
        pieces = []
        for key in ["student_id", "name", "program", "gpa", "academic_status", "email", "phone"]:
            if key in row and row.get(key) is not None:
                pieces.append(f"{key}: {row.get(key)}")
        lines.append("- " + ", ".join(pieces))
    return _line_join(lines)


def _format_student_ranking(data: Dict[str, Any], thai: bool) -> str:
    students = [row for row in (data.get("students") or []) if isinstance(row, dict)]
    field = str(data.get("field") or "gpa")
    metric = data.get("metric_label") or field.upper()
    direction = str(data.get("direction") or "desc")
    requested = int(data.get("requested_count") or len(students) or 0)
    total = int(data.get("total_candidates") or len(students))
    if not students:
        return (
            "ไม่พบข้อมูลนักศึกษาที่มีค่า GPA สำหรับจัดอันดับ"
            if thai else "I could not find student GPA records to rank."
        )
    direction_text = ("ต่ำสุด" if direction == "asc" else "สูงสุด") if thai else ("lowest" if direction == "asc" else "highest")
    rank_label = ("อันดับท้าย" if direction == "asc" else "อันดับสูงสุด") if thai else ("Bottom" if direction == "asc" else "Top")
    lines = [
        (
            f"นักศึกษา{rank_label} {min(requested, len(students))} คนตาม {metric} {direction_text} จากข้อมูลที่เข้าถึงได้ {total} คน:"
            if thai else
            f"{rank_label} {min(requested, len(students))} students by {metric} from {total} available records:"
        )
    ]
    for index, row in enumerate(students, start=1):
        sid = row.get("student_id") or "Unknown"
        name = row.get("name") or ""
        program = row.get("program") or ""
        value = row.get(field)
        detail = f"{metric}: {value if value is not None else '-'}"
        if program:
            detail += f" · {program}"
        lines.append(f"{index}. {sid}" + (f" ({name})" if name else "") + f" — {detail}")
    return _line_join(lines)


def _format_group_analytics(data: Dict[str, Any], thai: bool) -> str:
    groups = [row for row in (data.get("groups") or []) if isinstance(row, dict)]
    dimension = str(data.get("dimension") or "group").replace("_", " ")
    measure = str(data.get("measure") or "value")
    label = str(data.get("metric_label") or {
        "average_gpa": "Average GPA",
        "student_count": "Student count",
        "average_score": "Average final score",
        "attendance_rate": "Average attendance (%)",
        "pass_rate": "Pass rate (%)",
        "balance_due": "Average balance due",
        "score_change": "Average score change",
    }.get(measure) or measure.replace("_", " ").title())
    if not groups:
        limitation = data.get("limitation") if isinstance(data.get("limitation"), dict) else None
        if limitation:
            missing = ", ".join(str(value) for value in (limitation.get("missing_data") or []))
            alternative = str(limitation.get("available_alternative") or "")
            if thai:
                return (
                    f"ยังคำนวณคำตอบนี้ไม่ได้จากข้อมูลปัจจุบัน เพราะขาด {missing or 'ข้อมูลประวัติที่เพียงพอ'}"
                    + (f" แต่สามารถแสดง {alternative} ได้" if alternative else "")
                )
            return (
                f"I cannot calculate this reliably because the database does not contain {missing or 'enough repeated history'}."
                + (f" I can show {alternative} instead." if alternative else "")
            )
        return (
            "ไม่พบกลุ่มข้อมูลที่ตรงกับคำถามภายในขอบเขตสิทธิ์นี้"
            if thai else "No grouped records matched this question within the signed role's data scope."
        )
    student_self = str(data.get("role_scope") or "") == "student"
    lines = [
        (
            f"ผลวิเคราะห์ของคุณ: {label} แยกตาม {dimension}:"
            if thai and student_self else
            (f"Your {label.lower()} by {dimension}:" if student_self else (f"ผลวิเคราะห์ {label} แยกตาม {dimension}:" if thai else f"{label} by {dimension}:"))
        )
    ]
    for index, row in enumerate(groups, start=1):
        value = _format_number(row.get("value"), 3 if measure == "average_gpa" else 2)
        count = row.get("student_count")
        count_text = f" · {count} student(s)" if count is not None and not student_self else ""
        lines.append(f"{index}. {row.get('group') or 'Unknown'} — {label}: {value}{count_text}")
        if measure == "score_change" and row.get("first_term") and row.get("last_term"):
            lines.append(
                f"   {row.get('first_term')}: {_format_number(row.get('first_value'))} → "
                f"{row.get('last_term')}: {_format_number(row.get('last_value'))}"
            )
    if measure == "pass_rate" and data.get("pass_threshold") is not None:
        lines.append(
            f"Pass rate uses the stored final-score threshold of {data.get('pass_threshold')}."
        )
    if measure == "average_score":
        lines.append(
            "“Grade performance” is calculated from the numeric final score stored in course enrollments; letter grades are not silently converted."
        )
    return _line_join(lines)


def _format_advisor_classroom(data: Dict[str, Any], thai: bool) -> Optional[str]:
    if data.get("type") != "advisor_classroom":
        return None
    status = str(data.get("status") or "ok")
    requested_course = str(data.get("requested_course") or "").strip()
    course = data.get("course") if isinstance(data.get("course"), dict) else {}
    course_name = str(course.get("subject_name") or requested_course or "your assigned classes")
    course_code = str(course.get("subject_code") or "")
    course_label = f"{course_name} ({course_code})" if course_code else course_name
    lecturer = str(data.get("requester_role") or "") == "lecturer"
    account_label = "lecturer" if lecturer else "advisor"

    if status == "course_not_assigned":
        if thai:
            return (
                f"ไม่พบวิชา “{requested_course or 'ที่ระบุ'}” ในรายวิชาที่ผูกกับบัญชีอาจารย์นี้ "
                "ระบบจึงไม่ค้นหาหรือเปิดเผยนักศึกษาจากชั้นเรียนของอาจารย์คนอื่น"
            )
        return (
            f"“{requested_course or 'That course'}” is not assigned to your {account_label} account. "
            f"I did not search or reveal students from another {account_label}’s class."
        )
    if status == "student_not_in_advisor_class":
        ids = ", ".join(str(value) for value in (data.get("requested_student_ids") or []))
        if thai:
            return f"ไม่พบ {ids or 'นักศึกษาที่ระบุ'} ในชั้นเรียนที่ผูกกับบัญชีอาจารย์นี้ จึงไม่แสดงข้อมูลจากชั้นเรียนอื่น"
        return (
            f"I could not find {ids or 'that student'} in any class assigned to your {account_label} account, "
            "so I did not show records from other classes."
        )

    operation = str(data.get("operation") or "class_records")
    if operation == "class_count":
        count = int(data.get("student_count") or 0)
        if thai:
            return f"{course_label}: มีนักศึกษา {count} คนในชั้นเรียนของคุณ"
        return f"{course_label}: {count} student(s) are enrolled in your assigned class."

    if operation == "class_list":
        classes = [row for row in (data.get("classes") or []) if isinstance(row, dict)]
        if not classes:
            return "ยังไม่มีรายวิชาที่ผูกกับบัญชีอาจารย์นี้" if thai else f"No classes are assigned to your {account_label} account."
        lines = ["รายวิชาที่ผูกกับบัญชีของคุณ:" if thai else f"Classes assigned to your {account_label} account:"]
        for row in classes:
            lines.append(
                f"- {row.get('subject_code') or '-'} — {row.get('subject_name') or 'Unknown'}: "
                f"{row.get('student_count') or 0} student(s)"
            )
        return _line_join(lines)

    if operation == "class_summary":
        summaries = [row for row in (data.get("summaries") or []) if isinstance(row, dict)]
        requested_metrics = set(data.get("requested_metrics") or ["grade"])
        if not summaries:
            return (
                f"{course_label}: มีข้อมูลการลงทะเบียน แต่ยังไม่มีคะแนนหรือการเข้าเรียนที่บันทึกไว้"
                if thai else
                f"{course_label}: enrollment exists, but no class score or attendance measurement has been recorded."
            )
        lines = ["สรุปเฉพาะชั้นเรียนของคุณ:" if thai else "Summary from your assigned classes only:"]
        for row in summaries:
            score = (
                _format_number(row.get("average_score"))
                if row.get("average_score") is not None else "not recorded"
            )
            attendance = (
                f"{_format_number(row.get('average_attendance'))}%"
                if row.get("average_attendance") is not None else "not recorded"
            )
            details = [f"{row.get('student_count') or 0} student(s)"]
            if "grade" in requested_metrics:
                details.append(f"average score {score}")
            if "attendance" in requested_metrics:
                details.append(f"average attendance {attendance}")
            lines.append(
                f"- {row.get('course_code')} — {row.get('course_name')}: "
                + ", ".join(details)
            )
        return _line_join(lines)

    rows = [row for row in (data.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        return (
            f"ไม่พบนักศึกษาใน {course_label}"
            if thai else f"No students are enrolled in {course_label} within your advisor scope."
        )
    if operation == "class_roster":
        lines = [
            f"รายชื่อนักศึกษาใน {course_label}:" if thai else
            f"Students in {course_label} (your class only):"
        ]
        for row in rows:
            lines.append(
                f"- {row.get('student_id') or 'Unknown'}"
                + (f" ({row.get('full_name')})" if row.get("full_name") else "")
            )
        return _line_join(lines)

    metrics = set(data.get("requested_metrics") or ["grade"])
    lines = [
        "ข้อมูลเฉพาะจากชั้นเรียนที่ผูกกับบัญชีของคุณ:"
        if thai else "Records from your assigned classes only:"
    ]
    for row in rows:
        details: List[str] = []
        if "grade" in metrics:
            details.append(
                f"grade {row.get('grade')}, score {_format_number(row.get('score'))}"
                if row.get("grade") is not None or row.get("score") is not None
                else "grade/score not recorded"
            )
        if "attendance" in metrics:
            details.append(
                f"attendance {_format_number(row.get('attendance_rate'))}%"
                if row.get("attendance_rate") is not None
                else "attendance not recorded"
            )
        if "assessments" in metrics:
            assessments = row.get("assessments") or []
            details.append(
                "assessments " + ", ".join(
                    f"{item.get('assessment_type')}: {_format_number(item.get('score'))}"
                    for item in assessments
                    if isinstance(item, dict)
                )
                if assessments else "assessments not recorded"
            )
        lines.append(
            f"- {row.get('student_id') or 'Unknown'}"
            + (f" ({row.get('full_name')})" if row.get("full_name") else "")
            + f" — {row.get('course_code') or '-'} {row.get('course_name') or ''}: "
            + ", ".join(details)
        )
    return _line_join(lines)


def _format_student_benchmark(data: Dict[str, Any], thai: bool) -> str:
    student = data.get("student") if isinstance(data.get("student"), dict) else None
    if not student:
        return "ไม่พบข้อมูลนักศึกษาสำหรับเปรียบเทียบ" if thai else "I could not find the authorized student record for this comparison."
    sid = student.get("student_id") or "Unknown"
    name = student.get("name") or ""
    gpa = student.get("gpa")
    average = data.get("population_average")
    difference = data.get("difference")
    relation = "equal to"
    try:
        if float(difference) > 0:
            relation = "above"
        elif float(difference) < 0:
            relation = "below"
    except (TypeError, ValueError):
        pass
    if thai:
        return _line_join([
            f"เปรียบเทียบ GPA ของ {sid}" + (f" ({name})" if name else "") + ":",
            f"- GPA นักศึกษา: {_format_number(gpa, 3)}",
            f"- GPA เฉลี่ยของนักศึกษาที่มองเห็นได้ {data.get('population_count') or 0} คน: {_format_number(average, 3)}",
            f"- ส่วนต่าง: {_format_number(difference, 3)}",
        ])
    return _line_join([
        f"GPA comparison for {sid}" + (f" ({name})" if name else "") + ":",
        f"- Student GPA: {_format_number(gpa, 3)}",
        f"- University average across {data.get('population_count') or 0} visible student records: {_format_number(average, 3)}",
        f"- Difference: {_format_number(difference, 3)} ({relation} average)",
    ])


def _format_student_rank_with_academic(data: Dict[str, Any], thai: bool) -> Optional[str]:
    if not isinstance(data, dict) or data.get("type") != "student_rank_with_academic":
        return None
    ranking = data.get("ranking") if isinstance(data.get("ranking"), dict) else {}
    academic = data.get("academic") if isinstance(data.get("academic"), dict) else {}
    lines = [_format_student_ranking(ranking, thai)]
    style_map = {
        "attendance": "attendance",
        "enrollments": "enrollments",
        "assessments": "assessments",
        "financial_accounts": "finance",
        "scholarship_awards": "scholarship",
        "support_cases": "support_cases",
        "profile": "summary",
    }
    for section in data.get("requested_sections") or []:
        rendered = _format_academic_records(academic, style_map.get(str(section), "summary"), thai)
        if rendered:
            lines.append(rendered)
    return "\n\n".join(value for value in lines if value)


def _format_student_risk_records(data: Dict[str, Any], thai: bool) -> Optional[str]:
    if not isinstance(data, dict) or data.get("type") != "student_risk_records":
        return None
    records = [row for row in (data.get("records") or []) if isinstance(row, dict)]
    if not records:
        return (
            "ไม่พบนักศึกษาที่มีระดับความเสี่ยงในขอบเขตข้อมูลนี้"
            if thai else "No currently at-risk students were found within this role's data scope."
        )
    lines = [
        f"นักศึกษาที่มีความเสี่ยง {len(records)} คน:"
        if thai else f"Currently at-risk students ({len(records)}):"
    ]
    for row in records:
        line = (
            f"- {row.get('student_id') or '-'} ({row.get('full_name') or '-'}) — "
            f"risk {row.get('risk_level') or '-'}, attendance {_format_number(row.get('attendance_rate'))}%"
        )
        if data.get("include_balance") and row.get("balance_due") is not None:
            line += f", balance due {_format_number(row.get('balance_due'))}"
        lines.append(line)
    denied = [str(value).replace("_", " ") for value in (data.get("denied_sections") or [])]
    if denied:
        lines.append(
            ("ไม่แสดงตามสิทธิ์: " if thai else "Not shown for this role: ") + ", ".join(denied)
        )
    return _line_join(lines)



def _format_student_study_search(data: Dict[str, Any], answer_style: str, thai: bool) -> str:
    term = data.get("study_term") or "the requested study term"
    count = int(data.get("count") or data.get("total_records") or 0)
    students = [r for r in (data.get("students") or []) if isinstance(r, dict)]
    truncated = bool(data.get("truncated"))
    ranking = data.get("ranking_applied") if isinstance(data.get("ranking_applied"), dict) else None
    rank_label = ranking.get("metric_label") if ranking else None
    rank_field = ranking.get("field") if ranking else None
    rank_direction = ranking.get("direction") if ranking else None

    if answer_style == "student_course_membership":
        matching_subjects = [
            item
            for row in students
            for item in (row.get("matching_subjects") or [])
            if isinstance(item, dict)
        ]
        if not matching_subjects:
            return (
                f"ไม่พบ {term} ในรายวิชาที่บันทึกไว้ของคุณ"
                if thai else
                f"No. {term} is not in your recorded studied subjects."
            )
        item = matching_subjects[0]
        subject = item.get("subject") or term
        grade = item.get("grade")
        if thai:
            return f"ใช่ {subject} อยู่ในรายวิชาที่บันทึกไว้ของคุณ" + (f" และเกรดที่บันทึกไว้คือ {grade}" if grade else "")
        return f"Yes. {subject} is in your recorded studied subjects." + (f" Your recorded grade is {grade}." if grade else "")

    if thai:
        if answer_style == "study_rank" and ranking:
            direction_text = "สูงสุด" if rank_direction == "desc" else "ต่ำสุด"
            lines = [f"พบนักศึกษาที่เรียน/เกี่ยวข้องกับ {term} ทั้งหมด {count} คน และจัดอันดับตาม {rank_label or rank_field or 'GPA'} {direction_text}"]
        else:
            lines = [f"พบนักศึกษาที่เรียน/เกี่ยวข้องกับ {term} ทั้งหมด {count} คน"]
        if answer_style == "study_count":
            return _line_join(lines)
        if students:
            lines.append("\nรายชื่อที่พบ:" if answer_style != "study_rank" else "\nอันดับที่พบ:")
            for idx, row in enumerate(students[:50], start=1):
                sid = row.get("student_id") or "Unknown"
                name = row.get("name") or ""
                program = row.get("program") or ""
                gpa = row.get("gpa")
                matches = []
                if row.get("matching_program"):
                    matches.append(f"program: {row.get('matching_program')}")
                for item in row.get("matching_subjects") or []:
                    if isinstance(item, dict) and item.get("subject"):
                        suffix = f" ({item.get('grade')})" if item.get("grade") else ""
                        matches.append(f"subject: {item.get('subject')}{suffix}")
                detail_parts = []
                if gpa is not None:
                    detail_parts.append(f"GPA: {gpa}")
                if matches:
                    detail_parts.append("; ".join(matches))
                elif program:
                    detail_parts.append(program)
                prefix = f"{idx}. " if answer_style == "study_rank" else "- "
                lines.append(prefix + f"{sid}" + (f" ({name})" if name else "") + (f" — {'; '.join(detail_parts)}" if detail_parts else ""))
            if truncated:
                lines.append(f"แสดงบางส่วน {len(students)} จากทั้งหมด {count} คน")
        return _line_join(lines)

    if answer_style == "study_rank" and ranking:
        direction_text = "highest" if rank_direction == "desc" else "lowest"
        lines = [f"I found {count} student(s) who study or match {term}. Ranked by {direction_text} {rank_label or rank_field or 'GPA'}:"]
    else:
        lines = [f"I found {count} student(s) who study or match {term}."]
    if answer_style == "study_count":
        return _line_join(lines)
    if students:
        lines.append("\nMatching students:" if answer_style != "study_rank" else "\nRanked students:")
        for idx, row in enumerate(students[:50], start=1):
            sid = row.get("student_id") or "Unknown"
            name = row.get("name") or ""
            program = row.get("program") or ""
            gpa = row.get("gpa")
            matches = []
            if row.get("matching_program"):
                matches.append(f"program: {row.get('matching_program')}")
            for item in row.get("matching_subjects") or []:
                if isinstance(item, dict) and item.get("subject"):
                    suffix = f" ({item.get('grade')})" if item.get("grade") else ""
                    matches.append(f"subject: {item.get('subject')}{suffix}")
            detail_parts = []
            if gpa is not None:
                detail_parts.append(f"GPA: {gpa}")
            if matches:
                detail_parts.append("; ".join(matches))
            elif program:
                detail_parts.append(program)
            prefix = f"{idx}. " if answer_style == "study_rank" else "- "
            lines.append(prefix + f"{sid}" + (f" ({name})" if name else "") + (f" — {'; '.join(detail_parts)}" if detail_parts else ""))
        if truncated:
            lines.append(f"Showing {len(students)} of {count} matching students.")
    return _line_join(lines)


def _format_student_subjects(data: Dict[str, Any], answer_style: str, thai: bool) -> Optional[str]:
    if data.get("type") != "student_subjects":
        return None
    subjects = [row for row in (data.get("subjects") or []) if isinstance(row, dict)]
    course_query = str(data.get("course_query") or "the requested course")
    if answer_style == "student_course_membership":
        if not subjects:
            return (
                f"ไม่พบ {course_query} ในรายวิชาที่ผูกกับบัญชีของคุณ"
                if thai else
                f"No. {course_query} is not in the subjects assigned to your account."
            )
        row = subjects[0]
        subject = row.get("subject_name") or course_query
        grade = row.get("grade")
        if thai:
            return f"ใช่ {subject} เป็นรายวิชาที่ผูกกับบัญชีของคุณ" + (f" และเกรดที่บันทึกไว้คือ {grade}" if grade else " แต่ยังไม่มีเกรดที่บันทึกไว้")
        return f"Yes. {subject} is assigned to your account." + (f" Your recorded grade is {grade}." if grade else " No grade is recorded yet.")

    if not subjects:
        return "ไม่พบรายวิชาที่ผูกกับบัญชีของคุณ" if thai else "No subjects are assigned to your account."
    lines = ["รายวิชาที่ผูกกับบัญชีของคุณ:" if thai else "Subjects assigned to your account:"]
    for row in subjects:
        code = row.get("subject_code") or "-"
        name = row.get("subject_name") or "Unknown subject"
        grade = row.get("grade")
        if thai:
            suffix = f" — เกรด {grade}" if grade else " — ยังไม่มีเกรด"
        else:
            suffix = f" — recorded grade {grade}" if grade else " — no grade recorded yet"
        lines.append(f"- {code} — {name}{suffix}")
    return _line_join(lines)


def _format_student_study_statistic(data: Dict[str, Any], thai: bool) -> str:
    """Format V10/V12 student study aggregate results safely.

    This function was accidentally missing after the cleanup/stability pass,
    causing runtime errors such as:
        name '_format_student_study_statistic' is not defined

    Expected payload type: student_study_term_aggregate.
    """
    term = data.get("study_term") or "the requested study term"
    statistic = str(data.get("statistic") or "count").lower()
    field = data.get("field") or data.get("metric_field") or "gpa"
    metric_label = data.get("metric_label") or str(field).upper()
    count = int(data.get("count") or data.get("total_records") or 0)
    value = data.get("value")
    values_used = data.get("values_used_count")
    students = [r for r in (data.get("students") or []) if isinstance(r, dict)]
    truncated = bool(data.get("truncated"))

    stat_label_en = {
        "median": "median",
        "average": "average",
        "maximum": "highest",
        "minimum": "lowest",
        "count": "count",
    }.get(statistic, statistic)
    stat_label_th = {
        "median": "ค่ามัธยฐาน",
        "average": "ค่าเฉลี่ย",
        "maximum": "ค่าสูงสุด",
        "minimum": "ค่าต่ำสุด",
        "count": "จำนวน",
    }.get(statistic, statistic)

    def _student_line(row: Dict[str, Any], idx: Optional[int] = None) -> str:
        sid = row.get("student_id") or "Unknown"
        name = row.get("name") or ""
        program = row.get("program") or ""
        gpa = row.get("gpa")
        matches = []
        if row.get("matching_program"):
            matches.append(f"program: {row.get('matching_program')}")
        for item in row.get("matching_subjects") or []:
            if isinstance(item, dict) and item.get("subject"):
                suffix = f" ({item.get('grade')})" if item.get("grade") else ""
                matches.append(f"subject: {item.get('subject')}{suffix}")
        details = []
        if gpa is not None:
            details.append(f"GPA: {gpa}")
        if program:
            details.append(f"program: {program}")
        if matches:
            details.append("; ".join(matches))
        prefix = f"{idx}. " if idx is not None else "- "
        return prefix + f"{sid}" + (f" ({name})" if name else "") + (f" — {'; '.join(details)}" if details else "")

    if thai:
        if count == 0:
            return f"ไม่พบนักศึกษาที่เรียน/เกี่ยวข้องกับ {term} จึงไม่สามารถคำนวณ {stat_label_th} ของ {metric_label} ได้"
        if statistic == "count":
            return f"พบนักศึกษาที่เรียนหรือมีข้อมูลตรงกับ {term} ทั้งหมด {count} คน"
        elif value is None:
            lines = [f"พบนักศึกษาที่เรียน/เกี่ยวข้องกับ {term} ทั้งหมด {count} คน แต่ไม่มีข้อมูล {metric_label} แบบตัวเลขเพียงพอสำหรับคำนวณ {stat_label_th}"]
        else:
            lines = [f"{stat_label_th}ของ {metric_label} สำหรับนักศึกษาที่เรียน/เกี่ยวข้องกับ {term} คือ {value} จากนักศึกษา {count} คน"]
            if values_used is not None and values_used != count:
                lines.append(f"ใช้ข้อมูลตัวเลขได้ {values_used} รายการจากทั้งหมด {count} คน")
        if students:
            heading = "\nนักศึกษาที่ใช้ประกอบการคำนวณ:" if statistic not in {"maximum", "minimum"} else "\nนักศึกษาที่ตรงกับเงื่อนไข:"
            lines.append(heading)
            for idx, row in enumerate(students[:50], start=1):
                lines.append(_student_line(row, idx if statistic in {"maximum", "minimum"} else None))
            if truncated:
                lines.append(f"แสดงบางส่วน {len(students)} จากทั้งหมด {count} คน")
        return _line_join(lines)

    if count == 0:
        return f"I could not find students who study or match {term}, so I cannot calculate the {stat_label_en} {metric_label}."
    
    # A count question should be concise. Do not print every matching student.
    if statistic == "count":
        return f"I found {count} student(s) who study or match {term}."
    elif value is None:
        lines = [f"I found {count} student(s) who study or match {term}, but there is not enough numeric {metric_label} data to calculate the {stat_label_en}."]
    else:
        lines = [f"The {stat_label_en} {metric_label} for students who study or match {term} is {value}, based on {count} matching student(s)."]
        if values_used is not None and values_used != count:
            lines.append(f"Numeric values used: {values_used} out of {count} matching student(s).")
    if students:
        if statistic in {"maximum", "minimum"}:
            lines.append("\nMatching students, ordered by the requested metric:")
            for idx, row in enumerate(students[:50], start=1):
                lines.append(_student_line(row, idx))
        else:
            lines.append("\nStudents included in the matched group:")
            for row in students[:50]:
                lines.append(_student_line(row))
        if truncated:
            lines.append(f"Showing {len(students)} of {count} matching student(s).")
    return _line_join(lines)



def _format_student_population_statistic(data: Dict[str, Any], thai: bool) -> str:
    """Format a university-wide count/median/average/min/max without implying a study term."""
    statistic = str(data.get("statistic") or "count").lower()
    metric = data.get("metric_label") or str(data.get("field") or "gpa").upper()
    count = int(data.get("count") or data.get("total_records") or 0)
    value = data.get("value")
    values_used = data.get("values_used_count")
    students = [row for row in (data.get("students") or []) if isinstance(row, dict)]
    extreme_count = data.get("extreme_count")
    truncated = bool(data.get("truncated"))
    labels_en = {"median": "median", "average": "average", "maximum": "highest", "minimum": "lowest", "count": "total number"}
    labels_th = {"median": "ค่ามัธยฐาน", "average": "ค่าเฉลี่ย", "maximum": "ค่าสูงสุด", "minimum": "ค่าต่ำสุด", "count": "จำนวนทั้งหมด"}
    if thai:
        if statistic == "count":
            return f"มหาวิทยาลัยมีนักศึกษาทั้งหมด {count} คน"
        if value is None:
            return f"พบนักศึกษาทั้งหมด {count} คน แต่มีข้อมูล {metric} แบบตัวเลขไม่เพียงพอสำหรับคำนวณ{labels_th.get(statistic, statistic)}"
        lines = [f"{labels_th.get(statistic, statistic)}ของ {metric} สำหรับนักศึกษาทั้งมหาวิทยาลัยคือ {value} จากนักศึกษา {count} คน"]
        if values_used is not None and values_used != count:
            lines.append(f"ใช้ข้อมูล {metric} แบบตัวเลขได้ {values_used} รายการ")
        if statistic in {"maximum", "minimum"} and students:
            lines.append("\nรายชื่อนักศึกษาที่อยู่ในผลลัพธ์:")
            for row in students[:20]:
                lines.append(f"- {row.get('student_id')} ({row.get('name') or '-'}) — GPA: {row.get('gpa', '-')}")
        return _line_join(lines)
    if statistic == "count":
        return f"There are {count} students in the university."
    if value is None:
        return f"I found {count} students in the university, but there is not enough numeric {metric} data to calculate the {labels_en.get(statistic, statistic)}."
    lines = [f"The {labels_en.get(statistic, statistic)} {metric} across all {count} students in the university is {value}."]
    if values_used is not None and values_used != count:
        lines.append(f"Numeric values used: {values_used}.")
    if statistic in {"maximum", "minimum"} and students:
        lines.append("\nStudents at the requested extreme:")
        for row in students[:20]:
            lines.append(f"- {row.get('student_id')} ({row.get('name') or '-'}) — GPA: {row.get('gpa', '-')}")
    if truncated:
        lines.append(f"Showing {len(students)} of {extreme_count or len(students)} students tied at this value.")
    return _line_join(lines)

def _format_student_filter_summary(data: Dict[str, Any], answer_style: str, thai: bool) -> str:
    count = int(data.get("count") or data.get("total_records") or 0)
    metric = data.get("metric_query") if isinstance(data.get("metric_query"), dict) else {}
    field = metric.get("field") or "gpa"
    op_text = metric.get("operator_text") or "matching"
    value = metric.get("value")
    students = [r for r in (data.get("students") or []) if isinstance(r, dict)]
    truncated = bool(data.get("truncated"))

    if thai:
        if value is not None:
            lines = [f"พบนักศึกษาที่มี {field.upper()} {op_text} {value} ทั้งหมด {count} คน"]
        else:
            lines = [f"พบนักศึกษาที่ตรงกับเงื่อนไขทั้งหมด {count} คน"]
        if answer_style == "aggregate_count":
            return _line_join(lines)
        if students:
            lines.append("\nรายชื่อที่พบ:")
            for row in students[:50]:
                sid = row.get("student_id") or "Unknown"
                name = row.get("name") or ""
                gpa = row.get("gpa", "-")
                program = row.get("program") or ""
                detail = f"GPA {gpa}"
                if program:
                    detail += f", {program}"
                lines.append(f"- {sid}" + (f" ({name})" if name else "") + f": {detail}")
            if truncated:
                lines.append(f"แสดงบางส่วน {len(students)} จากทั้งหมด {count} คน")
        return _line_join(lines)

    if value is not None:
        lines = [f"I found {count} student(s) with {field.upper()} {op_text} {value}."]
    else:
        lines = [f"I found {count} matching student(s)."]
    if answer_style == "aggregate_count":
        return _line_join(lines)
    if students:
        lines.append("\nMatching students:")
        for row in students[:50]:
            sid = row.get("student_id") or "Unknown"
            name = row.get("name") or ""
            gpa = row.get("gpa", "-")
            program = row.get("program") or ""
            detail = f"GPA {gpa}"
            if program:
                detail += f", {program}"
            lines.append(f"- {sid}" + (f" ({name})" if name else "") + f": {detail}")
        if truncated:
            lines.append(f"Showing {len(students)} of {count} matching students.")
    return _line_join(lines)


def _format_advisors(data: Any, thai: bool) -> Optional[str]:
    if isinstance(data, dict) and data.get("type") == "advisor_list":
        advisors = data.get("advisors") or []
    elif isinstance(data, list):
        advisors = data
    elif isinstance(data, dict) and data.get("advisor_id"):
        advisors = [data]
    else:
        return None
    if not advisors:
        return "ไม่พบข้อมูลอาจารย์" if thai else "I could not find advisor records."
    lines = [f"มีอาจารย์ทั้งหมด {len(advisors)} คน:" if thai else f"I found {len(advisors)} advisor(s):"]
    for row in advisors[:50]:
        if not isinstance(row, dict):
            continue
        parts = [str(row.get("advisor_id") or "Unknown")]
        if row.get("name"):
            parts.append(str(row.get("name")))
        if row.get("department"):
            parts.append(f"department: {row.get('department')}")
        lines.append("- " + " | ".join(parts))
    return _line_join(lines)


def _is_neural_pseudo_document(document: Dict[str, Any]) -> bool:
    """Identify retrieval-only rows so technical agent scores never leak into chat.

    The semantic index can return helpful chunks before full document rows. Those
    rows are valid retrieval evidence, but they are not user-facing document
    summaries and must not be selected over the original stored file.
    """
    if not isinstance(document, dict):
        return False
    summary = str(document.get("summary") or "").lower()
    terms = document.get("matched_terms") or []
    return (
        "neural data agent match" in summary
        or "neural_data_agent" in terms
        or bool((document.get("structured_preview") or {}).get("neural_agent_name"))
    )


def _safe_document_excerpt(document: Dict[str, Any]) -> str:
    text = str(document.get("text_excerpt") or document.get("text_preview") or "")
    text = " ".join(text.split())
    if not text:
        return ""
    # Keep a readable source passage, not agent metadata or a score.
    if len(text) > 700:
        text = text[:700].rsplit(" ", 1)[0] + "…"
    return text


def _format_documents(data: Any, thai: bool, message: str) -> Optional[str]:
    """Return a grounded file explanation without asking the general chat model.

    Stored document facts live in summary, conclusion_table and extracted text.
    A document can therefore be explained even where filename term matching is weak.
    """
    operation = None
    if isinstance(data, dict) and "data" in data:
        operation = data.get("operation")
        docs = data.get("data") or []
    elif isinstance(data, list):
        docs = data
    else:
        return None
    docs = [d for d in docs if isinstance(d, dict)]
    if not docs:
        return "ยังไม่มีไฟล์ PDF/Excel ที่ตรงกับคำถามนี้" if thai else "I could not find an uploaded PDF/Excel file matching that question."

    # Prefer the actual stored document record. Retrieval-only pseudo rows may
    # have a higher semantic score, but selecting them exposed technical text such
    # as "neural data agent match" instead of a useful explanation.
    actual_docs = [d for d in docs if not _is_neural_pseudo_document(d)]
    display_docs = actual_docs or docs

    lower_message = (message or "").lower()
    if any(term in lower_message for term in ("compare", "versus", "difference between")):
        if len(display_docs) < 2:
            return (
                f"การเปรียบเทียบต้องมีอย่างน้อย 2 ไฟล์ แต่ในขอบเขตสิทธิ์นี้พบเพียง {len(display_docs)} ไฟล์"
                if thai else
                f"A document comparison requires at least 2 accessible files, but only {len(display_docs)} is currently available."
            )
        lines = ["เปรียบเทียบเอกสารที่เข้าถึงได้:" if thai else "Comparison of accessible documents:"]
        for document in display_docs[:8]:
            table = document.get("conclusion_table") if isinstance(document.get("conclusion_table"), dict) else {}
            summary = table.get("short_summary") or table.get("clear_conclusion") or document.get("summary") or document.get("text_excerpt") or ""
            lines.append(f"- {document.get('filename') or 'file'}: {' '.join(str(summary).split())[:500] or 'No readable summary'}")
        return _line_join(lines)
    if any(term in lower_message for term in ("summarize every", "summarize all", "together")):
        lines = ["สรุปชุดเอกสารที่เข้าถึงได้:" if thai else "Combined accessible document summary:"]
        for document in display_docs[:20]:
            table = document.get("conclusion_table") if isinstance(document.get("conclusion_table"), dict) else {}
            summary = table.get("short_summary") or table.get("clear_conclusion") or document.get("summary") or document.get("text_excerpt") or ""
            lines.append(f"- {document.get('filename') or 'file'}: {' '.join(str(summary).split())[:500] or 'No readable summary'}")
        return _line_join(lines)
    list_only = operation == "list_documents" or any(w in lower_message for w in ["list", "what files", "all files", "uploaded files", "มีไฟล์", "รายชื่อไฟล์"])
    if list_only:
        lines = [f"พบไฟล์ทั้งหมด {len(display_docs)} ไฟล์:" if thai else f"I found {len(display_docs)} uploaded file(s):"]
        for d in display_docs[:50]:
            lines.append(f"- ID {d.get('id')}: {d.get('filename')} ({d.get('source_type') or 'file'} → {d.get('storage_target') or 'store'})")
        return _line_join(lines)

    # A pinned workspace document has match_score 9999. Otherwise choose the best
    # actual document, never a retrieval-only pseudo row when a full record exists.
    best = max(display_docs, key=lambda item: float(item.get("match_score") or 0))

    # If only a retrieval chunk is available, present it as a source excerpt and
    # never show agent names, embedding scores, or internal retrieval metadata.
    if _is_neural_pseudo_document(best) and not actual_docs:
        filename = best.get("filename") or "the uploaded file"
        excerpt = _safe_document_excerpt(best)
        if thai:
            return (
                f"พบข้อความที่เกี่ยวข้องในไฟล์ “{filename}” ดังนี้:\n"
                f"{excerpt or 'ยังไม่มีข้อความที่อ่านได้เพียงพอ'}\n\n"
                "ข้อความนี้มาจากส่วนที่ค้นพบในไฟล์ ไม่ใช่สรุปทั้งไฟล์ค่ะ"
            )
        return (
            f"I found a relevant passage in “{filename}”:\n"
            f"{excerpt or 'There is not enough readable text in the matched section yet.'}\n\n"
            "This is a matched source passage, not a summary of the whole file."
        )

    # V21: When a user asks a focused question from a selected/open document,
    # answer from the exact stored text before falling back to a generic overview.
    # This prevents a question such as “What is torts?” from replying that a
    # summary was not found even though the selected PDF contains the term.
    grounded_excerpt_answer = answer_from_selected_document(best, message, "th" if thai else "en")
    if grounded_excerpt_answer:
        return grounded_excerpt_answer

    filename = best.get("filename") or "uploaded file"
    table = best.get("conclusion_table") if isinstance(best.get("conclusion_table"), dict) else {}
    profile = table.get("data_profile") if isinstance(table.get("data_profile"), dict) else {}
    source_type = str(best.get("source_type") or profile.get("source_type") or "file").upper()
    summary = (
        table.get("short_summary")
        or profile.get("summary")
        or table.get("clear_conclusion")
        or best.get("summary")
        or ""
    )
    topic = table.get("main_topic") or profile.get("main_topic") or ""
    excerpt = best.get("text_excerpt") or best.get("text_preview") or ""
    if not summary:
        summary = " ".join(str(excerpt).split())[:1200]

    key_points = []
    for key in ("key_points", "section_notes", "detailed_information"):
        values = table.get(key) or []
        if isinstance(values, list):
            for value in values:
                clean = " ".join(str(value).split())
                if clean and clean not in key_points:
                    key_points.append(clean[:280] + ("…" if len(clean) > 280 else ""))
                if len(key_points) >= 4:
                    break
        if len(key_points) >= 4:
            break

    structured = best.get("structured_preview") or {}
    if thai:
        lines = [f"ไฟล์ {source_type} “{filename}” เกี่ยวกับอะไร:"]
        lines.append(summary or "พบไฟล์นี้ในระบบ แต่ยังไม่มีข้อความที่อ่านได้เพียงพอสำหรับสรุปค่ะ")
        if topic:
            lines.append(f"\nหัวข้อหลัก: {topic}")
        if key_points:
            lines.append("\nประเด็นสำคัญ:")
            lines.extend(f"- {point}" for point in key_points)
        if isinstance(structured, dict) and structured.get("total_pages"):
            lines.append(f"\nไฟล์นี้มีประมาณ {structured.get('total_pages')} หน้า")
        lines.append("\nคำตอบนี้อ้างอิงจากข้อความที่เก็บจากไฟล์โดยตรง ส่วน Reading guide เป็นโน้ตที่จัดจากข้อความที่ extract ได้เพื่อช่วยอ่านง่าย ไม่ใช่ข้อมูลต้นฉบับแทนไฟล์ค่ะ")
        return _line_join(lines)

    lines = [f"About the {source_type} file \"{filename}\":"]
    lines.append(summary or "The file is stored, but there is not enough readable extracted text to summarize it yet.")
    if topic:
        lines.append(f"\nMain topic: {topic}")
    if key_points:
        lines.append("\nKey points:")
        lines.extend(f"- {point}" for point in key_points)
    if isinstance(structured, dict) and structured.get("total_pages"):
        lines.append(f"\nThis file has about {structured.get('total_pages')} page(s).")
    lines.append("\nThis answer is grounded in stored extracted file content. Reading guide is organized from extracted content; use Data table for original stored rows/chunks.")
    return _line_join(lines)


def _format_large_result(data: Dict[str, Any], thai: bool) -> Optional[str]:
    if not isinstance(data, dict) or data.get("type") != "large_result_with_report":
        return None
    total = data.get("total_records")
    preview = data.get("preview_rows") or []
    report = data.get("report") or {}
    lines = [f"พบข้อมูลทั้งหมด {total} รายการ แสดงตัวอย่างบางส่วนด้านล่าง" if thai else f"I found {total} records. Here are the first few:"]
    for row in preview[:10]:
        if isinstance(row, dict):
            lines.append("- " + ", ".join(f"{k}: {v}" for k, v in list(row.items())[:6]))
    if report.get("download_url"):
        lines.append((f"ดาวน์โหลดรายงานฉบับเต็ม: {report.get('download_url')}" if thai else f"Full report: {report.get('download_url')}"))
    return _line_join(lines)


def _format_number(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value if value is not None else "-")
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.{digits}f}".rstrip("0").rstrip(".")


def _format_academic_records(data: Dict[str, Any], answer_style: str, thai: bool) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    result_type = str(data.get("type") or "")

    if result_type == "student_academic_profiles":
        rendered = [
            _format_academic_records(row, answer_style, thai)
            for row in (data.get("records") or [])
            if isinstance(row, dict)
        ]
        rendered = [value for value in rendered if value]
        return "\n\n".join(rendered) if rendered else (
            "ไม่พบข้อมูลวิชาการของนักศึกษาที่ร้องขอ"
            if thai else "No requested academic records were available."
        )

    if result_type == "course_catalog":
        rows = [row for row in (data.get("courses") or []) if isinstance(row, dict)]
        if not rows:
            return "ไม่พบรายวิชาในแคตตาล็อกที่ตรงกับคำถาม" if thai else "I could not find matching courses in the formal course catalog."
        lines = [f"พบ {len(rows)} รายวิชาในแคตตาล็อก:" if thai else f"Formal course catalog ({len(rows)} course(s)):"]
        for row in rows:
            code = row.get("course_code") or "-"
            name = row.get("course_name") or "-"
            program = row.get("program_name") or row.get("program_code") or "-"
            credits = _format_number(row.get("credits"))
            level = row.get("course_level") or "-"
            lines.append(f"- {code}: {name} — {credits} credits, {program}, level {level}")
        return _line_join(lines)

    if result_type == "academic_overview":
        totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
        lines = ["ภาพรวมข้อมูลวิชาการ:" if thai else "Academic dataset overview:"]
        labels = [
            ("student_count", "นักศึกษา" if thai else "Students"),
            ("advisor_count", "อาจารย์ที่ปรึกษา" if thai else "Advisors"),
            ("program_count", "หลักสูตร" if thai else "Programs"),
            ("course_count", "รายวิชา" if thai else "Courses"),
            ("enrollment_count", "การลงทะเบียน" if thai else "Enrollments"),
            ("assessment_count", "ผลการประเมิน" if thai else "Assessment results"),
            ("attendance_summary_count", "สรุปการเข้าเรียน" if thai else "Attendance summaries"),
        ]
        lines.extend(f"- {label}: {_format_number(totals.get(key))}" for key, label in labels)
        risk_rows = [row for row in (data.get("risk_summary") or []) if isinstance(row, dict)]
        if risk_rows:
            lines.append("\nสรุประดับความเสี่ยง:" if thai else "\nRisk-level totals:")
            lines.extend(f"- {row.get('risk_level') or '-'}: {_format_number(row.get('student_count'))}" for row in risk_rows)
        return _line_join(lines)

    if result_type == "academic_risk_summary":
        rows = [row for row in (data.get("rows") or []) if isinstance(row, dict)]
        if not rows:
            return "ไม่พบข้อมูลสรุปความเสี่ยงทางการเรียน" if thai else "No academic-risk summary records were found."
        lines = ["สรุปความเสี่ยงทางการเรียนตามหลักสูตร:" if thai else "Academic risk summary by program:"]
        for row in rows:
            lines.append(
                f"- {row.get('program_name') or '-'} / {row.get('risk_level') or '-'}: "
                f"{_format_number(row.get('student_count'))} student(s), "
                f"average GPA {_format_number(row.get('average_gpa'))}, "
                f"average attendance {_format_number(row.get('average_attendance_rate'))}%"
            )
        return _line_join(lines)

    if result_type != "student_academic_profile":
        return None

    student_id = data.get("student_id") or ((data.get("profile") or {}).get("student_id") if isinstance(data.get("profile"), dict) else None) or "Unknown"
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else None
    if not profile:
        return f"ไม่พบข้อมูลวิชาการของนักศึกษา {student_id}" if thai else f"I could not find normalized academic records for {student_id}."
    name = profile.get("full_name") or profile.get("name") or ""
    identity = f"{student_id}" + (f" ({name})" if name else "")

    if answer_style == "attendance":
        rows = [row for row in (data.get("attendance") or []) if isinstance(row, dict)]
        if not rows:
            return f"ไม่พบสรุปการเข้าเรียนของ {identity}" if thai else f"No attendance summaries were found for {identity}."
        lines = [f"การเข้าเรียนของ {identity}:" if thai else f"Attendance for {identity}:"]
        for row in rows:
            lines.append(
                f"- {row.get('term_code') or '-'} / {row.get('course_code') or '-'}: "
                f"{_format_number(row.get('attendance_rate'))}% "
                f"({_format_number(row.get('classes_attended'))}/{_format_number(row.get('classes_scheduled'))} classes)"
            )
        return _line_join(lines)

    if answer_style == "enrollments":
        rows = [row for row in (data.get("enrollments") or []) if isinstance(row, dict)]
        if not rows:
            return f"ไม่พบข้อมูลการลงทะเบียนของ {identity}" if thai else f"No enrollment records were found for {identity}."
        lines = [f"รายวิชาที่ลงทะเบียนของ {identity}:" if thai else f"Enrollments for {identity}:"]
        for row in rows:
            lines.append(
                f"- {row.get('term_code') or '-'} / {row.get('course_code') or '-'} "
                f"{row.get('course_name') or ''}: {row.get('enrollment_status') or '-'}, "
                f"{_format_number(row.get('credits'))} credits"
                + (f", grade {row.get('grade')}" if row.get("grade") is not None else "")
            )
        return _line_join(lines)

    if answer_style == "assessments":
        rows = [row for row in (data.get("assessments") or []) if isinstance(row, dict)]
        if not rows:
            return f"ไม่พบผลการประเมินของ {identity}" if thai else f"No assessment results were found for {identity}."
        lines = [f"ผลการประเมินของ {identity}:" if thai else f"Assessment results for {identity}:"]
        for row in rows:
            lines.append(
                f"- {row.get('term_code') or '-'} / {row.get('course_code') or '-'} / "
                f"{row.get('assessment_type') or '-'}: score {_format_number(row.get('score'))}, "
                f"weight {_format_number(row.get('weight_percent'))}%"
            )
        return _line_join(lines)

    if answer_style == "finance":
        rows = [row for row in (data.get("financial_accounts") or []) if isinstance(row, dict)]
        if not rows:
            return f"ไม่พบบัญชีค่าเล่าเรียนของ {identity}" if thai else f"No financial-account records were found for {identity}."
        lines = [f"บัญชีค่าเล่าเรียนของ {identity}:" if thai else f"Financial account for {identity}:"]
        for row in rows:
            lines.append(
                f"- {row.get('term_code') or '-'}: due {_format_number(row.get('tuition_due'))}, "
                f"paid {_format_number(row.get('amount_paid'))}, "
                f"balance {_format_number(row.get('balance_due'))}, "
                f"status {row.get('payment_status') or '-'}"
            )
        return _line_join(lines)

    if answer_style == "scholarship":
        rows = [row for row in (data.get("scholarship_awards") or []) if isinstance(row, dict)]
        if not rows:
            return f"ไม่พบข้อมูลทุนการศึกษาของ {identity}" if thai else f"No scholarship awards were found for {identity}."
        lines = [f"ทุนการศึกษาของ {identity}:" if thai else f"Scholarships for {identity}:"]
        lines.extend(
            f"- {row.get('term_code') or '-'}: {row.get('scholarship_name') or '-'}, "
            f"amount {_format_number(row.get('amount'))}, status {row.get('status') or '-'}"
            for row in rows
        )
        return _line_join(lines)

    if answer_style == "support_cases":
        rows = [row for row in (data.get("support_cases") or []) if isinstance(row, dict)]
        if not rows:
            return f"ไม่พบเคสช่วยเหลือของ {identity}" if thai else f"No support cases were found for {identity}."
        lines = [f"เคสช่วยเหลือของ {identity}:" if thai else f"Support cases for {identity}:"]
        lines.extend(
            f"- {row.get('case_type') or '-'}: {row.get('status') or '-'}, "
            f"priority {row.get('priority') or '-'}, advisor {row.get('assigned_advisor_id') or '-'} — "
            f"{row.get('summary') or '-'}"
            for row in rows
        )
        return _line_join(lines)

    if answer_style == "academic_risk":
        return _line_join([
            f"ความเสี่ยงทางการเรียนของ {identity}:" if thai else f"Academic risk for {identity}:",
            f"- Risk level: {profile.get('risk_level') or '-'}",
            f"- Academic status: {profile.get('academic_status') or '-'}",
            f"- GPA: {_format_number(profile.get('gpa'))}",
            f"- Attendance rate: {_format_number(profile.get('attendance_rate'))}%",
        ])

    if answer_style == "graduation_progress":
        earned = profile.get("credits_earned")
        required = profile.get("credits_required")
        try:
            remaining = max(float(required) - float(earned), 0)
            progress = (float(earned) / float(required) * 100) if float(required) else 0
        except (TypeError, ValueError, ZeroDivisionError):
            remaining = None
            progress = None
        lines = [f"ความคืบหน้าการจบของ {identity}:" if thai else f"Graduation progress for {identity}:"]
        lines.extend([
            f"- Credits earned: {_format_number(earned)}",
            f"- Credits required: {_format_number(required)}",
            f"- Credits remaining: {_format_number(remaining)}",
            f"- Progress: {_format_number(progress)}%",
            f"- Expected graduation year: {profile.get('expected_graduation_year') or '-'}",
        ])
        return _line_join(lines)

    return _line_join([
        f"ข้อมูลวิชาการของ {identity}:" if thai else f"Academic record for {identity}:",
        f"- Program: {profile.get('program_name') or profile.get('program_code') or '-'}",
        f"- Year level: {profile.get('year_level') or '-'}",
        f"- Academic status: {profile.get('academic_status') or '-'}",
        f"- GPA: {_format_number(profile.get('gpa'))}",
        f"- Attendance rate: {_format_number(profile.get('attendance_rate'))}%",
        f"- Credits: {_format_number(profile.get('credits_earned'))}/{_format_number(profile.get('credits_required'))}",
        f"- Risk level: {profile.get('risk_level') or '-'}",
        f"- Scholarship status: {profile.get('scholarship_status') or '-'}",
    ])


def _format_student_combined_record(data: Dict[str, Any], thai: bool) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    if data.get("type") == "student_combined_records":
        academic_by_id = {
            str(row.get("student_id") or "").upper(): row
            for row in (data.get("academic_records") or [])
            if isinstance(row, dict)
        }
        master_by_id = {
            str(row.get("student_id") or "").upper(): row
            for row in (data.get("student_master_records") or [])
            if isinstance(row, dict)
        }
        answers: List[str] = []
        for student_id in data.get("student_ids") or []:
            student_id = str(student_id).upper()
            single = {
                "type": "student_combined_record",
                "student_id": student_id,
                "academic": academic_by_id.get(student_id),
                "student_master": master_by_id.get(student_id),
                "student_master_sections": data.get("student_master_sections") or [],
                "requested_sections": data.get("requested_sections") or [],
                "requested_section_styles": data.get("requested_section_styles") or {},
                "denied_sections": data.get("denied_sections") or [],
            }
            rendered = _format_student_combined_record(single, thai)
            if rendered:
                answers.append(rendered)
        return "\n\n".join(answers) if answers else (
            "ไม่พบข้อมูลของนักศึกษาที่ร้องขอ" if thai else "No requested student records were available."
        )
    if data.get("type") != "student_combined_record":
        return None

    student_id = str(data.get("student_id") or "Unknown")
    master = data.get("student_master")
    master_sections = [str(value) for value in (data.get("student_master_sections") or [])]
    academic = data.get("academic") if isinstance(data.get("academic"), dict) else None
    requested_sections = [str(value) for value in (data.get("requested_sections") or [])]
    section_styles = data.get("requested_section_styles") if isinstance(data.get("requested_section_styles"), dict) else {}
    denied_sections = [str(value).replace("_", " ") for value in (data.get("denied_sections") or [])]

    lines = [
        f"ข้อมูลที่ได้รับอนุญาตหลายส่วนของ {student_id}:"
        if thai else f"Combined authorized record for {student_id}:"
    ]

    if master_sections:
        if master is None:
            lines.append(
                "- ยังไม่สามารถอ่านส่วนโปรไฟล์/GPA/เกรดได้"
                if thai else "- The requested profile/GPA/grade section is currently unavailable."
            )
        else:
            if "profile" in master_sections:
                master_style = "profile"
            elif "gpa" in master_sections and "grades" in master_sections:
                master_style = "student_multi"
            elif "gpa" in master_sections:
                master_style = "gpa"
            else:
                master_style = "grades"
            master_text = _format_students(master, master_style, thai)
            if master_text:
                lines.append(master_text)

    rendered_styles = set()
    for section in requested_sections:
        style = str(section_styles.get(section) or {
            "attendance": "attendance",
            "enrollments": "enrollments",
            "assessments": "assessments",
            "financial_accounts": "finance",
            "scholarship_awards": "scholarship",
            "support_cases": "support_cases",
            "profile": "summary",
        }.get(section) or "summary")
        # Graduation progress deliberately uses profile + enrollments as one
        # calculation, so rendering that style twice would duplicate the answer.
        if style in rendered_styles:
            continue
        rendered_styles.add(style)
        section_text = _format_academic_records(academic or {}, style, thai)
        if section_text:
            lines.append(section_text)

    if denied_sections:
        denied = ", ".join(denied_sections)
        lines.append(
            f"ส่วนที่ไม่แสดงตามสิทธิ์ของบัญชี: {denied}"
            if thai else f"Not shown for this role: {denied}."
        )
    return _line_join(lines)


def deterministic_database_answer(user_message: str, language: str, plan: Dict[str, Any], tool_result: Dict[str, Any]) -> Optional[str]:
    thai = _lang_is_thai(language, user_message)
    if not isinstance(tool_result, dict):
        return None
    if tool_result.get("success") is False:
        return safe_failure_message(plan, tool_result, language, user_message)
    data = _unwrap_data(tool_result)
    answer_style = str((plan.get("arguments") or {}).get("answer_style") or "summary")

    # Broad university summaries must use the canonical MongoDB student/advisor
    # counts. PostgreSQL relationship rows (for example student_subjects) are
    # supporting data and must never be described as the student population.
    if isinstance(data, dict) and isinstance(data.get("admin_university_context"), dict):
        return format_authoritative_university_overview(data.get("admin_university_context") or {}, language)

    if isinstance(data, dict):
        student_subjects = _format_student_subjects(data, answer_style, thai)
        if student_subjects:
            return student_subjects
        advisor_classroom = _format_advisor_classroom(data, thai)
        if advisor_classroom:
            return advisor_classroom
        risk_records = _format_student_risk_records(data, thai)
        if risk_records:
            return risk_records
        ranked_academic = _format_student_rank_with_academic(data, thai)
        if ranked_academic:
            return ranked_academic
        if data.get("type") == "group_analytics":
            return _format_group_analytics(data, thai)
        if data.get("type") == "student_benchmark":
            return _format_student_benchmark(data, thai)
        combined = _format_student_combined_record(data, thai)
        if combined:
            return combined
        academic = _format_academic_records(data, answer_style, thai)
        if academic:
            return academic
        large = _format_large_result(data, thai)
        if large:
            return large
        if data.get("type") == "subject_summary" or "unique_subject_count" in data:
            return _format_subject_summary(data, thai, plan.get("arguments") or {}, str(plan.get("user_role") or "admin"))

    tool = plan.get("tool_name")
    if tool == "mongodb_student_tool":
        return _format_students(data, answer_style, thai)
    if tool == "mongodb_advisor_tool":
        return _format_advisors(data, thai)
    if tool == "postgres_university_tool":
        return _format_documents(data, thai, user_message)
    return None




def _naturalize_database_answer(user_message: str, language: str, user_role: str, plan: Dict[str, Any], factual_answer: str) -> Optional[str]:
    """Use the LLM only to rewrite verified facts in a more natural style.

    The model receives the already-validated deterministic answer as the only
    factual source. It must not add data, IDs, grades, or counts that are not in
    that fact block. This keeps database accuracy while making the chat feel less
    fixed/robotic.
    """
    if not factual_answer or os.getenv("AI_NATURALIZE_DATABASE_ANSWERS", "false").lower() in {"0", "false", "no"}:
        return None
    # Do not spend extra tokens rewriting very large reports.
    if len(factual_answer) > 5000:
        return None
    system = """
You are the final response writer for a university database AI.
Rewrite the verified database facts naturally and directly.
Do NOT add, guess, infer, or change any facts.
Do NOT introduce student IDs, grades, counts, names, files, or private fields not present in VERIFIED_FACTS.
If the verified facts say something was not found, say that clearly.
Keep the same language as the user.
""".strip()
    prompt = f"""
User question:
{user_message}

Role:
{user_role}

Tool/purpose metadata:
{json.dumps({
    'tool': plan.get('tool_name'),
    'arguments': plan.get('arguments', {}),
    'purpose_analysis': plan.get('purpose_analysis'),
    'validation': plan.get('orchestrator_validation'),
}, ensure_ascii=False, default=str)[:3000]}

VERIFIED_FACTS:
{factual_answer}

Write the final answer using only VERIFIED_FACTS.
""".strip()
    try:
        text = ai_generate_text(
            system_prompt=system,
            prompt=prompt,
            timeout_env="GEMINI_TIMEOUT",
            default_timeout=120,
            temperature=0.1,
            max_output_tokens=1600,
        )
        if text and text.strip():
            return text.strip()
    except Exception:
        return None
    return None


def write_final_answer(user_message: str, language: str, user_role: str, plan: Dict[str, Any], tool_result: Dict[str, Any], chat_history: Optional[List[Dict[str, Any]]] = None) -> str:
    orchestrator_validation = plan.get("orchestrator_validation") or {}
    if orchestrator_validation and orchestrator_validation.get("is_valid") is False:
        return safe_failure_message(plan, tool_result, language, user_message, validation_failed=True)

    args = plan.get("arguments") or {}
    if plan.get("tool_name") == "none" and args.get("reason") == "academic_student_id_required":
        if _lang_is_thai(language, user_message):
            return "โปรดระบุรหัสนักศึกษา เช่น S001 เพื่อดูข้อมูลการเข้าเรียน การลงทะเบียน การเงิน ทุน หรือความเสี่ยงที่ได้รับอนุญาต"
        return "Please include a student ID such as S001 so I can retrieve the permitted attendance, enrollment, finance, scholarship, or risk record."
    if plan.get("tool_name") == "none" and args.get("reason") == "benchmark_student_id_required":
        if _lang_is_thai(language, user_message):
            return "โปรดระบุรหัสนักศึกษาเพื่อเปรียบเทียบกับค่าเฉลี่ยรวม เช่น S001"
        return "Please include a student ID such as S001 for the comparison with the university average."
    if plan.get("tool_name") == "none" and args.get("reason") == "unsupported_realtime":
        if _lang_is_thai(language, user_message):
            return "ระบบไม่มีข้อมูลกิจกรรมหรือตำแหน่งแบบเรียลไทม์ ต้องการดูโปรไฟล์ GPA เกรด หรือข้อมูลที่บันทึกไว้ของนักศึกษาแทนไหม"
        return "I do not have live activity or location data. Would you like the stored student profile, GPA, grades, or attendance data instead?"
    if plan.get("tool_name") == "none" and args.get("reason") == "student_ranking_not_available_for_role":
        if _lang_is_thai(language, user_message):
            return "การจัดอันดับ GPA ของนักศึกษาทั้งมหาวิทยาลัยจำกัดไว้สำหรับผู้ดูแลระบบ คุณยังถามข้อมูลของตนเองหรือข้อมูลในขอบเขตการสอนที่ได้รับอนุญาตได้"
        return "University-wide student GPA rankings are limited to administrators. You can still ask for your own record or records within your assigned teaching scope."
    if plan.get("tool_name") == "none" and args.get("reason") == "student_other_record_denied":
        if _lang_is_thai(language, user_message):
            return "คุณดูได้เฉพาะข้อมูลนักศึกษาของตนเองที่ผูกกับบัญชีนี้"
        return "You can only access the student record linked to your own signed-in account."
    if plan.get("tool_name") == "none" and args.get("reason") == "student_signed_identity_required":
        if _lang_is_thai(language, user_message):
            return "ต้องเข้าสู่ระบบด้วยบัญชีนักศึกษาที่ตรวจสอบแล้วก่อนเข้าถึงข้อมูลนักศึกษา"
        return "A verified student login is required before student data can be accessed."
    if plan.get("tool_name") == "none" and args.get("reason") == "student_own_scope_only":
        if _lang_is_thai(language, user_message):
            return (
                "บัญชีนักศึกษาดูได้เฉพาะข้อมูลของตนเองและข้อมูลรายวิชาที่ตนลงทะเบียน "
                "ไม่สามารถดูรายชื่อนักศึกษาคนอื่น จำนวนรวม การจัดอันดับ ค่าเฉลี่ยรวม "
                "หรือการเปรียบเทียบกับนักศึกษาทั้งมหาวิทยาลัยได้"
            )
        return (
            "Student accounts can access only their own record and their enrolled-course information. "
            "They cannot access other students, university-wide student lists or counts, rankings, "
            "population averages, or university-wide comparisons."
        )
    if plan.get("tool_name") == "none" and args.get("reason") == "academic_sections_not_available_for_role":
        denied = ", ".join(str(value).replace("_", " ") for value in (args.get("denied_sections") or []))
        if _lang_is_thai(language, user_message):
            return f"บัญชีของคุณไม่มีสิทธิ์เข้าถึงส่วนข้อมูลนี้: {denied or 'ข้อมูลที่ร้องขอ'}"
        return f"Your role cannot access the requested academic section(s): {denied or 'requested data'}."
    if plan.get("tool_name") == "none" and args.get("reason") == "advisor_classroom_scope_only":
        denied = ", ".join(str(value) for value in (args.get("denied_fields") or []))
        if _lang_is_thai(language, user_message):
            return (
                f"บัญชีอาจารย์ไม่สามารถดู {denied or 'ข้อมูลนักศึกษาส่วนกลาง'} ได้ "
                "คุณสามารถถามได้เฉพาะรายชื่อนักศึกษาและเกรด คะแนน การเข้าเรียน หรือผลการประเมินจากชั้นเรียนที่ผูกกับบัญชีของคุณ"
            )
        role_label = "Lecturer" if str(plan.get("user_role") or "") == "lecturer" else "Advisor"
        return (
            f"{role_label} accounts cannot access {denied or 'university-wide student information'}. "
            "You may ask only for enrolled student identity and grade, score, attendance, or assessment facts "
            "from classes assigned to your teaching account."
        )
    if plan.get("tool_name") == "none" and args.get("answer_style") == "capability_limitation":
        limitation = args.get("capability_limitation") if isinstance(args.get("capability_limitation"), dict) else {}
        missing = ", ".join(str(value) for value in (limitation.get("missing_data") or []))
        alternative = str(limitation.get("available_alternative") or "currently stored records")
        if _lang_is_thai(language, user_message):
            return (
                f"ฐานข้อมูลปัจจุบันยังตอบคำถามนี้อย่างน่าเชื่อถือไม่ได้ เพราะไม่มี {missing or 'ข้อมูลที่จำเป็น'} "
                f"ระบบจะไม่เดาคำตอบ แต่สามารถแสดง {alternative} ได้"
            )
        return (
            f"I cannot answer this reliably from the current databases because they do not contain "
            f"{missing or 'the required evidence'}. I will not guess; I can show {alternative} instead."
        )

    # For protected/university database facts, first build an exact answer from
    # real allowed data. Then optionally ask the AI to rewrite only those verified
    # facts so the response feels natural instead of hard-coded.
    deterministic = deterministic_database_answer(user_message, language, plan, tool_result)
    if deterministic:
        data = _unwrap_data(tool_result) if isinstance(tool_result, dict) else None
        if isinstance(data, dict) and isinstance(data.get("admin_university_context"), dict):
            return deterministic
        if args.get("answer_style") in {
            "attendance", "enrollments", "assessments", "finance", "scholarship", "support_cases",
            "academic_risk", "academic_risk_summary", "graduation_progress",
            "course_catalog", "academic_overview", "academic_multi", "student_multi", "student_rank",
            "group_analytics", "student_benchmark",
            "advisor_class_count", "advisor_class_list", "advisor_class_roster",
            "advisor_class_records", "advisor_class_summary",
        }:
            return deterministic
        # File answers must remain verbatim/structured from stored content. A
        # second AI rewrite can discard the overview or make a source excerpt look
        # like the whole document.
        if plan.get("tool_name") == "postgres_university_tool" and (args.get("pinned_document") or args.get("answer_style") == "document_explanation"):
            return deterministic
        if args.get("answer_style") in {"count", "aggregate_count", "study_count"}:
            return deterministic
        naturalized = _naturalize_database_answer(user_message, language, user_role, plan, deterministic)
        return naturalized or deterministic

    # For normal chat or nuanced document explanations, use the existing final generator.
    try:
        return generate_final_answer(
            user_message=user_message,
            language=language,
            user_role=user_role,
            plan=plan,
            tool_result=tool_result,
            chat_history=chat_history,
        )
    except Exception:
        # Last fallback: ask the model directly for normal chat.
        try:
            return ai_generate_text(
                prompt=user_message,
                system_prompt="You are a helpful university AI assistant. Answer naturally and concisely.",
                timeout_env="GEMINI_TIMEOUT",
                default_timeout=120,
                temperature=0.2,
                max_output_tokens=1024,
            )
        except Exception:
            thai = _lang_is_thai(language, user_message)
            return "ตอนนี้ระบบยังสร้างคำตอบทั่วไปไม่ได้ ลองใหม่อีกครั้งค่ะ" if thai else "I cannot generate a general answer right now. Please try again."
