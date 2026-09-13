"""Authoritative schema and access registry for the V30 Agent AI.

The AI may interpret intent, but it never receives authority to expand data
scope. Deterministic planning chooses a registered MCP tool, signed identity
defines row scope, and the MCP policy minimizes fields before execution.
"""

from __future__ import annotations

from typing import Any, Dict, List


STUDENT_FIELDS_ADMIN = [
    "student_id", "name", "program", "gpa", "academic_status", "subject_grades",
    "email", "phone", "national_id", "passport_id", "address", "advisor_note",
]

STUDENT_FIELDS_STUDENT = [
    "student_id", "name", "program", "gpa", "academic_status", "subject_grades", "email",
]

STUDENT_FIELDS_ADVISOR = [
    "student_id", "name", "program", "academic_status", "subject_grades",
]

ADVISOR_FIELDS_ADMIN = ["advisor_id", "name", "department", "email", "phone", "teaches"]
ADVISOR_FIELDS_ADVISOR = ["advisor_id", "name", "department", "email", "phone", "teaches"]

AUTHORITATIVE_DATA_SOURCES: Dict[str, Dict[str, Any]] = {
    "student_master": {
        "source": "MongoDB students",
        "tool": "mongodb_student_tool",
        "facts": ["identity", "program", "GPA", "academic status", "subject grades"],
    },
    "advisor_master": {
        "source": "MongoDB advisors",
        "tool": "mongodb_advisor_tool",
        "facts": ["advisor identity", "department", "contact details", "teaching information"],
    },
    "academic_operations": {
        "source": "PostgreSQL normalized academic tables",
        "tool": "postgres_university_tool",
        "facts": [
            "course catalog", "enrollment", "assessment results", "attendance", "credits", "finance",
            "scholarships", "support cases", "academic risk summaries",
        ],
    },
    "uploaded_knowledge": {
        "source": "PostgreSQL document library and extracted file content",
        "tool": "postgres_university_tool",
        "facts": ["PDF, Excel, and CSV metadata", "extracted text", "structured rows"],
    },
}


SCHEMA_REGISTRY: Dict[str, Any] = {
    "mongodb_students": {
        "tool_name": "mongodb_student_tool",
        "authority": "canonical_student_master",
        "description": "Student records, GPA, academic status, and nested subject grade records.",
        "primary_key": "student_id",
        "fields": {
            "student_id": "Student ID such as S001.",
            "name": "Student full name.",
            "program": "Program/major.",
            "gpa": "Overall GPA as number.",
            "academic_status": "Academic status such as Good Standing or Warning.",
            "subject_grades": "List of {subject, grade, advisor_id}. This is the source of subject/course names.",
            "email": "Student email; sensitive for non-admin except own student.",
            "phone": "Sensitive contact field.",
            "national_id": "Sensitive field.",
            "passport_id": "Sensitive field.",
            "address": "Sensitive field.",
            "advisor_note": "Admin-only internal note.",
        },
        "operations": {
            "read_students": "Read one or many student records with filters/sort/limit.",
            "count": "Count student records matching optional filter.",
            "list_names": "List student IDs and names.",
            "grade_summary": "Summarize grade records and grade distribution.",
            "subject_summary": "Count/list unique subjects from subject_grades; use for university-wide subject/course questions.",
            "rank_students": "Return an exact top/bottom N student leaderboard ordered by GPA; administrator only.",
            "group_students": "Group visible students by an allowlisted master-data dimension and calculate count or average GPA.",
            "compare_student_to_population": "Compare one authorized student's GPA with the aggregate university average.",
            "study_term_search": "Find or count students by a normalized program/subject term before formatting the answer.",
            "student_population_aggregate": "Calculate an allowlisted university-wide GPA statistic without inventing a program filter.",
            "study_term_aggregate": "Calculate an allowlisted GPA statistic after applying a real program/subject filter.",
            "filter_summary": "Apply an allowlisted numeric GPA comparison and return the exact count plus a bounded preview.",
            "schema_overview": "Admin schema sample and field overview.",
        },
    },
    "mongodb_advisors": {
        "tool_name": "mongodb_advisor_tool",
        "authority": "canonical_advisor_master",
        "description": "Advisor/teacher records and teaching information.",
        "primary_key": "advisor_id",
        "fields": {
            "advisor_id": "Advisor ID such as A001.",
            "name": "Advisor name.",
            "department": "Advisor department.",
            "email": "Advisor email.",
            "phone": "Advisor phone.",
            "teaches": "Subjects/classes taught, if available.",
        },
        "operations": {
            "read_advisors": "Read one advisor profile.",
            "list_advisors": "List all advisors for admin; advisor role can see own profile.",
            "schema_overview": "Admin schema overview.",
        },
    },
    "postgres_university": {
        "tool_name": "postgres_university_tool",
        "authority": "operations_relationships_and_documents",
        "description": "Programs, enrollment relationships, uploaded document content, accounts, chat state, audit events, and local agent indexes. Relationship row counts are not the student population.",
        "query_types": {
            "programs": "Program/major/faculty/admission style information.",
            "advisor_subjects": "Advisor-to-subject teaching links.",
            "student_subjects": "Signed-student subject assignments and course authorization links.",
            "academic_overview": "Admin-only aggregate overview of normalized academic datasets.",
            "course_catalog": "Formal course codes, names, programs, credits, and levels.",
            "student_academic_profile": "Role-scoped enrollment, attendance, credits, finance, scholarships, and support data.",
            "academic_risk_summary": "Admin-only aggregate risk summary by program.",
            "academic_analytics": "Role-scoped grouped score, pass-rate, attendance, count, GPA, or balance analytics.",
            "advisor_classroom": "Advisor-only roster and grade/score/attendance facts bound to the signed advisor and same assigned course.",
            "database_map": "Schema/database overview.",
            "campus_info": "Campus locations such as cafeteria/library/buildings.",
            "all_documents": "Admin: global, Advisor, and Lecturer PDF/Excel/CSV files.",
            "advisor_documents": "Advisor/student scoped subject PDF/Excel/CSV files.",
            "lecturer_documents": "Lecturer-owned files restricted to the signed Lecturer and assigned classes.",
            "course_documents": "Student-visible Advisor and Lecturer files restricted to current enrollments.",
        },
        "document_fields": [
            "id", "filename", "summary", "conclusion_table", "text_excerpt", "structured_preview",
            "source_type", "storage_target", "cloned_agent_name", "subject_name", "advisor_id", "lecturer_id", "created_at",
        ],
        "operations": {
            "list_documents": "List available files.",
            "document_search": "Search uploaded file names, summaries, full text, and structured extracted rows.",
            "search": "Generic Postgres search.",
        },
    },
}

