import os
import re
from difflib import SequenceMatcher
from typing import Dict, Any, List, Tuple
from app.tools.neural_embedding import embed_text, cosine_similarity, embedding_descriptor, configured_embedding_provider
import psycopg2
from psycopg2.extras import RealDictCursor


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        database=os.getenv("POSTGRES_DB", "university_db"),
        user=os.getenv("POSTGRES_USER", "university_user"),
        password=os.getenv("POSTGRES_PASSWORD", "university_pass"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        cursor_factory=RealDictCursor,
    )


COMMON_DOC_TERMS = [
    "policy", "announcement", "guideline", "rule", "regulation", "document", "pdf", "excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "dataset", "upload", "uploaded", "stored", "table", "rows", "columns", "conclusion",
    "book", "books", "funding", "grant", "manual", "summary", "conclusion",
    "lesson", "lecture", "homework", "assignment", "material", "materials", "syllabus", "subject", "course",
    "calculus", "programming", "business", "english", "marketing", "writing", "report", "essay", "article", "chapter", "notes", "worksheet", "politics",
    "ประกาศ", "นโยบาย", "หลักเกณฑ์", "ระเบียบ", "ข้อบังคับ", "เอกสาร", "ไฟล์",
    "ตำรา", "หนังสือ", "ทุน", "สนับสนุน", "มหาวิทยาลัย", "ศูนย์ตำรา", "จ่าย", "เบิก", "จำหน่าย", "ขาย", "ขอรับ",
    "บทเรียน", "การบ้าน", "งาน", "วิชา", "แคลคูลัส", "เขียน", "การตลาด", "excel", "เอ็กเซล", "ตาราง", "ชีต", "ข้อมูล",
]




TYPO_SEARCH_REPLACEMENTS = {
    "wht": "what",
    "wat": "what",
    "gade": "grade",
    "grde": "grade",
    "gard": "grade",
    "subjet": "subject",
    "subjct": "subject",
    "re prot": "report",
    "re port": "report",
    "repo rt": "report",
    "repot": "report",
    "reprot": "report",
    "rport": "report",
    "writting": "writing",
    "writng": "writing",
    "wrting": "writing",
    "pdf beside": "uploaded pdfs",
    "pdf besides": "uploaded pdfs",
}

STOPWORDS = {
    "what", "which", "please", "tell", "about", "give", "show", "already", "upload", "uploads", "uploaded", "advisor", "teacher",
    "student", "subject", "from", "this", "that", "then", "with", "there", "their", "your", "what's", "whats",
    "คือ", "อะไร", "ขอ", "ช่วย", "หน่อย", "เกี่ยวกับ"
}


def _normalize_query_text(keyword: str) -> str:
    text = (keyword or "").lower().strip()
    text = text.replace("_", " ").replace("-", " ")
    for wrong, right in TYPO_SEARCH_REPLACEMENTS.items():
        text = text.replace(wrong, right)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _similarity(a: str, b: str) -> float:
    a = re.sub(r"[^a-z0-9\u0E00-\u0E7F]+", " ", (a or "").lower()).strip()
    b = re.sub(r"[^a-z0-9\u0E00-\u0E7F]+", " ", (b or "").lower()).strip()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _expand_fuzzy_terms(tokens: List[str]) -> List[str]:
    expanded: List[str] = []
    common = [t for t in COMMON_DOC_TERMS if re.match(r"^[a-z0-9]{4,}$", t)]
    for token in tokens:
        expanded.append(token)
        if len(token) < 4:
            continue
        for term in common:
            ratio = _similarity(token, term)
            if ratio >= 0.78 and term not in expanded:
                expanded.append(term)
                break
    return expanded


def _extract_search_terms(keyword: str) -> List[str]:
    text = _normalize_query_text(keyword)
    terms: List[str] = []
    raw_tokens = [t for t in re.findall(r"[a-z0-9฀-๿]{2,}", text) if t not in STOPWORDS]
    # Try to repair split words such as "re prot" -> "report" before scoring documents.
    joined_windows: List[str] = []
    for i in range(len(raw_tokens) - 1):
        joined_windows.append(raw_tokens[i] + raw_tokens[i + 1])
    tokens = raw_tokens + joined_windows
    for t in _expand_fuzzy_terms(tokens):
        if len(t) >= 3 and t not in terms:
            terms.append(t)
    for t in COMMON_DOC_TERMS:
        if t.lower() in text and t not in terms:
            terms.append(t)
    if text and text not in terms and len(text) <= 120:
        terms.append(text)
    return terms[:16]


