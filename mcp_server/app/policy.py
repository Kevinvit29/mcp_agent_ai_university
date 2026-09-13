from typing import Dict, Any, List

SENSITIVE_FIELDS = {"email", "phone", "national_id", "passport_id", "address"}

STUDENT_SELF_FIELDS = {
    "student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email"
}

ADVISOR_STUDENT_FIELDS = {
    "student_id", "name", "program", "academic_status", "subject_grades"
}

ADMIN_FIELDS = {
    "student_id", "name", "program", "gpa", "academic_status", "subject_grades",
    "email", "phone", "national_id", "passport_id", "address", "advisor_note"
}

ADMIN_ONLY_POSTGRES_QUERY_TYPES = {
    "tables",
    "database_map",
    "data_agents",
    "documents",
    "all_documents",
    "query",
    "academic_overview",
    "academic_risk_summary",
}

NON_ADMIN_POSTGRES_QUERY_TYPES = {
    "programs",
    "campus_info",
    "course_catalog",
    "student_academic_profile",
    "advisor_documents",
    "lecturer_documents",
    "course_documents",
    "advisor_subjects",
    "student_subjects",
    "academic_analytics",
    "advisor_classroom",
}

DATABASE_WORKER_OPERATIONS = {
    "student_risk_score",
    "lowest_gpa",
    "average_gpa",
    "duplicate_check",
}

ACADEMIC_SECTIONS_BY_ROLE = {
    "admin": {"profile", "enrollments", "assessments", "attendance", "financial_accounts", "support_cases", "scholarship_awards"},
    "advisor": {"enrollments", "assessments", "attendance"},
    "lecturer": {"enrollments", "assessments", "attendance"},
    "student": {"profile", "enrollments", "assessments", "attendance", "financial_accounts", "scholarship_awards"},
}

STUDENT_OWN_MONGO_OPERATIONS = {
    "read_students",
    "grade_summary",
    "subject_summary",
    "study_term_search",
    "study_term_aggregate",
    "filter_summary",
}

STUDENT_COURSE_ANALYTICS_MEASURES = {
    "average_score",
    "pass_rate",
    "attendance_rate",
    "student_count",
    "score_change",
}

STUDENT_COURSE_ANALYTICS_DIMENSIONS = {"course", "term", "overall"}

ROLE_SCOPED_EXCEL_OPERATIONS = {
    "list_uploaded_excel",
    "search_uploaded_excel",
    "document_search",
    "list_documents",
}


