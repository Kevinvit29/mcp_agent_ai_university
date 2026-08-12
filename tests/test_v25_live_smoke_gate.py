import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.live_smoke_gate import _mcp_snapshot, run_live_smoke_gate


def _mongo_ok(uri, db_name):
    assert uri.startswith("mongodb://")
    return {
        "database": db_name,
        "student_count": 100,
        "advisor_count": 3,
        "missing_student_id_count": 0,
        "missing_program_count": 0,
    }


def _postgres_ok():
    required = [
        "chat_sessions", "chat_messages", "admin_documents", "advisor_documents",
        "student_subjects", "ai_data_agents", "ai_data_chunks",
    ]
    return {
        "required_tables": required,
        "present_tables": required,
        "missing_tables": [],
        "counts": {
            "admin_documents": 2,
            "advisor_documents": 1,
            "student_subjects": 6,
            "ai_data_agents": 4,
            "ai_data_chunks": 15,
        },
    }


def _mcp_ok(url):
    assert url.startswith("http://")
    return {
        "health_status": "healthy",
        "missing_required_tools": [],
        "count_call_success": True,
        "mcp_student_count": 100,
    }


def test_v25_live_smoke_gate_reports_all_read_only_checks_passing():
    report = run_live_smoke_gate(
        mongo_uri="mongodb://mongo:27017",
        mongo_db_name="university_mongo",
        mcp_base_url="http://mcp_server:9000",
        mongo_reader=_mongo_ok,
        postgres_reader=_postgres_ok,
        mcp_reader=_mcp_ok,
    )

    assert report["success"] is True
    assert report["summary"] == {"passed": 4, "failed": 0, "total": 4, "percentage": 100.0}
    assert report["failed_case_ids"] == []
    boundary = next(case for case in report["cases"] if case["case_id"] == "source_truth_population_boundary")
    assert boundary["details"]["canonical_population_source"] == "MongoDB university_mongo.students"
    assert "student_subjects" in boundary["details"]["rule"]


def test_v25_live_smoke_gate_fails_safely_when_canonical_source_is_empty():
    def mongo_empty(uri, db_name):
        return {
            "database": db_name,
            "student_count": 0,
            "advisor_count": 0,
            "missing_student_id_count": 0,
            "missing_program_count": 0,
        }

    report = run_live_smoke_gate(
        mongo_reader=mongo_empty,
        postgres_reader=_postgres_ok,
        mcp_reader=_mcp_ok,
    )

    assert report["success"] is False
    assert "mongo_canonical_student_master" in report["failed_case_ids"]
    assert "source_truth_population_boundary" in report["failed_case_ids"]


def test_v30_mcp_smoke_call_uses_internal_service_key():
    class Response:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    captured = {}

    def fake_get(url, timeout):
        if url.endswith("/tools"):
            return Response({"tools": [{"name": "mongodb_student_tool"}, {"name": "postgres_university_tool"}]})
        return Response({"status": "healthy"})

    def fake_post(url, timeout, headers, json):
        captured["headers"] = headers
        captured["arguments"] = json["arguments"]
        return Response({"success": True, "data": {"type": "student_count", "count": 1000}})

    result = _mcp_snapshot(
        "http://mcp_server:9000",
        request_get=fake_get,
        request_post=fake_post,
    )

    assert captured["headers"]["X-MCP-Service-Key"]
    assert captured["arguments"]["student_id"] == "ALL"
    assert result["count_call_success"] is True
    assert result["mcp_student_count"] == 1000
