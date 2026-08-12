import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.agent.evaluation_suite import run_query_contract_evaluation


class V16RegressionEvaluationTests(unittest.TestCase):
    def test_full_local_contract_suite_passes(self):
        report = run_query_contract_evaluation()
        failed = [case for case in report['cases'] if not case['passed']]
        self.assertEqual([], failed, msg=f"Failed cases: {[c['case_id'] for c in failed]}")
        self.assertGreaterEqual(report['summary']['total'], 20)
        self.assertEqual(report['summary']['failed'], 0)


if __name__ == '__main__':
    unittest.main()