def _row_created_iso(row: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(row)
    if row.get("created_at"):
        row["created_at"] = row["created_at"].isoformat()
    return row


def _build_relevant_text_excerpt(full_text: str, terms: List[str], max_total: int = 30000, window: int = 2200) -> str:
    """Return relevant snippets from the full document, not only the first page.

    The old version gave the final AI only full_text[:14000]. If the answer was later
    in the PDF, the ranking could find the document but the response AI could not see
    the matched paragraph. This keeps later matches visible.
    """
    text = str(full_text or "")
    if not text:
        return ""
    clean_terms = [t.lower() for t in (terms or []) if isinstance(t, str) and len(t.strip()) >= 3]
    lowered = text.lower()
    snippets: List[str] = []
    used_ranges: List[tuple[int, int]] = []
    for term in clean_terms:
        pos = lowered.find(term)
        if pos < 0:
            continue
        start = max(0, pos - window)
        end = min(len(text), pos + window)
        # Avoid nearly duplicate windows.
        if any(not (end < a or start > b) for a, b in used_ranges):
            continue
        used_ranges.append((start, end))
        snippets.append(text[start:end].strip())
        if sum(len(s) for s in snippets) >= max_total:
            break
    if snippets:
        return "\n\n--- Relevant document snippet ---\n\n".join(snippets)[:max_total]
    return text[:max_total]


def _rank_documents(rows: List[Dict[str, Any]], keyword: str) -> List[Dict[str, Any]]:
    normalized_keyword = _normalize_query_text(keyword)
    terms = _extract_search_terms(keyword)
    ranked = []
    for row in rows:
        haystack = " ".join(str(row.get(k) or "") for k in [
            "filename", "summary", "text_preview", "full_text", "detected_language", "extraction_method",
            "source_type", "storage_target", "cloned_agent_name", "structured_data",
            "subject_code", "subject_name", "advisor_id", "uploaded_by",
        ]).lower()
        table = row.get("conclusion_table") or {}
        structured = row.get("structured_data") or {}
        haystack += " " + str(table).lower() + " " + str(structured).lower()
        score = 0
        matched_terms: List[str] = []
        for term in terms:
            term_l = term.lower()
            if term_l and term_l in haystack:
                score += 3 if term_l in COMMON_DOC_TERMS else 2
                matched_terms.append(term_l)
        filename = str(row.get("filename") or "").lower()
        subject = str(row.get("subject_name") or "").lower()
        searchable_title = _normalize_query_text(filename.rsplit('.', 1)[0])
        for term in terms:
            term_l = term.lower()
            if term_l in filename:
                score += 5
                if term_l not in matched_terms:
                    matched_terms.append(term_l)
            if term_l in subject:
                score += 6
                if term_l not in matched_terms:
                    matched_terms.append(term_l)
        # Fuzzy title matching helps with titles typed as "writing re prot" for Writing_a_report.pdf.
        if normalized_keyword:
            title_ratio = _similarity(normalized_keyword, searchable_title)
            subject_ratio = _similarity(normalized_keyword, subject)
            if title_ratio >= 0.55:
                score += int(title_ratio * 10)
            if subject_ratio >= 0.55:
                score += int(subject_ratio * 8)
            if title_ratio >= 0.7:
                matched_terms.append("title≈" + searchable_title)
        row = _row_created_iso(row)
        row["match_score"] = score
        row["matched_terms"] = sorted(set(matched_terms))[:10]
        row["normalized_query"] = normalized_keyword
        full_text = row.pop("full_text", "") or ""
        row["text_excerpt"] = _build_relevant_text_excerpt(full_text, terms, max_total=30000)
        structured = row.get("structured_data") or {}
        if isinstance(structured, dict):
            preview = {
                "source_type": structured.get("source_type"),
                "storage_mode": structured.get("storage_mode"),
                "sheet_count": structured.get("sheet_count"),
                "total_rows": structured.get("total_rows"),
                "total_pages": structured.get("total_pages"),
                "sample_rows": structured.get("sample_rows", [])[:8],
                "page_summaries": structured.get("page_summaries", [])[:20],
                "sheets": [
                    {
                        "sheet_name": sheet.get("sheet_name"),
                        "row_count": sheet.get("row_count"),
                        "stored_row_count": sheet.get("stored_row_count"),
                        "columns": sheet.get("columns", [])[:40],
                        "sample_rows": sheet.get("sample_rows", [])[:5],
                        "numeric_summary": sheet.get("numeric_summary", {}),
                    }
                    for sheet in (structured.get("sheets") or [])[:5]
                    if isinstance(sheet, dict)
                ],
            }
            # For PDF->Excel storage, include matched extraction rows so the final AI
            # can answer from later pages, not only the first text excerpt.
            if structured.get("source_type") == "pdf":
                rows = structured.get("rows") or []
                matched_rows = []
                term_l = [t.lower() for t in terms if len(t) >= 3]
                for item in rows:
                    text_value = str(item.get("Extracted text") or "")
                    low_text = text_value.lower()
                    if term_l and any(t in low_text for t in term_l):
                        matched_rows.append(item)
                    if len(matched_rows) >= 12:
                        break
                preview["matched_rows"] = matched_rows or rows[:8]
            row["structured_preview"] = preview
        ranked.append(row)
    if terms:
        ranked.sort(key=lambda r: (r.get("match_score", 0), r.get("created_at") or ""), reverse=True)
    return ranked


def _select_ranked(rows: List[Dict[str, Any]], keyword: str, operation: str) -> Dict[str, Any]:
    ranked = _rank_documents(rows, keyword)
    if operation == "list_documents":
        cleaned = []
        for row in ranked[:30]:
            row = dict(row)
            row.pop("full_text", None)
            row["text_excerpt"] = (row.pop("text_preview", "") or row.get("text_excerpt") or "")[:1000]
            cleaned.append(row)
        return {"success": True, "operation": operation, "data": cleaned}

    if keyword:
        matched = [r for r in ranked if r.get("match_score", 0) > 0]
        selected = matched[:8] if matched else ranked[:8]
        note = "matched_uploaded_documents" if matched else "no_exact_match_returning_recent_documents"
    else:
        selected = ranked[:8]
        note = "recent_uploaded_documents"
    return {"success": True, "operation": operation, "search_terms": _extract_search_terms(keyword), "normalized_query": _normalize_query_text(keyword), "note": note, "data": selected}


def _fetch_admin_documents(cur) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, filename, uploaded_by, summary, conclusion_table,
               text_preview, full_text, extraction_method, detected_language,
               source_type, storage_target, cloned_agent_name, structured_data, mongo_object_id, created_at
        FROM admin_documents
        ORDER BY created_at DESC
        LIMIT 50;
        """
    )
    return cur.fetchall()


def _fetch_advisor_documents_for_role(cur, user_role: str, requester_student_id: str | None, requester_advisor_id: str | None) -> Tuple[List[Dict[str, Any]], str | None]:
    """Return only advisor PDF rows the current role may know."""
    if user_role == "student":
        if not requester_student_id:
            return [], "Student document search requires logged-in student ID."
        cur.execute(
            """
            SELECT d.id, d.advisor_id, d.subject_code, d.subject_name, d.filename, d.uploaded_by,
                   d.summary, d.conclusion_table, d.text_preview, d.full_text,
                   d.extraction_method, d.detected_language, d.source_type, d.storage_target,
                   d.cloned_agent_name, d.structured_data, d.mongo_object_id, d.created_at
            FROM advisor_documents d
            WHERE EXISTS (
                SELECT 1 FROM student_course_enrollments e
                WHERE e.student_id = %s
                  AND e.advisor_id = d.advisor_id
                  AND e.course_code = d.subject_code
            )
            ORDER BY d.created_at DESC
            LIMIT 80;
            """,
            (requester_student_id,),
        )
        return cur.fetchall(), None

    if user_role in {"advisor", "lecturer"}:
        if not requester_advisor_id:
            return [], "Advisor document search requires logged-in advisor ID."
        cur.execute(
            """
            SELECT id, advisor_id, subject_code, subject_name, filename, uploaded_by,
                   summary, conclusion_table, text_preview, full_text,
                   extraction_method, detected_language, source_type, storage_target,
                   cloned_agent_name, structured_data, mongo_object_id, created_at
            FROM advisor_documents
            WHERE advisor_id = %s
            ORDER BY created_at DESC
            LIMIT 80;
            """,
            (requester_advisor_id,),
        )
        return cur.fetchall(), None

    if user_role == "admin":
        cur.execute(
            """
            SELECT id, advisor_id, subject_code, subject_name, filename, uploaded_by,
                   summary, conclusion_table, text_preview, full_text,
                   extraction_method, detected_language, source_type, storage_target,
                   cloned_agent_name, structured_data, mongo_object_id, created_at
            FROM advisor_documents
            ORDER BY created_at DESC
            LIMIT 80;
            """
        )
        return cur.fetchall(), None

    return [], "Unknown role. Access denied."


def _fetch_lecturer_documents_for_role(cur, user_role: str, requester_lecturer_id: str | None, requester_advisor_id: str | None) -> Tuple[List[Dict[str, Any]], str | None]:
    """Return only files owned by the signed Lecturer and teaching assignment."""
    if user_role != "lecturer" or not requester_lecturer_id or not requester_advisor_id:
        return [], "Lecturer document search requires a signed Lecturer identity and teaching scope."
    cur.execute(
        """
        SELECT id, lecturer_id, teaching_scope_id, subject_code, subject_name, filename,
               uploaded_by, summary, conclusion_table, text_preview, full_text,
               extraction_method, detected_language, source_type, storage_target,
               cloned_agent_name, structured_data, mongo_object_id, created_at,
               'lecturer' AS document_scope
        FROM lecturer_documents
        WHERE lecturer_id = %s AND teaching_scope_id = %s
        ORDER BY created_at DESC
        LIMIT 80
        """,
        (requester_lecturer_id, requester_advisor_id),
    )
    return cur.fetchall(), None


def _fetch_course_documents_for_student(cur, requester_student_id: str | None) -> Tuple[List[Dict[str, Any]], str | None]:
    """Combine Advisor and Lecturer materials for the signed student's enrollments."""
    if not requester_student_id:
        return [], "Course document search requires a signed student identity."
    cur.execute(
        """
        SELECT d.id, d.advisor_id, NULL::VARCHAR AS lecturer_id,
               d.advisor_id AS teaching_scope_id, d.subject_code, d.subject_name,
               d.filename, d.uploaded_by, d.summary, d.conclusion_table, d.text_preview,
               d.full_text, d.extraction_method, d.detected_language, d.source_type,
               d.storage_target, d.cloned_agent_name, d.structured_data, d.mongo_object_id,
               d.created_at, 'advisor'::VARCHAR AS document_scope
        FROM advisor_documents d
        WHERE EXISTS (
            SELECT 1 FROM student_course_enrollments e
            WHERE e.student_id = %s AND e.advisor_id = d.advisor_id
              AND e.course_code = d.subject_code
        )
        UNION ALL
        SELECT d.id, NULL::VARCHAR AS advisor_id, d.lecturer_id, d.teaching_scope_id,
               d.subject_code, d.subject_name, d.filename, d.uploaded_by, d.summary,
               d.conclusion_table, d.text_preview, d.full_text, d.extraction_method,
               d.detected_language, d.source_type, d.storage_target, d.cloned_agent_name,
               d.structured_data, d.mongo_object_id, d.created_at,
               'lecturer'::VARCHAR AS document_scope
        FROM lecturer_documents d
        WHERE EXISTS (
            SELECT 1 FROM student_course_enrollments e
            WHERE e.student_id = %s AND e.advisor_id = d.teaching_scope_id
              AND e.course_code = d.subject_code
        )
        ORDER BY created_at DESC
        LIMIT 160
        """,
        (requester_student_id, requester_student_id),
    )
    return cur.fetchall(), None


def _fetch_all_documents_for_admin(cur) -> List[Dict[str, Any]]:
    """Return both admin/global PDF/Excel files and advisor subject PDF/Excel files for admin."""
    cur.execute(
        """
        SELECT id, filename, uploaded_by, summary, conclusion_table,
               text_preview, full_text, extraction_method, detected_language,
               source_type, storage_target, cloned_agent_name, structured_data, mongo_object_id, created_at,
               'admin' AS document_scope, NULL::VARCHAR AS advisor_id, NULL::VARCHAR AS subject_code,
               'Admin/global' AS subject_name
        FROM admin_documents
        ORDER BY created_at DESC
        LIMIT 80;
        """
    )
    admin_rows = cur.fetchall()

    cur.execute(
        """
        SELECT id, advisor_id, subject_code, subject_name, filename, uploaded_by,
               summary, conclusion_table, text_preview, full_text,
               extraction_method, detected_language, source_type, storage_target,
               cloned_agent_name, structured_data, mongo_object_id, created_at,
               'advisor' AS document_scope
        FROM advisor_documents
        ORDER BY created_at DESC
        LIMIT 120;
        """
    )
    advisor_rows = cur.fetchall()
    cur.execute(
        """
        SELECT id, filename, uploaded_by, summary, conclusion_table, text_preview, full_text,
               extraction_method, detected_language, source_type, storage_target,
               cloned_agent_name, structured_data, mongo_object_id, created_at,
               'lecturer' AS document_scope, NULL::VARCHAR AS advisor_id, subject_code,
               subject_name, lecturer_id, teaching_scope_id
        FROM lecturer_documents
        ORDER BY created_at DESC
        LIMIT 120
        """
    )
    lecturer_rows = cur.fetchall()
    rows = list(admin_rows) + list(advisor_rows) + list(lecturer_rows)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:160]



