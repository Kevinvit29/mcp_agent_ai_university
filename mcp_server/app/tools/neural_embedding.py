"""Hybrid semantic embedding utilities for university table/file agents.

Default mode is local feature-hash retrieval so the app works without an
embedding quota.  When `NEURAL_EMBEDDING_PROVIDER=gemini` (or `auto` with a
key) is enabled, the same indexes are generated with real Gemini embedding
vectors.  The module always falls back to local vectors on network, quota, or
model errors so uploads and queries keep working.

This is semantic-index training, not fine-tuning a chat model.  Database rows
teach retrieval indexes what data exists; user corrections and evaluated query
plans are the data that can later train a routing model.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None

LOCAL_EMBEDDING_DIM = 384
DEFAULT_GEMINI_DIM = 768
MAX_CHUNK_CHARS = 1800
CHUNK_OVERLAP = 180
_WORD_RE = re.compile(r"[a-zA-Z0-9\u0E00-\u0E7F]+")

SYNONYM_GROUPS = [
    ("student learner pupil attendee", "student"),
    ("subject course class module lesson", "subject"),
    ("grade score mark result", "grade"),
    ("gpa average cgpa gradepoint", "gpa"),
    ("profile information info detail details record data", "profile"),
    ("advisor teacher lecturer instructor professor", "advisor"),
    ("file document pdf excel spreadsheet csv table upload", "document"),
    ("count number howmany total amount", "count"),
    ("lower below under less smaller", "lt"),
    ("higher above over greater more", "gt"),
]


def normalize_text(text: str) -> str:
    text = (text or "").lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokens(text: str) -> List[str]:
    text = normalize_text(text)
    tokens = _WORD_RE.findall(text)
    expanded = list(tokens)
    joined = " ".join(tokens)
    for words, canonical in SYNONYM_GROUPS:
        if any(w in joined for w in words.split()):
            expanded.append(canonical)
    for i in range(max(0, len(tokens) - 1)):
        expanded.append(tokens[i] + "_" + tokens[i + 1])
    return expanded[:2000]


def _bucket(token: str) -> int:
    digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
    return int.from_bytes(digest[:4], "little") % LOCAL_EMBEDDING_DIM


def _normalize_vector(values: Iterable[float]) -> List[float]:
    raw = [float(v) for v in values]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [round(v / norm, 7) for v in raw]


def _embed_local(text: str) -> List[float]:
    vec = [0.0] * LOCAL_EMBEDDING_DIM
    for token in _tokens(text):
        idx = _bucket(token)
        sign = -1.0 if (hash(token) & 1) else 1.0
        weight = 1.0 + min(len(token), 20) / 40.0
        vec[idx] += sign * weight
    return _normalize_vector(vec)


def configured_embedding_provider() -> str:
    configured = (os.getenv("NEURAL_EMBEDDING_PROVIDER") or "local").strip().lower()
    if configured == "auto":
        return "gemini" if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) else "local"
    return configured if configured in {"local", "gemini"} else "local"


def resolve_embedding_provider(provider: Optional[str] = None) -> str:
    """Return a provider that can be used consistently for one full index."""
    selected = (provider or configured_embedding_provider()).lower()
    if selected != "gemini":
        return "local"
    try:
        _embed_gemini("university semantic index health check", "document")
        return "gemini"
    except Exception:
        return "local"


def embedding_descriptor(provider: Optional[str] = None) -> Dict[str, Any]:
    selected = (provider or configured_embedding_provider()).lower()
    if selected == "gemini":
        return {
            "provider": "gemini",
            "model": os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2"),
            "dimension": int(os.getenv("GEMINI_EMBEDDING_DIM", str(DEFAULT_GEMINI_DIM))),
            "fallback": "local_hash_vector_v2",
        }
    return {"provider": "local", "model": "local_hash_vector_v2", "dimension": LOCAL_EMBEDDING_DIM}


def _task_prefix(text: str, task: str) -> str:
    # Gemini Embedding 2 uses task guidance in the input rather than the legacy
    # task_type parameter. Keep the texts short and symmetric with the query.
    if task == "query":
        return "Task: retrieve the most relevant university database row, table, or document chunk for this user question.\nQuery: " + text
    return "Task: represent this university database row, table schema, or document chunk for semantic retrieval.\nDocument: " + text


def _embed_gemini(text: str, task: str) -> List[float]:
    if requests is None:
        raise RuntimeError("requests dependency is unavailable")
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured for remote embeddings")
    model = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
    dimension = max(128, min(int(os.getenv("GEMINI_EMBEDDING_DIM", str(DEFAULT_GEMINI_DIM))), 3072))
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
    payload = {
        "model": f"models/{model}",
        "content": {"parts": [{"text": _task_prefix(str(text or "")[:24000], task)}]},
        "output_dimensionality": dimension,
    }
    response = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json=payload,
        timeout=float(os.getenv("GEMINI_EMBEDDING_TIMEOUT", "20")),
    )
    if not response.ok:
        raise RuntimeError(f"Gemini embedding request failed ({response.status_code}): {response.text[:300]}")
    body = response.json()
    values = ((body.get("embedding") or {}).get("values")) or []
    if not isinstance(values, list) or not values:
        raise RuntimeError("Gemini embedding response contained no vector values")
    return _normalize_vector(values)


def embed_text(text: str, task: str = "document", provider: Optional[str] = None) -> List[float]:
    """Return a normalized vector, falling back safely to local retrieval."""
    selected = (provider or configured_embedding_provider()).lower()
    if selected == "gemini":
        try:
            return _embed_gemini(text, task)
        except Exception:
            # Indexing must not fail just because a free-tier key is rate-limited.
            return _embed_local(text)
    return _embed_local(text)


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    aa = list(a or [])
    bb = list(b or [])
    if not aa or not bb:
        return 0.0
    n = min(len(aa), len(bb))
    dot = sum(float(aa[i]) * float(bb[i]) for i in range(n))
    na = math.sqrt(sum(float(x) * float(x) for x in aa[:n])) or 1.0
    nb = math.sqrt(sum(float(x) * float(x) for x in bb[:n])) or 1.0
    return float(dot / (na * nb))


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = re.sub(r"\s+", " ", text or " ").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind(". ", start, end), text.rfind(" ", start, end))
            if boundary > start + int(max_chars * 0.55):
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def row_to_text(row: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key, value in (row or {}).items():
        if value is None or value == "":
            continue
        parts.append(f"{key}: {value}")
    return " | ".join(parts)


def build_schema_text(structured_data: Dict[str, Any], filename: str = "") -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return a table-agent schema profile and searchable chunks."""
    structured = structured_data or {}
    source_type = str(structured.get("source_type") or "file").lower()
    chunks: List[Dict[str, Any]] = []
    schema: Dict[str, Any] = {
        "filename": filename or structured.get("filename"),
        "source_type": source_type,
        "capabilities": ["semantic_search", "question_answering", "table_lookup"],
        "sheets": [],
        "columns": [],
        "row_count": structured.get("total_rows"),
        "page_count": structured.get("total_pages"),
    }

    if source_type == "excel":
        schema["capabilities"] += ["row_search", "column_search", "numeric_summary", "sheet_agent"]
        for sheet in structured.get("sheets") or []:
            if not isinstance(sheet, dict):
                continue
            sheet_name = str(sheet.get("sheet_name") or "Sheet")
            columns = [str(c) for c in (sheet.get("columns") or [])]
            schema["sheets"].append({"sheet_name": sheet_name, "row_count": sheet.get("row_count"), "stored_row_count": sheet.get("stored_row_count"), "columns": columns, "numeric_summary": sheet.get("numeric_summary") or {}})
            for c in columns:
                if c not in schema["columns"]:
                    schema["columns"].append(c)
            chunks.append({"chunk_type": "sheet_schema", "sheet_name": sheet_name, "row_index": None, "page_number": None, "text": f"File {filename}. Sheet {sheet_name}. Columns: {', '.join(columns)}. Numeric summary: {sheet.get('numeric_summary') or {}}", "metadata": {"columns": columns, "numeric_summary": sheet.get("numeric_summary") or {}}})
            for idx, row in enumerate(sheet.get("rows") or []):
                if isinstance(row, dict):
                    chunks.append({"chunk_type": "excel_row", "sheet_name": sheet_name, "row_index": idx + 1, "page_number": None, "text": f"File {filename}. Sheet {sheet_name}. Row {idx + 1}. {row_to_text(row)}", "metadata": {"row": row, "columns": columns}})

    elif source_type in {"database_table", "mongodb_table", "postgres_table", "table"}:
        schema["capabilities"] += ["row_search", "column_search", "schema_search", "existing_database_agent"]
        tables = structured.get("tables") or ([] if structured.get("rows") is None else [structured])
        for table in tables:
            if not isinstance(table, dict):
                continue
            table_name = str(table.get("table_name") or table.get("collection") or structured.get("table_name") or filename or "table")
            columns = [str(c) for c in (table.get("columns") or [])]
            rows = [r for r in (table.get("rows") or []) if isinstance(r, dict)]
            schema.setdefault("tables", []).append({"table_name": table_name, "database": table.get("database") or structured.get("database"), "row_count": table.get("row_count") or len(rows), "stored_row_count": len(rows), "columns": columns, "primary_key": table.get("primary_key"), "description": table.get("description") or structured.get("description")})
            for c in columns:
                if c not in schema["columns"]:
                    schema["columns"].append(c)
            chunks.append({"chunk_type": "database_table_schema", "sheet_name": table_name, "row_index": None, "page_number": None, "text": f"Existing database table {table_name} in {table.get('database') or structured.get('database') or 'database'}. Columns: {', '.join(columns)}. Description: {table.get('description') or structured.get('description') or ''}", "metadata": {"table_name": table_name, "columns": columns, "database": table.get("database") or structured.get("database")}})
            for idx, row in enumerate(rows):
                chunks.append({"chunk_type": "database_row", "sheet_name": table_name, "row_index": idx + 1, "page_number": None, "text": f"Existing database table {table_name}. Row {idx + 1}. {row_to_text(row)}", "metadata": {"row": row, "columns": columns, "table_name": table_name}})

    elif source_type == "pdf":
        schema["capabilities"] += ["page_search", "chunk_search", "pdf_to_table"]
        rows = structured.get("rows") or []
        if isinstance(rows, list) and rows:
            for idx, row in enumerate(rows):
                if isinstance(row, dict):
                    page = row.get("Page") or row.get("page") or row.get("page_number")
                    chunks.append({"chunk_type": "pdf_extracted_row", "sheet_name": None, "row_index": idx + 1, "page_number": page, "text": f"File {filename}. Page {page or '-'} row {idx + 1}. {row_to_text(row)}", "metadata": {"row": row}})
        full_text = structured.get("full_text") or structured.get("searchable_text") or ""
        for i, chunk in enumerate(chunk_text(full_text)):
            chunks.append({"chunk_type": "pdf_text_chunk", "sheet_name": None, "row_index": i + 1, "page_number": None, "text": f"File {filename}. PDF text chunk {i + 1}. {chunk}", "metadata": {}})

    else:
        searchable = structured.get("searchable_text") or str(structured)[:50000]
        for i, chunk in enumerate(chunk_text(searchable)):
            chunks.append({"chunk_type": "generic_chunk", "sheet_name": None, "row_index": i + 1, "page_number": None, "text": f"File {filename}. Chunk {i + 1}. {chunk}", "metadata": {}})

    return schema, chunks
