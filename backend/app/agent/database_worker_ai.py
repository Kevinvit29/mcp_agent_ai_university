import json
import re
from typing import Any, Dict


DATABASE_WORKER_AI_PROMPT = """
You are the Database Worker AI.

You do not talk to the user directly.

Your job is to manage database work safely:
- organize data
- calculate new values
- clean data
- validate new data
- prepare insert/update plans
- create summaries
- calculate rankings
- detect missing or duplicate data

You must return only valid JSON.

You are not allowed to directly execute database changes.
You only create a safe action plan.

Output format:

{
  "worker_intent": "calculate | clean | import_new_data | update_calculated_field | validate | summarize | organize | no_action",
  "target_source": "mongodb_students | mongodb_advisors | postgres_programs | postgres_documents | campus_info | unknown",
  "operation": "student_risk_score | lowest_gpa | average_gpa | duplicate_check | normalize_fields | import_preview | import_commit | summary | unknown",
  "filters": [],
  "calculation": {
    "name": null,
    "formula_description": null,
    "output_field": null
  },
  "sort": [],
  "limit": 20,
  "dry_run": true,
  "requires_confirmation": true,
  "reason": "",
  "confidence": 0.0
}

Rules:

1. If the admin asks which students need improvement, use:
worker_intent = "calculate"
operation = "student_risk_score"

2. If the admin asks lowest grade or lowest GPA, use:
worker_intent = "calculate"
operation = "lowest_gpa"

3. If the admin asks average GPA, use:
worker_intent = "calculate"
operation = "average_gpa"

4. If the admin asks to clean, organize, or remove duplicate data, use:
worker_intent = "clean"

5. If the admin uploads or adds new data, use:
worker_intent = "import_new_data"
operation = "import_preview"
dry_run = true
requires_confirmation = true

6. If the admin says confirm import or confirm update, use:
operation = "import_commit"
dry_run = false

7. Any write action must use:
requires_confirmation = true

8. Never invent data.
9. If the database does not have enough information, set confidence below 0.6.
"""


def _extract_limit(message: str, default: int = 20) -> int:
    m = re.search(r"\b(?:list|show|top)?\s*(\d+)\b", message.lower())
    if m:
        return max(1, min(int(m.group(1)), 100))
    return default


def _fallback_database_worker_plan(message: str) -> Dict[str, Any]:
    low = message.lower()
    limit = _extract_limit(message)

    if any(x in low for x in ["improve", "support", "weak", "risk", "need help"]):
        return {
            "worker_intent": "calculate",
            "target_source": "mongodb_students",
            "operation": "student_risk_score",
            "filters": [],
            "calculation": {
                "name": "student_risk_score",
                "formula_description": "Rank students by low GPA, warning status, and weak subject grades.",
                "output_field": "risk_score"
            },
            "sort": [{"field": "risk_score", "direction": "desc"}],
            "limit": limit,
            "dry_run": True,
            "requires_confirmation": False,
            "reason": "Admin asked for students who need improvement.",
            "confidence": 0.9
        }

    if any(x in low for x in ["lowest gpa", "lowest grade", "worst grade"]):
        return {
            "worker_intent": "calculate",
            "target_source": "mongodb_students",
            "operation": "lowest_gpa",
            "filters": [],
            "calculation": {
                "name": "lowest_gpa",
                "formula_description": "Find the student with the lowest GPA.",
                "output_field": None
            },
            "sort": [{"field": "gpa", "direction": "asc"}],
            "limit": limit if limit != 20 else 1,
            "dry_run": True,
            "requires_confirmation": False,
            "reason": "Admin asked for lowest grade/GPA.",
            "confidence": 0.9
        }

    if any(x in low for x in ["average gpa", "avg gpa"]):
        return {
            "worker_intent": "calculate",
            "target_source": "mongodb_students",
            "operation": "average_gpa",
            "filters": [],
            "calculation": {
                "name": "average_gpa",
                "formula_description": "Calculate average GPA.",
                "output_field": None
            },
            "sort": [],
            "limit": limit,
            "dry_run": True,
            "requires_confirmation": False,
            "reason": "Admin asked for average GPA calculation.",
            "confidence": 0.9
        }

    if any(x in low for x in ["duplicate", "same student"]):
        return {
            "worker_intent": "clean",
            "target_source": "mongodb_students",
            "operation": "duplicate_check",
            "filters": [],
            "calculation": {
                "name": "duplicate_check",
                "formula_description": "Find possible duplicate student records.",
                "output_field": None
            },
            "sort": [],
            "limit": limit,
            "dry_run": True,
            "requires_confirmation": True,
            "reason": "Admin asked to check duplicate data.",
            "confidence": 0.85
        }

    if any(x in low for x in ["import", "upload", "add new data", "new student data"]):
        return {
            "worker_intent": "import_new_data",
            "target_source": "mongodb_students",
            "operation": "import_preview",
            "filters": [],
            "calculation": {
                "name": "import_preview",
                "formula_description": "Validate new data before inserting into database.",
                "output_field": None
            },
            "sort": [],
            "limit": limit,
            "dry_run": True,
            "requires_confirmation": True,
            "reason": "Admin wants to handle new data.",
            "confidence": 0.8
        }

    return {
        "worker_intent": "no_action",
        "target_source": "unknown",
        "operation": "unknown",
        "filters": [],
        "calculation": {
            "name": None,
            "formula_description": None,
            "output_field": None
        },
        "sort": [],
        "limit": limit,
        "dry_run": True,
        "requires_confirmation": False,
        "reason": "This request does not need Database Worker AI.",
        "confidence": 0.4
    }


def create_database_worker_plan(message: str, ai_json_func=None) -> Dict[str, Any]:
    """
    For now, use fallback rules.
    Later, you can connect the configured AI provider here.
    """
    return _fallback_database_worker_plan(message)