def _database_map(cur) -> Dict[str, Any]:
    """Return a compact admin-readable PostgreSQL map: tables, columns, and row counts."""
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
        """
    )
    table_rows = cur.fetchall()
    tables: List[Dict[str, Any]] = []
    for row in table_rows:
        table_name = row.get("table_name")
        cur.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position;
            """,
            (table_name,),
        )
        columns = cur.fetchall()
        # table_name comes from information_schema, so it is safe to quote.
        cur.execute(f'SELECT COUNT(*) AS count FROM "{table_name}";')
        count = cur.fetchone().get("count")
        tables.append({"table_name": table_name, "row_count": count, "columns": columns})
    return {
        "type": "postgres_database_map",
        "database": os.getenv("POSTGRES_DB", "university_db"),
        "tables": tables,
        "admin_note": "This is a read-only schema/data map. It helps the Admin AI understand where to pull information from.",
    }


def _fetch_campus_info(cur, keyword: str) -> Dict[str, Any]:
    """Search optional campus/facility data if the project has it.

    If the table has not been added yet, return a clear missing-data payload instead
    of letting the AI guess.
    """
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'campus_locations'
        ) AS exists;
        """
    )
    exists = bool(cur.fetchone().get("exists"))
    if not exists:
        return {
            "success": True,
            "data": {
                "type": "missing_campus_info_source",
                "rows": [],
                "message": "No campus_locations table exists yet. Add campus/building/facility data to answer location questions.",
                "needed_table": "campus_locations",
                "suggested_fields": ["name", "category", "building", "floor", "location", "opening_hours", "notes"],
            },
        }

    like = f"%{keyword}%" if keyword else "%"
    cur.execute(
        """
        SELECT name, category, building, floor, location, opening_hours, notes
        FROM campus_locations
        WHERE name ILIKE %s
           OR category ILIKE %s
           OR building ILIKE %s
           OR location ILIKE %s
           OR notes ILIKE %s
        ORDER BY name
        LIMIT 20;
        """,
        (like, like, like, like, like),
    )
    rows = cur.fetchall()
    return {"success": True, "data": {"type": "campus_info", "rows": rows, "keyword": keyword}}



def _semantic_data_agent_search(cur, keyword: str, user_role: str, requester_student_id: str | None, requester_advisor_id: str | None, requester_lecturer_id: str | None = None, preferred_source_type: str = "", limit: int = 12) -> Dict[str, Any]:
    """Search uploaded data-agent chunks by local embeddings.

    This complements keyword matching. It lets uploaded Excel rows/PDF chunks be
    pulled by meaning, column names, and table context while respecting role scope.
    """
    if not keyword:
        return {"success": True, "type": "neural_data_agent_search", "matches": [], "match_count": 0}
    preferred = (preferred_source_type or "").lower().strip()
    source_filter_sql = ""
    params: list[Any] = []
    if preferred in {"pdf", "excel"}:
        source_filter_sql = " AND a.source_type = %s"
        params.append(preferred)

    if user_role == "admin":
        sql = f"""
            SELECT c.*, a.agent_name, a.filename, a.subject_name, a.subject_code, a.owner_id,
                   a.storage_target, a.cloned_agent_name, a.table_schema, a.capabilities
            FROM ai_data_chunks c JOIN ai_data_agents a ON a.agent_key = c.agent_key
            WHERE TRUE {source_filter_sql}
            ORDER BY c.id DESC LIMIT 5000
        """
        cur.execute(sql, tuple(params))
    elif user_role == "advisor":
        sql = f"""
            SELECT c.*, a.agent_name, a.filename, a.subject_name, a.subject_code, a.owner_id,
                   a.storage_target, a.cloned_agent_name, a.table_schema, a.capabilities
            FROM ai_data_chunks c JOIN ai_data_agents a ON a.agent_key = c.agent_key
            WHERE a.document_scope = 'advisor' AND a.owner_id = %s {source_filter_sql}
            ORDER BY c.id DESC LIMIT 3500
        """
        cur.execute(sql, tuple([requester_advisor_id] + params))
    elif user_role == "lecturer":
        sql = f"""
            SELECT c.*, a.agent_name, a.filename, a.subject_name, a.subject_code, a.owner_id,
                   a.storage_target, a.cloned_agent_name, a.table_schema, a.capabilities
            FROM ai_data_chunks c JOIN ai_data_agents a ON a.agent_key = c.agent_key
            WHERE a.document_scope = 'lecturer' AND a.owner_id = %s {source_filter_sql}
            ORDER BY c.id DESC LIMIT 3500
        """
        cur.execute(sql, tuple([requester_lecturer_id] + params))
    elif user_role == "student":
        sql = f"""
            SELECT c.*, a.agent_name, a.filename, a.subject_name, a.subject_code, a.owner_id,
                   a.storage_target, a.cloned_agent_name, a.table_schema, a.capabilities
            FROM ai_data_chunks c JOIN ai_data_agents a ON a.agent_key = c.agent_key
            WHERE ((a.document_scope = 'advisor' AND EXISTS (
                SELECT 1 FROM student_course_enrollments e
                WHERE e.student_id = %s
                  AND e.advisor_id = a.owner_id
                  AND e.course_code = a.subject_code
              )) OR (a.document_scope = 'lecturer' AND EXISTS (
                SELECT 1 FROM lecturer_documents ld
                JOIN student_course_enrollments e
                  ON e.advisor_id = ld.teaching_scope_id AND e.course_code = ld.subject_code
                WHERE ld.id = a.document_id AND e.student_id = %s
              ))) {source_filter_sql}
            ORDER BY c.id DESC LIMIT 3500
        """
        cur.execute(sql, tuple([requester_student_id, requester_student_id] + params))
    else:
        return {"success": False, "error": "Unknown role for neural data-agent search."}

    rows = cur.fetchall()
    query_vectors: Dict[str, List[float]] = {}
    low = keyword.lower()
    token_boosts = set(re.findall(r"[a-zA-Z0-9\u0E00-\u0E7F]{3,}", low))
    scored: List[Dict[str, Any]] = []
    for row in rows:
        text = str(row.get("chunk_text") or "")
        capabilities = row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {}
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        provider = str((capabilities or {}).get("embedding_provider") or (metadata or {}).get("embedding_provider") or "local").lower()
        if provider not in query_vectors:
            query_vectors[provider] = embed_text(keyword, task="query", provider=provider)
        score = cosine_similarity(query_vectors[provider], row.get("embedding") or [])
        for token in token_boosts:
            if token in text.lower():
                score += 0.08
        if score <= 0.02:
            continue
        item = _row_created_iso(row)
        item["semantic_score"] = round(float(score), 4)
        item["chunk_text"] = text[:2500]
        item.pop("embedding", None)
        scored.append(item)
    scored.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
    return {
        "success": True,
        "type": "neural_data_agent_search",
        "query": keyword,
        "embedding_models": sorted(query_vectors.keys()) or [configured_embedding_provider()],
        "matches": scored[:limit],
        "match_count": len(scored),
    }


def _attach_neural_matches(cur, result: Dict[str, Any], keyword: str, user_role: str, requester_student_id: str | None, requester_advisor_id: str | None, preferred_source_type: str = "", requester_lecturer_id: str | None = None) -> Dict[str, Any]:
    try:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'ai_data_chunks'
            ) AS exists;
        """)
        if not bool(cur.fetchone().get("exists")):
            return result
        neural = _semantic_data_agent_search(cur, keyword, user_role, requester_student_id, requester_advisor_id, requester_lecturer_id, preferred_source_type, limit=12)
        if neural.get("success") and neural.get("matches"):
            result = dict(result)
            result["neural_data_agent"] = neural
            # Include the top matches as pseudo-documents for final-answer context.
            existing = result.get("data") if isinstance(result.get("data"), list) else []
            pseudo_docs = []
            seen = set()
            for m in neural.get("matches", [])[:8]:
                key = (m.get("agent_key"), m.get("id"))
                if key in seen:
                    continue
                seen.add(key)
                pseudo_docs.append({
                    "id": m.get("document_id"),
                    "filename": m.get("filename"),
                    "source_type": m.get("source_type"),
                    "storage_target": m.get("storage_target"),
                    "cloned_agent_name": m.get("cloned_agent_name"),
                    "subject_name": m.get("subject_name"),
                    "summary": f"Neural data agent match from {m.get('agent_name')} (score {m.get('semantic_score')}).",
                    "text_excerpt": m.get("chunk_text"),
                    "structured_preview": {
                        "neural_agent_name": m.get("agent_name"),
                        "chunk_type": m.get("chunk_type"),
                        "sheet_name": m.get("sheet_name"),
                        "row_index": m.get("row_index"),
                        "page_number": m.get("page_number"),
                        "semantic_score": m.get("semantic_score"),
                        "metadata": m.get("metadata") or {},
                    },
                    "match_score": 100 + float(m.get("semantic_score") or 0),
                    "matched_terms": ["neural_data_agent"],
                })
            result["data"] = pseudo_docs + existing
            result["note"] = "neural_data_agent_matches_attached"
        return result
    except Exception as e:
        result = dict(result)
        result["neural_data_agent_warning"] = str(e)
        return result

