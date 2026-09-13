"""Milestone 3 contracts for safe, separate student master-data imports."""

from io import BytesIO
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.roles.admin.master_import_models import ImportValidationError, parse_student_master


def test_csv_preview_maps_common_headers_without_writing_a_database():
    parsed = parse_student_master(
        b"Student ID,Name,Program Code,Program,GPA,Attendance\nT9001,Test Student,CS,Computer Science,3.75,92\n",
        "student-master.csv",
    )
    assert parsed.summary["valid"] is True
    assert parsed.records == [{
        "student_id": "T9001", "full_name": "Test Student", "program_code": "CS",
        "program_name": "Computer Science", "gpa": 3.75, "attendance_rate": 92.0,
    }]
    assert parsed.column_mapping["full_name"] == "Name"


def test_excel_preview_and_explicit_reverse_mapping_are_supported():
    workbook = BytesIO()
    pd.DataFrame([{
        "University Number": "X-7", "Display Name": "Excel Student", "Major ID": "BUS",
        "Major Label": "Business Administration", "Current GPA": 3.25,
    }]).to_excel(workbook, index=False)
    parsed = parse_student_master(
        workbook.getvalue(),
        "student-master.xlsx",
        {
            "University Number": "student_id", "Display Name": "full_name", "Major ID": "program_code",
            "Major Label": "program_name", "Current GPA": "gpa",
        },
    )
    assert parsed.summary["valid"] is True
    assert parsed.records[0]["student_id"] == "X-7"
    assert parsed.records[0]["gpa"] == 3.25


def test_invalid_values_and_duplicate_ids_block_confirmation():
    parsed = parse_student_master(
        b"student_id,name,program_code,program,gpa,attendance_rate\nS1,One,CS,Computer Science,4.5,90\nS1,Two,CS,Computer Science,3.0,105\n",
        "students.csv",
    )
    assert parsed.summary["valid"] is False
    assert parsed.summary["duplicate_in_file_count"] == 1
    codes = {issue["code"] for row in parsed.row_issues for issue in row}
    assert {"duplicate_in_file", "out_of_range"}.issubset(codes)


@pytest.mark.parametrize("filename", ["students.pdf", "students.json", "students"])
def test_master_import_rejects_non_tabular_file_types(filename):
    with pytest.raises(ImportValidationError, match="CSV, XLSX, or XLS"):
        parse_student_master(b"not a spreadsheet", filename)


def test_admin_router_keeps_document_upload_and_master_import_separate():
    router = (ROOT / "backend" / "app" / "roles" / "admin" / "router.py").read_text()
    security = (ROOT / "backend" / "app" / "production_security.py").read_text()
    assert '"/documents/upload"' in router
    assert '"/master-data/imports/preview"' in router
    assert '"/master-data/imports/{import_id}/confirm"' in router
    assert '"/master-data/imports/{import_id}/rollback"' in router
    assert 'if path.startswith("/admin/")' in security


def test_schema_contains_staging_rows_snapshots_and_import_marker():
    schema = (ROOT / "backend" / "app" / "db" / "postgres.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS master_import_batches" in schema
    assert "CREATE TABLE IF NOT EXISTS master_import_rows" in schema
    assert "CREATE TABLE IF NOT EXISTS master_import_snapshots" in schema
    assert "last_master_import_id UUID" in schema
    assert "is_active BOOLEAN NOT NULL DEFAULT TRUE" in schema


def test_step3_exposes_role_safe_crud_and_password_reset_workflows():
    router = (ROOT / "backend" / "app" / "roles" / "admin" / "router.py").read_text()
    auth = (ROOT / "backend" / "app" / "auth.py").read_text()
    accounts = (ROOT / "backend" / "app" / "admin_accounts.py").read_text()
    for route in (
        '"/master-data/students"', '"/master-data/students/{student_id}"',
        '"/master-data/students/{student_id}/active"', '"/master-data/advisors"',
        '"/master-data/advisors/{advisor_id}"', '"/master-data/advisors/{advisor_id}/active"',
        '"/accounts/{admin_id}/reset-password"',
    ):
        assert route in router
    assert 'student.get("is_active") is False' in auth
    assert 'advisor.get("is_active") is False' in auth
    assert "def reset_admin_password_by_id" in accounts


def test_frontend_labels_master_data_as_separate_from_knowledge_uploads():
    app = (ROOT / "frontend" / "src" / "App.jsx").read_text()
    component = (ROOT / "frontend" / "src" / "components" / "MasterDataImport.jsx").read_text()
    assert "Student data" in app
    assert "This is separate from knowledge files" in component
    assert "Confirm synchronized import" in component
    assert "Rollback this import" in component


def test_import_confirmation_is_race_safe_and_restart_recoverable():
    repository = (ROOT / "backend" / "app" / "roles" / "admin" / "master_import_repository.py").read_text()
    service = (ROOT / "backend" / "app" / "roles" / "admin" / "master_import_service.py").read_text()
    startup = (ROOT / "backend" / "app" / "main.py").read_text()
    bootstrap = (ROOT / "backend" / "app" / "system_bootstrap.py").read_text()
    assert "def transition_status" in repository
    assert "WHERE import_id = %s AND status = %s" in repository
    assert "def recover_incomplete_imports" in service
    assert "recover_incomplete_imports()" in startup
    assert "recovery = recover_incomplete_imports()" in bootstrap
    assert bootstrap.index("recovery = recover_incomplete_imports()") < bootstrap.index("current = dataset_status()")
