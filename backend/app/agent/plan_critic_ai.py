import json
from typing import Dict, Any

from app.agent.ai_client import ai_generate_text


PLAN_CRITIC_PROMPT = """
You are the Query Plan Critic AI.

You do not answer the user.
Your job is to check whether a database query plan correctly matches the user's request.

You receive:
1. Original user question
2. Current query plan

You must return only valid JSON.

Output format:
{
  "is_correct": true,
  "problem": null,
  "repaired_plan": null
}

If the plan is wrong, return:
{
  "is_correct": false,
  "problem": "short explanation",
  "repaired_plan": {
    "intent": "...",
    "goal": "...",
    "data_sources": [...],
    "operation": "...",
    "filters": [...],
    "select": [...],
    "sort": [...],
    "limit": 20,
    "create_report_if_over": 20,
    "needs_schema_lookup": false,
    "missing_data_risk": false,
    "clarifying_question": null,
    "answer_style": "summary",
    "confidence": 0.95
  }
}

Important rules:

1. If the user asks for one highest / best / top / most GPA student:
Use operation = "rank"
Use sort = [{"field":"gpa","direction":"desc"}]
Use limit = 1

2. If the user asks for one lowest / weakest / worst GPA student:
Use operation = "rank"
Use sort = [{"field":"gpa","direction":"asc"}]
Use limit = 1

3. If the user asks for students lower than a GPA:
Use operation = "filter"
Use filters = [{"field":"gpa","operator":"lt","value":number}]

4. If the user asks "list me 10":
Use limit = 10

5. If the user asks about a student ID like S035:
Use intent = "query_students"
Use filter student_id eq S035 or student_id argument S035

6. If the user asks about PDF, document, file, upload:
Use intent = "query_documents"

7. Do not repair a correct plan.
8. Do not invent data.
9. Keep the repaired plan safe and minimal.
"""


def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```json"):
        text = text.replace("```json", "", 1).strip()
    if text.startswith("```"):
        text = text.replace("```", "", 1).strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


def critique_and_repair_plan(
    user_message: str,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        prompt = f"""
Original user question:
{user_message}

Current query plan:
{json.dumps(plan, ensure_ascii=False)}

Check if this plan correctly matches the user request.
Return only JSON.
"""

        raw = ai_generate_text(
            system_prompt=PLAN_CRITIC_PROMPT,
            prompt=prompt,
            json_mode=True,
            timeout_env="GEMINI_INTENT_TIMEOUT",
            default_timeout=60,
            temperature=0.0,
            max_output_tokens=2048,
        )

        if not raw:
            return plan

        checked = json.loads(_clean_json_text(raw))

        if checked.get("is_correct") is True:
            return plan

        repaired = checked.get("repaired_plan")

        if isinstance(repaired, dict):
            return repaired

        return plan

    except Exception:
        return plan