def _select_exact_document(rows: List[Dict[str, Any]], arguments: Dict[str, Any], default_scope: str = "") -> Dict[str, Any]:
    """Return a single exact document selected by the workspace, not a fuzzy match."""
    requested_id = arguments.get("document_id")
    requested_scope = str(arguments.get("document_scope") or "").lower().strip()
    try:
        requested_id_int = int(requested_id)
    except (TypeError, ValueError):
        return {"success": False, "error": "A valid document id is required for document_by_id."}

    matched: List[Dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        try:
            row_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        row_scope = str(row.get("document_scope") or default_scope or "admin").lower().strip()
        if row_id != requested_id_int:
            continue
        if requested_scope and row_scope != requested_scope:
            continue
        row["document_scope"] = row_scope
        row = _row_created_iso(row)
        terms = _extract_search_terms(str(arguments.get("keyword") or ""))
        full_text = str(row.get("full_text") or "")
        row["text_excerpt"] = _build_relevant_text_excerpt(full_text, terms, max_total=30000)
        if not row["text_excerpt"]:
            row["text_excerpt"] = str(row.get("text_preview") or "")[:30000]
        row["match_score"] = 9999
        row["matched_terms"] = ["pinned_document_context"]
        matched.append(row)
        break

    if not matched:
        return {
            "success": True,
            "operation": "document_by_id",
            "note": "pinned_document_not_found_or_not_allowed",
            "data": [],
        }
    return {
        "success": True,
        "operation": "document_by_id",
        "note": "exact_workspace_document",
        "data": matched,
    }



def _academic_dataset_overview(cur) -> Dict[str, Any]:
    """Return aggregate-only facts from V29 normalized academic tables."""
    cur.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM student_profiles) AS student_count,
          (SELECT COUNT(*) FROM advisor_profiles) AS advisor_count,
          (SELECT COUNT(*) FROM university_program_catalog) AS program_count,
          (SELECT COUNT(*) FROM course_catalog) AS course_count,
          (SELECT COUNT(*) FROM student_course_enrollments) AS enrollment_count,
          (SELECT COUNT(*) FROM student_assessment_results) AS assessment_count,
          (SELECT COUNT(*) FROM student_attendance_summaries) AS attendance_summary_count
        """
    )
    totals = cur.fetchone() or {}
    cur.execute(
        """
        SELECT program_name, COUNT(*) AS student_count, ROUND(AVG(gpa), 2) AS average_gpa
        FROM student_profiles
        GROUP BY program_name
        ORDER BY student_count DESC, program_name
        LIMIT 20
        """
    )
    programs = cur.fetchall()
    cur.execute(
        """
        SELECT risk_level, COUNT(*) AS student_count
        FROM student_profiles
        GROUP BY risk_level
        ORDER BY student_count DESC, risk_level
        """
    )
    risk = cur.fetchall()
    cur.execute("SELECT dataset_key, data_origin, student_count, advisor_count, course_count, enrollment_count, assessment_count, notice, updated_at FROM demo_dataset_metadata ORDER BY updated_at DESC LIMIT 5")
    provenance = cur.fetchall()
    return {
        "success": True,
        "operation": "academic_overview",
        "data": {
            "type": "academic_overview",
            "totals": totals,
            "programs": programs,
            "risk_summary": risk,
            "dataset_provenance": provenance,
        },
        "source": "PostgreSQL normalized academic tables",
    }


def _course_catalog_search(cur, keyword: str, limit: int = 50) -> Dict[str, Any]:
    keyword = (keyword or "").strip()
    if keyword:
        like = f"%{keyword}%"
        cur.execute(
            """
            SELECT course_code, course_name, program_code, program_name, credits, course_level
            FROM course_catalog
            WHERE course_code ILIKE %s OR course_name ILIKE %s OR program_name ILIKE %s
            ORDER BY course_code
            LIMIT %s
            """,
            (like, like, like, max(1, min(int(limit), 100))),
        )
    else:
        cur.execute(
            """
            SELECT course_code, course_name, program_code, program_name, credits, course_level
            FROM course_catalog
            ORDER BY course_code
            LIMIT %s
            """,
            (max(1, min(int(limit), 100)),),
        )
    return {
        "success": True,
        "operation": "course_catalog",
        "data": {"type": "course_catalog", "courses": cur.fetchall(), "keyword": keyword},
        "source": "PostgreSQL course catalog",
    }


def _normalized_class_text(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _match_advisor_course(
    assignments: List[Dict[str, Any]],
    original_question: str,
    course_query: str,
) -> Dict[str, Any] | None:
    """Match only within the signed advisor's assigned course list."""
    question = _normalized_class_text(original_question)
    hint = _normalized_class_text(course_query)
    for row in assignments:
        code = _normalized_class_text(row.get("subject_code"))
        name = _normalized_class_text(row.get("subject_name"))
        if (code and re.search(rf"\b{re.escape(code)}\b", question)) or (
            name and re.search(rf"\b{re.escape(name)}\b", question)
        ):
            return row
    if not hint:
        return None
    hint_tokens = set(hint.split())
    best: tuple[float, Dict[str, Any] | None] = (0.0, None)
    for row in assignments:
        code = _normalized_class_text(row.get("subject_code"))
        name_tokens = set(_normalized_class_text(row.get("subject_name")).split())
        score = 1.0 if hint == code else (
            len(hint_tokens & name_tokens) / max(1, len(hint_tokens | name_tokens))
        )
        if score > best[0]:
            best = (score, row)
    return best[1] if best[0] >= 0.5 else None


