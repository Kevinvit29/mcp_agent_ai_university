# PDF → Excel Full Data Fix

This version fixes the problem where uploading a PDF with `Store in Excel` only showed the AI summary / conclusion table instead of the full extracted PDF data.

## What changed

### 1. PDF files now get a full extraction table
For every uploaded PDF, the backend now creates structured rows from all readable PDF text:

- Page number
- Chunk number
- Extracted text
- Word count
- Character count

This is stored in `structured_data` and also attached to `conclusion_table.full_extraction_table`.

### 2. The UI now separates two tables
The document modal now shows:

1. **AI explanation table** — summary, key points, explanation, why it matters
2. **Full stored extraction table** — all extracted PDF paragraphs/chunks

So `PDF_EXCEL_AGENT` is no longer limited to the summary.

### 3. MCP document search can see later PDF data
The MCP PostgreSQL document tool now builds relevant snippets from the full document text instead of only giving the AI the first part of the PDF. This helps answer questions from later pages.

### 4. Excel/CSV modal also shows full stored rows
For real Excel/CSV uploads, the modal can show sheet-by-sheet stored rows, not only the AI summary.

## Why this matters

Before:

```text
PDF stored in Excel → only summary/conclusion rows visible
PDF stored in MongoDB → full text available in Mongo payload
```

Now:

```text
PDF stored in Excel → AI summary + full extracted rows
PDF stored in MongoDB → AI summary + full extracted rows + full text
PDF stored in PostgreSQL → AI summary + full extracted rows + full text
```

## Rebuild

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up
```

Upload the PDF again after rebuilding. Old uploaded files will not automatically have the new full extraction table unless re-uploaded.
