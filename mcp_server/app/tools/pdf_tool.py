from typing import Dict, Any
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parent.parent / "data" / "university_policy.txt"

def pdf_tool(arguments: Dict[str, Any]) -> Dict[str, Any]:
    query = arguments.get("query", "")
    content = POLICY_PATH.read_text(encoding="utf-8")
    return {
        "source": "university_policy_mock.pdf",
        "query": query,
        "content": content
    }