def _advisor_classroom(
    cur,
    arguments: Dict[str, Any],
    user_role: str,
    requester_advisor_id: str | None,
) -> Dict[str, Any]:
    """Return only students/facts linked to the signed advisor and same course."""
    role = (user_role or "").lower()
    advisor_id = str(requester_advisor_id or "").upper().strip()
    if role not in {"advisor", "lecturer"} or not advisor_id:
        return {"success": False, "error": "A signed Advisor or Lecturer teaching identity is required for classroom queries."}

    cur.execute(
        """
        SELECT DISTINCT advisor_id, course_code AS subject_code, course_name AS subject_name
        FROM student_course_enrollments
        WHERE advisor_id = %s
        ORDER BY subject_name, subject_code
        """,
        (advisor_id,),
    )
    assignments = cur.fetchall()
    original_question = str(arguments.get("original_question") or "")
    course_query = str(arguments.get("course_query") or "")
    matched_course = _match_advisor_course(assignments, original_question, course_query)
    if course_query and not matched_course:
        return {
            "success": True,
            "operation": "advisor_classroom",
            "data": {
                "type": "advisor_classroom",
                "status": "course_not_assigned",
                "advisor_id": advisor_id,
                "requested_course": course_query,
                "assigned_courses": assignments,
                "rows": [],
                "student_count": 0,
            },
            "source": "PostgreSQL signed-advisor classroom scope",
        }

    selected_codes = (
        [str(matched_course.get("subject_code"))]
        if matched_course
        else [str(row.get("subject_code")) for row in assignments]
    )
    student_ids = [
        str(value).upper().strip()
        for value in (arguments.get("student_ids") or [])
        if re.fullmatch(r"S\d{3,6}", str(value).upper().strip())
    ]
    where = ["e.advisor_id = %s", "e.course_code = ANY(%s)"]
    params: List[Any] = [advisor_id, selected_codes]
    if student_ids:
        where.append("e.student_id = ANY(%s)")
        params.append(student_ids)

    cur.execute(
        f"""
        SELECT e.student_id,
               p.full_name,
               e.course_code,
               e.course_name,
               e.term_code,
               e.grade,
               e.score,
               COALESCE(a.attendance_rate, e.attendance_rate) AS attendance_rate,
               a.classes_attended,
               a.classes_scheduled,
               e.enrollment_status
        FROM (
            SELECT DISTINCT ON (student_id, advisor_id, course_code)
                   student_id, advisor_id, course_code, course_name, term_code,
                   grade, score, attendance_rate, enrollment_status
            FROM student_course_enrollments
            ORDER BY student_id, advisor_id, course_code, term_code DESC
        ) e
        JOIN student_profiles p ON p.student_id = e.student_id
        LEFT JOIN LATERAL (
            SELECT attendance_rate, classes_attended, classes_scheduled
            FROM student_attendance_summaries
            WHERE student_id = e.student_id
              AND advisor_id = e.advisor_id
              AND course_code = e.course_code
            ORDER BY term_code DESC
            LIMIT 1
        ) a ON TRUE
        WHERE {' AND '.join(where)}
        ORDER BY e.course_name, e.student_id
        """,
        tuple(params),
    )
    rows = cur.fetchall()

    requested_metrics = {
        str(value)
        for value in (arguments.get("requested_metrics") or ["grade"])
    }
    if "assessments" in requested_metrics and rows:
        cur.execute(
            """
            SELECT student_id, course_code, term_code, assessment_type,
                   weight_percent, score
            FROM student_assessment_results
            WHERE advisor_id = %s
              AND course_code = ANY(%s)
              AND (%s = FALSE OR student_id = ANY(%s))
            ORDER BY student_id, course_code, term_code DESC, assessment_type
            """,
            (advisor_id, selected_codes, bool(student_ids), student_ids or [""]),
        )
        assessment_map: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        for assessment in cur.fetchall():
            key = (str(assessment.get("student_id")), str(assessment.get("course_code")))
            assessment_map.setdefault(key, []).append(assessment)
        for row in rows:
            row["assessments"] = assessment_map.get(
                (str(row.get("student_id")), str(row.get("course_code"))),
                [],
            )

    operation = str(arguments.get("operation") or "class_records")
    direction = "asc" if str(arguments.get("direction") or "desc") == "asc" else "desc"
    try:
        top_n = max(1, min(int(arguments.get("top_n") or 20), 100))
    except (TypeError, ValueError):
        top_n = 20
    distinct_students = len({str(row.get("student_id")) for row in rows})
    status = "ok"
    if student_ids and not rows:
        status = "student_not_in_advisor_class"
    elif not rows:
        status = "no_students"

    data: Dict[str, Any] = {
        "type": "advisor_classroom",
        "status": status,
        "advisor_id": advisor_id,
        "operation": operation,
        "course": matched_course,
        "courses": [matched_course] if matched_course else assignments,
        "requested_course": course_query,
        "requested_student_ids": student_ids,
        "requested_metrics": sorted(requested_metrics),
        "student_count": distinct_students,
        "rows": rows,
        "scope": "signed_lecturer_same_course_only" if role == "lecturer" else "signed_advisor_same_course_only",
        "requester_role": role,
    }

    if operation == "class_list":
        counts: Dict[str, int] = {}
        for row in rows:
            code = str(row.get("course_code"))
            counts[code] = counts.get(code, 0) + 1
        data["classes"] = [
            {**course, "student_count": counts.get(str(course.get("subject_code")), 0)}
            for course in assignments
        ]
        data["rows"] = []
    elif operation == "class_summary":
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            code = str(row.get("course_code"))
            bucket = grouped.setdefault(code, {
                "course_code": code,
                "course_name": row.get("course_name"),
                "student_ids": set(),
                "scores": [],
                "attendance": [],
            })
            bucket["student_ids"].add(str(row.get("student_id")))
            try:
                bucket["scores"].append(float(row.get("score")))
            except (TypeError, ValueError):
                pass
            try:
                bucket["attendance"].append(float(row.get("attendance_rate")))
            except (TypeError, ValueError):
                pass
        data["summaries"] = [
            {
                "course_code": bucket["course_code"],
                "course_name": bucket["course_name"],
                "student_count": len(bucket["student_ids"]),
                "recorded_score_count": len(bucket["scores"]),
                "average_score": round(sum(bucket["scores"]) / len(bucket["scores"]), 2) if bucket["scores"] else None,
                "average_attendance": round(sum(bucket["attendance"]) / len(bucket["attendance"]), 2) if bucket["attendance"] else None,
            }
            for bucket in grouped.values()
        ]
        data["rows"] = []
    elif operation == "class_records" and any(
        term in _normalized_class_text(original_question)
        for term in ("rank", "top", "bottom", "highest", "lowest", "best", "worst")
    ):
        data["rows"] = sorted(
            rows,
            key=lambda row: (
                row.get("score") is None,
                float(row.get("score") or 0) * (-1 if direction == "desc" else 1),
                str(row.get("student_id") or ""),
            ),
        )[:top_n]
    else:
        data["rows"] = rows[:top_n] if operation in {"class_roster", "class_records"} else rows

    return {
        "success": True,
        "operation": "advisor_classroom",
        "data": data,
        "source": "PostgreSQL signed-advisor classroom scope",
    }


def _academic_student_profile(
    cur,
    requested_student_id: str | None,
    user_role: str,
    requester_student_id: str | None,
    requester_advisor_id: str | None,
    requested_sections: List[str] | None = None,
) -> Dict[str, Any]:
    """Read normalized academic data without widening Student/Advisor permissions."""
    role = (user_role or "").lower()
    student_id = str(requested_student_id or "").upper().strip()
    if role == "student":
        student_id = str(requester_student_id or "").upper().strip()
    if not student_id:
        return {"success": False, "error": "A student ID is required."}

    if role in {"advisor", "lecturer"}:
        if not requester_advisor_id:
            return {"success": False, "error": "Advisor identity is required."}
        cur.execute(
            """
            SELECT 1 FROM student_course_enrollments
            WHERE student_id = %s AND advisor_id = %s
            LIMIT 1
            """,
            (student_id, requester_advisor_id),
        )
        if not cur.fetchone():
            return {"success": False, "error": "Advisors can view only students enrolled in their assigned courses."}

    if role == "admin":
        cur.execute("SELECT * FROM student_profiles WHERE student_id = %s", (student_id,))
    elif role == "student":
        cur.execute(
            """
            SELECT student_id, full_name, thai_name, program_code, program_name, faculty, year_level,
                   entry_year, expected_graduation_year, academic_status, gpa, credits_earned,
                   credits_required, attendance_rate, risk_level, scholarship_status, campus
            FROM student_profiles WHERE student_id = %s
            """,
            (student_id,),
        )
    else:
        # A fallback advisor profile exposes identity only. Every actual
        # academic fact below is still filtered by this signed advisor.
        cur.execute(
            """
            SELECT student_id, full_name
            FROM student_profiles WHERE student_id = %s
            """,
            (student_id,),
        )
    profile = cur.fetchone()
    if not profile:
        return {
            "success": True,
            "operation": "student_academic_profile",
            "data": {
                "type": "student_academic_profile",
                "student_id": student_id,
                "profile": None,
            },
            "note": "student_not_found",
        }

    allowed_sections = {
        "admin": {"profile", "enrollments", "assessments", "attendance", "financial_accounts", "support_cases", "scholarship_awards"},
        "advisor": {"enrollments", "assessments", "attendance"},
        "student": {"profile", "enrollments", "assessments", "attendance", "financial_accounts", "scholarship_awards"},
    }.get(role, set())
    requested = {
        str(value).strip()
        for value in (requested_sections or [])
        if str(value).strip()
    }
    sections = (requested & allowed_sections) if requested else set(allowed_sections)
    sections.add("profile")

    data: Dict[str, Any] = {
        "type": "student_academic_profile",
        "student_id": student_id,
        "profile": profile,
    }

    if "enrollments" in sections:
        enrollment_sql = """
            SELECT student_id, course_code, course_name, term_code, advisor_id, grade, score, credits,
                   attendance_rate, enrollment_status
            FROM student_course_enrollments WHERE student_id = %s
        """
        params: List[Any] = [student_id]
        if role in {"advisor", "lecturer"}:
            enrollment_sql += " AND advisor_id = %s"
            params.append(requester_advisor_id)
        enrollment_sql += " ORDER BY term_code DESC, course_code"
        cur.execute(enrollment_sql, tuple(params))
        data["enrollments"] = cur.fetchall()

    if "attendance" in sections:
        attendance_sql = """
            SELECT student_id, course_code, term_code, advisor_id, attendance_rate, classes_attended, classes_scheduled
            FROM student_attendance_summaries WHERE student_id = %s
        """
        params = [student_id]
        if role in {"advisor", "lecturer"}:
            attendance_sql += " AND advisor_id = %s"
            params.append(requester_advisor_id)
        attendance_sql += " ORDER BY term_code DESC, course_code"
        cur.execute(attendance_sql, tuple(params))
        data["attendance"] = cur.fetchall()

    if "assessments" in sections:
        assessment_sql = """
            SELECT student_id, course_code, term_code, assessment_type, weight_percent, score, advisor_id
            FROM student_assessment_results WHERE student_id = %s
        """
        params = [student_id]
        if role in {"advisor", "lecturer"}:
            assessment_sql += " AND advisor_id = %s"
            params.append(requester_advisor_id)
        assessment_sql += " ORDER BY term_code DESC, course_code, assessment_type"
        cur.execute(assessment_sql, tuple(params))
        data["assessments"] = cur.fetchall()

    if "financial_accounts" in sections:
        cur.execute("SELECT student_id, term_code, tuition_due, amount_paid, balance_due, payment_status FROM student_financial_accounts WHERE student_id = %s ORDER BY term_code DESC", (student_id,))
        data["financial_accounts"] = cur.fetchall()
    if "support_cases" in sections:
        cur.execute("SELECT case_type, priority, status, assigned_advisor_id, summary, created_at FROM student_support_cases WHERE student_id = %s ORDER BY created_at DESC", (student_id,))
        data["support_cases"] = cur.fetchall()
    if "scholarship_awards" in sections:
        cur.execute("SELECT scholarship_name, term_code, amount, status FROM student_scholarship_awards WHERE student_id = %s ORDER BY term_code DESC", (student_id,))
        data["scholarship_awards"] = cur.fetchall()
    return {"success": True, "operation": "student_academic_profile", "data": data, "source": "PostgreSQL normalized academic tables"}


