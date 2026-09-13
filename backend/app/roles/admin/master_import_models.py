"""Parsing and validation for staged student master-data imports.

This module is intentionally database-free.  It turns CSV/Excel bytes into a
canonical preview that can be tested without a running service and cannot write
live university records by itself.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

import pandas as pd


MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_ROWS = 5_000
SUPPORTED_EXTENSIONS = {"csv", "xlsx", "xls"}

CANONICAL_FIELDS: Sequence[str] = (
    "student_id", "full_name", "thai_name", "program_code", "program_name",
    "faculty", "email", "phone", "admission_type", "year_level", "entry_year",
    "expected_graduation_year", "academic_status", "gpa", "credits_earned",
    "credits_required", "attendance_rate", "risk_level", "scholarship_status", "campus",
)
REQUIRED_FIELDS = {"student_id", "full_name", "program_code", "program_name"}
INTEGER_FIELDS = {
    "year_level", "entry_year", "expected_graduation_year", "credits_earned", "credits_required",
}
DECIMAL_FIELDS = {"gpa", "attendance_rate"}

ALIASES: Dict[str, Sequence[str]] = {
    "student_id": ("student id", "studentid", "id", "student number", "รหัสนักศึกษา"),
    "full_name": ("full name", "fullname", "name", "student name", "ชื่อ", "ชื่อเต็ม"),
    "thai_name": ("thai name", "name th", "name_th", "ชื่อไทย"),
    "program_code": ("program code", "programme code", "major code", "program_code"),
    "program_name": ("program", "program name", "programme", "major", "department", "program_name"),
    "faculty": ("faculty", "school", "คณะ"),
    "email": ("email", "e-mail", "student email"),
    "phone": ("phone", "telephone", "mobile", "phone number"),
    "admission_type": ("admission type", "entry type", "admission_type"),
    "year_level": ("year level", "study year", "year", "year_level"),
    "entry_year": ("entry year", "admission year", "entry_year"),
    "expected_graduation_year": ("expected graduation year", "graduation year", "expected_graduation_year"),
    "academic_status": ("academic status", "status", "academic_status"),
    "gpa": ("gpa", "grade point average", "เกรดเฉลี่ย"),
    "credits_earned": ("credits earned", "earned credits", "credits_earned"),
    "credits_required": ("credits required", "required credits", "credits_required"),
    "attendance_rate": ("attendance", "attendance rate", "attendance percent", "attendance_rate"),
    "risk_level": ("risk", "risk level", "risk_level"),
    "scholarship_status": ("scholarship", "scholarship status", "scholarship_status"),
    "campus": ("campus", "site"),
}


class ImportValidationError(ValueError):
    """Raised when a file cannot become a safe staged preview."""


@dataclass(frozen=True)
class ParsedImport:
    source_columns: List[str]
    column_mapping: Dict[str, str]
    records: List[Dict[str, Any]]
    row_issues: List[List[Dict[str, str]]]
    summary: Dict[str, Any]


def _normalise_header(value: Any) -> str:
    text = re.sub(r"[_\-]+", " ", str(value or "").strip().lower())
    return re.sub(r"\s+", " ", text)


def _extension(filename: str) -> str:
    return str(filename or "").rsplit(".", 1)[-1].lower() if "." in str(filename or "") else ""


def _read_frame(raw: bytes, filename: str) -> pd.DataFrame:
    if not raw:
        raise ImportValidationError("The import file is empty.")
    if len(raw) > MAX_IMPORT_BYTES:
        raise ImportValidationError("The import file is larger than the 10 MB safety limit.")
    extension = _extension(filename)
    if extension not in SUPPORTED_EXTENSIONS:
        raise ImportValidationError("Student master data must be a CSV, XLSX, or XLS file.")
    try:
        if extension == "csv":
            frame = pd.read_csv(io.BytesIO(raw), dtype=object, keep_default_na=False)
        else:
            frame = pd.read_excel(io.BytesIO(raw), dtype=object, keep_default_na=False)
    except Exception as exc:
        raise ImportValidationError("The spreadsheet could not be read. Check that it is a valid CSV or Excel file.") from exc
    frame = frame.dropna(how="all")
    if frame.empty:
        raise ImportValidationError("The import file does not contain any student rows.")
    if len(frame.index) > MAX_IMPORT_ROWS:
        raise ImportValidationError(f"An import may contain at most {MAX_IMPORT_ROWS:,} rows.")
    columns = [str(item).strip() for item in frame.columns]
    if not all(columns):
        raise ImportValidationError("Every spreadsheet column must have a header.")
    if len(set(columns)) != len(columns):
        raise ImportValidationError("Spreadsheet column names must be unique.")
    frame.columns = columns
    return frame


def propose_mapping(source_columns: Sequence[str]) -> Dict[str, str]:
    """Return canonical-field -> source-column guesses using deterministic aliases."""
    normalised_sources = {_normalise_header(column): column for column in source_columns}
    proposed: Dict[str, str] = {}
    for canonical in CANONICAL_FIELDS:
        candidates = (canonical, canonical.replace("_", " "), *ALIASES.get(canonical, ()))
        for candidate in candidates:
            source = normalised_sources.get(_normalise_header(candidate))
            if source:
                proposed[canonical] = source
                break
    return proposed


def resolve_mapping(source_columns: Sequence[str], requested: Mapping[str, Any] | None) -> Dict[str, str]:
    """Accept canonical->source or source->canonical mapping and merge it over aliases."""
    resolved = propose_mapping(source_columns)
    if not requested:
        return resolved
    available = {str(column) for column in source_columns}
    canonical = set(CANONICAL_FIELDS)
    for left, right in requested.items():
        left_text, right_text = str(left).strip(), str(right).strip()
        if left_text in canonical and right_text in available:
            resolved[left_text] = right_text
        elif left_text in available and right_text in canonical:
            resolved[right_text] = left_text
        else:
            raise ImportValidationError(
                f"Invalid column mapping '{left_text}' -> '{right_text}'. Use a source header and a supported student field."
            )
    duplicates = [source for source in set(resolved.values()) if list(resolved.values()).count(source) > 1]
    if duplicates:
        raise ImportValidationError("One spreadsheet column cannot be mapped to multiple student fields.")
    return resolved


def _clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text if text else None


def _integer(value: Any, field: str, issues: List[Dict[str, str]]) -> int | None:
    value = _clean_scalar(value)
    if value is None:
        return None
    try:
        number = float(value)
        if not number.is_integer():
            raise ValueError
        return int(number)
    except (TypeError, ValueError):
        issues.append({"severity": "error", "field": field, "code": "invalid_integer", "message": f"{field} must be a whole number."})
        return None


def _decimal(value: Any, field: str, issues: List[Dict[str, str]]) -> float | None:
    value = _clean_scalar(value)
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        issues.append({"severity": "error", "field": field, "code": "invalid_number", "message": f"{field} must be numeric."})
        return None


def _validate_record(record: Dict[str, Any], issues: List[Dict[str, str]]) -> None:
    for field in sorted(REQUIRED_FIELDS):
        if not record.get(field):
            issues.append({"severity": "error", "field": field, "code": "required", "message": f"{field} is required."})
    student_id = str(record.get("student_id") or "")
    if student_id and (len(student_id) > 20 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", student_id)):
        issues.append({"severity": "error", "field": "student_id", "code": "invalid_student_id", "message": "student_id must be 1-20 letters, numbers, dots, underscores, or hyphens."})
    if record.get("full_name") and len(str(record["full_name"])) > 255:
        issues.append({"severity": "error", "field": "full_name", "code": "too_long", "message": "full_name is longer than 255 characters."})
    if record.get("program_code") and len(str(record["program_code"])) > 30:
        issues.append({"severity": "error", "field": "program_code", "code": "too_long", "message": "program_code is longer than 30 characters."})
    gpa = record.get("gpa")
    if gpa is not None and not 0 <= gpa <= 4:
        issues.append({"severity": "error", "field": "gpa", "code": "out_of_range", "message": "gpa must be between 0.00 and 4.00."})
    attendance = record.get("attendance_rate")
    if attendance is not None and not 0 <= attendance <= 100:
        issues.append({"severity": "error", "field": "attendance_rate", "code": "out_of_range", "message": "attendance_rate must be between 0 and 100."})
    year_level = record.get("year_level")
    if year_level is not None and not 1 <= year_level <= 12:
        issues.append({"severity": "error", "field": "year_level", "code": "out_of_range", "message": "year_level must be between 1 and 12."})
    for field in ("credits_earned", "credits_required"):
        if record.get(field) is not None and record[field] < 0:
            issues.append({"severity": "error", "field": field, "code": "out_of_range", "message": f"{field} cannot be negative."})
    email = str(record.get("email") or "")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        issues.append({"severity": "error", "field": "email", "code": "invalid_email", "message": "email is not valid."})


def parse_student_master(raw: bytes, filename: str, mapping: Mapping[str, Any] | None = None) -> ParsedImport:
    frame = _read_frame(raw, filename)
    source_columns = list(frame.columns)
    resolved = resolve_mapping(source_columns, mapping)
    missing_mapping = sorted(REQUIRED_FIELDS - set(resolved))
    if missing_mapping:
        raise ImportValidationError(
            "Required column mapping is missing: " + ", ".join(missing_mapping) + "."
        )

    records: List[Dict[str, Any]] = []
    row_issues: List[List[Dict[str, str]]] = []
    seen: Dict[str, int] = {}
    for offset, (_, source_row) in enumerate(frame.iterrows(), start=2):
        issues: List[Dict[str, str]] = []
        record: Dict[str, Any] = {}
        for canonical, source in resolved.items():
            raw_value = source_row[source]
            if canonical in INTEGER_FIELDS:
                record[canonical] = _integer(raw_value, canonical, issues)
            elif canonical in DECIMAL_FIELDS:
                record[canonical] = _decimal(raw_value, canonical, issues)
            else:
                record[canonical] = _clean_scalar(raw_value)
        if record.get("student_id"):
            record["student_id"] = str(record["student_id"]).upper()
        _validate_record(record, issues)
        student_id = str(record.get("student_id") or "")
        if student_id in seen:
            issues.append({
                "severity": "error", "field": "student_id", "code": "duplicate_in_file",
                "message": f"student_id also appears on spreadsheet row {seen[student_id]}.",
            })
        elif student_id:
            seen[student_id] = offset
        records.append(record)
        row_issues.append(issues)

    errors = sum(1 for issues in row_issues for issue in issues if issue["severity"] == "error")
    return ParsedImport(
        source_columns=source_columns,
        column_mapping=resolved,
        records=records,
        row_issues=row_issues,
        summary={
            "valid": errors == 0,
            "row_count": len(records),
            "error_count": errors,
            "warning_count": 0,
            "duplicate_in_file_count": sum(
                1 for issues in row_issues for issue in issues if issue["code"] == "duplicate_in_file"
            ),
        },
    )

