"""Checks for the single maintainable V30 chat benchmark catalog."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.evaluation_suite import load_benchmark_catalog, run_query_contract_evaluation


def test_benchmark_catalog_has_unique_cases_across_all_sections():
    catalog = load_benchmark_catalog()
    ids = [
        case["case_id"]
        for section in ("parser_cases", "contract_cases", "planner_cases", "conversation_cases")
        for case in catalog[section]
    ]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 100
    assert len(catalog["conversation_cases"]) >= 6


def test_live_evaluation_reports_the_catalog_version_and_passes():
    catalog = load_benchmark_catalog()
    report = run_query_contract_evaluation()
    assert report["benchmark_version"] == catalog["version"]
    assert report["benchmark_file"] == "evaluation_cases.json"
    assert report["success"] is True, report


def test_release_gate_runs_both_live_answer_brains():
    control = (ROOT / "scripts" / "v30_control.py").read_text()
    assert "app.agent.academic_brain_gate" in control
    assert "app.agent.random_question_gate" in control
