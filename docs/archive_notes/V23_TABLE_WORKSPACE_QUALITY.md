# Archived V23 — Table Workspace Quality

## Purpose

V23 makes stored PDF and spreadsheet data easier to inspect without mixing source data with AI-organized reading material.

## What changed

- The **Data table** tab now provides column-aware search, sort, pagination, row counts, and CSV export.
- The top workspace search searches every displayed source row/chunk. The table control chooses whether the search applies to all columns or one specific column.
- Each table clearly states whether it shows **original stored extraction**, **original PDF text chunks**, **original spreadsheet rows**, or **reading-guide evidence**.
- The Overview tab now explains, in plain language:
  - where the file is stored,
  - what the assistant may use to answer questions,
  - why the Reading guide is not the original source.
- Internal agent names and storage implementation details are removed from the workspace header.

## User rules

- **Overview** explains the source and what it can answer.
- **Data table** is the verification view: it contains stored rows/text.
- **Reading guide** is an organized study aid made from source material; it is not a replacement for source rows.
- **Export visible data** exports the currently filtered and sorted table rows only.

## Release checks

- Frontend production build must pass.
- Existing V15–V22 backend and document-grounding tests must pass.
