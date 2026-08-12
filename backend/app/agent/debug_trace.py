"""V7 Debug Trace helpers.

This module creates safe, human-readable traces for each chat turn so a developer
can see how the AI/database agent made a decision without exposing giant raw
payloads or sensitive private fields.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

SENSITIVE_KEYS = {
    "email", "phone", "national_id", "passport_id", "address", "token",
    "api_key", "password", "secret", "full_text", "text_preview", "embedding",
}


def _safe_str(value: Any, max_len: int = 600) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[:max_len].rstrip() + "..."
    return text


def _redact_value(key: str, value: Any) -> Any:
    low_key = str(key or "").lower()
    if low_key in SENSITIVE_KEYS or any(s in low_key for s in ["password", "secret", "token", "api_key"]):
        if value in (None, "", [], {}):
            return value
        return "[redacted]"
    return value


def safe_compact(value: Any, *, max_depth: int = 3, max_items: int = 8, max_text: int = 700) -> Any:
    """Return a compact JSON-safe preview of nested tool/planner data."""
    if max_depth < 0:
        return "..."
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= max_items:
                out["_truncated_keys"] = max(0, len(value) - max_items)
                break
            redacted = _redact_value(str(k), v)
            if redacted == "[redacted]":
                out[str(k)] = redacted
            else:
                out[str(k)] = safe_compact(redacted, max_depth=max_depth - 1, max_items=max_items, max_text=max_text)
        return out
    if isinstance(value, list):
        items = [safe_compact(v, max_depth=max_depth - 1, max_items=max_items, max_text=max_text) for v in value[:max_items]]
        if len(value) > max_items:
            items.append({"_truncated_items": len(value) - max_items})
        return items
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return _safe_str(value, max_text)
        return value
    return _safe_str(value, max_text)


def summarize_tool_result(result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = result or {}
    data = result.get("data")
    summary: Dict[str, Any] = {
        "success": result.get("success"),
        "tool_name": result.get("tool_name") or result.get("tool"),
        "result_type": type(data).__name__,
    }
    if isinstance(data, dict):
        summary["data_keys"] = list(data.keys())[:12]
        for key in ["type", "operation", "scope", "count", "total", "total_records", "student_id", "student_ids", "subject_count", "unique_subject_count", "study_term", "statistic", "field", "metric_label", "value", "values_used_count", "ranking_applied", "query_filter"]:
            if key in data:
                summary[key] = safe_compact(data.get(key), max_depth=2)
        # Common result shapes.
        for list_key in ["students", "rows", "matches", "documents", "preview_rows", "subjects"]:
            if isinstance(data.get(list_key), list):
                summary[f"{list_key}_count"] = len(data.get(list_key) or [])
                summary[f"{list_key}_preview"] = safe_compact((data.get(list_key) or [])[:3], max_depth=2)
    elif isinstance(data, list):
        summary["row_count"] = len(data)
        summary["preview"] = safe_compact(data[:3], max_depth=2)
    else:
        summary["preview"] = safe_compact(data, max_depth=1)
    if result.get("error"):
        summary["error"] = _safe_str(result.get("error"), 500)
    if result.get("policy_note"):
        summary["policy_note"] = _safe_str(result.get("policy_note"), 300)
    if result.get("access_scope"):
        summary["access_scope"] = safe_compact(result.get("access_scope"), max_depth=2)
    return summary


def build_debug_trace(
    *,
    message: str,
    effective_question: str,
    language: str,
    user_role: str,
    session_id: str,
    plan: Dict[str, Any],
    tool_result: Dict[str, Any],
    validation: Dict[str, Any],
    answer: str,
    learning_memory_used: bool = False,
    learning_memory_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a trace object suitable for frontend display."""
    plan = plan or {}
    trace = {
        "version": "V7_DEBUG_TRACE_PANEL",
        "session_id": session_id,
        "input": {
            "original_message": message,
            "effective_question": effective_question,
            "language": language,
            "user_role": user_role,
        },
        "learning_memory": {
            "used": bool(learning_memory_used),
            "memory_id": learning_memory_row.get("id") if isinstance(learning_memory_row, dict) else None,
            "learned_domain": learning_memory_row.get("learned_domain") if isinstance(learning_memory_row, dict) else None,
        },
        "purpose_analysis": safe_compact(plan.get("purpose_analysis"), max_depth=3),
        "purpose_contract": safe_compact(plan.get("purpose_contract"), max_depth=3),
        "local_training_hint": safe_compact(plan.get("local_training_hint"), max_depth=3),
        "selected_plan": {
            "selected_agent": plan.get("selected_agent"),
            "tool_name": plan.get("tool_name"),
            "role_prompt_name": plan.get("role_prompt_name"),
            "arguments": safe_compact(plan.get("arguments", {}), max_depth=3),
            "planner_warning": plan.get("planner_warning"),
            "reason": plan.get("reason") or plan.get("planner_reason") or (plan.get("orchestrator") or {}).get("reason"),
        },
        "execution_steps": safe_compact(plan.get("orchestrator_execution_trace") or [], max_depth=4, max_items=12),
        "validation": safe_compact(validation or plan.get("orchestrator_validation"), max_depth=4),
        "tool_result_summary": summarize_tool_result(tool_result),
        "answer_quality": {
            "answer_preview": _safe_str(answer, 900),
            "grounded_in_tool_result": plan.get("tool_name") != "none",
            "matched_operation": (plan.get("arguments") or {}).get("operation"),
            "matched_study_term": (plan.get("arguments") or {}).get("study_term"),
            "matched_ranking": safe_compact((plan.get("arguments") or {}).get("ranking"), max_depth=2),
            "matched_statistic": (plan.get("arguments") or {}).get("statistic"),
            "matched_metric_field": (plan.get("arguments") or {}).get("metric_field"),
        },
        "developer_hint": _developer_hint(plan, validation, tool_result),
    }
    return trace


def _developer_hint(plan: Dict[str, Any], validation: Dict[str, Any], tool_result: Dict[str, Any]) -> str:
    tool = plan.get("tool_name") or "none"
    valid = bool((validation or {}).get("is_valid", True))
    problems = (validation or {}).get("problems") or []
    if tool == "none":
        return "Normal chat: no database tool was used. If this should use database/PDF/Excel, improve purpose detection or schema mapping."
    if not valid:
        return "Validator still found a mismatch. Check required domain/entity/field contract and MCP tool result shape."
    if problems:
        return "Validated with warnings: " + _safe_str(", ".join(map(str, problems)), 400)
    return "Plan, tool result, and final answer passed the current validation contract."
