import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.purpose_contract import (
    build_latest_message_contract,
    apply_contract_to_purpose,
)
from app.agent.contextual_tool_planner import plan_from_purpose


class StudentTableIntentTests(unittest.TestCase):
    def test_table_is_presentation_not_schema(self):
        message = "Can you list students as a table?"
        contract = build_latest_message_contract(message)

        self.assertEqual(contract["domain"], "students")
        self.assertEqual(contract["intent"], "list")
        self.assertEqual(contract["presentation"]["view"], "table")
        self.assertFalse(contract["is_schema_request"])

    def test_schema_remains_database_map(self):
        message = "Show me the columns in the student table"
        contract = build_latest_message_contract(message)

        self.assertEqual(contract["domain"], "database_map")
        self.assertTrue(contract["is_schema_request"])

    def test_bad_ai_database_map_is_overridden(self):
        message = "Can you list students as a table?"
        bad_ai_purpose = {
            "target_domain": "database_map",
            "answer_intent": "list",
            "should_use_database": True,
            "confidence": 0.8,
            "explicit_entities": {},
        }

        fixed = apply_contract_to_purpose(message, bad_ai_purpose)

        self.assertEqual(fixed["target_domain"], "students")

    def test_table_list_routes_to_student_tool(self):
        message = "Can you list students as a table?"
        purpose = apply_contract_to_purpose(message, {
            "target_domain": "database_map",
            "answer_intent": "list",
            "should_use_database": True,
            "confidence": 0.8,
            "explicit_entities": {},
        })

        plan = plan_from_purpose(
            message=message,
            language="en",
            user_role="admin",
            purpose=purpose,
        )

        self.assertEqual(plan["tool_name"], "mongodb_student_tool")
        self.assertEqual(plan["arguments"]["operation"], "read_students")
        self.assertEqual(plan["arguments"]["presentation"]["view"], "table")


if __name__ == "__main__":
    unittest.main()