def _academic_analytics(
    cur,
    arguments: Dict[str, Any],
    user_role: str,
    requester_student_id: str | None,
    requester_advisor_id: str | None,
) -> Dict[str, Any]:
    """Execute an allowlisted group/aggregate query inside the signed role scope."""
    role = (user_role or "").lower()
    dimension = str(arguments.get("dimension") or "overall")
    measure = str(arguments.get("measure") or "student_count")
    direction = "asc" if str(arguments.get("direction") or "desc").lower() == "asc" else "desc"
    try:
        limit = max(1, min(int(arguments.get("top_n") or 20), 100))
    except (TypeError, ValueError):
        limit = 20
    requested_ids = [
        str(value).upper().strip()
        for value in (arguments.get("student_ids") or [])
        if re.fullmatch(r"S\d{3,6}", str(value).upper().strip())
    ]

    if measure == "risk_level":
        where = ["COALESCE(LOWER(p.risk_level), '') NOT IN ('', 'low', 'none')"]
        params: List[Any] = []
        if role == "student":
            if not requester_student_id:
                return {"success": False, "error": "Student analytics require a signed student identity."}
            where.append("p.student_id = %s")
            params.append(requester_student_id)
        elif role in {"advisor", "lecturer"}:
            if not requester_advisor_id:
                return {"success": False, "error": "Advisor analytics require a signed advisor identity."}
            where.append(
                "EXISTS (SELECT 1 FROM student_course_enrollments scoped "
                "WHERE scoped.student_id = p.student_id AND scoped.advisor_id = %s)"
            )
            params.append(requester_advisor_id)
        if requested_ids:
            where.append("p.student_id = ANY(%s)")
            params.append(requested_ids)
        include_balance = bool(arguments.get("include_balance")) and role in {"admin", "student"}
        balance_sql = (
            "(SELECT SUM(f.balance_due) FROM student_financial_accounts f WHERE f.student_id = p.student_id)"
            if include_balance else "NULL::numeric"
        )
        cur.execute(
            f"""
            SELECT p.student_id, p.full_name, p.program_name, p.risk_level,
                   p.academic_status, p.attendance_rate, {balance_sql} AS balance_due
            FROM student_profiles p
            WHERE {' AND '.join(where)}
            ORDER BY
                CASE LOWER(p.risk_level)
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END,
                p.attendance_rate ASC NULLS LAST,
                p.student_id
            LIMIT %s
            """,
            tuple(params + [limit]),
        )
        rows = cur.fetchall()
        return {
            "success": True,
            "operation": "academic_analytics",
            "data": {
                "type": "student_risk_records",
                "measure": "risk_level",
                "records": rows,
                "count": len(rows),
                "include_balance": include_balance,
                "denied_sections": arguments.get("denied_sections") or [],
                "role_scope": role,
            },
            "source": "PostgreSQL normalized academic analytics",
        }

    if measure == "score_change":
        where = ["e.score IS NOT NULL"]
        params: List[Any] = []
        if role == "student":
            if not requester_student_id:
                return {"success": False, "error": "Student analytics require a signed student identity."}
            where.append("e.student_id = %s")
            params.append(requester_student_id)
        elif role in {"advisor", "lecturer"}:
            if not requester_advisor_id:
                return {"success": False, "error": "Advisor analytics require a signed advisor identity."}
            where.append("e.advisor_id = %s")
            params.append(requester_advisor_id)
        if requested_ids:
            where.append("e.student_id = ANY(%s)")
            params.append(requested_ids)
        order_sql = "ASC" if direction == "asc" else "DESC"
        cur.execute(
            f"""
            WITH scoped AS (
                SELECT e.student_id, p.full_name, e.term_code,
                       AVG(e.score)::numeric AS term_score
                FROM student_course_enrollments e
                JOIN student_profiles p ON p.student_id = e.student_id
                WHERE {' AND '.join(where)}
                GROUP BY e.student_id, p.full_name, e.term_code
            ),
            bounds AS (
                SELECT MIN(term_code) AS first_term, MAX(term_code) AS last_term
                FROM scoped
            )
            SELECT s.student_id || ' — ' || s.full_name AS group_name,
                   ROUND((
                       MAX(s.term_score) FILTER (WHERE s.term_code = b.last_term)
                       - MAX(s.term_score) FILTER (WHERE s.term_code = b.first_term)
                   )::numeric, 2) AS value,
                   b.first_term,
                   b.last_term,
                   ROUND(MAX(s.term_score) FILTER (WHERE s.term_code = b.first_term), 2) AS first_value,
                   ROUND(MAX(s.term_score) FILTER (WHERE s.term_code = b.last_term), 2) AS last_value
            FROM scoped s
            CROSS JOIN bounds b
            GROUP BY s.student_id, s.full_name, b.first_term, b.last_term
            HAVING b.first_term <> b.last_term
               AND COUNT(DISTINCT s.term_code) >= 2
            ORDER BY value {order_sql} NULLS LAST, group_name
            LIMIT %s
            """,
            tuple(params + [limit]),
        )
        rows = cur.fetchall()
        limitation = None
        if not rows:
            limitation = {
                "reason": "insufficient_repeated_term_history",
                "missing_data": ["at least two stored score terms for the same student"],
                "available_alternative": "current course scores, attendance, GPA, and academic risk",
            }
        return {
            "success": True,
            "operation": "academic_analytics",
            "data": {
                "type": "group_analytics",
                "source": "postgres_normalized_academic",
                "dimension": "student",
                "measure": "score_change",
                "metric_label": "Average score change",
                "direction": direction,
                "groups": [
                    {
                        "group": row.get("group_name"),
                        "value": row.get("value"),
                        "student_count": 1,
                        "first_term": row.get("first_term"),
                        "last_term": row.get("last_term"),
                        "first_value": row.get("first_value"),
                        "last_value": row.get("last_value"),
                    }
                    for row in rows
                ],
                "group_count": len(rows),
                "role_scope": role,
                "limitation": limitation,
            },
            "source": "PostgreSQL normalized academic analytics",
        }

    source_alias = "e"
    source_sql = "student_course_enrollments e JOIN student_profiles p ON p.student_id = e.student_id"
    dimension_map = {
        "course": "e.course_code || ' — ' || e.course_name",
        "term": "e.term_code",
        "program": "p.program_name",
        "year_level": "p.year_level::text",
        "student": "e.student_id || ' — ' || p.full_name",
        "overall": "'Overall'",
    }
    value_sql = "COUNT(DISTINCT e.student_id)::numeric"
    label = "Student count"

    if measure in {"average_score", "pass_rate"}:
        if measure == "average_score":
            value_sql = "ROUND(AVG(e.score)::numeric, 2)"
            label = "Average final score"
        else:
            value_sql = "ROUND((AVG(CASE WHEN e.score >= 60 THEN 1.0 ELSE 0.0 END) * 100)::numeric, 2)"
            label = "Pass rate (%)"
    elif measure == "attendance_rate":
        source_alias = "a"
        source_sql = "student_attendance_summaries a JOIN student_profiles p ON p.student_id = a.student_id"
        dimension_map = {
            "course": "a.course_code",
            "term": "a.term_code",
            "program": "p.program_name",
            "year_level": "p.year_level::text",
            "student": "a.student_id || ' — ' || p.full_name",
            "overall": "'Overall'",
        }
        value_sql = "ROUND(AVG(a.attendance_rate)::numeric, 2)"
        label = "Average attendance (%)"
    elif measure == "average_gpa":
        source_alias = "p"
        source_sql = "student_profiles p"
        dimension_map = {
            "program": "p.program_name",
            "year_level": "p.year_level::text",
            "overall": "'Overall'",
        }
        value_sql = "ROUND(AVG(p.gpa)::numeric, 3)"
        label = "Average GPA"
    elif measure == "balance_due":
        source_alias = "f"
        source_sql = "student_financial_accounts f JOIN student_profiles p ON p.student_id = f.student_id"
        dimension_map = {
            "term": "f.term_code",
            "program": "p.program_name",
            "year_level": "p.year_level::text",
            "overall": "'Overall'",
        }
        value_sql = "ROUND(AVG(f.balance_due)::numeric, 2)"
        label = "Average balance due"
    elif measure == "student_count":
        if dimension in {"program", "year_level", "overall"}:
            source_alias = "p"
            source_sql = "student_profiles p"
            dimension_map = {
                "program": "p.program_name",
                "year_level": "p.year_level::text",
                "overall": "'Overall'",
            }
            value_sql = "COUNT(DISTINCT p.student_id)::numeric"
        label = "Student count"
    else:
        return {"success": False, "error": "Unsupported academic analytics measure."}

    group_expr = dimension_map.get(dimension)
    if not group_expr:
        return {"success": False, "error": "Unsupported academic analytics dimension for this measure."}

    where: List[str] = []
    params: List[Any] = []
    if role == "student":
        if not requester_student_id:
            return {"success": False, "error": "Student analytics require a signed student identity."}
        where.append(f"{source_alias}.student_id = %s")
        params.append(requester_student_id)
    elif role in {"advisor", "lecturer"}:
        if not requester_advisor_id:
            return {"success": False, "error": "Advisor analytics require a signed advisor identity."}
        if source_alias in {"e", "a"}:
            where.append(f"{source_alias}.advisor_id = %s")
            params.append(requester_advisor_id)
        else:
            where.append(
                "EXISTS (SELECT 1 FROM student_course_enrollments scoped "
                "WHERE scoped.student_id = p.student_id AND scoped.advisor_id = %s)"
            )
            params.append(requester_advisor_id)
    if requested_ids:
        where.append(f"{source_alias}.student_id = ANY(%s)")
        params.append(requested_ids)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    order_sql = "ASC" if direction == "asc" else "DESC"
    group_by_sql = "" if dimension == "overall" else f"GROUP BY {group_expr}"
    cur.execute(
        f"""
        SELECT {group_expr} AS group_name,
               {value_sql} AS value,
               COUNT(DISTINCT {source_alias}.student_id) AS student_count
        FROM {source_sql}
        {where_sql}
        {group_by_sql}
        ORDER BY value {order_sql} NULLS LAST, group_name
        LIMIT %s
        """,
        tuple(params + [limit]),
    )
    rows = cur.fetchall()
    return {
        "success": True,
        "operation": "academic_analytics",
        "data": {
            "type": "group_analytics",
            "source": "postgres_normalized_academic",
            "dimension": dimension,
            "measure": measure,
            "metric_label": label,
            "direction": direction,
            "groups": [
                {
                    "group": row.get("group_name"),
                    "value": row.get("value"),
                    "student_count": row.get("student_count"),
                }
                for row in rows
            ],
            "group_count": len(rows),
            "role_scope": role,
            "pass_threshold": 60 if measure == "pass_rate" else None,
        },
        "source": "PostgreSQL normalized academic analytics",
    }


