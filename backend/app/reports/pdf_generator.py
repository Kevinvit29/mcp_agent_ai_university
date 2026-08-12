from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
import os
import re
import uuid

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


REPORT_DIR = os.getenv("REPORT_DIR", "generated_reports")


def _safe_text(value: Any, max_len: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = str(value)
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _flatten_grades(row: Dict[str, Any]) -> str:
    grades = row.get("subject_grades") or row.get("grades") or []
    if not isinstance(grades, list):
        return _safe_text(grades, 180)
    pieces: List[str] = []
    for item in grades:
        if isinstance(item, dict):
            subject = item.get("subject") or item.get("subject_name") or "Subject"
            grade = item.get("grade") or item.get("score") or "-"
            pieces.append(f"{subject}: {grade}")
        else:
            pieces.append(str(item))
    return _safe_text("; ".join(pieces), 260)


def _guess_columns(rows: List[Dict[str, Any]], preferred: Optional[List[str]] = None) -> List[str]:
    if preferred:
        return [c for c in preferred if any(c in row for row in rows)]

    priority = [
        "student_id", "name", "program", "gpa", "academic_status", "email", "phone",
        "national_id", "passport_id", "address", "advisor_note", "subject_grades",
        "advisor_id", "department", "filename", "subject_name", "created_at",
    ]
    found = set()
    for row in rows:
        found.update(row.keys())
    cols = [c for c in priority if c in found]
    cols.extend(sorted(c for c in found if c not in cols and c != "_id"))
    return cols[:10]


def _summary_by_key(rows: List[Dict[str, Any]], key: str) -> List[List[str]]:
    counts: Dict[str, int] = {}
    for row in rows:
        value = _safe_text(row.get(key) or "Unknown", 80)
        counts[value] = counts.get(value, 0) + 1
    return [[key.replace("_", " ").title(), "Count"]] + [[k, str(v)] for k, v in sorted(counts.items())]


def create_pdf_report(
    title: str,
    rows: Iterable[Dict[str, Any]],
    columns: Optional[List[str]] = None,
    subtitle: Optional[str] = None,
) -> Dict[str, str]:
    """Create a PDF report from database rows and return file info.

    This function is intentionally deterministic. The AI should not write the report rows;
    it should only request this backend function after the database returns records.
    """
    os.makedirs(REPORT_DIR, exist_ok=True)
    clean_rows = [dict(row) for row in rows if isinstance(row, dict)]
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
    filepath = os.path.join(REPORT_DIR, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=landscape(A4),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24,
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(_safe_text(title, 180), styles["Title"]))
    if subtitle:
        story.append(Paragraph(_safe_text(subtitle, 240), styles["Normal"]))
    story.append(Paragraph(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    story.append(Paragraph(f"Total records: {len(clean_rows)}", styles["Normal"]))
    story.append(Spacer(1, 12))

    if clean_rows and "program" in clean_rows[0]:
        story.append(Paragraph("Summary by Program", styles["Heading2"]))
        summary_table = Table(_summary_by_key(clean_rows, "program"), repeatRows=1)
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 12))

    if not clean_rows:
        story.append(Paragraph("No records found.", styles["Normal"]))
        doc.build(story)
        return {"filename": filename, "path": filepath, "url": f"/reports/{filename}"}

    use_columns = _guess_columns(clean_rows, columns)
    header = [c.replace("_", " ").title() for c in use_columns]
    table_data: List[List[str]] = [header]

    for row in clean_rows:
        line = []
        for col in use_columns:
            if col == "subject_grades":
                line.append(_flatten_grades(row))
            else:
                line.append(_safe_text(row.get(col), 160))
        table_data.append(line)

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
    ]))
    story.append(Paragraph("Full Data", styles["Heading2"]))
    story.append(table)

    doc.build(story)
    return {"filename": filename, "path": filepath, "url": f"/reports/{filename}"}
