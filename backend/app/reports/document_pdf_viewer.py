import os
import uuid
from datetime import datetime
from typing import Any, Dict, List

from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors


PDF_VIEW_DIR = "generated_document_views"


def create_document_table_pdf(
    title: str,
    rows: List[Dict[str, Any]],
    columns: List[str] | None = None,
) -> Dict[str, str]:
    os.makedirs(PDF_VIEW_DIR, exist_ok=True)

    filename = f"document_view_{uuid.uuid4().hex[:8]}.pdf"
    filepath = os.path.join(PDF_VIEW_DIR, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=landscape(A4),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24,
    )

    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(title or "Document Table View", styles["Title"]))
    elements.append(Paragraph(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    if not rows:
        elements.append(Paragraph("No table data found for this document.", styles["Normal"]))
        doc.build(elements)

        return {
            "filename": filename,
            "path": filepath,
            "url": f"/document-views/{filename}",
        }

    if columns is None:
        columns = list(rows[0].keys())

    table_data = [columns]

    for row in rows:
        table_data.append([
            str(row.get(col, ""))[:300]
            for col in columns
        ])

    table = Table(table_data, repeatRows=1)

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
    ]))

    elements.append(table)
    doc.build(elements)

    return {
        "filename": filename,
        "path": filepath,
        "url": f"/document-views/{filename}",
    }