def check_pdpa_policy(
    tool_name: str,
    arguments: Dict[str, Any],
    user_role: str,
    requester_student_id: str | None = None,
    requester_advisor_id: str | None = None,
) -> Dict[str, Any]:
    user_role = (user_role or "").lower()

    if tool_name == "database_worker_tool":
        if user_role != "admin":
            return {"allowed": False, "reason": "Only administrators can use Database Worker operations."}
        operation = str(arguments.get("operation") or "")
        if operation not in DATABASE_WORKER_OPERATIONS:
            return {"allowed": False, "reason": "Unsupported Database Worker operation."}
        return {"allowed": True, "reason": "Admin may run this allowlisted read-only Database Worker operation."}

    if user_role == "admin":
        return {"allowed": True, "reason": "Admin access allowed through an explicitly registered MCP tool."}

    if tool_name == "mongodb_student_tool":
        requested_student_id = arguments.get("student_id")
        operation = str(arguments.get("operation") or "read_students")

        if operation == "schema_overview" and user_role != "admin":
            return {"allowed": False, "reason": "Only administrators can inspect database schema metadata."}
        if operation == "rank_students" and user_role != "admin":
            return {
                "allowed": False,
                "reason": "University-wide GPA rankings are only available to administrators.",
            }

        if user_role == "student":
            if not requester_student_id:
                return {"allowed": False, "reason": "Student role requires logged-in student ID."}
            if requested_student_id != requester_student_id:
                return {"allowed": False, "reason": "Students can only access their own information."}
            if operation not in STUDENT_OWN_MONGO_OPERATIONS:
                return {
                    "allowed": False,
                    "reason": "Students may use MongoDB only for their own record and own studied-subject facts; population, directory, ranking, benchmark, and grouped operations are denied.",
                }
            return {"allowed": True, "reason": "Student can access own record only."}

        if user_role in {"advisor", "lecturer"}:
            if not requester_advisor_id:
                return {"allowed": False, "reason": "Advisor role requires logged-in advisor ID."}
            return {
                "allowed": False,
                "reason": "Advisor student access must use the PostgreSQL advisor_classroom query so every row is bound to the signed advisor and same course.",
            }

        return {"allowed": False, "reason": "Unknown role. Access denied."}

    if tool_name == "mongodb_advisor_tool":
        if user_role == "admin":
            return {"allowed": True, "reason": "Admin can access advisor data."}
        if user_role != "advisor":
            return {"allowed": False, "reason": "Only advisors or admin can access advisor profile data."}
        return {"allowed": True, "reason": "Advisor can access own advisor profile."}

    if tool_name == "postgres_university_tool":
        query_type = str(arguments.get("query_type") or "")

        if query_type in ADMIN_ONLY_POSTGRES_QUERY_TYPES and user_role != "admin":
            return {"allowed": False, "reason": "Only administrators can access database maps, global documents, SQL tools, or university-wide diagnostics."}

        if query_type == "student_academic_profile":
            if user_role == "student" and not requester_student_id:
                return {"allowed": False, "reason": "Student academic profile access requires a signed student identity."}
            if user_role in {"advisor", "lecturer"} and not requester_advisor_id:
                return {"allowed": False, "reason": "Academic profile access requires a signed teaching identity."}
            requested_sections = {
                str(value).strip()
                for value in (arguments.get("requested_sections") or [])
                if str(value).strip()
            }
            forbidden_sections = requested_sections - ACADEMIC_SECTIONS_BY_ROLE.get(user_role, set())
            if forbidden_sections:
                return {
                    "allowed": False,
                    "reason": f"The signed role cannot access academic section(s): {', '.join(sorted(forbidden_sections))}.",
                }
            if user_role == "student":
                requested_student_id = str(arguments.get("student_id") or requester_student_id).upper().strip()
                requested_student_ids = {
                    str(value).upper().strip()
                    for value in (arguments.get("student_ids") or [])
                    if str(value).strip()
                }
                if (
                    requested_student_id != requester_student_id
                    or any(student_id != requester_student_id for student_id in requested_student_ids)
                ):
                    return {"allowed": False, "reason": "Students can only access their own academic profile."}
            return {"allowed": True, "reason": "Academic profiles are constrained by signed role and enrollment assignment inside the PostgreSQL tool."}

        if query_type == "advisor_classroom":
            if user_role not in {"advisor", "lecturer"} or not requester_advisor_id:
                return {"allowed": False, "reason": "Classroom access requires a signed Advisor or Lecturer teaching identity."}
            return {
                "allowed": True,
                "reason": "Classroom rows are constrained to current course enrollments for the signed teaching scope.",
            }

        if query_type == "academic_analytics":
            measure = str(arguments.get("measure") or "")
            dimension = str(arguments.get("dimension") or "")
            if user_role == "student" and not requester_student_id:
                return {"allowed": False, "reason": "Student analytics require a signed student identity."}
            if user_role in {"advisor", "lecturer"} and not requester_advisor_id:
                return {"allowed": False, "reason": "Advisor analytics require a signed advisor identity."}
            if user_role in {"advisor", "lecturer"} and (
                measure not in {"average_score", "pass_rate", "attendance_rate", "student_count", "score_change"}
                or dimension not in {"course", "student", "term", "overall"}
            ):
                return {"allowed": False, "reason": "Advisor analytics are limited to score, pass, attendance, and enrollment facts from assigned classes."}
            if user_role == "student":
                requested_student_ids = {
                    str(value).upper().strip()
                    for value in (arguments.get("student_ids") or [])
                    if str(value).strip()
                }
                if (
                    measure not in STUDENT_COURSE_ANALYTICS_MEASURES
                    or dimension not in STUDENT_COURSE_ANALYTICS_DIMENSIONS
                    or any(student_id != requester_student_id for student_id in requested_student_ids)
                ):
                    return {
                        "allowed": False,
                        "reason": "Student analytics are limited to the signed student's own enrolled-course score, pass, attendance, enrollment, and term facts.",
                    }
            return {"allowed": True, "reason": "Academic analytics are allowlisted and constrained to the signed role inside the PostgreSQL tool."}

        if query_type in {"programs", "campus_info", "course_catalog"}:
            return {"allowed": True, "reason": "Course catalog information is available without personal student data."}

        if query_type == "advisor_documents":
            if user_role == "student" and not requester_student_id:
                return {"allowed": False, "reason": "Student advisor-document access requires logged-in student ID."}
            if user_role in {"advisor", "lecturer"} and not requester_advisor_id:
                return {"allowed": False, "reason": "Course-document access requires a signed teaching identity."}
            return {"allowed": True, "reason": "Advisor documents are filtered by role, subject, advisor, and enrollment."}

        if query_type == "lecturer_documents":
            if user_role != "lecturer" or not requester_advisor_id:
                return {"allowed": False, "reason": "Lecturer documents require a signed Lecturer teaching identity."}
            return {"allowed": True, "reason": "Lecturer documents are isolated by signed owner and assigned class."}

        if query_type == "course_documents":
            if user_role != "student" or not requester_student_id:
                return {"allowed": False, "reason": "Course materials require a signed student identity."}
            return {"allowed": True, "reason": "Course materials are filtered to the student's current enrollments."}

        if query_type == "advisor_subjects":
            if user_role == "student" and not requester_student_id:
                return {"allowed": False, "reason": "Student subject access requires logged-in student ID."}
            if user_role in {"advisor", "lecturer"} and not requester_advisor_id:
                return {"allowed": False, "reason": "Subject access requires a signed teaching identity."}
            return {"allowed": True, "reason": "Subject lists are filtered by role."}

        if query_type == "student_subjects":
            if user_role != "student" or not requester_student_id:
                return {"allowed": False, "reason": "Student subject access requires a signed student identity."}
            return {"allowed": True, "reason": "Student subjects are filtered to the signed student inside PostgreSQL."}

        if user_role != "admin" and query_type not in NON_ADMIN_POSTGRES_QUERY_TYPES:
            return {"allowed": False, "reason": "This database operation is not available to the signed role."}
        return {"allowed": True, "reason": "The signed role is allowed to use this PostgreSQL query type."}

    if tool_name == "excel_tool":
        operation = str(arguments.get("operation") or "")
        if operation not in ROLE_SCOPED_EXCEL_OPERATIONS:
            return {"allowed": False, "reason": "Legacy global spreadsheet operations are not available to non-admin roles."}
        return {"allowed": True, "reason": "Uploaded spreadsheet rows are constrained by the signed role and enrolled subject."}

    if tool_name in {"pdf_tool", "image_tool", "analyze_document_image"}:
        return {"allowed": False, "reason": "Legacy direct-file tools are not available to non-admin roles; use an authorized enrolled-course document record."}

    return {"allowed": False, "reason": "This tool has no explicit access policy."}


