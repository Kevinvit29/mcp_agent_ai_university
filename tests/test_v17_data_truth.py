import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.data_truth import build_university_truth_snapshot, format_authoritative_university_overview


def wrapped(data):
    return {"success": True, "data": data}


def test_mongo_students_are_authoritative_over_postgres_links():
    bundle = {
        "student_count": wrapped({"type": "student_count", "count": 100}),
        "student_schema": wrapped({"type": "mongo_schema_overview", "count": 100}),
        "advisor_schema": wrapped({"type": "mongo_schema_overview", "count": 3}),
        "programs": wrapped([{"program_name": "Law"}, {"program_name": "Business"}]),
        "documents": wrapped({"data": []}),
        "postgres_database_map": wrapped({"type": "postgres_database_map", "tables": [
            {"table_name": "student_subjects", "row_count": 5},
            {"table_name": "advisor_subjects", "row_count": 6},
        ]}),
    }
    snapshot = build_university_truth_snapshot(bundle)
    assert snapshot["canonical_metrics"]["student_count"] == 100
    assert snapshot["supporting_table_counts"]["student_subject_links"] == 5
    assert snapshot["conflicts_detected"]
    answer = format_authoritative_university_overview(bundle, "en")
    assert "Students: 100 total" in answer
    assert "5 relationship row(s)" in answer
    assert "5 student records" not in answer
