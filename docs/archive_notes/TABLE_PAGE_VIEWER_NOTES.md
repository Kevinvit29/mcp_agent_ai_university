# Table Page Viewer Upgrade

This version changes the Knowledge Base "View table" behavior from a modal popup into a separate full-page table viewer.

## What changed

- `View table` now opens a dedicated full-page viewer instead of a small modal.
- Added a `Back to chat` button.
- Added tabs:
  - `AI explanation`
  - `Full stored data`
  - `Insights`
- Added a search box that filters the visible table rows.
- Large PDF/Excel tables are easier to read because the page can use the full browser width.
- The page includes file metadata: type, storage target, agent clone, extraction method, language, and status.
- Admin/advisor can still delete from the table page.
- User can click `Ask AI about this file` from the table page.

## Files changed

- `frontend/src/App.jsx`
- `frontend/src/style.css`

## Validation

- Frontend build passed with `npm --prefix frontend run build`.
- Backend Python compile passed.
- MCP server Python compile passed.
