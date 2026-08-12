import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.aggregate_query import (
    parse_total_student_count_query,
    parse_student_statistic_query,
    parse_student_study_query,
)


class V15QueryContractTests(unittest.TestCase):
    def test_total_students_uses_total_count_contract(self):
        query = parse_total_student_count_query("how many student in the university")
        self.assertIsNotNone(query)
        self.assertEqual(query["operation"], "count")
        self.assertEqual(query["scope"], "university")

    def test_total_students_not_study_aggregate(self):
        self.assertIsNone(parse_student_statistic_query("how many student in the university"))

    def test_law_median_uses_study_aggregate(self):
        query = parse_student_statistic_query("what is student median grade in law program")
        self.assertIsNotNone(query)
        self.assertEqual(query["operation"], "study_term_aggregate")
        self.assertEqual(query["study_term"].lower(), "law")
        self.assertEqual(query["statistic"], "median")

    def test_university_average_uses_population_aggregate(self):
        query = parse_student_statistic_query("average GPA of all students")
        self.assertIsNotNone(query)
        self.assertEqual(query["operation"], "student_population_aggregate")
        self.assertEqual(query["scope"], "university")

    def test_law_search_keeps_real_term(self):
        query = parse_student_study_query("how many students study law")
        self.assertIsNotNone(query)
        self.assertEqual(query["study_term"].lower(), "law")
        self.assertEqual(query["intent"], "count")


if __name__ == "__main__":
    unittest.main()

from app.agent.contextual_tool_planner import plan_from_purpose
from app.agent.result_validator import validate_tool_result


class V15PlannerValidationTests(unittest.TestCase):
    def _purpose(self, intent="count"):
        return {
            "target_domain": "students",
            "answer_intent": intent,
            "should_use_database": True,
            "confidence": 0.9,
            "user_purpose": "test",
            "explicit_entities": {"student_ids": [], "advisor_ids": [], "subject_terms": []},
        }

    def test_planner_uses_count_for_total_university_students(self):
        plan = plan_from_purpose(
            message="how many student in the university",
            language="en",
            user_role="admin",
            purpose=self._purpose(),
        )
        self.assertEqual(plan["arguments"]["operation"], "count")
        self.assertIsNone(plan["arguments"].get("study_term"))

    def test_validator_rejects_empty_study_aggregate_for_total_count_question(self):
        bad_plan = {
            "tool_name": "mongodb_student_tool",
            "purpose_analysis": self._purpose(),
            "arguments": {"operation": "study_term_aggregate", "study_term": "", "statistic": "count"},
            "validation_contract": {"expected_domain": "students"},
        }
        result = {"success": True, "data": {"type": "student_study_term_aggregate", "study_term": "", "statistic": "count", "count": 0}}
        validation = validate_tool_result("how many student in the university", bad_plan, result)
        self.assertFalse(validation["is_valid"])
        self.assertTrue(any("University-wide student count" in problem for problem in validation["problems"]))


if __name__ == "__main__":
    unittest.main()
