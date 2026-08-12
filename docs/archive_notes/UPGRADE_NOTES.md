# Excel / PDF Knowledge-Base Upgrade

## What changed

### 1. Upload PDF, Excel, XLS, or CSV
- Admin and advisor upload panels now accept `.pdf`, `.xlsx`, `.xls`, and `.csv`.
- Students can still only view files they are allowed to access.
- Advisors must still select a subject before uploading, so student access stays filtered by enrolled subject.

### 2. Select where to store knowledge
The upload form now includes a storage target selector:
- `postgres` = store searchable metadata, summary, tables, full text, and structured rows in PostgreSQL.
- `mongodb` = store a full clone payload in MongoDB `knowledge_uploads`, while also keeping a PostgreSQL index row for fast listing/search.
- `excel` = store the spreadsheet as an Excel-agent knowledge source with structured rows/columns in PostgreSQL.

Each upload is tagged with:
- `source_type` (`pdf` or `excel`)
- `storage_target`
- `cloned_agent_name` such as `PDF_POSTGRES_AGENT`, `EXCEL_MONGODB_AGENT`, or `EXCEL_EXCEL_AGENT`
- `structured_data`
- `mongo_object_id` when MongoDB clone storage succeeds

### 3. Richer PDF extraction
The PDF processing prompt now stores more than a short conclusion. It extracts:
- main topic
- document type
- short summary
- detailed information
- section notes
- important dates
- key points
- requirements / conditions
- actions / next steps
- student takeaways
- recommended questions
- a larger searchable table with up to 40 rows

The table now has an extra `Detailed information` column so the chat has stronger context to answer from.

### 4. Structured Excel extraction
Excel/CSV uploads are parsed into structured knowledge:
- sheet names
- row count
- column count
- columns
- sample rows
- stored rows, capped to avoid extremely large payloads
- numeric summaries for numeric columns
- searchable text made from headers and row values

OpenAI is used to create a clear spreadsheet summary when available, with a fallback table if OpenAI is unavailable.

### 5. Faster source-specific routing
The MCP tools and agent planner now detect whether the user is asking about PDF files, Excel files, spreadsheets, CSV files, rows, columns, or sheets.

When the user asks about Excel, the system prefers Excel sources. When the user asks about PDF, it prefers PDF sources.

### 6. UI updates
The right knowledge panel now says PDF/Excel instead of PDF only. Cards show:
- file type
- storage target
- cloned agent name
- scope
- subject
- extraction method
- status

The modal table can show richer PDF information and spreadsheet insights.

## Validation performed
- Python compile check passed for `backend/app` and `mcp_server/app`.
- Frontend dependencies installed successfully.
- `npm --prefix frontend run build` completed successfully.


## OpenAI replacement

This package now uses OpenAI / ChatGPT API by default. See `OPENAI_REPLACEMENT_NOTES.md`.
