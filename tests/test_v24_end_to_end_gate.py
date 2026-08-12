import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.end_to_end_gate import run_end_to_end_gate


def test_v24_end_to_end_gate_passes():
    report = run_end_to_end_gate()
    assert report["success"] is True, report.get("failed_case_ids")
    assert report["summary"]["total"] >= 7
    assert report["summary"]["failed"] == 0