def access_scope_summary(
    tool_name: str,
    user_role: str,
    requester_student_id: str | None = None,
    requester_advisor_id: str | None = None,
) -> Dict[str, str]:
    """Return a non-sensitive explanation of the scope enforced for a tool call."""
    role = (user_role or "").lower()
    if role == "student":
        scope = "own_student_record"
    elif role in {"advisor", "lecturer"}:
        scope = "assigned_classes_same_course_records"
    elif role == "admin":
        scope = "authorized_university_administration"
    else:
        scope = "denied"
    return {
        "role": role or "unknown",
        "scope": scope,
        "authority": "signed_backend_identity",
        "gateway": "internal_mcp_service_key",
        "tool": str(tool_name or ""),
    }


def minimize_requested_fields(
    tool_name: str,
    arguments: Dict[str, Any],
    user_role: str,
    requester_student_id: str | None = None,
    requester_advisor_id: str | None = None,
) -> Dict[str, Any]:
    user_role = (user_role or "").lower()

    if tool_name == "postgres_university_tool" and str(arguments.get("query_type") or "") == "student_academic_profile":
        safe = dict(arguments)
        if user_role == "student":
            safe["student_id"] = requester_student_id
            safe["student_ids"] = [requester_student_id] if requester_student_id else []
        requested = {
            str(value).strip()
            for value in (safe.get("requested_sections") or [])
            if str(value).strip()
        }
        allowed = ACADEMIC_SECTIONS_BY_ROLE.get(user_role, set())
        safe["requested_sections"] = sorted(requested & allowed) if requested else sorted(allowed)
        return safe

    if tool_name != "mongodb_student_tool":
        return arguments

    requested_fields: List[str] = arguments.get("requested_fields", [])

    if user_role == "student":
        arguments["student_id"] = requester_student_id
        if not requested_fields:
            arguments["requested_fields"] = list(STUDENT_SELF_FIELDS)
        else:
            arguments["requested_fields"] = [field for field in requested_fields if field in STUDENT_SELF_FIELDS]
        return arguments

    if user_role in {"advisor", "lecturer"}:
        arguments["requested_fields"] = list(ADVISOR_STUDENT_FIELDS)
        arguments["advisor_scope_required"] = True
        return arguments

    if user_role == "admin":
        if not requested_fields:
            arguments["requested_fields"] = list(ADMIN_FIELDS)
        return arguments

    return arguments


def mask_value(value):
    if value is None:
        return None
    value = str(value)
    if "@" in value:
        name, domain = value.split("@", 1)
        return name[:2] + "***@" + domain
    if len(value) <= 4:
        return "***"
    return value[:2] + "***" + value[-2:]


def mask_sensitive_data(data: Any, user_role: str) -> Any:
    # Admin sees all. Student sees their own record because policy enforces own ID.
    if user_role in {"admin", "student"}:
        return data

    if isinstance(data, dict):
        return {
            key: mask_value(value) if key in SENSITIVE_FIELDS else mask_sensitive_data(value, user_role)
            for key, value in data.items()
        }

    if isinstance(data, list):
        return [mask_sensitive_data(item, user_role) for item in data]

    return data