def _academic_student_profiles(
    cur,
    student_ids: List[str],
    user_role: str,
    requester_student_id: str | None,
    requester_advisor_id: str | None,
    requested_sections: List[str] | None = None,
) -> Dict[str, Any]:
    """Read several explicitly requested academic records without dropping IDs."""
    unique_ids: List[str] = []
    for value in student_ids or []:
        value = str(value).upper().strip()
        if re.fullmatch(r"S\d{3,6}", value) and value not in unique_ids:
            unique_ids.append(value)
    if not unique_ids:
        return {"success": False, "error": "At least one student ID is required."}
    records: List[Dict[str, Any]] = []
    for student_id in unique_ids[:50]:
        result = _academic_student_profile(
            cur,
            student_id,
            user_role,
            requester_student_id,
            requester_advisor_id,
            requested_sections,
        )
        if result.get("success") is False:
            records.append({
                "type": "student_academic_profile",
                "student_id": student_id,
                "profile": None,
                "unavailable_in_role_scope": True,
            })
        else:
            payload = result.get("data") if isinstance(result.get("data"), dict) else {}
            records.append(payload)
    return {
        "success": True,
        "operation": "student_academic_profiles",
        "data": {
            "type": "student_academic_profiles",
            "student_ids": unique_ids[:50],
            "records": records,
            "requested_count": len(unique_ids[:50]),
            "returned_count": len(records),
        },
        "source": "PostgreSQL normalized academic tables",
    }


def _academic_risk_summary(cur) -> Dict[str, Any]:
    cur.execute(
        """
        SELECT program_name, risk_level, COUNT(*) AS student_count,
               ROUND(AVG(gpa), 2) AS average_gpa,
               ROUND(AVG(attendance_rate), 2) AS average_attendance_rate
        FROM student_profiles
        GROUP BY program_name, risk_level
        ORDER BY risk_level, student_count DESC, program_name
        """
    )
    return {
        "success": True,
        "operation": "academic_risk_summary",
        "data": {"type": "academic_risk_summary", "rows": cur.fetchall()},
        "source": "PostgreSQL normalized academic tables",
    }

