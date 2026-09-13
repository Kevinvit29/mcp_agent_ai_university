"""Regression checks for the single authoritative V30 chat path."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.contextual_tool_planner import plan_from_purpose
from app.agent.final_answer_writer import deterministic_database_answer
from app.agent.purpose_contract import apply_contract_to_purpose, build_latest_message_contract


class V30LatestMessageContractTests(unittest.TestCase):
    def test_student_id_profile_is_current_target(self):
        contract = build_latest_message_contract("student S099 profile")

        self.assertEqual(["S099"], contract["student_ids"])
        self.assertEqual("students", contract["domain"])
        self.assertEqual("profile", contract["answer_style"])
        self.assertTrue(contract["must_not_use_previous_entities"])

    def test_latest_surname_becomes_database_entity(self):
        purpose = apply_contract_to_purpose(
            "gpa of boonmee",
            {
                "target_domain": "student_gpa",
                "answer_intent": "read",
                "should_use_database": True,
                "explicit_entities": {"student_ids": ["S099"]},
            },
        )

        self.assertEqual("students", purpose["target_domain"])
        self.assertEqual(["boonmee"], purpose["explicit_entities"]["last_names"])
        self.assertEqual([], purpose["explicit_entities"]["student_ids"])
        self.assertFalse(purpose["use_history"])
        self.assertTrue(purpose["must_not_use_previous_entities"])

    def test_second_surname_replaces_previous_context(self):
        purpose = apply_contract_to_purpose(
            "gpa of aksornchai",
            {
                "target_domain": "student_gpa",
                "answer_intent": "read",
                "should_use_database": True,
                "explicit_entities": {"last_names": ["boonmee"]},
            },
        )

        self.assertEqual(["aksornchai"], purpose["explicit_entities"]["last_names"])
        self.assertFalse(purpose["use_history"])

    def test_student_table_is_records_not_schema(self):
        contract = build_latest_message_contract("list students as a table")

        self.assertEqual("students", contract["domain"])
        self.assertEqual("list", contract["intent"])
        self.assertEqual("table", contract["presentation"]["view"])
        self.assertFalse(contract["is_schema_request"])

    def test_columns_in_student_table_is_schema(self):
        contract = build_latest_message_contract("show columns in the student table")

        self.assertEqual("database_map", contract["domain"])
        self.assertTrue(contract["is_schema_request"])
        self.assertEqual("text", contract["presentation"]["view"])

    def test_live_family_activity_is_refused(self):
        purpose = apply_contract_to_purpose(
            "what is the Boonmee family doing right now",
            {
                "target_domain": "students",
                "answer_intent": "read",
                "should_use_database": True,
                "explicit_entities": {"last_names": ["boonmee"]},
            },
        )

        self.assertEqual("clarify", purpose["target_domain"])
        self.assertEqual("clarify", purpose["answer_intent"])
        self.assertFalse(purpose["should_use_database"])
        self.assertFalse(purpose["use_history"])

    def test_recommended_subjects_are_not_a_fake_gpa_study_term(self):
        contract = build_latest_message_contract("rank me top 5 subject that recommended")

        self.assertEqual("subjects", contract["domain"])
        self.assertEqual("rank", contract["intent"])
        self.assertEqual("subject_rank", contract["answer_style"])
        self.assertEqual(5, contract["subject_ranking"]["top_n"])
        self.assertIsNone(contract["stat_query"])


class V30AuthoritativePlannerTests(unittest.TestCase):
    @staticmethod
    def _purpose(message):
        base = {
            "source": "test",
            "target_domain": "normal_chat",
            "answer_intent": "read",
            "should_use_database": False,
            "confidence": 1.0,
            "explicit_entities": {},
        }
        return apply_contract_to_purpose(message, base)

    def test_surname_gpa_uses_filtered_mongo_read(self):
        plan = plan_from_purpose(
            message="gpa of boonmee",
            language="en",
            user_role="admin",
            purpose=self._purpose("gpa of boonmee"),
        )

        self.assertEqual("mongodb_student_tool", plan["tool_name"])
        self.assertEqual("read_students", plan["arguments"]["operation"])
        self.assertEqual(["boonmee"], plan["arguments"]["requested_last_names"])
        self.assertIn("$regex", plan["arguments"]["query_filter"]["name"])
        self.assertEqual("gpa", plan["arguments"]["answer_style"])

    def test_realtime_request_never_calls_database(self):
        message = "what is the Boonmee family doing right now"
        plan = plan_from_purpose(
            message=message,
            language="en",
            user_role="admin",
            purpose=self._purpose(message),
        )

        self.assertEqual("none", plan["tool_name"])
        self.assertEqual("unsupported_realtime", plan["arguments"]["reason"])

    def test_recommended_subjects_use_role_scoped_subject_summary(self):
        message = "rank me top 5 subject that recommended"
        plan = plan_from_purpose(
            message=message,
            language="en",
            user_role="admin",
            purpose=self._purpose(message),
        )

        self.assertEqual("mongodb_student_tool", plan["tool_name"])
        self.assertEqual("subject_summary", plan["arguments"]["operation"])
        self.assertEqual("subject_rank", plan["arguments"]["answer_style"])
        self.assertEqual("student_count", plan["arguments"]["ranking_basis"])
        self.assertEqual(5, plan["arguments"]["top_n"])
        self.assertNotIn("study_term", plan["arguments"])

        result = {
            "success": True,
            "data": {
                "type": "subject_summary",
                "unique_subject_count": 2,
                "total_subject_grade_records": 15,
                "student_count_in_scope": 10,
                "top_subjects": [
                    {"subject": "Database Systems", "student_count": 8},
                    {"subject": "Business Analytics", "student_count": 7},
                ],
            },
        }
        answer = deterministic_database_answer(message, "en", plan, result)
        self.assertIn("ranked by distinct enrolled-student count", answer)
        self.assertIn("not a personalized recommendation", answer)
        self.assertNotIn("match recommended", answer)

        student_plan = dict(plan)
        student_plan["user_role"] = "student"
        student_answer = deterministic_database_answer(message, "en", student_plan, result)
        self.assertIn("only subjects already in your own record", student_answer)
        self.assertIn("cannot rank new courses as a personalized recommendation", student_answer)

    def test_normal_chat_source_does_not_apply_learning_memory(self):
        source = (ROOT / "backend" / "app" / "main.py").read_text()
        chat_source = source[source.index("def _chat_impl"):source.index('@app.get("/chat/debug/last")')]

        self.assertNotIn("apply_relevant_learning_memory", chat_source)
        self.assertNotIn("learn_from_user_correction", chat_source)
        self.assertIn('"normal_chat_learning_memory_enabled": False', chat_source)

    def test_table_payload_is_saved_in_message_metadata(self):
        source = (ROOT / "backend" / "app" / "main.py").read_text()
        chat_source = source[source.index("def _chat_impl"):source.index('@app.get("/chat/debug/last")')]

        self.assertIn('"data_table": chat_table', chat_source)

    def test_debug_trace_endpoint_is_admin_only(self):
        source = (ROOT / "backend" / "app" / "main.py").read_text()
        endpoint = source[source.index('@app.get("/chat/debug/last")'):source.index('@app.get("/chat/history")')]

        self.assertIn("_verified_admin_identity(request)", endpoint)

    def test_frontend_health_check_is_invisible_and_trace_is_admin_only(self):
        source = (ROOT / "frontend" / "src" / "App.jsx").read_text()

        self.assertIn("runBackgroundHealthCheck", source)
        self.assertIn("/admin/system-check/run?user_role=admin", source)
        self.assertNotIn("Train AI router", source)
        self.assertNotIn("Run system check", source)
        self.assertIn("userRole === 'admin' && renderDebugTracePanel()", source)


if __name__ == "__main__":
    unittest.main()
