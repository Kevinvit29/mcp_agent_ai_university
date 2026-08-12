"""Conversation state helpers for Agent Orchestrator V1."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def last_user_message(history: Optional[List[Dict[str, Any]]]) -> str:
    for item in reversed(history or []):
        if str(item.get("role", "")).lower() == "user":
            content = str(item.get("content") or "").strip()
            if content:
                return content
    return ""


def last_assistant_message(history: Optional[List[Dict[str, Any]]]) -> str:
    for item in reversed(history or []):
        if str(item.get("role", "")).lower() == "assistant":
            content = str(item.get("content") or "").strip()
            if content:
                return content
    return ""


def recent_student_ids(history: Optional[List[Dict[str, Any]]]) -> List[str]:
    ids: List[str] = []
    for item in history or []:
        content = str(item.get("content") or "")
        for sid in re.findall(r"\bS\d{3,6}\b", content, flags=re.I):
            sid = sid.upper()
            if sid not in ids:
                ids.append(sid)
    return ids[-10:]


def resolve_followup_student_ids(message: str, history: Optional[List[Dict[str, Any]]]) -> List[str]:
    """Resolve pronouns/short continuations to recently displayed student IDs."""
    text = str(message or "").lower().strip()
    explicit = [
        value.upper()
        for value in re.findall(r"\bS\d{3,6}\b", message or "", flags=re.I)
    ]
    followup_signals = (
        "what about", "and ", "that student", "this student", "that one",
        "the same student", "compare that", "compare them", "their ", "them ",
        "those students", "เขา", "คนนี้", "คนนั้น", "แล้ว",
    )
    if not any(signal in text for signal in followup_signals):
        return explicit

    latest_context = ""
    for item in reversed(history or []):
        content = str(item.get("content") or "")
        if re.search(r"\bS\d{3,6}\b", content, flags=re.I):
            latest_context = content
            break
    recent = [
        value.upper()
        for value in re.findall(r"\bS\d{3,6}\b", latest_context, flags=re.I)
    ]
    recent = list(dict.fromkeys(recent))[-20:]
    plural = any(signal in text for signal in ("their ", "them ", "those students", "compare them"))
    resolved = list(recent if plural else recent[-1:])
    for value in explicit:
        if value not in resolved:
            resolved.append(value)
    return resolved


def is_correction_message(message: str) -> bool:
    text = (message or "").lower().strip()
    if re.search(r"\bS\d{3,6}\b", message or "", flags=re.I) or re.search(r"\bA\d{3}\b", message or "", flags=re.I):
        return False
    correction_signals = [
        "i mean", "not", "no,", "actually", "wrong", "mistake", "i said", "หมายถึง", "ไม่ใช่", "ผิด", "คือ",
    ]
    return any(signal in text for signal in correction_signals) or text in {"subject", "subjects", "วิชา", "ไฟล์", "เอกสาร"}


def build_context_for_planner(message: str, history: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    return {
        "latest_message": message,
        "previous_user_message": last_user_message(history),
        "previous_assistant_message": last_assistant_message(history),
        "recent_student_ids": recent_student_ids(history),
        "is_correction": is_correction_message(message),
        "recent_messages": [
            {"role": item.get("role"), "content": str(item.get("content") or "")[:600]}
            for item in (history or [])[-8:]
        ],
    }
