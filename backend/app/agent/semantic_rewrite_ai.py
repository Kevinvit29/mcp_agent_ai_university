import json
import re
from typing import Any, Dict

from app.agent.ai_client import ai_generate_text


SEMANTIC_REWRITE_PROMPT = """
You are the Semantic Rewrite AI.

Your job is to rewrite the user's natural language question into a clearer database-planning meaning.

The user may ask in Thai, English, informal language, broken grammar, typo, or mixed language.

You do not answer the user.
You only return JSON.

Return this JSON format:

{
  "original_language": "thai | english | mixed | unknown",
  "rewritten_query": "clear English version of the user's database request",
  "target": "students | advisors | documents | campus_info | normal_chat | unknown",
  "operation_hint": "find | filter | rank | count | search | summarize | normal_chat | unknown",
  "filters_hint": [],
  "sort_hint": [],
  "limit_hint": null,
  "confidence": 0.0
}

Meaning rules:
- If the user asks for the student with the highest grade, best grade, most grade, high GPA, or similar meaning:
  target = students
  operation_hint = rank
  sort_hint = [{"field":"gpa","direction":"desc"}]
  limit_hint = 1

- If the user asks for the student with the lowest grade, worst grade, weakest grade, low GPA, or similar meaning:
  target = students
  operation_hint = rank
  sort_hint = [{"field":"gpa","direction":"asc"}]
  limit_hint = 1

- If the user asks for students under / below / lower than a GPA number:
  operation_hint = filter
  filters_hint = [{"field":"gpa","operator":"lt","value":number}]

- If the user asks for students who need improvement/support:
  operation_hint = rank
  sort_hint = [{"field":"gpa","direction":"asc"}]
  limit_hint = 10 unless user gives another number

- If the user mentions a student ID such as S035:
  target = students

- If the user asks about PDF/file/document/upload:
  target = documents

- If the user asks about cafeteria/building/room/location:
  target = campus_info

Examples:
Thai: "คนที่เกรดเยอะ"
Meaning: "student with the highest GPA"

Thai: "คนที่เกรดสูงสุด"
Meaning: "student with the highest GPA"

Thai: "ใครเกรดดีที่สุด"
Meaning: "student with the highest GPA"

Thai: "คนที่เกรดน้อย"
Meaning: "student with the lowest GPA"

Thai: "ใครต้องปรับปรุงเกรดบ้าง ขอ 10 คน"
Meaning: "10 students who need academic improvement"

Do not invent data.
Only rewrite the request.
"""


def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    return m.group(0) if m else text


def semantic_rewrite_for_planning(message: str) -> Dict[str, Any]:
    try:
        raw = ai_generate_text(
            system_prompt=SEMANTIC_REWRITE_PROMPT,
            prompt=f"User message:\n{message}\n\nRewrite it for database planning.",
            json_mode=True,
            timeout_env="GEMINI_INTENT_TIMEOUT",
            default_timeout=60,
            temperature=0.0,
            max_output_tokens=1200,
        )

        if not raw:
            return {}

        parsed = json.loads(_clean_json_text(raw))
        return parsed if isinstance(parsed, dict) else {}

    except Exception:
        return {}