AUTHORIZED_AGENT_DATA_FLOW = [
    {
        "step": "signed_identity",
        "rule": "The backend token fixes role and owner ID; browser role/ID fields cannot expand access.",
    },
    {
        "step": "purpose_contract",
        "rule": "The latest message fixes entity, intent, answer shape, and whether stored university data is required.",
    },
    {
        "step": "deterministic_tool_plan",
        "rule": "The agent selects only a registered MCP tool and allowlisted operation; AI hints are advisory.",
    },
    {
        "step": "internal_mcp_gateway",
        "rule": "Only the backend can call database tools, using the internal MCP service key.",
    },
    {
        "step": "role_scope_and_field_minimization",
        "rule": "Students receive their own record; advisors receive only student identity and academic facts from the signed advisor's same assigned class; admins receive authorized university administration data.",
    },
    {
        "step": "source_of_truth_query",
        "rule": "MongoDB answers student/advisor master facts and grades; PostgreSQL answers normalized enrollment, attendance, credits, finance, scholarships, support, risk, catalog, and document facts.",
    },
    {
        "step": "result_validation",
        "rule": "The returned data domain and answer shape must match the request before formatting.",
    },
    {
        "step": "grounded_answer",
        "rule": "Database facts are formatted deterministically and are not rewritten into unsupported claims.",
    },
]


ROLE_POLICY_SUMMARY: Dict[str, Any] = {
    "admin": {
        "description": "Authorized university administration access through the signed backend and MCP policy guard.",
        "row_scope": "authorized_university_administration",
        "student_fields": STUDENT_FIELDS_ADMIN,
        "advisor_fields": ADVISOR_FIELDS_ADMIN,
        "document_scope": "all_documents",
        "academic_scope": "all normalized academic records, assessments, finance, scholarships, support cases, and aggregate risk",
    },
    "advisor": {
        "description": "Can see own advisor profile, taught students' subject grades, and own advisor-uploaded subject documents.",
        "row_scope": "assigned_students_and_taught_subjects",
        "student_fields": STUDENT_FIELDS_ADVISOR,
        "advisor_fields": ADVISOR_FIELDS_ADVISOR,
        "document_scope": "advisor_documents",
        "academic_scope": "assigned students' limited profile, enrollment, assessments, attendance, credits, and academic risk only",
        "hidden_student_fields": ["gpa", "email", "phone", "national_id", "passport_id", "address", "advisor_note"],
    },
    "student": {
        "description": "Can see only own student record and advisor-uploaded documents for enrolled subjects.",
        "row_scope": "own_student_record",
        "student_fields": STUDENT_FIELDS_STUDENT,
        "document_scope": "advisor_documents",
        "academic_scope": "own profile, enrollment, assessments, attendance, credits, finance, and scholarships",
    },
}


TOOL_CONTRACTS: List[Dict[str, Any]] = [
    {
        "tool_name": "mongodb_student_tool",
        "when_to_use": [
            "student profile/name/program/GPA/status/questions",
            "grades or subject_grades for student IDs",
            "student count/list/filter/ranking",
            "unique subject/course count/list/summary from subject_grades",
        ],
        "important_rule": "If the question target is subjects/courses without a specific student ID, use operation=subject_summary, not operation=count.",
    },
    {
        "tool_name": "mongodb_advisor_tool",
        "when_to_use": ["advisor profile", "advisor list/count", "advisor ID questions"],
    },
    {
        "tool_name": "postgres_university_tool",
        "when_to_use": [
            "PDF/Excel/CSV/uploaded file questions",
            "document content search",
            "programs/faculty/admission/campus/database map",
            "course catalog, enrollment, attendance, credits, finance, scholarships, support cases, and academic risk",
        ],
    },
    {"tool_name": "none", "when_to_use": ["normal ChatGPT-style questions that do not need university data"]},
]


def get_schema_registry_for_role(role: str) -> Dict[str, Any]:
    role_key = (role or "student").lower()
    return {
        "schema": SCHEMA_REGISTRY,
        "role_policy": ROLE_POLICY_SUMMARY.get(role_key, ROLE_POLICY_SUMMARY["student"]),
        "tool_contracts": TOOL_CONTRACTS,
        "authorized_agent_data_flow": AUTHORIZED_AGENT_DATA_FLOW,
        "authoritative_data_sources": AUTHORITATIVE_DATA_SOURCES,
    }


def allowed_student_fields_for_role(role: str, requested: List[str] | None = None) -> List[str]:
    role_key = (role or "student").lower()
    allowed = ROLE_POLICY_SUMMARY.get(role_key, ROLE_POLICY_SUMMARY["student"]).get("student_fields", STUDENT_FIELDS_STUDENT)
    if not requested:
        return list(allowed)
    return [field for field in requested if field in allowed] or list(allowed)