def postgres_university_tool(arguments: Dict[str, Any]) -> Dict[str, Any]:
    query_type = arguments.get("query_type", "programs")
    keyword = (arguments.get("keyword") or "").strip()
    operation = arguments.get("operation") or "search"
    user_role = (arguments.get("_user_role") or "").lower()
    requester_student_id = arguments.get("_requester_student_id")
    requester_advisor_id = arguments.get("_requester_advisor_id")
    requester_lecturer_id = arguments.get("_requester_lecturer_id")

    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            if query_type == "tables":
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name;
                    """
                )
                return {"success": True, "data": cur.fetchall()}

            if query_type == "database_map":
                if user_role != "admin":
                    return {"success": False, "error": "Only admin can inspect the database map."}
                return {"success": True, "data": _database_map(cur)}

            if query_type == "data_agents":
                preferred = (arguments.get("preferred_source_type") or "").lower().strip()
                limit = int(arguments.get("limit") or 20)
                return _semantic_data_agent_search(cur, keyword, user_role, requester_student_id, requester_advisor_id, requester_lecturer_id, preferred_source_type=preferred, limit=max(1, min(limit, 100)))

            if query_type == "campus_info":
                return _fetch_campus_info(cur, keyword)

            if query_type == "academic_overview":
                if user_role != "admin":
                    return {"success": False, "error": "Only admin can view the academic dataset overview."}
                return _academic_dataset_overview(cur)

            if query_type == "course_catalog":
                return _course_catalog_search(cur, keyword, int(arguments.get("limit") or 50))

            if query_type == "advisor_classroom":
                return _advisor_classroom(
                    cur,
                    arguments,
                    user_role,
                    requester_advisor_id,
                )

            if query_type == "student_academic_profile":
                student_ids = arguments.get("student_ids") if isinstance(arguments.get("student_ids"), list) else []
                if len(student_ids) > 1:
                    return _academic_student_profiles(
                        cur,
                        student_ids,
                        user_role,
                        requester_student_id,
                        requester_advisor_id,
                        arguments.get("requested_sections"),
                    )
                return _academic_student_profile(
                    cur,
                    arguments.get("student_id"),
                    user_role,
                    requester_student_id,
                    requester_advisor_id,
                    arguments.get("requested_sections"),
                )

            if query_type == "academic_analytics":
                return _academic_analytics(
                    cur,
                    arguments,
                    user_role,
                    requester_student_id,
                    requester_advisor_id,
                )

            if query_type == "academic_risk_summary":
                if user_role != "admin":
                    return {"success": False, "error": "Only admin can view academic risk summaries."}
                return _academic_risk_summary(cur)

            if query_type == "programs":
                if keyword:
                    like = f"%{keyword}%"
                    cur.execute(
                        """
                        SELECT program_name, faculty, admission_requirement, tuition_fee, language
                        FROM programs
                        WHERE program_name ILIKE %s
                           OR faculty ILIKE %s
                           OR admission_requirement ILIKE %s
                           OR language ILIKE %s
                        ORDER BY program_name
                        LIMIT 20;
                        """,
                        (like, like, like, like),
                    )
                else:
                    cur.execute(
                        """
                        SELECT program_name, faculty, admission_requirement, tuition_fee, language
                        FROM programs
                        ORDER BY program_name
                        LIMIT 20;
                        """
                    )
                rows = cur.fetchall()
                if not rows:
                    cur.execute(
                        """
                        SELECT program_name, faculty, admission_requirement, tuition_fee, language
                        FROM programs
                        ORDER BY program_name
                        LIMIT 20;
                        """
                    )
                    rows = cur.fetchall()
                return {"success": True, "data": rows}

            if query_type == "all_documents":
                # Admin universal knowledge base: admin/global PDF/Excel files + all advisor subject PDF/Excel files.
                if user_role != "admin":
                    return {"success": False, "error": "Only admin can access all document stores."}
                rows = _fetch_all_documents_for_admin(cur)
                preferred = (arguments.get("preferred_source_type") or "").lower().strip()
                if preferred in {"pdf", "excel"}:
                    rows = [r for r in rows if str(r.get("source_type") or "pdf").lower() == preferred] or rows
                if operation == "document_by_id":
                    result = _select_exact_document(rows, arguments)
                else:
                    result = _select_ranked(rows, keyword, "list_documents" if operation == "list_documents" else "document_search")
                    result = _attach_neural_matches(cur, result, keyword, user_role, requester_student_id, requester_advisor_id, preferred, requester_lecturer_id)
                result["document_scope"] = "admin_advisor_and_lecturer_documents"
                result["preferred_source_type"] = preferred or None
                return result

            if query_type == "documents":
                # Admin/global PDF knowledge base only.
                if user_role != "admin":
                    return {"success": False, "error": "Only admin can access admin/global document summaries."}
                rows = _fetch_admin_documents(cur)
                preferred = (arguments.get("preferred_source_type") or "").lower().strip()
                if preferred in {"pdf", "excel"}:
                    rows = [r for r in rows if str(r.get("source_type") or "pdf").lower() == preferred] or rows
                if operation == "document_by_id":
                    return _select_exact_document(rows, arguments, default_scope="admin")
                result = _select_ranked(rows, keyword, operation)
                return _attach_neural_matches(cur, result, keyword, user_role, requester_student_id, requester_advisor_id, preferred, requester_lecturer_id)

            if query_type == "advisor_documents":
                # Advisor-owned PDF knowledge base. Tool-level filtering is strict:
                # - student: only documents for subjects that student studies with that advisor
                # - advisor: only their own uploaded subject documents
                # - admin: may audit all advisor documents
                rows, error = _fetch_advisor_documents_for_role(cur, user_role, requester_student_id, requester_advisor_id)
                if error:
                    return {"success": False, "error": error}
                preferred = (arguments.get("preferred_source_type") or "").lower().strip()
                if preferred in {"pdf", "excel"}:
                    rows = [r for r in rows if str(r.get("source_type") or "pdf").lower() == preferred] or rows
                if operation == "document_by_id":
                    result = _select_exact_document(rows, arguments, default_scope="advisor")
                else:
                    result = _select_ranked(rows, keyword, "list_documents" if operation == "list_documents" else "document_search")
                    result = _attach_neural_matches(cur, result, keyword, user_role, requester_student_id, requester_advisor_id, preferred, requester_lecturer_id)
                result["document_scope"] = "advisor_subject_documents"
                result["preferred_source_type"] = preferred or None
                return result

            if query_type == "lecturer_documents":
                rows, error = _fetch_lecturer_documents_for_role(cur, user_role, requester_lecturer_id, requester_advisor_id)
                if error:
                    return {"success": False, "error": error}
                preferred = (arguments.get("preferred_source_type") or "").lower().strip()
                if preferred in {"pdf", "excel"}:
                    rows = [r for r in rows if str(r.get("source_type") or "pdf").lower() == preferred] or rows
                if operation == "document_by_id":
                    result = _select_exact_document(rows, arguments, default_scope="lecturer")
                else:
                    result = _select_ranked(rows, keyword, "list_documents" if operation == "list_documents" else "document_search")
                    result = _attach_neural_matches(cur, result, keyword, user_role, requester_student_id, requester_advisor_id, preferred, requester_lecturer_id)
                result["document_scope"] = "lecturer_course_documents"
                result["preferred_source_type"] = preferred or None
                return result

            if query_type == "course_documents":
                rows, error = _fetch_course_documents_for_student(cur, requester_student_id)
                if user_role != "student":
                    return {"success": False, "error": "Course materials are available only to signed students."}
                if error:
                    return {"success": False, "error": error}
                preferred = (arguments.get("preferred_source_type") or "").lower().strip()
                if preferred in {"pdf", "excel"}:
                    rows = [r for r in rows if str(r.get("source_type") or "pdf").lower() == preferred] or rows
                if operation == "document_by_id":
                    result = _select_exact_document(rows, arguments)
                else:
                    result = _select_ranked(rows, keyword, "list_documents" if operation == "list_documents" else "document_search")
                    result = _attach_neural_matches(cur, result, keyword, user_role, requester_student_id, requester_advisor_id, preferred, requester_lecturer_id)
                result["document_scope"] = "enrolled_course_documents"
                result["preferred_source_type"] = preferred or None
                return result

            if query_type == "student_subjects":
                if user_role != "student" or not requester_student_id:
                    return {"success": False, "error": "Student subjects require a signed student identity."}
                cur.execute(
                    """
                    SELECT ss.student_id, ss.advisor_id, ss.subject_code, ss.subject_name,
                           ss.term_code, ss.grade, ss.enrollment_status
                    FROM (
                        SELECT DISTINCT ON (student_id, advisor_id, course_code)
                               student_id, advisor_id, course_code AS subject_code,
                               course_name AS subject_name, term_code, grade,
                               enrollment_status
                        FROM student_course_enrollments
                        WHERE student_id = %s
                        ORDER BY student_id, advisor_id, course_code, term_code DESC
                    ) ss
                    ORDER BY ss.subject_name, ss.subject_code;
                    """,
                    (requester_student_id,),
                )
                all_subjects = cur.fetchall()
                course_query = str(arguments.get("course_query") or "").strip()
                selected = all_subjects
                if course_query:
                    normalized = _normalize_query_text(course_query)
                    selected = [
                        row for row in all_subjects
                        if normalized in _normalize_query_text(
                            f"{row.get('subject_code') or ''} {row.get('subject_name') or ''}"
                        )
                        or _similarity(normalized, _normalize_query_text(row.get("subject_name") or "")) >= 0.7
                    ]
                return {
                    "success": True,
                    "data": {
                        "type": "student_subjects",
                        "student_id": requester_student_id,
                        "operation": operation,
                        "course_query": course_query,
                        "subjects": selected,
                        "match_count": len(selected),
                        "total_count": len(all_subjects),
                        "scope": "signed_student_current_enrollments",
                    },
                    "source": "PostgreSQL signed current-enrollment authorization",
                }

            if query_type == "advisor_subjects":
                if user_role in {"advisor", "lecturer"}:
                    cur.execute(
                        """
                        SELECT advisor_id, subject_code, subject_name
                        FROM advisor_subjects
                        WHERE advisor_id = %s
                        ORDER BY subject_name;
                        """,
                        (requester_advisor_id,),
                    )
                elif user_role == "student":
                    cur.execute(
                        """
                        SELECT student_id, advisor_id, subject_code, subject_name
                        FROM (
                            SELECT DISTINCT ON (student_id, advisor_id, course_code)
                                   student_id, advisor_id, course_code AS subject_code,
                                   course_name AS subject_name, term_code
                            FROM student_course_enrollments
                            WHERE student_id = %s
                            ORDER BY student_id, advisor_id, course_code, term_code DESC
                        ) enrolled
                        ORDER BY subject_name;
                        """,
                        (requester_student_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT advisor_id, subject_code, subject_name
                        FROM advisor_subjects
                        ORDER BY advisor_id, subject_name;
                        """
                    )
                return {"success": True, "data": cur.fetchall()}

            if query_type == "query":
                sql = arguments.get("sql", "")
                if user_role != "admin":
                    return {"success": False, "error": "Only admin can run SQL select queries."}
                if not sql.strip().lower().startswith("select"):
                    return {"success": False, "error": "Only SELECT queries are allowed."}
                cur.execute(sql)
                return {"success": True, "data": cur.fetchall()}

            return {"success": False, "error": f"Unknown query_type: {query_type}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if conn is not None:
            conn.close()
