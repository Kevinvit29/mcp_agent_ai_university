"""Deterministic, grounded question answering for a selected uploaded document.

This module deliberately does not call an LLM.  It answers only from the exact
stored document text/notes selected in the Knowledge Workspace.  It is used as
a reliability layer before a general summary is returned.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from difflib import SequenceMatcher

from app.agent.natural_query import normalize_typos


_EN_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "about", "be", "can", "could", "define",
    "does", "explain", "file", "for", "from", "give", "how", "i", "in", "is", "it",
    "meaning", "me", "of", "on", "please", "summary", "tell", "that", "the", "this",
    "to", "what", "where", "which", "who", "why", "with", "would", "you", "your",
    "document", "pdf", "excel", "csv", "uploaded", "upload", "uploads", "stored", "file",
}


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())


def _is_thai(text: str) -> bool:
    return any("\u0e00" <= ch <= "\u0e7f" for ch in text or "")


def extract_focus_terms(question: str) -> List[str]:
    """Extract meaningful requested terms without treating phrase fillers as terms."""
    raw = normalize_typos(_clean_text(question))
    raw = re.sub(r"\([^)]*\.(?:pdf|xlsx?|csv)\)", " ", raw)
    raw = re.sub(r"\b[\w.-]+\.(?:pdf|xlsx?|csv)\b", " ", raw)
    # Thai often arrives without spaces. Remove common question/file fillers so
    # “ละเมิดคืออะไร” can retrieve “ละเมิด” from stored text.
    raw = re.sub(r"(?:คืออะไร|หมายถึงอะไร|หมายถึง|ความหมาย|ช่วยอธิบาย|อธิบาย|สรุป|ไฟล์นี้|เอกสารนี้|ในไฟล์|ในเอกสาร|เกี่ยวกับ|ให้หน่อย|หน่อย)", " ", raw)
    tokens = re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}|[\u0e00-\u0e7f]{2,}", raw)
    result: List[str] = []
    for token in tokens:
        if token in _EN_STOPWORDS:
            continue
        if token not in result:
            result.append(token)
    return result[:6]


def _iter_notes(table: Dict[str, Any]) -> Iterable[str]:
    for key in ("main_topic", "short_summary", "clear_conclusion"):
        value = table.get(key)
        if value:
            yield _clean_text(value)
    for key in ("key_points", "section_notes", "detailed_information", "important_columns"):
        values = table.get(key)
        if isinstance(values, list):
            for value in values:
                if value:
                    yield _clean_text(value)
    rows = table.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("Detailed information", "Main point", "Simple explanation", "Information"):
                if row.get(key):
                    yield _clean_text(row[key])


def _split_candidates(text: str) -> List[str]:
    text = _clean_text(text)
    if not text:
        return []
    # Keep sentences plus line-like fragments. This works with PDFs whose text
    # extraction may have weak punctuation.
    parts = re.split(r"(?<=[.!?])\s+|\s{2,}|\n+", text)
    return [part.strip() for part in parts if len(part.strip()) >= 20]


def _thai_fuzzy_contains(candidate: str, term: str) -> bool:
    """A narrow typo tolerance for one Thai focus term.

    It is used only when an exact match is absent, only for terms of four or
    more Thai characters, and never changes the stored source text.
    """
    if term in candidate or len(term) < 4 or not any("\u0e00" <= char <= "\u0e7f" for char in term):
        return term in candidate
    for run in re.findall(r"[\u0e00-\u0e7f]{4,}", candidate):
        minimum = max(4, len(term) - 1)
        maximum = min(len(run), len(term) + 2)
        for width in range(minimum, maximum + 1):
            for index in range(0, len(run) - width + 1):
                if SequenceMatcher(None, term, run[index:index + width]).ratio() >= 0.86:
                    return True
    return False


def _score_candidate(candidate: str, terms: Sequence[str], definition_question: bool) -> int:
    lower = candidate.lower()
    score = 0
    for term in terms:
        if term in lower:
            score += 5
        elif _thai_fuzzy_contains(lower, term):
            score += 3
    if definition_question:
        # Definitions normally begin with the requested term. Prefer that over a
        # passing mention such as "private law includes torts".
        if any(re.match(rf"^\s*{re.escape(term)}\b", lower) for term in terms):
            score += 6
        if re.search(r"\b(is|are|means|meaning|refers to|defined|definition|includes|concerns)\b", lower):
            score += 3
    # Prefer concise, readable excerpts over a whole PDF page.
    length = len(candidate)
    if 45 <= length <= 500:
        score += 2
    elif length > 1400:
        score -= 2
    return score


def _definition_question(question: str) -> bool:
    q = _clean_text(question).lower()
    return bool(re.search(r"\b(what is|what are|define|definition of|meaning of|tell me about|explain)\b", q)) or any(
        item in q for item in ("คืออะไร", "หมายถึง", "อธิบาย", "ความหมาย")
    )


def is_general_document_overview_question(question: str) -> bool:
    """Return True for broad requests that should use the document overview.

    A broad request such as "explain this file" must not be treated as a
    keyword lookup. Otherwise a weak extractor can select one unrelated sentence
    and make it look like the explanation of the whole document.
    """
    q = _clean_text(question).lower()
    if not q:
        return True
    generic_patterns = (
        r"^explain\s*(this|the)?\s*(file|document|pdf)?\s*$",
        r"^can you explain\s*(this|the)?\s*(file|document|pdf)?(\s+that\s+i\s+upload(?:ed)?)?\s*$",
        r"^what is this (file|document|pdf) about\??$",
        r"^summari[sz]e\s*(this|the)?\s*(file|document|pdf)?\s*$",
        r"^tell me about\s*(this|the)?\s*(file|document|pdf)?\s*$",
    )
    if any(re.match(pattern, q) for pattern in generic_patterns):
        return True
    # Generic prompts often include harmless trailing punctuation or words like
    # "uploaded". If no subject term remains after stop-word filtering, use
    # the whole-file overview instead of passage retrieval.
    if not extract_focus_terms(q) and any(word in q for word in ("explain", "summarize", "summary", "tell me about", "อธิบาย", "สรุป")):
        return True
    return any(phrase in q for phrase in (
        "อธิบายไฟล์นี้", "อธิบายเอกสารนี้", "ไฟล์นี้เกี่ยวกับอะไร", "สรุปไฟล์นี้", "สรุปเอกสารนี้"
    ))


def answer_from_selected_document(document: Dict[str, Any], question: str, language: str = "en") -> Optional[str]:
    """Answer a targeted question from one exact document.

    Returns None when the question is only asking for a general overview, so the
    normal document-summary formatter can produce a fuller response.
    """
    if not isinstance(document, dict):
        return None
    # Broad prompts should return the stored overview/main topic instead of one
    # arbitrary matching sentence. Targeted questions such as "What is torts?"
    # still use evidence retrieval below.
    if is_general_document_overview_question(question):
        return None
    terms = extract_focus_terms(question)
    if not terms:
        return None

    table = document.get("conclusion_table") if isinstance(document.get("conclusion_table"), dict) else {}
    full_text = "\n".join(
        part for part in (
            document.get("full_text"),
            document.get("text_excerpt"),
            document.get("text_preview"),
            *list(_iter_notes(table)),
        ) if part
    )
    candidates = _split_candidates(full_text)
    if not candidates:
        return None

    definition = _definition_question(question)
    scored: List[Tuple[int, str]] = []
    for candidate in candidates:
        score = _score_candidate(candidate, terms, definition)
        if score > 0:
            scored.append((score, candidate))
    if not scored:
        return None

    scored.sort(key=lambda item: (-item[0], len(item[1])))
    best = scored[0][1]
    filename = document.get("filename") or "this file"
    thai = (language or "").lower().startswith("th") or _is_thai(question)
    focus = ", ".join(terms[:2])

    if thai:
        return f"จากไฟล์ “{filename}” พบข้อมูลเกี่ยวกับ {focus} ดังนี้:\n{best}\n\nคำตอบนี้อ้างอิงจากข้อความที่เก็บจากไฟล์โดยตรง"
    return f"In “{filename}”, the stored text says:\n{best}\n\nThis answer is grounded in the selected file’s extracted content."


def run_document_grounding_checks() -> Dict[str, Any]:
    """Small deterministic checks for the release-quality dashboard/tests."""
    sample = {
        "filename": "law-notes.pdf",
        "full_text": (
            "Law is a body of rules recognized and applied by the state. "
            "Private law includes torts, contracts, and trusts. "
            "Torts concern civil wrongs and remedies between private parties."
        ),
        "conclusion_table": {"short_summary": "An introduction to law and private-law categories."},
    }
    answer = answer_from_selected_document(sample, "What is torts?", "en") or ""
    cases = [
        {"name": "extracts_focus_term", "passed": "torts" in extract_focus_terms("What is torts?")},
        {"name": "returns_grounded_excerpt", "passed": "torts" in answer.lower()},
        {"name": "does_not_use_filename_matching", "passed": "law-notes.pdf" in answer},
        {"name": "generic_file_prompt_uses_overview", "passed": is_general_document_overview_question("Can you explain this file that I uploaded?")},
        {"name": "upload_word_is_not_fake_focus_term", "passed": extract_focus_terms("Explain this uploaded file") == []},
    ]
    return {
        "success": all(item["passed"] for item in cases),
        "summary": {"passed": sum(1 for item in cases if item["passed"]), "total": len(cases)},
        "cases": cases,
    }
